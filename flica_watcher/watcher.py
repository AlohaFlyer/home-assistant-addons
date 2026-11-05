"""FLICA Watcher: one kept-alive FLICA session, open time pot diff, HA over MQTT.

Login rule: never two login attempts in a row without a success in between.
A failed login, or anything unexpected, parks the watcher until re-armed from HA.
v0.2 is READ ONLY: rules match and log; nothing is ever submitted to FLICA.
"""
import json
import logging
import os
import random
import re
import threading
import time
from datetime import date, datetime, timedelta, timezone

import paho.mqtt.client as mqtt
import requests
from playwright.sync_api import sync_playwright

import rules as R
import web
from far import far_check, window as far_window
from pot import PAIRING_RE, LEG_FULL_RE, parse_schedule_desktop, parse_legs, parse_cm_schedule, inflight_at, crew_ids, with_ids, parse_alert_email, fit_tag, hours, parse_crew, pickup_diff, pickup_result, layout_still_parses, parse_schedule, row_date, BLOCK_HINTS, detail_url, parse_detail, soft_time, bcid, bcid_after, bcid_key, classify, header_fingerprint, is_pot_page, parse_pot, pot_links, visible_text
from store import Store
import tradeboard as TB
import swap as SW
import swapmap as SM
import grid as G
import submit as SUB
import inflt as IF
import charter as CH
import versions as VER
import pdfs as PDF

VERSION = "0.9.1"
BASE = "https://ha2.flica.net"
DATA = os.environ.get("FLICA_DATA", "/data")
STATE_FILE = f"{DATA}/state.json"
DB_FILE = f"{DATA}/watcher.db"
RULES_FILE = f"{DATA}/rules.json"
COOKIES = f"{DATA}/storage_state.json"
OPTS = json.load(open(f"{DATA}/options.json"))

logging.basicConfig(
    level=getattr(logging, OPTS.get("log_level", "info").upper()),
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("flica")

MOBILE_POT = "https://ha2.flica.net/full/mobileopentimepot.cgi?BCID=003.152&From=MainMenu"
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December"]
BACKOFF_MIN = [1, 2, 4, 8, 16, 30]  # minutes before each re-login on repeated needs_login; then park
HST = timezone(timedelta(hours=-10))

T = "flica_watcher"
AVAIL = f"{T}/status"


def now_iso():
    return datetime.now(timezone.utc).isoformat()


HST = timezone(timedelta(hours=-10))  # FLICA dates are HNL local; Hawaii has no DST


def local_now():
    """0.4.5: wall-clock time in Honolulu. The container runs UTC, so after 14:00 HST datetime.now()
    is already tomorrow (that pruned today's blocked day and skewed month rollover)."""
    return datetime.now(HST).replace(tzinfo=None)


# ---------------------------------------------------------------- state
DEFAULT_STATE = {"baseline": {}, "machine": "idle", "pot_urls": {}, "kills": [], "last_login_ok": None,
                 "fingerprints": {}, "relogin_streak": 0}
DB = Store(DB_FILE, legacy_json=STATE_FILE, default_state=DEFAULT_STATE)


def load_state():
    s = DB.load_state()
    for k, v in DEFAULT_STATE.items():
        s.setdefault(k, json.loads(json.dumps(v)))
    return s


def save_state(s):
    DB.save_state(s)


S = load_state()
WAKE = threading.Event()
FLAGS = {"hunt": False, "pause": False, "rearm": False, "full": False}
# Check frequency from the dashboard sliders (number entities); persisted in state.
# Each gap is randomized +-30 % around the setting so the checks never look machine-regular.
FREQ_LIMITS = {"normal_min": (1, 20), "hunt_s": (5, 90)}
JITTER = 0.3
CHECK_NOW_MIN_GAP_S = 10
RULES = {"list": [], "published": set()}
RULE_LOCK = threading.Lock()


# ---------------------------------------------------------------- rules file
def load_rules():
    if not os.path.exists(RULES_FILE):
        clean, _ = R.validate(R.EXAMPLE)
        write_rules(clean)
        log.info("rules.json created with the example SIN alert rule (alert only, dry run)")
        return clean
    try:
        clean, errs = R.validate(json.load(open(RULES_FILE)))
    except Exception as e:
        clean, errs = [], [f"rules.json unreadable: {e}"]
    if errs:
        log.warning("rules.json has errors, running with NO rules until fixed: %s", errs)
    return clean


def write_rules(lst):
    tmp = RULES_FILE + ".tmp"
    json.dump(lst, open(tmp, "w"), indent=2)
    os.replace(tmp, RULES_FILE)


def save_rules_from_page(data):
    clean, errs = R.validate(data)
    if errs:
        return errs
    with RULE_LOCK:
        write_rules(clean)
        RULES["list"] = clean
    if MQ:
        publish_rules(MQ)
    return []


# ---------------------------------------------------------------- mqtt
def mqtt_creds():
    tok = os.environ.get("SUPERVISOR_TOKEN")
    r = requests.get("http://supervisor/services/mqtt",
                     headers={"Authorization": f"Bearer {tok}"}, timeout=10)
    r.raise_for_status()
    return r.json()["data"]


def on_message(c, u, msg):
    if msg.topic == f"{T}/email/alert":
        email_alert(msg.payload.decode(errors="replace"))
        return
    if msg.topic == f"{T}/blocked/set":
        blocked_cmd(msg.payload.decode(errors="replace"))
        return
    if msg.topic == f"{T}/improved/set":
        improved_cmd(msg.payload.decode(errors="replace"))
        return
    if msg.topic == f"{T}/trade/set":
        trade_cmd(msg.payload.decode(errors="replace"))
        return
    if msg.topic == f"{T}/drop/set":
        drop_cmd(msg.payload.decode(errors="replace"))
        return
    if msg.topic == f"{T}/swap_mode/set":
        swap_mode_cmd(msg.payload.decode(errors="replace").strip())
        return
    if msg.topic == f"{T}/auto_swap/set":
        S["auto_swap"] = msg.payload.decode().strip().upper() == "ON"
        save_state(S)
        c.publish(f"{T}/auto_swap/state", "ON" if S["auto_swap"] else "OFF", retain=True)
        log.info("auto swap %s (dry run: nothing is ever submitted)", S["auto_swap"])
        return
    p = msg.payload.decode().strip().upper()
    if msg.topic == f"{T}/hunt/set":
        FLAGS["hunt"] = p == "ON"
        c.publish(f"{T}/hunt/state", "ON" if FLAGS["hunt"] else "OFF", retain=True)
        log.info("hunt mode %s", FLAGS["hunt"])
    elif msg.topic == f"{T}/pause/set":
        FLAGS["pause"] = p == "ON"
        c.publish(f"{T}/pause/state", "ON" if FLAGS["pause"] else "OFF", retain=True)
        log.info("pause %s", FLAGS["pause"])
    elif msg.topic == f"{T}/rearm/press":
        FLAGS["rearm"] = True
        log.info("re-arm pressed")
    elif msg.topic in (f"{T}/hunt/state", f"{T}/pause/state"):
        key = "hunt" if "hunt" in msg.topic else "pause"
        FLAGS[key] = p == "ON"
        return
    elif msg.topic == f"{T}/swap_map/press":
        FLAGS["swap_map"] = True  # 0.4.10: one read-only mapping pass on the next check
        log.info("swap map pressed: read-only mapping on the next check")
    elif msg.topic == f"{T}/pilot/set":
        pilot_cmd(msg.payload.decode(errors="replace"))
    elif msg.topic == f"{T}/charter_scan/press":
        CHARTER_WAKE.set()  # 0.7.0: scan CrewTrac now
        log.info("charter scan pressed")
    elif msg.topic == f"{T}/check_now/press":
        # Waking the loop runs a check right away (only when idle or hunting; paused/stopped ignore it).
        if time.time() - S.get("last_check_ts", 0) < CHECK_NOW_MIN_GAP_S:
            log.info("check now ignored: last check under %d s ago", CHECK_NOW_MIN_GAP_S)
            return
        log.info("check now pressed: full refresh")
        FLAGS["full"] = True  # 0.3.9: re-read schedule, own trips, pot details, pickups, tradeboard
    elif msg.topic in (f"{T}/freq/normal_min/set", f"{T}/freq/hunt_s/set"):
        key = msg.topic.split("/")[2]
        lo, hi = FREQ_LIMITS[key]
        try:
            v = int(round(float(p)))
        except ValueError:
            return
        S.setdefault("freq", {})[key] = max(lo, min(hi, v))
        save_state(S)
        c.publish(f"{T}/freq/{key}/state", str(S["freq"][key]), retain=True)
        log.info("frequency %s = %s", key, S["freq"][key])
    elif msg.topic.startswith(f"{T}/rule/") and msg.topic.endswith("/live/set"):
        rule_live_cmd(c, msg.topic.split("/")[2], p == "ON")
        return
    WAKE.set()


def swap_mode_cmd(want):
    """0.5.0: Test / Confirm / Live from the dashboard select. Only Test exists in this version:
    Confirm and Live are refused (logged, event) until the send path is written and Ryan turns it on."""
    want = next((m for m in SUB.MODES if m.lower() == want.lower()), None)
    if want is None:
        return
    if want != "Test" and not SUB.WRITES_IMPLEMENTED:
        log.info("swap mode %s refused: writes not implemented, staying in Test", want)
        pub("event/swap_mode_refused", {"wanted": want, "at": now_iso()}, retain=False)
        want = "Test"
    S["swap_mode"] = want
    save_state(S)
    pub("swap_mode/state", want)
    log.info("swap mode %s", want)


def rule_live_cmd(c, rid, want):
    with RULE_LOCK:
        rule = next((r for r in RULES["list"] if r["id"] == rid), None)
    if rule is None:
        return
    if want:
        ok, why = R.live_allowed(rule)
        if not ok:
            log.info("rule %s live refused: %s", rid, why)
            c.publish(f"{T}/rule/{rid}/live/state", "OFF", retain=True)
            c.publish(f"{T}/event/rule_refused", json.dumps({"rule_id": rid, "reason": why, "at": now_iso()}))
            return
    DB.set_live(rid, want)
    c.publish(f"{T}/rule/{rid}/live/state", "ON" if want else "OFF", retain=True)
    log.info("rule %s live=%s", rid, want)


DEV = {"identifiers": ["flica_watcher"], "name": "FLICA Watcher", "manufacturer": "Pako HI",
       "sw_version": VERSION}


def publish_rules(c):
    """One live switch per rule via MQTT discovery; removes switches of deleted rules."""
    with RULE_LOCK:
        lst = list(RULES["list"])
    flags = DB.live_flags()
    ids = {r["id"] for r in lst}
    for rid in RULES["published"] - ids:
        c.publish(f"homeassistant/switch/flica_watcher/rule_{rid}_live/config", "", retain=True)
        c.publish(f"{T}/rule/{rid}/live/state", "", retain=True)
        DB.drop_live(rid)
    for r in lst:
        cfg = {"availability_topic": AVAIL, "device": DEV, "name": f"Rule {r['name']} live",
               "unique_id": f"flica_rule_{r['id']}_live", "object_id": f"flica_rule_{r['id']}_live",
               "command_topic": f"{T}/rule/{r['id']}/live/set", "state_topic": f"{T}/rule/{r['id']}/live/state",
               "icon": "mdi:rocket-launch", "entity_category": "config"}
        c.publish(f"homeassistant/switch/flica_watcher/rule_{r['id']}_live/config", json.dumps(cfg), retain=True)
        live = flags.get(r["id"], False) and R.live_allowed(r)[0]
        c.publish(f"{T}/rule/{r['id']}/live/state", "ON" if live else "OFF", retain=True)
    RULES["published"] = ids
    active = [r for r in lst if r["enabled"]]
    c.publish(f"{T}/rules/state", json.dumps({
        "count": len(active),
        "rules": [{"id": r["id"], "name": r["name"], "mode": r["mode"], "live": flags.get(r["id"], False),
                   "created_at": r["created_at"]} for r in lst]}), retain=True)


def publish_blocked():
    """0.4.4: days Ryan tapped off on the schedule card (no pickups wanted). Past days drop off."""
    today = local_now().date().isoformat()
    S["blocked_days"] = sorted(d for d in set(S.get("blocked_days") or []) if d >= today)
    save_state(S)
    pub("blocked/state", {"count": len(S["blocked_days"]), "days": S["blocked_days"]})


def blocked_cmd(payload):
    """{"date": "2026-11-05"} toggles that day; {"date": ..., "on": true|false} sets it."""
    try:
        d = json.loads(payload)
        day = date.fromisoformat(str(d["date"])).isoformat()
    except (ValueError, KeyError, TypeError):
        log.info("blocked day ignored: %r", payload[:80])
        return
    days = set(S.get("blocked_days") or [])
    on = d.get("on", day not in days)
    (days.add if on else days.discard)(day)
    S["blocked_days"] = sorted(days)
    log.info("blocked day %s %s", day, "on" if on else "off")
    publish_blocked()
    publish_tradeboard()


def trade_cmd(payload):
    """0.4.9: {"key": "H3628|2026-11-06"} toggles a trip Ryan would trade away for a better one."""
    try:
        k = str(json.loads(payload)["key"])
        trip, start = k.split("|")
        date.fromisoformat(start)
    except (ValueError, KeyError, TypeError):
        log.info("trade mark ignored: %r", payload[:80])
        return
    keys = set(S.get("trade_away") or [])
    (keys.discard if k in keys else keys.add)(k)
    S["trade_away"] = sorted(keys)
    log.info("would trade %s: %s", k, k in keys)
    publish_trade()


def drop_cmd(payload):
    """0.6.0 (Ryan): {"key": "H3629|2026-11-14"} toggles a trip Ryan would DROP once the reserve grid is
    green on every day of it. Marking never files anything."""
    try:
        k = str(json.loads(payload)["key"])
        trip, start = k.split("|")
        date.fromisoformat(start)
    except (ValueError, KeyError, TypeError):
        log.info("drop mark ignored: %r", payload[:80])
        return
    keys = set(S.get("drop_away") or [])
    (keys.discard if k in keys else keys.add)(k)
    S["drop_away"] = sorted(keys)
    if k not in keys:
        (S.get("drop_ready") or {}).pop(k, None)
    log.info("would drop %s: %s", k, k in keys)
    publish_drop()


def publish_drop():
    today = local_now().date().isoformat()
    live = {f"{it['trip']}|{it['start']}" for it in _sched_items() if it["start"] > today}  # 0.6.1: a started trip cannot be dropped
    if _sched_items():
        S["drop_away"] = [k for k in S.get("drop_away") or [] if k in live]
    save_state(S)
    pub("drop/state", {"count": len(S.get("drop_away") or []), "keys": S.get("drop_away") or [],
                       "ready": S.get("drop_ready") or {}, "tests": (S.get("drop_tests") or [])[-20:]})


def drop_scan():
    """0.6.0 Test mode: for each 'would drop' trip, check NET RESERVES on every day of the trip. The first
    time all days are green the Watcher pushes event/drop_ready and composes the drop request (logged,
    never sent); a day turning red again re-arms the push. Live filing waits for the DROP page map."""
    marks = S.get("drop_away") or []
    if not marks:
        return
    grid = S.get("grid") or {}
    ready = S.setdefault("drop_ready", {})
    for k in marks:
        it = next((x for x in _sched_items() if f"{x['trip']}|{x['start']}" == k), None)
        if not it:
            continue
        days = [(date.fromisoformat(it["start"]) + timedelta(days=i)).isoformat()
                for i in range((date.fromisoformat(it["end"]) - date.fromisoformat(it["start"])).days + 1)]
        ok, bad = G.drop_allowed(grid, days)
        if not ok:
            if k in ready:
                log.info("drop %s: grid red again on %s", k, ", ".join(bad))
                ready.pop(k, None)
            continue
        if k in ready:
            continue
        b = sorted({bcid(u) for u in S.get("pot_urls", {}).values() if bcid(u)}, key=bcid_key)
        own = S.get("own_trips", {}).get(k) or {}
        rep_h = SUB.hours_until(f"{it['start']}T{(own.get('report') or '')[:5]}", local_now()) if own.get("report") else None
        rec = SUB.compose_drop(k, b[0] if b else None, rep_h, close_in_bcid=S.get("close_in_bcid"))
        rec.update({"key": k, "at": now_iso(), "days": days, "net": {d: (grid.get(d) or {}).get("net") for d in days},
                    "mode": S.get("swap_mode") or SUB.DEFAULT_MODE, "sent": False,
                    "hours_to_report": round(rep_h, 1) if rep_h is not None else None})
        ready[k] = rec["at"]
        tests = S.setdefault("drop_tests", [])
        tests.append(rec)
        del tests[:-20]
        log.info("DROP READY (not sent): %s, grid green on %s; form %s", k, ", ".join(days), rec["form"])
        pub("event/drop_ready", rec, retain=False)
    save_state(S)
    publish_drop()


def publish_trade():
    today = local_now().date().isoformat()
    live = {f"{it['trip']}|{it['start']}" for it in _sched_items() if it["start"] > today}  # 0.6.1: a started trip cannot be traded
    if _sched_items():  # a trip that is gone from the schedule (traded, dropped) or has started drops its mark
        S["trade_away"] = [k for k in S.get("trade_away") or [] if k in live]
    save_state(S)
    pub("trade/state", {"count": len(S.get("trade_away") or []), "keys": S.get("trade_away") or []})


def publish_finds():
    pub("finds", {"count": len(f := DB.recent_finds(50)), "finds": f})
    publish_pickers()


def publish_pickers():
    """0.4.18 (Ryan): every FO/RO seen taking a trip, with their average time in open time, fastest first."""
    rows = [{"emp": e, "name": v["name"], "pos": v["pos"], "n": v["n"], "avg_s": int(v["total_s"] / v["n"]) if v["n"] else None,
             "inflt_n": v.get("inflt_n", 0), "month_n": v.get("month_n", 0), "year_n": v.get("year_n", 0),
             "lays": v.get("lays", []), "last_lay": v.get("last_lay", ""),  # 0.7.6: Common Layover
             "min_s": v.get("min_s"),  # 0.8.2: Fastest Pickup Speed
             "last_at": v["last_at"]} for e, v in DB.picker_stats().items()]
    rows.sort(key=lambda r: (r["avg_s"] is None, r["avg_s"] or 0, r["name"]))
    pub("pickers", {"count": len(rows), "pickers": rows})


def discovery(c):
    dev = DEV
    base = {"availability_topic": AVAIL, "device": dev}
    ents = [
        ("sensor", "state", {"name": "State", "state_topic": f"{T}/state", "icon": "mdi:airplane-search",
                             "json_attributes_topic": f"{T}/state_attr"}),
        ("sensor", "last_check", {"name": "Last check", "state_topic": f"{T}/last_check",
                                  "device_class": "timestamp"}),
        ("sensor", "flica_fetches", {"name": "FLICA fetches", "state_topic": f"{T}/fetches", "value_template": "{{ value_json.total }}",
                                     "state_class": "total_increasing", "unit_of_measurement": "pages", "icon": "mdi:counter",
                                     "json_attributes_topic": f"{T}/fetches"}),
        ("sensor", "next_check", {"name": "Next check", "state_topic": f"{T}/next_check",
                                  "device_class": "timestamp", "icon": "mdi:timer-sand"}),
        ("sensor", "pot_count", {"name": "Pot count", "state_topic": f"{T}/pot/state",
                                 "value_template": "{{ value_json.count }}", "state_class": "measurement",
                                 "unit_of_measurement": "pairings",
                                 "json_attributes_topic": f"{T}/pot/state", "icon": "mdi:format-list-bulleted"}),
        ("sensor", "pickers", {"name": "Pickers", "state_topic": f"{T}/pickers",
                               "value_template": "{{ value_json.count }}",
                               "json_attributes_topic": f"{T}/pickers", "icon": "mdi:account-group"}),
        ("sensor", "reserve_grid", {"name": "Reserve grid", "state_topic": f"{T}/grid/state",
                                    "value_template": "{{ value_json.green }}",
                                    "json_attributes_topic": f"{T}/grid/state", "icon": "mdi:grid"}),
        ("sensor", "drop_away", {"name": "Would drop", "state_topic": f"{T}/drop/state",
                                 "value_template": "{{ value_json.count }}",
                                 "json_attributes_topic": f"{T}/drop/state", "icon": "mdi:tray-arrow-down"}),
        ("sensor", "trade_away", {"name": "Would trade", "state_topic": f"{T}/trade/state",
                                  "value_template": "{{ value_json.count }}",
                                  "json_attributes_topic": f"{T}/trade/state", "icon": "mdi:swap-horizontal-bold"}),
        ("sensor", "swap_ideas", {"name": "Swap ideas", "state_topic": f"{T}/swap/state",
                                  "value_template": "{{ value_json.count }}",
                                  "json_attributes_topic": f"{T}/swap/state", "icon": "mdi:swap-horizontal-circle"}),
        ("switch", "auto_swap", {"name": "Auto swap (dry run)", "command_topic": f"{T}/auto_swap/set",
                                 "state_topic": f"{T}/auto_swap/state", "icon": "mdi:robot"}),
        ("select", "swap_mode", {"name": "Swap mode", "command_topic": f"{T}/swap_mode/set",
                                 "state_topic": f"{T}/swap_mode/state", "options": list(SUB.MODES),
                                 "icon": "mdi:swap-horizontal-variant"}),
        ("sensor", "swap_tests", {"name": "Swap test requests", "state_topic": f"{T}/swap_tests",
                                  "value_template": "{{ value_json.count }}",
                                  "json_attributes_topic": f"{T}/swap_tests", "icon": "mdi:file-send-outline"}),
        ("sensor", "improved_pay", {"name": "Improved pay gross", "state_topic": f"{T}/improved_pay",
                                     "value_template": "{{ value_json.improved }}", "unit_of_measurement": "USD",
                                     "json_attributes_topic": f"{T}/improved_pay", "icon": "mdi:cash-plus"}),
        ("sensor", "schedule_versions", {"name": "Schedule versions", "state_topic": f"{T}/schedule_versions",
                                          "value_template": "{{ value_json.count }}",
                                          "json_attributes_topic": f"{T}/schedule_versions", "icon": "mdi:history"}),
        ("sensor", "own_trips", {"name": "Own trip times", "state_topic": f"{T}/own_trips",
                                 "value_template": "{{ value_json.count }}",
                                 "json_attributes_topic": f"{T}/own_trips", "icon": "mdi:clock-outline"}),
        ("sensor", "tradeboard", {"name": "Tradeboard pickups", "state_topic": f"{T}/tradeboard/state",
                                  "value_template": "{{ value_json.count }}",
                                  "json_attributes_topic": f"{T}/tradeboard/state",
                                  "icon": "mdi:swap-horizontal"}),
        ("sensor", "blocked_days", {"name": "Blocked days", "state_topic": f"{T}/blocked/state",
                                    "value_template": "{{ value_json.count }}",
                                    "json_attributes_topic": f"{T}/blocked/state",
                                    "icon": "mdi:calendar-remove"}),
        ("sensor", "finds", {"name": "Finds", "state_topic": f"{T}/finds",
                             "value_template": "{{ value_json.count }}",
                             "json_attributes_topic": f"{T}/finds", "icon": "mdi:history"}),
        ("sensor", "rules_active", {"name": "Rules active", "state_topic": f"{T}/rules/state",
                                    "value_template": "{{ value_json.count }}",
                                    "json_attributes_topic": f"{T}/rules/state", "icon": "mdi:filter-cog"}),
        ("sensor", "last_match", {"name": "Last match", "state_topic": f"{T}/last_match",
                                  "value_template": "{{ value_json.rule_id }}: {{ value_json.row.pairing }}",
                                  "json_attributes_topic": f"{T}/last_match", "icon": "mdi:bullseye-arrow"}),
        ("sensor", "last_new", {"name": "Last new pairing", "state_topic": f"{T}/last_new",
                                "value_template": "{{ value_json.pairing }}",
                                "json_attributes_topic": f"{T}/last_new", "icon": "mdi:new-box"}),
        ("sensor", "schedule", {"name": "Schedule", "state_topic": f"{T}/schedule",
                                "value_template": "{{ value_json.updated }}",
                                "json_attributes_topic": f"{T}/schedule", "icon": "mdi:calendar-account"}),
        ("binary_sensor", "session_ok", {"name": "Session OK", "state_topic": f"{T}/session",
                                         "device_class": "connectivity"}),
        ("switch", "hunt_mode", {"name": "Hunt mode", "command_topic": f"{T}/hunt/set",
                                 "state_topic": f"{T}/hunt/state", "icon": "mdi:target"}),
        ("switch", "pause", {"name": "Pause", "command_topic": f"{T}/pause/set",
                             "state_topic": f"{T}/pause/state", "icon": "mdi:pause-circle"}),
        ("button", "rearm", {"name": "Re-arm", "command_topic": f"{T}/rearm/press", "icon": "mdi:restart"}),
        ("sensor", "pilot_schedule", {"name": "Pilot schedule", "state_topic": f"{T}/pilot_schedule",
                                      "value_template": "{{ value_json.emp }}",
                                      "json_attributes_topic": f"{T}/pilot_schedule", "icon": "mdi:account-clock"}),
        ("sensor", "charters", {"name": "Charters", "state_topic": f"{T}/charters",
                                "value_template": "{{ value_json.count }}",
                                "json_attributes_topic": f"{T}/charters", "icon": "mdi:airplane-alert"}),
        ("button", "charter_scan", {"name": "Scan CrewTrac charters now", "command_topic": f"{T}/charter_scan/press",
                                    "icon": "mdi:airplane-search"}),
        ("button", "swap_map", {"name": "Map swap pages (read only)", "command_topic": f"{T}/swap_map/press",
                                 "icon": "mdi:map-search", "entity_category": "diagnostic"}),
        ("button", "check_now", {"name": "Check now", "command_topic": f"{T}/check_now/press",
                                 "icon": "mdi:refresh"}),
        ("number", "normal_minutes", {"name": "Normal check every", "command_topic": f"{T}/freq/normal_min/set",
                                      "state_topic": f"{T}/freq/normal_min/state", "min": 1, "max": 20,
                                      "step": 1, "mode": "slider", "unit_of_measurement": "min",
                                      "icon": "mdi:timer-outline"}),
        ("number", "hunt_seconds", {"name": "Hunt check every", "command_topic": f"{T}/freq/hunt_s/set",
                                    "state_topic": f"{T}/freq/hunt_s/state", "min": 5, "max": 90,
                                    "step": 5, "mode": "slider", "unit_of_measurement": "s",
                                    "icon": "mdi:timer-alert-outline"}),
    ]
    for comp, oid, cfg in ents:
        cfg = {**base, **cfg, "unique_id": f"flica_watcher_{oid}", "object_id": f"flica_watcher_{oid}"}
        c.publish(f"homeassistant/{comp}/flica_watcher/{oid}/config", json.dumps(cfg), retain=True)


def mqtt_start():
    m = mqtt_creds()
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="flica_watcher")
    c.username_pw_set(m["username"], m["password"])
    c.will_set(AVAIL, "offline", retain=True)
    c.on_message = on_message

    def on_connect(cl, u, f, rc, p=None):
        cl.publish(AVAIL, "online", retain=True)
        discovery(cl)
        for t in ("hunt/set", "pause/set", "rearm/press", "hunt/state", "pause/state", "rule/+/live/set",
                  "check_now/press", "freq/normal_min/set", "freq/hunt_s/set", "email/alert", "blocked/set",
                  "trade/set", "auto_swap/set", "swap_map/press", "swap_mode/set", "drop/set", "charter_scan/press", "pilot/set",
                  "improved/set"):
            cl.subscribe(f"{T}/{t}")
        fq = freq()
        cl.publish(f"{T}/freq/normal_min/state", str(fq["normal_min"]), retain=True)
        cl.publish(f"{T}/freq/hunt_s/state", str(fq["hunt_s"]), retain=True)
        publish_rules(cl)
        cl.publish(f"{T}/auto_swap/state", "ON" if S.get("auto_swap") else "OFF", retain=True)
        cl.publish(f"{T}/swap_mode/state", S.get("swap_mode") or SUB.DEFAULT_MODE, retain=True)
        publish_swap_tests()

    c.on_connect = on_connect
    c.connect(m["host"], int(m["port"]))
    c.loop_start()
    return c


MQ = None


def pub(topic, payload, retain=True):
    if not isinstance(payload, str):
        payload = json.dumps(payload)
    MQ.publish(f"{T}/{topic}", payload, retain=retain)


FETCHES = {"n": None, "pub_at": 0}


def count_fetch():
    """0.8.7 (Ryan): count every page the Watcher loads from FLICA (fetch or goto), kept in the DB and
    published as sensor.flica_watcher_flica_fetches (total_increasing) so HA utility meters can show
    hourly / daily / monthly session refreshes."""
    try:
        if FETCHES["n"] is None:
            FETCHES["n"] = int(DB.get("fetches_total") or 0)
        FETCHES["n"] += 1
        if time.time() - FETCHES["pub_at"] >= 5:
            FETCHES["pub_at"] = time.time()
            DB.put("fetches_total", FETCHES["n"])
            pub("fetches", {"total": FETCHES["n"], "at": now_iso()})
    except Exception as e:
        log.info("fetch count skipped: %s", e)


def set_machine(state, note=""):
    if S.get("machine") != state:
        log.info("state %s -> %s %s", S.get("machine"), state, note)
    if S.get("machine") != state or not S.get("since"):
        S["since"] = now_iso()
    S["machine"] = state
    S["note"] = note
    save_state(S)
    pub("state", state)
    pub("state_attr", {"note": note, "version": VERSION, "since": S["since"]})


# ---------------------------------------------------------------- browser
class Flica:
    def __init__(self, pw):
        self.browser = pw.chromium.launch(headless=True)
        self.ctx = None
        self.new_context()

    def new_context(self, fresh=False):
        if self.ctx:
            self.ctx.close()
        kw = {"storage_state": COOKIES} if (os.path.exists(COOKIES) and not fresh) else {}
        self.ctx = self.browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"), **kw)

    def save(self):
        self.ctx.storage_state(path=COOKIES)

    def login(self):
        """Exactly one attempt. Returns 'ok', 'failed' or 'blocked'."""
        log.info("login attempt")
        S["last_login_attempt"] = now_iso()
        save_state(S)
        self.new_context(fresh=True)  # old cookies can skip the login form and break the login
        page = self.ctx.new_page()
        try:
            count_fetch()
            page.goto(BASE + "/", wait_until="domcontentloaded", timeout=45000)
            pw_in = page.locator("input[type=password]").first
            pw_in.wait_for(timeout=20000)
            inputs = page.evaluate("""() => [...document.querySelectorAll('input')].map((e, i) => {
                e.setAttribute('data-fwi', String(i));
                const r = e.getBoundingClientRect();
                return {i, type: (e.type || '').toLowerCase(), name: e.name || '', id: e.id || '',
                        vis: r.width > 0 && r.height > 0 && getComputedStyle(e).visibility !== 'hidden'};
            })""")
            log.info("login form inputs: %s", [(x["type"], x["name"], x["id"], x["vis"]) for x in inputs])
            pw_idx = next(x["i"] for x in inputs if x["type"] == "password" and x["vis"])
            skip = {"hidden", "password", "submit", "button", "checkbox", "radio", "image", "reset"}
            cands = [x for x in inputs if x["i"] < pw_idx and x["vis"] and x["type"] not in skip]
            if not cands:
                log.warning("no username field found before the password field")
                return "failed"
            user_in = page.locator(f"input[data-fwi='{cands[-1]['i']}']")
            pw_in = page.locator(f"input[data-fwi='{pw_idx}']")
            user_in.fill(OPTS["username"])
            pw_in.fill(OPTS["password"])
            pw_in.press("Enter")
            page.wait_for_load_state("domcontentloaded", timeout=45000)
            time.sleep(4)
            html = page.content()
            for fr in page.frames:
                try:
                    html += fr.content()
                except Exception:
                    pass
            low = html.lower()
            try:
                os.makedirs("/share/flica_watcher", exist_ok=True)
                page.screenshot(path="/share/flica_watcher/last_login.png", full_page=True)
                vis = page.inner_text("body")[:600].replace("\n", " | ")
                log.info("after login url=%s text=%s", page.url.split("?")[0], vis)
            except Exception as e:
                log.info("diag capture failed: %s", e)
            if "forward to the main menu" in low or "/online/mainmenu.cgi" in page.url:
                time.sleep(5)
                html = page.content()
                for fr in page.frames:
                    try:
                        html += fr.content()
                    except Exception:
                        pass
                low = html.lower()
            text = visible_text(html)
            on_menu = "/online/mainmenu.cgi" in page.url or "/full/" in page.url
            no_pw = page.locator("input[type=password]:visible").count() == 0
            # The main menu's "Recent Updates" bulletin can mention captcha/MFA in its news
            # text, so reaching the menu with no password box is a successful login.
            if on_menu and no_pw:
                self.save()
                S["last_login_ok"] = now_iso()
                save_state(S)
                return "ok"
            hits = [h for h in BLOCK_HINTS if h in text]
            if hits:
                i = text.find(hits[0])
                log.warning("block hints matched (visible text): %s near: %s", hits, text[max(0, i - 120):i + 120])
                return "blocked"
            if "sign out" in low and no_pw:
                self.save()
                S["last_login_ok"] = now_iso()
                save_state(S)
                return "ok"
            return "failed"
        except Exception as e:
            log.warning("login error: %s", e)
            return "failed"
        finally:
            page.close()

    def discover_pot_urls(self):
        """Walk the main menu once, open each 'View Opentime Pot' under the configured
        section for the current and next month, and remember the content frame URL."""
        page = self.ctx.new_page()
        found = {}
        try:
            count_fetch()
            page.goto(BASE + "/online/mainmenu.cgi", wait_until="domcontentloaded", timeout=45000)
            menu = None
            for _ in range(10):  # mainmenu.cgi first shows a "forwarding to the Main Menu" page
                time.sleep(2)
                menu = next((f for f in page.frames if "leftmenu" in f.url.lower()), None)
                if menu:
                    break
            kind = classify(page.content())
            if not menu:
                log.warning("main menu: no leftmenu frame (classify=%s) url=%s frames=%s", kind,
                            page.url.split("?")[0], [f.url.split("?")[0] for f in page.frames])
                if kind in ("killed", "expired"):
                    return None
                # Headless main menu can stall on a reCAPTCHA forward; the mobile pot page is
                # frameless and works with the same session cookie (Ryan's Distill used it).
                html = self.fetch(MOBILE_POT)
                mk = classify(html)
                txt = visible_text(html)
                log.info("mobile pot probe: classify=%s len=%d text=%s", mk, len(html), txt[:1500])
                rows = re.findall(r"<tr[^>]*>.*?</tr>", html, re.S | re.I)
                log.info("mobile pot rows=%d sample=%s", len(rows), [r[:400] for r in rows[:4]])
                if mk in ("killed", "expired"):
                    return None
                if "open time" in txt or "opentime" in txt:
                    # key "mobile" kept for the first page so the v0.1.x baseline carries over
                    urls = {"mobile": MOBILE_POT}
                    if OPTS.get("watch_next_month", True):
                        links = pot_links(html, MOBILE_POT)
                        log.info("mobile pot links to other bid months: %s", links)
                        mine = bcid(MOBILE_POT)
                        later = sorted((l for l in links if bcid(l["url"]) and bcid_after(bcid(l["url"]), mine)),
                                       key=lambda l: bcid_key(bcid(l["url"])))
                        if later:  # the nearest later bid period only, never an earlier month
                            urls[f"mobile_{bcid(later[0]['url'])}"] = later[0]["url"]
                        if len(urls) < 2:
                            log.info("no next-month pot link on the mobile page yet (opens with the bid month)")
                    return urls
                return None
            links = menu.evaluate(
                """(sec) => {
                  const months = %s; let section = '', month = '', out = [], i = 0;
                  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT);
                  let n; const re = new RegExp(sec, 'i');
                  while ((n = walker.nextNode())) {
                    if (n.children.length === 0 || n.tagName === 'A') {
                      const t = (n.innerText || '').trim();
                      const m = months.find(x => t.startsWith(x));
                      const bold = parseInt(getComputedStyle(n).fontWeight || '400') >= 600;
                      if (n.tagName !== 'A' && bold && !m && t) section = re.test(t) ? t : '';
                      if (m) month = m;
                      if (n.tagName === 'A' && /View Opentime Pot/i.test(t)) {
                        n.setAttribute('data-fw', String(i)); out.push({i, section, month}); i++;
                      }
                    }
                  }
                  return out;
                }""" % json.dumps(MONTHS),
                OPTS["pot_section"],
            )
            now = local_now()
            want = {MONTHS[now.month - 1], MONTHS[now.month % 12]}
            for l in links:
                if not l["section"] or l["month"] not in want or l["month"] in found:
                    continue
                with self.ctx.expect_page(timeout=20000) as pinfo:
                    menu.locator(f"a[data-fw='{l['i']}']").click()
                pot = pinfo.value
                pot.wait_for_load_state("domcontentloaded")
                time.sleep(3)
                alltxt = ""
                for fr in pot.frames:
                    try:
                        alltxt += fr.inner_text("body")
                    except Exception:
                        pass
                cat = OPTS["category_check"].split()
                if cat and not all(c in alltxt for c in cat):
                    log.warning("pot page for %s is not category %s, skipped", l["month"], OPTS["category_check"])
                    pot.close()
                    continue
                for fr in pot.frames:
                    try:
                        if "Opentime Pot" in fr.content() and fr.url.startswith("http"):
                            found[l["month"]] = fr.url
                    except Exception:
                        pass
                pot.close()
            self.save()
            return found
        finally:
            page.close()

    def fetch(self, url):
        count_fetch()
        r = self.ctx.request.get(url, timeout=45000)
        return r.text()

    def menu_tree(self):
        """0.8.4: the left menu's JS tree (M.addC entries with the tokened Schedules links). FLICA only
        builds it inside the real menu frame, so load the main menu in a tab and read that frame's
        source. Read only: no clicks."""
        page = self.ctx.new_page()
        try:
            count_fetch()
            page.goto(f"{BASE}/online/mainmenu.cgi", wait_until="domcontentloaded", timeout=45000)
            html = ""
            for _ in range(20):
                for fr in page.frames:
                    if "leftmenu" in (fr.url or ""):
                        try:
                            html = fr.content()
                        except Exception:
                            html = ""
                        if "addC(" in html or "addE(" in html:
                            return html
                time.sleep(1)
            return html
        finally:
            page.close()

    def render(self, url, wait_for=None, timeout=30000):
        """0.4.12: load a JS-built page in a real tab (read only, no clicks) and return its HTML
        once `wait_for` (a CSS selector) is present, plus the API responses it fetched."""
        page = self.ctx.new_page()
        calls = []
        page.on("response", lambda resp: calls.append((resp.url, resp.status)) if "/api/" in resp.url or "json" in (resp.headers.get("content-type") or "") else None)
        try:
            count_fetch()
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            if wait_for:
                page.wait_for_selector(wait_for, timeout=timeout)
            else:
                time.sleep(4)
            return page.content(), calls
        finally:
            page.close()


# ---------------------------------------------------------------- main loop
def freq():
    """Current settings. Defaults are the midpoints of the add-on options (6 min normal, 40 s hunt)."""
    f = dict(S.get("freq") or {})
    f.setdefault("normal_min", max(1, round((OPTS["idle_min_s"] + OPTS["idle_max_s"]) / 2 / 60)))
    f.setdefault("hunt_s", max(5, round((OPTS["hunt_min_s"] + OPTS["hunt_max_s"]) / 2)))
    for k, (lo, hi) in FREQ_LIMITS.items():  # stored values from wider old ranges are clamped
        f[k] = max(lo, min(hi, f[k]))
    return f


def gap():
    fq = freq()
    mid = fq["hunt_s"] if FLAGS["hunt"] else fq["normal_min"] * 60
    return random.uniform(mid * (1 - JITTER), mid * (1 + JITTER))


def sleep(sec):
    WAKE.clear()
    WAKE.wait(sec)



def sleep_announced(sec):
    """Sleep, publishing when the next pot check is due (sensor.flica_watcher_next_check)."""
    pub("next_check", datetime.fromtimestamp(time.time() + sec, timezone.utc).isoformat())
    sleep(sec)


def no_next_check():
    pub("next_check", "None")  # HA shows unknown: no check scheduled (paused/stopped)


def try_login(fl, reason):
    """Single attempt. Parks the watcher on anything but success."""
    res = fl.login()
    if res == "ok":
        S["pot_urls"] = {}
        pub("session", "ON")
        set_machine("hunting" if FLAGS["hunt"] else "idle", f"logged in ({reason})")
        return True
    pub("session", "OFF")
    if res == "blocked":
        set_machine("stopped_unexpected", "FLICA asked for captcha/MFA/password change during login")
    else:
        set_machine("stopped_login_failed", f"one login attempt failed ({reason})")
    return False


def hst_midnight_utc():
    d = datetime.now(HST).replace(hour=0, minute=0, second=0, microsecond=0)
    return d.astimezone(timezone.utc).isoformat()


def run_rules(month, key, row):
    with RULE_LOCK:
        lst = list(RULES["list"])
    if not lst:
        return
    hits = R.evaluate(lst, row, DB.live_flags(), DB.would_submits_since(hst_midnight_utc()))
    for m in hits:
        DB.add_match(m, f"{month}|{key}")
        log.info("rule match %s %s would_submit=%s (%s)", m["rule_id"], row.get("pairing"),
                 m["would_submit"], m["reason"])
        pub("event/rule_match", m, retain=False)
        pub("last_match", m)


DETAIL_PROBE = {"done": False}


def enrich(fl, ev):
    """One read-only GET of the pairing's mobile detail page: captain name, block, credit,
    soft time (credit minus block). Never clicks or submits. Failure leaves the row as is."""
    try:
        url = detail_url(ev)
        if url:
            page = fl.fetch(url)
            if classify(page) == "ok":
                d = parse_detail(page)
                DB.remember_crew(visible_text(page))  # 0.8.2: crew directory for name lookups
                if not DETAIL_PROBE["done"]:
                    DETAIL_PROBE["done"] = True
                    log.info("detail text %s: %s", ev.get("pairing"), visible_text(page)[:2500])
                ev.update({k: v for k, v in d.items() if k == "captain" or not ev.get(k)})
                ev["detail_url"] = url
    except Exception as e:
        log.info("detail skipped for %s: %s", ev.get("pairing"), e)
    ev.setdefault("captain", "")
    st = soft_time(ev.get("credit"), ev.get("blk"))
    ev["soft"] = st or ""
    ev["fit"] = schedule_fit(ev)
    ev["vac"] = touches_vac(ev)
    ev["blocked"] = touches_blocked(ev)
    ev["far"] = far_for(ev)


def _span(ev):
    s = row_date(ev.get("start") or (ev.get("dates") or "").split("-")[0])
    if not s:
        return None, None
    e = row_date(ev.get("end")) if ev.get("end") else None
    if not e:
        try:
            e = s + timedelta(days=max(int(ev.get("days") or 1), 1) - 1)
        except ValueError:
            e = s
    return s, e


def _sched_items():
    return [it for m in S.get("schedule", {}).values() for it in m.get("items", [])]


def touches_vac(ev):
    """True when the trip's dates overlap any VAC block on Ryan's schedule (0.3.8)."""
    s, e = _span(ev)
    if not s:
        return False
    for it in _sched_items():
        if it.get("trip") == "VAC" and s.isoformat() <= it["end"] and e.isoformat() >= it["start"]:
            return True
    return False


def touches_blocked(ev):
    """True when the trip's dates include a day Ryan blocked on the schedule card (0.4.4)."""
    s, e = _span(ev)
    days = S.get("blocked_days") or []
    return bool(s and days and any(s.isoformat() <= d <= e.isoformat() for d in days))


def far_for(ev, exclude=None):
    """FAR 117 screen (far.py) of a pot or tradeboard row against Ryan's own trips. '?' when the
    pickup's check-in or final arrival is not known yet."""
    try:
        s, e = _span(ev)
        w = far_window(s, e, ev.get("report"), ev.get("arrive") or ev.get("last_arr"))
        if not w:
            return "?"
        mine = []
        for it in _sched_items():
            if not PAIRING_RE.match(it.get("trip") or "") or f"{it['trip']}|{it['start']}" == exclude:
                continue
            t = S.get("own_trips", {}).get(f"{it['trip']}|{it['start']}") or {}
            a, b = date.fromisoformat(it["start"]), date.fromisoformat(it["end"])
            ow = far_window(a, b, t.get("report"), t.get("last_arr"))
            if ow:
                mine.append((ow[0], ow[1], hours(t.get("blk")) or 0))
            else:  # times not read yet: whole days, flagged so a neighbouring trip reads '?'
                mine.append((datetime.combine(a, datetime.min.time()),
                             datetime.combine(b, datetime.max.time()), 0, True))
        return far_check((w[0], w[1], hours(ev.get("blk")) or 0), mine)
    except Exception as ex:
        log.info("far skipped for %s: %s", ev.get("pairing"), ex)
        return "?"


OWN_PER_CHECK = 3
FULL_MAX = 12  # Check now: at most this many detail GETs per kind, still 1.5-3.5 s apart


def own_trip_times(fl, full=False):
    """Read only (0.3.8): check-in, final arrival and block of Ryan's own trips from their pairing
    pages, cached per trip and start date, so the FAR column can measure rest."""
    own = S.setdefault("own_trips", {})
    keep, n = set(), 0
    for it in _sched_items():
        trip = it.get("trip") or ""
        if not PAIRING_RE.match(trip):
            continue
        k = f"{trip}|{it['start']}"
        keep.add(k)
        old = k in own and own[k] and ("credit" not in own[k] or "duties" not in own[k] or "crew" not in own[k]
                                             or (own[k].get("duties") and "blk" not in own[k]["duties"][0]))  # cached before 0.4.9 / 0.4.15 / 0.4.17 / 0.4.19
        # 0.6.1 (Ryan): block and credit move once a trip flies (actuals). Re-read a trip in progress every 6 h
        # and a finished trip once more the day after it ends, so completed trips show their final times.
        today = local_now().date().isoformat()
        cur = own.get(k) or {}
        if k in own and cur and it["start"] <= today:
            read_at = cur.get("read_at") or ""
            if it["end"] >= today and read_at[:13] < (local_now() - timedelta(hours=6)).isoformat()[:13]:
                old = True
            elif it["end"] < today and not cur.get("final"):
                old = True
        if (k in own and not full and not old) or n >= (FULL_MAX if full else OWN_PER_CHECK):
            continue
        if n:
            time.sleep(random.uniform(1.5, 3.5))
        n += 1
        url = (f"{BASE}/full/mobilepairing.cgi?PID={trip}&DATE={it['start'].replace('-', '')}"
               "&FROM=MobileOpentimePot&CurrentPage=1")
        try:
            page = fl.fetch(url)
            if classify(page) == "ok":
                d = parse_detail(page)
                if d.get("report") and d.get("last_arr"):
                    own[k] = {f: d.get(f, "") for f in ("report", "last_arr", "blk", "credit")}
                    own[k]["soft"] = soft_time(d.get("credit"), d.get("blk")) or ""
                    own[k]["read_at"] = local_now().isoformat()
                    own[k]["final"] = it["end"] < today  # read after the trip ended: these are the final times
                    own[k]["duties"] = d.get("duties", [])  # 0.4.15: duty periods, so a 30 in 7 on a layover counts
                    own[k]["seat"] = my_seat(d.get("crew") or [])  # 0.4.15: RO or FO as listed on the trip
                    ids = crew_ids(visible_text(page))  # 0.4.17: roster with employee numbers for the card
                    own[k]["crew"] = [with_ids(f"{pos} {name}", ids) for pos, name in (d.get("crew") or [])]
                    log.info("own trip %s: report %s, in %s, blk %s", k, d["report"], d["last_arr"],
                             d.get("blk"))
                else:
                    log.info("own trip %s: no times on the pairing page", k)
                    own[k] = {}
        except Exception as e:
            log.info("own trip %s skipped: %s", k, e)
    for k in [k for k in own if k not in keep]:
        own.pop(k)
    if n:
        save_state(S)
    publish_own_trips()


def my_seat(crew):
    """'RO' / 'FO' / 'CA' when the crew roster lists my_name (config option, e.g. a surname); '' if not
    set or not found. RO override pay only applies when Ryan is listed as RO on the trip."""
    me = (OPTS.get("my_name") or "").strip().lower()
    if not me:
        return ""
    for pos, name in crew:
        if me in str(name).lower():
            return pos
    return ""


def versions_check(force_pub=False):
    """0.9.0 (Ryan): a new schedule version (MM.NNN) every time anything on a month changes. A month whose new
    pairings have no block / credit read yet waits up to 2 h for them, so one change makes one version."""
    try:
        months, own = S.get("schedule") or {}, S.get("own_trips") or {}
        wait = S.setdefault("ver_wait", {})
        ready = {}
        for mk, sch in months.items():
            missing = [i for i in sch.get("items") or [] if PAIRING_RE.match(i.get("trip") or "")
                       and f"{i['trip']}|{i['start']}" not in own]
            if missing and time.time() - wait.setdefault(mk, time.time()) < 7200:
                continue
            wait.pop(mk, None)
            ready[mk] = sch
        if not S.get("ver_seeded"):  # 0.9.0: Nov 2-4 versions rebuilt from HA's recorder (before the Watcher kept versions)
            for mk, v in VER.seed(DB, "/share/flica_watcher/versions_seed.json",
                                  lambda ts: datetime.fromtimestamp(ts or time.time(), timezone.utc).isoformat()):
                log.info("schedule version %s (%s) imported from the recorder", v, mk)
            S["ver_seeded"] = True
        made = VER.update(DB, ready, own, now_iso())
        for mk, v in made:
            log.info("schedule version %s (%s)", v, mk)
        if made or force_pub or not S.get("ver_published"):
            pub("schedule_versions", {"count": sum(len(DB.get(f"sched_versions:{m}") or []) for m in months),
                                      "months": VER.published(DB, months), "at": now_iso()})
            S["ver_published"] = True
            if made:
                pub("event/schedule_version", {"versions": [v for _, v in made], "at": now_iso()}, retain=False)
    except Exception as e:
        log.info("schedule versions skipped: %s", e)


UPLOADS = "/share/flica_watcher/uploads"
CARD_PAIRINGS = "/homeassistant/www/flica"


def uploads_check():
    """0.9.1 (Ryan): parse the monthly PDFs uploaded on the Web UI (text copies made by pdftotext). Pairings
    package -> the schedule card's pairing file (www/flica/pairings_<YYYY-MM>.json) and trip details; award ->
    this month's version .001. Each file is handled again only when it changes. No FLICA traffic."""
    try:
        done = S.setdefault("uploads_done", {})
        files = sorted(os.listdir(UPLOADS)) if os.path.isdir(UPLOADS) else []
        for kind in ("pairings", "award"):  # the award needs that month's package details
            for f in [x for x in files if x.endswith(f"_{kind}.txt")]:
                path = os.path.join(UPLOADS, f)
                sig = f"{os.path.getmtime(path):.0f}"
                if done.get(f) == sig:
                    continue
                month = f[:7]
                text = open(path, errors="replace").read()
                if kind == "pairings":
                    pj = PDF.package_json(text, os.path.basename(path)[:-4] + " (uploaded PDF), A332 HNL base")
                    if pj["month"] != month or not pj["rows"]:
                        log.info("upload %s: not a %s A332 pairing package (%s, %d rows)", f, month, pj["month"], len(pj["rows"]))
                    else:
                        os.makedirs(CARD_PAIRINGS, exist_ok=True)
                        json.dump(pj, open(os.path.join(CARD_PAIRINGS, f"pairings_{month}.json"), "w"), separators=(",", ":"))
                        DB.put(f"pkg_details:{month}", PDF.package_details(text))
                        log.info("upload %s: %d A332 pairings -> www/flica/pairings_%s.json", f, len(pj["rows"]), month)
                else:
                    det = DB.get(f"pkg_details:{month}")
                    emp = S.get("own_emp") or ""
                    if not det or not emp:
                        log.info("upload %s: waiting for the %s pairing package and the employee number", f, month)
                        continue
                    aw = PDF.parse_award(text, emp, det, month)
                    if not aw:
                        log.info("upload %s: employee %s not in this award", f, emp)
                    else:
                        vers = VER.set_award(DB, month, aw, now_iso())
                        log.info("upload %s: awarded line is version %s (%d items, credit %s); %d versions",
                                 f, vers[0]["ver"], len(aw["items"]), aw["totals"].get("credit"), len(vers))
                        versions_check(force_pub=True)
                done[f] = sig
                save_state(S)
    except Exception as e:
        log.info("uploads skipped: %s", e)


def improved_cmd(payload):
    """0.9.0 (Ryan): the schedule card prices each month's awarded version (.001) and current version with
    today's pay settings and reports {month, awarded, current, ver, awarded_ver}; kept per month in the DB
    (improved_pay) and published for the Details bar chart."""
    try:
        d = json.loads(payload or "{}")
        mk = str(d.get("month") or "")
        if not re.fullmatch(r"\d{4}-\d{2}", mk):
            return
        allm = DB.get("improved_pay") or {}
        rec = {"month": mk, "awarded": round(float(d.get("awarded") or 0), 2), "current": round(float(d.get("current") or 0), 2),
               "ver": str(d.get("ver") or ""), "awarded_ver": str(d.get("awarded_ver") or "")}
        rec["improved"] = round(rec["current"] - rec["awarded"], 2)
        if {k: v for k, v in (allm.get(mk) or {}).items() if k != "at"} == rec:
            return
        allm[mk] = {**rec, "at": now_iso()}
        DB.put("improved_pay", allm)
        publish_improved()
    except Exception as e:
        log.info("improved pay skipped: %s", e)


def publish_improved():
    allm = DB.get("improved_pay") or {}
    rows = [allm[k] for k in sorted(allm)]
    cur = rows[-1] if rows else {}
    pub("improved_pay", {"improved": cur.get("improved", 0), "months": rows, "ytd": round(sum(r.get("improved", 0) for r in rows), 2)})


def publish_own_trips():
    """0.4.7: Ryan's own trip report and block-in times (HNL local) for the schedule card, which
    shows them and suggests tag-on pairings after each trip. Keys 'TRIP|YYYY-MM-DD' (start)."""
    pub("own_trips", {"count": len(S.get("own_trips", {})), "trips": S.get("own_trips", {})})


def schedule_fit(ev):
    """'Fits' / 'Conflict H3659' / 'Check rest H3628' / 'Days off 11' vs Ryan's own schedule; ''
    when no schedule month covers the dates. Never fails the alert."""
    try:
        s = row_date(ev.get("start"))
        if not s:
            return ""
        e = row_date(ev.get("end")) if ev.get("end") else None
        if not e:
            try:
                e = s + timedelta(days=max(int(ev.get("days") or 1), 1) - 1)
            except ValueError:
                e = s
        for sched in S.get("schedule", {}).values():
            tag = fit_tag(s, e, sched)
            if tag:
                return tag
        return "No sched"  # never blank: blank read as "fits" for months with no schedule yet
    except Exception as ex:
        log.info("fit skipped for %s: %s", ev.get("pairing"), ex)
    return ""


DETAIL_FIELDS = ("captain", "report", "blk", "tafb", "soft", "turn", "route", "open_seats", "crew", "detail_url")
DETAIL_MAX_PER_CHECK = 8


def pot_details(fl, pot, full=False):
    """Captain, check-in, block, TAFB and soft time on EVERY pot row (not only new ones), so the
    dashboard table can show them. One read-only detail GET per pairing, cached until the pairing
    leaves the pot; at most 8 new ones per check, 1.5-3.5 s apart. Fit is re-tagged every check
    because the schedule can change."""
    cache = S.setdefault("details", {})
    fetched = 0
    for k, row in pot.items():
        stale = k in cache and "crew" not in cache[k]  # cached before 0.4.0: re-read once
        if (k not in cache or stale or full) and fetched < (FULL_MAX if full else DETAIL_MAX_PER_CHECK):
            if fetched:
                time.sleep(random.uniform(1.5, 3.5))
            ev = dict(row)
            enrich(fl, ev)
            fetched += 1
            cache[k] = {f: ev.get(f, "") for f in DETAIL_FIELDS}
        if k in cache:
            row.update({f: v for f, v in cache[k].items() if v or not row.get(f)})
            if not row.get("soft"):
                row["soft"] = soft_time(row.get("credit"), row.get("blk")) or ""
        row["fit"] = schedule_fit(row)
        row["vac"] = touches_vac(row)
        row["blocked"] = touches_blocked(row)
        row["far"] = far_for(row)
    if fetched:
        log.info("pot details fetched: %d (cached %d)", fetched, len(cache))


SCHED_GAP_S = 30 * 60


LEFTMENU = f"{BASE}/online/leftmenu.cgi?whosepage=Crewmember"
SCHED_LINK_RE = r"scheduledetail\.cgi\?[^\"']*?BlockDate=%s(?:[^\"']*?)(?:&|&amp;)token=([0-9A-Za-z]+)"  # 0.8.3: params in any order


def desktop_schedule(fl, bd, seen):
    """0.7.1: the desktop Schedules > <month> page via the left menu's tokened link (GET only). The first
    two pages are saved to the private share folder for the parser; returns parse_schedule_desktop() or
    None. The token is never logged."""
    menu = fl.fetch(LEFTMENU)
    if "scheduledetail" not in (menu or ""):  # 0.8.4: the plain GET gets only the skeleton; the frame has the tree
        menu = fl.menu_tree()
    try:  # 0.8.3: keep the menu page (token masked) so the link pattern can be checked against the real thing
        os.makedirs(IF.CAPTURE_DIR, exist_ok=True)
        open(f"{IF.CAPTURE_DIR}/leftmenu.html", "w").write(re.sub(r"token=[0-9A-Za-z]+", "token=MASKED", menu or ""))
    except Exception as e:
        log.info("leftmenu capture skipped: %s", e)
    m = re.search(SCHED_LINK_RE % bd, menu or "")
    if not m:
        m2 = re.search(r"scheduledetail\.cgi\?[^\"']*?token=([0-9A-Za-z]+)", menu or "")
        if m2:  # any month's link carries the same session token (0.8.3)
            m = m2
    if not m:
        seen.append(("leftmenu", f"no Schedules link for BlockDate={bd}: {classify(menu)} {visible_text(menu)[:120]}"))
        return None
    time.sleep(random.uniform(1.0, 2.0))
    page = fl.fetch(f"{BASE}/full/scheduledetail.cgi?GO=1&token={m.group(1)}&BlockDate={bd}")
    try:
        os.makedirs(IF.CAPTURE_DIR, exist_ok=True)
        open(f"{IF.CAPTURE_DIR}/scheduledetail_{bd}.html", "w").write(page)
    except Exception as e:
        log.info("schedule capture skipped: %s", e)
    sp = parse_schedule_desktop(page)
    if not sp:
        seen.append((f"scheduledetail GO=1 BlockDate={bd}", f"{classify(page)} {len(page)} chars: {visible_text(page)[:160]}"))
    return sp


OWN_RE = re.compile(r"\b([a-z]+(?: jr| sr| ii| iii)?, [a-z]+(?: [a-z]+)?)\s+(\d{3,6})\s+-\s+[a-z]{3}\s+\d{3}\s+(?:fo|ca|ro)\b")


def note_own(text):
    """0.8.5: Ryan's own employee number from a FLICA page header ('doe, jane 9901 - hnl 332 fo'),
    kept in state for the Schedule Lookup reads of his other months."""
    m = OWN_RE.search((text or "").lower())
    if m and S.get("own_emp") != m.group(2):
        S["own_emp"], S["own_name"] = m.group(2), m.group(1).title()
        S["sched_prev_at"] = S["sched_checked_at"] = 0  # read the other months on the next pass
        log.info("own employee number noted from the page header")
    return S.get("own_emp")


def other_months_check(fl, cur_month):
    """0.8.5 (Ryan: October now, December once it is published): Tools > Schedule Lookup for Ryan's own
    number lists every month FLICA holds in its <select> (1026, 1126, later 1226); each listed month other
    than the current one is read with bd=MMYY (GET only) and parsed like a picker's month, so the FAR 30 in
    7 / 100 in 672 columns can look back and forward. Returns True when every listed month is in."""
    emp = S.get("own_emp")
    if not emp:
        return False
    store = S.setdefault("schedule", {})
    cur = local_now()
    html = fl.fetch(IF.CM_SCHED_MONTH.format(base=BASE, emp=emp, bd=f"{cur.month:02d}{cur.year % 100:02d}"))
    if classify(html) != "ok":
        log.info("own schedule lookup: %s", classify(html))
        return False
    bds = re.findall(r'<option value="(\d{4})"', html)
    if not bds:
        log.info("own schedule lookup: no month list: %s", visible_text(html)[:160])
        return False
    got = []
    for bd in bds:
        mon = f"20{bd[2:]}-{bd[:2]}"
        if mon == cur_month:
            continue
        if mon in store and store[mon].get("src") == "lookup" and time.time() - store[mon].get("read_ts", 0) < 6 * 3600:
            got.append(mon)
            continue
        time.sleep(random.uniform(1.5, 3.5))
        page = fl.fetch(IF.CM_SCHED_MONTH.format(base=BASE, emp=emp, bd=bd))
        sp = IF.parse_cm_month(page) if classify(page) == "ok" else None
        if not sp or sp["month"] != mon:
            log.info("own schedule %s (bd=%s): %s %s", mon, bd, classify(page), (sp and sp["month"]) or visible_text(page)[:160])
            continue
        store[mon] = {"month": mon, "updated": sp.get("updated", ""), "days": sp["days"], "items": sp["items"],
                      "totals": sp.get("totals") or {}, "src": "lookup", "read_ts": time.time()}
        got.append(mon)
        log.info("schedule %s: %d items via Schedule Lookup (bd=%s), totals %s", mon, len(sp["items"]), bd, sp.get("totals"))
    return len(got) == len([b for b in bds if f"20{b[2:]}-{b[:2]}" != cur_month])


def prev_month_check(fl, ok_url, cur_month):
    """0.4.16/0.4.17 (Ryan): read last month's schedule once a day with the bid-period number one lower
    (Nov 152 -> Oct 151), trying the same URL shapes as the current month (the OT drop view only
    offers open months), so the card's FAR 117 windows that reach back into last month have data.
    Read only; failures are logged and ignored."""
    store = S.setdefault("schedule", {})
    y, m = int(cur_month[:4]), int(cur_month[5:7])
    prev = f"{y - 1}-12" if m == 1 else f"{y}-{m - 1:02d}"
    if time.time() - S.get("sched_prev_at", 0) < (6 * 3600 if S.get("sched_prev_v") == 6 else 1800):
        return
    try:  # 0.8.5: Schedule Lookup lists every month FLICA holds; October (and December when out) come from there
        if other_months_check(fl, cur_month):
            S["sched_prev_at"] = time.time()
            S["sched_prev_v"] = 6
            return
    except Exception as e:
        log.info("own schedule lookup failed: %s", e)
    if S.get("sched_prev_v") == 5 and prev in store and time.time() - S.get("sched_prev_at", 0) < 86400:
        return
    mo = re.search(r"BCID=\d{3}\.(\d+)", ok_url)
    if not mo:
        return
    n = f"{int(mo.group(1)) - 1:03d}"
    py, pm = int(prev[:4]), int(prev[5:7])
    cands = [f"{BASE}/full/mobileschedule.cgi?BlockDate={pm:02d}{py % 100:02d}&From=MainMenu",
             f"{BASE}/full/scheduledetail.cgi?BlockDate={pm:02d}{py % 100:02d}"]
    S["sched_prev_v"] = 5  # 0.8.3: re-run the October read right away
    S["sched_prev_at"] = time.time()
    seen = []
    try:  # 0.7.1 (Ryan: October): FLICA's own Schedules menu links each month with a session token
        sp = desktop_schedule(fl, f"{pm:02d}{py % 100:02d}", seen)
        if sp and sp["month"] == prev:
            store[prev] = sp
            S["sched_prev_url"] = "leftmenu"
            log.info("schedule %s (previous month): %d items via Schedules menu", prev, len(sp["items"]))
            return
    except Exception as e:
        seen.append(("leftmenu", str(e)))
    for url in cands:
        try:
            time.sleep(random.uniform(1.5, 3.5))
            html = fl.fetch(url)
            if classify(html) != "ok":
                seen.append((url.split("?")[1], classify(html)))
                continue
            sp = parse_schedule(html)
            if sp and sp["month"] == prev:
                store[prev] = sp
                S["sched_prev_url"] = url
                log.info("schedule %s (previous month): %d items via %s", prev, len(sp["items"]), url.split("?")[1])
                return
            seen.append((url.split("?")[1], (sp and sp["month"]) or visible_text(html)[:160]))
        except Exception as e:
            seen.append((url.split("?")[1], str(e)))
    log.info("previous month schedule %s not found: %s", prev, seen)


def schedule_check(fl, force=False):
    """Read only: GET Ryan's month schedule (mobileschedule.cgi), publish sensor.flica_watcher_schedule
    and an event when trips change. Never stops the pot watch."""
    if not force and time.time() - S.get("sched_checked_at", 0) < SCHED_GAP_S:
        return
    S["sched_checked_at"] = time.time()
    b = sorted({bcid(u) for u in S.get("pot_urls", {}).values() if bcid(u)}, key=bcid_key)
    b = b[0] if b else "003.152"
    store = S.setdefault("schedule", {})
    n = b.split(".")[-1]
    tried = S.setdefault("sched_url_ok", "")
    # 0.4.20: the desktop schedule page (Schedules > month) carries FLICA's Block / Credit / YTD / Days Off and
    # every leg; it is keyed by BlockDate=MMYY, not by BCID. Try it first for the pot month.
    cur = local_now()
    bdc = f"{cur.month:02d}{cur.year % 100:02d}"
    cands = [f"{BASE}/full/mobileschedule.cgi?BlockDate={bdc}&From=MainMenu", f"{BASE}/full/mobileschedule.cgi?From=MainMenu"]  # 0.4.21 shapes
    cands += [f"{BASE}/full/scheduledetail.cgi?BlockDate={bdc}"]  # desktop page: reCAPTCHA interstitial for this session (0.4.20); kept last
    cands += [f"{BASE}/full/mobileschedule.cgi?BCID={p}.{n}&From=MainMenu" for p in ("003", "001", "002", "004", "000")]
    cands += [f"{BASE}/full/mobileschedule.cgi?BCID={b}&Priority=1&From=MainMenu",
              f"{BASE}/full/mobileschedule.cgi?BCID={b}&Priority=1&From=MobileOTDrop"]  # view only; GET never submits
    if tried in cands:
        cands.remove(tried)
        cands.insert(0, tried)
    # 0.4.19: prefer the view that carries FLICA's Block / Credit totals (the OT drop view has none); the
    # winning URL is tried first next time. At most 3 fetches per read, 1-2 s apart.
    def accept(url, s):
        old = store.get(s["month"])
        if old and [(i["trip"], i["start"]) for i in old["items"]] != [(i["trip"], i["start"]) for i in s["items"]]:
            ev = {"month": s["month"], "updated": s["updated"],
                  "added": sorted({i["trip"] + " " + i["start"] for i in s["items"]} - {i["trip"] + " " + i["start"] for i in old["items"]}),
                  "removed": sorted({i["trip"] + " " + i["start"] for i in old["items"]} - {i["trip"] + " " + i["start"] for i in s["items"]}),
                  "totals": s["totals"]}
            log.info("SCHEDULE changed %s", ev)
            pub("event/schedule_changed", ev, retain=False)
        S["sched_url_ok"] = url
        store[s["month"]] = s
        prev_month_check(fl, url, s["month"])  # 0.4.16: last month too, for 30 in 7 / 100 in 672 windows
        keep = sorted(store)[-3:]
        S["schedule"] = {k: store[k] for k in keep}
        pub("schedule", {"updated": s["updated"] or now_iso(), "source": "FLICA mobile schedule (Watcher)",
                         "checked": now_iso(),
                         "months": {k: {kk: v[kk] for kk in ("items", "days", "totals", "updated")}
                                    for k, v in S["schedule"].items()}})
        log.info("schedule %s: %d items, totals %s", s["month"], len(s["items"]), s["totals"])
        save_state(S)

    fallback, tries = None, 0
    probe_alts = time.time() - S.get("sched_alt_at", 0) > 86400  # 0.5.0: other URL shapes once a day, not every read
    if probe_alts:
        S["sched_alt_at"] = time.time()
    for url in cands:
        if tries >= 4 or (tries and not probe_alts and fallback):
            break
        try:
            if tries:
                time.sleep(random.uniform(1.0, 2.0))
            tries += 1
            html = fl.fetch(url)
            if classify(html) != "ok":
                log.info("schedule %s: %s", url.split("?")[1], classify(html))
                continue
            s = parse_schedule(html)
            if "scheduledetail" in url and not S.get("sched_detail_saved"):
                try:
                    os.makedirs(CAPTURE_DIR, exist_ok=True)
                    open(f"{CAPTURE_DIR}/scheduledetail.html", "w").write(html)
                    S["sched_detail_saved"] = True
                    log.info("scheduledetail page saved (%d chars), parsed: %s", len(html), bool(s) and s.get("totals"))
                except Exception:
                    pass
            if not s:
                log.info("schedule try %s: %s", url.split("?")[1], visible_text(html)[:120])
                if not S.get("sched_probe_logged"):
                    S["sched_probe_logged"] = True
                    log.info("schedule page not parsed (%s): %s", url, visible_text(html)[:2000])
                    try:
                        os.makedirs(CAPTURE_DIR, exist_ok=True)
                        open(f"{CAPTURE_DIR}/schedule.html", "w").write(html)
                    except Exception:
                        pass
                continue
            if "block" in s.get("totals", {}):
                accept(url, s)
                return
            if fallback is None or url == S.get("sched_url_ok"):
                fallback = (url, s)  # parses but has no totals: keep looking, use it if nothing better turns up
        except Exception as e:
            log.info("schedule error %s: %s", url, e)
    if fallback:
        accept(*fallback)


def detail_probe(fl, pot):
    """Once per start: log one detail page's text so the captain/total parsers can be checked."""
    if DETAIL_PROBE["done"] or not pot:
        return
    row = dict(next(iter(pot.values())))
    enrich(fl, row)
    log.info("detail probe %s: captain=%r blk=%s credit=%s soft=%s", row.get("pairing"),
             row.get("captain"), row.get("blk"), row.get("credit"), row.get("soft"))


CAPTURE_DIR = "/share/flica_watcher/captures"


def capture(fl, month, html):
    """Read-only discovery for t1222 (soft time, captain, fits, FAR): every 6 h save the pot page,
    its links, one pairing detail page and any schedule page this session can already open, so
    the parsers get built from real HTML. Same session, GET only; never clicks or submits."""
    if time.time() - S.get("captured_at", 0) < 6 * 3600:
        return
    S["captured_at"] = time.time()
    try:
        from bs4 import BeautifulSoup
        from urllib.parse import urljoin
        os.makedirs(CAPTURE_DIR, exist_ok=True)
        open(f"{CAPTURE_DIR}/pot_{month}.html", "w").write(html)
        url = S["pot_urls"][month]
        links = [{"text": a.get_text(" ", strip=True)[:60], "href": urljoin(url, a["href"])}
                 for a in BeautifulSoup(html, "html.parser").find_all("a", href=True)]
        json.dump(links, open(f"{CAPTURE_DIR}/links_{month}.json", "w"), indent=1)
        picks = [l for l in links if re.match(r"^[A-Z]\d{4}", l["text"])][:1]
        picks += [l for l in links if re.search(r"sched|my trips|calendar", l["text"], re.I)][:1]
        for l in picks:
            if not l["href"].startswith(BASE):
                continue
            page = fl.fetch(l["href"])
            if classify(page) != "ok":
                log.info("capture: %s gave %s, skipped", l["text"], classify(page))
                continue
            name = re.sub(r"[^A-Za-z0-9]+", "_", l["text"])[:30] or "page"
            open(f"{CAPTURE_DIR}/{name}.html", "w").write(page)
        log.info("capture saved to %s: %d links, extra pages %s", CAPTURE_DIR, len(links),
                 [l["text"] for l in picks])
    except Exception as e:
        log.info("capture skipped: %s", e)


TB_MIN_GAP_S = 120
TB_PROBE = {"done": False}


def tradeboard_check(fl, full=False):
    """Read only: Tradeboard All Requests for each watched bid month. Alerts on new posts whose
    response method is 'Pickup Trip'. Any failure is logged and never stops the pot watch."""
    if not full and time.time() - S.get("tb_checked_at", 0) < TB_MIN_GAP_S:
        return
    S["tb_checked_at"] = time.time()
    nums = sorted({b.split(".")[-1] for b in (bcid(u) for u in S.get("pot_urls", {}).values()) if b})
    base = S.setdefault("tb_baseline", {})
    tb_cache = S.setdefault("tb_details", {})  # 0.4.6: enriched pickup posts, one detail GET each
    live = {}
    read_ok = False
    for n in nums:
        key = f"tb2_{n}"
        try:
            furl = f"{BASE}/online/tb_frame.cgi?BCID=001.{n}&dp=mr"
            fh = fl.fetch(furl)
            if classify(fh) != "ok":
                log.info("tradeboard %s frame: %s, skipped", n, classify(fh))
                continue
            url = TB.other_requests_url(fh, furl) or f"{BASE}/online/tb_otherrequests.cgi?BCID=001.{n}"
            html = fl.fetch(url)
            if classify(html) != "ok":
                log.info("tradeboard %s: %s, skipped", n, classify(html))
                continue
            picks = TB.parse_pickups(html)
            note_own(visible_text(html))  # 0.8.5: the header names Ryan with his employee number
            if not TB.has_rows(html):
                if not S.get("tb_raw_logged2"):
                    S["tb_raw_logged2"] = True
                    flat = re.sub(r"\s+", " ", html)
                    calls = [m.start() for m in re.finditer(r"\bA\s*\(", flat)]
                    i = calls[1] if len(calls) > 1 else (calls[0] if calls else 0)
                    log.info("tradeboard %s: no trip rows; %d A( calls; data: %s", n, len(calls),
                             flat[max(0, i - 300):i + 5000])
                    try:
                        os.makedirs(CAPTURE_DIR, exist_ok=True)
                        open(f"{CAPTURE_DIR}/tradeboard_{n}.html", "w").write(fh + "\n<!--OTHER-->\n" + html)
                    except Exception:
                        pass
                continue
            if not TB_PROBE["done"]:
                TB_PROBE["done"] = True
                log.info("tradeboard probe %s url=%s pickups=%s text=%s", n, url.split("?")[0],
                         list(picks), visible_text(html)[:1500])
            old = base.get(key)
            if old is None:
                log.info("tradeboard baseline %s: %d pickup posts (no alert)", key, len(picks))
            else:
                for k in sorted(set(picks) - set(old)):
                    ev = {**picks[k], "month": key, "seen": now_iso()}
                    enrich(fl, ev)
                    log.info("NEW tradeboard pickup %s", ev)
                    pub("event/new_pairing", ev, retain=False)
                    pub("last_tradeboard", ev)
            base[key] = sorted(picks)
            pub(f"tradeboard/{key}", {"count": len(picks), "posts": list(picks.values())[:40]})
            read_ok = True
            for k, row in picks.items():
                cached = tb_cache.get(k)
                if cached is None or full:
                    cached = {**row}
                    enrich(fl, cached)
                    tb_cache[k] = cached
                live[k] = cached
        except Exception as e:
            log.info("tradeboard %s error: %s", n, e)
    if read_ok:
        for k in list(tb_cache):
            if k not in live:
                del tb_cache[k]
        publish_tradeboard(live)
    save_state(S)


def publish_tradeboard(live=None):
    """0.4.6 (Ryan): Tradeboard 'Pickup Trip' posts are trips anyone can pick up, like open time.
    Published with the same fields as pot rows (fit, vac, blocked, far re-screened every time) plus
    src 'T', so the dashboard lists them in the pot table."""
    live = S.get("tb_details", {}) if live is None else live
    rows = []
    for k, row in sorted(live.items()):
        r = {f: v for f, v in row.items() if f not in ("row", "crew")}
        r["key"], r["src"] = k, "T"
        try:
            r["fit"] = schedule_fit(r)
            r["vac"] = touches_vac(r)
            r["blocked"] = touches_blocked(r)
            r["far"] = far_for(r)
        except Exception as e:
            log.info("tradeboard screen %s skipped: %s", k, e)
        rows.append(r)
    pub("tradeboard/state", {"count": len(rows), "pairings": rows})


GRID_MIN_GAP_S = 300
GRID_RENDER_GAP_S = 1800


def grid_check(fl, full=False):
    """0.4.13 (Ryan): read the Reserve Grid for each watched pot month. The JSON service behind the
    page is tried first (one GET); the rendered page is the fallback and also a cross-check every
    30 min. Publishes {date: {net, color}} on flica_watcher/grid/state. Read only."""
    if not full and time.time() - S.get("grid_at", 0) < GRID_MIN_GAP_S:
        return
    S["grid_at"] = time.time()
    grid = {}
    for u in S.get("pot_urls", {}).values():
        b = bcid(u)
        if not b:
            continue
        yr = local_now().year
        try:
            raw = fl.fetch(f"{BASE}/full/reserveGridService.cgi?bcid={b}&json=1")
            data = json.loads(raw)
            if not S.get("grid_json_logged"):
                S["grid_json_logged"] = True
                log.info("reserve grid json %s: %s", b, raw[:1500])
            got = G.parse_grid_json(data, yr)
        except Exception as e:
            log.info("reserve grid json %s failed: %s", b, e)
            got = {}
        need_render = not got or full or time.time() - S.get("grid_rendered_at", 0) > GRID_RENDER_GAP_S
        if need_render:
            try:
                html, _ = fl.render(f"{BASE}/ui/private/bidCloseReserveGrid/index.html?BCID={b}&GO=1",
                                    wait_for="table td", timeout=30000)
                page = G.parse_grid_html(html, yr)
                S["grid_rendered_at"] = time.time()
                if got and page and any(got[d]["color"] != page[d]["color"] for d in got if d in page):
                    log.info("reserve grid %s: json colors differ from the page, page wins", b)
                if page:
                    got = {**got, **page}
            except Exception as e:
                log.info("reserve grid render %s failed: %s", b, e)
        grid.update(got)
    if grid:
        S["grid"] = grid
        save_state(S)
    g = S.get("grid") or {}
    pub("grid/state", {"green": sum(1 for v in g.values() if v["color"] == "green"), "count": len(g),
                       "days": g, "read": now_iso() if grid else S.get("grid_read")})
    if grid:
        S["grid_read"] = now_iso()


def _trip_days(ev):
    s, e = _span(ev)
    if not s:
        return []
    return [(s + timedelta(days=i)).isoformat() for i in range((e - s).days + 1)]


SWAP_MAP_MAX = 14


def swap_map_probe(fl):
    """0.4.10, read only (t1243): walk from the main menu, the pot, the OT drop view and the
    Tradeboard to the open time request pages, GET each page that swapmap.safe_get allows (never a
    POST, never a URL carrying Add/Drop lists or an action word), and save the HTML plus a summary
    of every form to the private captures folder so the live swap can be built from real pages."""
    os.makedirs(f"{CAPTURE_DIR}/swapmap", exist_ok=True)
    b = (bcid(MOBILE_POT) or "003.152").split(".")[-1]
    queue = [("main menu", BASE + "/online/mainmenu.cgi"), ("mobile pot", MOBILE_POT),
             ("OT drop view", f"{BASE}/full/mobileschedule.cgi?BCID=001.{b}&Priority=1&From=MobileOTDrop"),
             ("tradeboard", f"{BASE}/online/tb_frame.cgi?BCID=001.{b}&dp=mr")]
    seen, index, n = set(), [], 0
    while queue and n < SWAP_MAP_MAX:
        text, url = queue.pop(0)
        if url in seen or not SM.safe_get(url):
            continue
        seen.add(url)
        if n:
            time.sleep(random.uniform(1.5, 3.5))
        n += 1
        try:
            html = fl.fetch(url)
        except Exception as e:
            index.append({"n": n, "text": text, "url": url, "error": str(e)})
            continue
        kind = classify(html)
        open(f"{CAPTURE_DIR}/swapmap/{n:02d}.html", "w").write(html)
        fm = SM.forms(html)
        index.append({"n": n, "text": text, "url": url, "classify": kind, "len": len(html), "forms": fm,
                      "title": (re.search(r"<title>(.*?)</title>", html, re.I | re.S) or [None, ""])[1].strip()[:80]})
        if kind != "ok":
            continue
        for t, u in SM.links(html, url):
            if u not in seen and (t == "frame" or SM.FOLLOW.search(t) or SM.FOLLOW.search(u)):
                queue.append((t, u))
    try:  # 0.4.12: the Reserve Grid is a JS page; render it and save HTML + the API calls it made
        gurl = f"{BASE}/ui/private/bidCloseReserveGrid/index.html?BCID=003.{b}&GO=1"
        html, calls = fl.render(gurl, wait_for="table td", timeout=30000)
        open(f"{CAPTURE_DIR}/swapmap/grid.html", "w").write(html)
        json.dump(calls, open(f"{CAPTURE_DIR}/swapmap/grid_calls.json", "w"), indent=1)
        index.append({"n": 99, "text": "reserve grid (rendered)", "url": gurl, "len": len(html), "calls": calls[:20]})
        log.info("swap map: reserve grid rendered, %d chars, %d api calls", len(html), len(calls))
    except Exception as e:
        index.append({"n": 99, "text": "reserve grid", "error": str(e)})
        log.info("swap map: reserve grid failed: %s", e)
    json.dump(index, open(f"{CAPTURE_DIR}/swapmap/index.json", "w"), indent=1)
    log.info("swap map: %d pages saved to %s/swapmap (read only, GET only)", n, CAPTURE_DIR)
    pub("event/swap_map", {"pages": n, "at": now_iso()}, retain=False)


AUTO_SWAP_PER_DAY = 1


# ---------------------------------------------------------------- 0.8.0 pilot schedule (Ryan: tap a picker's name)
PILOT_CACHE_S = 6 * 3600
PILOT_PAIRINGS_MAX = 8


def pilot_cmd(payload):
    """MQTT flica_watcher/pilot/set {"emp": "10001", "name": "..."}: show that pilot's current month on the
    dashboard. Served from a 6 h cache when fresh, else read on the next check (Schedule Lookup + the
    pairing pages, GET only)."""
    try:
        d = json.loads(payload)
        emp = re.sub(r"\D", "", str(d.get("emp") or ""))
    except (ValueError, AttributeError):
        d, emp = {}, ""
    q = str(d.get("q") or "").strip()
    if not emp and q:  # 0.8.2 (Ryan): free text: an employee number, or a name from the crew directory
        if q.isdigit():
            emp = q
        else:
            hits = DB.find_crew(q)
            if len(hits) == 1:
                emp, d["name"] = hits[0]["emp"], hits[0]["name"]
            elif hits:
                pub("pilot_schedule", {"emp": "", "name": q, "status": f"{len(hits)} pilots match '{q}', pick one", "matches": hits,
                                       "month": "", "days": [], "items": [], "totals": {}, "updated": "", "fetched": ""})
                return
            else:
                pub("pilot_schedule", {"emp": "", "name": q, "status": f"no pilot named '{q}' in the {DB.crew_count()} crew the Watcher has seen; enter the employee number",
                                       "matches": [], "month": "", "days": [], "items": [], "totals": {}, "updated": "", "fetched": ""})
                return
    if not emp:
        return
    S["pilot_req"] = {"emp": emp, "name": d.get("name") or "", "at": now_iso()}
    save_state(S)
    cached = DB.get(f"pilot_sched:{emp}")
    if cached and time.time() - cached.get("fetched_ts", 0) < PILOT_CACHE_S:
        pub("pilot_schedule", {**cached, "status": "cached"})
        S.pop("pilot_req", None)
        save_state(S)
        log.info("pilot %s: schedule served from cache", emp)
        return
    pub("pilot_schedule", {"emp": emp, "name": d.get("name") or "", "status": "loading", "month": "", "days": [], "items": [],
                           "totals": {}, "updated": "", "fetched": ""})
    log.info("pilot %s: schedule requested", emp)
    WAKE.set()


def pilot_check(fl):
    """Read the requested pilot's month (read only) and publish it for the pilot schedule card."""
    req = S.get("pilot_req")
    if not req:
        return False
    if not S.get("cm_prompt_captured"):  # 0.8.4: does FLICA's Schedule Lookup prompt offer a name search? Save it once.
        try:
            html = fl.fetch(f"{BASE}/full/cmschedules.cgi?Prompt=1&SchBrowser=1")
            os.makedirs(IF.CAPTURE_DIR, exist_ok=True)
            open(f"{IF.CAPTURE_DIR}/cmschedules_prompt.html", "w").write(html or "")
            log.info("schedule lookup prompt page saved (%d chars): %s", len(html or ""), visible_text(html)[:200])
            S["cm_prompt_captured"] = True
            save_state(S)
            time.sleep(random.uniform(1.0, 2.0))
        except Exception as e:
            log.info("schedule lookup prompt capture skipped: %s", e)
    emp = req["emp"]
    cur = local_now()
    bd = f"{cur.month:02d}{cur.year % 100:02d}"
    try:
        sched, html = None, ""
        for i, url in enumerate((IF.CM_SCHED.format(base=BASE, emp=emp), IF.CM_SCHED_MONTH.format(base=BASE, emp=emp, bd=bd))):
            if i:
                time.sleep(random.uniform(1.5, 3.5))
            html = fl.fetch(url)
            sched = IF.parse_cm_month(html) if classify(html) == "ok" and IF.schedule_ok(html) else None
            if sched:
                break
            log.info("pilot %s: %s gave %s: %s", emp, url.split("?")[1], classify(html), visible_text(html)[:200])
        if not sched:
            pub("pilot_schedule", {"emp": emp, "name": req.get("name") or "", "status": f"not readable: {classify(html)} {visible_text(html)[:120]}",
                                   "month": "", "days": [], "items": [], "totals": {}, "updated": "", "fetched": now_iso()})
            log.info("pilot %s: schedule page not readable (%s)", emp, classify(html))
            S.pop("pilot_req", None)
            save_state(S)
            return True
        n = 0
        for it in sched["items"]:
            if not PAIRING_RE.match(it["trip"]) or n >= PILOT_PAIRINGS_MAX:
                continue
            n += 1
            time.sleep(random.uniform(1.5, 3.5))
            page = fl.fetch(f"{BASE}/full/mobilepairing.cgi?PID={it['trip']}&DATE={it['start'].replace('-', '')}"
                            "&FROM=MobileOpentimePot&CurrentPage=1")
            if classify(page) != "ok":
                continue
            d = parse_detail(page)
            it.update({k: d.get(k, "") for k in ("blk", "credit", "captain", "tafb")})
            it["soft"] = soft_time(it.get("credit"), it.get("blk")) or ""
            txt = visible_text(page)
            DB.remember_crew(txt)
            it["legs"] = [{"dow": dw, "route": f"{a}-{b}".upper(), "dep": dep, "arr": arr, "blk": blk}
                          for dw, a, b, dep, arr, blk in LEG_FULL_RE.findall(txt)][:12]
            it["crew"] = parse_crew(txt)[:6]
        rec = {**sched, "emp": emp, "name": sched.get("name") or req.get("name") or "", "bd": bd,
               "fetched": now_iso(), "fetched_ts": time.time()}
        DB.put(f"pilot_sched:{emp}", rec)
        pub("pilot_schedule", {**rec, "status": "ok"})
        log.info("pilot %s (%s): %s read, %d items, %d pairing pages", emp, rec["name"], sched["month"], len(sched["items"]), n)
    except Exception as e:
        log.info("pilot %s: schedule read failed: %s", emp, e)
        pub("pilot_schedule", {"emp": emp, "name": req.get("name") or "", "status": f"error: {e}", "month": "", "days": [],
                               "items": [], "totals": {}, "updated": "", "fetched": now_iso()})
    S.pop("pilot_req", None)
    save_state(S)
    return True


# ---------------------------------------------------------------- 0.7.0 charter watch (CrewTrac, read only)
CHARTER_WAKE = threading.Event()


def publish_charters(status=""):
    known = DB.get("charters") or {}
    items = sorted(known.values(), key=lambda r: (r.get("date", ""), r.get("scheduled", "")))
    pub("charters", {"count": len([r for r in items if not r.get("gone")]), "items": items,
                     "last_scan": DB.get("charter_scan_at") or "", "status": status or DB.get("charter_status") or "",
                     "regular": sorted(CH.regular_set(OPTS.get("charter_regular")))})


def charter_scan():
    """One read-only pass over CrewTrac Scheduled Service: HNL departures and arrivals for the next 30
    days, A330 rows that are 99xx or touch a non-regular station become sensor.flica_watcher_charters
    entries; each new one fires event/charter once (HA pushes it)."""
    u, p = (OPTS.get("ctweb_username") or "").strip(), OPTS.get("ctweb_password") or ""
    if not u or not p:
        DB.put("charter_status", "not configured: set ctweb_username and ctweb_password (CrewTrac) in the app Configuration tab")
        publish_charters()
        return False
    sess = requests.Session()
    sess.headers["User-Agent"] = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                                  "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
    def capture(name, html):  # 0.7.3: first pages saved privately (never committed) to check the parser
        try:
            os.makedirs(IF.CAPTURE_DIR, exist_ok=True)
            open(f"{IF.CAPTURE_DIR}/ctweb_{name}.html", "w").write(html or "")
        except Exception as e:
            log.info("charter capture skipped: %s", e)
    sc = CH.Scanner(sess, u, p, log, sleep=lambda: time.sleep(random.uniform(1.0, 2.5)), capture=capture)
    today = local_now().date()
    try:
        if not sc.login():
            DB.put("charter_status", f"CrewTrac login failed at {local_now().strftime('%H:%M')} HST; one try per scan")
            publish_charters()
            return False
        rows = sc.scan(today)
    except Exception as e:
        DB.put("charter_status", f"scan error: {e}")
        log.info("charter scan error: %s", e)
        publish_charters()
        return False
    if rows is None:
        DB.put("charter_status", "CrewTrac session dropped mid-scan")
        publish_charters()
        return False
    found = CH.unusual(rows, CH.regular_set(OPTS.get("charter_regular")))
    regular = CH.regular_set(OPTS.get("charter_regular"))
    known, new = CH.merge(CH.prune(DB.get("charters") or {}, regular), found, today.isoformat())
    DB.put("charters", known)
    DB.put("charter_scan_at", now_iso())
    DB.put("charter_status", f"ok: {len(rows)} rows, {len(found)} unusual A330, {len(new)} new")
    log.info("charter scan: %d rows, %d unusual A330 flights, %d new", len(rows), len(found), len(new))
    for k in new:
        r = known[k]
        log.info("CHARTER %s %s %s %s (%s)", r.get("date"), r.get("flight"), r.get("route"), r.get("eqpt"), r.get("why"))
        pub("event/charter", {"key": k, **{f: r.get(f) for f in ("date", "flight", "route", "scheduled", "eqpt", "tail", "why")}},
            retain=False)
    publish_charters()
    return True


def charter_thread():
    """Every 6 h (or on the Scan button) in its own thread: CrewTrac is a separate site and session, so
    this never touches the FLICA session or delays the pot checks."""
    while True:
        last = DB.get("charter_scan_at")
        due = 0  # 0.7.1: no scan yet = scan now (0.7.0 waited the full 6 h first)
        if last:
            try:
                due = CH.SCAN_EVERY_S - (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds()
            except ValueError:
                due = 0
        CHARTER_WAKE.wait(max(30, due + random.uniform(0, 600)) if not CHARTER_WAKE.is_set() else 0)
        CHARTER_WAKE.clear()
        try:
            charter_scan()
        except Exception as e:
            log.info("charter thread: %s", e)


def publish_swap_tests():
    tests = S.get("swap_tests") or []
    pub("swap_tests", {"count": len(tests), "tests": tests[-20:], "mode": S.get("swap_mode") or SUB.DEFAULT_MODE})


def swap_test(idea):
    """0.5.0 Test mode: compose the exact mobileotswap.cgi POST a live swap would send for this idea,
    log it, keep the last 20 (sensor.flica_watcher_swap_test_requests) and push event/swap_test.
    Never sends: submit.WRITES_IMPLEMENTED is False."""
    b = sorted({bcid(u) for u in S.get("pot_urls", {}).values() if bcid(u)}, key=bcid_key)
    rep_h = None
    if idea.get("report") and idea.get("start"):
        rep_h = SUB.hours_until(f"{idea['start']}T{idea['report'][:5]}", local_now())
    seat = "R" if (S.get("own_trips", {}).get(idea["for"]) or {}).get("seat") == "RO" else "F"
    rec = SUB.compose(idea, b[0] if b else None, rep_h, seat=seat, close_in_bcid=S.get("close_in_bcid"))
    rec.update({"key": idea["key"], "at": now_iso(), "mode": S.get("swap_mode") or SUB.DEFAULT_MODE,
                "hours_to_report": round(rep_h, 1) if rep_h is not None else None, "sent": False})
    tests = S.setdefault("swap_tests", [])
    tests.append(rec)
    del tests[:-20]
    log.info("SWAP TEST (not sent): give %s take %s folder %s bcid %s form %s", rec["give"], rec["take"],
             rec["folder"], rec["bcid"], rec["form"])
    pub("event/swap_test", rec, retain=False)
    publish_swap_tests()


def swap_scan(pot_rows):
    """0.4.9 (Ryan): for each trip he marked 'would trade', find open time and Tradeboard pickups
    that are better (swap.better: more soft time, or more credit) and still legal once his trip is
    gone: FAR screen with that trip removed must read plain 'OK' (no CBA-rest note: PWA 10.E.1.a
    wants 11 h in domicile), no VAC, no blocked day, no clash with his other trips. New ideas push
    once (event/swap). With the Auto swap switch on, the event also says what a live swap WOULD
    submit; nothing is ever submitted (swap.WRITES_IMPLEMENTED is False)."""
    marks = S.get("trade_away") or []
    own = S.get("own_trips", {})
    rows = [dict(r, src="O") for r in pot_rows] + [dict(r, src="T") for r in S.get("tb_details", {}).values()]
    ideas = []
    for mk in marks:
        mine = own.get(mk) or {}
        trip = mk.split("|")[0]
        for row in rows:
            if row.get("pairing") == trip or touches_vac(row) or touches_blocked(row):
                continue
            ok, ds, dc, why = SW.better(row, mine)
            if not ok:
                continue
            far = far_for(row, exclude=mk)
            if far != "OK":
                continue
            mine_it = next((it for it in _sched_items() if f"{it['trip']}|{it['start']}" == mk), None)
            mine_days = [(date.fromisoformat(mine_it["start"]) + timedelta(days=i)).isoformat()
                         for i in range((date.fromisoformat(mine_it["end"]) - date.fromisoformat(mine_it["start"])).days + 1)] if mine_it else []
            ok_grid, bad_days = G.swap_allowed(S.get("grid") or {}, mine_days, _trip_days(row))
            grid_note = "grid OK" if ok_grid else ("no shared day" if bad_days == ["no shared day"] else "grid red " + ", ".join(d[5:] for d in bad_days))
            ideas.append({"for": mk, "for_trip": trip, "for_credit": mine.get("credit", ""),
                          "for_soft": mine.get("soft", ""), "pairing": row.get("pairing"),
                          "start": row.get("start"), "end": row.get("end"), "dates": row.get("dates"),
                          "days": row.get("days"), "layover": row.get("layover"), "turn": row.get("turn"),
                          "credit": row.get("credit"), "soft": row.get("soft"), "src": row["src"],
                          "soft_gain": SW.fmt_gain(ds), "credit_gain": SW.fmt_gain(dc), "why": why,
                          "detail_url": row.get("detail_url", ""), "gain_h": round(ds + dc / 10, 3),
                          "grid_ok": ok_grid, "grid": grid_note})
    ideas.sort(key=lambda i: -i["gain_h"])
    seen = set(S.get("swap_seen") or [])
    today = local_now().date().isoformat()
    for i in ideas:
        if not i["grid_ok"]:
            continue
        k = f"{i['pairing']}|{i['start']}>{i['for']}"
        if k in seen:
            continue
        seen.add(k)
        ev = dict(i, key=k, at=now_iso())
        swap_test(dict(i, key=k, report=next((r.get("report", "") for r in rows if r.get("pairing") == i["pairing"] and r.get("start") == i["start"]), "")))
        if S.get("auto_swap"):
            done = S.setdefault("auto_swap_log", {})
            if done.get(today, 0) < AUTO_SWAP_PER_DAY:
                done[today] = done.get(today, 0) + 1
                ev["would_submit"] = f"DRY RUN: drop {i['for_trip']} {i['for'].split('|')[1]}, add {i['pairing']} {i['start']}"
                log.info("auto swap %s (dry run, nothing submitted)", ev["would_submit"])
            else:
                ev["would_submit"] = f"DRY RUN: daily cap of {AUTO_SWAP_PER_DAY} reached, not even dry-run counted"
        log.info("swap idea %s: %s (%s)", i["for_trip"], i["pairing"], i["why"])
        pub("event/swap", ev, retain=False)
    live = {f"{i['pairing']}|{i['start']}>{i['for']}" for i in ideas if i["grid_ok"]}
    S["swap_seen"] = sorted(seen & live)  # an idea that goes away can alert again if it comes back
    S["auto_swap_log"] = {d: n for d, n in (S.get("auto_swap_log") or {}).items() if d >= today}
    save_state(S)
    pub("swap/state", {"count": len(ideas), "ideas": ideas[:30], "marked": marks})


PICKUP_FIRST_S = 120      # FLICA updates the crew line shortly after the pot drops it
PICKUP_RETRY_S = 20 * 60  # while unknown, or in the first 2 h after it left the pot
PICKUP_OPEN_S = 60 * 60   # still open after that: recheck hourly until the trip starts
PICKUP_TRIES = 6
PICKUP_PER_CHECK = 3


def pickup_check(fl, full=False):
    """Read only (0.3.7): when a find leaves the pot, GET its pairing page and record who now holds
    the FO/RO seat that was open, plus the CA. A seat still Open on the pairing page while the trip
    is not in the open time pot is stored as status 'open' (dashboard: suspected hidden by
    scheduling) and rechecked hourly until it is filled or the trip starts. Gone finds from before
    0.3.7 are back-filled once. Returns True when any pickup record changed."""
    pend = S.setdefault("pickup_pending", {})
    if not S.get("email_unchanged_fixed"):  # 0.4.2: email finds 0.4.1 wrongly marked 'same crew'
        for k in DB.email_unchanged():
            DB.clear_pickup(k)
            pend.setdefault(k, {"tries": 0, "next": 0})
        S["email_unchanged_fixed"] = True
    if not S.get("email_details_fixed"):  # 0.4.3: re-read email finds once (bad credit, no days)
        for k in DB.email_finds():
            DB.clear_pickup(k)
            pend.setdefault(k, {"tries": 0, "next": 0})
        S["email_details_fixed"] = True
    if not S.get("pickup_backfilled"):
        for k in DB.gone_without_pickup(50):
            pend.setdefault(k, {"tries": 0, "next": 0})
        S["pickup_backfilled"] = True
    if not S.get("pickers_scored"):  # 0.4.18: score every finished pickup once
        for k in DB.unscored_pickups():
            DB.score_pickup(k)
        S["pickers_scored"] = True
    if not S.get("ids_backfilled"):  # 0.4.17 (Ryan): add employee numbers to finds recorded before 0.4.11
        for k in DB.pickups_without_ids(50):
            pend.setdefault(k, {"tries": 0, "next": 0})
        S["ids_backfilled"] = True
    done, now, n = False, time.time(), 0
    for k, p in list(pend.items()):
        if n >= (FULL_MAX if full else PICKUP_PER_CHECK):
            break
        if now < p.get("next", 0) and not full:
            continue
        row = DB.find_row(k)
        url = row and (row.get("detail_url") or detail_url(row))
        if not url:
            pend.pop(k, None)
            continue
        if n:
            time.sleep(random.uniform(1.5, 3.5))
        n += 1
        p["tries"] = p.get("tries", 0) + 1
        status, who, ca, seats, known = "unknown", "", "", [], False
        try:
            page = fl.fetch(url)
            if classify(page) == "ok":
                vt = visible_text(page)
                crew = parse_crew(vt)
                ids = crew_ids(vt)
                if row.get("source") == "email":  # 0.4.3: email finds get credit/days/blk from the page
                    d = parse_detail(page)
                    DB.patch_row(k, {f: d[f] for f in ("credit", "days", "blk", "tafb") if d.get(f)})
                seats = [x for x in (row.get("open_seats") or "").split(",") if x]
                before = row.get("crew")
                if before is not None:
                    status, who, known = pickup_diff([tuple(x) for x in before], crew)
                else:  # found before 0.4.0: no roster to compare, fall back to open_seats
                    status, who = pickup_result(crew, seats)
                    known = bool(seats)
                ca = next((nm for pos, nm in crew if pos == "CA" and nm != "OPEN"), "")
                who, ca = with_ids(who, ids), with_ids(f"CA {ca}", ids)[3:] if ca else ""
        except Exception as e:
            log.info("pickup lookup %s skipped: %s", k, e)
        start = row_date(row.get("start") or (row.get("dates") or "").split("-")[0])
        started = bool(start and start < local_now().date())
        if status == "filled":
            DB.set_pickup(k, {"status": "filled", "by": who, "ca": ca, "known": known,
                              "at": now_iso()})
            log.info("pickup %s: %s (CA %s)", k, who, ca or "?")
            secs = DB.score_pickup(k)  # 0.4.18: picker speed stats
            if secs is not None:
                log.info("picker %s: %s in open time", who, secs)
            pend.pop(k, None)
            done = True
        elif status == "open":
            DB.set_pickup(k, {"status": "open", "by": who, "ca": ca, "known": known,
                              "at": now_iso()})
            if p.get("logged") != "open":
                log.info("pickup %s: seat still Open on the pairing page but not in the pot "
                         "(suspected hidden)", k)
                p["logged"] = "open"
                # 0.4.3: HA pushes this (automation "FLICA watcher hidden trip")
                pub("event/hidden", {"key": k, **{f: row.get(f) for f in (
                    "pairing", "start", "end", "dates", "days", "layover", "turn", "credit", "soft",
                    "depart", "arrive", "detail_url", "source")}, "captain": ca or row.get("captain"),
                    "vac": touches_vac(row), "blocked": touches_blocked(row),
                    "gone": now_iso()}, retain=False)
            done = True
            if started:
                pend.pop(k, None)
            else:
                p["next"] = now + (PICKUP_RETRY_S if p["tries"] < PICKUP_TRIES else PICKUP_OPEN_S)
        elif status == "unchanged":
            DB.set_pickup(k, {"status": "unchanged", "by": "", "ca": ca, "known": True, "at": now_iso()})
            log.info("pickup %s: left the pot with the same FO/RO crew", k)
            pend.pop(k, None)
            done = True
        elif p["tries"] >= PICKUP_TRIES or started:
            DB.set_pickup(k, {"status": "unknown", "by": "?", "ca": ca, "at": now_iso()})
            pend.pop(k, None)
            done = True
        else:
            p["next"] = now + PICKUP_RETRY_S
    save_state(S)
    if inflt_check(fl, FULL_MAX if full else INFLT_PER_CHECK):
        done = True
    if pilot_check(fl):  # 0.8.0: a tapped picker's month
        done = True
    return done


INFLT_PER_CHECK = 3


def inflt_check(fl, limit=INFLT_PER_CHECK):
    """0.5.2 (Ryan): was the picker in flight when the trip left the pot? See inflt.py (0.5.3)."""
    if not S.get("inflt_reset_v3"):
        DB.reset_inflt()
        S["inflt_reset_v3"] = True
        save_state(S)
    changed = IF.run(fl, DB, limit, log, local_now, BASE, HST)
    if changed:
        publish_finds()
    return changed


FP_VERSION = 2  # bump when header_fingerprint changes, so stored hashes are re-learned


def email_alert(payload):
    """0.4.1: HA forwards each FLICA alert email (imap_content) here. Pairings it names that the
    pot watch never saw are queued; the next check (woken now) reads them and adds them to finds."""
    try:
        d = json.loads(payload)
    except ValueError:
        d = {"text": payload}
    items = parse_alert_email(f"{d.get('subject', '')}\n{d.get('text', '')}")
    try:  # HA sends the mail date as '2026-11-01 15:36:31-10:00'; store UTC ISO like every find
        at = datetime.fromisoformat(str(d.get("date"))).astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError):
        at = now_iso()
    q = S.setdefault("email_queue", [])
    for it in items:
        if not any(x["key"] == it["key"] for x in q):
            q.append(dict(it, at=at))
    log.info("alert email: %s", [it["key"] for it in items] or "no pairings")
    if items:
        WAKE.set()


def email_check(fl, pot_all):
    """Add pairings from alert emails that are not finds yet (the pot moved faster than a check).
    One read-only detail GET each, so CA, times and the crew roster are known; a pairing not in
    the pot any more is stamped gone now and its pickup is tracked like any other find."""
    q = S.get("email_queue") or []
    if not q:
        return False
    live = {k: m for m, p in pot_all.items() for k in p}
    added, n = False, 0
    for it in list(q):
        k = it["key"]
        if DB.has_find(k):
            if it.get("at") and DB.set_alert_at(k, it["at"]):  # 0.7.6: FLICA's alert time is the true pot-entry time
                log.info("alert email: %s entered the pot at %s (Pickup Speed rescored)", k, it["at"])
            # 0.4.21 (Ryan): a known find named in a fresh alert went back to open time; re-read its page
            # so "who holds it now" is current, instead of trusting the old pickup record.
            row = DB.find_row(k) or {}
            if k not in live and row.get("source") != "email":
                S.setdefault("pickup_pending", {})[k] = {"tries": 0, "next": 0, "realert": True}
                log.info("alert email names known find %s: pickup re-check queued", k)
            q.remove(it)
            continue
        if n >= FULL_MAX:
            break
        if n:
            time.sleep(random.uniform(1.5, 3.5))
        n += 1
        ev = {"pairing": it["pairing"], "start": it["start"], "dates": it["start"], "source": "email",
              "alert_sources": it.get("sources", [])}
        enrich(fl, ev)
        if ev.get("turn") and not ev.get("layover"):
            ev["layover"] = ev["turn"].split("/")[0]
        month = next(iter(S.get("pot_urls") or {"mobile": 1}))
        gone = None if k in live else now_iso()
        if gone:  # roster read after it left the pot: no "before" to diff, so names stay unbolded
            ev.pop("crew", None)
        DB.add_find(k, month, ev, it.get("at") or now_iso(), gone)
        if gone:
            S.setdefault("pickup_pending", {}).setdefault(k, {"tries": 0, "next": 0})
        log.info("finds: %s added from alert email (%s)", k, "in pot" if k in live else "already gone")
        q.remove(it)
        added = True
    save_state(S)
    return added


def check(fl):
    """One pass. Returns next action hint. After Check now (FLAGS full) every cached read is
    refreshed too: schedule, own trip times, pot details, pending pickups, tradeboard."""
    full, FLAGS["full"] = FLAGS.get("full", False), False
    if not S.get("pot_urls"):
        urls = fl.discover_pot_urls()
        if urls is None:
            return "needs_login"
        if not urls:
            set_machine("stopped_unexpected", f"no 'View Opentime Pot' found under '{OPTS['pot_section']}'")
            return "stop"
        S["pot_urls"] = urls
        S["discovered_at"] = time.time()
        save_state(S)
        log.info("pot pages: %s", list(urls))
    schedule_check(fl, force=full or not S.get("schedule"))
    own_trip_times(fl, full)
    versions_check()
    uploads_check()
    pot_all = {}
    new_any = False
    for month, url in list(S["pot_urls"].items()):
        html = fl.fetch(url)
        kind = classify(html)
        if kind == "killed":
            return "killed"
        if kind == "blocked":
            set_machine("stopped_unexpected", "FLICA showed a captcha/MFA/password page")
            return "stop"
        if kind == "expired":
            return "needs_login"
        if not is_pot_page(html, mobile=month.startswith("mobile")):
            S["pot_urls"] = {}
            S["parse_fail"] = S.get("parse_fail", 0) + 1
            save_state(S)
            if S["parse_fail"] >= 3:
                set_machine("stopped_unexpected", "open time page no longer recognised (3 in a row)")
                return "stop"
            return "retry"
        S["parse_fail"] = 0
        fp = header_fingerprint(html)
        if fp:
            old = S["fingerprints"].get(month)
            if old is None:
                S["fingerprints"][month] = fp
                log.info("pot header fingerprint %s: %s", month, fp)
            elif old != fp and layout_still_parses(html):
                # Self re-arm (0.3.5): the hash moved but every row still parses, so accept it
                # instead of going blind until someone presses Re-arm.
                log.warning("pot header fingerprint %s changed %s -> %s; rows still parse, accepted",
                            month, old, fp)
                S["fingerprints"][month] = fp
                S["fp_accepts"] = S.get("fp_accepts", 0) + 1
            elif old != fp:
                set_machine("stopped_unexpected",
                            f"pot table layout changed on {month} ({old} -> {fp}); not parsing it. "
                            "Check the page, then Re-arm to accept the new layout")
                S["fingerprint_pending"] = {month: fp}
                save_state(S)
                return "stop"
        pot = parse_pot(html)
        pot_all[month] = pot
        capture(fl, month, html)
        detail_probe(fl, pot)
        pot_details(fl, pot, full)
        base = S["baseline"].get(month)
        new_keys = set()
        if base is None:
            log.info("baseline %s: %d pairings (no alert)", month, len(pot))
        else:
            new_keys = {k for k in pot if k not in base}
            for k in sorted(new_keys):
                ev = {**pot[k], "month": month, "seen": now_iso()}
                if not ev.get("detail_url"):  # pot_details already read it when cached
                    enrich(fl, ev)
                log.info("NEW pairing %s", ev)
                pub("event/new_pairing", ev, retain=False)
                pub("last_new", ev)
                run_rules(month, k, pot[k])
        if base is not None:
            pend = S.setdefault("pickup_pending", {})
            for k in set(base) - set(pot):
                pend.setdefault(k, {"tries": 0, "next": time.time() + PICKUP_FIRST_S})
        DB.record_pot(month, pot, new_keys)
        new_any = new_any or bool(new_keys)
        S["baseline"][month] = sorted(pot.keys())
    # drop months no longer published, and cached details of pairings no longer in any pot
    S["baseline"] = {m: v for m, v in S["baseline"].items() if m in S["pot_urls"]}
    live = {k for p in pot_all.values() for k in p}
    S["details"] = {k: v for k, v in S.get("details", {}).items() if k in live}
    S["relogin_streak"] = 0
    save_state(S)
    flat = [dict(v, month=m) for m, p in pot_all.items() for v in p.values()]
    pub("pot/state", {"count": len(flat), "pairings": flat[:60]})
    email_check(fl, pot_all)
    pickup_check(fl, full)
    publish_finds()  # rows carry live CA / details now, so publish every check
    tradeboard_check(fl, full)
    grid_check(fl, full)
    swap_scan(flat)
    drop_scan()
    if FLAGS.pop("swap_map", False):
        swap_map_probe(fl)
    pub("last_check", now_iso())
    S["last_check_ts"] = time.time()
    if S.get("note") in ("starting",) or (S.get("note") or "").startswith("logged in"):
        set_machine(S.get("machine", "idle"), "")
    pub("session", "ON")
    return "ok"


def main():
    global MQ
    MQ = mqtt_start()
    time.sleep(2)
    if not OPTS.get("username") or not OPTS.get("password"):
        set_machine("stopped_unexpected", "set username and password in the add-on Configuration tab")
    elif S.get("machine", "").startswith("stopped"):
        set_machine(S["machine"], S.get("note", "") + " (still stopped after restart, press Re-arm)")
    else:
        set_machine("idle", "starting")
    if S.get("fp_version") != FP_VERSION:
        S["fingerprints"] = {}
        S["fp_version"] = FP_VERSION
        save_state(S)
        log.info("pot header fingerprints cleared for fingerprint v%d", FP_VERSION)
    if DB.get("crew_dir_v") != 1:  # 0.8.2 one-shot: seed the crew directory from pickers and captains already recorded
        n = 0
        for e, v in DB.picker_stats().items():
            DB.remember_person(e, v["name"], v["pos"])
            n += 1
        for f in DB.recent_finds(500):
            for who in (f.get("picked_by") or "").split("; ") + [("CA " + f["captain"]) if f.get("captain") else ""]:
                m = re.match(r"(CA|FO|RO)\s+(.*?)\s*\((\d{3,7})\)\s*$", who or "")
                if m:
                    DB.remember_person(m.group(3), m.group(2), m.group(1))
                    n += 1
        DB.put("crew_dir_v", 1)
        log.info("crew directory seeded with %d names (%d total)", n, DB.crew_count())
    if DB.get("score_v") != 2:  # 0.7.6 one-shot: Pickup Speed recomputed with the vetted dwell() for every scored pickup
        DB.rescore_all()
        DB.put("score_v", 2)
        log.info("pickup speeds rescored (0.7.6 dwell: alert time in, middle of the gone window out)")
    RULES["list"] = load_rules()
    publish_rules(MQ)
    publish_finds()
    publish_blocked()
    publish_tradeboard()
    publish_own_trips()
    publish_trade()
    publish_charters()
    publish_improved()
    versions_check(force_pub=True)
    uploads_check()
    threading.Thread(target=charter_thread, daemon=True, name="charter").start()
    web.serve(int(os.environ.get("INGRESS_PORT", "8099")), VERSION, lambda: RULES["list"],
              save_rules_from_page, DB, log)
    last_month_check = None
    with sync_playwright() as pw:
        fl = Flica(pw)
        while True:
            st = S.get("machine", "idle")
            if FLAGS["rearm"]:
                FLAGS["rearm"] = False
                if st.startswith("stopped") or st in ("yielded", "backoff"):
                    S["kills"] = []
                    S["pot_urls"] = {}
                    S["parse_fail"] = 0
                    S["relogin_streak"] = 0
                    if S.pop("fingerprint_pending", None):
                        S["fingerprints"] = {}  # Re-arm after a layout park accepts the new layout
                        log.info("re-arm: pot header fingerprints cleared, re-learned on next check")
                    try_login(fl, "re-arm")
                    continue
            if st.startswith("stopped"):
                no_next_check()
                sleep(3600)
                continue
            if FLAGS["pause"]:
                if st != "paused":
                    set_machine("paused", "paused from HA")
                no_next_check()
                sleep(3600)
                continue
            if st == "paused":
                if not try_login(fl, "un-pause"):
                    continue
                st = S["machine"]
            if st == "yielded":
                wait_until = S.get("yield_until", 0)
                if time.time() < wait_until:
                    sleep_announced(wait_until - time.time())
                    continue
                if not try_login(fl, "after yield cooldown"):
                    continue
            if st == "backoff":
                wait_until = S.get("relogin_at", 0)
                if time.time() < wait_until:
                    sleep_announced(wait_until - time.time())
                    continue
                try_login(fl, f"backoff step {S.get('relogin_streak', 0)}")
                continue
            # next bid month: its pot link appears mid-month, so rediscover every 6 h until found
            if (OPTS.get("watch_next_month", True) and 0 < len(S.get("pot_urls") or {}) < 2
                    and time.time() - S.get("discovered_at", 0) > 6 * 3600):
                log.info("rediscovering pot pages to look for the next bid month")
                S["pot_urls"] = {}
            if time.time() - S.get("pruned_at", 0) > 86400:
                DB.prune()
                S["pruned_at"] = time.time()
            # month rollover: rediscover once per new calendar month
            mk = local_now().strftime("%Y-%m")
            if last_month_check and last_month_check != mk:
                S["pot_urls"] = {}
            last_month_check = mk
            try:
                res = check(fl)
            except Exception as e:
                log.warning("check error: %s", e)
                S["net_fail"] = S.get("net_fail", 0) + 1
                if S["net_fail"] >= 3:
                    set_machine("stopped_unexpected", f"3 check errors in a row: {e}")
                sleep_announced(gap())
                continue
            S["net_fail"] = 0
            if res == "needs_login":
                pub("session", "OFF")
                streak = S.get("relogin_streak", 0)
                if streak >= len(BACKOFF_MIN):
                    set_machine("stopped_unexpected",
                                f"session lost {streak} times in a row with no good check between; parked")
                    continue
                wait = BACKOFF_MIN[streak]
                S["relogin_streak"] = streak + 1
                S["relogin_at"] = time.time() + wait * 60
                set_machine("backoff", f"session expired, one login attempt in {wait} min "
                                       f"(step {streak + 1}/{len(BACKOFF_MIN)})")
                continue
            if res == "killed":
                pub("session", "OFF")
                now = time.time()
                S["kills"] = [k for k in S.get("kills", []) if now - k < 86400] + [now]
                recent = [k for k in S["kills"] if now - k < 6 * 3600]
                mult = 2 ** max(0, len(recent) - 1)
                cool = min(OPTS["yield_cooldown_min"] * 60 * mult, 4 * 3600)
                S["yield_until"] = now + cool
                set_machine("yielded", f"Ryan logged in elsewhere, back in {int(cool / 60)} min")
                continue
            if res == "stop":
                pub("session", "OFF")
                continue
            if res == "ok":
                want = "hunting" if FLAGS["hunt"] else "idle"
                if S["machine"] != want:
                    set_machine(want)
            sleep_announced(gap())


if __name__ == "__main__":
    main()
