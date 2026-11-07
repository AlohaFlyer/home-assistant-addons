"""Flight Watcher: one kept-alive FLICA session, open time pot diff, HA over MQTT.

Login rule: never two login attempts in a row without a success in between.
A failed login, or anything unexpected, parks the watcher until re-armed from HA.
FLICA is read only: rules match and log, nothing is ever submitted to FLICA.
"""
import hashlib
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
import far as FAR
from pot import PAIRING_RE, LEG_FULL_RE, schedule_items, parse_schedule_desktop, parse_legs, parse_cm_schedule, inflight_at, crew_ids, with_ids, parse_alert_email, fit_tag, hours, parse_crew, pickup_diff, pickup_result, layout_still_parses, parse_schedule, row_date, BLOCK_HINTS, detail_url, parse_detail, soft_time, bcid, bcid_after, bcid_key, classify, CLOSE_IN_RE, close_in_folders, pick_close_in, header_fingerprint, is_pot_page, parse_pot, pot_links, visible_text
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
import recall as RC
import ccr as CCR
import crewidx as CI
import tickets as TK
import sealed as SEAL
import pay as PAY
import seniority as SEN
import wwwfiles as WF
import trades as TR

VERSION = "1.4.7"
BASE = "https://ha2.flica.net"
DATA = os.environ.get("FLIGHT_WATCHER_DATA", "/data")
STATE_FILE = f"{DATA}/state.json"
DB_FILE = f"{DATA}/watcher.db"
RULES_FILE = f"{DATA}/rules.json"
COOKIES = f"{DATA}/storage_state.json"
# 0.10.0: a second pilot runs as another watcher.py from the same add-on (run.py). The instance gets its own
# MQTT prefix (T), its own /data folder and its own credentials (creds.json, set over MQTT); the add-on
# options stay Ryan's.
T = os.environ.get("FLIGHT_WATCHER_PREFIX", "flight_watcher")
INSTANCE = os.environ.get("FLIGHT_WATCHER_INSTANCE", "")
OPTIONS_FILE = os.environ.get("FLIGHT_WATCHER_OPTIONS", f"{DATA}/options.json")
CREDS_FILE = f"{DATA}/creds.json"
KEY_FILE = f"{DATA}/settings_key.pem"  # 1.1.0: this instance's key for sealed settings from the dashboard card
_KEY = {}
WWW_KEY_FILE = f"{DATA}/www_key"  # FW-0010: this instance's random key in the finds file names under /local/ (wwwfiles.py)


def settings_key():
    if "k" not in _KEY:
        _KEY["k"] = SEAL.load_key(KEY_FILE)
    return _KEY["k"]


def www_key():
    """FW-0010: the 128-bit key in this instance's finds file names (made once, kept in /data). Published only in
    sensor.<prefix>_finds (attribute file_key, behind HA's login); never logged."""
    if "w" not in _KEY:
        _KEY["w"] = WF.load_key(WWW_KEY_FILE)
    return _KEY["w"]
CRED_KEYS = ("username", "password", "ctweb_username", "ctweb_password", "my_name")


def load_creds():
    """creds.json: the per-pilot values set over {T}/settings/set (never the add-on options). {} when absent."""
    try:
        if os.path.exists(CREDS_FILE):
            d = json.load(open(CREDS_FILE))
            return d if isinstance(d, dict) else {}
    except Exception:
        pass
    return {}


def load_opts():
    """Add-on options; an instance drops Ryan's credentials from them, then creds.json (non-empty keys only)
    overlays for any instance."""
    o = json.load(open(OPTIONS_FILE))
    if INSTANCE:
        for k in CRED_KEYS:
            o.pop(k, None)
        o.pop("second_pilot", None)
    for k, v in load_creds().items():
        if k in CRED_KEYS and isinstance(v, str) and v.strip():
            o[k] = v.strip()
    return o


OPTS = load_opts()

logging.basicConfig(
    level=getattr(logging, OPTS.get("log_level", "info").upper()),
    format=f"%(asctime)s %(levelname)s {'[' + INSTANCE + '] ' if INSTANCE else ''}%(message)s",
)
log = logging.getLogger("flight_watcher")

MOBILE_POT = "https://ha2.flica.net/full/mobileopentimepot.cgi?BCID=003.152&From=MainMenu"
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December"]
BACKOFF_MIN = [1, 2, 4, 8, 16, 30]  # minutes before each re-login on repeated needs_login; then park
HST = timezone(timedelta(hours=-10))

AVAIL = f"{T}/status"
# Rule switches: <T>_rule_<id>_live for every instance (switch.flight_watcher_rule_<id>_live for Ryan)
RULE_UID = f"{T}_rule"
SHARE = f"/share/flight_watcher/{INSTANCE}" if INSTANCE else "/share/flight_watcher"


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
# FW-0024: the Hunt mode and Pause switches are kept in state as well as on their retained MQTT topics, and both are
# published a few seconds after every connect, so HA never shows them 'unknown' after a start.
SWITCHES = ("hunt", "pause")
FLAGS.update({k: bool((S.get("switches") or {}).get(k)) for k in SWITCHES})
CONNECT_STATES_DELAY_S = 3.0
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
    if msg.topic == f"{T}/recall/set":
        recall_cmd(msg.payload.decode(errors="replace"))
        return
    if msg.topic == f"{T}/recall/act":
        recall_act(msg.payload.decode(errors="replace"))
        return
    if msg.topic == f"{T}/settings/set":
        settings_cmd(msg.payload.decode(errors="replace"))
        return
    if msg.topic == f"{T}/ticket/new":
        ticket_safe(ticket_new, msg.payload.decode(errors="replace"))
        return
    if msg.topic == f"{T}/ticket/image":
        ticket_safe(ticket_image, msg.payload.decode(errors="replace"))
        return
    if msg.topic == f"{T}/ticket/act":
        ticket_safe(ticket_act, msg.payload.decode(errors="replace"))
        return
    if msg.topic == f"{T}/ticket/edit":
        ticket_safe(ticket_edit, msg.payload.decode(errors="replace"))
        return
    if msg.topic == f"{T}/ticket/delete":
        ticket_safe(ticket_delete, msg.payload.decode(errors="replace"))
        return
    if msg.topic == f"{T}/trade/set":
        trade_cmd(msg.payload.decode(errors="replace"))
        return
    if msg.topic == f"{T}/drop/set":
        drop_cmd(msg.payload.decode(errors="replace"))
        return
    if msg.topic == f"{T}/auto_swap/set":
        S["auto_swap"] = msg.payload.decode().strip().upper() == "ON"
        save_state(S)
        c.publish(f"{T}/auto_swap/state", "ON" if S["auto_swap"] else "OFF", retain=True)
        log.info("auto swap %s (dry run: nothing is ever submitted)", S["auto_swap"])
        return
    p = msg.payload.decode().strip().upper()
    if msg.topic == f"{T}/hunt/set":
        set_switch(c, "hunt", p == "ON")
        log.info("hunt mode %s", FLAGS["hunt"])
    elif msg.topic == f"{T}/pause/set":
        set_switch(c, "pause", p == "ON")
        log.info("pause %s", FLAGS["pause"])
    elif msg.topic == f"{T}/rearm/press":
        FLAGS["rearm"] = True
        log.info("re-arm pressed")
    elif msg.topic in (f"{T}/hunt/state", f"{T}/pause/state"):
        if p in ("ON", "OFF"):  # the retained state restores the switch after a restart (an empty payload is no state)
            remember_switch("hunt" if "hunt" in msg.topic else "pause", p == "ON")
        return
    elif msg.topic == f"{T}/swap_map/press":
        FLAGS["swap_map"] = True  # 0.4.10: one read-only mapping pass on the next check
        log.info("swap map pressed: read-only mapping on the next check")
    elif msg.topic == f"{T}/pilot/set":
        pilot_cmd(msg.payload.decode(errors="replace"))
    elif msg.topic == f"{T}/crew_scan/press":
        if not INSTANCE:
            FLAGS["crew_scan"] = True  # 0.10.1: one crew index run, read in chunks over the next checks
            log.info("crew index run requested")
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


def remember_switch(key, on):
    """FW-0024: FLAGS plus the copy in state, saved only when it changes."""
    FLAGS[key] = on
    sw = S.setdefault("switches", {})
    if sw.get(key) != on:
        sw[key] = on
        save_state(S)


def set_switch(c, key, on):
    remember_switch(key, on)
    c.publish(f"{T}/{key}/state", "ON" if on else "OFF", retain=True)


def publish_switches(c):
    """FW-0024: switch.flight_watcher_hunt_mode and switch.flight_watcher_pause states, which used to go out only on a
    toggle (HA showed 'unknown' after every start, and the heartbeat-stale automation's 'pause is off' condition
    could never pass)."""
    for k in SWITCHES:
        set_switch(c, k, FLAGS[k])


def connect_states(c):
    """FW-0024: run CONNECT_STATES_DELAY_S after each connect, once the retained switch states subscribed in
    on_connect have restored FLAGS: the switches, and Would drop (count 0 when nothing is marked)."""
    try:
        publish_switches(c)
        publish_drop()
    except Exception as e:
        log.info("connect states skipped: %s", e)


def migrate_swap_mode():
    """FW-0028 (FLICA stays read-only for good): Confirm and Live are gone; a stored 'Confirm' / 'Live' (or anything
    but Test) becomes Test once, at start."""
    old = S.get("swap_mode")
    if old != SUB.DEFAULT_MODE:
        S["swap_mode"] = SUB.DEFAULT_MODE
        save_state(S)
        if old:
            log.info("swap mode %r retired: Test is the only mode (swap and drop requests are drafts, never sent)", old)


def publish_swap_mode(c):
    """FW-0028: sensor.flight_watcher_swap_mode, read only (was a Test / Confirm / Live select)."""
    c.publish(f"{T}/swap_mode/state", SUB.DEFAULT_MODE, retain=True)
    c.publish(f"{T}/swap_mode/attr", json.dumps({"sends": False, "writes_implemented": SUB.WRITES_IMPLEMENTED,
                                                  "note": f"swap and drop requests are drafts: {SUB.DRAFT}"}), retain=True)


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


DEV = {"identifiers": [T], "name": "Flight Watcher" + (f" ({INSTANCE.title()})" if INSTANCE else ""),
       "manufacturer": "Pako HI", "sw_version": VERSION}


def settings_state(creds=None, result=""):
    """What {T}/settings/state says: who is configured, never a password; plus the public key the dashboard card
    seals new settings with (1.1.0) and the result of the last settings message."""
    o = {**OPTS, **{k: v for k, v in (creds or {}).items() if k in CRED_KEYS and isinstance(v, str) and v.strip()}}
    st = {"instance": INSTANCE, "username": o.get("username") or "", "my_name": o.get("my_name") or "",
          "ctweb_username": o.get("ctweb_username") or "", "has_password": bool(o.get("password")),
          "has_ctweb_password": bool(o.get("ctweb_password")), "at": now_iso(), "result": result}
    try:
        st.update(SEAL.public_info(settings_key()))
    except Exception as e:  # noqa: BLE001 (no key: the card says so; Web UI and plain settings/set still work)
        log.info("settings key unavailable: %s", e)
    return st


def publish_settings(c=None, creds=None, result=""):
    (c or MQ).publish(f"{T}/settings/state", json.dumps(settings_state(creds, result)), retain=True)


def settings_cmd(payload):
    """0.10.0: {T}/settings/set {username?, password?, ctweb_username?, ctweb_password?, my_name?} merges the
    non-empty values into creds.json (mode 600), publishes settings/state (no passwords) and restarts this
    watcher after RESTART_DELAY_S so run.py brings it back with the new credentials."""
    try:
        d = json.loads(payload)
        if not isinstance(d, dict):
            raise ValueError("not an object")
    except (ValueError, TypeError) as e:
        log.info("settings ignored: %s", e)
        return False
    if "enc" in d:  # 1.1.0: sealed by the dashboard Settings card
        try:
            d = SEAL.open_sealed(settings_key(), d["enc"])
        except Exception as e:  # noqa: BLE001 (SealError, or no usable key: never let it reach paho's thread)
            msg = str(e) if isinstance(e, SEAL.SealError) else f"settings key unavailable ({type(e).__name__})"
            log.info("sealed settings refused: %s", msg)
            try:
                publish_settings(creds=load_creds(), result=f"refused: {msg}")
            except Exception:  # noqa: BLE001
                pass
            return False
    cur = load_creds()
    changed = []
    for k in CRED_KEYS:
        v = d.get(k)
        if isinstance(v, str) and v.strip() and cur.get(k) != v.strip():
            cur[k] = v.strip()
            changed.append(k)
    if not changed:
        log.info("settings: nothing new (keys %s)", ", ".join(sorted(k for k in d if k in CRED_KEYS)) or "none")
        publish_settings(creds=cur, result="nothing new")
        return False
    tmp = CREDS_FILE + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)  # never readable by others, even briefly
    with os.fdopen(fd, "w") as f:
        json.dump(cur, f)
    os.chmod(tmp, 0o600)
    os.replace(tmp, CREDS_FILE)
    if creds_stop_cleared(changed):  # kills (the yield back-off count) stay; only Re-arm clears those
        S["machine"], S["note"] = "idle", "new settings"
        S["pot_urls"], S["parse_fail"], S["relogin_streak"] = {}, 0, 0
        save_state(S)
    publish_settings(creds=cur, result="saved: " + ", ".join(changed))
    log.info("settings saved (%s); restarting in %d s to use them", ", ".join(changed), RESTART_DELAY_S)
    restart_later()
    return True


def still_waiting(now=None):
    """1.0.1: a yield to Ryan's own FLICA login, or a re-login back-off, that has not run out yet."""
    now = time.time() if now is None else now
    m = S.get("machine")
    return (m == "yielded" and now < S.get("yield_until", 0)) or (m == "backoff" and now < S.get("relogin_at", 0))


def settings_clear():
    """1.0.1: forget everything saved in creds.json (Web UI 'Use the Configuration tab'), so the add-on options
    apply again; restarts like a save. True when there was something to forget."""
    if not os.path.exists(CREDS_FILE):
        return False
    os.remove(CREDS_FILE)
    publish_settings(creds={})
    log.info("settings: saved values cleared, the Configuration tab applies; restarting in %d s", RESTART_DELAY_S)
    restart_later()
    return True


RESTART_DELAY_S = 2
NO_CREDS_NOTES = ("enter your FLICA username and password", "set username and password")


def creds_stop_cleared(changed):
    """1.0.1: a new FLICA username or password fixes only the stops it can fix: no credentials yet, or one login
    rejected (stopped_login_failed). A CAPTCHA/MFA/password-change stop or any other park keeps needing Ryan's
    Re-arm after he has dealt with FLICA himself, whatever is saved (FLICA's CAPTCHA/MFA is never worked around)."""
    if not ({"username", "password"} & set(changed)):
        return False
    m, note = str(S.get("machine", "")), str(S.get("note", ""))
    return m in ("needs_settings", "stopped_login_failed") or (
        m == "stopped_unexpected" and note.startswith(NO_CREDS_NOTES))


def restart_later():
    threading.Thread(target=_restart, daemon=True, name="restart").start()


def _restart():
    time.sleep(RESTART_DELAY_S)  # let the settings/state publish go out
    log.info("restarting for new settings")
    os._exit(3)


def publish_rules(c):
    """One live switch per rule via MQTT discovery; removes switches of deleted rules."""
    with RULE_LOCK:
        lst = list(RULES["list"])
    flags = DB.live_flags()
    ids = {r["id"] for r in lst}
    for rid in RULES["published"] - ids:
        c.publish(f"homeassistant/switch/{T}/rule_{rid}_live/config", "", retain=True)
        c.publish(f"{T}/rule/{rid}/live/state", "", retain=True)
        DB.drop_live(rid)
    for r in lst:
        cfg = {"availability_topic": AVAIL, "device": DEV, "name": f"Rule {r['name']} live",
               "unique_id": f"{RULE_UID}_{r['id']}_live", "object_id": f"{RULE_UID}_{r['id']}_live",
               "default_entity_id": f"switch.{RULE_UID}_{r['id']}_live",
               "command_topic": f"{T}/rule/{r['id']}/live/set", "state_topic": f"{T}/rule/{r['id']}/live/state",
               "icon": "mdi:rocket-launch", "entity_category": "config"}
        c.publish(f"homeassistant/switch/{T}/rule_{r['id']}_live/config", json.dumps(cfg), retain=True)
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
    old = [d for d in set(S.get("blocked_days") or []) if d < today]
    if old:  # 0.9.2: the recall check looks back at past days, so keep what was blocked
        DB.put("blocked_hist", sorted(set(DB.get("blocked_hist") or []) | set(old))[-400:])
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


DROP_PUB = {"at": 0}


def publish_drop():
    DROP_PUB["at"] = time.time()
    today = local_now().date().isoformat()
    live = {f"{it['trip']}|{it['start']}" for it in _sched_items() if it["start"] > today}  # 0.6.1: a started trip cannot be dropped
    if _sched_items():
        S["drop_away"] = [k for k in S.get("drop_away") or [] if k in live]
    save_state(S)
    pub("drop/state", {"count": len(S.get("drop_away") or []), "keys": S.get("drop_away") or [],
                       "ready": S.get("drop_ready") or {}, "tests": (S.get("drop_tests") or [])[-20:]})


def drop_scan():
    """0.6.0 Test mode: for each 'would drop' trip, check NET RESERVES on every day of the trip. The first
    time all days are green the Watcher pushes event/drop_ready and composes the drop request (logged, a
    draft only, never sent); a day turning red again re-arms the push. FW-0028: FLICA stays read-only, so the
    draft is all there is; Ryan files the drop himself."""
    marks = S.get("drop_away") or []
    if not marks:
        if not DROP_PUB["at"] or S.get("drop_ready"):  # FW-0024: Would drop reads 0, not 'unknown', with nothing marked
            S["drop_ready"] = {}
            publish_drop()
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
                    "mode": SUB.DEFAULT_MODE, "sent": False,
                    "hours_to_report": round(rep_h, 1) if rep_h is not None else None})
        ready[k] = rec["at"]
        tests = S.setdefault("drop_tests", [])
        tests.append(rec)
        del tests[:-20]
        log.info("DROP READY (%s): %s, grid green on %s; form %s", SUB.DRAFT, k, ", ".join(days), rec["form"])
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


# FW-0026: sensor.<prefix>_finds carries a short recent list only. At 50 full rows (~28 KB) its attributes passed HA's
# 16 KiB recorder limit, so the recorder dropped them and logged a warning on every update. The finds card reads the
# month files for the full rows; the attribute keeps what the automations on Pako read (the FLICA alert push looks a
# trip up by pairing in pot_count, tradeboard_pickups and this list for layover, turn, dates, days, credit and
# captain, so a burst of new finds should not push a trip out of every list) and what the card needs to show a row
# the file has not caught up with yet. 30 short rows ran 9.9 KB on Pako's live data (Nov 2026). The H3628 Fanfare
# push reads event/new_pairing, not this sensor.
FINDS_ATTR_ROWS = 30
FINDS_ATTR_MAX = 12000  # bytes of the whole payload (ASCII-escaped, so HA's UTF-8 copy is no larger); recorder limit 16384
FINDS_ATTR_KEYS = ("pairing", "dates", "days", "layover", "turn", "report", "credit", "captain", "seen", "gone",
                   "alert_at", "pickup_status", "picked_by", "source")


def finds_payload(rows, key, rev=None):
    """{count, finds, file_key, rev} for sensor.<prefix>_finds: the newest FINDS_ATTR_ROWS finds with FINDS_ATTR_KEYS
    only, fewer when the payload would pass FINDS_ATTR_MAX bytes; file_key is the finds files' key (FW-0010); rev
    changes whenever this month's or last month's file changes (FW-0026: an InFlt verdict, a Prem flag or a picker's
    average lives only in the files, and without rev the sensor would not change, so an open card would not refetch)."""
    out = [{k: r.get(k) for k in FINDS_ATTR_KEYS} for r in rows[:FINDS_ATTR_ROWS]]
    while True:
        d = {"count": len(out), "finds": out, "file_key": key, "rev": rev}
        if len(json.dumps(d, separators=(",", ":"))) <= FINDS_ATTR_MAX or not out:
            return d
        out = out[:-1]


def publish_finds():
    """FW-0026: the month files first, then the sensor: the finds card refetches the file when the sensor changes, so
    the file must already hold what the sensor announces (rev)."""
    rev = write_finds_months()
    try:
        key = www_key()
    except Exception as e:  # /data not writable: publish the rows anyway; the card says history is not available
        key = None
        log.info("finds file key unavailable: %s", e)
    pub("finds", finds_payload(DB.recent_finds(FINDS_ATTR_ROWS), key, rev))
    publish_pickers()


FINDS_FILES = {"all": False}


def write_finds_months():
    """0.9.4 (Ryan): one file per HST month for the finds card's month picker. This month and last month on every
    check; all 24 months once per start. Read only, no FLICA traffic. FW-0010: the files carry crew names and
    employee numbers and HA serves www with no login, so the name is finds_<YYYY-MM>_<key>.json (wwwfiles.py).
    FW-0026: returns rev, a short hash of this month's and last month's files as written (the two that change between
    starts), for the sensor; None when the files could not be written."""
    key = None
    try:
        key = www_key()
        today = local_now().date().replace(day=1)
        n = 24 if not FINDS_FILES["all"] else 2
        fdir = finds_dir()
        os.makedirs(fdir, exist_ok=True)
        rev = hashlib.sha256()
        for i in range(n):
            y, m = divmod(today.year * 12 + today.month - 1 - i, 12)
            a = datetime(y, m + 1, 1, 10, tzinfo=timezone.utc)  # 00:00 HST = 10:00 UTC
            y2, m2 = divmod(y * 12 + m + 1, 12)
            b = datetime(y2, m2 + 1, 1, 10, tzinfo=timezone.utc)
            rows = DB.finds_between(a.isoformat(), b.isoformat())
            month = f"{y:04d}-{m + 1:02d}"
            path = os.path.join(fdir, WF.finds_name(month, key))
            if rows or os.path.exists(path):
                text = json.dumps({"month": month, "count": len(rows), "finds": rows}, separators=(",", ":"))
                tmp = path + ".tmp"
                with open(tmp, "w") as fh:
                    fh.write(text)
                os.replace(tmp, path)
                if i < 2:
                    rev.update(f"{month}\n{text}\n".encode())
        FINDS_FILES["all"] = True
        return rev.hexdigest()[:12]
    except Exception as e:
        log.info("finds month files skipped: %s", WF.scrub(e, key))  # an OSError names the file: never log the key
        return None


def finds_files_cleanup():
    """FW-0010, once per start, before the month files are written: delete every finds file at a guessable /local/
    path (finds_<YYYY-MM>.json from before FW-0010) and this instance's files under an old key. Ryan's instance also
    sweeps the predictable names from the second-pilot folders (www/flight-watcher/<name>/, configured or not) and
    the pre-1.0.0 www/flica tree; a second pilot's instance sweeps its own folder. The month files are rebuilt from
    the DB right after, so nothing is lost. Logs a count, never a name."""
    key = None
    try:
        key = www_key()
        others = [] if INSTANCE else WF.subdirs(CARD_PAIRINGS) + [WWW_OLD] + WF.subdirs(WWW_OLD)
        n = WF.cleanup(finds_dir(), key, others)
        if n:
            log.info("FW-0010: removed %d finds file(s) with a guessable /local/ name; the month files now carry a key", n)
    except Exception as e:
        log.info("finds file cleanup skipped: %s", WF.scrub(e, key))


PICKERS_ATTR_ROWS = 20  # FW-0060: the fastest pickers the sensor keeps; the card reads every one from the file


def publish_pickers():
    """0.4.18 (Ryan): every FO/RO seen taking a trip, with their average time in open time, fastest first.
    FW-0060: one pilot runs about 230 bytes, so the list (38 pilots, 8.7 KB in Nov 2026, more every week) goes to
    pickers_<key>.json for the pickers card, and the sensor keeps the count and the fastest PICKERS_ATTR_ROWS."""
    rows = [{"emp": e, "name": v["name"], "pos": v["pos"], "n": v["n"], "avg_s": int(v["total_s"] / v["n"]) if v["n"] else None,
             "inflt_n": v.get("inflt_n", 0), "month_n": v.get("month_n", 0), "year_n": v.get("year_n", 0),
             "lays": v.get("lays", []), "last_lay": v.get("last_lay", ""),  # 0.7.6: Common Layover
             "min_s": v.get("min_s"),  # 0.8.2: Fastest Pickup Speed
             "last_at": v["last_at"]} for e, v in DB.picker_stats().items()]
    rows.sort(key=lambda r: (r["avg_s"] is None, r["avg_s"] or 0, r["name"]))
    key, rev = write_list_file("pickers", {"count": len(rows), "pickers": rows})
    pub("pickers", {"count": len(rows), "pickers": rows[:PICKERS_ATTR_ROWS], "file_key": key, "rev": rev})


# 1.0.0: entity id suffix per discovery oid where the two differ (the ids HA gave these entities from their names
# before 0.10.3; the dashboard cards and the automations on Pako use them).
ENTITY_SUFFIX = {
    "auto_swap": "auto_swap_dry_run", "charter_scan": "scan_crewtrac_charters_now", "crew_scan": "update_schedules",
    "drop_away": "would_drop", "hunt_seconds": "hunt_check_every", "improved_pay": "improved_pay_gross",
    "last_new": "last_new_pairing", "normal_minutes": "normal_check_every", "own_trips": "own_trip_times",
    "rearm": "re_arm", "recall": "recall_o75", "swap_map": "map_swap_pages_read_only",
    "swap_tests": "swap_test_requests", "trade_away": "would_trade", "tradeboard": "tradeboard_pickups",
}


RETIRED_ENTITIES = (("select", "swap_mode"),)  # FW-0028: the Test / Confirm / Live select, now a read-only sensor


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
        ("sensor", "swap_mode", {"name": "Swap mode", "state_topic": f"{T}/swap_mode/state",  # FW-0028: read only
                                 "json_attributes_topic": f"{T}/swap_mode/attr", "icon": "mdi:file-document-edit-outline"}),
        ("sensor", "swap_tests", {"name": "Swap test requests", "state_topic": f"{T}/swap_tests",
                                  "value_template": "{{ value_json.count }}",
                                  "json_attributes_topic": f"{T}/swap_tests", "icon": "mdi:file-send-outline"}),
        ("sensor", "improved_pay", {"name": "Improved pay gross", "state_topic": f"{T}/improved_pay",
                                     "value_template": "{{ value_json.improved }}", "unit_of_measurement": "USD",
                                     "json_attributes_topic": f"{T}/improved_pay", "icon": "mdi:cash-plus"}),
        ("sensor", "recall", {"name": "Recall O75", "state_topic": f"{T}/recall", "value_template": "{{ value_json.open }}",
                               "json_attributes_topic": f"{T}/recall", "icon": "mdi:alert-octagon"}),
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
        ("sensor", "settings", {"name": "Settings", "state_topic": f"{T}/settings/state",
                                "value_template": "{{ value_json.has_password }}",
                                "json_attributes_topic": f"{T}/settings/state", "icon": "mdi:account-key",
                                "entity_category": "diagnostic"}),
        ("sensor", "ot_requests", {"name": "Open time requests", "state_topic": f"{T}/ot_requests",
                                   "value_template": "{{ value_json.pending }}",
                                   "json_attributes_topic": f"{T}/ot_requests", "icon": "mdi:swap-horizontal-circle-outline"}),
        ("sensor", "tickets", {"name": "Tickets", "state_topic": f"{T}/tickets", "value_template": "{{ value_json.open }}",
                               "json_attributes_topic": f"{T}/tickets", "icon": "mdi:ticket-outline"}),
    ]
    if not INSTANCE:  # 0.10.1: the crew index runs on Ryan's instance only
        ents += [
            ("sensor", "crew_index", {"name": "Crew index", "state_topic": f"{T}/crew_index",
                                      "value_template": "{{ value_json.coverage_pct }}", "unit_of_measurement": "%",
                                      "json_attributes_topic": f"{T}/crew_index", "icon": "mdi:account-search"}),
            ("button", "crew_scan", {"name": "Update schedules", "command_topic": f"{T}/crew_scan/press",
                                     "icon": "mdi:account-sync"}),
        ]
    for comp, oid, cfg in ents:
        # 0.10.3: HA ignores object_id now; default_entity_id sets the id, object_id stays for older HA.
        # 1.0.0: the id keeps the name-based suffix the entity has always had (ENTITY_SUFFIX), which the cards,
        # automations and recorder history use; the unique_id and topics keep the short oid.
        eid = f"{T}_{ENTITY_SUFFIX.get(oid, oid)}"
        cfg = {**base, **cfg, "unique_id": f"{T}_{oid}", "object_id": eid, "default_entity_id": f"{comp}.{eid}"}
        c.publish(f"homeassistant/{comp}/{T}/{oid}/config", json.dumps(cfg), retain=True)
    for comp, oid in RETIRED_ENTITIES:  # an empty retained config removes the entity from HA
        c.publish(f"homeassistant/{comp}/{T}/{oid}/config", "", retain=True)


def mqtt_start():
    m = mqtt_creds()
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=T)
    c.username_pw_set(m["username"], m["password"])
    c.will_set(AVAIL, "offline", retain=True)
    c.on_message = on_message

    def on_connect(cl, u, f, rc, p=None):
        cl.publish(AVAIL, "online", retain=True)
        discovery(cl)
        for t in ("hunt/set", "pause/set", "rearm/press", "hunt/state", "pause/state", "rule/+/live/set",
                  "check_now/press", "freq/normal_min/set", "freq/hunt_s/set", "email/alert", "blocked/set",
                  "trade/set", "auto_swap/set", "swap_map/press", "drop/set", "charter_scan/press", "pilot/set",
                  "improved/set", "recall/set", "recall/act", "settings/set",
                  "ticket/new", "ticket/image", "ticket/act", "ticket/edit",
                  "ticket/delete") + (() if INSTANCE else ("crew_scan/press",)):
            cl.subscribe(f"{T}/{t}")
        publish_settings(cl)
        fq = freq()
        cl.publish(f"{T}/freq/normal_min/state", str(fq["normal_min"]), retain=True)
        cl.publish(f"{T}/freq/hunt_s/state", str(fq["hunt_s"]), retain=True)
        publish_rules(cl)
        cl.publish(f"{T}/auto_swap/state", "ON" if S.get("auto_swap") else "OFF", retain=True)
        publish_swap_mode(cl)
        publish_swap_tests()
        tm = threading.Timer(CONNECT_STATES_DELAY_S, connect_states, args=(cl,))  # FW-0024
        tm.daemon = True
        tm.start()

    c.on_connect = on_connect
    c.connect(m["host"], int(m["port"]))
    c.loop_start()
    return c


MQ = None

# FW-0060: HA's recorder keeps no history for a state whose attributes pass 16 KiB and logs a warning on every update
# (sensor.flight_watcher_tickets ran about 39 KB, schedule_versions about 33 KB). Every sensor attribute payload stays
# at or under ATTR_MAX bytes (compact JSON, ASCII-escaped, so HA's UTF-8 copy is no larger; HA adds friendly_name and
# icon, about 100 bytes, which keeps it under 12 KB). The long lists live in files (write_list_file); this is the
# backstop for the rest: the list a sensor carries is cut from its least useful end and "trimmed" says how many went.
ATTR_MAX = FINDS_ATTR_MAX
# topic -> (attribute holding the list or dict that can grow, which end goes first: "end", "front", or "old" for a
# dict keyed TRIP|YYYY-MM-DD or YYYY-MM, oldest key first)
ATTR_TRIM = {
    "pot/state": ("pairings", "end"), "tradeboard/state": ("pairings", "end"), "recall": ("days", "end"),
    "charters": ("items", "front"), "ot_requests": ("requests", "front"), "swap/state": ("ideas", "end"),
    "swap_tests": ("tests", "front"), "own_trips": ("trips", "old"), "improved_pay": ("months", "front"),
    "pilot_schedule": ("reconstructed", "end"), "rules/state": ("rules", "end"), "blocked/state": ("days", "front"),
    "finds": ("finds", "end"), "pickers": ("pickers", "end"), "tickets": ("tickets", "end"),
    "schedule": ("months", "old"), "schedule_versions": ("months", "old"), "grid/state": ("days", "old"),
    "drop/state": ("keys", "front"), "trade/state": ("keys", "front"), "last_tradeboard": (None, None),
    "last_new": (None, None), "last_match": (None, None), "crew_index": ("waiting_for_award", "front"),
}
ATTR_LOGGED = set()


def attr_size(payload):
    return len(json.dumps(payload, separators=(",", ":")))


def _dict_age(k):
    k = str(k)
    return k.split("|")[-1] if "|" in k else k


def cap_attrs(topic, payload):
    """FW-0060: payload (a dict for a sensor's json_attributes_topic) at or under ATTR_MAX bytes: the ATTR_TRIM list
    loses items from its least useful end until it fits, and "trimmed" counts them. A payload that still does not fit
    (no list to cut) goes out as it is, logged once per topic."""
    if not isinstance(payload, dict) or attr_size(payload) <= ATTR_MAX:
        return payload
    key, end = ATTR_TRIM.get(topic, (None, None))
    lst = payload.get(key) if key else None
    out, n = dict(payload), 0
    if isinstance(lst, list):
        lst = list(lst)
        while lst and attr_size({**out, key: lst, "trimmed": n}) > ATTR_MAX:
            lst.pop(0 if end == "front" else -1)
            n += 1
        out[key] = lst
    elif isinstance(lst, dict):
        keep = sorted(lst, key=_dict_age)
        while keep and attr_size({**out, key: {k: lst[k] for k in keep}, "trimmed": n}) > ATTR_MAX:
            keep.pop(0)
            n += 1
        out[key] = {k: lst[k] for k in lst if k in keep}
    if n:
        out["trimmed"] = n
    if topic not in ATTR_LOGGED and (n or attr_size(out) > ATTR_MAX):
        ATTR_LOGGED.add(topic)
        log.info("FW-0060: %s attributes over %d bytes: %s", topic, ATTR_MAX,
                 f"{n} item(s) of {key} left out" if n else "nothing to cut")
    return out


def pub(topic, payload, retain=True):
    if not isinstance(payload, str):
        payload = json.dumps(cap_attrs(topic, payload) if topic in ATTR_TRIM else payload)
    MQ.publish(f"{T}/{topic}", payload, retain=retain)


LIST_REV = {}  # FW-0060: name -> rev of the list file last written, so an unchanged list is not written again


def write_list_file(name, obj):
    """FW-0060: obj as <name>_<key>.json (wwwfiles.LIST_NAMES) in this instance's www folder (finds_dir(): a second
    pilot's is www/flight-watcher/<name>/), written atomically and only when it changed. Returns (file_key, rev): rev
    is a short hash of the text, which the sensor carries so an open card fetches the file again when it changes;
    (None, None) when it could not be written (the card then shows the sensor's short list). Never logs the key."""
    key = None
    try:
        key = www_key()
        text = json.dumps(obj, separators=(",", ":"))
        rev = hashlib.sha256(text.encode()).hexdigest()[:12]
        fdir = finds_dir()
        path = os.path.join(fdir, WF.list_name(name, key))
        if LIST_REV.get(name) != (key, rev) or not os.path.exists(path):
            os.makedirs(fdir, exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w") as fh:
                fh.write(text)
            os.replace(tmp, path)
            LIST_REV[name] = (key, rev)
        return key, rev
    except Exception as e:
        log.info("%s file skipped: %s", name, WF.scrub(e, key))
        return None, None


FETCHES = {"n": None, "pub_at": 0}


def count_fetch():
    """0.8.7 (Ryan): count every page the Watcher loads from FLICA (fetch or goto), kept in the DB and
    published as sensor.flight_watcher_flica_fetches (total_increasing) so HA utility meters can show
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
    pub("state_attr", {"note": note, "version": VERSION, "since": S["since"], "instance": INSTANCE, "doh": pilot_doh()})


def pilot_doh():
    """FW-0010: the pilot's date of hire (YYYY-MM-DD) from <data>/cards.json for the schedule card's longevity year,
    "" when none. Published in sensor.<prefix>_state (behind HA's login); the deployed card file under /local/ (no
    login) carries the placeholder only (cards.py)."""
    try:
        with open(f"{DATA}/cards.json", encoding="utf-8") as f:
            d = json.load(f).get("doh", "")
    except (OSError, ValueError, AttributeError):
        return ""
    return d if isinstance(d, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", d) else ""


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
                os.makedirs(SHARE, exist_ok=True)
                page.screenshot(path=f"{SHARE}/last_login.png", full_page=True)
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
                    close_in_scan(html, "mobile open time page")  # FW-0034: a link naming the close-in folder
                    if OPTS.get("watch_next_month", True):
                        links = pot_links(html, MOBILE_POT)
                        log.info("mobile pot links to other bid months: %s", links)
                        mine = bcid(MOBILE_POT)
                        ci = (S.get("close_in") or {}).get("bcid")
                        later = sorted((l for l in links if bcid(l["url"]) and bcid_after(bcid(l["url"]), mine)
                                        and not CLOSE_IN_RE.search(l["text"]) and bcid(l["url"]) != ci),
                                       key=lambda l: bcid_key(bcid(l["url"])))  # FW-0034: never the close-in folder
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
            try:  # FW-0034: the menu frame names the close-in folder, if the account has one
                close_in_scan(menu.content(), "main menu frame")
            except Exception as e:
                log.info("close-in scan of the menu frame skipped: %s", e)
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
    """Sleep, publishing when the next pot check is due (sensor.flight_watcher_next_check)."""
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


FAR_WHY_MAX = 400  # far_why on published rows stays short (the pot sensor's attributes)


def _pickup_duties(ev, s):
    """FW-0039: the pickup's duty periods (HST minutes from 00:00 of its first day, pot.parse_duties shape): from its
    FLICA pairing page (enrich(); pot rows keep them in the details cache, off the published row), else the bid
    period's pairing package (the same lookup as the Recall check). [] when neither has them."""
    d = ev.get("duties") or (S.get("details", {}).get(f"{ev.get('pairing')}|{ev.get('start')}") or {}).get("duties")
    if d:
        return d
    try:
        return RC.package_entry(ev.get("pairing"), s, pkg_details_for).get("duties") or []
    except Exception:
        return []


def far_screen(ev, exclude=None):
    """FW-0039: FAR 117 and PWA rest screen of a pot, Tradeboard or finds row against Ryan's own line, with the same
    rules as the Recall check (far.legality(): 117.25(e), 117.25(b), 117.23(b)(1) and now 117.23(c)(1)/(2), the FDP
    60 h in 168 h and 190 h in 672 h; PWA 10.E.1.a, 2.19.b), per duty period of his trips and of the pickup.
    {far, why}: far is the column ('OK', 'OK (CBA rest 10:30)', 'Conflict', 'Rest 8:00 before · FDP 65h/168h', or
    '?' when the pickup's report or final arrival is not known yet or a check needs data not on file: never OK);
    why cites the rule behind it. exclude: 'TRIP|YYYY-MM-DD' of his own trip to leave out (a swap)."""
    try:
        s, e = _span(ev)
        if not s:
            return {"far": "?", "why": "pickup dates unknown"}
        rep, arr = ev.get("report"), ev.get("arrive") or ev.get("last_arr")
        if not FAR.window(s, e, rep, arr):
            return {"far": "?", "why": "pickup report or final arrival not read yet"}
        new = RC.pickup_trip(ev.get("pairing") or "pickup", s, e, rep, arr, hours(ev.get("blk")),
                             _pickup_duties(ev, s))
        mine = RC.line_records(S.get("schedule") or {}, S.get("own_trips") or {}, s, e, local_now().date(), exclude)
        r = FAR.screen(new, mine)
        return {"far": r["far"], "why": r["why"][:FAR_WHY_MAX]}
    except Exception as ex:
        log.info("far skipped for %s: %s", ev.get("pairing"), ex)
        return {"far": "?", "why": "FAR screen failed"}


def far_for(ev, exclude=None):
    """The FAR column of a row (far_screen), and its reason on the row as far_why."""
    r = far_screen(ev, exclude)
    if exclude is None:
        ev["far_why"] = r["why"]
    return r["far"]


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


ENDS_FIX_V = 1  # FW-0065: bump to run repair_ends() over the stored versions again


def repair_trip_ends():
    """FW-0065, once: versions and the schedule on file stored while the item builder cut a trip short when the next
    activity started on its return day (H3681 Nov 9 to 12 kept as Nov 9 to 9 from 11.009 on) get the end their own
    days list gives, so recall legality spans and pay see the whole trip. Months from 24 back to 3 ahead."""
    if S.get("ends_fix_v") == ENDS_FIX_V:
        return 0
    n = 0
    today = local_now().date()
    for i in range(-24, 4):
        y, m = divmod(today.year * 12 + today.month - 1 + i, 12)
        key = f"sched_versions:{y:04d}-{m + 1:02d}"
        vers = DB.get(key)
        if vers and VER.repair_ends(vers, schedule_items):
            n += sum(1 for v in vers if v.get("repaired"))
            DB.put(key, vers)
    for mk, sch in (S.get("schedule") or {}).items():
        if isinstance(sch, dict) and sch.get("days") and VER.repair_ends([sch], schedule_items):
            sch.pop("repaired", None)
            n += 1
    S["ends_fix_v"] = ENDS_FIX_V
    save_state(S)
    if n:
        log.info("FW-0065: %d stored schedule version(s) / month(s) got the trip end their days list gives", n)
    return n


def versions_check(force_pub=False):
    """0.9.0 (Ryan): a new schedule version (MM.NNN) every time anything on a month changes. A month whose new
    pairings have no block / credit read yet waits up to 2 h for them, so one change makes one version."""
    try:
        repair_trip_ends()
    except Exception as e:  # never stops the versions; tried again next time
        log.info("FW-0065 trip end repair skipped: %s", e)
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
        if not INSTANCE and not S.get("ver_seeded"):  # 0.9.0: Nov 2-4 versions rebuilt from HA's recorder (before the Watcher kept versions); Ryan only
            for mk, v in VER.seed(DB, "/share/flight_watcher/versions_seed.json",
                                  lambda ts: datetime.fromtimestamp(ts or time.time(), timezone.utc).isoformat()):
                log.info("schedule version %s (%s) imported from the recorder", v, mk)
            S["ver_seeded"] = True
        made = VER.update(DB, ready, own, now_iso())
        for mk, v in made:
            log.info("schedule version %s (%s)", v, mk)
        if made or force_pub or not S.get("ver_published"):
            # FW-0060: every version's items, days and trips go to versions_<key>.json (about 33 KB in Nov 2026) for
            # the schedule card; the sensor keeps the counts and each month's awarded / current version
            full = VER.published(DB, months)
            key, rev = write_list_file("versions", {"months": full})
            pub("schedule_versions", {"count": sum(len(DB.get(f"sched_versions:{m}") or []) for m in months),
                                      "months": VER.summary(full), "file_key": key, "rev": rev, "at": now_iso()})
            S["ver_published"] = True
            if made:
                pub("event/schedule_version", {"versions": [v for _, v in made], "at": now_iso()}, retain=False)
    except Exception as e:
        log.info("schedule versions skipped: %s", e)


UPLOADS = f"{SHARE}/uploads"
# FW-0062: where the Web UI saves every upload (web.UPLOAD_DIR). The Web UI runs on the default instance only, so a
# second pilot's instance reads the pairings package text and the seniority list from here too.
UPLOADS_SHARED = "/share/flight_watcher/uploads"
CARD_PAIRINGS = "/homeassistant/www/flight-watcher"  # pairings_<month>.json: shared, either instance may write the same content
WWW_OLD = "/homeassistant/www/flica"  # FW-0010: the pre-1.0.0 folder (migrate.py moves it); swept for old finds files
_PKG_CACHE = {}  # FW-0062: period -> (file time, details) parsed from the shared package text
_SEN_CACHE = {}  # FW-0062: {mt: file time, data: seniority.json}


def pkg_details_for(period):
    """FW-0062: the pairing package details ({pid: {block, credit, lay, ...}}) of one bid period: this instance's DB
    copy (uploads_check), else parsed from the shared upload's text copy (<period>_pairings.txt, cached by file
    time), so a second pilot's instance has them too. {} when there is no package for the period."""
    det = DB.get(f"pkg_details:{period}")
    if det:
        return det
    path = os.path.join(UPLOADS_SHARED, f"{period}_pairings.txt")
    try:
        mt = os.path.getmtime(path)
    except OSError:
        return {}
    c = _PKG_CACHE.get(period)
    if c and c[0] == mt:
        return c[1]
    try:
        det = PDF.package_details(open(path, errors="replace").read())
    except Exception as e:
        log.info("pairing package %s not read: %s", period, e)
        det = {}
    _PKG_CACHE[period] = (mt, det)
    return det


def seniority_data():
    """FW-0062: the parsed pilot seniority list (web.seniority_write), shared by every instance; {} when none."""
    path = os.path.join(UPLOADS_SHARED, "seniority.json")
    try:
        mt = os.path.getmtime(path)
        if _SEN_CACHE.get("mt") != mt:
            _SEN_CACHE.update(mt=mt, data=json.load(open(path, encoding="utf-8")))
        return _SEN_CACHE["data"] or {}
    except (OSError, ValueError):
        return {}


def seniority_refresh():
    """FW-0062: the Web UI parses the seniority list as it is uploaded. When a source of seniority.json is missing or
    was read by an older parser (SEN.PARSER), it is read again: the dedicated list (the text copy of the file
    seniority.json names, else (no seniority.json, or its text copy is gone) the newest seniority_<date>.txt) and,
    1.4.5 (Ryan, Nov 6: the monthly award packet lists every pilot's date of hire), the award (the month
    seniority.json names, else the newest <YYYY-MM>_award.txt), so an award uploaded before 1.4.5 is read for dates
    of hire at the first start. web.award_seniority applies the merge rules (25 pilot rows or more; the later date on
    top). Every list file is one that gave pilot rows when it was uploaded: the Web UI deletes a refused upload
    (web._save_seniority). Each file's signature is recorded before it is read (an award's under 'sen:<file>', its own
    key belongs to uploads_check), so a file that is slow or fails is not read again at every start. Default instance
    only, so the files have one writer; counts only in the log."""
    if INSTANCE:
        return
    try:
        names = os.listdir(UPLOADS_SHARED)
    except OSError:
        return
    lists = sorted(f for f in names if re.fullmatch(r"seniority_\d{4}-\d{2}-\d{2}\.txt", f))
    awards = sorted(f for f in names if re.fullmatch(r"\d{4}-\d{2}_award\.txt", f))
    if not lists and not awards:
        return
    out = os.path.join(UPLOADS_SHARED, "seniority.json")
    done = S.setdefault("uploads_done", {})

    def sig(path):
        return f"{os.path.getmtime(path):.0f}|{SEN.PARSER}"

    def fresh(key, path):  # True once per file version and parser: the signature is stored before the read
        s = sig(path)
        if done.get(key) == s:
            return False
        done[key] = s
        save_state(S)
        return True

    def award_pick(aw):  # the award the dates of hire come from: the one on file, else the newest
        own = f"{(aw or {}).get('award_month')}_award.txt"
        return own if own in awards else awards[-1]

    cur = seniority_data()
    if cur and int(cur.get("parser") or 0) >= SEN.PARSER:
        # 1.4.5 review fix: a current seniority.json says the list is current, not that an award was read (a 1.4.4
        # list has none), so return only when no award is due: none on file, its dates of hire on file from this
        # parser (seniority_award.json), or the award to read already tried with it (too few rows, say).
        aw = web.seniority_award(out)
        if not awards or int((aw or {}).get("parser") or 0) >= SEN.PARSER:
            return
        f = award_pick(aw)
        if done.get("sen:" + f) == sig(os.path.join(UPLOADS_SHARED, f)):
            return
    lst, aw = web.seniority_sources(out)
    if lists and int((lst or {}).get("parser") or 0) < SEN.PARSER:
        own = re.sub(r"\.pdf$", ".txt", str((lst or {}).get("file") or ""))
        f = own if own in lists else lists[-1]
        path = os.path.join(UPLOADS_SHARED, f)
        if fresh(f, path):
            same = (lst or {}).get("file") == f[:-4] + ".pdf"
            try:
                d = web.seniority_write(path, f[:-4] + ".pdf", lst.get("uploaded_at") if same else f"{f[10:20]}T00:00:00",
                                        (lst.get("list_date") or "") if same else "", out)
                log.info("seniority list %s: %s", f, f"{d['count']} pilots read again" if d else "no pilot rows")
            except Exception as e:
                log.info("seniority list %s not read: %s", f, e)
    if awards and int((aw or {}).get("parser") or 0) < SEN.PARSER:
        f = award_pick(aw)
        path = os.path.join(UPLOADS_SHARED, f)
        if fresh("sen:" + f, path):
            same = (aw or {}).get("file") == f[:-4] + ".pdf"
            try:
                info = web.award_seniority(path, f[:7], f[:-4] + ".pdf",
                                           aw.get("uploaded_at") if same else web.hst_iso(os.path.getmtime(path)), out)
                log.info("award %s dates of hire: %d pilot rows (%s), %s", f, info["rows"], info["reader"], info["decision"])
            except Exception as e:
                log.info("award %s dates of hire not read: %s", f, e)


TAX = {"at": 0.0, "pct": None}
TAX_CACHE_S = 600


def tax_pct():
    """FW-0062: this instance's federal + state tax % for the pay line's Pay-Net estimate, from the same helpers the
    schedule card reads (input_number.<prefix>_federal_tax_pct, default 22; ..._state_tax_pct, default 0); read at
    most every 10 min."""
    if TAX["pct"] is None or time.time() - TAX["at"] > TAX_CACHE_S:
        tot = 0.0
        for name, dflt in (("federal", 22.0), ("state", 0.0)):
            try:
                tot += float(ha_state(f"input_number.{T}_{name}_tax_pct"))
            except (TypeError, ValueError):
                tot += dflt
        TAX.update(at=time.time(), pct=round(tot, 2))
    return TAX["pct"]


def pilot_pay_line(trips, emp, name, start, end):
    """FW-0062: the pay line under a rebuilt month (pay.pay_line over the trips the card draws, crewidx.grid_pick),
    priced with the date of hire on the shared seniority list. Adds 'gross' to each priced trip. list_status: 'ok',
    'none' (no list uploaded) or 'not_on_list' (a newer hire, or a name the list spells another way)."""
    data = seniority_data()
    rec = SEN.find(data, emp, name) if data else None
    grid, _also = CI.grid_pick(trips)
    line, per = PAY.pay_line(grid, (rec or {}).get("doh") or "", start, end, tax_pct())
    for t in trips:
        g = per.get(f"{t.get('pairing')}|{t.get('start')}")
        if g is not None:
            t["gross"] = g
    line.update(list_status="ok" if rec else ("not_on_list" if data else "none"), list_date=data.get("list_date") or "",
                list_newest_doh=data.get("newest_doh") or "", seat_list=(rec or {}).get("seat") or "",
                list_source=(data.get("source") or "list") if data else "")
    return line


def finds_dir():
    """0.10.0: the finds month files per pilot: www/flight-watcher for Ryan, www/flight-watcher/<instance> for a second
    pilot (FW-0010: finds_<YYYY-MM>_<key>.json, the key from that instance's /data)."""
    return os.path.join(CARD_PAIRINGS, INSTANCE) if INSTANCE else CARD_PAIRINGS


def uploads_check():
    """0.9.1 (Ryan): parse the monthly PDFs uploaded on the Web UI (text copies made by pdftotext). Pairings
    package -> the schedule card's pairing file (www/flight-watcher/pairings_<YYYY-MM>.json) and trip details; award ->
    this month's version .001. Each file is handled again only when it changes. No FLICA traffic.
    FW-0062: the seniority list is parsed by the Web UI as it is uploaded; seniority_refresh re-reads it after a
    parser change."""
    try:
        seniority_refresh()
    except Exception as e:
        log.info("seniority list skipped: %s", e)
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
                        log.info("upload %s: %d A332 pairings -> www/flight-watcher/pairings_%s.json", f, len(pj["rows"]), month)
                else:
                    det = DB.get(f"pkg_details:{month}")
                    emp = S.get("own_emp") or ""
                    if not det or not emp:
                        log.info("upload %s: waiting for the %s pairing package and the employee number", f, month)
                        continue
                    try:  # FW-0015: the award's columns start on the bid period's first day (Dec 2 in December)
                        start = json.load(open(os.path.join(CARD_PAIRINGS, f"pairings_{month}.json"))).get("start")
                    except (OSError, ValueError, AttributeError):
                        start = None
                    try:
                        aw, why = PDF.parse_award(text, emp, det, month, start), f"employee {emp} not in this award"
                    except ValueError as e:  # logged once: the file is marked done until it changes
                        aw, why = None, f"award not read: {e}"
                    if not aw:
                        log.info("upload %s: %s", f, why)
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


def recall_me():
    """Ryan's recall settings: {sen, seat, o75_months {YYYY-MM: true | false}} (1.4.6 review: Over 75 eligibility,
    PWA 22.G.2.d, is per month; the old single 'o75' flag defaulted to eligible and is no longer used)."""
    me = {"sen": None, "seat": "FO", "o75_months": {}, **(DB.get("recall_me") or {})}
    me.pop("o75", None)
    if not isinstance(me.get("o75_months"), dict):
        me["o75_months"] = {}
    return me


def recall_me_set(new):
    """Merge a {me: {...}} change into recall_me: sen, seat, and o75_months {YYYY-MM: true | false | null} (null
    forgets that month's answer). Anything else is ignored."""
    if not isinstance(new, dict):
        return
    cur = {k: v for k, v in (DB.get("recall_me") or {}).items() if k != "o75"}
    for k in ("sen", "seat"):
        if k in new:
            cur[k] = new[k]
    om = new.get("o75_months")
    if isinstance(om, dict):
        months = dict(cur.get("o75_months") or {})
        for mk, v in om.items():
            if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", str(mk)):
                continue
            if v is None:
                months.pop(mk, None)
            elif isinstance(v, bool):
                months[mk] = v
        cur["o75_months"] = dict(sorted(months.items())[-36:])
    DB.put("recall_me", cur)


def recall_cmd(payload):
    """0.9.2 (Ryan): Hark posts each day's HNL recall list from Alaska Flight Ops SharePoint here (HA webhook ->
    MQTT recall/set): {"date": "YYYY-MM-DD", "file": "ok|blank|not posted", "rows": [{kind recall|o75|junior,
    seat, pilot, sen, pairing, report?, last_arr?, days?, blk?}], "me": {sen, seat, o75_months}?}. A list of such
    days is accepted too. Each row is judged against Ryan's line as he held it that day (recall.py, PWA 22.G.2 /
    FAR 117) and kept in the DB."""
    try:
        d = json.loads(payload or "{}")
        days = d if isinstance(d, list) else [d]
        with RECALL_LOCK:
            if isinstance(d, dict) and d.get("me"):
                recall_me_set(d["me"])
            allr = DB.get("recall_days") or {}
            for day in days:
                dk = str(day.get("date") or "")[:10]
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", dk):
                    continue
                allr[dk] = {"date": dk, "file": day.get("file") or ("ok" if day.get("rows") else "blank"),
                            "rows": day.get("rows") or [], "at": now_iso()}
            DB.put("recall_days", dict(sorted(allr.items())[-120:]))
            recall_eval(notify=True)
    except Exception as e:
        log.info("recall list skipped: %s", e)


RECALL_LIVE = ("MISSED", "POSSIBLE")  # FW-0012: a CCR draft is open, counted and shown only while its row says this
# 1.4.6: 'filing' while Hark has the CCR request; 'blocked' / 'cancelled' when Hark's task stopped without a CCR number
# (the narrative stays approved; a request HOM never made a task of can be sent again)
RECALL_OPEN = ("new", "confirmed", "approved", "filing", "blocked", "cancelled")
HARK_LIVE = ("filing", "blocked", "cancelled")  # 1.4.6 review: Hark's HOM task (or the request) may still file it
RECALL_LOCK = threading.RLock()  # recall_days / recall_acts change from MQTT, the CCR poll and the main thread
CCR_DIR = "/share/flight_watcher/ccr_requests"  # 1.4.6: shared with the HOM app (ccr.py); one folder, not per pilot
CCR_POLL_S = 60
CCR_PILOT = "ryan"  # 1.4.6: only Ryan's Watcher (the default instance) asks Hark to file


def recall_versions(day_keys):
    """{YYYY-MM: [schedule versions]} for the months the list days reach (recall.LOOK + 7 days each side), plus the
    months before them back to the first one on file, so recall.keeping_since() sees when versions began."""
    ds = sorted(d for d in day_keys if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(d)))
    if not ds:
        return {}
    a = date.fromisoformat(ds[0]) - timedelta(days=RC.LOOK + 7)
    b = date.fromisoformat(ds[-1]) + timedelta(days=RC.LOOK + 7)
    out = {}
    for mk in RC._months(a, b):
        v = DB.get(f"sched_versions:{mk}")
        if v:
            out[mk] = v
    y, m = a.year, a.month
    for _ in range(24):  # versions are kept month after month since they began: stop at the first gap
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
        v = DB.get(f"sched_versions:{y:04d}-{m:02d}")
        if not v:
            break
        out[f"{y:04d}-{m:02d}"] = v
    return out


def recall_helds(vers, dk):
    """The lines Ryan held on list day dk (recall.helds_on). If that fails, one line with nothing on file around
    the day, so every row that reaches legality is POSSIBLE, never MISSED on today's schedule."""
    day = date.fromisoformat(dk)
    try:
        return RC.helds_on(vers, day, S.get("schedule") or {}, S.get("own_trips") or {})
    except Exception as e:
        log.info("recall: line held on %s not built (%s); its rows cannot be MISSED", dk, e)
        return [{"day": dk, "items": [], "trips": {}, "line": "", "asof": "",
                 "unknown": [((day - timedelta(days=RC.LOOK + 7)).isoformat(),
                              (day + timedelta(days=RC.LOOK + 7)).isoformat())]}]


def _act_label(vid):
    p = (str(vid).split("|") + ["", "", ""])[:3]
    return f"{'Over 75' if p[2] == 'o75' else 'Recall'} {p[1]} {p[0]}"


def _hark_alert(vid, a, what, text):
    """1.4.6 review: keep a Hark warning on the act (shown on the card) and return the event/recall_hark_alert payload
    (a time-sensitive push to Ryan: Hark may file a CCR he no longer wants filed, or filed one twice)."""
    a["hark_alert"], a["hark_alert_at"], a["hark_alert_what"] = text, now_iso(), what
    p = (str(vid).split("|") + ["", "", ""])[:3]
    return {"id": vid, "rid": a.get("rid") or "", "task_id": a.get("task_id") or "", "what": what, "text": text,
            "date": p[0], "pairing": p[1], "kind": p[2]}


def _pub_hark_alerts(alerts):
    for p in alerts:
        log.info("Hark alert %s for %s: %s", p["what"], p["rid"], p["text"])
        pub("event/recall_hark_alert", p, retain=False)


def recall_eval(notify=False):
    """Judge every recall list on file against the line Ryan held on that list day (1.4.6) and keep one act (CCR
    draft) per MISSED / POSSIBLE row. FW-0012: an act whose row no longer says MISSED or POSSIBLE (now NO, or gone
    from a list on file) is marked superseded, keeping what it was ('was'), its narrative and CCR #; it comes back as
    it was if the row turns into a miss again (no second push). With notify (a list just came in), a new act fires
    event/recall_miss, and so does an act whose row turns MISSED for the first time (once per act, 'missed_sent').
    1.4.6 review: each row reads its own bid period's package (pkg_details_for); a draft Hark still has (filing,
    blocked, cancelled) that is superseded fires event/recall_hark_alert, since nothing tells HOM."""
    alerts = []
    with RECALL_LOCK:
        me = recall_me()
        allr, acts = DB.get("recall_days") or {}, DB.get("recall_acts") or {}
        blocked = sorted(set(DB.get("blocked_hist") or []) | set(S.get("blocked_days") or []))
        pkgs = {}

        def det(period):  # FW-0062 / 1.4.6 review: pairing ids repeat across bid periods; never another month's
            if period not in pkgs:
                pkgs[period] = pkg_details_for(period) or {}
            return pkgs[period]

        prev = {v.get("id") or f"{v.get('date')}|{v.get('pairing')}|{v.get('kind')}": v.get("verdict")
                for day in allr.values() for v in day.get("verdicts") or [] if isinstance(v, dict)}
        items, own = _sched_items(), S.get("own_trips") or {}
        vers = recall_versions(allr)
        fresh, live, seen = [], {}, {}
        for dk, day in allr.items():
            day["verdicts"] = RC.check_day(day.get("rows"), me, items, own, blocked, det, helds=recall_helds(vers, dk))
            for v in day["verdicts"]:
                v["id"] = f"{v['date']}|{v['pairing']}|{v['kind']}"
                seen.setdefault(v["id"], v)
                if v["verdict"] in RECALL_LIVE:
                    live.setdefault(v["id"], v)
        for vid in live:  # 1.4.6 review: an act from before counts as pushed only if the stored verdict was MISSED
            if vid in acts and "missed_sent" not in acts[vid]:
                acts[vid]["missed_sent"] = prev.get(vid) == "MISSED"
        for vid, v in live.items():
            a = acts.get(vid)
            if not a:
                acts[vid] = {"status": "new", "narrative": RC.narrative(v, me, S.get("own_name") or "", S.get("own_emp") or ""),
                             "at": now_iso(), "missed_sent": False}
                fresh.append(v)
            elif a.get("status") == "superseded":
                a["status"], a["at"] = a.pop("was", None) or "new", now_iso()
                a.pop("superseded_why", None)
                if a.get("hark_alert_what") == "superseded":  # a miss again: that warning no longer applies
                    for k in ("hark_alert", "hark_alert_at", "hark_alert_what"):
                        a.pop(k, None)
        first = min(allr) if allr else ""
        for vid, a in acts.items():
            if vid in live or a.get("status") == "superseded" or (vid not in seen and (not first or vid[:10] < first)):
                continue  # live, already closed, or from a day older than the lists kept: history as it stands
            why = ((seen.get(vid) or {}).get("why") or ["no longer on the recall list"])[-1]
            was = a.get("status") or "new"
            a.update(was=was, status="superseded", superseded_why=why, at=now_iso())
            if was in HARK_LIVE and a.get("rid"):
                task = f"HOM task {a['task_id']}" if a.get("task_id") else f"the request {a['rid']}"
                alerts.append(_hark_alert(vid, a, "superseded", (
                    f"{_act_label(vid)} is no longer a miss ({why}), but Hark still has {task}. Complete it as "
                    f"skipped in HOM so Hark does not file this CCR.")))
        push = []
        if notify:
            push = list(fresh) + [v for vid, v in live.items() if v not in fresh and v["verdict"] == "MISSED"
                                  and acts[vid].get("missed_sent") is False and acts[vid].get("status") in RECALL_OPEN]
            for v in push:
                if v["verdict"] == "MISSED":
                    acts[v["id"]]["missed_sent"] = True
        keep = ("status", "was", "at", "ccr", "superseded_why", "filed_at", "filed_by", "rid", "task_id", "hark_alert",
                "hark_ccr", "requested_at")
        for day in allr.values():
            for v in day["verdicts"]:
                a = acts.get(v["id"]) or {}
                if v["verdict"] in RECALL_LIVE:
                    v["act"] = {k: x for k, x in a.items() if k not in ("missed_sent", "hark_bad")}
                else:  # history only: no narrative, no controls
                    v["act"] = {k: a[k] for k in keep if k in a} if a.get("status") == "superseded" else {}
        DB.put("recall_days", allr)
        DB.put("recall_acts", acts)
        publish_recall()
    for v in push:
        pub("event/recall_miss", {"id": v["id"], "verdict": v["verdict"], "date": v["date"], "pairing": v["pairing"],
                                  "kind": v["kind"], "sen": v["sen"], "why": "; ".join(v["why"])}, retain=False)
    _pub_hark_alerts(alerts)


def _hom_task(a):
    """1.4.6 review: the HOM task made from this act's request: the id ccr_poll recorded, else <rid>.task.json on disk
    now (HOM makes one task per rid, ever); '' when there is none; '?' when the folder cannot be read (then a task
    is assumed)."""
    if a.get("task_id"):
        return a["task_id"]
    if not a.get("rid"):
        return ""
    try:
        t = CCR.read_reply(CCR_DIR, a["rid"], "task")
    except (CCR.Refused, OSError) as e:
        log.info("CCR task file for %s not read: %s", a.get("rid"), e)
        return "?"
    if t:
        a["task_id"], a["task_at"] = t["task_id"], t.get("imported_at") or t["mtime"]
        return t["task_id"]
    return ""


def _hark_take_back(vid, a, cleared):
    """1.4.6 review: before a withdraw, dismiss or Mark filed on a draft Hark may still file (HARK_LIVE with a rid).
    With no HOM task yet, the Watcher removes its own request file so HOM never imports it (and checks again for a
    task HOM made meanwhile). With a HOM task, nothing reaches HOM from here (the file contract has no withdraw), so
    Ryan must say he completed that task as skipped in HOM (cleared). Returns '' when the action may go ahead, else
    why not (kept as the act's hark_note for the card)."""
    tid = _hom_task(a)
    if not tid:
        try:
            CCR.remove_request(CCR_DIR, a["rid"])
        except (CCR.Refused, OSError) as e:
            return f"the request to Hark could not be taken back ({e}); nothing changed"
        tid = _hom_task(a)
        if not tid:
            a["withdrawn_at"] = now_iso()
            return ""
    if cleared is True:
        a["withdrawn_at"] = now_iso()
        return ""
    return (f"Hark has HOM task {tid if tid != '?' else '(not readable)'} for this CCR. Complete it as skipped in HOM, "
            f"then tick 'I completed HOM task {tid} as skipped' and tap again; otherwise Hark files it too.")


def recall_act(payload):
    """{id, action: confirm|dismiss|approve|filed|reopen|file_request|withdraw, narrative?, ccr?, hom_cleared?}.
    Ryan's answers from the push or the tab. approve stores his reviewed narrative; file_request (1.4.6) hands the
    approved narrative to Hark through the HOM app (recall_file_request); the Watcher itself files nothing.
    {refresh: true} re-judges every list on file (the tab's Refresh button), and {me: {...}} changes seniority, seat
    and the per-month Over 75 answer.
    1.4.6 review: while Hark may still file the draft (filing, blocked, cancelled with a rid), confirm / reopen do
    nothing and approve in filing does nothing; withdraw (back to approved), dismiss and Mark filed take the request
    back when HOM has no task yet, and otherwise need hom_cleared: Ryan says he completed the HOM task as skipped.
    An approve in blocked / cancelled keeps that status when HOM has a task (Hark's task is still what it was), else
    takes the old request back (HOM rejected it) and the draft is approved, ready to send again."""
    try:
        d = json.loads(payload or "{}")
        if d.get("refresh"):  # Ryan (Nov 6): the tab's Refresh re-judges every list on file now; no push, no FLICA read
            recall_eval()
            return
        if d.get("me"):
            with RECALL_LOCK:
                recall_me_set(d["me"])
                recall_eval()
            return
        if d.get("action") == "file_request":
            recall_file_request(d)
            return
        with RECALL_LOCK:
            acts = DB.get("recall_acts") or {}
            a = acts.get(str(d.get("id")))
            act = d.get("action")
            st = {"confirm": "confirmed", "dismiss": "dismissed", "approve": "approved", "filed": "filed", "reopen": "new",
                  "withdraw": "approved"}.get(act)
            if not a or not st:
                return
            cur = a.get("status")
            if cur == "superseded":  # FW-0012: the row is no longer a miss; a late tap on an old push does nothing
                log.info("recall action %s on %s skipped: superseded (%s)", act, d.get("id"), a.get("superseded_why", ""))
                return
            hark = cur in HARK_LIVE and bool(a.get("rid"))
            if act == "withdraw" and not hark:
                return
            keep_status = False
            if hark:
                if act in ("confirm", "reopen") or (act == "approve" and cur == "filing"):
                    log.info("recall action %s on %s skipped: Hark has the CCR request %s", act, d.get("id"), a.get("rid"))
                    return
                if act == "approve":  # with a HOM task, Hark's task stays what it was: the new text is for filing by hand
                    keep_status = bool(_hom_task(a)) or bool(_hark_take_back(d.get("id"), a, None))
                else:
                    why = _hark_take_back(d.get("id"), a, d.get("hom_cleared"))
                    if why:
                        log.info("recall action %s on %s held: %s", act, d.get("id"), why)
                        a["hark_note"] = why
                        DB.put("recall_acts", acts)
                        recall_eval()
                        return
                    for k in ("hark_reason", "hark_at"):
                        a.pop(k, None)
            a.pop("hark_note", None)
            a["at"] = now_iso()
            if not keep_status:
                a["status"] = st
            if isinstance(d.get("narrative"), str) and d["narrative"].strip() and act == "approve":
                a["narrative"] = d["narrative"].strip()[:6000]
            if d.get("ccr") and act == "filed":
                a["ccr"] = str(d["ccr"])[:80]
            if act == "approve":  # 1.4.6: what Hark gets is the narrative as approved now
                a["approved_at"] = a["at"]
                if not keep_status:
                    for k in ("hark_reason", "hark_at"):
                        a.pop(k, None)
            DB.put("recall_acts", acts)
            recall_eval()
        if act == "approve":
            pub("event/recall_approved", {"id": d["id"], "narrative": a["narrative"]}, retain=False)
    except Exception as e:
        log.info("recall action skipped: %s", e)


def _recall_verdict(vid):
    for day in (DB.get("recall_days") or {}).values():
        for v in day.get("verdicts") or []:
            if v.get("id") == vid:
                return v
    return None


def recall_file_refusal(vid, a, v, narrative=None):
    """Why a CCR request for this act may not go to Hark, or '' when it may. narrative: the text the card's box held
    when Ryan tapped (1.4.6 review: it must be what he approved)."""
    if INSTANCE:
        return "only Ryan's Watcher asks Hark to file CCRs in this release"
    if not a:
        return "no CCR draft for this row"
    if a.get("status") == "superseded":
        return "the row is no longer a miss (superseded); a superseded draft is never filed"
    if a.get("status") not in ("approved", "blocked", "cancelled") or not (a.get("approved_at") or a.get("status") == "approved"):
        return f"the narrative is not approved (status {a.get('status')})"
    if not str(a.get("narrative") or "").strip():
        return "no narrative"
    if isinstance(narrative, str) and narrative.strip() != str(a.get("narrative") or "").strip():
        return "the narrative box differs from what you approved; re-approve it first"
    if not v or v.get("verdict") not in RECALL_LIVE:
        return "the row is no longer MISSED or POSSIBLE"
    if not CCR.rid_for(vid):
        return "this row's date, pairing and kind do not make a request name"
    tid = _hom_task({**a, "rid": CCR.rid_for(vid)})
    if tid:  # 1.4.6 review: HOM makes one task per rid, ever; a second request under it would never be answered
        return (f"Hark already had HOM task {tid} for this row; HOM never takes a second request under the same name. "
                f"File it yourself")
    return ""


def recall_file_request(d):
    """1.4.6 (Ryan, Nov 6): 'Have Hark file this CCR'. Only for an act whose narrative Ryan approved and whose row is
    still MISSED / POSSIBLE, on Ryan's Watcher, while HOM has no task for its rid. Writes <rid>.json in CCR_DIR (ccr.py
    contract) with the narrative as approved, sets the act to 'filing' and fires event/recall_file_requested. Hark
    files on hal.alpa.org from the HOM task; ccr_poll() reads the answer. Returns True when the request was written.
    A refusal is kept as the act's hark_note so the card can say why."""
    vid = str(d.get("id") or "")
    with RECALL_LOCK:
        acts = DB.get("recall_acts") or {}
        a, v = acts.get(vid), _recall_verdict(vid)
        why = recall_file_refusal(vid, a, v, d.get("narrative"))
        if why:
            log.info("CCR request for %s refused: %s", vid, why)
            if a and a.get("status") != "superseded" and not INSTANCE:
                a["hark_note"] = f"Not sent to Hark: {why}."
                DB.put("recall_acts", acts)
                recall_eval()
            return False
        now = now_iso()
        rid = CCR.rid_for(vid)
        rec = {"v": 1, "rid": rid, "id": vid, "pilot": CCR_PILOT, "date": v["date"], "pairing": v["pairing"],
               "kind": v["kind"], "seat": v.get("seat") or "FO", "narrative": a["narrative"],
               "approved_at": a.get("approved_at") or a.get("at") or now, "requested_at": now}
        try:
            CCR.write_request(CCR_DIR, rec)
        except (CCR.Refused, OSError) as e:
            log.warning("CCR request for %s not written: %s", vid, e)
            a["hark_reason"], a["hark_at"] = f"the request could not be written ({e})", now
            DB.put("recall_acts", acts)
            recall_eval()
            return False
        for k in ("hark_reason", "hark_at", "task_id", "task_at", "hark_bad", "withdrawn_at", "hark_alert",
                  "hark_alert_at", "hark_alert_what", "hark_ccr", "hark_note"):
            a.pop(k, None)
        a.update(status="filing", rid=rid, requested_at=now, at=now)
        DB.put("recall_acts", acts)
        recall_eval()
    log.info("CCR request %s written for Hark", rid)
    pub("event/recall_file_requested", {"id": vid, "rid": rid, "date": rec["date"], "pairing": rec["pairing"],
                                        "kind": rec["kind"], "requested_at": now}, retain=False)
    return True


def _same_ccr(a, b):
    n = lambda x: re.sub(r"[^0-9a-z]", "", str(x or "").lower())  # noqa: E731
    return bool(n(a)) and n(a) == n(b)


def ccr_poll():
    """1.4.6: HOM's answers to this Watcher's CCR requests (ccr.py), once a minute, no FLICA. <rid>.done.json -> the act
    is 'filed' with the CCR number (event/recall_ccr_filed); <rid>.status.json -> 'blocked' / 'cancelled' with the
    reason; <rid>.task.json -> the HOM task id. Replies older than the request are ignored; a reply that breaks the
    contract is logged once and left alone. A superseded act records what Hark did in 'was'.
    1.4.6 review: a blocked / cancelled act goes back to 'filing' when HOM removed its status file and the task is
    there (the task is open again). Every act that ever had a request keeps being read after Ryan took it back
    (withdraw, dismiss, Mark filed): a CCR number from Hark that is not the one Ryan entered, or a task HOM made after
    the request was taken back, fires event/recall_hark_alert once. Returns True when something changed."""
    events, alerts = [], []
    with RECALL_LOCK:
        acts = DB.get("recall_acts") or {}
        changed = False
        for vid, a in acts.items():
            st = a.get("status")
            cur = a.get("was") if st == "superseded" else st
            rid, req = a.get("rid"), a.get("requested_at")
            if not rid or not cur:
                continue
            live = cur in HARK_LIVE
            try:
                task, done, stat = (CCR.read_reply(CCR_DIR, rid, k) for k in ("task", "done", "status"))
            except CCR.Refused as e:
                if a.get("hark_bad") != str(e):
                    log.warning("CCR reply for %s refused: %s", rid, e)
                    a["hark_bad"], changed = str(e), True
                continue
            except OSError as e:
                log.info("CCR replies for %s not read: %s", rid, e)
                continue
            task_ok = bool(task) and CCR.fresh(task, req, "imported_at")
            if task_ok and a.get("task_id") != task["task_id"]:
                late = not live and not a.get("task_id")
                a["task_id"], a["task_at"], changed = task["task_id"], task.get("imported_at") or task["mtime"], True
                if late:
                    alerts.append(_hark_alert(vid, a, "late_task", (
                        f"HOM made task {task['task_id']} for {_act_label(vid)} after you took the request back. "
                        f"Complete it as skipped in HOM, or Hark files this CCR.")))
            if done and CCR.fresh(done, req, "filed_at"):
                if live:
                    a.update(ccr=done["ccr"], filed_at=done.get("filed_at") or done["mtime"], filed_by=done["by"],
                             filed_note=done["note"], hark_ccr=done["ccr"], at=now_iso())
                    a.pop("hark_reason", None)
                    a.pop("hark_at", None)
                    a["was" if st == "superseded" else "status"] = "filed"
                    changed = True
                    events.append({"id": vid, "rid": rid, "ccr": a["ccr"], "filed_at": a["filed_at"], "by": a["filed_by"],
                                   "date": vid.split("|")[0], "pairing": vid.split("|")[1], "kind": vid.split("|")[2]})
                    log.info("CCR %s filed by %s for %s", a["ccr"], a["filed_by"], rid)
                elif a.get("hark_ccr") != done["ccr"]:
                    a["hark_ccr"], changed = done["ccr"], True
                    if cur == "filed" and _same_ccr(a.get("ccr"), done["ccr"]):  # Ryan typed Hark's own number
                        a.update(filed_by=done["by"], filed_at=done.get("filed_at") or done["mtime"], filed_note=done["note"])
                    else:
                        mine = {"filed": f"you marked it filed as CCR {a.get('ccr') or '(no number)'}",
                                "dismissed": "you marked it not a miss"}.get(cur, "you took the request back")
                        alerts.append(_hark_alert(vid, a, "duplicate", (
                            f"Hark filed CCR {done['ccr']} for {_act_label(vid)}, but {mine}. Check hal.alpa.org for "
                            f"a second CCR.")))
                continue
            if not live:
                continue
            if stat and CCR.fresh(stat, req, "at"):
                at = stat.get("at") or stat["mtime"]
                if cur != stat["status"] or a.get("hark_at") != at:
                    a["hark_reason"], a["hark_at"] = stat["reason"] or "no reason given", at
                    a["was" if st == "superseded" else "status"] = stat["status"]
                    changed = True
                    log.info("CCR request %s %s by HOM: %s", rid, stat["status"], a["hark_reason"])
            elif cur in ("blocked", "cancelled") and task_ok and not stat:  # HOM cleared it: the task is open again
                a.pop("hark_reason", None)
                a.pop("hark_at", None)
                a["was" if st == "superseded" else "status"] = "filing"
                changed = True
                log.info("CCR request %s: HOM task %s is open again", rid, a.get("task_id"))
        if changed:
            DB.put("recall_acts", acts)
            recall_eval()
    for p in events:
        pub("event/recall_ccr_filed", p, retain=False)
    _pub_hark_alerts(alerts)
    return changed


def ccr_thread():
    """1.4.6: ccr_poll() every CCR_POLL_S in its own thread, so it keeps running while the FLICA loop waits."""
    while True:
        time.sleep(CCR_POLL_S)
        try:
            ccr_poll()
        except Exception as e:
            log.info("CCR poll: %s", e)


def publish_recall():
    allr, acts = DB.get("recall_days") or {}, DB.get("recall_acts") or {}
    days = [{k: v for k, v in allr[k].items() if k != "rows"} for k in sorted(allr)[-45:]]
    opn = [v for d in days for v in d.get("verdicts") or []
           if v.get("verdict") in RECALL_LIVE and (v.get("act") or {}).get("status") in RECALL_OPEN]
    alert = [v for v in opn if v["verdict"] == "MISSED"]  # 1.4.6 (Ryan): RECALL ALERT = the Watcher says he should have been called
    received = max((d.get("at") or "" for d in allr.values()), default="")  # when the newest list post came in
    # FW-0060: every day goes to recall_<key>.json for the recall card (about 380 bytes a verdict: 45 days would pass
    # the recorder's 16 KB); the sensor keeps the newest days that fit (cap_attrs) and the counts over all of them
    key, rev = write_list_file("recall", {"days": days[::-1]})
    pub("recall", {"open": len(opn), "alert": len(alert), "me": recall_me(), "last": days[-1]["date"] if days else "",
                   "checked": now_iso(), "received": received, "hark_files": not INSTANCE, "days": days[::-1],
                   "days_total": len(days), "file_key": key, "rev": rev})


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
        stale = k in cache and ("crew" not in cache[k] or "duties" not in cache[k])  # cached before 0.4.0 / FW-0039: re-read once
        if (k not in cache or stale or full) and fetched < (FULL_MAX if full else DETAIL_MAX_PER_CHECK):
            if fetched:
                time.sleep(random.uniform(1.5, 3.5))
            ev = dict(row)
            enrich(fl, ev)
            fetched += 1
            cache[k] = {f: ev.get(f, "") for f in DETAIL_FIELDS}
            cache[k]["duties"] = ev.get("duties") or []  # FW-0039: the FAR screen's FDPs; kept off the published row
        if k in cache:
            row.update({f: v for f, v in cache[k].items() if f in DETAIL_FIELDS and (v or not row.get(f))})
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
    close_in_scan(menu or "", "left menu")  # FW-0034: the close-in folder's link, if the menu names it
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
    """0.8.5: Ryan's own employee number from a FLICA page header ('pettit, ryan 9711 - hnl 332 fo'),
    kept in state for the Schedule Lookup reads of his other months."""
    m = OWN_RE.search((text or "").lower())
    if m and S.get("own_emp") != m.group(2):
        S["own_emp"], S["own_name"] = m.group(2), m.group(1).title()
        S["sched_prev_at"] = S["sched_checked_at"] = 0  # read the other months on the next pass
        log.info("own employee number noted from the page header")
    return S.get("own_emp")


LOOKUP_KEYS = ("block", "credit")
LOOKUP_PAGE = {"bd": "", "html": "", "at": 0}  # the last Schedule Lookup page read, so other_months_check does not load it twice


def lookup_totals(fl, month):
    """FW-0019: FLICA's Block / Credit for `month` (YYYY-MM) from Tools > Schedule Lookup for the pilot's own number
    (cmschedules.cgi bd=MMYY, a plain GET that passes both safe_get checks, paced 1.5 to 3.5 s). The mobile schedule
    page the current month comes from carries no totals; the lookup page does (October's read showed them).
    {} when the number is not known yet, the URL is refused or the page is not that month's schedule."""
    emp = S.get("own_emp")
    if not emp or not re.match(r"^\d{4}-\d{2}$", month or ""):
        return {}
    bd = f"{month[5:7]}{month[2:4]}"
    url = IF.CM_SCHED_MONTH.format(base=BASE, emp=emp, bd=bd)
    if not (SUB.safe_get(url) and SM.safe_get(url)):
        log.info("schedule %s totals: lookup url refused by safe_get", month)
        return {}
    time.sleep(random.uniform(1.5, 3.5))
    html = fl.fetch(url)
    sp = IF.parse_cm_month(html) if classify(html) == "ok" else None
    if not sp or sp["month"] != month:
        log.info("schedule %s totals via Schedule Lookup (bd=%s): %s %s", month, bd, classify(html),
                 (sp and sp["month"]) or visible_text(html)[:120])
        return {}
    LOOKUP_PAGE.update(bd=bd, html=html, at=time.time())
    return {k: v for k, v in (sp.get("totals") or {}).items() if k in LOOKUP_KEYS and v not in (None, "")}


def merge_lookup_totals(fl, s, old=None):
    """FW-0019: fill the Block / Credit a schedule page lacks from the Schedule Lookup page, so schedule versions see
    FLICA's totals change. A missed lookup keeps the figures last stored for the month (old), so a failed read is
    never taken for a schedule change. Figures the schedule page has itself are kept."""
    tot = s.setdefault("totals", {})
    if all(k in tot for k in LOOKUP_KEYS):
        return
    try:
        got = lookup_totals(fl, s.get("month"))
    except Exception as e:
        log.info("schedule %s totals via Schedule Lookup failed: %s", s.get("month"), e)
        got = {}
    if not got and old and old.get("month", s.get("month")) == s.get("month"):
        got = {k: v for k, v in (old.get("totals") or {}).items() if k in LOOKUP_KEYS}
    for k in LOOKUP_KEYS:
        if k not in tot and got.get(k) not in (None, ""):
            tot[k] = got[k]


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
    bdc = f"{cur.month:02d}{cur.year % 100:02d}"
    if LOOKUP_PAGE["bd"] == bdc and time.time() - LOOKUP_PAGE["at"] < 300:
        html = LOOKUP_PAGE["html"]  # FW-0019: the schedule check's totals read just loaded this page
    else:
        time.sleep(random.uniform(1.5, 3.5))
        html = fl.fetch(IF.CM_SCHED_MONTH.format(base=BASE, emp=emp, bd=bdc))
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
    """Read only: GET Ryan's month schedule (mobileschedule.cgi), publish sensor.flight_watcher_schedule
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
        read_at = now_iso()
        merge_lookup_totals(fl, s, old)  # FW-0019: the mobile page has no Block / Credit; Schedule Lookup does
        if old and [(i["trip"], i["start"]) for i in old["items"]] != [(i["trip"], i["start"]) for i in s["items"]]:
            ev = {"month": s["month"], "updated": s["updated"],
                  "added": sorted({i["trip"] + " " + i["start"] for i in s["items"]} - {i["trip"] + " " + i["start"] for i in old["items"]}),
                  "removed": sorted({i["trip"] + " " + i["start"] for i in old["items"]} - {i["trip"] + " " + i["start"] for i in s["items"]}),
                  "totals": s["totals"]}
            log.info("SCHEDULE changed %s", ev)
            pub("event/schedule_changed", ev, retain=False)
            try:  # FW-0064; never fails the read (an error here must not make schedule_check load another URL)
                if not old.get("src"):  # the same page read twice; a month first read on Schedule Lookup is not
                    sched_moves_record(s["month"], old["items"], s["items"], s.get("updated"), read_at)
            except Exception as e:
                log.info("schedule moves not recorded: %s", e)
        S["sched_read_at"] = read_at  # FW-0064: a trade seen on the schedule is decided one quiet read later
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
        try:
            trade_check()  # FW-0064
        except Exception as e:
            log.info("schedule trade check skipped: %s", e)
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


CAPTURE_DIR = f"{SHARE}/captures"


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
REQ_IDLE_GAP_S = 900     # 1.2.0: Open Time Requests read every 15 min,
REQ_PENDING_GAP_S = 120  # every 2 min while a request is pending, and right after a yield to Ryan's own login
REQ_FIRST_H = 6  # the feature's first read: decisions filed this recently are still pushed


MON3 = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


def ha_state(entity_id):
    """1.2.1: one entity's state from Home Assistant (Supervisor API proxy, homeassistant_api in config.yaml);
    None when unreachable."""
    try:
        r = requests.get(f"http://supervisor/core/api/states/{entity_id}",
                         headers={"Authorization": f"Bearer {os.environ.get('SUPERVISOR_TOKEN', '')}"}, timeout=5)
        return r.json().get("state") if r.ok else None
    except Exception:
        return None


def pay_settings():
    """(rate, longevity year, ER list) the way the schedule card reads them: the longevity year helper, else the
    DOH in /data/cards.json; rate for today (HST); the per-trip Extended Range list helper."""
    today = local_now().date().isoformat()
    yr = None
    try:
        yr = int(float(ha_state(f"input_number.{T}_longevity_year")))
    except (TypeError, ValueError):
        pass
    if not yr:
        try:
            yr = min(12, PAY.doh_year(json.load(open(f"{DATA}/cards.json"))["doh"], today))
        except Exception:
            yr = None
    er = [x for x in str(ha_state(f"input_text.{T}_er_trips") or "").split(",") if x]
    return (PAY.rate_for(yr, today) if yr else None), yr, er


def _package(month, cache):
    if month not in cache:
        try:
            d = json.load(open(os.path.join(CARD_PAIRINGS, f"pairings_{month}.json")))
            cols = d.get("cols") or []
            cache[month] = {r[0]: dict(zip(cols, r)) for r in d.get("rows") or [] if r}
        except Exception:
            cache[month] = {}
    return cache[month]


def _filed_at(r, now):
    """The request's filing time (HST) from its MM/DD and HH:MM: this year, or last year when that is in the future."""
    mo, dd = (int(x) for x in r["date"].split("/"))
    hh, mi = (int(x) for x in r["time"].split(":"))
    t = datetime(now.year, mo, dd, hh, mi, tzinfo=HST)
    return t.replace(year=now.year - 1) if t > now + timedelta(days=1) else t


def _own_trips_at(t):
    """Ryan's trips ({TRIP: start}) on the schedule version in force at time t (versions are stamped UTC)."""
    out = {}
    for month in sorted(S.get("schedule") or {}):
        vers = DB.get(f"sched_versions:{month}") or []
        before = [v for v in vers if v.get("at") and datetime.fromisoformat(v["at"]) <= t]
        for it in (before[-1] if before else (vers[0] if vers else {})).get("items") or []:
            if it.get("trip"):
                out.setdefault(it["trip"], it.get("start"))
    return out


def price_request(r, now=None):
    """1.2.1 (Ryan): Pay-Gross change of an Approved request: + for a pickup, - for a drop, the net for a swap.
    Each leg is a trip given (drop) or taken (add): from the page's own words when it has them, else Add / Drop
    by the request type, else for a swap or a trade (1.4.1) the trips Ryan held when he filed are the ones given. A
    trip given is priced from his own trip record (FLICA's credit, block, seat), a trip taken from the month's pairing
    package in the seat the view page marks, (F) / (R) / (C), FO when unmarked (1.4.1). None when any leg cannot be
    priced; the push then goes out without an amount."""
    if r.get("status") != "Approved" or not r.get("legs"):
        return None
    now = now or local_now().replace(tzinfo=HST)
    rate, yr, er = pay_settings()
    if not rate:
        return None
    filed = _filed_at(r, now)
    held = _own_trips_at(filed.astimezone(timezone.utc))
    own, cache, parts = S.get("own_trips") or {}, {}, []

    def was_held(leg):  # Ryan held this trip (on this date, when the page gives one) when he filed
        st = held.get(leg["trip"])
        if not st:
            return False
        d = leg.get("day") or ""
        return not d or (st[8:10] == d[:2] and MON3.index(d[2:]) + 1 == int(st[5:7]))
    # 1.2.2 review: the request type decides an Add or a Drop; a swap's sides come from what Ryan held when he
    # filed. Page words only when no schedule version is on file, and only when they name both sides; else no
    # amount (a missing Pay-Gross beats a wrong one).
    typed = {"Add": "add", "Drop": "drop"}.get(r["type"])
    words = [leg.get("side") or "" for leg in r["legs"]]
    if not typed:
        sides = [("drop" if was_held(leg) else "add") for leg in r["legs"]] if held else words
        if "drop" not in sides or "add" not in sides or not all(sides):
            return None
    for i, leg in enumerate(r["legs"]):
        trip = leg["trip"]
        side = typed or sides[i]
        start = held.get(trip) if side == "drop" else None
        if not start and leg.get("day"):
            mo = MON3.index(leg["day"][2:]) + 1
            y = filed.year + (1 if mo < filed.month - 6 else 0)
            start = f"{y}-{mo:02d}-{leg['day'][:2]}"
        if not start:
            return None
        rec = (own.get(f"{trip}|{start}") or {}) if side == "drop" else {}
        pk = _package(start[:7], cache).get(trip[:5]) or {}
        credit = PAY.hrs(rec.get("credit")) if rec.get("credit") else PAY.hrs(pk.get("credit"))
        block = PAY.hrs(rec.get("blk")) if rec.get("blk") else PAY.hrs(pk.get("block"))
        lay = "/".join(x for x in str(pk.get("route") or "").split("-") if x and x != "HNL")
        seat = rec.get("seat") or leg.get("seat") or "FO"  # 1.4.1: a taken trip's seat from the view page's (F)/(R)/(C)
        g = PAY.trip_gross(credit, block, pk.get("crew"), lay, f"{trip}|{start}", seat, rate, er)
        if g is None:
            return None
        parts.append({"trip": trip, "start": start, "side": side, "gross": round(g, 2),
                      "credit": rec.get("credit") or pk.get("credit") or ""})
    delta = sum(p["gross"] for p in parts if p["side"] == "add") - sum(p["gross"] for p in parts if p["side"] == "drop")
    return {"delta": round(delta, 2), "delta_text": PAY.usd(delta), "parts": parts, "rate": rate, "year": yr}


# ---------------------------------------------------------------- FW-0034: the close-in open time folder
CLOSE_IN_KEY = "closein"  # its rows' month key (pot rows, finds)
CLOSE_IN_GAP_S = 6 * 3600  # a menu read every 6 h while the folder is not known,
CLOSE_IN_RECHECK_S = 86400  # once a day once it is (a new bid period can bring a new BCID)
CLOSE_IN_BAD_MAX = 3  # reads that are not its open time page before its BCID is dropped


def close_in_url(b):
    return f"{BASE}/full/mobileopentimepot.cgi?BCID={b}&From=MainMenu"


def _regular_bcids():
    return {x for x in (bcid(u) for u in (S.get("pot_urls") or {}).values()) if x}


def close_in_scan(html, via):
    """FW-0034: look for the close-in folder ('Close in Opentime: <16 Hrs to RPT') on a page already read (a menu or
    an open time page; pot.close_in_folders: a link whose text names it, never a guess). A BCID found becomes the
    candidate, logged once; it is used only once its own open time page reads (close_in_check). Never fetches.
    Returns the BCID found, or None."""
    try:
        reg = _regular_bcids()
        ci = S.get("close_in") or {}
        ex = reg | {f"001.{b.split('.')[-1]}" for b in reg} | set(ci.get("rejected") or [])  # 001.n: Tradeboard
        found = close_in_folders(html, ex)
        b = pick_close_in(found, {x.split(".")[-1] for x in reg})
    except Exception as e:
        log.info("close-in scan of the %s failed: %s", via, e)
        return None
    if not b:
        return None
    ci = S.setdefault("close_in", {})
    if ci.get("bcid") != b:
        log.info("close-in folder found on the %s: BCID %s ('%s'); its open time page is read next, GET only", via, b,
                 next(f["text"] for f in found if f["bcid"] == b))
        for k in ("verified", "verified_at", "bad", "baseline"):  # a new folder: its own baseline, no alert storm
            ci.pop(k, None)
        ci.update(bcid=b, via=via, found_at=now_iso())
        S["close_in_bcid"] = None  # drafts and the request list wait for its page to read
    return b


def close_in_menu_read(fl):
    """FW-0034: the menu read that finds the close-in folder, read only: the left menu (leftmenu.cgi, a plain GET), and
    when that holds no menu tree (FLICA builds it only inside the menu frame), the main menu's menu frame (rendered in
    a tab like the pot discovery, no clicks). Both URLs pass SUB.safe_get and SM.safe_get; paced 1.5 to 3.5 s. Every
    6 h while the folder is not known (or its BCID is of no bid period watched), once a day once it is. A menu that
    does not name the folder is logged and kept privately (CAPTURE_DIR/menu_closein.html, session token masked) so
    its shape can be checked. Returns the BCID found, or None."""
    ci = S.setdefault("close_in", {})
    periods = {x.split(".")[-1] for x in _regular_bcids()}
    settled = ci.get("verified") and (not periods or ci["bcid"].split(".")[-1] in periods)  # a new bid period: look again
    if time.time() - ci.get("menu_at", 0) < (CLOSE_IN_RECHECK_S if settled else CLOSE_IN_GAP_S):
        return None
    ci["menu_at"] = time.time()
    seen, keep = [], ""
    for url, how in ((LEFTMENU, "left menu"), (f"{BASE}/online/mainmenu.cgi", "main menu frame")):
        if not (SUB.safe_get(url) and SM.safe_get(url)):
            seen.append(f"{how}: refused by safe_get")
            continue
        time.sleep(random.uniform(1.5, 3.5))
        try:
            html = (fl.fetch(url) if how == "left menu" else fl.menu_tree()) or ""
        except Exception as e:
            seen.append(f"{how}: {e}")
            continue
        kind = classify(html) if html else "empty"
        if kind != "ok":
            seen.append(f"{how}: {kind}")
            if kind in ("killed", "expired", "blocked"):
                break
            continue
        b = close_in_scan(html, how)
        if b:
            return b
        named = bool(CLOSE_IN_RE.search(visible_text(html)))
        seen.append(f"{how}: {len(html)} chars, " + ("names the folder but no BCID link" if named else
                                                       "no close-in folder named"))
        keep = html
        if "addC(" in html or "addE(" in html or "BCID=" in html.upper():
            break  # a real menu that does not name it; the frame would show the same
    log.info("close-in folder not on the menu yet: %s", "; ".join(seen) or "nothing read")
    if keep:
        try:
            os.makedirs(CAPTURE_DIR, exist_ok=True)
            open(f"{CAPTURE_DIR}/menu_closein.html", "w").write(re.sub(r"token=[0-9A-Za-z]+", "token=MASKED", keep))
        except Exception:
            pass
    return None


def close_in_check(fl, pot_all, full=False):
    """FW-0034 (Ryan: trips under 16 h to report reached him only through FLICA's alert email): read only, the close-in
    folder. Finds its BCID (close_in_menu_read when due; close_in_scan of pages read anyway), then GETs its open time
    page (mobileopentimepot.cgi?BCID=<its BCID>, both safe_get guards, paced 1.5 to 3.5 s). The BCID is trusted (swap
    and drop drafts, the request list) only once that page reads as an open time page of the pilot's category
    (OPTS category_check); CLOSE_IN_BAD_MAX reads that do not drop it. Its pairings not in a regular pot join the pot
    rows (src 'C', folder 'close-in'), with details, the FAR column and finds; a new one fires event/new_pairing like
    a pot find (none on the folder's first read). Returns those rows {key: row}."""
    ci = S.setdefault("close_in", {})
    if not ci.get("bcid") or ci.get("verified"):
        close_in_menu_read(fl)
    b = ci.get("bcid")
    if not b:
        return {}
    url = close_in_url(b)
    if not (SUB.safe_get(url) and SM.safe_get(url)):
        log.info("close-in %s: url refused by safe_get", b)
        return {}
    time.sleep(random.uniform(1.5, 3.5))
    try:
        html = fl.fetch(url)
    except Exception as e:
        log.info("close-in %s error: %s", b, e)
        return {}
    kind = classify(html)
    if kind != "ok":
        log.info("close-in %s: %s, skipped", b, kind)
        return {}
    text = visible_text(html)
    cat = [c.lower() for c in (OPTS.get("category_check") or "").split()]
    if not (is_pot_page(html) and all(c in text for c in cat)):
        ci["bad"] = ci.get("bad", 0) + 1
        log.info("close-in %s: not an open time page of %s (%d of %d): %s", b, OPTS.get("category_check"), ci["bad"],
                 CLOSE_IN_BAD_MAX, text[:160])
        if ci["bad"] >= CLOSE_IN_BAD_MAX:
            log.info("close-in BCID %s dropped; the menu is read again", b)
            ci["rejected"] = (ci.get("rejected") or [])[-4:] + [b]
            for k in ("bcid", "verified", "verified_at", "bad", "via", "found_at", "menu_at", "baseline"):
                ci.pop(k, None)
            S["close_in_bcid"] = None
        return {}
    ci["bad"] = 0
    if not ci.get("verified"):
        ci.update(verified=True, verified_at=now_iso())
        log.info("close-in folder %s verified (found on the %s): its open time page reads; text: %s", b, ci.get("via"),
                 text[:300])
        try:  # a private copy for parser checks (/share, never git)
            os.makedirs(CAPTURE_DIR, exist_ok=True)
            open(f"{CAPTURE_DIR}/pot_closein_{b.split('.')[-1]}.html", "w").write(html)
        except Exception:
            pass
    S["close_in_bcid"] = b
    pot = parse_pot(html)
    regular = {k: r for p in pot_all.values() for k, r in p.items()}
    rows = {k: dict(r, src="C", folder="close-in") for k, r in pot.items() if k not in regular}
    cache = S.get("details") or {}
    if full or any(k not in cache or "duties" not in cache[k] for k in rows):
        time.sleep(random.uniform(1.5, 3.5))  # pot_details paces its own reads after the first
    pot_details(fl, rows, full)
    base, new_keys = ci.get("baseline"), set()
    if base is None:
        log.info("close-in baseline %s: %d pairings (no alert)", b, len(pot))
    else:
        new_keys = {k for k in rows if k not in base}
        for k in sorted(new_keys):
            ev = {**rows[k], "month": CLOSE_IN_KEY, "seen": now_iso()}
            if not ev.get("detail_url"):  # details not read yet (pot_details' per-check cap)
                time.sleep(random.uniform(1.5, 3.5))
                enrich(fl, ev)
            log.info("NEW close-in pairing %s", ev)
            pub("event/new_pairing", ev, retain=False)
            pub("last_new", ev)
            run_rules(CLOSE_IN_KEY, k, rows[k])
        pend = S.setdefault("pickup_pending", {})
        for k in set(base) - set(pot) - set(regular):
            pend.setdefault(k, {"tries": 0, "next": time.time() + PICKUP_FIRST_S})
    DB.record_pot(CLOSE_IN_KEY, {k: rows.get(k) or regular[k] for k in pot}, new_keys)
    ci["baseline"] = sorted(pot)
    return rows


def _request_view(fl, b, ts):
    """1.2.2: {legs, trips, detail} of one request from its read-only view page ({} when it cannot be read).
    The first view page of each folder is saved privately to CAPTURE_DIR for parser checks."""
    url = SUB.request_view_url(BASE, b, ts)
    if not (SUB.safe_get(url) and SM.safe_get(url)):
        log.info("request view %s: url refused by safe_get", ts)
        return {}
    try:
        time.sleep(random.uniform(1.5, 3.5))
        html = fl.fetch(url)
        if classify(html) != "ok":
            return {}
        text = visible_text(html)
        n = ("closein_" if b == S.get("close_in_bcid") else "") + b.split(".")[-1]
        if not S.get("req_view_captured", {}).get(n):
            S.setdefault("req_view_captured", {})[n] = True
            try:
                os.makedirs(CAPTURE_DIR, exist_ok=True)
                open(f"{CAPTURE_DIR}/otrequest_view_{n}.html", "w").write(html)
                log.info("request view %s captured; text: %s", ts, text[:600])
            except Exception:
                pass
        return SUB.parse_request_view(text)
    except Exception as e:
        log.info("request view %s error: %s", ts, e)
        return {}


def requests_check(fl):
    """1.2.0 (Ryan): read only, the Open Time Requests list of each watched bid folder. A swap, add or drop
    request that turns Approved or Denied (or first shows up already decided) fires event/request_decided once,
    which HA pushes to Ryan's phone. Only the list URL is fetched (SUB.safe_get + SM.safe_get): its Approved /
    Denied links carry QuickDelete=1 and would delete the request, so no link on the page is ever followed.
    Each decision is pushed once ever (S['ot_req_pushed']); on the feature's very first read only decisions filed
    in the last REQ_FIRST_H hours are news. FW-0034: the close-in folder's list is read too once its BCID is verified
    (close_in_check); its decisions carry folder 'close-in', and its own first read pushes only the last REQ_FIRST_H
    hours (older ones are history)."""
    rows_of = S.setdefault("ot_req_rows", {})  # bcid -> rows of the last good read
    regular = sorted({x for x in (bcid(u) for u in S.get("pot_urls", {}).values()) if x})
    ci = S.get("close_in_bcid") if (S.get("close_in") or {}).get("verified") else None
    folders = regular + ([ci] if ci and ci not in regular else [])
    done_first = S.setdefault("ot_req_first_done", {})  # FW-0034: folders (the close-in one) whose first read is done
    trows_of = S.setdefault("tb_req_rows", {})  # 1.4.3: tradeboard number -> Ryan's trade requests of the last good read
    pending = any(r.get("status") in SUB.OPEN for b in folders for r in rows_of.get(b) or []) or \
        any(r.get("status") in SUB.OPEN for rs in trows_of.values() for r in rs or [])
    gap = REQ_PENDING_GAP_S if pending else REQ_IDLE_GAP_S
    if not S.pop("req_force", False) and time.time() - S.get("req_checked_at", 0) < gap:
        return
    S["req_checked_at"] = time.time()
    pushed = S.setdefault("ot_req_pushed", {})
    empty = S.setdefault("ot_req_empty", {})
    first = not S.get("ot_req_init")
    now = datetime.now(HST)
    read_ok = False
    for b in folders:
        url = SUB.requests_url(BASE, b)
        if not (SUB.safe_get(url) and SM.safe_get(url)):
            log.info("requests %s: url refused by safe_get, skipped", b)
            continue
        try:
            time.sleep(random.uniform(1.5, 3.5))  # paced like every other FLICA page load
            html = fl.fetch(url)
            if classify(html) != "ok":
                log.info("requests %s: %s, skipped", b, classify(html))
                continue
            text = visible_text(html)
            rows = SUB.parse_request_rows(text, html)
            n = ("closein_" if b == ci else "") + b.split(".")[-1]  # capture names; FW-0034: the close-in list apart
            if not S.get("req_captured", {}).get(n):  # first read: a private copy for parser checks (/share)
                try:
                    os.makedirs(CAPTURE_DIR, exist_ok=True)
                    open(f"{CAPTURE_DIR}/otrequests_{n}.html", "w").write(html)
                    S.setdefault("req_captured", {})[n] = True
                    log.info("requests %s: %d rows, page captured; text: %s", b, len(rows), text[:600])
                except Exception:
                    pass
            ids = SUB.request_ids(html)
            if len(ids) != len(rows) or re.search(r"\b(trade|processing)\b", text, re.I):
                # 1.4.2: a row the parser does not know (Ryan's Nov 6 Trade was missed): keep a private copy of the
                # latest such page (/share, never git) and say how many requests the page has against rows read
                try:
                    os.makedirs(CAPTURE_DIR, exist_ok=True)
                    open(f"{CAPTURE_DIR}/otrequests_{n}_latest.html", "w").write(html)
                except Exception:
                    pass
                if S.get("req_mismatch_logged", {}).get(n) != len(ids):
                    S.setdefault("req_mismatch_logged", {})[n] = len(ids)
                    log.info("requests %s: %d requests on the page, %d rows read; latest page captured", b, len(ids), len(rows))
            if not SUB.is_request_page(text, rows):
                log.info("requests %s: not the request list, skipped: %s", b, text[:120])
                continue
            if not rows and rows_of.get(b) and empty.get(b, 0) < 1:  # a list gone empty must read so twice
                empty[b] = empty.get(b, 0) + 1
                log.info("requests %s: list empty after %d rows, read again before believing it", b, len(rows_of[b]))
                continue
            empty.pop(b, None)
            first_b = first or (b == ci and not done_first.get(b))
            for r in SUB.request_news(pushed, rows):
                try:
                    old = _filed_at(r, now) < now - timedelta(hours=REQ_FIRST_H)
                except Exception:
                    old = True
                if first_b and old:
                    continue  # the feature's (or the close-in folder's) first read: older decisions are history
                if r.get("ts") and not r.get("legs"):
                    r.update(_request_view(fl, b, r["ts"]))  # the list names no trips; its view page does
                ev = {**r, "bcid": b, "at": now_iso(), "url": url}
                if b == ci:
                    ev["folder"] = "close-in"
                try:
                    ev["pay"] = price_request(r)  # 1.2.1: Pay-Gross gained or given up (Approved only)
                except Exception as e:
                    log.info("request pay not priced: %s", e)
                    ev["pay"] = None
                log.info("request %s %s %s", r["type"], r["status"], r["detail"][:80])
                pub("event/request_decided", ev, retain=False)
                note_decided(r, now)  # FW-0064: its schedule changes are this request's, not a trade's
            if rows and rows[-1].get("ts") and not S.get("req_view_captured", {}).get(n):
                _request_view(fl, b, rows[-1]["ts"])  # once: a private copy of a view page for parser checks
            for r in rows:
                if r["status"] in SUB.DECIDED:
                    pushed[SUB.push_key(r)] = now_iso()  # last seen; pruned once gone 60 days
                    if r.get("alt"):  # the content key too: a read that falls back to it never re-pushes
                        pushed[f"{r['alt']}|{r['status']}"] = now_iso()
            rows_of[b] = rows
            if b == ci:
                done_first[b] = now_iso()
            read_ok = True
        except Exception as e:
            log.info("requests %s error: %s", b, e)
    tb_ok = _trade_requests_check(fl, regular, trows_of, pushed, now)
    try:
        trade_check()  # FW-0064: a decision just read explains schedule changes; a pending one may match them
    except Exception as e:
        log.info("schedule trade check skipped: %s", e)
    if folders:
        for b in [x for x in rows_of if x not in folders]:
            rows_of.pop(b, None)  # a folder no longer watched: its Pending rows no longer hold the 2-min poll
        nums = {b.split(".")[-1] for b in regular}
        for n in [x for x in trows_of if x not in nums]:
            trows_of.pop(n, None)
    cut = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
    for k in [k for k, v in pushed.items() if v < cut]:
        pushed.pop(k, None)
    if read_ok:
        S["ot_req_init"] = True
    save_state(S)
    tsig = json.dumps(trows_of, sort_keys=True)
    tb_new = tb_ok and tsig != S.get("tb_req_sig")  # 1.4.3: trades alone republish only when they changed
    if read_ok or tb_new:  # a failed pass keeps the last good sensor instead of showing 0 pending
        S["tb_req_sig"] = tsig
        shown = [{**r, "bcid": b, **({"folder": "close-in"} if b == ci else {})} for b in folders for r in rows_of.get(b) or []]
        shown += [{**r, "bcid": f"001.{n}"} for n in sorted(trows_of) for r in trows_of[n] or []]
        pub("ot_requests", {"pending": sum(1 for r in shown if r["status"] in SUB.OPEN), "count": len(shown),
                            "requests": shown[-20:], "checked_at": now_iso()})


def _trade_requests_check(fl, folders, trows_of, pushed, now):
    """1.4.3 (Ryan's Nov 6 Trade, which the Open Time Requests list never shows): read only, Ryan's Tradeboard 'My
    Requests' page for each watched bid month. A crew-to-crew Trade that turns Approved or Denied fires
    event/request_decided once (type Trade, with Pay-Gross), like an open time request; while one reads Processing
    or Pending the list is read every 2 min. The first read of each month (and a page that mentions a trade the
    parser cannot read) is kept privately in CAPTURE_DIR for parser checks. True when at least one page was read."""
    ok = False
    first = not S.get("tb_req_init")
    for n in sorted({b.split(".")[-1] for b in folders}):
        url = TB.my_requests_url(BASE, n)
        if not (SUB.safe_get(url) and SM.safe_get(url)):
            log.info("trade requests %s: url refused by safe_get, skipped", n)
            continue
        try:
            time.sleep(random.uniform(1.5, 3.5))  # paced like every other FLICA page load
            html = fl.fetch(url)
            if classify(html) != "ok":
                log.info("trade requests %s: %s, skipped", n, classify(html))
                continue
            text = visible_text(html)
            rows = TB.parse_my_requests(text)
            odd = not rows and re.search(r"\btrade\b.*\bemp\b", text, re.I | re.S)
            if not S.get("tbreq_captured", {}).get(n) or odd:
                try:
                    os.makedirs(CAPTURE_DIR, exist_ok=True)
                    open(f"{CAPTURE_DIR}/tb_myrequests_{n}{'_latest' if odd else ''}.html", "w").write(html)
                    S.setdefault("tbreq_captured", {})[n] = True
                    log.info("trade requests %s: %d rows, page captured; text: %s", n, len(rows), text[:600])
                except Exception:
                    pass
            for r in SUB.request_news(pushed, rows):
                try:
                    old = _filed_at(r, now) < now - timedelta(hours=REQ_FIRST_H)
                except Exception:
                    old = True
                if first and old:
                    continue  # the feature's first read: older decisions are history, not news
                ev = {**r, "bcid": f"001.{n}", "at": now_iso(), "url": url}
                try:
                    ev["pay"] = price_request(r)
                except Exception as e:
                    log.info("trade pay not priced: %s", e)
                    ev["pay"] = None
                log.info("trade %s %s", r["status"], r["detail"][:120])
                pub("event/request_decided", ev, retain=False)
                note_decided(r, now)  # FW-0064
            for r in rows:
                if r["status"] in SUB.DECIDED:
                    pushed[SUB.push_key(r)] = now_iso()
            trows_of[n] = rows
            ok = True
        except Exception as e:
            log.info("trade requests %s error: %s", n, e)
    if ok:
        S["tb_req_init"] = True
    return ok


# ---------------------------------------------------------------- FW-0064: a request decided on the schedule
DECIDED_KEEP_DAYS = 7


def note_decided(r, now=None):
    """FW-0064: an Approved decision the request path just pushed: its legs (or, with none read, its filing time and
    now) explain the schedule changes it made, so trade_check() never pushes them again as a trade."""
    if r.get("status") != "Approved":
        return
    try:
        now = now or datetime.fromisoformat(now_iso()).astimezone(HST)
        filed = _filed_at(r, now).astimezone(timezone.utc).isoformat()
    except Exception:
        filed = now_iso()
    cut = (datetime.fromisoformat(now_iso()) - timedelta(days=DECIDED_KEEP_DAYS)).isoformat()
    lst = [d for d in S.get("req_decided") or [] if d.get("seen", "") >= cut]
    lst.append({"key": r.get("key") or "", "type": r.get("type") or "", "filed": filed, "seen": now_iso(),
                "legs": [{k: x.get(k) for k in ("trip", "day", "side")} for x in r.get("legs") or []]})
    S["req_decided"] = lst[-50:]


def _move_rec(trip, start, month):
    """What a trip on Ryan's line pays, kept when it leaves the schedule (its own trip record is dropped then): credit,
    block and seat from his own trip record, else from the newest schedule version that held it; the number of pilots
    from its crew roster (PWA 4.O.1 overrides)."""
    k = f"{trip}|{start}"
    own = (S.get("own_trips") or {}).get(k) or {}
    if not own.get("credit"):
        for v in reversed(DB.get(f"sched_versions:{month}") or []):
            if (v.get("trips") or {}).get(k):
                own = {**v["trips"][k], **{f: x for f, x in own.items() if x}}
                break
    rec = {f: own.get(f) for f in ("credit", "blk", "seat") if own.get(f)}
    if own.get("crew"):
        rec["n"] = len(own["crew"])
    return rec


def sched_moves_record(month, old_items, new_items, updated, read_at):
    """FW-0064: the pairings this read dropped and added, kept in the state with what each dropped trip paid."""
    keys = lambda its: {f"{i['trip']}|{i['start']}" for i in its or []}  # noqa: E731
    dropped = keys(old_items) - keys(new_items)
    recs = {k: _move_rec(*k.split("|"), month) for k in dropped}
    mv = TR.moves(old_items, new_items, month, updated, read_at, recs)
    if mv:
        S["sched_moves"] = TR.prune(S.get("sched_moves") or [], read_at) + mv
        log.info("schedule moves %s: %s", month, ", ".join(f"{m['side']} {m['trip']} {m['start']}" for m in mv))


def _add_rec(m):
    """A trip taken: its own trip record once read (credit, block, seat, crew roster)."""
    own = (S.get("own_trips") or {}).get(f"{m['trip']}|{m['start']}") or {}
    rec = {f: own.get(f) for f in ("credit", "blk", "seat") if own.get(f)}
    if own.get("crew"):
        rec["n"] = len(own["crew"])
    return rec


def price_moves(group, legs=None):
    """FW-0064: the Pay-Gross change of trips given and taken on the schedule, the request path's way (pay.py, the
    schedule card's rules): each trip at its own credit x the PWA 3.D.6 rate for the longevity year, plus the PWA 4.O.1
    override for the seat flown (RO $4.00 per block hour; FO $3.00 on a 3-pilot crew) and the Extended Range +15% where
    on. A trip's credit, block, seat and crew come from Ryan's own trip record (a given trip's as kept when it left), else
    the month's pairing package (seat as the request page marks it, else FO). None when any trip cannot be priced."""
    rate, yr, er = pay_settings()
    if not rate:
        return None
    cache, parts, cr = {}, [], 0.0
    for m in sorted(group, key=lambda x: (x["side"] != "drop", x["t"], x["start"])):
        rec = (m.get("rec") or {}) if m["side"] == "drop" else _add_rec(m)
        pk = _package(m["start"][:7], cache).get(m["trip"][:5]) or {}
        credit = PAY.hrs(rec.get("credit")) if rec.get("credit") else PAY.hrs(pk.get("credit"))
        block = PAY.hrs(rec.get("blk")) if rec.get("blk") else PAY.hrs(pk.get("block"))
        lay = "/".join(x for x in str(pk.get("route") or "").split("-") if x and x != "HNL") or m.get("lay") or ""
        leg = next((x for x in legs or [] if TR.leg_matches(x, m)), {})
        seat = rec.get("seat") or leg.get("seat") or "FO"
        key = f"{m['trip']}|{m['start']}"
        g = PAY.trip_gross(credit, block, rec.get("n") or pk.get("crew"), lay, key, seat, rate, er)
        if g is None:
            return None
        parts.append({"trip": m["trip"], "start": m["start"], "side": m["side"], "gross": round(g, 2), "seat": seat,
                      "credit": rec.get("credit") or pk.get("credit") or ""})
        cr += credit if m["side"] == "add" else -credit
    delta = sum(p["gross"] for p in parts if p["side"] == "add") - sum(p["gross"] for p in parts if p["side"] == "drop")
    return {"delta": round(delta, 2), "delta_text": PAY.usd(delta), "parts": parts, "rate": rate, "year": yr,
            "credit_delta": ("+" if cr >= 0 else "-") + PAY.hm(abs(cr))}


def _priced(m):
    return bool(_add_rec(m).get("credit"))


def trade_check():
    """FW-0064: schedule changes that are a decided request. A pending request (Open Time Requests or Tradeboard My
    Requests) whose every leg is now on the schedule is decided at once under its own key (the list path then never
    pushes it again); what no request explains, a same-day group of trips dropped and added, goes out once a later
    read is quiet (trades.py). Each goes out once as event/request_decided, status Approved, with the Pay-Gross change
    (price_moves), and the moves are marked so a restart never pushes them again."""
    mvs = S.get("sched_moves") or []
    if not mvs:
        return
    TR.explain(mvs, S.get("req_decided") or [])
    pushed = S.setdefault("ot_req_pushed", {})
    pending = [{**r, "bcid": b} for b, rs in (S.get("ot_req_rows") or {}).items() for r in rs or []
               if r.get("status") in SUB.OPEN]
    pending += [{**r, "bcid": f"001.{n}"} for n, rs in (S.get("tb_req_rows") or {}).items() for r in rs or []
                if r.get("status") in SUB.OPEN]
    for r, used in TR.match_pending(mvs, [r for r in pending if f"{r.get('key')}|Approved" not in pushed]):
        ev = {"reason": "", **r, "status": "Approved", "source": "schedule", "at": now_iso(),
              "url": f"{BASE}/online/mainmenu.cgi"}
        try:
            ev["pay"] = price_moves(used, r.get("legs"))
        except Exception as e:
            log.info("schedule request pay not priced: %s", e)
            ev["pay"] = None
        for m in used:
            m.update(state="pushed", by=r.get("key") or "")
        pushed[f"{r.get('key')}|Approved"] = now_iso()  # SUB.push_key of the Approved row the list will show
        if r.get("alt"):
            pushed[f"{r['alt']}|Approved"] = now_iso()
        note_decided({**r, "status": "Approved"})
        log.info("request %s %s approved on the schedule (%s)", r.get("type"), r.get("key"),
                 ", ".join(m["id"] for m in used))
        pub("event/request_decided", ev, retain=False)
    done = S.setdefault("sched_trades_pushed", {})
    for day, grp in sorted(TR.groups(mvs).items()):
        if not TR.settled(grp, S.get("sched_read_at"), now_iso(), _priced):
            continue
        ev = TR.group_event(day, grp)
        if ev["key"] in done:
            for m in grp:
                m.update(state="pushed", by=ev["key"])
            continue
        ev.update(bcid="", at=now_iso(), url=f"{BASE}/online/mainmenu.cgi")
        try:
            ev["pay"] = price_moves(grp)
        except Exception as e:
            log.info("schedule trade pay not priced: %s", e)
            ev["pay"] = None
        for m in grp:
            m.update(state="pushed", by=ev["key"])
        done[ev["key"]] = now_iso()
        log.info("trade seen on the schedule (%s): %s, Pay-Gross %s", day, ev["detail"],
                 (ev["pay"] or {}).get("delta_text", "not priced"))
        pub("event/request_decided", ev, retain=False)
    cut = (datetime.fromisoformat(now_iso()) - timedelta(days=30)).isoformat()
    S["sched_trades_pushed"] = {k: v for k, v in done.items() if v >= cut}
    save_state(S)


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
    30 min. Publishes {date: {net, color}} on flight_watcher/grid/state. Read only."""
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
    """MQTT flight_watcher/pilot/set {"emp": "10001", "name": "..."}: show that pilot's current month on the
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
                pub_pilot({"emp": "", "name": q, "status": f"{len(hits)} pilots match '{q}', pick one", "matches": hits,
                                       "month": "", "days": [], "items": [], "totals": {}, "updated": "", "fetched": ""})
                return
            else:
                pub_pilot({"emp": "", "name": q, "status": f"no pilot named '{q}' in the {DB.crew_count()} crew the Watcher has seen; enter the employee number",
                                       "matches": [], "month": "", "days": [], "items": [], "totals": {}, "updated": "", "fetched": ""})
                return
    if not emp:
        return
    S["pilot_req"] = {"emp": emp, "name": d.get("name") or "", "at": now_iso()}
    save_state(S)
    cached = DB.get(f"pilot_sched:{emp}")
    if cached and time.time() - cached.get("fetched_ts", 0) < PILOT_CACHE_S:
        pub_pilot({**cached, "status": "cached"})
        S.pop("pilot_req", None)
        save_state(S)
        log.info("pilot %s: schedule served from cache", emp)
        return
    pub_pilot({"emp": emp, "name": d.get("name") or "", "status": "loading", "month": "", "days": [], "items": [],
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
            pub_pilot({"emp": emp, "name": req.get("name") or "", "status": f"not readable: {classify(html)} {visible_text(html)[:120]}",
                                   "month": "", "days": [], "items": [], "totals": {}, "updated": "", "fetched": now_iso()})
            log.info("pilot %s: schedule page not readable (%s)", emp, classify(html))
            S.pop("pilot_req", None)
            save_state(S)
            return True
        note_sched_trips(sched["items"], "lookup")  # FW-0056 / FW-0057: the crew index reads every trip on it
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
        pub_pilot({**rec, "status": "ok"})
        log.info("pilot %s (%s): %s read, %d items, %d pairing pages", emp, rec["name"], sched["month"], len(sched["items"]), n)
    except Exception as e:
        log.info("pilot %s: schedule read failed: %s", emp, e)
        pub_pilot({"emp": emp, "name": req.get("name") or "", "status": f"error: {e}", "month": "", "days": [],
                               "items": [], "totals": {}, "updated": "", "fetched": now_iso()})
    S.pop("pilot_req", None)
    save_state(S)
    return True


def pub_pilot(payload):
    """0.10.1: every pilot_schedule publish carries the crew index's view of that pilot's month too:
    reconstructed [{pairing, start, end, seat, route, checked_at, lay, blk, credit, soft, crew}],
    reconstructed_coverage_pct, reconstructed_month and (FW-0002) reconstructed_from / reconstructed_to, the
    bid period's first and last day, so the card can draw it in the schedule grid when FLICA hides the schedule
    or errors. Trips and coverage span that grid: the day before the bid period (FLICA's first row) to its end.
    FW-0056 / FW-0057: the trips come from crew_instances (the package's and every schedule's, October's included);
    FW-0059: a trip that overlaps another of the pilot's carries overlap / overlap_with (crewidx.pilot_trips).
    FW-0062: each trip's package details come from its own bid period (pkg_details_for), and pay_line (pilot_pay_line)
    totals the rebuilt month with Pay-Gross for the seat flown on each trip, from the pilot's date of hire on the
    shared seniority list. A readable month (status ok) gets no pay line of its own: Schedule Lookup shows no seat,
    only PILOT_PAIRINGS_MAX of its pairing pages are read, and FLICA's credit total holds reserve and training days
    that cannot be priced trip by trip."""
    try:
        emp = re.sub(r"\D", "", str(payload.get("emp") or ""))
        month = str(payload.get("month") or "")
        if not re.fullmatch(r"\d{4}-\d{2}", month):
            month = local_now().strftime("%Y-%m")
        insts, rows = crew_instances(), DB.crew_rows()
        first, start, end = CI.grid_range(CARD_PAIRINGS, month)
        mine = DB.crew_by_emp(emp) if emp else []
        marks = CI.overlap_marks(DB.get(CREW_OVERLAP_KEY) or {}, rows).get(emp) or {}  # FW-0059
        trips = CI.pilot_trips(insts, mine, month, first, rows, pkg_details_for, end, marks) if emp else []
        payload = {**payload, "reconstructed": trips,
                   "reconstructed_coverage_pct": CI.coverage(insts, rows, None, first, end)[2],
                   "reconstructed_month": month, "reconstructed_from": start, "reconstructed_to": end}
        if trips:
            try:
                name = payload.get("name") or next((r.get("name") for r in mine if r.get("name")), "")
                payload["pay_line"] = pilot_pay_line(trips, emp, name, start, end)
            except Exception as e:
                log.info("pilot lookup: pay line skipped: %s", e)
    except Exception as e:
        log.info("pilot lookup: crew index skipped: %s", e)
        payload = {**payload, "reconstructed": [], "reconstructed_coverage_pct": 0.0}
    pub("pilot_schedule", payload)


# ---------------------------------------------------------------- 0.10.1 crew index (Ryan)
CREW_FROM = CI.CREW_FROM
CREW_PER_RUN = 300
CREW_PER_CHECK = 50
CREW_PER_CHECK_HUNT = 8  # about 20 s, so a hunt check is barely delayed
CREW_SLOT_H = 6  # runs at 00:00, 06:00, 12:00, 18:00 HST
CREW_DIR = "/share/flight_watcher/crew_index"


def crew_slot(now=None):
    """('2026-11-05T12', next slot start) for the 6 h HST slot `now` falls in (HST wall clock, naive)."""
    now = now or local_now()
    st = now.replace(hour=now.hour - now.hour % CREW_SLOT_H, minute=0, second=0, microsecond=0)
    return st.strftime("%Y-%m-%dT%H"), st + timedelta(hours=CREW_SLOT_H)


CREW_SCHED_KEY = "crew_sched_trips"  # FW-0056: {key: {pairing, date, end, route, report, src, seen}} from schedules read
CREW_SCHED_KEEP_D = 62  # a schedule trip that ended this long ago is forgotten
CREW_REREAD_KEY = "crew_reread"  # FW-0058 / FW-0059: {key: {why, at}} trips to read once more, first
CREW_OVERLAP_KEY = "crew_overlaps"  # FW-0059: {id: {emp, name, keys, found_at, state}} pilots on two overlapping trips
CREW_REREAD_PER_CHECK = 10  # re-reads per check while no run is going (a run reads them first, in its own chunks)


def note_sched_trips(items, src):
    """FW-0056 / FW-0057: remember the pairings on a schedule the Watcher read (Ryan's own months, October's from
    Schedule Lookup included; a pilot lookup's month; a picker's month), so the crew index reads them even when no
    pairing package lists them (H38xx trips built later, a trade's H3815B, October's trips with no October file).
    Items are the schedule parsers' {trip, start[, end]}; anything not a pairing id (VAC, SCR...) is skipped. Kept in
    the DB (CREW_SCHED_KEY); a trip that ended more than CREW_SCHED_KEEP_D days ago is dropped. Ryan's instance only
    (the crew index's). Returns the number of new trips."""
    if INSTANCE:
        return 0
    try:
        reg = DB.get(CREW_SCHED_KEY) or {}
        old = json.dumps(reg, sort_keys=True)
        now, n = now_iso(), 0
        for it in items or []:
            trip, start = str(it.get("trip") or "").strip().upper(), str(it.get("start") or "")
            if not PAIRING_RE.match(trip) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", start):
                continue
            end = str(it.get("end") or "")
            end = end if re.fullmatch(r"\d{4}-\d{2}-\d{2}", end) and end >= start else ""
            k = f"{trip}|{start}"
            e = reg.get(k)
            if e is None:
                reg[k] = {"pairing": trip, "date": start, "end": end, "src": src, "seen": now}
                n += 1
            elif end and end > (e.get("end") or ""):
                e["end"] = end  # FW-0065: a trip end cut short by the old item builder grows to the repaired one
        cut = (local_now().date() - timedelta(days=CREW_SCHED_KEEP_D)).isoformat()
        reg = {k: e for k, e in reg.items() if (e.get("end") or e.get("date") or "") >= cut}
        if json.dumps(reg, sort_keys=True) != old:
            DB.put(CREW_SCHED_KEY, reg)
        if n:
            log.info("crew index: %d new trips from a schedule (%s) for the index to read", n, src)
        return n
    except Exception as e:
        log.info("crew index: schedule trips not noted (%s): %s", src, e)
        return 0


def crew_instances():
    """FW-0056 / FW-0057: the crew index's trip instances: every pairing file's, plus the trips on the schedules the
    Watcher read that no file lists on that date (note_sched_trips; Ryan's own months are noted here, so a trade on
    his schedule is read at the next run). A trip that starts before CREW_FROM and runs into it is kept."""
    if INSTANCE:
        return CI.instances(CARD_PAIRINGS)
    try:  # a pilot lookup publishes from the MQTT thread while the main thread may be storing a schedule
        own = _sched_items()
    except RuntimeError:
        own = []
    note_sched_trips(own, "own")
    return CI.instances(CARD_PAIRINGS, extra=DB.get(CREW_SCHED_KEY) or {})


def crew_reread_add(keys, why):
    """FW-0058 / FW-0059: queue trips for one more read, ahead of everything else (CREW_REREAD_KEY)."""
    rr = DB.get(CREW_REREAD_KEY) or {}
    at = local_now().isoformat(timespec="seconds")
    for k in keys:
        rr.setdefault(k, {"why": why, "at": at})
    DB.put(CREW_REREAD_KEY, rr)


def crew_overlaps(insts, rows):
    """FW-0059: look for pilots the index shows on two overlapping trips (a trade between reads). A new overlap is
    flagged and both trips are queued for one paced re-read (read first at the next check, in a run or not); an
    overlap still there once both were read again keeps its flag, with the newer read kept; one gone is cleared.
    Returns the stored flags."""
    try:
        f0, r0 = DB.get(CREW_OVERLAP_KEY) or {}, DB.get(CREW_REREAD_KEY) or {}
        flags, rr, new, kept, cleared = CI.overlap_update(CI.overlaps(insts, rows), f0, r0,
                                                          local_now().isoformat(timespec="seconds"))
        for i in new:
            log.info("crew index: pilot %s on two overlapping trips (%s), both queued for a re-read", flags[i]["emp"],
                     " and ".join(flags[i]["keys"]))
        for i in kept:
            log.info("crew index: pilot %s still on %s after the re-read, newer read kept (flagged)", flags[i]["emp"],
                     " and ".join(flags[i]["keys"]))
        for i in cleared:
            log.info("crew index: overlap %s cleared", i)
        if flags != f0:
            DB.put(CREW_OVERLAP_KEY, flags)
        if rr != r0:
            DB.put(CREW_REREAD_KEY, rr)
        return flags
    except Exception as e:
        log.info("crew index: overlap check skipped: %s", e)
        return DB.get(CREW_OVERLAP_KEY) or {}


def crew_split_repair():
    """FW-0058 one-shot (at start, Ryan's instance): crew lines stored before the seat code fix and cut at a seat code
    inside a name (crewidx.split_suspect) are queued for one re-read, ahead of everything else; a failed re-read keeps
    the stored line. Returns the number queued, or None when already done."""
    if INSTANCE or DB.get("crew_split_v") == 1:
        return None
    try:
        keys = sorted(k for k, r in DB.crew_rows().items() if r.get("status") == "ok" and CI.split_suspect(r.get("crew")))
        if keys:
            crew_reread_add(keys, "name split (FW-0058)")
        DB.put("crew_split_v", 1)
        log.info("crew index: %d crew lines read before the seat code fix queued for a re-read", len(keys))
        return len(keys)
    except Exception as e:  # never stops the start; tried again on the next one
        log.warning("crew index split repair skipped: %s: %s", type(e).__name__, e)
        return None


def crew_fill(k, it, vt):
    """FW-0056: a trip from a schedule (no package row) takes its end, route and report from its pairing page when
    the schedule did not give them (a picker's month lists starts only); the schedule entry keeps them."""
    if it.get("src") != "schedule":
        return it
    got = CI.page_trip(vt)
    upd = {}
    if not it.get("end_known") and got.get("days"):
        upd["end"] = (date.fromisoformat(it["date"]) + timedelta(days=max(int(got["days"]) - 1, 0))).isoformat()
    for f in ("route", "report"):
        if not it.get(f) and got.get(f):
            upd[f] = got[f]
    if not upd:
        return it
    try:
        reg = DB.get(CREW_SCHED_KEY) or {}
        if k in reg:
            reg[k].update(upd)
            DB.put(CREW_SCHED_KEY, reg)
    except Exception as e:
        log.info("crew index: %s details not kept: %s", k, e)
    it = {**it, **{f: v for f, v in upd.items() if f != "end"}}
    if "end" in upd:
        it.update(end_date=upd["end"], end_known=True, days=int(got["days"]))
    return it


def crew_index_check(fl):
    """Read up to CREW_PER_CHECK pairing pages of the current crew index run (GET only, 1.5-3.5 s apart, each URL
    through SUB.safe_get and SM.safe_get). A run starts at the first check after each 6 h slot (once per slot, saved
    in state) or on Update schedules, and reads at most CREW_PER_RUN pages over as many checks as it takes.
    FW-0058 / FW-0059: trips queued for a re-read (CREW_REREAD_KEY: both trips of a pilot on two overlapping trips, a
    crew line cut at a seat code) are read first, one read each; with no run going a check reads just those. A
    re-read that fails keeps the trip's last good read. Returns 'ok', or 'killed' / 'needs_login' / 'stop' when a
    page says so (the run is ended there)."""
    if INSTANCE:
        return "ok"
    slot, _ = crew_slot()
    run = S.get("crew_run")
    if not run:
        why = "button" if FLAGS.pop("crew_scan", False) else ("slot" if S.get("crew_slot") != slot else "")
        if why:
            S["crew_slot"] = slot
            run = S["crew_run"] = {"started": local_now().isoformat(timespec="seconds"), "pages": 0, "why": why,
                                   "slot": slot}
            save_state(S)
            log.info("crew index run started (%s)", why)
        elif not DB.get(CREW_REREAD_KEY):  # nothing to read: the idle check stays cheap
            return "ok"
    else:
        FLAGS.pop("crew_scan", None)  # a run is already going
    insts = crew_instances()
    rows = DB.crew_rows()
    crew_overlaps(insts, rows)  # FW-0059: an overlap not flagged yet (as before this version) queues its two trips
    pending = DB.get(CREW_REREAD_KEY) or {}
    again = {k for k in pending if k in insts}
    if len(again) < len(pending):  # a trip no longer in the index is not waited for
        DB.put(CREW_REREAD_KEY, {k: v for k, v in pending.items() if k in again})
    if not run and not again:
        return "ok"
    if run:
        todo = CI.queue(insts, rows, local_now(), run["started"], again)
    else:  # FW-0059: no run going: only the re-reads, soonest first
        todo = sorted(again, key=lambda k: (CI.departs(insts[k]).isoformat(), k))
    awarded = CI.awarded_periods(insts, rows)  # FW-0016: bid periods with a read that named a pilot
    held0 = CI.held_periods(insts, rows, awarded)  # periods already held (their one probe is in todo)
    held, newly = set(held0), False
    n, res, halted, reread = 0, "ok", False, set()
    per_check = CREW_PER_CHECK_HUNT if FLAGS.get("hunt") else CREW_PER_CHECK  # hunting: short chunks, pot first
    if not run:
        per_check = min(per_check, CREW_REREAD_PER_CHECK)
    for k in todo:
        if (run and run["pages"] >= CREW_PER_RUN) or n >= per_check:
            break
        if FLAGS["pause"] or FLAGS["rearm"]:
            log.info("crew index: pause / re-arm, chunk stopped (run continues later)")
            halted = True
            break
        it = insts[k]
        forced = k in again
        if CI.period_of(it) in held - held0 and not forced:  # FW-0016: held during this chunk, the rest waits for names
            continue
        url = (f"{BASE}/full/mobilepairing.cgi?PID={it['pairing']}&DATE={it['date'].replace('-', '')}"
               "&FROM=MobileOpentimePot&CurrentPage=1")
        if not (SUB.safe_get(url) and SM.safe_get(url)):
            log.info("crew index: %s url refused by safe_get, skipped", k)
            reread.add(k)
            continue
        if n:
            time.sleep(random.uniform(1.5, 3.5))
        n += 1
        if run:
            run["pages"] += 1
        if forced:
            reread.add(k)
        good = forced and (rows.get(k) or {}).get("status") == "ok"  # a re-read never loses the last good read
        at = local_now().isoformat(timespec="seconds")
        try:
            page = fl.fetch(url)
        except Exception as e:
            if good:
                log.info("crew index: re-read of %s failed (%s), last read kept", k, e)
            else:
                DB.crew_put(k, it["pairing"], it["date"], it["end_date"], it["route"], None, at, "fail",
                            f"fetch: {e}"[:200])
            continue
        kind = classify(page)
        if kind != "ok":
            reread.discard(k)
            res = {"killed": "killed", "expired": "needs_login", "blocked": "stop"}.get(kind, "ok")
            log.info("crew index: %s page on %s, run ended", kind, k)
            break
        vt = visible_text(page)
        crew = CI.crew_line(vt)
        if crew is None:
            if good:
                log.info("crew index: re-read of %s found no crew line, last read kept", k)
            else:
                DB.crew_put(k, it["pairing"], it["date"], it["end_date"], it["route"], None, at, "fail",
                            f"no crew line: {vt[:120]}")
            continue
        it = insts[k] = crew_fill(k, it, vt)  # FW-0056: a schedule trip's end and route from its page
        per, named = CI.period_of(it), CI.has_crew(crew)
        if not named and per not in awarded:  # FW-0016: no pilot named and no award seen in this bid period yet:
            DB.crew_put(k, it["pairing"], it["date"], it["end_date"], it["route"], None, at, "empty",  # not read
                        "no crew names on the page")
            rows[k] = {**(rows.get(k) or {}), "status": "empty", "checked_at": at}
            if per not in held and per in CI.held_periods(insts, rows, awarded):
                held.add(per)
                log.info("crew index: %s bid period names no crew yet, held until names appear (one page a run)", per)
            continue
        # after the award a page naming no pilot is an open-time trip ('CA Open FO Open'): a read like any other
        DB.crew_put(k, it["pairing"], it["date"], it["end_date"], it["route"], crew, at, "ok")
        rows[k] = {**(rows.get(k) or {}), "status": "ok", "checked_at": at, "crew": crew}
        if named and per not in awarded:  # FW-0016: the first names in this bid period: the award is out
            awarded.add(per)
            again_n = sum(1 for x, i2 in insts.items() if CI.period_of(i2) == per and (rows.get(x) or {}).get("status") == "empty")
            if per in held or again_n:  # its pages held back or read before the award: read from the next check on
                held.discard(per)
                newly = True
                log.info("crew index: %s bid period names crew now (%s), %d pages read before it go first", per, k, again_n)
        DB.remember_crew(vt)
    if reread:  # FW-0058 / FW-0059: one re-read each, done
        rr = DB.get(CREW_REREAD_KEY) or {}
        DB.put(CREW_REREAD_KEY, {k: v for k, v in rr.items() if k not in reread})
    if n:
        crew_overlaps(insts, DB.crew_rows())  # FW-0059: new overlaps queue their re-reads, re-read ones keep or clear
    done = False
    if run:
        # the run is over when its budget is used, a page ended it, or the queue ran dry before the chunk filled
        # (FW-0016: the pages of a period held in this chunk are not read, so they do not keep the run going; a period
        # whose award was seen in this chunk does: its pages are read from the next check on, not a slot later)
        done = res != "ok" or run["pages"] >= CREW_PER_RUN or (n < per_check and not halted and not newly)
        if done:
            S.pop("crew_run", None)
            S["crew_last"] = {"at": now_iso(), "pages": run["pages"], "why": run["why"], "ended": res}
            log.info("crew index run done: %d pages (%s)", run["pages"], res)
        save_state(S)
    elif n:
        log.info("crew index: %d trips read again (no run going)", n)
    if n or done:
        publish_crew_index(insts, write=done or not run)
    if res == "stop":
        set_machine("stopped_unexpected", "FLICA showed a captcha/MFA/password page (crew index)")
    return res


def publish_crew_index(insts=None, write=False):
    """{T}/crew_index (retained) and, after a run, the month Markdown files."""
    if INSTANCE:
        return
    insts = crew_instances() if insts is None else insts
    rows = DB.crew_rows()
    n, ok, pct = CI.coverage(insts, rows)
    last = S.get("crew_last") or {}
    _, nxt = crew_slot()
    run = S.get("crew_run")
    held = CI.held_periods(insts, rows)
    flags = DB.get(CREW_OVERLAP_KEY) or {}
    pub("crew_index", {"instances": n, "checked": ok, "coverage_pct": pct, "last_run": last.get("at") or "",
                       "next_slot": nxt.replace(tzinfo=HST).isoformat(), "pages_last_run": last.get("pages", 0),
                       "failures": sum(1 for k in insts if (rows.get(k) or {}).get("status") == "fail"),
                       # FW-0016: read with no crew names yet (not counted in checked), and the bid periods held
                       "no_crew_yet": sum(1 for k in insts if (rows.get(k) or {}).get("status") == "empty"),
                       "waiting_for_award": sorted(held),
                       # FW-0056: trips from schedules no package lists; FW-0059: pilots on two overlapping trips
                       "from_schedules": sum(1 for it in insts.values() if it.get("src") == "schedule"),
                       "overlaps": len(flags), "overlaps_rereading": sum(1 for f in flags.values() if f.get("state") != "kept"),
                       "reread_queued": len(DB.get(CREW_REREAD_KEY) or {}),
                       "running": bool(run), "pages_this_run": (run or {}).get("pages", 0)})
    if write:
        write_crew_md(insts, rows, held, flags)


def write_crew_md(insts, rows, held=None, flags=None):
    """/share/flight_watcher/crew_index/<YYYY-MM>.md for every month with instances, rewritten after each run."""
    try:
        os.makedirs(CREW_DIR, exist_ok=True)
        stamp = local_now().strftime("%Y-%m-%d %H:%M")
        for month in sorted({it["month"] for it in insts.values()}):
            path = os.path.join(CREW_DIR, f"{month}.md")
            tmp = path + ".tmp"
            with open(tmp, "w") as f:
                f.write(CI.render_month(month, insts, rows, stamp, held, flags))
            os.replace(tmp, path)
    except Exception as e:
        log.info("crew index files skipped: %s", e)


# ---------------------------------------------------------------- 0.10.1 tickets (Ryan)
TICKETS_DIR = "/share/flight_watcher/tickets"  # shared by every instance
TICKETS_SIG = {"sig": None}
TICKETS_LAST = {}  # FW-0049: the last edit / delete answer, sent as "last" on the listing for the card
RID_RE = TK.CID_RE


def reporter():
    return INSTANCE or "ryan"


def ticket_safe(fn, payload):
    """FW-0003: run a ticket handler so that one bad message can never end the MQTT loop (paho re-raises an
    exception from on_message and the loop thread stops). The error is logged and sent as event/ticket_error."""
    try:
        return fn(payload)
    except Exception as e:
        log.warning("ticket message failed (%s): %s: %s", getattr(fn, "__name__", "?"), type(e).__name__, e)
        try:
            pub("event/ticket_error", {"error": f"ticket message failed: {type(e).__name__}", "at": now_iso()},
                retain=False)
        except Exception:
            pass
        return None


def ticket_new(payload):
    """{T}/ticket/new {kind, title, narrative, steps?, expected?, page?, version?, image?, cid?, images?}.
    FW-0003: the card sends photos after this, one per {T}/ticket/image message (ticket_image)."""
    try:
        d = json.loads(payload or "{}")
    except ValueError:
        d = None
    t, err = TK.create(TICKETS_DIR, d, reporter(), now_iso())
    if not t:
        log.info("ticket refused: %s", err)
        pub("event/ticket_error", {"error": err, "at": now_iso()}, retain=False)
        return None
    log.info("ticket %s (%s) from %s: %s (%d photos to come)", t["id"], t["kind"], t["reporter"], t["title"],
             t["images_expected"] - len(t["images"]))
    pub("event/ticket_new", {"id": t["id"], "kind": t["kind"], "title": t["title"], "reporter": t["reporter"]}, retain=False)
    publish_tickets(force=True)
    return t


def ticket_image(payload):
    """FW-0003 {T}/ticket/image {cid, i, image}: photo i (1 to 10) of the ticket this instance filed with that
    cid, one photo per message. An unknown cid or a bad photo is refused and nothing is written."""
    try:
        d = json.loads(payload or "{}")
    except ValueError:
        d = None
    t, err = TK.add_image(TICKETS_DIR, d, reporter(), now_iso())
    if not t:
        log.info("ticket photo refused: %s", err)
        pub("event/ticket_error", {"error": err, "at": now_iso()}, retain=False)
        return None
    log.info("ticket %s: photo %s (%d of %d)", t["id"], d.get("i"), len(t["images"]), t["images_expected"])
    publish_tickets(force=True)
    return t


def ticket_act(payload):
    """{T}/ticket/act {id, action: triage|progress|fixed|verify|reopen|close|note, text?, version?}. A pilot
    instance may act on its own tickets only.
    FW-0007: a fixed action that moves a ticket to fixed also sends {T}/event/ticket_fixed {id, kind, title,
    reporter, version} (not retained), once per move, after the new listing. "reporter" (ryan, or the second
    pilot's name) says whose phone the HA automation pushes it to, quietly, so they can check it is what they
    expected and verify or reopen it on the tickets card."""
    try:
        d = json.loads(payload or "{}")
    except ValueError:
        d = None
    t, err = TK.act(TICKETS_DIR, d, reporter(), now_iso(), allowed_reporter=INSTANCE or None)
    if not t:
        log.info("ticket action refused: %s", err)
        pub("event/ticket_error", {"error": err, "at": now_iso()}, retain=False)
        return None
    log.info("ticket %s: %s -> %s", t["id"], d.get("action"), t["status"])
    publish_tickets(force=True)
    ev = TK.fixed_event(t)
    if ev:
        log.info("ticket %s fixed (v%s): telling %s", ev["id"], ev["version"] or "?", ev["reporter"])
        pub("event/ticket_fixed", ev, retain=False)
    return t


def _ticket_change(fn, verb, payload):
    """FW-0049: run TK.edit or TK.delete for this instance (a pilot instance: its own tickets only) and say how it
    went in "last" {rid, id, action, ok, error, at} on the next listing, so the card that sent the card-made rid can
    show it. A refusal also goes out as event/ticket_error, like every other ticket message."""
    try:
        d = json.loads(payload or "{}")
    except ValueError:
        d = None
    t, err = fn(TICKETS_DIR, d, reporter(), now_iso(), allowed_reporter=INSTANCE or None)
    d = d if isinstance(d, dict) else {}
    rid = str(d.get("rid") or "").strip()
    TICKETS_LAST.clear()
    TICKETS_LAST.update({"rid": rid if RID_RE.match(rid) else "", "id": str(d.get("id") or "")[:20], "action": verb,
                         "ok": bool(t), "error": err, "at": now_iso()})
    if not t:
        log.info("ticket %s refused: %s", verb, err)
        pub("event/ticket_error", {"error": err, "at": now_iso()}, retain=False)
    publish_tickets(force=True)
    return t


def ticket_edit(payload):
    """FW-0049 {T}/ticket/edit {id, rid?, title?, narrative?, steps?, expected?, page?}: only while the ticket is new
    or reopened; only the fields sent change."""
    t = _ticket_change(TK.edit, "edit", payload)
    if t:
        log.info("ticket %s edited by %s: %s", t["id"], reporter(), ", ".join(t["history"][-1]["fields"]))
    return t


def ticket_delete(payload):
    """FW-0049 {T}/ticket/delete {id, rid?}: any status; the folder moves to tickets/.deleted/ and leaves the list."""
    t = _ticket_change(TK.delete, "delete", payload)
    if t:
        log.info("ticket %s (%s) deleted by %s", t["id"], t.get("status"), reporter())
    return t


TICKET_ROW_KEYS = ("id", "kind", "title", "status", "reporter", "created_at", "version_fixed", "image_count", "editable")
TICKET_ATTR_ROWS = 30  # FW-0060: open tickets on the sensor, newest first; the card reads every ticket from the file


def tickets_payload(listing, key, rev, last):
    """FW-0060: the tickets sensor. The full listing (every ticket, narratives, steps) is in tickets_<key>.json, which
    the tickets card reads; the sensor keeps the counts, this instance's last edit / delete answer and a short row
    (no text) for the newest TICKET_ATTR_ROWS tickets still open (TK.OPEN: new, triaged, in progress, fixed,
    reopened), so the card can list them before the file comes in. It ran about 39 KB with every ticket's text, over
    the recorder's 16 KB."""
    rows = [{k: t.get(k) for k in TICKET_ROW_KEYS} for t in listing.get("tickets") or []
            if t.get("status") in TK.OPEN][:TICKET_ATTR_ROWS]
    for r in rows:
        r["title"] = str(r.get("title") or "")[:80]
        r["created_at"] = str(r.get("created_at") or "")[:10]
    return {"open": listing.get("open", 0), "total": listing.get("total", 0), "tickets": rows, "rows": "open",
            "file_key": key, "rev": rev, "last": dict(last or {})}


def publish_tickets(force=False):
    """{T}/tickets (retained): Ryan's instance lists every ticket, a pilot instance only its own. Re-published
    when the folder changed (the other instance may have written to it) or when forced. FW-0049: "last" is this
    instance's last edit / delete answer ({} until one). FW-0060: the listing goes to tickets_<key>.json first, then
    the sensor (tickets_payload) announces it with rev."""
    try:
        sig = TK.signature(TICKETS_DIR)
        if not force and sig == TICKETS_SIG["sig"]:
            return
        TICKETS_SIG["sig"] = sig
        listing = TK.listing(TICKETS_DIR, INSTANCE or None)
        key, rev = write_list_file("tickets", listing)
        pub("tickets", tickets_payload(listing, key, rev, TICKETS_LAST))
    except Exception as e:
        log.info("tickets publish skipped: %s", e)


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
    days, A330 rows that are 99xx or touch a non-regular station become sensor.flight_watcher_charters
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
    pub("swap_tests", {"count": len(tests), "tests": tests[-20:], "mode": SUB.DEFAULT_MODE})


def swap_test(idea):
    """0.5.0 Test mode: compose the exact mobileotswap.cgi POST a swap would need for this idea, log it,
    keep the last 20 (sensor.flight_watcher_swap_test_requests) and push event/swap_test. FW-0028: a draft
    only, never sent (submit.WRITES_IMPLEMENTED is False and FLICA stays read-only)."""
    b = sorted({bcid(u) for u in S.get("pot_urls", {}).values() if bcid(u)}, key=bcid_key)
    rep_h = None
    if idea.get("report") and idea.get("start"):
        rep_h = SUB.hours_until(f"{idea['start']}T{idea['report'][:5]}", local_now())
    seat = "R" if (S.get("own_trips", {}).get(idea["for"]) or {}).get("seat") == "RO" else "F"
    rec = SUB.compose(idea, b[0] if b else None, rep_h, seat=seat, close_in_bcid=S.get("close_in_bcid"))
    rec.update({"key": idea["key"], "at": now_iso(), "mode": SUB.DEFAULT_MODE,
                "hours_to_report": round(rep_h, 1) if rep_h is not None else None, "sent": False})
    tests = S.setdefault("swap_tests", [])
    tests.append(rec)
    del tests[:-20]
    log.info("SWAP DRAFT (%s): give %s take %s folder %s bcid %s form %s", SUB.DRAFT, rec["give"], rec["take"],
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
    rows = [dict(r, src=r.get("src") or "O") for r in pot_rows] + [dict(r, src="T") for r in S.get("tb_details", {}).values()]
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
                ev["would_submit"] = f"DRAFT ({SUB.DRAFT}): drop {i['for_trip']} {i['for'].split('|')[1]}, add {i['pairing']} {i['start']}"
                log.info("auto swap %s", ev["would_submit"])
            else:
                ev["would_submit"] = f"DRAFT ({SUB.DRAFT}): daily cap of {AUTO_SWAP_PER_DAY} reached, not even a draft counted"
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
                # 0.4.3: HA pushes this (automation "Flight Watcher hidden trip")
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
    changed = IF.run(fl, DB, limit, log, local_now, BASE, HST,
                     on_sched=lambda items: note_sched_trips(items, "picker"))  # FW-0056: the crew index reads them too
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
        if not (S.get("close_in") or {}).get("verified"):
            close_in_scan(html, f"open time page {month}")  # FW-0034: a link to the close-in folder, if it has one
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
    try:  # FW-0034: the close-in folder (trips under 16 h to report), read only
        pot_all[CLOSE_IN_KEY] = close_in_check(fl, pot_all, full)
    except Exception as e:
        log.info("close-in check error: %s", e)
    # drop months no longer published, and cached details of pairings no longer in any pot
    S["baseline"] = {m: v for m, v in S["baseline"].items() if m in S["pot_urls"]}
    live = {k for p in pot_all.values() for k in p}
    S["details"] = {k: v for k, v in S.get("details", {}).items() if k in live}
    S["relogin_streak"] = 0
    save_state(S)
    flat = [dict(v, month=m) for m, p in pot_all.items() for v in p.values()]
    flat.sort(key=lambda r: r.get("src") != "C")  # FW-0034: close-in trips (under 16 h to report) first
    pub("pot/state", {"count": len(flat), "pairings": flat[:60]})
    email_check(fl, pot_all)
    pickup_check(fl, full)
    publish_finds()  # rows carry live CA / details now, so publish every check
    tradeboard_check(fl, full)
    requests_check(fl)  # 1.2.0: swap / add / drop request decisions -> push
    grid_check(fl, full)
    swap_scan(flat)
    drop_scan()
    if FLAGS.pop("swap_map", False):
        swap_map_probe(fl)
    publish_tickets()  # 0.10.1: cheap folder re-scan, the other instance may have written
    cr = crew_index_check(fl)  # 0.10.1: at most CREW_PER_CHECK pages per check, so pot checks keep their cadence
    if cr != "ok":
        return cr
    pub("last_check", now_iso())
    S["last_check_ts"] = time.time()
    if S.get("note") in ("starting",) or (S.get("note") or "").startswith("logged in"):
        set_machine(S.get("machine", "idle"), "")
    pub("session", "ON")
    return "ok"


def main():
    global MQ
    migrate_swap_mode()  # FW-0028: before on_connect publishes the mode
    MQ = mqtt_start()
    time.sleep(2)
    if not OPTS.get("username") or not OPTS.get("password"):
        if INSTANCE:  # 0.10.0: a second pilot gets credentials over MQTT; wait for them (settings/set restarts us)
            set_machine("needs_settings", f"send username and password to {T}/settings/set")
            no_next_check()
            pub("session", "OFF")
            log.info("no credentials for instance %s: waiting on %s/settings/set", INSTANCE, T)
            while True:
                time.sleep(3600)
        set_machine("stopped_unexpected", "enter your FLICA username and password: dashboard Settings tab")
    elif S.get("machine", "").startswith("stopped"):
        set_machine(S["machine"], S.get("note", "") + " (still stopped after restart, press Re-arm)")
    elif still_waiting():
        # 1.0.1 review: a restart (a Settings save, an app restart) keeps a yield to Ryan's own FLICA login
        # and a re-login back-off running instead of loading FLICA at once
        set_machine(S["machine"], S.get("note", ""))
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
    if DB.get("crew_fix_v") != 1:  # FW-0016 / FW-0017 one-shot: CKP out of stored names, pre-award reads not counted
        try:  # by bid period (Dec 1 is November's), and only trips not yet started
            periods = {k: CI.period_of(it) for k, it in CI.instances(CARD_PAIRINGS).items()}
            names, empties = DB.crew_fix(CI.has_crew, periods, local_now().date().isoformat())
            DB.put("crew_fix_v", 1)
            log.info("crew index repaired: %d CKP tags taken out of names, %d reads with no crew names set to read "
                     "again", names, empties)
        except Exception as e:  # never stops the start; tried again on the next one
            log.warning("crew index repair skipped: %s: %s", type(e).__name__, e)
    crew_split_repair()
    if DB.get("score_v") != 2:  # 0.7.6 one-shot: Pickup Speed recomputed with the vetted dwell() for every scored pickup
        DB.rescore_all()
        DB.put("score_v", 2)
        log.info("pickup speeds rescored (0.7.6 dwell: alert time in, middle of the gone window out)")
    RULES["list"] = load_rules()
    publish_rules(MQ)
    finds_files_cleanup()  # FW-0010: before publish_finds() rebuilds the month files under the key
    publish_finds()
    publish_blocked()
    publish_tradeboard()
    publish_own_trips()
    publish_trade()
    publish_charters()
    publish_improved()
    publish_tickets(force=True)
    publish_crew_index()
    versions_check(force_pub=True)
    uploads_check()
    recall_eval()
    threading.Thread(target=charter_thread, daemon=True, name="charter").start()
    threading.Thread(target=ccr_thread, daemon=True, name="ccr").start()  # 1.4.6: Hark's answers to CCR requests
    if os.environ.get("FLIGHT_WATCHER_WEB", "1") == "1":  # 0.10.0: only the default instance serves the ingress page
        web.serve(int(os.environ.get("INGRESS_PORT", "8099")), VERSION, lambda: RULES["list"],
                  save_rules_from_page, DB, log, get_settings=lambda: settings_state(load_creds()),
                  save_settings=lambda d: settings_cmd(json.dumps(d)), clear_settings=settings_clear)
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
                S["req_force"] = True  # 1.2.0: he was in FLICA, maybe filing a request: read the list first thing back
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
