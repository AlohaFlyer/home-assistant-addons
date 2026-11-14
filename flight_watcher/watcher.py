"""Flight Watcher: one kept-alive FLICA session, open time pot diff, HA over MQTT.

Login rule: never two login attempts in a row without a success in between.
A failed login, or anything unexpected, parks the watcher until re-armed from HA.
FLICA is read only: rules match and log, nothing is ever submitted to FLICA.
"""
import collections
import contextlib
import hashlib
import hmac
import json
import logging
import math
import os
import random
import re
import secrets
import shutil
import stat
import tempfile
import threading
import time
from datetime import date, datetime, timedelta, timezone

import paho.mqtt.client as mqtt
import requests
from playwright.sync_api import sync_playwright

import rules as R
import web
import far as FAR
from pot import PAIRING_RE, LEG_FULL_RE, schedule_items, parse_schedule_desktop, parse_legs, parse_cm_schedule, inflight_at, crew_ids, with_ids, parse_alert_email, fit_tag, hours, parse_crew, pickup_diff, pickup_result, layout_still_parses, parse_schedule, row_date, BLOCK_HINTS, detail_url, parse_detail, soft_time, bcid, bcid_after, bcid_key, classify, CLOSE_IN_RE, close_in_folders, pick_close_in, trade_pages, header_fingerprint, is_pot_page, parse_pot, pot_links, visible_text
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
import chunks as UP
import contacts as CT
import working as WK
import pilotver as PV
import smart as SMART
import roles as ROLES
import portal as PT
import ntfy as NT
import gate as GT
import captures as CAPS
import photos as PH
import bidcal as BC
import layover as LO
import pilotpdf as PP

VERSION = "1.7.3"
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
# 1.5.0 (FW-0063): the pilot's portal is on. 1.6.0 (FW-0061): run.py sets it, with the pilot's portal folder, the
# signing key's path and the ntfy Click origin, only for a pilot entry with portal: true (portal_on())
PORTAL = os.environ.get("FLIGHT_WATCHER_PORTAL", "") == "1"
PORTAL_DIR = os.environ.get("FLIGHT_WATCHER_PORTAL_DIR", "")
PORTAL_KEY_FILE = os.environ.get("FLIGHT_WATCHER_PORTAL_KEY", "")
PORTAL_ORIGIN = PT.origin_ok(os.environ.get("FLIGHT_WATCHER_PORTAL_ORIGIN", ""))
PORTAL_PUB = os.environ.get("FLIGHT_WATCHER_PORTAL_PUB", "")  # the admin's Web UI shows it (never a pilot's)
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
SECRET_KEYS = ("password", "ctweb_password")  # 1.6.1: kept exactly as typed (a space may be part of a password)
# 1.6.0 (FW-0061): a portal pilot's ntfy topic and token, kept in creds.json beside the logins; accepted only from a
# sealed settings message and only on a pilot whose portal is on (never on the admin), never shown or logged
NTFY_KEYS = NT.KEYS
PREFS_FILE = f"{DATA}/prefs.json"  # 1.6.0: a portal pilot's pay and tax prefs (pref/set); the admin never reads it


def portal_on():
    """1.6.0 (FW-0061): this instance is a pilot whose portal is on (run.py: option pilots[].portal). Never the admin.
    Reads its globals when called."""
    return PORTAL and ROLES.role(INSTANCE) == ROLES.PILOT and bool(PORTAL_DIR)


def has(feature):
    """1.5.0 (FW-0063): this instance has the feature (roles.FEATURES): the default instance is the admin, every other
    one a pilot. Reads INSTANCE when called."""
    return ROLES.allowed(feature, INSTANCE)


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
    if not has("addon_config"):
        for k in CRED_KEYS:
            o.pop(k, None)
        o.pop("second_pilot", None)
    for k, v in load_creds().items():
        if k in CRED_KEYS and isinstance(v, str) and v.strip():
            o[k] = v if k in SECRET_KEYS else v.strip()  # 1.6.1: a password exactly as saved
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
# FW-0042: the smart push config (home airports, nonstop tables, month types, VAC, rate) lives only on the pilot's
# share, never in git; without it the comm / value / month_rule fields stay blank (smart.py)
SMART_FILE = f"{SHARE}/smart.json"


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
FREQ_LIMITS = ROLES.freq_limits(INSTANCE)  # 1.6.2 (Ryan 2026-11-10): every instance normal_min 1 to 90, hunt_s 5 to 90
# (roles.py; the portal spool checks the contract's ROLES.FREQ_LIMITS, normal 1 to 90 since revision 2 (1.7.0; 1 to 20
# before), the handler then clamps into these; the number entities advertise ROLES.entity_freq_limits, within the
# contract on a portal pilot)
JITTER = 0.3
CHECK_NOW_MIN_GAP_S = 10  # every instance's (check_now_gap; a pilot's was his 120 s floor before 2026-11-10)
RULES = {"list": [], "published": set()}
RULE_LOCK = threading.Lock()


# ---------------------------------------------------------------- rules file
def is_seeded_example(rule):
    """1.7.1 (F#15): True when a stored rule is the example load_rules seeded (rules.EXAMPLE as validate fills it in),
    never edited: every field the same but created_at (stamped when it was written)."""
    seed = R.validate(R.EXAMPLE)[0][0]
    return isinstance(rule, dict) and {k: v for k, v in rule.items() if k != "created_at"} == \
        {k: v for k, v in seed.items() if k != "created_at"}


def load_rules():
    pilot = ROLES.role(INSTANCE) == ROLES.PILOT
    if not os.path.exists(RULES_FILE):
        # 1.7.1 (F#15): a pilot gets no example rule: his portal has no rules view, so he could neither see nor turn
        # off a SIN alert he never asked for (an alert rule raises a Rule match alert even in dry run)
        clean = [] if pilot else R.validate(R.EXAMPLE)[0]
        write_rules(clean)
        log.info("rules.json created empty (a pilot gets no example rule)" if pilot else
                 "rules.json created with the example SIN alert rule (alert only, dry run)")
        return clean
    try:
        clean, errs = R.validate(json.load(open(RULES_FILE)))
    except Exception as e:
        clean, errs = [], [f"rules.json unreadable: {e}"]
    if errs:
        log.warning("rules.json has errors, running with NO rules until fixed: %s", errs)
    elif pilot and not DB.get("example_rule_checked"):
        # 1.7.1 (F#15), once per pilot: the example a 1.7.0 or older start seeded for him goes, only while it is
        # exactly the seed (an edited rule is his and stays); its live switch is taken down by the next publish_rules
        drop = [r["id"] for r in clean if is_seeded_example(r)]
        if drop:
            clean = [r for r in clean if r["id"] not in drop]
            write_rules(clean)
            RULES["published"] |= set(drop)
            log.info("rules.json: the example rule %s seeded before 1.7.1 removed (a pilot gets no example rule)",
                     ", ".join(drop))
        DB.put("example_rule_checked", 1)
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


def refused_sub(topic):
    """1.5.0 (FW-0063): True (one log line, nothing changed) when <prefix>/<sub> belongs to a feature this instance
    lacks (roles.SUBS). A pilot instance does not subscribe to those; this guards a stray message all the same."""
    if not topic.startswith(f"{T}/"):
        return False
    sub = topic[len(T) + 1:]
    if ROLES.sub_allowed(sub, INSTANCE, portal_on()):
        return False
    why = ("the portal is off on this instance" if ROLES.sub_key(sub) in ROLES.PORTAL_SUBS
           else "not for a pilot instance")
    log.info("MQTT %s refused: %s (%s)", sub, why, ROLES.SUBS.get(ROLES.sub_key(sub)))
    return True


def on_message(c, u, msg):
    if msg.topic == CHARTERS_SHARED and is_pilot():  # 1.7.1 (F#22): a pilot reads the admin's list
        charters_shared_in(msg.payload)
        return
    if pilot_status_in(msg.topic, msg.payload):  # 1.7.1 review: the admin notes a pilot Watcher online or not
        return
    if refused_sub(msg.topic):
        return
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
    if msg.topic == f"{T}/pref/set":  # 1.6.0 (FW-0061): a portal pilot only (roles.PORTAL_SUBS)
        pref_cmd(msg.payload.decode(errors="replace"))
        return
    if msg.topic == f"{T}/upload/chunk":
        upload_chunk(msg.payload)
        return
    if msg.topic == f"{T}/upload/pdf":  # 1.7.2 (FW-0066): a portal pilot only (roles.PORTAL_SUBS)
        pilot_upload_chunk(msg.payload)
        return
    if msg.topic == f"{T}/upload/decide":  # 1.7.2 (FW-0066): the admin only (roles: upload_review)
        upload_decide_cmd(msg.payload.decode(errors="replace"))
        return
    if msg.topic == f"{T}/layover/note":  # 1.7.1 (FW-0072): the admin only (roles: one_writer)
        layover_note_cmd(msg.payload.decode(errors="replace"))
        return
    if msg.topic in (f"{T}/van/alerts/set", f"{T}/van/first_min/set", f"{T}/van/second_min/set"):  # 1.7.2: admin
        van_setting_cmd(c, msg.topic[len(T) + 1:], msg.payload.decode(errors="replace"))
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
    # 1.6.2 (Release A): which commands wake the loop into a FLICA check at once. On every instance: Check now (its
    # CHECK_NOW_MIN_GAP_S), a hunt or pause switch that changes, and Re-arm while stopped (else it would wait up to an
    # hour). On a pilot nothing else does (every portal command used to). The admin keeps his other wakes (pilot
    # lookup, frequency, swap map, crew index), except Scan CrewTrac now, which is no FLICA read at all.
    # 1.6.2 review: on a pilot a hunt change, an un-pause and Check now wake a check at most once every
    # PILOT_CHECK_FLOOR_S (his fastest hunt, 5 s since Ryan's 2026-11-10 ranges); inside it the check starts at the
    # floor (wake_check). His FLICA budget (100 loads an hour) is what holds a fast pace. Pause on loads nothing: it
    # always wakes the loop, so a check waiting in the gate is given up at once.
    admin = ROLES.role(INSTANCE) == ROLES.ADMIN
    wake = False
    if msg.topic == f"{T}/hunt/set":
        changed = FLAGS["hunt"] != (p == "ON")
        set_switch(c, "hunt", p == "ON")
        log.info("hunt mode %s", FLAGS["hunt"])
        held_apply()  # 1.6.2: the held-hunt note follows the switch at once
        wake = changed and wake_check("hunt mode changed")
    elif msg.topic == f"{T}/pause/set":
        changed = FLAGS["pause"] != (p == "ON")
        set_switch(c, "pause", p == "ON")
        log.info("pause %s", FLAGS["pause"])
        if changed and FLAGS["pause"]:
            wake = True  # nothing is loaded: the loop parks (and a load waiting in the gate gives up)
        elif changed:
            # paused, the loop sleeps an hour: it must see the un-pause (its check then waits for the floor itself)
            wake = S.get("machine") == "paused" or wake_check("pause off")
    elif msg.topic == f"{T}/rearm/press":
        act, _, why = rearm_answer()  # 1.7.1 (F#92, F#149): what it does depends on the state
        if act == "login":
            FLAGS["rearm"] = True
            wake = (S.get("machine") or "").startswith("stopped")
        elif act == "check":  # idle or hunting with no check for too long: the full check the card's 'Stuck' asks for
            FLAGS["full"] = True
            wake = wake_check("re-arm")
        log.info("re-arm pressed" + (f": {why}" if why else ""))
    elif msg.topic in (f"{T}/hunt/state", f"{T}/pause/state"):
        if p in ("ON", "OFF"):  # the retained state restores the switch after a restart (an empty payload is no state)
            remember_switch("hunt" if "hunt" in msg.topic else "pause", p == "ON")
        return
    elif msg.topic == f"{T}/swap_map/press":
        FLAGS["swap_map"] = True  # 0.4.10: one read-only mapping pass on the next check
        wake = admin
        log.info("swap map pressed: read-only mapping on the next check")
    elif msg.topic == f"{T}/pilot/set":
        pilot_cmd(msg.payload.decode(errors="replace"))
        wake = admin  # 1.6.2: a pilot's lookup runs on his next check
    elif msg.topic == f"{T}/crew_scan/press":
        if has("crew_index"):
            FLAGS["crew_scan"] = True  # 0.10.1: one crew index run, read in chunks over the next checks
            wake = admin
            log.info("crew index run requested")
    elif msg.topic == f"{T}/charter_scan/press":
        try:
            charter_press()  # 0.7.0: scan CrewTrac now; 1.6.1: only when one may run, else the status is republished
        except Exception as e:  # noqa: BLE001 (never let it reach paho's thread)
            log.info("charter scan press: %s", e)
    elif msg.topic == f"{T}/check_now/press":
        # Waking the loop runs a check right away (only when idle or hunting; paused/stopped ignore it).
        why = check_now_refusal(admin)  # 1.7.1 (F#12): the same reason a portal press is answered with
        if why:
            log.info("check now %s", why)
            return
        log.info("check now pressed: full refresh")
        FLAGS["full"] = True  # 0.3.9: re-read schedule, own trips, pot details, pickups, tradeboard
        wake = wake_check("check now")
    elif msg.topic in (f"{T}/freq/normal_min/set", f"{T}/freq/hunt_s/set"):
        key = msg.topic.split("/")[2]
        lo, hi = FREQ_LIMITS[key]
        try:
            v = int(round(float(p)))
        except (ValueError, OverflowError):  # 'inf' or '1e999' is OverflowError: it must not end paho's thread
            return
        S.setdefault("freq", {})[key] = max(lo, min(hi, v))
        save_state(S)
        c.publish(f"{T}/freq/{key}/state", str(S["freq"][key]), retain=True)
        log.info("frequency %s = %s", key, S["freq"][key])
        held_apply()  # 1.6.2: a pilot's held-hunt note follows his new frequency at once
        wake = admin  # 1.6.2: a pilot's new frequency applies from his next check
    elif msg.topic.startswith(f"{T}/rule/") and msg.topic.endswith("/live/set"):
        rule_live_cmd(c, msg.topic.split("/")[2], p == "ON")
        return
    if wake:
        WAKE.set()


def on_message_safe(c, u, msg):
    """paho's on_message (1.6.0): on_message, with any error a handler lets out logged once per message (its type and
    the topic's sub only, never the payload) instead of re-raised. paho 2.1 re-raises a callback's error and its
    network thread then ends: no MQTT command (settings/set, hunt, pause, a portal's command) would be read again
    until a restart."""
    try:
        on_message(c, u, msg)
    except Exception as e:  # noqa: BLE001
        topic = str(getattr(msg, "topic", ""))
        log.info("MQTT %s skipped: %s", topic[len(T) + 1:] if topic.startswith(T + "/") else "message",
                 type(e).__name__)


def check_now_gap():
    """Check now is ignored this soon after the last check: 10 s on every instance (1.6.2, Ryan 2026-11-10: a pilot's
    gap was his 120 s check floor before; his FLICA budget still holds the pace)."""
    return CHECK_NOW_MIN_GAP_S


def stuck_after_s():
    """1.7.1 (F#149): idle or hunting with no check for this long reads as 'Stuck' on the clock card (its limit): 10 min
    hunting, else 2.5 times the normal interval and at least 30 min."""
    return 600 if FLAGS.get("hunt") else max(1800, freq()["normal_min"] * 150)


def budget_hold():
    """(seconds, 'budget' or 'host') the FLICA budget or the host's cap holds the next check: the main loop's wait
    before a check (GATE_CHECK_TOKENS loads must fit). (0, '') when a check may start now."""
    return GATE.free_in(min(check_tokens(), GATE.budget or GATE_CHECK_TOKENS))


def _hold_words(wait, why):
    return (f"the FLICA {'budget' if why == 'budget' else 'host limit'} holds the next check until "
            f"{hst_hm(time.time() + wait)} HST")


def check_now_refusal(admin):
    """1.7.1 (F#12, F#149): why a Check now press does nothing now, in plain words ('' when it wakes a check). It answers
    a portal press (portal_spool_once: ok false, the press is not republished) and goes to the log for one from Home
    Assistant. Paused, stopped, waiting for settings, stepped aside, in a re-login back-off, under check_now_gap() since
    the last check, or held by the FLICA budget: each of those would leave the press unread until its wait ended."""
    st = S.get("machine") or "idle"
    if FLAGS.get("pause") or st == "paused":
        return "ignored: the Watcher is paused (turn Pause off first)"
    if st.startswith("stopped"):
        return "ignored: the Watcher is stopped (see why on the Watcher tab, then Re-arm)"
    if st == "needs_settings":
        return "ignored: the Watcher waits for your FLICA login on the Settings tab"
    if st == "yielded":
        return (f"ignored: the Watcher stepped aside for your own FLICA login until "
                f"{hst_hm(S.get('yield_until'))} HST")
    if st == "backoff":
        return f"ignored: the Watcher logs in again at {hst_hm(S.get('relogin_at'))} HST"
    gap_s = check_now_gap()  # 10 s on every instance; on a pilot a press or a check start inside it counts too
    if time.time() - max(S.get("last_check_ts", 0), S.get("wake_ts", 0) if not admin else 0,
                         S.get("check_started_ts", 0) if not admin else 0) < gap_s:
        return f"ignored: last check under {gap_s} s ago"
    wait, why = budget_hold()
    if wait > 0:
        return "ignored: " + _hold_words(wait, why)
    return ""


def rearm_answer():
    """1.7.1 (F#92, F#149): what a Re-arm press does now: (action, ok, why). action 'login': stopped, yielded or in a
    back-off, the login Re-arm has always made (only a stop wakes the loop for it, as before, so a step-aside for the
    pilot's own FLICA login is never cut short: the login waits for its end); ok is false while FLICA refused these
    details (the loop says so in the note and logs in no more). action 'check': idle or hunting with no check for
    stuck_after_s() and none running, what the clock card's 'Stuck. Press Re-arm.' asks for: a full check now.
    action '': nothing to re-arm (ok false, why says what the Watcher is doing)."""
    st = S.get("machine") or "idle"
    if st.startswith("stopped") or st in ("yielded", "backoff"):
        if flica_refused_at() is not None:
            if S.get(FL_KEY_LOST):  # 1.7.4: the refusal on record can no longer be checked: only a save lifts it
                return "login", False, ("nothing to re-arm: FLICA's refusal on record can no longer be checked; save "
                                        "your FLICA details on Settings again")
            return "login", False, "nothing to re-arm: FLICA refused these login details; save new ones on Settings"
        if st == "yielded":
            return "login", True, (f"logs in when the step-aside for your own FLICA login ends, "
                                   f"{hst_hm(S.get('yield_until'))} HST")
        if st == "backoff":
            return "login", True, f"logs in at the next login try, {hst_hm(S.get('relogin_at'))} HST at the latest"
        return "login", True, ""
    if st == "needs_settings":
        return "", False, "nothing to re-arm: enter your FLICA login on the Settings tab"
    if FLAGS.get("pause") or st == "paused":
        return "", False, "nothing to re-arm while paused: turn Pause off"
    last = float(S.get("last_check_ts") or 0)
    if time.time() - last < stuck_after_s():
        return "", False, f"nothing to re-arm: the Watcher is checking (last check {hst_hm(last)} HST)"
    if RUN["check"]:
        return "", False, (f"nothing to re-arm: a check is running (since "
                           f"{hst_hm(S.get('check_started_ts'))} HST)")
    wait, why = budget_hold()
    if wait > 0:
        return "", False, "nothing to re-arm: " + _hold_words(wait, why)
    return "check", True, "a full check starts now"


def press_answer(sub):
    """1.7.1 (F#12, F#92, F#149): (ok, why) for a portal command before it is republished. A Check now, a Re-arm or
    (1.7.1 review) a Scan CrewTrac now the Watcher would ignore answers ok false with the reason and is not republished;
    a Re-arm that acts says what it does. Any other command: (True, '')."""
    if sub == "check_now/press":
        why = check_now_refusal(ROLES.role(INSTANCE) == ROLES.ADMIN)
        return not why, why
    if sub == "rearm/press":
        _, ok, why = rearm_answer()
        return ok, why
    if sub == "charter_scan/press":
        if is_pilot():  # 1.7.1 (F#22): the admin's scan is his; a pilot's Watcher never logs in to CrewTrac
            return False, f"ignored: {CHARTERS_NO_SCAN}"
        why = charter_press_refusal()  # 1.7.1 review: a press that starts no scan says why, like Check now
        return not why, ("ignored: " + why) if why else ""
    return True, ""


CHARTERS_NO_SCAN = "charters come from the admin's CrewTrac scan; this Watcher does not log in to CrewTrac"


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
          "has_ctweb_password": bool(o.get("ctweb_password")), "at": now_iso(), "result": result,
          "doh": pilot_doh()}  # 1.6.4: the Settings card's Date of hire field (the pilot's own, not a secret)
    try:
        st.update(SEAL.public_info(settings_key()))
    except Exception as e:  # noqa: BLE001 (no key: the card says so; Web UI and plain settings/set still work)
        log.info("settings key unavailable: %s", e)
    if portal_on():  # 1.6.0 (FW-0061): the card shows the ntfy fields only then; set / not set, never a value
        c = load_creds() if creds is None else creds
        st.update({"ntfy": True, "has_ntfy_topic": bool(c.get("ntfy_topic")),
                   "has_ntfy_token": bool(c.get("ntfy_token")),
                   # 1.6.2 (item 9): a saved topic too easy to guess (saved before 1.6.2) is off; the card says so
                   "ntfy_topic_ok": bool(c.get("ntfy_topic")) and not NT.topic_refusal(c.get("ntfy_topic"))})
    return st


def publish_settings(c=None, creds=None, result=""):
    (c or MQ).publish(f"{T}/settings/state", json.dumps(settings_state(creds, result)), retain=True)


def settings_cmd(payload):
    """0.10.0: {T}/settings/set {username?, password?, ctweb_username?, ctweb_password?, my_name?} merges the
    non-empty values into creds.json (mode 600), publishes settings/state (no passwords) and restarts this
    watcher after RESTART_DELAY_S so run.py brings it back with the new credentials. 1.6.0 (FW-0061): on a pilot
    whose portal is on, a sealed message may also carry ntfy_topic and ntfy_token (a plain one never does).
    1.6.1: a password is kept byte for byte (plain or sealed); the other values are trimmed. CrewTrac details sent
    here (even the same ones) lift a refusal block on the details then in use for one more try (crewtrac_resaved)."""
    try:
        d = json.loads(payload)
        if not isinstance(d, dict):
            raise ValueError("not an object")
    except (ValueError, TypeError) as e:
        log.info("settings ignored: %s", e)
        return False
    keys = CRED_KEYS
    ntfy_off = ct_off = False
    if "enc" in d:  # 1.1.0: sealed by the dashboard Settings card
        try:
            d = SEAL.open_sealed(settings_key(), d["enc"])
            # 1.7.1 (F#155): the card's Remove CrewTrac login, sealed only like ntfy_off (the portal relays the sealed
            # message as it is: no contract change)
            ct_off = d.get("ctweb_off") is True
            if portal_on():  # 1.6.0 (FW-0061): ntfy only sealed, only on a portal pilot
                keys = CRED_KEYS + NTFY_KEYS
                # 1.6.2 (item 9): the token is optional; a topic must be hard to guess (ntfy.topic_refusal). An
                # unusable ntfy value refuses the whole message (nothing saved), with the reason; never the value.
                why = ""
                t = d.get("ntfy_topic")
                if isinstance(t, str) and t.strip():
                    why = NT.topic_refusal(t.strip())
                    why = f"ntfy topic: {why}" if why else ""
                k = d.get("ntfy_token")
                if not why and isinstance(k, str) and k.strip() and not NT.TOKEN_RE.fullmatch(k.strip()):
                    why = "ntfy access token: use 8 to 128 letters, digits, '.', '_' or '-'"
                if why:
                    log.info("settings refused: %s", why.split(":")[0] + " not usable")
                    publish_settings(creds=load_creds(), result=f"refused: {why}; nothing was saved")
                    return False
                ntfy_off = d.get("ntfy_off") is True  # 1.6.2: the card's Turn off phone alerts
        except Exception as e:  # noqa: BLE001 (SealError, or no usable key: never let it reach paho's thread)
            msg = str(e) if isinstance(e, SEAL.SealError) else f"settings key unavailable ({type(e).__name__})"
            log.info("sealed settings refused: %s", msg)
            try:
                publish_settings(creds=load_creds(), result=f"refused: {msg}")
            except Exception:  # noqa: BLE001
                pass
            return False
    # 1.6.4: the date of hire (Settings card), plain or sealed like the other non-secret fields. Checked again here; an
    # unusable one refuses the whole message (nothing saved), with the reason. Saved to <data>/cards.json, not creds.
    doh = d.get("doh")
    doh = doh.strip() if isinstance(doh, str) else ("" if doh is None else doh)
    if doh != "":
        why = doh_refusal(doh)
        if why:
            log.info("settings refused: date of hire not usable (%s)", why)
            publish_settings(creds=load_creds(), result=f"refused: date of hire: {why}; nothing was saved")
            return False
    doh_new = bool(doh) and doh != pilot_doh()
    cur = load_creds()
    changed = []
    if ntfy_off:  # 1.6.2: forget the topic and token (a later topic turns alerts on again)
        for k in NTFY_KEYS:
            if cur.pop(k, None) is not None:
                changed.append(k)
    ct_keys = ("ctweb_username", "ctweb_password")
    gone = [k for k in ct_keys if k in cur] if ct_off else []
    if gone:
        # 1.7.1 (F#155): forget the saved CrewTrac login (the charter watch then has none: no CrewTrac login at all);
        # its record goes too, so a refusal or a back-off of the old login says nothing about the next one
        for k in gone:
            cur.pop(k)
            if not has("addon_config"):
                # 1.7.1 review: on a pilot the options in memory hold creds.json's values from the start (load_opts),
                # so the state published now (settings_state) and the charter watch until the restart forget it too;
                # the admin's may be the add-on's own options, which stay
                OPTS.pop(k, None)
        changed.append("CrewTrac login removed")
        DB.put("crewtrac", {})
    for k in keys:
        v = d.get(k)
        if not isinstance(v, str) or not v.strip() or (ct_off and k in ct_keys):
            continue
        v = v if k in SECRET_KEYS else v.strip()  # 1.6.1: a password exactly as typed; names and ntfy values trimmed
        if cur.get(k) != v:
            cur[k] = v
            changed.append(k)
    ct_saved = not ct_off and any(isinstance(d.get(k), str) and d[k].strip() for k in ct_keys)
    fl_saved = any(isinstance(d.get(k), str) and d[k].strip() for k in ("username", "password"))
    if doh_new:  # 1.6.4: first, so a failed write leaves everything as it was
        try:
            doh_save(doh)
        except OSError as e:
            log.info("settings: date of hire not saved: %s", type(e).__name__)
            publish_settings(creds=cur, result="refused: the date of hire could not be saved; nothing was saved")
            return False
    if not changed:
        again = ct_saved and crewtrac_lift()  # 1.6.1: the same CrewTrac details saved again: one more try
        fl_again = fl_saved and flica_lift()  # 1.6.2 review: the same for FLICA details FLICA refused
        lifted = (("; CrewTrac gets one more try with these details" if again else "") +
                  ("; FLICA gets one more login try with these details" if fl_again else ""))
        if doh_new:  # 1.6.4: only the date of hire: no restart, the new state goes out at once (1.6.4 review: the
            # same logins saved with it still lift their refusal blocks, as they do alone)
            log.info("settings: date of hire saved (no restart needed)")
            publish_settings(creds=cur, result="saved: date of hire (no restart needed)" + lifted)
            pub("state_attr", state_attrs(S.get("note", "")))
        else:
            log.info("settings: nothing new (keys %s)", ", ".join(sorted(k for k in d if k in keys or k == "doh")) or
                     "none")
            publish_settings(creds=cur, result="nothing new" + (": no CrewTrac login is saved" if ct_off else "") +
                             lifted)
        if again:
            publish_charters()
            CHARTER_WAKE.set()
        return doh_new
    if doh_new:
        changed.append("date of hire")
    tmp = CREDS_FILE + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)  # never readable by others, even briefly
    with os.fdopen(fd, "w") as f:
        json.dump(cur, f)
    os.chmod(tmp, 0o600)
    os.replace(tmp, CREDS_FILE)
    if {"username", "password"} & set(changed):  # 1.6.2 review: new FLICA details: no refusal block, no login floor
        S.pop("flica_refused", None)
        S.pop(FL_KEY_LOST, None)  # 1.7.4: nor the block kept since the key was lost
        S.pop("login_ts", None)
        save_state(S)
    if creds_stop_cleared(changed):  # kills (the yield back-off count) stay; only Re-arm clears those
        S["machine"], S["note"] = "idle", "new settings"
        S["pot_urls"], S["parse_fail"], S["relogin_streak"] = {}, 0, 0
        save_state(S)
    if ct_saved:
        crewtrac_lift()  # 1.6.1: details CrewTrac refused before and saved again here get one more try
    publish_settings(creds=cur, result="saved: " + ", ".join(changed))
    S["settings_last"] = {"result": "saved: " + ", ".join(changed), "at": time.time()}  # 1.6.2 review: after the restart
    save_state(S)
    log.info("settings saved (%s); restarting in %d s to use them", ", ".join(changed), RESTART_DELAY_S)
    restart_later()
    return True


SETTINGS_LAST_S = 600  # 1.6.2 review: a save's result is said again after the restart for this long


def settings_last_result(now=None):
    """The result to publish on (re)connect: the last save's, said again for SETTINGS_LAST_S after the restart it
    caused, so a card that missed it (the restart came first) still gets its confirmation. '' otherwise."""
    r = S.get("settings_last") or {}
    now = time.time() if now is None else now
    if r.get("result") and 0 <= now - float(r.get("at") or 0) < SETTINGS_LAST_S:
        return f"{r['result']} (Watcher restarted with them)"
    return ""


def flica_lift():
    """1.6.2 review: the same FLICA details saved again in Settings while FLICA's refusal blocks them: the pilot says
    they are right. One more login try (Re-arm's path: still at most one login every LOGIN_MIN_GAP_S). True when the
    block was lifted. 1.7.4: the block kept since its key was lost (FL_KEY_LOST) is lifted the same way."""
    try:
        if flica_refused_at() is None:
            return False
        S.pop("flica_refused", None)
        S.pop(FL_KEY_LOST, None)
        S["note"] = "FLICA details saved again: one more login try"
        save_state(S)
        FLAGS["rearm"] = True
        WAKE.set()
        log.info("FLICA details saved again in Settings; the refusal block is lifted for one more try")
        return True
    except Exception as e:  # noqa: BLE001 (never let it stop a settings save)
        log.info("FLICA re-save not applied: %s", type(e).__name__)
        return False


def crewtrac_lift():
    """crewtrac_resaved(), never letting an error stop a settings save. 1.7.1 (F#22): nothing on a pilot, whose
    Watcher never logs in to CrewTrac (a login saved there stays unused, and Remove CrewTrac login still clears it)."""
    if is_pilot():
        return False
    try:
        return crewtrac_resaved()
    except Exception as e:  # noqa: BLE001
        log.info("charter: CrewTrac re-save not applied: %s", type(e).__name__)
        return False


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
    if not has("drop_mark"):  # 1.5.0 (FW-0063): no would_drop sensor on a pilot instance
        return
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
    draft is all there is; Ryan files the drop himself. 1.5.0 (FW-0063): the admin's only (drop_mark)."""
    if not has("drop_mark"):
        return
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
    check (written even with no finds, 1.6.2); all 24 months once per start. Read only, no FLICA traffic. FW-0010: the files carry crew names and
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
            # 1.6.2 (Release A item 15): this month and last month always have a file, empty or not, so the finds
            # card (and a portal pilot's export) never asks for a month file that does not exist
            if rows or i < 2 or os.path.exists(path):
                text = json.dumps({"month": month, "count": len(rows), "finds": rows}, separators=(",", ":"))
                tmp = path + ".tmp"
                with open(tmp, "w") as fh:
                    fh.write(text)
                os.replace(tmp, path)
                if i < 2:
                    rev.update(f"{month}\n{text}\n".encode())
        FINDS_FILES["all"] = True
        portal_files_dirty()  # 1.6.0: a portal pilot copies them to out/files (no-op otherwise)
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
        others = WF.subdirs(CARD_PAIRINGS) + [WWW_OLD] + WF.subdirs(WWW_OLD) if has("one_writer") else []
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


def entity_defs():
    """1.5.0 (FW-0063): every MQTT discovery entity as (comp, oid, cfg, feature), whatever this instance's role; cfg is
    the full discovery config. feature (roles.ENTITY_FEATURE, else core) says who gets it: discovery() publishes the
    ones this instance has."""
    base = {"availability_topic": AVAIL, "device": DEV}
    # 1.6.2 (Ryan 2026-11-10): the interval sliders' ranges; on a pilot whose portal is on, within contract 1 (normal up
    # to 20 min, what his portal can send, until Release C revises the contract; the Watcher's clamp takes 1 to 90)
    efl = ROLES.entity_freq_limits(INSTANCE, portal_on())
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
        # FW-0067: the working flight from this pilot's own schedule (working.py), for every instance
        ("sensor", "working_flight", {"name": "Working flight", "state_topic": f"{T}/working_flight",
                                      "value_template": "{{ value_json.state }}",
                                      "json_attributes_topic": f"{T}/working_flight",
                                      "json_attributes_template": "{{ value_json.attributes | tojson }}",
                                      "icon": "mdi:airplane-takeoff"}),
        # 1.7.1 (FW-0070): the next bid calendar alert (bidcal.py), with its cycle's dates and where they came from
        ("sensor", "bid_calendar", {"name": "Bid calendar", "state_topic": f"{T}/bid_calendar",
                                    "value_template": "{{ value_json.next_at }}", "device_class": "timestamp",
                                    "json_attributes_topic": f"{T}/bid_calendar", "icon": "mdi:calendar-clock"}),
        # 1.7.1 (FW-0072, admin only): the van at the layover station from Hark's working flight (layover.py), with
        # its time zone, HST and the 30 and 10 min alerts; and Ryan's layover notes by station, with Claude's guides
        ("sensor", "layover_van", {"name": "Layover van", "state_topic": f"{T}/layover_van",
                                   "value_template": "{{ value_json.at }}", "device_class": "timestamp",
                                   "json_attributes_topic": f"{T}/layover_van", "icon": "mdi:van-passenger"}),
        ("sensor", "layover_notes", {"name": "Layover notes", "state_topic": f"{T}/layover_notes",
                                     "value_template": "{{ value_json.count }}",
                                     "json_attributes_topic": f"{T}/layover_notes", "icon": "mdi:notebook-edit"}),
        # 1.7.2 (Ryan, Nov 12, admin only): the van alerts' switch (the layover card's tick box) and their two lead
        # times as sliders on the Settings tab (van_setting_cmd; second 0 is no second alert)
        ("switch", "van_alerts", {"name": "Van time alerts", "command_topic": f"{T}/van/alerts/set",
                                  "state_topic": f"{T}/van/alerts/state", "icon": "mdi:van-passenger"}),
        ("number", "van_alert_first", {"name": "First van alert", "command_topic": f"{T}/van/first_min/set",
                                       "state_topic": f"{T}/van/first_min/state",
                                       "min": VAN_LIMITS["first"][0], "max": VAN_LIMITS["first"][1], "step": 5,
                                       "mode": "slider", "unit_of_measurement": "min", "icon": "mdi:timer-outline"}),
        ("number", "van_alert_second", {"name": "Second van alert (0 is off)",
                                        "command_topic": f"{T}/van/second_min/set",
                                        "state_topic": f"{T}/van/second_min/state",
                                        "min": VAN_LIMITS["second"][0], "max": VAN_LIMITS["second"][1], "step": 5,
                                        "mode": "slider", "unit_of_measurement": "min",
                                        "icon": "mdi:timer-outline"}),
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
                                      "state_topic": f"{T}/freq/normal_min/state",
                                      "min": efl["normal_min"][0], "max": efl["normal_min"][1],
                                      "step": 1, "mode": "slider", "unit_of_measurement": "min",
                                      "icon": "mdi:timer-outline"}),
        ("number", "hunt_seconds", {"name": "Hunt check every", "command_topic": f"{T}/freq/hunt_s/set",
                                    "state_topic": f"{T}/freq/hunt_s/state",
                                    "min": efl["hunt_s"][0], "max": efl["hunt_s"][1],
                                    "step": 5, "mode": "slider", "unit_of_measurement": "s",
                                    "icon": "mdi:timer-alert-outline"}),
        ("sensor", "settings", {"name": "Settings", "state_topic": f"{T}/settings/state",
                                "value_template": "{{ value_json.has_password }}",
                                "json_attributes_topic": f"{T}/settings/state", "icon": "mdi:account-key",
                                "entity_category": "diagnostic"}),
        # FW-0066: what is on file (web.uploads_json: names, sizes and counts only) and the last chunked upload's
        # progress and result, for the uploads card of a user who is not an admin (no ingress session)
        ("sensor", "uploads", {"name": "Uploads on file", "state_topic": f"{T}/uploads",
                               "value_template": "{{ value_json.count }}",
                               "json_attributes_topic": f"{T}/uploads", "icon": "mdi:file-upload-outline"}),
        ("sensor", "upload_status", {"name": "Upload status", "state_topic": f"{T}/upload/status",
                                     "value_template": "{{ value_json.state }}",
                                     "json_attributes_topic": f"{T}/upload/status", "icon": "mdi:progress-upload"}),
        ("sensor", "ot_requests", {"name": "Open time requests", "state_topic": f"{T}/ot_requests",
                                   "value_template": "{{ value_json.pending }}",
                                   "json_attributes_topic": f"{T}/ot_requests", "icon": "mdi:swap-horizontal-circle-outline"}),
        ("sensor", "tickets", {"name": "Tickets", "state_topic": f"{T}/tickets", "value_template": "{{ value_json.open }}",
                               "json_attributes_topic": f"{T}/tickets", "icon": "mdi:ticket-outline"}),
        # 0.10.1: the crew index runs on Ryan's instance only (roles: crew_index)
        ("sensor", "crew_index", {"name": "Crew index", "state_topic": f"{T}/crew_index",
                                  "value_template": "{{ value_json.coverage_pct }}", "unit_of_measurement": "%",
                                  "json_attributes_topic": f"{T}/crew_index", "icon": "mdi:account-search"}),
        ("button", "crew_scan", {"name": "Update schedules", "command_topic": f"{T}/crew_scan/press",
                                 "icon": "mdi:account-sync"}),
    ]
    out = []
    for comp, oid, cfg in ents:
        # 0.10.3: HA ignores object_id now; default_entity_id sets the id, object_id stays for older HA.
        # 1.0.0: the id keeps the name-based suffix the entity has always had (ENTITY_SUFFIX), which the cards,
        # automations and recorder history use; the unique_id and topics keep the short oid.
        eid = f"{T}_{ENTITY_SUFFIX.get(oid, oid)}"
        cfg = {**base, **cfg, "unique_id": f"{T}_{oid}", "object_id": eid, "default_entity_id": f"{comp}.{eid}"}
        out.append((comp, oid, cfg, ROLES.ENTITY_FEATURE.get(oid, "core")))
    return out


def discovery(c):
    """Publishes this instance's entities (entity_defs). 1.5.0 (FW-0063): on a pilot instance the entities of a feature
    it lacks get an empty retained config, which removes them from HA (Would drop, Auto swap, Map swap pages)."""
    for comp, oid, cfg, feature in entity_defs():
        if has(feature):
            c.publish(f"homeassistant/{comp}/{T}/{oid}/config", json.dumps(cfg), retain=True)
        else:
            c.publish(f"homeassistant/{comp}/{T}/{oid}/config", "", retain=True)
    for comp, oid in RETIRED_ENTITIES:  # an empty retained config removes the entity from HA
        c.publish(f"homeassistant/{comp}/{T}/{oid}/config", "", retain=True)


def subscribe_all(cl):
    """1.5.0 (FW-0063): this instance's subscriptions (roles.subscriptions). The admin's are the 1.4.12 list; a pilot
    instance does not take email/alert, auto_swap/set, swap_map/press, drop/set or crew_scan/press. upload/chunk at
    qos 1 (FW-0066: an upload in chunks, mqtt.publish from the uploads card). 1.6.0: a pilot whose portal is on
    also takes pref/set (roles.PORTAL_SUBS)."""
    for t, qos in ROLES.subscriptions(INSTANCE, portal_on()):
        cl.subscribe((f"{T}/{t}", qos) if qos else f"{T}/{t}")
    if is_pilot():  # 1.7.1 (F#22): the admin's shared charter list (retained, the admin's prefix; never a command)
        cl.subscribe((CHARTERS_SHARED, 1))
    for sub in pilot_status_subs():  # 1.7.1 review: the admin reads its pilots' availability (recall_replay_tick)
        cl.subscribe(sub)


def mqtt_start():
    m = mqtt_creds()
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=T)
    c.username_pw_set(m["username"], m["password"])
    c.will_set(AVAIL, "offline", retain=True)
    c.on_message = on_message_safe
    if portal_on():  # 1.6.0 (FW-0061): a portal pilot notes what it publishes for its export (portal_wrap)
        portal_wrap(c)

    def on_connect(cl, u, f, rc, p=None):
        cl.publish(AVAIL, "online", retain=True)
        discovery(cl)
        subscribe_all(cl)
        publish_settings(cl, result=settings_last_result())
        fq = freq()
        cl.publish(f"{T}/freq/normal_min/state", str(fq["normal_min"]), retain=True)
        cl.publish(f"{T}/freq/hunt_s/state", str(fq["hunt_s"]), retain=True)
        publish_rules(cl)
        if has("auto_swap"):
            cl.publish(f"{T}/auto_swap/state", "ON" if S.get("auto_swap") else "OFF", retain=True)
        publish_van_settings(cl)  # 1.7.2: the van alerts switch and sliders (the admin only)
        publish_swap_mode(cl)
        publish_swap_tests()
        publish_uploads(cl, force=True)  # FW-0066
        _BIDCAL["sig"] = None  # 1.7.1 review: the bid calendar sensor goes again at the next minute's bidcal_tick
        forget_layover_sigs()  # 1.7.1 review: and the van and notes sensors at the next sweep's van_tick
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
    "uploads": ("files", "end"),  # FW-0066: newest first, so the oldest files go
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
    if topic.startswith("event/") and not ROLES.event_allowed(topic[6:], INSTANCE):  # 1.5.0 (FW-0063): a backstop
        log.info("%s not sent: not for a pilot instance", topic)
        return
    if not isinstance(payload, str):
        payload = json.dumps(cap_attrs(topic, payload) if topic in ATTR_TRIM else payload)
    MQ.publish(f"{T}/{topic}", payload, retain=retain)


LIST_REV = {}  # FW-0060: name -> rev of the list file last written, so an unchanged list is not written again
LIST_LOCK = threading.Lock()  # FW-0069: pub_pilot writes its list file from the MQTT thread too (cached replies)


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
        with LIST_LOCK:  # FW-0069: one writer at a time (the .tmp name is shared)
            if LIST_REV.get(name) != (key, rev) or not os.path.exists(path):
                os.makedirs(fdir, exist_ok=True)
                tmp = path + ".tmp"
                with open(tmp, "w") as fh:
                    fh.write(text)
                os.replace(tmp, path)
                LIST_REV[name] = (key, rev)
                portal_files_dirty()  # 1.6.0: a portal pilot copies it to out/files (no-op otherwise)
        return key, rev
    except Exception as e:
        log.info("%s file skipped: %s", name, WF.scrub(e, key))
        return None, None


FETCHES = {"n": None, "pub_at": 0, "hour": None}


def fetches_payload():
    """sensor.<prefix>_flica_fetches: {total, at} and (1.7.1, F#10) hour, this Watcher's FLICA loads in the hour up
    to at (the host gate's own count, gate.counts), and budget, his loads an hour (100 on a pilot, None on the admin):
    plain numbers of this instance, for the health line on the settings card."""
    if FETCHES["n"] is None:
        FETCHES["n"] = int(DB.get("fetches_total") or 0)
    p = {"total": FETCHES["n"], "at": now_iso()}
    try:
        c = GATE.counts()
        p["hour"], p["budget"] = int(c["own"]), c["budget"]
        FETCHES["hour"] = p["hour"]
    except Exception as e:  # noqa: BLE001 (the count is a nicety; the total goes out regardless)
        log.info("FLICA loads this hour not read: %s", type(e).__name__)
    return p


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
            pub("fetches", fetches_payload())
    except Exception as e:
        log.info("fetch count skipped: %s", e)


def fetches_tick():
    """1.7.1 (F#10): on a pilot, the uploads janitor's minute: the fetches sensor again when his loads in the last
    hour changed (loads age out of the hour while he is paused or between checks), so his health line stays true.
    Nothing when the count is the same (no recorder row a minute)."""
    if not is_pilot():
        return False
    try:
        own = int(GATE.counts()["own"])
    except Exception:  # noqa: BLE001
        return False
    if own == FETCHES.get("hour"):
        return False
    pub("fetches", fetches_payload())
    return True


# ---------------------------------------------------------------- 1.6.2 (Release A): FLICA gate and breakers
# gate.py: one lock file for every Watcher in the container (the admin's /data, the parent of each pilot's /data/<name>):
# every FLICA page load waits for the pacing (1.5 to 3.5 s after this Watcher's last load, 1.5 s after the host's),
# the host cap (480 an hour, all pilots) and a pilot's own budget (100 an hour). Each read path has a breaker.
GATE_FILE = os.environ.get("FLIGHT_WATCHER_GATE") or (
    os.path.join(os.path.dirname(DATA.rstrip("/")) or "/", "flica_gate.lock") if INSTANCE else f"{DATA}/flica_gate.lock")
GATE_CHECK_TOKENS = 3  # a check starts once this many loads fit the budget (it waits, WAKE-able, until they do)


def check_tokens():
    """1.6.2 review: the loads the next check needs whatever happens (its open time pages, or the discovery's main menu
    and mobile pot; the schedule read when due; one more): it starts only once they fit, so it never waits inside."""
    n = len(S.get("pot_urls") or {}) or 2
    if (S.get("close_in") or {}).get("bcid"):
        n += 1
    try:
        if schedule_due(FLAGS.get("full")):
            n += SCHED_TRIES_PER_READ
    except Exception:  # noqa: BLE001
        n += SCHED_TRIES_PER_READ
    return max(GATE_CHECK_TOKENS, n + 1)
BRK_JUDGED = ("schedule", "lookup")  # paths whose callers judge each page (a good page is not a good read by itself)
# 1.6.2 review: paths Flica judges by what their parsers know (page_verdict): name in the breaker's note
BRK_PAGE_JUDGED = {"tradeboard": "Tradeboard", "pairing": "pairing", "grid": "reserve grid"}
TB_KNOWN = ("tradeboard", "var g='pickup'", "var g=\"pickup\"", "pickup trip", "propose trade", "add to favorites",
            "my requests", "all requests")
# 1.7.3: on while crew_variants reads a lettered copy (H3646D) that may not exist. FLICA answers a missing one with a
# page that names the id and holds nothing (page_verdict 'error'): a miss, not a failed pairing read (three in a row
# stopped every pairing read for 30 min on each crew index run, Nov 12-13). FLICA's application error page
# (inflt.ERROR_HINTS) is a miss on a probe too; a page nothing knows still stops the path at once
PROBE = {"miss_ok": False}


def page_verdict(path, url, html):
    """1.6.2 review: 'ok' (a page its parser reads), 'unknown' (none of its parsers knows the page: the path stops at
    once), 'error' (the page is the one asked for but holds nothing readable: a failed read, 3 in a row stop) or ''
    (no verdict). FLICA's 'Service Temporarily Unavailable' and other strange pages are 'unknown'."""
    low = (html or "").lower()
    u = (url or "").lower()
    if path == "tradeboard":
        if "tb_frame" in u:
            return "ok" if ("<frame" in low or "tb_otherrequests" in low or any(k in low for k in TB_KNOWN)) \
                else "unknown"
        if TB.has_rows(html) or any(k in low for k in TB_KNOWN):
            return "ok"
        return "unknown"
    if path == "pairing":
        d = parse_detail(html)
        if d.get("report") or d.get("crew") or d.get("credit"):
            return "ok"
        m = re.search(r"pid=([a-z]\d{4}[a-z]?)", u)
        return "error" if m and m.group(1) in low else "unknown"
    if path == "grid":
        if "reservegridservice" in u:
            try:
                return "ok" if isinstance(json.loads(html), (dict, list)) else "unknown"
            except ValueError:
                return "unknown"
        try:
            return "ok" if G.parse_grid_html(html, local_now().year) else "error"
        except Exception:  # noqa: BLE001
            return "error"
    return ""
HEALTH = {"note": "", "gate": "", "held": "", "brk": ""}  # the state note the gate, the pace and the breakers last put
# up; 1.7.3: brk is the breakers' part of it as health_note last saw it (health_note_tick)


def hst_hm(ts):
    """HH:MM HST of a unix time (no zone label)."""
    return datetime.fromtimestamp(float(ts or 0), HST).strftime("%H:%M")


def gate_note(why, until):
    """1.6.2: Gate.on_wait: the state note while a FLICA load waits for a budget ('' once it went). While a pilot hunts
    the budget wait reads as his held hunt (held_note, with the next check's time)."""
    if why == "budget" and FLAGS.get("hunt") and GATE.budget:
        HEALTH["gate"] = held_note(until)
    elif why == "budget":
        HEALTH["gate"] = (f"FLICA budget: {GT.PILOT_BUDGET_H} page loads in the last hour; the next one waits until "
                          f"{hst_hm(until)} HST")
    elif why == "host":
        HEALTH["gate"] = (f"FLICA host limit: {GT.HOST_CAP_H} page loads in the last hour from this host (every "
                          f"pilot's Watcher); the next one waits until {hst_hm(until)} HST")
    else:
        HEALTH["gate"] = ""
    health_note_apply()


def health_note():
    HEALTH["brk"] = BRK.note()
    return "; ".join(x for x in (HEALTH["gate"] or HEALTH["held"], HEALTH["brk"]) if x)


def health_note_tick():
    """1.7.3: a stop's end (open_until passing) moves no read, trip or gate, so nothing put the note together again and
    'FLICA pairing read paused until 05:52 HST' was still up at 06:25 (seen live). sleep() calls this every tick: once
    the breakers' note differs from the one health_note last saw, the note is applied again (published only when it
    changed; a stop, pause or yield note stays, health_note_apply). No FLICA load."""
    if BRK.note() != HEALTH["brk"]:
        health_note_apply()


def health_note_apply():
    """1.6.2: the gate's and the breakers' note becomes the state note while the Watcher is idle or hunting and the note
    is empty, a start note or the one they put up last (a stop, pause or yield note is never replaced)."""
    want, cur = health_note(), S.get("note") or ""
    if want == cur:
        return
    ours = cur in ("", HEALTH["note"]) and S.get("machine") in ("idle", "hunting")
    if ours or cur in ("starting", "un-paused") or cur.startswith("logged in"):
        HEALTH["note"] = want
        set_machine(S.get("machine", "idle"), want)


def gate_sleep(sec):
    """1.7.3 review: a wait inside a check (a load waiting in the gate for pacing or a budget) never goes through the
    loop's sleep(), so it looks at the note after each wait chunk too (health_note_tick: no FLICA load, published only
    on a change)."""
    time.sleep(sec)
    health_note_tick()


GATE = GT.Gate(GATE_FILE, INSTANCE or "admin", budget=GT.PILOT_BUDGET_H if ROLES.role(INSTANCE) == ROLES.PILOT else None,
               log=log, on_wait=lambda why, until: gate_note(why, until), sleep=gate_sleep)
BRK = GT.Breakers(lambda: S.setdefault("breakers", {}), save=lambda: save_state(S), log=log, fmt=hst_hm,
                  on_change=lambda: health_note_apply())
# 1.6.2 review: while a check runs, a load waiting for the gate is given up (GateAbort) once Pause is on or the Watcher
# stopped, and the check ends with nothing more loaded. On a pilot the reads that may be left out (read_guard
# optional=True: the Tradeboard, the reserve grid, the request lists, the crew index, his own trips, pot details,
# pickups) skip a load that would wait for his budget (GATE_KEEP) or pass opt_cap() an hour: the pot keeps its share.
RUN = {"check": False, "optional": False, "aborted": "", "skipped": set(), "opt": [], "opt_name": ""}
GATE_KEEP = 4  # an optional load leaves this many of a pilot's budget free (the next check's start)


PACE_OPT_H = 12  # 1.6.2: a pilot's paced hunt leaves at least this many loads an hour to the reads that may be left out
# 1.7.1 (LIVE-1): those loads were one first come, first served pool, so the reads early in a check (his own trips, the
# pickups and their in-flight lookups) took every load that came free, and the Tradeboard, the reserve grid, the request
# lists and the pot details were left out for hours. Each of those four now has its own share (opt_shares: one whole
# read an hour), the rest is a pool any optional read may use, and the pace keeps room for all of it (opt_hour).
OPT_POOL_H = 4  # loads an hour left to the pool when the shares alone reach PACE_OPT_H
OPT_WAIT_LOG_S = 1800  # a read that waits for room in a pilot's budget says so in the log at most this often
OPT_WAIT_LOGGED = {}


def close_in_h():
    """1.6.2 review: the close-in folder's FLICA loads an hour that a hunt costs whatever its pace: hunting reads it at
    most every CLOSE_IN_READ_S (FW-0035, about 12 an hour), not on every check. 0 when its BCID is not known, and in
    normal mode (every check reads it then: pot_pages counts it)."""
    return 3600.0 / CLOSE_IN_READ_S if FLAGS.get("hunt") and (S.get("close_in") or {}).get("bcid") else 0.0


def pot_pages():
    """The open time pages every check loads: the pot months (2 until they are found) and, in normal mode, the close-in
    folder (hunting, it is an hourly cost instead: close_in_h)."""
    ci = 1 if (S.get("close_in") or {}).get("bcid") and not FLAGS.get("hunt") else 0
    return (len(S.get("pot_urls") or {}) or 2) + ci


def budget_pace_s():
    """1.6.2 (Ryan 2026-11-10: hunt 5 to 90 s): on a pilot, the shortest wait between his checks that his FLICA budget
    keeps up for a whole hour: the pot's pages a check into his budget less his schedule read (2 loads every 30 min),
    one check's start, the optional reads (opt_hour: PACE_OPT_H, 1.7.1 more for two bid months) and, hunting, the
    close-in folder's reads (close_in_h): about 44 s with 1 pot page, 96 s with 2, about 2 min once the close-in folder
    is known. A shorter hunt is spread over the hour at this pace (gap) instead of using the budget in minutes and then
    waiting most of the hour. 0 on the admin (no budget)."""
    if not GATE.budget:
        return 0.0
    room = GATE.budget - 2 * SCHED_TRIES_PER_READ - GATE_CHECK_TOKENS - opt_hour() - close_in_h()
    return pot_pages() * 3600.0 / max(1.0, room)


def _bid_folders():
    """(the BCIDs of his pot pages, the request folders requests_check reads: those and, once verified, the close-in
    folder)."""
    regular = sorted({x for x in (bcid(u) for u in (S.get("pot_urls") or {}).values()) if x})
    ci = S.get("close_in_bcid") if (S.get("close_in") or {}).get("verified") else None
    return regular, regular + ([ci] if ci and ci not in regular else [])


def opt_shares():
    """1.7.1 (LIVE-1): {read: loads an hour kept for it} on a pilot, {} on the admin: one whole read an hour of each
    secondary read. The Tradeboard costs 2 loads a bid number (its frame and its list), the reserve grid 2 a pot page
    (its JSON and the page cross-check), the requests 1 a folder (the open time list) and 1 a bid number (his trades
    on the Tradeboard), the pot details 2 (a new trip's page or two). Whatever more they read comes out of the pool,
    like every other optional read."""
    if not GATE.budget:
        return {}
    regular, folders = _bid_folders()
    nums = {b.split(".")[-1] for b in regular}
    grid = sum(1 for u in (S.get("pot_urls") or {}).values() if bcid(u))
    return {"tradeboard_check": 2 * len(nums), "grid_check": 2 * grid, "requests_check": len(folders) + len(nums),
            "pot_details": 2}


def opt_hour():
    """1.7.1 (LIVE-1): the optional loads an hour a pilot's pace keeps room for: PACE_OPT_H, or the shares plus a small
    pool (OPT_POOL_H) when they need more (two bid months: 18, so a hunt at the floor goes from about 89 s to 96 s
    apart; one bid month stays at 12, about 44 s)."""
    return max(PACE_OPT_H, sum(opt_shares().values()) + OPT_POOL_H)


def held_note(until=None):
    """1.6.2 (Ryan 2026-11-10): a pilot's check frequency faster than his FLICA budget allows, in plain words ('Hunting
    every 10 s is held to 100 FLICA loads an hour: checks wait for the budget'), with the pace it is held to or, while
    the gate makes the loop wait, the next check's time. '' when nothing holds it (the admin, a slow enough setting)."""
    fq, hunt = freq(), bool(FLAGS.get("hunt"))
    pace = budget_pace_s()
    want = fq["hunt_s"] if hunt else fq["normal_min"] * 60
    if not GATE.budget or (not until and pace <= want):
        return ""
    head = (f"Hunting every {fq['hunt_s']} s" if hunt else f"Checking every {fq['normal_min']} min") + \
        f" is held to {GATE.budget} FLICA loads an hour: checks wait for the budget"
    return head + (f" (next at {hst_hm(until)} HST)" if until else f", at least {int(math.ceil(pace))} s apart")


def held_apply():
    """The held note (held_note) joins the state note while the Watcher is idle or hunting (health_note_apply)."""
    want = held_note() if ROLES.role(INSTANCE) == ROLES.PILOT else ""
    if want != HEALTH["held"]:
        HEALTH["held"] = want
        health_note_apply()


def opt_cap():
    """1.6.2 review: the optional loads a pilot may make in an hour: his budget less what the open time pot needs at
    his check rate (its pages times checks an hour; a check rate his budget holds counts at its pace, budget_pace_s;
    hunting, the close-in folder's reads an hour, close_in_h), his schedule read (2 loads every 30 min) and one check's
    start."""
    if not GATE.budget:
        return None
    fq = freq()
    every = max(1.0, float(fq["hunt_s"] if FLAGS.get("hunt") else fq["normal_min"] * 60), budget_pace_s())
    pot = pot_pages() * 3600.0 / every + min(close_in_h(), 3600.0 / every)
    return max(0, GATE.budget - int(round(pot)) - 2 * SCHED_TRIES_PER_READ - GATE_CHECK_TOKENS)


def _opt_room(name, now):
    """1.7.1 (LIVE-1): (loads the read `name` may still make in this hour, when the oldest optional load leaves it):
    its own share (opt_shares) first, then the pool (opt_cap less every share), never past opt_cap in all. (None, now)
    when nothing limits it (the admin). RUN['opt'] holds (time, read) of this process's optional loads."""
    RUN["opt"] = [(t, n) for t, n in RUN["opt"] if now - GT.WINDOW_S < t <= now + 5]
    cap = opt_cap()
    if cap is None:
        return None, now
    shares = opt_shares()
    used = collections.Counter(n for _, n in RUN["opt"])
    pool = max(0, cap - sum(shares.values()))
    pool_used = sum(max(0, c - shares.get(n, 0)) for n, c in used.items())
    own = max(0, shares.get(name, 0) - used.get(name, 0))
    room = min(cap - len(RUN["opt"]), own + max(0, pool - pool_used))
    return max(0, room), (RUN["opt"][0][0] if RUN["opt"] else now) + GT.WINDOW_S


def opt_load():
    """Before an optional load on a pilot: GateSkip when the read it belongs to (RUN['opt_name'], set by read_guard)
    has used its share of the last hour and the pool is used up too, or the optional loads reached opt_cap() in all
    (this process's count; a restart starts it again, the gate's budget still holds)."""
    room, until = _opt_room(RUN.get("opt_name") or "", time.time())
    if room is not None and room < 1:
        raise GT.GateSkip("budget", until)


def opt_fits(n):
    """1.7.1 (LIVE-1): True when an optional read can make its n loads now (its share or the pool, and his budget and
    the host's cap with GATE_KEEP left free), so a Tradeboard read never loads its frame and is then left out of its
    list. A read calls it before its own timer moves: one that does not fit tries again at a later check, quietly (one
    log line at most every OPT_WAIT_LOG_S). Always True on the admin and outside a check's optional reads."""
    if not (RUN["check"] and RUN["optional"] and GATE.budget) or n <= 0:
        return True
    name = RUN.get("opt_name") or ""
    room, _ = _opt_room(name, time.time())
    c = GATE.counts()
    ok = (room is None or room >= n) and c["own"] + n <= GATE.budget - GATE_KEEP and \
        c["host"] + n <= (GATE.cap or GT.HOST_CAP_H) - GATE_KEEP
    if not ok and time.time() - OPT_WAIT_LOGGED.get(name, 0) >= OPT_WAIT_LOG_S:
        OPT_WAIT_LOGGED[name] = time.time()
        log.info("%s waits for room in this pilot's FLICA budget (%d loads an hour kept for it, %d needed now)",
                 name, opt_shares().get(name, 0), n)
    return ok


def gate_abort():
    """Why a load waiting in the gate must be given up ('' when it may wait): only while a check runs."""
    if not RUN["check"]:
        return ""
    if FLAGS.get("pause"):
        return "Pause is on"
    if str(S.get("machine") or "").startswith("stopped"):
        return "the Watcher stopped"
    return ""


def read_guard(fn, *a, default=None, optional=False, **k):
    """1.6.2: a read path called from check(): a load its breaker refused ends that read only (logged), never the
    check (the pot watch keeps its own stop rules). Review: a load given up for Pause or a stop (GateAbort) ends the
    check; optional=True marks a read whose loads a pilot's budget may leave out (GateSkip, logged once a check)."""
    was, RUN["optional"] = RUN["optional"], bool(optional) or RUN["optional"]
    was_name = RUN.get("opt_name") or ""
    if optional and not was:  # 1.7.1 (LIVE-1): its loads count against this read's share (opt_shares)
        RUN["opt_name"] = getattr(fn, "__name__", "read")
    try:
        res = fn(*a, **k)
    except GT.GateAbort:
        raise
    except GT.GateSkip as e:
        name = getattr(fn, "__name__", "read")
        if name not in RUN["skipped"]:
            RUN["skipped"].add(name)
            log.info("%s left out of this check: %s", name, e)
        res = default
    except GT.BreakerOpen as e:
        log.info("%s skipped: %s", getattr(fn, "__name__", "read"), e)
        res = default
    finally:
        RUN["optional"], RUN["opt_name"] = was, was_name
    if RUN["aborted"]:  # a read that caught the GateAbort itself: the check still ends here
        raise GT.GateAbort(RUN["aborted"])
    return res


def set_machine(state, note=""):
    moved = S.get("machine") != state
    if moved:
        log.info("state %s -> %s %s", S.get("machine"), state, note)
    if S.get("machine") != state or not S.get("since"):
        S["since"] = now_iso()
    S["machine"] = state
    S["note"] = note
    save_state(S)
    pub("state", state)
    pub("state_attr", state_attrs(note))
    if moved and EXPORT["on"] and ROLES.machine_event(state):  # 1.6.0 (FW-0061): one portal event per new state
        portal_event(ROLES.machine_event(state), {"state": state, "since": S["since"]})


def state_attrs(note):
    """sensor.<prefix>_state's attributes (set_machine; 1.6.4: also right after a date of hire is saved)."""
    return {"note": note, "version": VERSION, "since": S.get("since") or "", "instance": INSTANCE, "doh": pilot_doh(),
            "role": ROLES.role(INSTANCE), "features": ROLES.features(INSTANCE)}  # 1.5.0 (FW-0063)


def pilot_doh():
    """FW-0010: the pilot's date of hire (YYYY-MM-DD) from <data>/cards.json for the schedule card's longevity year,
    "" when none. Published in sensor.<prefix>_state (behind HA's login); the deployed card file under /local/ (no
    login) carries the placeholder only (cards.py). 1.6.4: the Settings card saves it here (settings_cmd, doh_save)."""
    try:
        with open(f"{DATA}/cards.json", encoding="utf-8") as f:
            d = json.load(f).get("doh", "")
    except (OSError, ValueError, AttributeError):
        return ""
    return d if isinstance(d, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", d) else ""


DOH_MIN = "1960-01-01"  # 1.6.4: the earliest date of hire the Settings card and the Watcher take


def doh_refusal(v, today=None):
    """1.6.4: why a date of hire from the Settings card cannot be saved ("" when it can): YYYY-MM-DD, a real date, not
    after today (HST) and not before DOH_MIN. The card checks the same (fwDohWhy). The value is never in the reason."""
    if not isinstance(v, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
        return "use YYYY-MM-DD"
    try:
        d = date.fromisoformat(v)
    except ValueError:
        return "not a real date"
    today = today or local_now().date()
    if d > today:
        return "it is in the future"
    if v < DOH_MIN:
        return f"it is before {DOH_MIN[:4]}"
    return ""


def doh_save(doh):
    """1.6.4: the date of hire into <data>/cards.json ("doh"), every other key there kept; atomic, mode 0600. A file
    that is not a JSON object is replaced (it had nothing pilot_doh could read); one that cannot be read raises OSError
    (nothing is written)."""
    path = f"{DATA}/cards.json"
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    except FileNotFoundError:
        d = {}
    except ValueError:
        d = None
    if not isinstance(d, dict):
        log.info("%s was not readable as settings: written again with the date of hire only", os.path.basename(path))
        d = {}
    d["doh"] = doh
    PT.write_private(path, json.dumps(d))


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
        """Exactly one attempt. Returns 'ok', 'failed' or 'blocked'. 1.6.2 review: login_error names a failure that is
        no refusal by FLICA (a load error, no login form), so a pilot's refusal block is not set by it."""
        self.login_error = None
        log.info("login attempt")
        S["last_login_attempt"] = now_iso()
        save_state(S)
        self.new_context(fresh=True)  # old cookies can skip the login form and break the login
        page = self.ctx.new_page()
        try:
            self._load()  # 1.6.2: the login page and its submit go through the gate too (no breaker)
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
                self.login_error = "no username field"
                return "failed"
            user_in = page.locator(f"input[data-fwi='{cands[-1]['i']}']")
            pw_in = page.locator(f"input[data-fwi='{pw_idx}']")
            user_in.fill(OPTS["username"])
            pw_in.fill(OPTS["password"])
            self._load()
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
                if CAP.admin:  # 1.6.2 (item 8): a screenshot cannot be masked, so a pilot's login is never saved
                    os.makedirs(SHARE, exist_ok=True)
                    page.screenshot(path=f"{SHARE}/last_login.png", full_page=True)
                vis = page.inner_text("body")[:600].replace("\n", " | ")
                log.info("after login url=%s text=%s", page.url.split("?")[0], page_log(vis))
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
            self.login_error = type(e).__name__
            return "failed"
        finally:
            page.close()

    def discover_pot_urls(self):
        """Walk the main menu once, open each 'View Opentime Pot' under the configured
        section for the current and next month, and remember the content frame URL."""
        page = self.ctx.new_page()
        found = {}
        try:
            self._load()  # 1.6.2: through the gate; the pot discovery keeps the pot's own stop rules (no breaker)
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
                log.info("mobile pot probe: classify=%s len=%d text=%s", mk, len(html), page_log(txt[:1500]))
                rows = re.findall(r"<tr[^>]*>.*?</tr>", html, re.S | re.I)
                log.info("mobile pot rows=%d sample=%s", len(rows), page_log(str([r[:400] for r in rows[:4]])))
                if mk in ("killed", "expired"):
                    return None
                if mk in ("captcha", "blocked"):  # 1.6.2 review: never answered, and no new login to get around it
                    return mk
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
                if kind in ("captcha", "blocked"):  # the main menu asks for a CAPTCHA and the mobile pot is no way round
                    return kind
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
                self._load()  # 1.6.2: the click opens a FLICA page: one load through the gate
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

    def _load(self, url=None):
        """1.6.2: before every FLICA page load: the read path's breaker (BreakerOpen while it is stopped; the pot, the
        login and the pot discovery have none), then the host-wide gate (pacing, host cap, a pilot's budget), then the
        page counter. Returns the read path ('' for none)."""
        path = GT.read_path(url) if url else ""
        if path and path != "pot" and not BRK.allow(path):
            raise GT.BreakerOpen(path, hst_hm(BRK.until(path)) + " HST")
        optional = bool(RUN["check"] and RUN["optional"] and GATE.budget)
        if optional:
            opt_load()  # 1.6.2 review: the pot's share of a pilot's budget is never spent on optional reads
        try:
            GATE.acquire(keep=GATE_KEEP if optional else 0, abort=gate_abort)
        except GT.GateAbort as e:
            RUN["aborted"] = e.why
            raise
        if optional:
            RUN["opt"].append((time.time(), RUN.get("opt_name") or ""))
        health_note_tick()  # 1.7.3 review: pages slower than the pace never wait in the gate; a stop's end shows here
        count_fetch()
        return path if path != "pot" else ""

    def _loaded(self, path, html=None, error=None, url=""):
        """1.6.2: a CAPTCHA or interstitial page stops its read path for 6 h (it is never answered). On a path whose
        callers do not judge the page themselves, a load error is a failed read; review: the Tradeboard, pairing and
        grid pages are judged here by what their parsers know (page_verdict), so a page none of them knows stops the
        path for 30 min instead of counting as a good read."""
        if not path:
            return
        if error is not None:
            if path not in BRK_JUDGED:
                BRK.fail(path, f"load error ({type(error).__name__})")
            return
        kind = classify(html or "")
        if kind == "captcha":
            BRK.fail(path, "a CAPTCHA page (never answered)", "captcha")
        elif kind == "ok" and path in BRK_PAGE_JUDGED:
            v = page_verdict(path, url, html or "")
            if v == "ok":
                BRK.ok(path)
            elif PROBE["miss_ok"] and (v == "error" or any(h in visible_text(html or "").lower()
                                                           for h in IF.ERROR_HINTS)):
                pass  # 1.7.3: a probed lettered copy that does not exist (or FLICA's application error page for it,
                # a miss in crew_variants since FW-0068): the breaker counts nothing
            elif v in ("unknown", "error"):
                BRK.fail(path, f"not a {BRK_PAGE_JUDGED[path]} page" + (" (a page the parser does not know)"
                                                                       if v == "unknown" else ""), v)
        elif kind == "ok" and path not in BRK_JUDGED:
            BRK.ok(path)

    def fetch(self, url):
        path = self._load(url)
        try:
            html = self.ctx.request.get(url, timeout=45000).text()
        except Exception as e:
            self._loaded(path, error=e)
            raise
        self._loaded(path, html, url=url)
        return html

    def menu_tree(self):
        """0.8.4: the left menu's JS tree (M.addC entries with the tokened Schedules links). FLICA only
        builds it inside the real menu frame, so load the main menu in a tab and read that frame's
        source. Read only: no clicks."""
        path = self._load(f"{BASE}/online/mainmenu.cgi")
        page = self.ctx.new_page()
        try:
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
                            self._loaded(path, html)
                            return html
                time.sleep(1)
            self._loaded(path, html)
            return html
        except Exception as e:
            self._loaded(path, error=e)
            raise
        finally:
            page.close()

    def render(self, url, wait_for=None, timeout=30000):
        """0.4.12: load a JS-built page in a real tab (read only, no clicks) and return its HTML
        once `wait_for` (a CSS selector) is present, plus the API responses it fetched."""
        path = self._load(url)
        page = self.ctx.new_page()
        calls = []
        page.on("response", lambda resp: calls.append((resp.url, resp.status)) if "/api/" in resp.url or "json" in (resp.headers.get("content-type") or "") else None)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            if wait_for:
                page.wait_for_selector(wait_for, timeout=timeout)
            else:
                time.sleep(4)
            html = page.content()
        except Exception as e:
            self._loaded(path, error=e)
            raise
        finally:
            page.close()
        self._loaded(path, html, url=url)
        return html, calls


# ---------------------------------------------------------------- main loop
def freq():
    """Current settings. Defaults are the midpoints of the add-on options (6 min normal, 40 s hunt)."""
    f = dict(S.get("freq") or {})
    o = {"idle_min_s": 120, "idle_max_s": 600, "hunt_min_s": 20, "hunt_max_s": 60, **OPTS}  # config.yaml's defaults
    f.setdefault("normal_min", max(1, round((o["idle_min_s"] + o["idle_max_s"]) / 2 / 60)))
    f.setdefault("hunt_s", max(5, round((o["hunt_min_s"] + o["hunt_max_s"]) / 2)))
    for k, (lo, hi) in FREQ_LIMITS.items():  # stored values from wider old ranges are clamped
        f[k] = max(lo, min(hi, f[k]))
    return f


def gap():
    fq = freq()
    mid = fq["hunt_s"] if FLAGS["hunt"] else fq["normal_min"] * 60
    lo, hi = mid * (1 - JITTER), mid * (1 + JITTER)
    if ROLES.role(INSTANCE) == ROLES.PILOT:  # 1.6.2 review: the jitter never takes a pilot under 5 s / 1 min
        lo = max(lo, FREQ_LIMITS["hunt_s"][0] if FLAGS["hunt"] else FREQ_LIMITS["normal_min"][0] * 60)
        pace = budget_pace_s()  # 1.6.2 (Ryan 2026-11-10): a short hunt is spread over the hour, still irregular
        if pace > lo:
            lo, hi = pace, max(hi, pace * (1 + JITTER))
        hi = max(hi, lo)
    return random.uniform(lo, hi)


def sleep(sec):
    """Wait sec seconds or until WAKE is set. FW-0067: looks at the working flight every WORKING_TICK_S meanwhile
    (it publishes only on a change), so it follows the schedule clock while no check runs."""
    WAKE.clear()
    end = time.time() + sec
    while True:
        now = time.time()
        if WAKE_DUE["at"] and now >= WAKE_DUE["at"]:  # 1.6.2 review: a wake a pilot's check floor put off
            WAKE_DUE["at"] = 0.0
            return
        left = end - now
        due = WAKE_DUE["at"] - now if WAKE_DUE["at"] else left
        if left <= 0 or WAKE.wait(max(0.0, min(left, due, WORKING_TICK_S))):
            return
        publish_working_flight()
        health_note_tick()  # 1.7.3: a read path's stop leaves the state note within a tick of its end



def sleep_announced(sec):
    """Sleep, publishing when the next pot check is due (sensor.flight_watcher_next_check)."""
    pub("next_check", datetime.fromtimestamp(time.time() + sec, timezone.utc).isoformat())
    sleep(sec)


def no_next_check():
    pub("next_check", "None")  # HA shows unknown: no check scheduled (paused/stopped)


# 1.6.2 review (account safety): on a pilot, FLICA logins are at least LOGIN_MIN_GAP_S apart whatever asks for one
# (Re-arm, un-pause, a re-login back-off, the end of a yield); only new FLICA details saved in Settings start one
# sooner. Details FLICA refused (the login form came back, not a load error) are kept as a hash (S flica_refused, never
# the values): while stopped_login_failed holds those same details, Re-arm logs in no more; saving new details in
# Settings lifts the block, and saving the same ones again gives one more try (as CrewTrac's refusal block, 1.6.1).
# 1.7.4: that hash is an HMAC-SHA256 with the pilot instance's own random key (flica_key), as CrewTrac's since 1.7.2: a
# bare sha256 of the details let anyone who could read the state test password guesses against it offline.
LOGIN_MIN_GAP_S = 600
FL_KEY_FILE = f"{DATA}/flica_hmac.key"  # 1.7.4: a pilot's FLICA block key, 32 random bytes, 0600, this instance only
FL_HMAC_V = "flica_hmac_v"  # S: 1 once the refusal record is keyed with it (the 1.7.4 migration ran)
FL_KEY_LOST = "flica_key_lost"  # S: the refusal's time when its key was lost with it on record: blocked until a save
_FLK = {"key": None}
_FLK_LOCK = threading.RLock()


def is_pilot():
    return ROLES.role(INSTANCE) == ROLES.PILOT


def _key_file_read(path):
    """1.7.2 (CrewTrac), 1.7.4 (FLICA): an instance's 32-byte HMAC key from its file, or None when there is none to
    use: missing, a link (O_NOFOLLOW: never followed), not a plain file, unreadable or not 32 bytes. A mode other than
    0600 is put back to 0600."""
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            return None
        if stat.S_IMODE(st.st_mode) != 0o600:
            os.fchmod(fd, 0o600)
        raw = os.read(fd, 64)
    except OSError:
        return None
    finally:
        os.close(fd)
    return raw if len(raw) == 32 else None


def _key_file_make(path, prefix):
    """A new random 32-byte key at path: written to a private temporary file beside it (mode 0600), synced, then moved
    into place (os.replace: a link or anything else at path is replaced, never written through). OSError on failure,
    with nothing left behind."""
    key = secrets.token_bytes(32)
    fd, tmp = tempfile.mkstemp(prefix=prefix, dir=os.path.dirname(path) or ".")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(key)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
    return key


def _flica_msg(o):
    return json.dumps(["flica", o.get("username") or "", o.get("password") or ""]).encode()


def _same_hash(a, b):
    """Two refusal hashes equal (compared as bytes: a stored value that is not plain text never raises)."""
    return bool(a) and bool(b) and hmac.compare_digest(str(a).encode(), str(b).encode())


def flica_legacy_hash(o=None):
    """The 1.6.2 to 1.7.3 refusal record (a bare sha256 of the details), read only when the record is keyed
    (flica_key: the 1.7.4 migration) and never stored again."""
    return hashlib.sha256(_flica_msg(OPTS if o is None else o)).hexdigest()


def flica_key():
    """1.7.4: the random 32-byte key of a pilot's FLICA refusal record (flica_creds_hash, HMAC-SHA256), in his own data
    folder (FL_KEY_FILE, mode 0600, read with O_NOFOLLOW), made when he first needs it (a refusal on record at the
    start, or FLICA's first refusal); never logged, exported, published or sent. The admin has no block, so no key
    (None). The first time a process has the key, the record on file is put right: an HMAC of the details in use is
    kept, a bare sha256 of them (1.7.3's, on the first 1.7.4 start or after a rollback) is keyed with its time kept,
    anything else is dropped (it blocks nothing and cannot be keyed without its details); the first time ever is
    marked (FL_HMAC_V) and logged with counts only. A key found gone or unreadable after that, with a refusal on
    record: no record can be matched any more, so the pilot stays blocked while stopped_login_failed until FLICA
    details are saved again in Settings (FL_KEY_LOST; flica_refused_at, flica_lift, settings_cmd), never one more
    login on its own. Raises OSError when no key can be made."""
    if not is_pilot():
        return None
    with _FLK_LOCK:
        if _FLK["key"] is not None:
            return _FLK["key"]
        key = _key_file_read(FL_KEY_FILE)
        made = key is None
        if made:
            key = _key_file_make(FL_KEY_FILE, ".flica_hmac.")
        _FLK["key"] = key
        first = S.get(FL_HMAC_V) != 1
        r = dict(S.get("flica_refused") or {})
        kept = dropped = 0
        if made and not first:  # records made with a key that is gone
            if r.get("hash"):
                S.pop("flica_refused", None)
                S[FL_KEY_LOST] = float(r.get("at") or 0) or time.time()
                log.info("the FLICA block key was lost with a refusal on record; no FLICA login until FLICA details "
                         "are saved again in Settings")
        elif r.get("hash"):
            new = hmac.new(key, _flica_msg(OPTS), hashlib.sha256).hexdigest()
            if _same_hash(r["hash"], new):
                kept = 1
            elif _same_hash(r["hash"], flica_legacy_hash()):
                S["flica_refused"] = {**r, "hash": new}
                kept = 1
                if not first:
                    log.info("a FLICA refusal kept as a bare hash (1.7.3) was keyed with this instance's own key")
            else:
                S.pop("flica_refused", None)
                dropped = 1
        if first:
            S[FL_HMAC_V] = 1
            if kept or dropped:  # a record was on file (none at a pilot's first refusal: nothing to say)
                log.info("FLICA refusal record keyed with this instance's own key (%d kept, %d dropped)", kept,
                         dropped)
        save_state(S)
        return key


def flica_key_start():
    """1.7.4: at a pilot's start with a FLICA refusal on record, its key is had (the 1.7.4 migration, or the key-lost
    rule) before anything compares the record. No record, no key: it is made at FLICA's first refusal."""
    if not is_pilot() or not (S.get("flica_refused") or {}).get("hash"):
        return
    try:
        flica_key()
    except OSError as e:  # flica_refused_at holds the block while no key can be had
        log.info("the FLICA block key could not be read or made (%s)", type(e).__name__)


def flica_creds_hash(o=None):
    """The refusal record's key of the FLICA user name and password in use: 1.7.4, an HMAC-SHA256 with this pilot
    instance's own key (flica_key); never the values, never a bare hash. None on the admin (no block, no key)."""
    key = flica_key()
    if key is None:
        return None
    return hmac.new(key, _flica_msg(OPTS if o is None else o), hashlib.sha256).hexdigest()


def login_wait(now=None):
    """Seconds until a pilot's next FLICA login may start (0 on the admin)."""
    if not is_pilot():
        return 0.0
    now = time.time() if now is None else now
    last = float(S.get("login_ts") or 0)
    if last > now + 60:  # the clock went back: a stale time never blocks for good
        return 0.0
    return max(0.0, last + LOGIN_MIN_GAP_S - now)


def flica_refused_at():
    """A pilot's block: the unix time FLICA refused the details now in use, while stopped_login_failed; else None.
    1.7.4: or, whatever details are in use, the refusal's time when its key was lost with it on record (FL_KEY_LOST),
    until FLICA details are saved again in Settings. The key is had first (flica_key may key or drop the record); while
    none can be had, the record holds the block (never one more login on a doubt)."""
    if not is_pilot() or S.get("machine") != "stopped_login_failed":
        return None
    h = None
    r = S.get("flica_refused") or {}
    if r.get("hash"):
        try:
            h = flica_creds_hash()
        except OSError as e:
            log.info("the FLICA block key could not be read or made (%s); the refusal on record holds",
                     type(e).__name__)
            return float(r.get("at") or 0)
    if S.get(FL_KEY_LOST):
        return float(S[FL_KEY_LOST])
    r = S.get("flica_refused") or {}  # read again: having the key may have keyed or dropped it
    return float(r.get("at") or 0) if _same_hash(r.get("hash"), h) else None


def flica_refused_note(at):
    if S.get(FL_KEY_LOST):  # 1.7.4: the record cannot be checked any more; only a save in Settings lifts the block
        return (f"FLICA refused a login at {hst_hm(at)} HST and that refusal can no longer be checked; save your FLICA "
                "details on the Settings tab again (the same ones or new ones) to try once more")
    return (f"FLICA refused these login details at {hst_hm(at)} HST; save new ones on the Settings tab "
            "(saving the same ones again gives one more try)")


def try_login(fl, reason):
    """Single attempt. Parks the watcher on anything but success."""
    S["login_ts"] = time.time()
    res = fl.login()
    if res == "ok":
        S["pot_urls"] = {}
        S.pop("flica_refused", None)
        S.pop(FL_KEY_LOST, None)
        pub("session", "ON")
        set_machine("hunting" if FLAGS["hunt"] else "idle", f"logged in ({reason})")
        return True
    pub("session", "OFF")
    if res == "blocked":
        set_machine("stopped_unexpected", "FLICA asked for captcha/MFA/password change during login")
    elif is_pilot() and not getattr(fl, "login_error", None):  # the form came back: FLICA refused these details
        at = time.time()
        try:
            S["flica_refused"] = {"hash": flica_creds_hash(), "at": at}
            S.pop(FL_KEY_LOST, None)  # this refusal's own record replaces one whose key was lost
        except OSError as e:  # 1.7.4: no key to keep the record with: blocked until a save in Settings all the same
            S.pop("flica_refused", None)
            S[FL_KEY_LOST] = at
            log.info("the FLICA block key could not be made (%s); no FLICA login until FLICA details are saved again "
                     "in Settings", type(e).__name__)
        log.info("FLICA refused the login (%s); no login with these details until others are saved", reason)
        set_machine("stopped_login_failed", flica_refused_note(at))
    else:
        set_machine("stopped_login_failed", f"one login attempt failed ({reason})")
    return False


def login_deferred(st, base_note=None):
    """1.6.2 review: True (after a WAKE-able wait with a note) when a pilot's next FLICA login must wait for
    LOGIN_MIN_GAP_S; the caller then loops back and asks again."""
    w = login_wait()
    if w <= 0:
        return False
    at = hst_hm(time.time() + w)
    note = (base_note or S.get("note") or "").split("; the FLICA login waits until")[0]
    set_machine(st, (note + "; " if note else "") + f"the FLICA login waits until {at} HST (at most one every "
                f"{LOGIN_MIN_GAP_S // 60} min)")
    sleep_announced(w)
    return True


# 1.6.2 review: on a pilot no check starts within PILOT_CHECK_FLOOR_S (his fastest hunt: 5 s since Ryan's 2026-11-10
# ranges, 120 s before) of the last one, whatever woke the loop; a hunt or pause change or Check now inside that time
# wakes it at the floor instead. His FLICA budget (100 loads an hour, gate.py) is what holds a fast hunt's pace.
PILOT_CHECK_FLOOR_S = FREQ_LIMITS["hunt_s"][0] if ROLES.role(INSTANCE) == ROLES.PILOT else 0
WAKE_DUE = {"at": 0.0}


def check_floor_wait(now=None, woken=False):
    """Seconds until a pilot's next check may start (0 on the admin). woken: count a wake already asked for too."""
    if not PILOT_CHECK_FLOOR_S:
        return 0.0
    now = time.time() if now is None else now
    last = max(float(S.get("check_started_ts") or 0), float(S.get("last_check_ts") or 0),
               float(S.get("wake_ts") or 0) if woken else 0.0)
    if last > now + 60:
        return 0.0
    return max(0.0, last + PILOT_CHECK_FLOOR_S - now)


def wake_check(why):
    """Wake the loop for a FLICA check now, or (a pilot inside his floor) at the floor: True when woken now."""
    w = check_floor_wait(woken=True)
    if w <= 0:
        S["wake_ts"] = time.time()
        return True
    due = time.time() + w
    if not WAKE_DUE["at"] or WAKE_DUE["at"] > due:
        if not WAKE_DUE["at"]:  # one line per put-off wake, not one per toggle
            log.info("%s: the next check starts at %s HST (at most one every %d s)", why, hst_hm(due),
                     PILOT_CHECK_FLOOR_S)
        WAKE_DUE["at"] = due
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
        if url and not (SUB.safe_get(url) and SM.safe_get(url)):
            log.info("detail %s: url refused by safe_get, skipped", ev.get("pairing"))
            url = None
        if url:
            page = fl.fetch(url)
            if classify(page) == "ok":
                d = parse_detail(page)
                DB.remember_crew(visible_text(page))  # 0.8.2: crew directory for name lookups
                if not DETAIL_PROBE["done"]:
                    DETAIL_PROBE["done"] = True
                    log.info("detail text %s: %s", ev.get("pairing"), page_log(visible_text(page)[:2500]))
                ev.update({k: v for k, v in d.items() if k == "captain" or not ev.get(k)})
                ev["detail_url"] = url
    except (GT.GateAbort, GT.GateSkip):
        raise  # 1.6.2 review: given up (Pause) or left out (a pilot's budget): the caller decides, nothing is cached
    except Exception as e:
        log.info("detail skipped for %s: %s", ev.get("pairing"), e)
    screen_row(ev)


def screen_row(ev):
    """The screens enrich() puts on a row after its detail GET (soft time, fit, vacation, blocked days, FAR, smart
    fields), alone: a row whose details a pilot's budget left out (1.7.1 review) is still screened, from what its list
    shows."""
    ev.setdefault("captain", "")
    st = soft_time(ev.get("credit"), ev.get("blk"))
    ev["soft"] = st or ""
    ev["fit"] = schedule_fit(ev)
    ev["vac"] = touches_vac(ev)
    ev["blocked"] = touches_blocked(ev)
    ev["far"] = far_for(ev)
    smart_fields(ev)  # FW-0042


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


def far_trips(ev, exclude=None):
    """FW-0039: ((new, mine), '') the pickup and Ryan's own line as far.py reads them (recall.pickup_trip with the
    pickup's block and duty periods; recall.line_records: his schedule items flown and to fly, their times and blocks
    from own_trips, and the days around the pickup no schedule month on file covers), or (None, why) when the pickup's
    dates, report or final arrival are not known. The FAR column (far_screen) and the 672 h block check (1.7.1,
    smart.block_672) read the same trips. exclude: 'TRIP|YYYY-MM-DD' of his own trip to leave out (a swap)."""
    s, e = _span(ev)
    if not s:
        return None, "pickup dates unknown"
    rep, arr = ev.get("report"), ev.get("arrive") or ev.get("last_arr")
    if not FAR.window(s, e, rep, arr):
        return None, "pickup report or final arrival not read yet"
    new = RC.pickup_trip(ev.get("pairing") or "pickup", s, e, rep, arr, hours(ev.get("blk")), _pickup_duties(ev, s))
    mine = RC.line_records(S.get("schedule") or {}, S.get("own_trips") or {}, s, e, local_now().date(), exclude)
    return (new, mine), ""


def far_screen(ev, exclude=None):
    """FW-0039: FAR 117 and PWA rest screen of a pot, Tradeboard or finds row against Ryan's own line, with the same
    rules as the Recall check (far.legality(): 117.25(e), 117.25(b), 117.23(b)(1) and now 117.23(c)(1)/(2), the FDP
    60 h in 168 h and 190 h in 672 h; PWA 10.E.1.a, 2.19.b), per duty period of his trips and of the pickup.
    {far, why}: far is the column ('OK', 'OK (CBA rest 10:30)', 'Conflict', 'Rest 8:00 before · FDP 65h/168h', or
    '?' when the pickup's report or final arrival is not known yet or a check needs data not on file: never OK);
    why cites the rule behind it. exclude: 'TRIP|YYYY-MM-DD' of his own trip to leave out (a swap)."""
    try:
        trips, why = far_trips(ev, exclude)
        if not trips:
            return {"far": "?", "why": why}
        r = FAR.screen(*trips)
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


# FW-0042: the smart push fields every row with fit and far carries (pot, Tradeboard, close-in, finds, the
# event/new_pairing payload); each '' without smart.json. 1.7.1: b672 ('97:59', the block in the 672 h ending at the
# pickup's release) and b672_ok (True at most 98:00, False over, '' unknown), smart.block_672
SMART_FIELDS = ("comm", "comm_why", "value", "month_rule", "b672", "b672_ok")
# Off the pot and Tradeboard sensors: far_why (long) and the smart fields, which no card reads from those sensors yet
# (the pot_table macro and the schedule card show neither); on them they would cost rows under cap_attrs' 12 KB. The
# DB, the finds month files, last_new and event/new_pairing keep all of them; the finds sensor carries FINDS_ATTR_KEYS
# only, so none of them either. Showing Comm or Value in the pot_table macro needs a Watcher release that takes them
# out of SENSOR_DROP for pot/state (minding the 12 KB cap) as well as the HA macro edit.
SENSOR_DROP = ("far_why",) + SMART_FIELDS
# FW-0042 review: stations a last leg into HNL comes from without clearing customs (the US stations of pot.TZ; a
# pilot's smart.json "domestic" adds more). Any other origin means a release 30 min after block-in (PWA 2.19.b), the
# one the commute HOME check uses; an origin not on file is judged both ways (smart.comm, far.py's sure / worst rule).
US_STATIONS = frozenset(("HNL", "OGG", "KOA", "ITO", "LIH", "ANC", "LAX", "SFO", "SEA", "SAN", "OAK", "SMF", "LAS",
                         "PDX", "SJC", "ONT", "LGB", "PHX", "SLC", "DEN", "ORD", "DFW", "AUS", "MSP", "IAH", "JFK",
                         "BOS", "MCO", "IAD", "ATL", "MIA", "EWR"))


def report_release(ev):
    """FW-0042: (report, release) of a pot / Tradeboard / close-in / finds row as naive HST datetimes, from the best on
    file: report = the row's check-in (its pairing page), else the pairings package's report (BASE REPT), else 1:00
    before the first duty's departure (its duty periods: pairing page, details cache or the bid period's package; PWA
    2.19.b), else 1:00 before the pot row's first departure; release = the final block-in ('arrive' on the pot row,
    'last_arr' from the pairing page) on the last day, else the last duty's, plus 15 min (PWA 2.19.b, as far.window;
    a customs release is release_customs()'s to judge). (None, None) when either is unknown."""
    s, e = _span(ev)
    if not s:
        return None, None
    base = datetime.combine(s, datetime.min.time())
    rep_t, arr_t = FAR._t(ev.get("report")), FAR._t(ev.get("arrive") or ev.get("last_arr"))
    rep = datetime.combine(s, rep_t) if rep_t else None
    rel = datetime.combine(e or s, arr_t) + FAR.DEBRIEF if arr_t else None
    if rep is None:  # the pairings package's BASE REPT (pairing file column report)
        try:
            pr = FAR._t(RC.package_entry(ev.get("pairing"), s, pkg_details_for).get("report"))
            rep = datetime.combine(s, pr) if pr else None
        except Exception:
            rep = None
    if rep is None or rel is None:
        try:
            duties = _pickup_duties(ev, s)
            if duties:
                if rep is None:
                    rep = base + timedelta(minutes=min(int(x["dep"]) for x in duties) - 60)
                if rel is None:
                    rel = base + timedelta(minutes=max(int(x["arr"]) for x in duties)) + FAR.DEBRIEF
        except (KeyError, TypeError, ValueError):
            pass
    if rep is None and FAR._t(ev.get("depart")):
        rep = datetime.combine(s, FAR._t(ev.get("depart"))) - timedelta(hours=1)
    if rep is None or rel is None:
        return None, None
    while rel <= rep:  # a block-in printed for the day after the end date (as far.window)
        rel += timedelta(days=1)
    return rep, rel


def last_origin(ev):
    """The origin of the row's last leg (the one into HNL): the route from its pairing page ('HNL-LAX-HNL' -> 'LAX'),
    else the bid period's pairings package route; '' when neither is on file."""
    route = ev.get("route") or ""
    if not route:
        try:
            s, _ = _span(ev)
            route = (RC.package_entry(ev.get("pairing"), s, pkg_details_for).get("route") or "") if s else ""
        except Exception:
            route = ""
    parts = [p.strip().upper() for p in str(route).split("-") if p.strip()]
    return parts[-2] if len(parts) >= 2 else ""


def release_customs(ev, cfg=None):
    """FW-0042 review: whether the row's release is 30 min after block-in, not 15 (PWA 2.19.b, clearing customs), as
    far.py's sure / worst rule needs it: True when its last leg comes from a station outside the US, False for a known
    US origin (US_STATIONS and the pilot's smart.json "domestic"), None when the origin is not on file (smart.comm then
    judges HOME at both releases: a No needs the sure one to fail)."""
    o = last_origin(ev)
    if not o:
        return None
    return o not in (US_STATIONS | set((cfg or {}).get("domestic") or ()))


BID_PERIODS = {"at": 0.0, "bounds": {}, "files": {}}  # crewidx.period_for's cache of the pairing files' bounds
BID_PERIODS_TTL_S = 600


def bid_period_of(d):
    """FW-0042 review: the bid month ('YYYY-MM') a day belongs to by the pairing files' period bounds, the ones the
    crew index and the cards use (crewidx.period_for: Dec 1, 2026 is November's, whose period runs Nov 1 to Dec 1),
    or None when no pairing file speaks for it (no file for that month, and none made it another month than the
    calendar's): smart.bid_month then reads the bid month off the schedule pages. The bounds are cached 10 min."""
    if time.time() - BID_PERIODS["at"] > BID_PERIODS_TTL_S:
        BID_PERIODS.update(at=time.time(), bounds={}, files={})
    mon = CI.period_for(CARD_PAIRINGS, d.isoformat(), BID_PERIODS["bounds"])
    if mon not in BID_PERIODS["files"]:
        BID_PERIODS["files"][mon] = os.path.exists(os.path.join(CARD_PAIRINGS, f"pairings_{mon}.json"))
    return mon if mon != f"{d:%Y-%m}" or BID_PERIODS["files"][mon] else None


def block_672(ev):
    """1.7.1 (FW-0042, Ryan's rule of Nov 9): smart.block_672 of a row, on the FAR column's own trips (far_trips):
    {tag, b672, b672_ok}; '672 ? (times not read)' when the pickup's report or final arrival is not known."""
    try:
        trips, _ = far_trips(ev)
    except Exception as ex:
        log.info("672 h block check skipped for %s: %s", ev.get("pairing"), ex)
        trips = None
    return SMART.block_672(*(trips or (None, None)))


def smart_fields(ev):
    """FW-0042: comm, comm_why (Hark's commute check, PWA 26.QQ.2), value (credit x rate, dollars), month_rule (the
    bid month's line / reserve rules, each day in its bid period: bid_period_of) and, 1.7.1, b672 / b672_ok (the block
    in the 672 h ending at the pickup's release against the company's 98 h buffer, block_672; its tag is in month_rule
    too) on a row, after its fit and far are set. All '' without smart.json, so nothing else changes. Never raises (a
    malformed smart.json loads as none). The HOME leg uses the customs release (block-in + 30 min, PWA 2.19.b) for a
    last leg from outside the US, and both releases when the origin is not on file (release_customs)."""
    out = dict.fromkeys(SMART_FIELDS, "")
    try:
        cfg = SMART.load(SMART_FILE, warn=log.info)
        if cfg:
            rep, rel = report_release(ev)
            out["comm"], out["comm_why"] = SMART.comm(rep, rel, cfg, customs=release_customs(ev, cfg))
            out["value"] = SMART.value(ev.get("credit"), cfg)
            b = block_672(ev)
            out["b672"], out["b672_ok"] = b["b672"], b["b672_ok"]
            s, e = _span(ev)
            out["month_rule"] = SMART.month_rule(s, e, ev.get("credit"), ev.get("fit"), ev.get("far"),
                                                 S.get("schedule") or {}, cfg, period=bid_period_of, b672=b["tag"])
    except Exception as ex:
        log.info("smart fields skipped for %s: %s", ev.get("pairing"), ex)
        out = dict.fromkeys(SMART_FIELDS, "")
    ev.update(out)
    return out


def sensor_row(r):
    """FW-0042: a pot / Tradeboard row as its sensor carries it: no far_why and none of the smart fields (SENSOR_DROP),
    so the sensor rows are byte for byte what they were in 1.4.12 and a busy month keeps as many rows under the 12 KB
    cap. Showing them in the pot_table macro or the schedule card needs a Watcher release that puts them back on
    these sensors (SENSOR_DROP), not only the HA edit."""
    return {k: v for k, v in r.items() if k not in SENSOR_DROP}


OWN_PER_CHECK = 3
FULL_MAX = 12  # Check now: at most this many detail GETs per kind, still 1.5-3.5 s apart


def own_trip_times(fl, full=False):
    """Read only (0.3.8): check-in, final arrival and block of Ryan's own trips from their pairing
    pages, cached per trip and start date, so the FAR column can measure rest."""
    own = S.setdefault("own_trips", {})
    # 1.7.2 (Ryan, Nov 13): first, with no FLICA load and before the trips gone from the schedule are pruned below, a
    # PAYP keeps the removed trip's credit (payp_refresh); a read stopped half way still leaves it on file
    keep, n = payp_refresh(own), 0
    for it in _sched_items():
        trip = it.get("trip") or ""
        if not PAIRING_RE.match(trip):
            continue
        k = f"{trip}|{it['start']}"
        keep.add(k)
        today = local_now().date().isoformat()
        # FW-0067: the legs only matter to a trip that can still be the working or next one (the working leg can be
        # yesterday's last leg until 2 h after its block-in); an ended trip is not read again for them
        yesterday = (local_now() - timedelta(days=1)).date().isoformat()
        old = k in own and own[k] and ("credit" not in own[k] or "duties" not in own[k] or "crew" not in own[k]
                                             or (own[k].get("duties") and "blk" not in own[k]["duties"][0])
                                             or ("legs" not in own[k] and it["end"] >= yesterday))  # cached before 0.4.9 / 0.4.15 / 0.4.17 / 0.4.19 / 1.4.9
        # 0.6.1 (Ryan): block and credit move once a trip flies (actuals). Re-read a trip in progress every 6 h
        # and a finished trip once more the day after it ends, so completed trips show their final times.
        cur = own.get(k) or {}
        if k in own and cur and it["start"] <= today:
            read_at = cur.get("read_at") or ""
            if it["end"] >= today and read_at[:13] < (local_now() - timedelta(hours=6)).isoformat()[:13]:
                old = True
            elif it["end"] < today and not cur.get("final"):
                old = True
        if (k in own and not full and not old) or n >= (FULL_MAX if full else OWN_PER_CHECK) or not BRK.allow("pairing"):
            continue  # 1.6.2: nothing is read while pairing pages are stopped (the cached times stay)
        # FW-0067: paced before every read, the first too (the schedule check may have just loaded a page) ...
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
                    txt = visible_text(page)  # parse_detail's text, lower case (parse_legs ignores case)
                    ids = crew_ids(txt)  # 0.4.17: roster with employee numbers for the card
                    own[k]["crew"] = [with_ids(f"{pos} {name}", ids) for pos, name in (d.get("crew") or [])]
                    # FW-0067: every leg (flight, from, to, times) for the working flight; kept in the state, not
                    # on the own_trips sensor (publish_own_trips)
                    own[k]["legs"] = parse_legs(txt)
                    log.info("own trip %s: report %s, in %s, blk %s", k, d["report"], d["last_arr"],
                             d.get("blk"))
                else:
                    log.info("own trip %s: no times on the pairing page", k)
                    own[k] = {}
        except GT.BreakerOpen:  # 1.6.2 review: given up or left out by the gate: not a failed read
            raise
        except Exception as e:
            log.info("own trip %s skipped: %s", k, e)
    for k in [k for k in own if k not in keep]:
        own.pop(k)
    if n:
        save_state(S)
        time.sleep(random.uniform(1.5, 3.5))  # ... and after the last, before the check loads the pot
    publish_own_trips()


def payp_refresh(own=None):
    """1.7.2 (Ryan, Nov 13: "My LAS trip today was cancelled and PAYP pay protected. Why did your pay calculations
    drop?"): every PAYP item on the schedule gets an own trips record PAYP|<start> holding the removed trip's credit
    (PWA Definitions 57: the pilot retains the Pay and Credit of a Flight Grouping removed from his schedule), so the
    schedule card, the versions and every pay figure count it; block 0:00 (never in the block total, Block Avail, FAR
    117 or the 98/672 checks: nothing is flown). versions.payp_entries() finds the removed trip: an own trips record no
    longer on the schedule over the PAYP's days (call this before they are pruned), else the newest stored version
    before the PAYP; else no record (the card estimates it from FLICA's month credit). Kept while the PAYP item is on
    the schedule (or, PWA 4.R.1, while a trip added over all its days is); pruned with it. Each instance does this for
    its own schedule. Pure bookkeeping, never a FLICA load. Returns the PAYP keys to keep (every one on file when this
    step fails)."""
    own = S.setdefault("own_trips", {}) if own is None else own
    try:
        got = VER.payp_entries(_sched_items(), own, lambda mk: DB.get(f"sched_versions:{mk}") or [], PAIRING_RE.match)
    except Exception as e:  # never stops the trip reads; what is on file stays while its PAYP is on the schedule
        log.info("pay protection skipped: %s", e)
        return {k for k in own if k.startswith(f"{VER.PAYP}|")}
    moved = False
    for k, rec in got.items():
        if own.get(k) != rec:
            own[k] = rec
            moved = True
            log.info("pay protection %s: credit %s kept from %s (%s)", k, rec["credit"], rec["protected"], rec["src"])
    if moved:
        save_state(S)
    return set(got)


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


ENDS_FIX_V = 1  # trip end: bump to run repair_ends() over the stored versions again


def repair_trip_ends():
    """Trip end, once: versions and the schedule on file stored while the item builder cut a trip short when the next
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
        log.info("trip end repair: %d stored schedule version(s) / month(s) got the trip end their days list gives", n)
    return n


def versions_months(months):
    """1.6.2: the months whose versions are published: every month FLICA's schedule was read for, plus any month from
    last month to two ahead whose first version is the PBS award (an award upload before any FLICA read of it: a pilot's
    11.001 was stored but never shown). No version is made here; only what is on file is published."""
    out = set(months or {})
    today = local_now()
    for i in range(-1, 3):
        y, m = divmod(today.year * 12 + today.month - 1 + i, 12)
        mk = f"{y:04d}-{m + 1:02d}"
        if mk not in out and ((DB.get(f"sched_versions:{mk}") or [{}])[0] or {}).get("award"):
            out.add(mk)
    return out


def versions_check(force_pub=False):
    """0.9.0 (Ryan): a new schedule version (MM.NNN) every time anything on a month changes. A month whose new
    pairings have no block / credit read yet waits up to 2 h for them, so one change makes one version."""
    try:
        repair_trip_ends()
    except Exception as e:  # never stops the versions; tried again next time
        log.info("trip end repair skipped: %s", e)
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
        if has("one_writer") and not S.get("ver_seeded"):  # 0.9.0: Nov 2-4 versions rebuilt from HA's recorder (before the Watcher kept versions); Ryan only
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
            pubm = versions_months(months)
            full = VER.published(DB, pubm)
            key, rev = write_list_file("versions", {"months": full})
            pub("schedule_versions", {"count": sum(len(DB.get(f"sched_versions:{m}") or []) for m in pubm),
                                      "months": VER.summary(full), "file_key": key, "rev": rev, "at": now_iso()})
            S["ver_published"] = True
            if made:
                pub("event/schedule_version", {"versions": [v for _, v in made], "at": now_iso()}, retain=False)
    except Exception as e:
        log.info("schedule versions skipped: %s", e)


# FW-0062: where the Web UI saves every upload (web.UPLOAD_DIR). The Web UI runs on the default instance only, so a
# second pilot's instance reads the pairings package text and the seniority list from here too.
UPLOADS_SHARED = "/share/flight_watcher/uploads"
# FW-0066 (1.4.8): the award, the pairings package and the seniority list are base-wide, and either instance may save
# an upload sent in chunks over MQTT, so every instance reads the one shared folder (a second pilot's instance read
# /share/flight_watcher/<name>/uploads before, which nothing ever wrote to). uploads_check's marks stay per instance.
UPLOADS = UPLOADS_SHARED
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
    if not has("one_writer"):
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
    most every 10 min. 1.6.0 (FW-0061): a portal pilot's prefs.json first (pref_get: None on any other instance)."""
    if TAX["pct"] is None or time.time() - TAX["at"] > TAX_CACHE_S:
        tot = 0.0
        for name, dflt in (("federal", 22.0), ("state", 0.0)):
            v = pref_get(f"{name}_tax_pct")
            if v is None and portal_on():  # 1.6.2 (item 12): a portal pilot has no HA helpers: never read them
                v = dflt
            try:
                tot += float(ha_state(f"input_number.{T}_{name}_tax_pct") if v is None else v)
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


UPLOADS_LOCK = threading.RLock()  # 1.7.2: the main loop and the uploads janitor both run uploads_check


def uploads_check():
    """0.9.1 (Ryan): parse the monthly PDFs uploaded on the Web UI (text copies made by pdftotext). Pairings
    package -> the schedule card's pairing file (www/flight-watcher/pairings_<YYYY-MM>.json) and trip details; award ->
    this month's version .001. Each file is handled again only when it changes. No FLICA traffic.
    FW-0062: the seniority list is parsed by the Web UI as it is uploaded; seniority_refresh re-reads it after a
    parser change. 1.7.2 (FW-0066): a file whose generation changed (a pilot's upload, the admin's approve or remove:
    upload_gens_check) is read again, or forgotten when it is gone. Only the shared uploads folder is read: never the
    quarantine folder (a pilot's copy waiting for the admin)."""
    with UPLOADS_LOCK:
        _uploads_check()


def _uploads_check():
    try:
        upload_gens_check()
    except Exception as e:  # noqa: BLE001
        log.info("upload changes not followed: %s", type(e).__name__)
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
                    pv = S.setdefault("pilotver_awards", {})
                    if det and pv.get(f) != sig:  # FW-0069: an award after a looked-up pilot's first version is his
                        pilotver_awards(month, text, det)  # .001 now (once per file version, even while this waits)
                        pv[f] = sig
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


def sen_value(v, strict=True):
    """1.6.2 (item 10): a seniority number as recall/act may set it: an int 1..99999 (recall.SEN_MAX); with strict
    off (a list Hark posts), an all-digit text too. None for anything else."""
    if isinstance(v, bool):
        return None
    if not strict and isinstance(v, str) and re.fullmatch(r"\d{1,5}", v.strip()):
        v = int(v.strip())
    return v if isinstance(v, int) and 1 <= v <= RC.SEN_MAX else None


_AWARD_SEN = {}  # (path, mtime, emp) -> the pilot's seniority number on that award, or None


def award_sen(path, emp):
    """1.6.2: the pilot's seniority number on one PBS award text ('SSSSS / EMP' line, seniority.AWARD_PILOT_RE), by
    his own employee number; None when he is not on it. Cached by the file's time."""
    try:
        key = (path, os.path.getmtime(path), emp)
    except OSError:
        return None
    if key not in _AWARD_SEN:
        got = None
        try:
            for ln in open(path, errors="replace"):
                m = SEN.AWARD_PILOT_RE.match(ln)
                if m and m["emp"].lstrip("0") == emp:
                    got = sen_value(int(m["sen"]))
                    break
        except OSError:
            pass
        _AWARD_SEN[key] = got
    return _AWARD_SEN[key]


def own_seniority():
    """1.6.2 (item 10): (seniority number, source) of this instance's own pilot from the files every instance already
    has, by his own employee number (S['own_emp']): the PBS award of the current month or the newest before it
    ('award YYYY-MM'), then a later one, else the shared seniority list ('seniority list'). (None, '') when neither
    names him."""
    emp = re.sub(r"\D", "", str(S.get("own_emp") or "")).lstrip("0")
    if not emp:
        return None, ""
    try:
        names = sorted(f for f in os.listdir(UPLOADS) if re.fullmatch(r"\d{4}-\d{2}_award\.txt", f))
    except OSError:
        names = []
    cur = local_now().strftime("%Y-%m")
    for f in [f for f in reversed(names) if f[:7] <= cur] + [f for f in names if f[:7] > cur]:
        sen = award_sen(os.path.join(UPLOADS, f), emp)
        if sen:
            return sen, f"award {f[:7]}"
    data = seniority_data()
    rec = SEN.find(data, emp) if data else None
    sen = sen_value((rec or {}).get("sen"), strict=False) if rec else None
    return (sen, "seniority list") if sen else (None, "")


def recall_me(with_source=False):
    """Ryan's recall settings: {sen, seat, o75_months {YYYY-MM: true | false}} (1.4.6 review: Over 75 eligibility,
    PWA 22.G.2.d, is per month; the old single 'o75' flag defaulted to eligible and is no longer used). 1.6.2 (item
    10): the number typed on the tab wins; when none is (or what is stored is not a number from 1 to 99999) it comes
    from the award or the seniority list (own_seniority). with_source: (me, 'typed' | 'award YYYY-MM' |
    'seniority list' | '')."""
    me = {"sen": None, "seat": "FO", "o75_months": {}, **(DB.get("recall_me") or {})}
    me.pop("o75", None)
    if not isinstance(me.get("o75_months"), dict):
        me["o75_months"] = {}
    me["sen"], src = sen_value(me.get("sen"), strict=False), "typed"
    if me["sen"] is None:
        me["sen"], src = own_seniority()
    return (me, src) if with_source else me


def recall_me_set(new, strict=True):
    """Merge a {me: {...}} change into recall_me: sen, seat, and o75_months {YYYY-MM: true | false | null} (null
    forgets that month's answer). Anything else is ignored. 1.6.2 (item 10): sen only as an int 1..99999 (or null:
    forget the typed one, so the award's or the list's applies; strict off also takes all-digit text), seat only FO or
    CA; anything else is left as it was (logged, the value not)."""
    if not isinstance(new, dict):
        return
    cur = {k: v for k, v in (DB.get("recall_me") or {}).items() if k != "o75"}
    if "sen" in new:
        v = sen_value(new["sen"], strict)
        if v is not None or new["sen"] is None:
            cur["sen"] = v
        else:
            log.info("recall: seniority # not taken: not a whole number from 1 to %d", RC.SEN_MAX)
    if "seat" in new:
        seat = str(new["seat"] or "").upper()
        if seat in ("FO", "CA"):
            cur["seat"] = seat
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
    FAR 117) and kept in the DB.
    1.7.1 (F#75): the same day again (the admin's forward and Ryan's HA automation both sending it) changes nothing: it
    keeps the time it first came in ('at', the card's 'received'), and no miss is counted or pushed twice (recall_eval
    keys its drafts by row). On the admin, the days it took go on to every pilot's Watcher (recall_forward).
    1.7.1 (Ryan, Nov 11, the recall history replay): on a pilot, a day marked "replay": true (the admin's history,
    recall_replay_tick) is taken only when this Watcher holds no list for that date (a day it holds is never touched, so
    a replay twice changes nothing); it keeps the admin's 'at' (when the list first came in) and its "replay" mark, is
    judged and shown like any day, and raises no alert or push (recall_eval, publish_recall). One log line a replay.
    The mark means nothing on the admin (its lists come from Hark) and is never forwarded."""
    try:
        d = json.loads(payload or "{}")
        days = d if isinstance(d, list) else [d]
        took, replayed, held = [], [], 0
        pilot = ROLES.role(INSTANCE) != ROLES.ADMIN
        with RECALL_LOCK:
            if isinstance(d, dict) and d.get("me"):
                if ROLES.role(INSTANCE) == ROLES.ADMIN:
                    recall_me_set(d["me"], strict=False)
                else:  # 1.6.2: a forwarded list never sets a pilot's own seniority (only his tab, recall/act, does)
                    log.info("recall list: its 'me' ignored on a pilot instance")
            allr = DB.get("recall_days") or {}
            for day in days:
                dk = str(day.get("date") or "")[:10]
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", dk):
                    continue
                new = {"date": dk, "file": day.get("file") or ("ok" if day.get("rows") else "blank"),
                       "rows": day.get("rows") or []}
                if pilot and day.get("replay") is True:  # 1.7.1: the admin's history, once
                    if dk in allr:
                        held += 1
                        continue  # a day this Watcher holds stays exactly as it is
                    allr[dk] = {**new, "at": replay_at(day.get("at")), "replay": True}
                    replayed.append(dk)
                    continue
                took.append({k: v for k, v in day.items() if k not in ("me", "replay", "at")})
                old = allr.get(dk) or {}
                if {k: old.get(k) for k in new} == new:
                    continue  # 1.7.1 (F#75): the same list again: its first 'at' stays
                allr[dk] = {**new, "at": now_iso()}
            DB.put("recall_days", dict(sorted(allr.items())[-120:]))
            recall_eval(notify=True)
        if replayed or held:
            log.info("recall history from the admin: %d day%s taken (%s to %s), %d already held; judged and shown, "
                     "no alert or push for them", len(replayed), "" if len(replayed) == 1 else "s",
                     min(replayed) if replayed else "-", max(replayed) if replayed else "-", held)
        if took and ROLES.role(INSTANCE) == ROLES.ADMIN:
            recall_forward(took)
    except Exception as e:
        log.info("recall list skipped: %s", e)


def pilot_prefixes():
    """1.7.1 (F#75): the MQTT prefixes of the pilots this add-on runs besides the admin (flight_watcher_<name>), by
    run.py's own rules on the add-on options (`pilots`, else `second_pilot`; a name it leaves out is not here). Its
    log lines about a left-out name are not repeated here (run.py says them at start)."""
    import contextlib
    import io
    import run as RUNNER
    with contextlib.redirect_stdout(io.StringIO()):
        return [f"flight_watcher_{n}" for n in RUNNER.pilot_names(OPTS)]


def replay_at(v):
    """1.7.1: the 'at' a replayed day keeps: the admin's (when that list first came in), when it is an ISO time no
    later than now; else now."""
    try:
        t = datetime.fromisoformat(str(v))
        if t.tzinfo and t <= datetime.now(timezone.utc) + timedelta(minutes=5):
            return str(v)[:40]
    except (TypeError, ValueError):
        pass
    return now_iso()


def recall_forward(days, replay=False, prefixes=None):
    """1.7.1 (F#75): the admin hands each recall list it took to every pilot's Watcher (<prefix>/recall/set, qos 1,
    not retained) itself, so a pilot's lists no longer hang on a second action in Ryan's HA automation that fails
    silently. Never its 'me' (a pilot's own seniority is his tab's). A pilot takes the same day again as a no-op, so
    the HA forward, while it is still there, does no harm. A pilot forwards nothing. replay (recall_replay_tick): each
    day goes marked "replay": true, to prefixes only (default every pilot)."""
    if ROLES.role(INSTANCE) != ROLES.ADMIN or MQ is None:
        return 0
    body = json.dumps([{**d, "replay": True} for d in days] if replay else days)
    n = 0
    for prefix in (pilot_prefixes() if prefixes is None else prefixes):
        try:
            MQ.publish(f"{prefix}/recall/set", body, qos=1, retain=False)
            n += 1
        except Exception as e:  # noqa: BLE001 (one pilot's forward never stops the others)
            log.info("recall list not forwarded to %s: %s", prefix, type(e).__name__)
    if n and not replay:
        log.info("recall list (%d day%s) forwarded to %d pilot Watcher%s", len(days), "" if len(days) == 1 else "s",
                 n, "" if n == 1 else "s")
    return n


# 1.7.1 (Ryan's yes, Nov 11): the admin's recall history replayed once to each pilot's Watcher. Ryan's instance held
# the lists from Oct 30 on; a pilot's Watcher (James's started Nov 10) got only the lists that came after it started.
RECALL_REPLAY = "recall_replay_done"  # DB on the admin: {pilot prefix: {at, days}}, one entry per pilot replayed to
RECALL_REPLAY_DELAY_S = 120  # after the admin's start: the pilots' Watchers (started by run.py too) have subscribed
RECALL_REPLAY_PART = 20  # days a message
_REPLAY = {"since": time.time(), "sent": {}, "waited": set()}
# 1.7.1 review: every Watcher's MQTT session is clean and the replay is not retained, so a replay published while the
# pilot's Watcher is down (a Settings save restarts it, a crash, a broker reconnect) is dropped by the broker without
# an error. The admin reads each pilot's own availability, <prefix>/status (retained; "online" from his on_connect, the
# broker's will sets "offline" when his connection ends, os._exit and SIGTERM included), and sends his replay only while
# it has read "online" for RECALL_REPLAY_SETTLE_S (his subscriptions follow his "online"). It marks the replay done (DB
# RECALL_REPLAY) only once he stayed online RECALL_REPLAY_CONFIRM_S after the send (past the broker's keepalive
# window); if he went offline or restarted in that time, the replay goes again when he is back (a replay twice
# changes nothing on him). Never a command: the payload is only compared with "online", and a pilot's portal cannot write it.
PILOT_UP = {}  # admin only: pilot prefix -> time.time() its status last turned "online"; None or absent: not online
RECALL_REPLAY_SETTLE_S = 30
RECALL_REPLAY_CONFIRM_S = 120


def pilot_status_subs():
    """The admin's subscriptions to its pilots' availability topics (1.7.1 review, recall_replay_tick), outside
    roles.subscriptions: no command, nothing in the portal contract. A pilot subscribes to none. On every (re)connect
    the counts start again (PILOT_UP cleared): a restart missed while the admin was offline then counts as one."""
    if is_pilot():
        return []
    PILOT_UP.clear()
    return [(f"{p}/status", 1) for p in pilot_prefixes()]


def pilot_status_in(topic, payload):
    """A pilot Watcher's availability, read as data (pilot_status_subs): "online" starts his count (an "online" again,
    as the retained copy on a reconnect, keeps it), anything else stops it. True when the topic is one of them."""
    p = str(topic)[:-len("/status")] if str(topic).endswith("/status") else ""
    if not p or p == T or is_pilot() or p not in pilot_prefixes():
        return False
    text = payload.decode("utf-8", "replace") if isinstance(payload, bytes) else str(payload or "")
    if text.strip() == "online":
        PILOT_UP[p] = PILOT_UP.get(p) or time.time()
    else:
        PILOT_UP[p] = None
    return True


def recall_replay_tick(now=None):
    """1.7.1: once per pilot (DB RECALL_REPLAY), the admin sends every recall day it stores (date, file and rows only:
    never its 'me', verdicts or CCR drafts) to that pilot's Watcher with recall_forward, marked replay. The pilot takes
    only the days it holds no list for (recall_cmd), judges them against his own line and shows them on his Recall/O75
    tab, with no alert or push; a replay twice changes nothing there. Runs from the uploads janitor (once a minute) on
    the admin only, RECALL_REPLAY_DELAY_S after its start and while MQTT is up; a pilot added later gets his replay
    then. 1.7.1 review: sent only while the pilot's Watcher is online (PILOT_UP), done only once it stayed online
    RECALL_REPLAY_CONFIRM_S after the send, else sent again. A publish that fails is tried again the next minute.
    Returns the prefixes the replay was sent to on this tick."""
    if ROLES.role(INSTANCE) != ROLES.ADMIN or MQ is None:
        return []
    now = time.time() if now is None else now
    if now - _REPLAY["since"] < RECALL_REPLAY_DELAY_S or not getattr(MQ, "is_connected", lambda: True)():
        return []
    done = dict(DB.get(RECALL_REPLAY) or {})
    todo = [p for p in pilot_prefixes() if p not in done]
    if not todo:
        return []
    days = None
    sent, confirmed = [], []
    pend = _REPLAY["sent"]
    for p in todo:
        up = PILOT_UP.get(p)
        if not up or now - up < RECALL_REPLAY_SETTLE_S:
            if p not in _REPLAY["waited"]:
                _REPLAY["waited"].add(p)
                log.info("recall history replay to %s waits until its Watcher is online", p)
            continue
        was = pend.get(p)
        if was and was["up"] == up:  # sent while this same connection was up: done once it stayed up long enough
            if now - was["at"] >= RECALL_REPLAY_CONFIRM_S:
                done[p] = {"at": now_iso(), "days": was["days"]}
                confirmed.append((p, was))
                pend.pop(p, None)
            continue
        if was:
            log.info("recall history replay to %s: its Watcher restarted after the send; sending it again", p)
        if days is None:
            with RECALL_LOCK:
                allr = DB.get("recall_days") or {}
                days = [{"date": dk, "file": d.get("file") or "", "rows": d.get("rows") or [], "at": d.get("at") or ""}
                        for dk, d in sorted(allr.items()) if isinstance(d, dict)]
        # in parts of RECALL_REPLAY_PART days, so no one message grows with the history kept (120 days)
        parts = [days[i:i + RECALL_REPLAY_PART] for i in range(0, len(days), RECALL_REPLAY_PART)]
        if not all(recall_forward(part, replay=True, prefixes=[p]) for part in parts):
            continue
        pend[p] = {"at": now, "up": up, "days": len(days),
                   "span": f"{days[0]['date']} to {days[-1]['date']}" if days else "-"}
        sent.append(p)
    if confirmed:
        DB.put(RECALL_REPLAY, done)
        for p, was in confirmed:
            log.info("recall history replayed once to %s: %d stored day%s (%s), marked replay: no alert or push there",
                     p, was["days"], "" if was["days"] == 1 else "s", was["span"])
    if sent:
        log.info("recall history sent to %s; marked done once its Watcher stays online %d s", ", ".join(sent),
                 RECALL_REPLAY_CONFIRM_S)
    return sent


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
                if v.get("missing"):  # 1.6.2 (item 10): no CCR draft, no alert while his seniority or line is unknown
                    continue
                acts[vid] = {"status": "new", "narrative": RC.narrative(v, me, S.get("own_name") or "", S.get("own_emp") or ""),
                             "at": now_iso(), "missed_sent": False}
                fresh.append(v)
            elif a.get("status") in ("new", "confirmed") and not a.get("approved_at") and not v.get("missing"):
                # 1.6.2: the Watcher's own text until it is approved (edits reach it only with approve): it follows
                # the row, so a number or a line that came in later is in it
                a["narrative"] = RC.narrative(v, me, S.get("own_name") or "", S.get("own_emp") or "")
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
        # 1.7.1: a replayed day (the admin's history, recall_cmd) is judged and shown, never pushed, now or later
        quiet = {v["id"] for day in allr.values() if day.get("replay") for v in day["verdicts"]}
        if notify:
            push = list(fresh) + [v for vid, v in live.items() if v not in fresh and v["verdict"] == "MISSED"
                                  and vid in acts and acts[vid].get("missed_sent") is False
                                  and acts[vid].get("status") in RECALL_OPEN]
            push = [v for v in push if v["id"] not in quiet]
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
    if not has("hark_ccr"):
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
            if a and a.get("status") != "superseded" and has("hark_ccr"):
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
    """1.4.6: ccr_poll() every CCR_POLL_S in its own thread, so it keeps running while the FLICA loop waits. 1.5.0
    (FW-0063): idle on a pilot instance, which never asks Hark (hark_ccr), so it never reads Hark's folder."""
    while True:
        time.sleep(CCR_POLL_S)
        if not has("hark_ccr"):
            continue
        try:
            ccr_poll()
        except Exception as e:
            log.info("CCR poll: %s", e)


def publish_recall():
    allr, acts = DB.get("recall_days") or {}, DB.get("recall_acts") or {}
    days = [{k: v for k, v in allr[k].items() if k != "rows"} for k in sorted(allr)[-45:]]
    opn = [v for d in days for v in d.get("verdicts") or []
           if v.get("verdict") in RECALL_LIVE and (v.get("act") or {}).get("status") in RECALL_OPEN]
    alert = [v for d in days if not d.get("replay") for v in d.get("verdicts") or []  # 1.7.1: none from a replay
             if v.get("verdict") == "MISSED" and (v.get("act") or {}).get("status") in RECALL_OPEN]
    # 1.4.6 (Ryan): RECALL ALERT = the Watcher says he should have been called
    received = max((d.get("at") or "" for d in allr.values()), default="")  # when the newest list post came in
    # FW-0060: every day goes to recall_<key>.json for the recall card (about 380 bytes a verdict: 45 days would pass
    # the recorder's 16 KB); the sensor keeps the newest days that fit (cap_attrs) and the counts over all of them
    key, rev = write_list_file("recall", {"days": days[::-1]})
    me, src = recall_me(with_source=True)
    # 1.6.2 review: a list day before the first schedule version on file (the award upload, or the first FLICA read)
    # can never have its line read back; those rows are counted apart (missing_line_old), with the date versions start
    vfrom = recall_versions_from(allr)
    miss = [("line_old" if v.get("missing") == "line" and vfrom and str(d.get("date") or "") < vfrom else v.get("missing"))
            for d in days for v in d.get("verdicts") or [] if v.get("verdict") in RECALL_LIVE]
    pub("recall", {"open": len(opn), "alert": len(alert), "me": me, "last": days[-1]["date"] if days else "",
                   "checked": now_iso(), "received": received, "hark_files": has("hark_ccr"), "days": days[::-1],
                   "days_total": len(days), "file_key": key, "rev": rev,
                   # 1.6.2 (item 10): where the seniority number comes from, and the rows held back for missing data
                   "sen_source": src, "missing_sen": miss.count("seniority"), "missing_line": miss.count("line"),
                   "missing_line_old": miss.count("line_old"), "versions_from": vfrom})


def recall_versions_from(allr):
    """1.6.2 review: the HST date of the first schedule version on file (the award upload's or the first FLICA read's),
    '' when there is none."""
    try:
        ts = [RC._at(v) for vs in recall_versions(allr).values() for v in vs or [] if isinstance(v, dict)]
        ts = [t for t in ts if t]
        return min(ts).astimezone(HST).date().isoformat() if ts else ""
    except Exception:  # noqa: BLE001 (a nicety for the card's wording)
        return ""


def publish_improved():
    allm = DB.get("improved_pay") or {}
    rows = [allm[k] for k in sorted(allm)]
    cur = rows[-1] if rows else {}
    pub("improved_pay", {"improved": cur.get("improved", 0), "months": rows, "ytd": round(sum(r.get("improved", 0) for r in rows), 2)})


def publish_own_trips():
    """0.4.7: Ryan's own trip report and block-in times (HNL local) for the schedule card, which
    shows them and suggests tag-on pairings after each trip. Keys 'TRIP|YYYY-MM-DD' (start). FW-0067: without
    the legs (about 100 bytes a leg; with them a busy line passes ATTR_MAX and loses trips the card shows);
    the working flight sensor carries the one leg that matters."""
    own = S.get("own_trips", {})
    pub("own_trips", {"count": len(own), "trips": {k: ({f: v for f, v in t.items() if f != "legs"} if isinstance(t, dict) else t)
                                                   for k, t in own.items()}})


# FW-0067: the working flight sensor is published when it changes (state, leg, status, next...), and at least every
# WORKING_REPUB_S while only its time stamps move; WORKING_TICK_S is how often a long wait looks again, so a
# departure, a block-in or the 2 h roll shows within a minute even while the Watcher is yielded or paused.
WORKING_REPUB_S = 30 * 60
WORKING_TICK_S = 60
WORKING_ROLL_H = 2
WORKING_LAST = {"news": None, "at": None}


def publish_working_flight(now=None, force=False):
    """FW-0067: sensor.<prefix>_working_flight from this instance's own schedule and own trip legs (working.py), any
    pilot. Retained. Skipped when nothing but its time stamps changed, unless WORKING_REPUB_S passed. Never raises
    (logs and goes on). Returns True when it published."""
    try:
        now = now or datetime.now(HST)
        wf = WK.working_flight(_sched_items(), S.get("own_trips") or {}, now, WORKING_ROLL_H)
        news = WK.news(wf)
        last = WORKING_LAST.get("at")
        if (not force and news == WORKING_LAST.get("news") and last is not None
                and timedelta(0) <= now - last < timedelta(seconds=WORKING_REPUB_S)):
            return False
        pub("working_flight", wf)
        if news.get("state") != (WORKING_LAST.get("news") or {}).get("state"):
            log.info("working flight: %s", wf["state"])
        WORKING_LAST.update(news=news, at=now)
        return True
    except Exception as e:
        log.warning("working flight not published: %s: %s", type(e).__name__, e)
        return False


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
    fetched, left_out = 0, False
    for k, row in pot.items():
        stale = k in cache and ("crew" not in cache[k] or "duties" not in cache[k])  # cached before 0.4.0 / FW-0039: re-read once
        if ((k not in cache or stale or full) and fetched < (FULL_MAX if full else DETAIL_MAX_PER_CHECK)
                and BRK.allow("pairing") and not left_out):  # 1.6.2: while pairing pages are stopped no empty detail is cached
            if fetched:
                time.sleep(random.uniform(1.5, 3.5))
            ev = dict(row)
            try:
                enrich(fl, ev)
            except GT.GateSkip as e:  # 1.6.2 review: a pilot's budget is kept for the pot: no empty detail cached
                left_out = True  # no more detail loads this check (the rows are still tagged below)
                if "pot_details" not in RUN["skipped"]:
                    RUN["skipped"].add("pot_details")
                    log.info("pot_details left out of this check: %s", e)
                ev = None
            if ev is not None:
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
        smart_fields(row)  # FW-0042
    if fetched:
        log.info("pot details fetched: %d (cached %d)", fetched, len(cache))


SCHED_GAP_S = 30 * 60
# 1.6.1: after a failed read (no page accepted) the next one is due 10 min later, then 30, then every SCHED_GAP_S; a
# read that works resets it. S keeps the count (sched_fail) and the due time (sched_next_at).
SCHED_FAIL_GAPS_S = (10 * 60, 30 * 60)
SCHED_FORCED = {"used": False}  # 1.6.1: one forced read per start (first pass, Check now) may skip that back-off


def schedule_due(force, now=None):
    """1.6.1: may schedule_check read now. While reads fail, only the back-off's due time (or the first forced read
    of this start) lets one through; otherwise as before: forced, or SCHED_GAP_S after the last read."""
    now = time.time() if now is None else now
    if int(S.get("sched_fail") or 0):
        if now >= float(S.get("sched_next_at") or 0):
            return True
        return bool(force) and not SCHED_FORCED["used"]
    return bool(force) or now - S.get("sched_checked_at", 0) >= SCHED_GAP_S


def schedule_failed(seen, why=(), paths=()):
    """1.6.1: one log line for a read where no page was accepted, and the next read's due time. 1.6.2: the due time
    waits for a breaker that stopped every page this read may load (30 min doubling to 6 h after 3 failed reads in a
    row), the status goes on sensor.<prefix>_schedule (read_status) and the log line says when the next read is."""
    n = int(S.get("sched_fail") or 0) + 1
    gap = SCHED_FAIL_GAPS_S[n - 1] if n <= len(SCHED_FAIL_GAPS_S) else SCHED_GAP_S
    nxt = time.time() + gap
    if paths and not any(BRK.allow(p) for p in paths):
        nxt = max(nxt, min(BRK.until(p) for p in paths))
    S["sched_fail"], S["sched_next_at"] = n, nxt
    log.info("schedule read failed (%d in a row, %d tries: %s); next read in %d min", n, len(seen),
             "; ".join(seen) or "none", round((nxt - time.time()) / 60))
    sched_status("; ".join(why) or "no page accepted", len(seen))
    save_state(S)
    publish_schedule()


def sched_status(why, tries):
    """1.6.2: S['sched_status'] for a read that accepted nothing: the reason in words (no URL, no employee number),
    when, and when the next read is due (HST clock times for the card)."""
    nxt = float(S.get("sched_next_at") or 0)
    S["sched_status"] = {"ok": False, "why": why[:300], "at": now_iso(), "at_hst": hst_hm(time.time()),
                         "next_try": datetime.fromtimestamp(nxt, timezone.utc).isoformat() if nxt else "",
                         "next_hst": hst_hm(nxt) if nxt else "", "tries": tries}


LEFTMENU = f"{BASE}/online/leftmenu.cgi?whosepage=Crewmember"


OWN_RE = re.compile(r"\b([a-z]+(?: jr| sr| ii| iii)?, [a-z]+(?: [a-z]+)?)\s+(\d{3,6})\s+-\s+[a-z]{3}\s+\d{3}\s+(?:fo|ca|ro)\b")


def note_own(text):
    """0.8.5: Ryan's own employee number from a FLICA page header ('doe, jane 10001 - hnl 332 fo', made up),
    kept in state for the Schedule Lookup reads of his other months."""
    m = OWN_RE.search((text or "").lower())
    if m and S.get("own_emp") != m.group(2):
        S["own_emp"], S["own_name"] = m.group(2), m.group(1).title()
        S["sched_prev_at"] = S["sched_checked_at"] = 0  # read the other months on the next pass
        log.info("own employee number noted from the page header")
    return S.get("own_emp")


LOOKUP_KEYS = ("block", "credit")
LOOKUP_PAGE = {"bd": "", "html": "", "at": 0}  # the last Schedule Lookup page read, so other_months_check does not load it twice
# 1.6.2 review: one schedule read loads at most SCHED_TRIES_PER_READ pages in all: the current month's tries and then
# the follow-on reads (FLICA's totals, the other months, last month). A follow-on that finds no load left waits for the
# next due read (SchedFull). left None: no read is running (a direct call loads as before). lookup_ok: a Schedule Lookup
# page of this read was a schedule (the path works, so one month's odd answer is not counted against it).
SCHED_READ = {"left": None, "lookup_ok": False}
LOOKUP_MONTHS_KEEP_S = 6 * 3600  # the Schedule Lookup month list is kept this long (S lookup_months)
OTHER_FAIL_FIRST_S = 3600  # a listed month that fails waits 1 h, then 2, 4, at most 6 h (S sched_other_fail)


class SchedFull(Exception):
    """This schedule read has used its loads: the rest waits for the next due read."""


def sched_fetch(fl, url):
    if SCHED_READ["left"] is not None:
        if SCHED_READ["left"] <= 0:
            raise SchedFull()
        SCHED_READ["left"] -= 1
    return fl.fetch(url)


def note_lookup_months(html):
    """Keep the month list of a current-month Schedule Lookup page (S lookup_months), so the other months need no
    second load of it within LOOKUP_MONTHS_KEEP_S."""
    bds = re.findall(r'<option value="(\d{4})"', html or "")
    if bds:
        S["lookup_months"] = {"bds": bds, "at": time.time()}


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
    html = sched_fetch(fl, url)
    sp = IF.parse_cm_month(html) if classify(html) == "ok" else None
    if not sp or sp["month"] != month:
        log.info("schedule %s totals via Schedule Lookup (bd=%s): %s %s", month, bd, classify(html),
                 (sp and sp["month"]) or visible_text(html)[:120])
        return {}
    LOOKUP_PAGE.update(bd=bd, html=html, at=time.time())
    note_lookup_months(html)
    SCHED_READ["lookup_ok"] = True
    return {k: v for k, v in (sp.get("totals") or {}).items() if k in LOOKUP_KEYS and v not in (None, "")}


def merge_lookup_totals(fl, s, old=None):
    """FW-0019: fill the Block / Credit a schedule page lacks from the Schedule Lookup page, so schedule versions see
    FLICA's totals change. A missed lookup keeps the figures last stored for the month (old), so a failed read is
    never taken for a schedule change. Figures the schedule page has itself are kept."""
    tot = s.setdefault("totals", {})
    if all(k in tot for k in LOOKUP_KEYS):
        return
    try:
        got = lookup_totals(fl, s.get("month")) if fl is not None else {}
    except SchedFull:  # 1.6.2 review: no load left in this read: the last stored figures stay
        got = {}
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
    kept = S.get("lookup_months") or {}
    bds = []
    if LOOKUP_PAGE["bd"] == bdc and time.time() - LOOKUP_PAGE["at"] < 300:
        html = LOOKUP_PAGE["html"]  # FW-0019: the schedule check's totals read just loaded this page
    elif kept.get("bds") and 0 <= time.time() - float(kept.get("at") or 0) < LOOKUP_MONTHS_KEEP_S:
        html, bds = "", list(kept["bds"])  # 1.6.2 review: the month list read earlier (no second load of it)
    else:
        time.sleep(random.uniform(1.5, 3.5))
        try:
            html = sched_fetch(fl, IF.CM_SCHED_MONTH.format(base=BASE, emp=emp, bd=bdc))
        except SchedFull:
            return None  # this read's loads are used: the next due read goes on
        if classify(html) == "ok" and re.search(r'<option value="(\d{4})"', html):
            note_lookup_months(html)
            SCHED_READ["lookup_ok"] = True
        else:
            other_failed(None, "the month list page: " + classify(html))
    if not bds:
        if classify(html) != "ok":
            log.info("own schedule lookup: %s", classify(html))
            return False
        bds = re.findall(r'<option value="(\d{4})"', html)
    if not bds:
        log.info("own schedule lookup: no month list: %s", visible_text(html)[:160])
        return False
    got, waiting = [], False
    fails = S.setdefault("sched_other_fail", {})
    for bd in bds:
        mon = f"20{bd[2:]}-{bd[:2]}"
        if mon == cur_month:
            continue
        if mon in store and store[mon].get("src") == "lookup" and time.time() - store[mon].get("read_ts", 0) < 6 * 3600:
            got.append(mon)
            continue
        if time.time() < float((fails.get(mon) or {}).get("next") or 0):
            continue  # 1.6.2 review: a month that failed waits its back-off (it was loaded again on every read)
        time.sleep(random.uniform(1.5, 3.5))
        try:
            page = sched_fetch(fl, IF.CM_SCHED_MONTH.format(base=BASE, emp=emp, bd=bd))
        except SchedFull:
            waiting = True
            break
        sp = IF.parse_cm_month(page) if classify(page) == "ok" else None
        if sp and sp["month"] == mon:
            SCHED_READ["lookup_ok"] = True
        if not sp or sp["month"] != mon:
            log.info("own schedule %s (bd=%s): %s %s", mon, bd, classify(page), (sp and sp["month"]) or visible_text(page)[:160])
            other_failed(mon, classify(page) if classify(page) != "ok" else "not that month's schedule")
            continue
        fails.pop(mon, None)
        store[mon] = {"month": mon, "updated": sp.get("updated", ""), "days": sp["days"], "items": sp["items"],
                      "totals": sp.get("totals") or {}, "src": "lookup", "read_ts": time.time()}
        got.append(mon)
        log.info("schedule %s: %d items via Schedule Lookup (bd=%s), totals %s", mon, len(sp["items"]), bd, sp.get("totals"))
    if waiting:
        return None
    return len(got) == len([b for b in bds if f"20{b[2:]}-{b[:2]}" != cur_month])


def other_failed(mon, why):
    """1.6.2 review: a listed month (or, mon None, the month list page) that Schedule Lookup did not give: the month
    waits OTHER_FAIL_FIRST_S doubling to 6 h, and the 'lookup' read path counts one failed read per schedule read
    unless another Schedule Lookup page of the same read was a schedule (the path works)."""
    if mon:
        f = S.setdefault("sched_other_fail", {}).setdefault(mon, {"n": 0, "next": 0})
        f["n"] = int(f.get("n") or 0) + 1
        f["next"] = time.time() + min(6 * 3600, OTHER_FAIL_FIRST_S * 2 ** (f["n"] - 1))
    if not SCHED_READ.get("lookup_ok") and not SCHED_READ.get("lookup_failed"):
        SCHED_READ["lookup_failed"] = True
        BRK.fail("lookup", f"Schedule Lookup, other months: {why}")


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
        done = other_months_check(fl, cur_month)
        if done is None:
            return  # 1.6.2 review: this read's loads are used; the next due read goes on from here
        if done:
            S["sched_prev_at"] = time.time()
            S["sched_prev_v"] = 6
            return
    except GT.BreakerOpen as e:
        log.info("own schedule lookup skipped: %s", e)
    except Exception as e:
        log.info("own schedule lookup failed: %s", e)
    if S.get("sched_prev_v") == 5 and prev in store and time.time() - S.get("sched_prev_at", 0) < 86400:
        return
    mo = re.search(r"BCID=\d{3}\.(\d+)", ok_url)
    if not mo:
        S["sched_prev_at"] = time.time()  # 1.6.2 review: a pass that missed a month waits like the mobile one
        return
    n = f"{int(mo.group(1)) - 1:03d}"
    py, pm = int(prev[:4]), int(prev[5:7])
    # 1.6.2: the mobile BlockDate page only. The desktop Schedules page (scheduledetail.cgi, plain or through the left
    # menu's tokened GO=1 link) answers this session with FLICA's reCAPTCHA forward page: it is never loaded again.
    cands = [f"{BASE}/full/mobileschedule.cgi?BlockDate={pm:02d}{py % 100:02d}&From=MainMenu"]
    S["sched_prev_v"] = 5  # 0.8.3: re-run the October read right away
    S["sched_prev_at"] = time.time()
    seen = []
    for url in cands:
        try:
            time.sleep(random.uniform(1.5, 3.5))
            html = sched_fetch(fl, url)
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
        except SchedFull:
            S["sched_prev_at"] = 0  # no load left in this read: the next due read tries it
            return
        except Exception as e:
            seen.append((url.split("?")[1], str(e)))
    log.info("previous month schedule %s not found: %s", prev, seen)


SCHED_PERIOD_AT = ("2026-11", 152)  # FLICA's bid period number of a month: 152 for November 2026 (Oct = 151, 0.4.16)
SCHED_TRIES_PER_READ = 2  # 1.6.2: FLICA loads one current-month schedule read may make (pages already in use only)
SCHED_REFUSED = ("invalid or unspecified bid period",)  # FLICA's own answer when a URL shape names no bid period


def bid_period_n(month):
    """1.6.2: FLICA's bid period number of a month (YYYY-MM), one more each month from SCHED_PERIOD_AT. A learned
    schedule URL is kept as a shape and filled with this, so it follows the month instead of breaking at a rollover."""
    y, m = int(month[:4]), int(month[5:7])
    ay, am = int(SCHED_PERIOD_AT[0][:4]), int(SCHED_PERIOD_AT[0][5:7])
    return SCHED_PERIOD_AT[1] + (y - ay) * 12 + (m - am)


def sched_shape_of(url):
    """1.6.2: the shape of a schedule URL that worked: 'lookup' (Tools > Schedule Lookup for the pilot's own number),
    or the mobile schedule's path with the bid period number as {n} and the BlockDate as {bd}. '' for anything else
    (the desktop scheduledetail page is never kept: FLICA answers it with a reCAPTCHA page)."""
    u = url or ""
    if "cmschedules.cgi" in u:
        return "lookup"
    p = u[len(BASE):] if u.startswith(BASE) else u
    if not p.startswith("/full/mobileschedule.cgi?"):
        return ""
    return re.sub(r"(BlockDate=)\d{4}", r"\g<1>{bd}", re.sub(r"(BCID=\d{3})\.\d+", r"\g<1>.{n}", p))


def sched_shape_url(shape, month):
    """The URL of a shape for a month ('' when it cannot be built: Schedule Lookup with no own number known)."""
    bd = f"{month[5:7]}{month[2:4]}"
    if shape == "lookup":
        emp = S.get("own_emp")
        return IF.CM_SCHED_MONTH.format(base=BASE, emp=emp, bd=bd) if emp else ""
    if not shape.startswith("/full/mobileschedule.cgi?"):
        return ""
    return BASE + shape.replace("{n}", f"{bid_period_n(month):03d}").replace("{bd}", bd)


def sched_cands(month):
    """1.6.2: the schedule pages one read may load, in order, only pages already in use: the shape that last worked,
    else the pilot's own Schedule Lookup for the month (IF.CM_SCHED_MONTH, as other_months_check reads it), else the
    mobile schedule's BlockDate page. [(label, url)]; no BCID guesses, no scheduledetail."""
    if "sched_shape" not in S and S.get("sched_url_ok"):  # an older Watcher kept the literal URL: keep its shape (once)
        S["sched_shape"] = sched_shape_of(S["sched_url_ok"])
        if S["sched_shape"].startswith("/full/mobileschedule.cgi?"):
            S["sched_shape_mobile"] = S["sched_shape"]
        log.info("schedule: the URL that last worked is kept as a shape that follows the bid period (%s)",
                 S["sched_shape"].split("?")[-1] if S["sched_shape"] not in ("", "lookup") else S["sched_shape"] or "none")
    if (S.get("sched_shape") or "").startswith("/full/mobileschedule.cgi?") and not S.get("sched_shape_mobile"):
        S["sched_shape_mobile"] = S["sched_shape"]
    bd = f"{month[5:7]}{month[2:4]}"
    out = []
    # 1.6.2 review: the mobile shape that worked last (S sched_shape_mobile) comes second, so one hiccup that let
    # Schedule Lookup answer does not lose it for good
    for shape in (S.get("sched_shape") or "", S.get("sched_shape_mobile") or "", "lookup",
                  "/full/mobileschedule.cgi?BlockDate={bd}&From=MainMenu"):
        url = sched_shape_url(shape, month) if shape else ""
        if url and url not in [u for _, u in out]:
            out.append(("Schedule Lookup" if shape == "lookup" else "mobile schedule", url))
    return out


def sched_label(url):
    """A try's name for the log: the mobile URL's query, or 'Schedule Lookup bd=MMYY' (never the employee number)."""
    if "cmschedules.cgi" in url:
        m = re.search(r"bd=(\d{4})", url)
        return f"Schedule Lookup bd={m.group(1) if m else '?'}"
    return url.split("?")[-1]


def publish_schedule(updated=None, source=None):
    """sensor.<prefix>_schedule: the months on file (as before) and, 1.6.2, read_status: {ok, why, at, at_hst,
    next_try, next_hst, tries} of the last read, so the Schedule card can say why FLICA's schedule is not read."""
    sch = S.get("schedule") or {}
    cur = sch.get(local_now().strftime("%Y-%m")) or {}
    pub("schedule", {"updated": updated if updated is not None else (cur.get("updated") or ""),
                     "source": source if source is not None else (S.get("sched_source") or ""),
                     "checked": now_iso(), "read_status": S.get("sched_status") or {},
                     "months": {k: {kk: v[kk] for kk in ("items", "days", "totals", "updated") if kk in v}
                                for k, v in sch.items()}})


def schedule_check(fl, force=False):
    """Read only: the pilot's current month (1.6.2: at most SCHED_TRIES_PER_READ loads, sched_cands' order), publish
    sensor.<prefix>_schedule and an event when trips change. A page for another month is refused (a rollover never
    keeps last month as this one). Never stops the pot watch."""
    if not schedule_due(force):
        return
    SCHED_READ.update(left=SCHED_TRIES_PER_READ, lookup_ok=False, lookup_failed=False)  # 1.6.2 review: all loads
    try:
        _schedule_read(fl, force)
    finally:
        SCHED_READ.update(left=None, lookup_ok=False, lookup_failed=False)


def other_months_pending(cur_month):
    """1.6.2 review: a listed other month needs a load now (the month list is kept, the month is not fresh and not
    backing off), so this read's last load goes to it and FLICA's totals keep their stored figures one read."""
    kept = S.get("lookup_months") or {}
    if not S.get("own_emp") or not kept.get("bds") or time.time() - float(kept.get("at") or 0) >= LOOKUP_MONTHS_KEEP_S:
        return False
    if time.time() - S.get("sched_prev_at", 0) < (6 * 3600 if S.get("sched_prev_v") == 6 else 1800):
        return False
    store, fails = S.get("schedule") or {}, S.get("sched_other_fail") or {}
    for bd in kept["bds"]:
        mon = f"20{bd[2:]}-{bd[:2]}"
        if mon == cur_month or time.time() < float((fails.get(mon) or {}).get("next") or 0):
            continue
        if not (mon in store and store[mon].get("src") == "lookup"
                and time.time() - store[mon].get("read_ts", 0) < 6 * 3600):
            return True
    return False


def _schedule_read(fl, force):
    if force:
        SCHED_FORCED["used"] = True
    S["sched_checked_at"] = time.time()
    store = S.setdefault("schedule", {})
    cur_month = local_now().strftime("%Y-%m")

    def accept(url, s):
        if seen:  # 1.6.1: tries that failed before this page, one line (Release A needs to see the URL drift)
            log.info("schedule read: %s worked after %d failed: %s", sched_label(url), len(seen), "; ".join(seen))
        old = store.get(s["month"])
        read_at = now_iso()
        if s.get("src") != "lookup":
            if other_months_pending(s["month"]) and old and all(k in (old.get("totals") or {}) for k in LOOKUP_KEYS):
                merge_lookup_totals(None, s, old)  # 1.6.2 review: the stored figures; this read's load is a month's
            else:
                merge_lookup_totals(fl, s, old)  # FW-0019: the mobile page has no Block / Credit; Schedule Lookup does
        if old and [(i["trip"], i["start"]) for i in old["items"]] != [(i["trip"], i["start"]) for i in s["items"]]:
            ev = {"month": s["month"], "updated": s["updated"],
                  "added": sorted({i["trip"] + " " + i["start"] for i in s["items"]} - {i["trip"] + " " + i["start"] for i in old["items"]}),
                  "removed": sorted({i["trip"] + " " + i["start"] for i in old["items"]} - {i["trip"] + " " + i["start"] for i in s["items"]}),
                  "totals": s["totals"]}
            log.info("SCHEDULE changed %s", ev)
            pub("event/schedule_changed", ev, retain=False)
            try:  # FW-0064; never fails the read (an error here must not make schedule_check load another URL)
                # the same page read twice (1.6.2: a current month read on Schedule Lookup each time counts too); a month
                # first read on Schedule Lookup and now on the mobile page is not
                if old.get("src") == s.get("src"):
                    sched_moves_record(s["month"], old["items"], s["items"], s.get("updated"), read_at)
            except Exception as e:
                log.info("schedule moves not recorded: %s", e)
        S["sched_read_at"] = read_at  # FW-0064: a trade seen on the schedule is decided one quiet read later
        S["sched_url_ok"] = url
        S["sched_shape"] = sched_shape_of(url)
        if S["sched_shape"].startswith("/full/mobileschedule.cgi?"):
            S["sched_shape_mobile"] = S["sched_shape"]  # 1.6.2 review: kept apart from the last shape used
        S["sched_fail"], S["sched_next_at"] = 0, 0  # 1.6.1: a read that works resets the back-off
        S["sched_source"] = "FLICA Schedule Lookup (Watcher)" if s.get("src") == "lookup" else "FLICA mobile schedule (Watcher)"
        S["sched_status"] = {"ok": True, "why": "", "at": read_at, "at_hst": hst_hm(time.time()), "next_try": "",
                             "next_hst": "", "tries": len(seen) + 1}
        store[s["month"]] = s
        prev_month_check(fl, url, s["month"])  # 0.4.16: last month too, for 30 in 7 / 100 in 672 windows
        keep = sorted(store)[-3:]
        S["schedule"] = {k: store[k] for k in keep}
        publish_schedule(updated=s["updated"] or now_iso())
        log.info("schedule %s: %d items, totals %s", s["month"], len(s["items"]), s["totals"])
        try:
            trade_check()  # FW-0064
        except Exception as e:
            log.info("schedule trade check skipped: %s", e)
        save_state(S)

    seen, why, tries, paths = [], [], 0, []  # seen: each try for the log; why: the same in words for the card
    failed = set()

    def bfail(path, what):  # one failed read per path per read, however many of its pages this read tried
        if path not in failed:
            failed.add(path)
            BRK.fail(path, what)
    for label, url in sched_cands(cur_month):
        if tries >= SCHED_TRIES_PER_READ:
            break
        path = GT.read_path(url)
        paths.append(path)
        if not BRK.allow(path):
            why.append(f"{label} reads paused until {hst_hm(BRK.until(path))} HST")
            continue
        if not (SUB.safe_get(url) and SM.safe_get(url)):
            seen.append(f"{sched_label(url)}: refused by safe_get")
            continue
        try:
            if tries:
                time.sleep(random.uniform(1.5, 3.5))  # 1.6.2: the FLICA pacing rule (was 1.0 to 2.0 s)
            tries += 1
            html = sched_fetch(fl, url)
        except GT.GateAbort:
            raise  # 1.6.2 review: Pause or a stop while the load waited: the check ends
        except GT.BreakerOpen as e:
            tries -= 1  # refused before the load: nothing reached FLICA
            why.append(f"{label} reads paused ({e})")
            continue
        except Exception as e:
            seen.append(f"{sched_label(url)}: error {e}")
            why.append(f"{label}: no answer ({type(e).__name__})")
            bfail(path, f"{label}: load error ({type(e).__name__})")
            continue
        kind = classify(html)
        if kind != "ok":
            seen.append(f"{sched_label(url)}: {kind}")
            why.append(f"{label}: {'a CAPTCHA page (never answered)' if kind == 'captcha' else kind + ' page'}")
            if kind != "captcha":  # a CAPTCHA page already stopped the path for 6 h (Flica)
                bfail(path, f"{label}: {kind} page")
            continue
        if path == "lookup":
            sp = IF.parse_cm_month(html) if IF.schedule_ok(html) else None
            if sp:
                sp = {"month": sp["month"], "updated": sp.get("updated", ""), "days": sp["days"], "items": sp["items"],
                      "totals": sp.get("totals") or {}, "src": "lookup", "read_ts": time.time()}
                LOOKUP_PAGE.update(bd=f"{cur_month[5:7]}{cur_month[2:4]}", html=html, at=time.time())
                note_lookup_months(html)
                SCHED_READ["lookup_ok"] = True
        else:
            sp = parse_schedule(html)
        if not sp:
            text = visible_text(html)
            said = next((h for h in SCHED_REFUSED if h in text), "")
            seen.append(f"{sched_label(url)}: {text[:120]}")
            why.append(f"{label}: FLICA answered '{said}'" if said else f"{label}: not a schedule page")
            bfail(path, f"{label}: " + (f"FLICA answered '{said}'" if said else "not a schedule page"))
            if not S.get("sched_probe_logged"):
                S["sched_probe_logged"] = True
                log.info("schedule page not parsed (%s): %s", sched_label(url), page_log(text[:2000]))
                try:
                    cap_write("schedule.html", html)
                except Exception:
                    pass
            continue
        if sp["month"] != cur_month:  # 1.6.2: the month rollover bug: never last month's page as this one
            seen.append(f"{sched_label(url)}: the {sp['month']} schedule, not {cur_month}")
            why.append(f"{label}: FLICA gave the {sp['month']} schedule, not {cur_month}")
            bfail(path, f"{label}: the {sp['month']} schedule, not {cur_month}")
            continue
        BRK.ok(path)
        accept(url, sp)
        return
    if not tries:  # every page this read may load is paused: no FLICA load, no failed read
        nxt = min([BRK.until(p) for p in paths if not BRK.allow(p)] or [time.time() + SCHED_FAIL_GAPS_S[0]])
        S["sched_next_at"] = max(float(S.get("sched_next_at") or 0), nxt)
        sched_status("; ".join(why) or "no schedule page may be read", 0)
        save_state(S)
        publish_schedule()
        return
    schedule_failed(seen, why, paths)


def detail_probe(fl, pot):
    """Once per start: log one detail page's text so the captain/total parsers can be checked."""
    if DETAIL_PROBE["done"] or not pot:
        return
    row = dict(next(iter(pot.values())))
    enrich(fl, row)
    # 1.7.3: a pilot's log never names the captain (another pilot), only whether one was parsed; PilotLogMask too
    who = repr(row.get("captain")) if CAP.admin else ("parsed" if row.get("captain") else "none")
    log.info("detail probe %s: captain=%s blk=%s credit=%s soft=%s", row.get("pairing"),
             who, row.get("blk"), row.get("credit"), row.get("soft"))


CAPTURE_DIR = f"{SHARE}/captures"


def cap_secrets():
    """1.6.2 (item 8): what a pilot's debug captures must never hold: his FLICA and CrewTrac logins, his name and his
    employee number (captures.mask masks them as 'MASKED')."""
    return [str(OPTS.get(k) or "") for k in CRED_KEYS] + [str(S.get("own_name") or ""), str(S.get("own_emp") or "")]


# 1.6.2 (item 8): every page capture goes through this instance's policy (captures.py): the admin's as before, in
# CAPTURE_DIR; a pilot's only while /share/flight_watcher/<pilot>/captures_on is under 24 h old, masked, 0600, in his
# own 0700 folder, deleted after 7 days. inflt's own capture (cmschedule_<emp>.html) is wired in too, per instance.
CAP = CAPS.Captures(INSTANCE, log=log.info, secrets=cap_secrets)
IF.CAPTURE_DIR = CAPTURE_DIR


def cap_on():
    """True when this instance may write a page capture now (always the admin; a pilot only while captures_on is
    fresh). Loads made only to be captured are skipped when False."""
    return CAP.on()


def cap_write(name, data, extra=()):
    """One page capture (name under the captures folder, e.g. 'schedule.html'): the admin's to CAPTURE_DIR as before
    (unmasked), a pilot's masked into his own folder or not at all. The path written, or None. Errors are the
    caller's (each capture site keeps its own try). extra: more strings a pilot's copy masks (names a parser read)."""
    return CAP.write(name, data, admin_dir=CAPTURE_DIR, extra=extra)


def page_log(text):
    """1.6.2 review: FLICA page text for a log line. The admin's as before. A pilot's only while his captures are on
    (and masked, as a capture); otherwise just its size. The pilot log filter (PilotLogMask) masks every line too."""
    t = str(text or "")
    if CAP.admin:
        return t
    if not cap_on():
        return f"({len(t)} chars, not logged: page captures are off for this pilot)"
    return CAPS.mask(t, cap_secrets())


# 1.7.0 review: characters a log line never carries as they are (pilot text, e.g. a ticket title, could otherwise
# start a line of its own in the add-on log that looks like the admin instance's): controls (a line feed, a carriage
# return, ESC), lone surrogates, the line and paragraph separators and the bidi controls. They become visible escapes.
LOG_CTRL_RE = re.compile("[\x00-\x1f\x7f-\x9f\u2028\u2029\u200e\u200f\u061c\u202a-\u202e\u2066-\u2069\ud800-\udfff]")


def log_safe(v, n=None):
    """v as text for one log line: LOG_CTRL_RE characters as escapes (\\n, \\x1b, \\u202e), cut to n code points
    first when n is given. Ordinary text is unchanged."""
    s = str(v if v is not None else "")
    s = s[:n] if n else s
    return LOG_CTRL_RE.sub(lambda m: m.group(0).encode("unicode_escape", "backslashreplace").decode("ascii"), s)


class PilotLogMask(logging.Filter):
    """1.6.2 review: on a pilot, every log line (the add-on log the admin and Claude read) is masked as a capture is:
    other pilots' names, employee numbers, e-mail addresses and phone numbers, and his own logins. 1.7.0 review: and
    kept to one line (log_safe), so nothing a pilot sends can write a line that looks like another instance's."""

    def filter(self, record):
        try:
            msg = record.getMessage()
            out = log_safe(CAPS.mask(msg, cap_secrets()))
            if out != msg:
                record.msg, record.args = out, ()
        except Exception:  # noqa: BLE001 (a log line is never lost to the mask)
            pass
        return True


for _f in list(log.filters):  # one per process (a re-import, as the tests do, replaces it)
    if type(_f).__name__ == "PilotLogMask":
        log.removeFilter(_f)
if ROLES.role(INSTANCE) == ROLES.PILOT:
    log.addFilter(PilotLogMask())


IF.WRITE = cap_write
IF.PAGE_LOG = page_log  # 1.7.3 review: inflt logs page text as the Watcher does


def capture(fl, month, html):
    """Read-only discovery for t1222 (soft time, captain, fits, FAR): every 6 h save the pot page,
    its links, one pairing detail page and any schedule page this session can already open, so
    the parsers get built from real HTML. Same session, GET only; never clicks or submits."""
    if time.time() - S.get("captured_at", 0) < 6 * 3600:
        return
    if not cap_on():  # 1.6.2 (item 8): a pilot takes no captures (and loads no page for one) unless they are on
        return
    S["captured_at"] = time.time()
    try:
        from bs4 import BeautifulSoup
        from urllib.parse import urljoin
        cap_write(f"pot_{month}.html", html)
        url = S["pot_urls"][month]
        links = [{"text": a.get_text(" ", strip=True)[:60], "href": urljoin(url, a["href"])}
                 for a in BeautifulSoup(html, "html.parser").find_all("a", href=True)]
        cap_write(f"links_{month}.json", links)
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
            cap_write(f"{name}.html", page)
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
    DOH in /data/cards.json; rate for today (HST); the per-trip Extended Range list helper. 1.6.0 (FW-0061): a portal
    pilot's prefs.json first (pref_get: None on any other instance). 1.6.4: with a date of hire on file, a longevity
    year still flagged unconfirmed (copied from a never-set helper, prefs_seed) yields to the DOH's year; a year the
    pilot chose himself (pref/set, or Keep these) still wins, as the admin's own helper does."""
    today = local_now().date().isoformat()
    doh = pilot_doh()
    yr = pref_get("longevity_year")
    if yr is not None and doh and pref_unconfirmed("longevity_year"):
        yr = None
    if yr is None and not portal_on():  # 1.6.2 (item 12): a portal pilot's HA helpers are gone: never read
        try:
            yr = int(float(ha_state(f"input_number.{T}_longevity_year")))
        except (TypeError, ValueError):
            pass
    if not yr:
        try:
            yr = min(12, PAY.doh_year(doh, today))
        except Exception:
            yr = None
    er_pref = pref_get("er_trips")
    if er_pref is None and portal_on():
        er_pref = ""
    er = [x for x in str((ha_state(f"input_text.{T}_er_trips") if er_pref is None else er_pref) or "").split(",") if x]
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
CLOSE_IN_READ_S = 300  # FW-0035: hunting, the close-in page is read at most every 5 min (about 12 loads an hour; every check otherwise)
CLOSE_IN_LAST = {"bcid": None, "at": 0.0, "rows": {}}  # its last good read in this process (the rows between reads)
STOP_KINDS = ("killed", "expired", "blocked")  # pages that end the pass (classify())


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


def trade_pages_scan(html, via):
    """FW-0064 (Ryan: 'also find the FLICA page that lists crew-to-crew trades, read only'): look on a menu already read
    for an entry naming crew-to-crew trades (pot.trade_pages; Tradeboard folders left out). Nothing is fetched or
    followed: what is found is logged once (S['trade_pages'], token masked) and the menu is kept privately as
    CAPTURE_DIR/menu_trades.html (token masked) whenever what it names changes, so the page can be checked by hand
    before the Watcher ever reads it. Returns the entries found."""
    try:
        found = trade_pages(html)
    except Exception as e:
        log.info("trade page scan of the %s failed: %s", via, e)
        return []
    tp = S.setdefault("trade_pages", {})
    sig = json.dumps(found, sort_keys=True)
    if tp.get("sig") != sig:
        tp.update(sig=sig, found=found, via=via, at=now_iso())
        if found:
            log.info("crew-to-crew trades page named on the %s (not read; GET only once checked): %s", via,
                     "; ".join(f"{f['text']} -> {f['url']}" for f in found))
        else:
            log.info("crew-to-crew trades page: the %s names none", via)
        try:  # a private copy of the menu that was scanned (/share, never git)
            cap_write("menu_trades.html", re.sub(r"token=[0-9A-Za-z]+", "token=MASKED", html or ""))
        except Exception:
            pass
    return found


def close_in_menu_read(fl):
    """FW-0034: the menu read that finds the close-in folder, read only: the left menu (leftmenu.cgi, a plain GET), and
    when that holds no menu tree (FLICA builds it only inside the menu frame), the main menu's menu frame (rendered in
    a tab like the pot discovery, no clicks). Both URLs pass SUB.safe_get and SM.safe_get; paced 1.5 to 3.5 s. Every
    6 h while the folder is not known (or its BCID is of no bid period watched), once a day once it is. A menu that
    does not name the folder is logged and kept privately (CAPTURE_DIR/menu_closein.html, session token masked) so
    its shape can be checked. FW-0064: the same menu is scanned for a crew-to-crew trades page (trade_pages_scan, never
    followed). Returns (the BCID found or None, kind): kind is 'ok', or 'killed' / 'expired' / 'blocked' when a menu
    page said so (the caller ends the pass as the pot loop does)."""
    ci = S.setdefault("close_in", {})
    periods = {x.split(".")[-1] for x in _regular_bcids()}
    settled = ci.get("verified") and (not periods or ci["bcid"].split(".")[-1] in periods)  # a new bid period: look again
    if time.time() - ci.get("menu_at", 0) < (CLOSE_IN_RECHECK_S if settled else CLOSE_IN_GAP_S):
        return None, "ok"
    ci["menu_at"] = time.time()
    seen, keep, stop = [], "", "ok"
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
            if kind in STOP_KINDS:
                stop = kind
                break
            continue
        trade_pages_scan(html, how)  # FW-0064: a page listing crew-to-crew trades, if the menu names one
        b = close_in_scan(html, how)
        if b:
            return b, "ok"
        named = bool(CLOSE_IN_RE.search(visible_text(html)))
        seen.append(f"{how}: {len(html)} chars, " + ("names the folder but no BCID link" if named else
                                                       "no close-in folder named"))
        keep = html
        if "addC(" in html or "addE(" in html or "BCID=" in html.upper():
            break  # a real menu that does not name it; the frame would show the same
    log.info("close-in folder not on the menu yet: %s", "; ".join(seen) or "nothing read")
    if keep:
        try:
            cap_write("menu_closein.html", re.sub(r"token=[0-9A-Za-z]+", "token=MASKED", keep))
        except Exception:
            pass
    return None, stop


def _close_in_cached(regular):
    """The close-in rows of the last good read of the folder now trusted, less any trip a regular pot has now."""
    b = (S.get("close_in") or {}).get("bcid")
    if not b or CLOSE_IN_LAST["bcid"] != b:
        return {}
    return {k: r for k, r in CLOSE_IN_LAST["rows"].items() if k not in regular}


def close_in_check(fl, pot_all, full=False, moved_from=()):
    """FW-0034 (Ryan: trips under 16 h to report reached him only through FLICA's alert email): read only, the close-in
    folder. Finds its BCID (close_in_menu_read when due; close_in_scan of pages read anyway), then GETs its open time
    page (mobileopentimepot.cgi?BCID=<its BCID>, both safe_get guards, paced 1.5 to 3.5 s). The BCID is trusted (swap
    and drop drafts, the request list) only once that page reads as an open time page of the pilot's category
    (OPTS category_check); CLOSE_IN_BAD_MAX reads that do not drop it. Its pairings not in a regular pot join the pot
    rows (src 'C', folder 'close-in'), with details, the FAR column and finds; a new one fires event/new_pairing like
    a pot find (none on the folder's first read).
    FW-0035: hunting, the page is read at most every CLOSE_IN_READ_S (about 12 loads an hour, not one a check); between
    reads (and after a read that failed) the last good read's rows are returned. Every check otherwise, and on Check
    now. A trip that moved here from a regular pot (moved_from: the regular baselines before this check's pot reads;
    or a trip waiting for its pickup check because it left one) is not new: no second push, its find keeps its
    first_seen and now belongs to the close-in folder, and it is no pickup to check. Returns (rows {key: row}, kind):
    kind is 'ok', or 'killed' / 'expired' / 'blocked' when a page read here said so (check() then ends the pass as
    the pot loop does)."""
    ci = S.setdefault("close_in", {})
    regular = {k: r for p in pot_all.values() for k, r in p.items()}
    if not ci.get("bcid") or ci.get("verified"):
        _, kind = close_in_menu_read(fl)
        if kind in STOP_KINDS:
            return _close_in_cached(regular), kind
    b = ci.get("bcid")
    if not b:
        return {}, "ok"
    if (FLAGS.get("hunt") and not full and CLOSE_IN_LAST["bcid"] == b and CLOSE_IN_LAST["at"]
            and time.time() - CLOSE_IN_LAST["at"] < CLOSE_IN_READ_S):
        return _close_in_cached(regular), "ok"
    url = close_in_url(b)
    if not (SUB.safe_get(url) and SM.safe_get(url)):
        log.info("close-in %s: url refused by safe_get", b)
        return {}, "ok"
    time.sleep(random.uniform(1.5, 3.5))
    try:
        html = fl.fetch(url)
    except Exception as e:
        log.info("close-in %s error: %s", b, e)
        return _close_in_cached(regular), "ok"
    kind = classify(html)
    if kind != "ok":
        log.info("close-in %s: %s, skipped", b, kind)
        return _close_in_cached(regular), kind if kind in STOP_KINDS + ("captcha",) else "ok"
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
            CLOSE_IN_LAST.update(bcid=None, at=0.0, rows={})
            return {}, "ok"
        return _close_in_cached(regular), "ok"
    ci["bad"] = 0
    if not ci.get("verified"):
        ci.update(verified=True, verified_at=now_iso())
        log.info("close-in folder %s verified (found on the %s): its open time page reads; text: %s", b, ci.get("via"),
                 text[:300])
        try:  # a private copy for parser checks (/share, never git)
            cap_write(f"pot_closein_{b.split('.')[-1]}.html", html)
        except Exception:
            pass
    S["close_in_bcid"] = b
    pot = parse_pot(html)
    rows = {k: dict(r, src="C", folder="close-in") for k, r in pot.items() if k not in regular}
    cache = S.get("details") or {}
    if full or any(k not in cache or "duties" not in cache[k] for k in rows):
        time.sleep(random.uniform(1.5, 3.5))  # pot_details paces its own reads after the first
    pot_details(fl, rows, full)
    pend = S.setdefault("pickup_pending", {})
    moved = {k for k in rows if k in set(moved_from or ()) or k in pend}
    if moved:  # the regular pot gave the trip up to this folder (at 16 h to report): the same find, not a new one
        log.info("close-in %s: %s moved here from the regular pot (no new alert)", b, ", ".join(sorted(moved)))
        DB.move_finds(moved, CLOSE_IN_KEY)
    for k in rows:
        pend.pop(k, None)  # open in this folder: neither picked up nor hidden by scheduling
    base, new_keys = ci.get("baseline"), set()
    if base is None:
        log.info("close-in baseline %s: %d pairings (no alert)", b, len(pot))
    else:
        new_keys = {k for k in rows if k not in base and k not in moved}
        for k in sorted(new_keys):
            ev = {**rows[k], "month": CLOSE_IN_KEY, "seen": now_iso()}
            if not ev.get("detail_url"):  # details not read yet (pot_details' per-check cap)
                time.sleep(random.uniform(1.5, 3.5))
                enrich(fl, ev)
            log.info("NEW close-in pairing %s", ev)
            pub("event/new_pairing", ev, retain=False)
            pub("last_new", ev)
            run_rules(CLOSE_IN_KEY, k, rows[k])
        for k in set(base) - set(pot) - set(regular):
            pend.setdefault(k, {"tries": 0, "next": time.time() + PICKUP_FIRST_S})
    DB.record_pot(CLOSE_IN_KEY, {k: rows.get(k) or regular[k] for k in pot}, new_keys)
    ci["baseline"] = sorted(pot)
    CLOSE_IN_LAST.update(bcid=b, at=time.time(), rows={k: dict(r) for k, r in rows.items()})
    return rows, "ok"


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
        if not S.get("req_view_captured", {}).get(n) and cap_on():
            S.setdefault("req_view_captured", {})[n] = True
            try:
                cap_write(f"otrequest_view_{n}.html", html)
                log.info("request view %s captured; text: %s", ts, text[:600])
            except Exception:
                pass
        return SUB.parse_request_view(text)
    except Exception as e:
        log.info("request view %s error: %s", ts, e)
        return {}


REQ_VIEW_TRIES = 3  # FW-0064 review: view page reads of one pending request whose legs could not be read
REQ_VIEWS_PER_READ = 3  # new pending view pages per folder per list read (each request's page is read once)


def _pending_legs(fl, b, rows):
    """FW-0064 review: the list names no trips, so a Pending or Processing request read with its id (ts) has no legs,
    and trades.match_pending could not match it on the schedule (a swap approved there would go out as a trade with
    no request on file, then again as the Swap). Its read-only view page is read once (_request_view: both safe_get
    guards, paced), at most REQ_VIEWS_PER_READ new ones per read, and its legs and trips kept by folder and ts in
    S['req_views'] (pruned to the rows listed) and put on the row."""
    views = S.setdefault("req_views", {})
    listed, n = set(), 0
    for r in rows:
        if r.get("status") not in SUB.OPEN or not r.get("ts") or r.get("legs"):
            continue
        k = f"{b}|{r['ts']}"
        listed.add(k)
        v = views.get(k)
        if (v is None or (not v.get("ok") and v.get("tries", 0) < REQ_VIEW_TRIES)) and n < REQ_VIEWS_PER_READ:
            n += 1
            got = _request_view(fl, b, r["ts"])
            v = views[k] = {"ok": bool(got.get("legs")), "tries": (v or {}).get("tries", 0) + 1,
                            "legs": got.get("legs") or [], "trips": got.get("trips") or []}
        if v and v.get("legs"):
            r["legs"] = v["legs"]
            if v.get("trips") and not r.get("trips"):
                r["trips"] = v["trips"]
    for k in [k for k in views if k.startswith(f"{b}|") and k not in listed]:
        views.pop(k, None)


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
    force = S.pop("req_force", False)
    if not force and time.time() - S.get("req_checked_at", 0) < gap:
        return
    if not opt_fits(len(folders) + len({b.split(".")[-1] for b in regular})):  # 1.7.1 (LIVE-1): the lists and trades
        if force:
            S["req_force"] = True  # still owed: the next check with room reads it
        return
    S["req_checked_at"] = time.time()
    pushed = S.setdefault("ot_req_pushed", {})
    empty = S.setdefault("ot_req_empty", {})
    first = not S.get("ot_req_init")
    now = datetime.now(HST)
    read_ok = False
    for b in folders:
        url = SUB.requests_url(BASE, b)
        if not BRK.allow("requests"):  # 1.6.2: the request list reads are stopped (the breaker's note says why)
            break
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
            if not S.get("req_captured", {}).get(n) and cap_on():  # first read: a private copy for parser checks
                try:
                    cap_write(f"otrequests_{n}.html", html)
                    S.setdefault("req_captured", {})[n] = True
                    log.info("requests %s: %d rows, page captured; text: %s", b, len(rows), text[:600])
                except Exception:
                    pass
            ids = SUB.request_ids(html)
            if len(ids) != len(rows) or re.search(r"\b(trade|processing)\b", text, re.I):
                # 1.4.2: a row the parser does not know (Ryan's Nov 6 Trade was missed): keep a private copy of the
                # latest such page (/share, never git) and say how many requests the page has against rows read
                try:
                    cap_write(f"otrequests_{n}_latest.html", html)
                except Exception:
                    pass
                if S.get("req_mismatch_logged", {}).get(n) != len(ids):
                    S.setdefault("req_mismatch_logged", {})[n] = len(ids)
                    log.info("requests %s: %d requests on the page, %d rows read; latest page captured", b, len(ids), len(rows))
            if not SUB.is_request_page(text, rows):
                log.info("requests %s: not the request list, skipped: %s", b, text[:120])
                BRK.fail("requests", "not the request list (a page the parser does not know)", "unknown")  # 1.6.2
                continue
            if not rows and rows_of.get(b) and empty.get(b, 0) < 1:  # a list gone empty must read so twice
                empty[b] = empty.get(b, 0) + 1
                log.info("requests %s: list empty after %d rows, read again before believing it", b, len(rows_of[b]))
                continue
            empty.pop(b, None)
            _pending_legs(fl, b, rows)  # FW-0064 review: a pending swap's trips, so the schedule can decide it
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
            if rows and rows[-1].get("ts") and not S.get("req_view_captured", {}).get(n) and cap_on():
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
        except GT.GateAbort:
            raise
        except GT.BreakerOpen as e:  # 1.6.2 review: left out by the gate: not a failed read; the rest still publishes
            log.info("requests %s skipped: %s", b, e)
            break
        except Exception as e:
            log.info("requests %s error: %s", b, e)
    try:
        tb_ok = _trade_requests_check(fl, regular, trows_of, pushed, now)
    except GT.GateAbort:
        raise
    except GT.BreakerOpen as e:  # 1.6.2 review: the Tradeboard path stopped or left out: the request list still publishes
        log.info("trade requests skipped: %s", e)
        tb_ok = False
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
            if (not S.get("tbreq_captured", {}).get(n) or odd) and cap_on():
                try:
                    cap_write(f"tb_myrequests_{n}{'_latest' if odd else ''}.html", html,
                              extra=[str(r.get("emp") or "") for r in rows])
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
        except GT.BreakerOpen:  # 1.6.2 review: given up or left out by the gate: not a failed read
            raise
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
    # 1.7.2 fix pass: a trip removed for pay protection (its first day now PAYP; it keeps its Pay and Credit, PWA
    # Definitions 57) was not given away, so it is never part of a trade, priced as a loss; a trip added on the PAYP
    # days pays on top (PWA 4.R.1). Also an earlier read's drop whose PAYP shows only now
    pp = [(i["start"], i.get("end") or i["start"]) for i in new_items or [] if i.get("trip") == VER.PAYP and i.get("start")]
    for m in (S.get("sched_moves") or []) + mv:
        if (pp and m.get("side") == "drop" and m.get("state") == "open" and m.get("month") == month
                and any(s <= str(m.get("start") or "") <= e for s, e in pp)):
            m.update(state="explained", by="pay protected")
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
    nums = sorted({b.split(".")[-1] for b in (bcid(u) for u in S.get("pot_urls", {}).values()) if b})
    if not opt_fits(2 * len(nums)):  # 1.7.1 (LIVE-1): a pilot's read waits for room for its frame and its list
        return
    S["tb_checked_at"] = time.time()
    base = S.setdefault("tb_baseline", {})
    tb_cache = S.setdefault("tb_details", {})  # 0.4.6: enriched pickup posts, one detail GET each
    live = {}
    read_ok = False
    left = {"out": False, "keep": 0}
    fresh = set()  # the new posts whose details this read just read

    def detail(ev):
        """1.7.1 review: enrich() while this read has room for the detail and for the frames and lists of the bid
        months still to read (a pilot's budget; the admin always has room). A detail left out (GateSkip, or no room)
        only screens the row from its list (screen_row) and never ends the read, so its baseline is saved, every bid
        month is read and the board is published: a post pushed is never pushed again by the next read. True when the
        detail was read (the row may be cached)."""
        why = "no room for them in this pilot's FLICA budget"
        if not left["out"] and opt_fits(1 + left["keep"]):
            try:
                enrich(fl, ev)
                return True
            except GT.GateSkip as e:
                left["out"], why = True, str(e)  # no more detail loads in this read
        if "tradeboard_check details" not in RUN["skipped"]:
            RUN["skipped"].add("tradeboard_check details")
            log.info("tradeboard_check details left out of this check (%s): %s", why, ev.get("pairing"))
        screen_row(ev)
        return False

    for pos, n in enumerate(nums):
        key = f"tb2_{n}"
        left["keep"] = 2 * (len(nums) - pos - 1)  # the frames and lists of the bid months after this one
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
                             page_log(flat[max(0, i - 300):i + 5000]))
                    try:
                        cap_write(f"tradeboard_{n}.html", fh + "\n<!--OTHER-->\n" + html,
                                  extra=[str(r.get("poster") or "") for r in picks.values()])
                    except Exception:
                        pass
                continue
            if not TB_PROBE["done"]:
                TB_PROBE["done"] = True
                log.info("tradeboard probe %s url=%s pickups=%s text=%s", n, url.split("?")[0],
                         page_log(str(list(picks))), page_log(visible_text(html)[:1500]))
            old = base.get(key)
            if old is None:
                log.info("tradeboard baseline %s: %d pickup posts (no alert)", key, len(picks))
            else:
                for k in sorted(set(picks) - set(old)):
                    ev = {**picks[k], "month": key, "seen": now_iso()}
                    if detail(ev):  # 1.7.1 review: its details kept, so the post costs one detail GET, not two
                        tb_cache[k] = {f: v for f, v in ev.items() if f not in ("month", "seen")}
                        fresh.add(k)
                    log.info("NEW tradeboard pickup %s", ev)
                    pub("event/new_pairing", ev, retain=False)
                    pub("last_tradeboard", ev)
                    # 1.7.1 review: in the baseline at once, so a read that ends later (Pause) never pushes it again
                    base[key] = sorted(set(base.get(key) or ()) | {k})
            base[key] = sorted(picks)
            pub(f"tradeboard/{key}", {"count": len(picks), "posts": list(picks.values())[:40]})
            read_ok = True
            for k, row in picks.items():
                cached = tb_cache.get(k)
                if cached is None or (full and k not in fresh):
                    row = {**row}
                    if detail(row):
                        tb_cache[k] = cached = row
                    else:
                        cached = cached or row  # left out: the details read before, else the list's row, not cached
                live[k] = cached
        except GT.BreakerOpen:  # 1.6.2 review: given up or left out by the gate: not a failed read
            raise
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
        # far_why and the smart fields off the sensor, as on pot/state (a new post's event/new_pairing carries them)
        rows.append(sensor_row(r))
    pub("tradeboard/state", {"count": len(rows), "pairings": rows})


GRID_MIN_GAP_S = 300
GRID_RENDER_GAP_S = 1800


def grid_check(fl, full=False):
    """0.4.13 (Ryan): read the Reserve Grid for each watched pot month. The JSON service behind the
    page is tried first (one GET); the rendered page is the fallback and also a cross-check every
    30 min. Publishes {date: {net, color}} on flight_watcher/grid/state. Read only."""
    if not full and time.time() - S.get("grid_at", 0) < GRID_MIN_GAP_S:
        return
    pages = sum(1 for u in S.get("pot_urls", {}).values() if bcid(u))
    render_due = full or time.time() - S.get("grid_rendered_at", 0) > GRID_RENDER_GAP_S
    if not opt_fits(pages * (2 if render_due else 1)):  # 1.7.1 (LIVE-1): a pilot's read waits for room for all of it
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
                log.info("reserve grid json %s: %s", b, page_log(raw[:1500]))
            got = G.parse_grid_json(data, yr)
        except GT.BreakerOpen:  # 1.6.2 review: given up or left out by the gate: not a failed read
            raise
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
            except GT.GateSkip as e:  # 1.7.1 (LIVE-1): the cross-check left out keeps the JSON just read
                if not got:
                    raise
                log.info("reserve grid render %s left out: %s (the JSON read is kept)", b, e)
            except GT.BreakerOpen:  # 1.6.2 review: given up or left out by the gate: not a failed read
                raise
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
    of every form to the private captures folder so the live swap can be built from real pages.
    1.5.0 (FW-0063): the admin's only (auto_swap); a pilot instance loads nothing."""
    if not has("auto_swap"):
        return
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


# ---------------------------------------------------------------- 1.6.2 (Release A item 11): a pilot's name lookup
LOOKUP_MIN_LETTERS = 3  # of the last name
LOOKUP_PREFIX_MIN = 5  # 1.6.2 review: a last name matches whole; only this many letters or more also match its start
LOOKUP_PER_H = 20  # 1.6.2 review: name queries an hour (the roster cannot be walked letter by letter)
LOOKUP_MAX = 5  # matches shown (name and seat); more is no list: type more of the name
PICK_TTL_S = 1800  # a pick-list entry stays usable this long
LOOKUP_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z '.-]*(?:,\s*[A-Za-z][A-Za-z '.-]*)?$")  # letters only: no wildcard
AWARD_SEAT_RE = re.compile(r"\b[AB]\d{3}\s*(CA|FO)\b[^\n]{0,40}\bAWARD\b", re.I)
_NAME_DIR = {"sig": None, "rows": []}
PICK_SALT = os.urandom(8).hex()


def _nkey(s):
    return re.sub(r"[^A-Z]", "", str(s or "").upper())


def name_directory():
    """1.6.2 (item 11): [{emp, last, first, name, seat}] of every pilot on the files every instance already receives:
    the shared seniority list (seniority.json: 'Last, First', seat) and the PBS award texts (<YYYY-MM>_award.txt: the
    'SSSSS / EMP' line, the last name on it or on the next line, the seat from the award's title, e.g. 'A332FO ...
    AWARD'). Never the admin's crew index or contact list. The list's record wins for an employee number on both.
    Cached by the files' times."""
    try:
        awards = sorted(f for f in os.listdir(UPLOADS) if re.fullmatch(r"\d{4}-\d{2}_award\.txt", f))
    except OSError:
        awards = []
    paths = [os.path.join(UPLOADS_SHARED, "seniority.json")] + [os.path.join(UPLOADS, f) for f in awards]
    sig = tuple((p, os.path.getmtime(p)) for p in paths if os.path.exists(p))
    if _NAME_DIR["sig"] == sig:
        return _NAME_DIR["rows"]
    rows = {}
    for f in reversed(awards):  # the newest award first
        try:
            lines = open(os.path.join(UPLOADS, f), errors="replace").read().split("\n")
        except OSError:
            continue
        m = AWARD_SEAT_RE.search("\n".join(lines[:40]))
        seat = m.group(1).upper() if m else ""
        for i, ln in enumerate(lines):
            g = SEN.AWARD_PILOT_RE.match(ln)
            if not g:
                continue
            emp = g["emp"].lstrip("0")
            name = SEN._award_name(g["rest"]) or (SEN._award_name(lines[i + 1]) if i + 1 < len(lines) else "")
            if emp and name and emp not in rows:
                last, _, first = (x.strip() for x in name.partition(","))
                rows[emp] = {"emp": emp, "last": last.title(), "first": first.title(), "seat": seat}
    for k, rec in ((seniority_data() or {}).get("pilots") or {}).items():
        for r in [rec] + list(rec.get("also") or []):
            name = str(r.get("name") or "")
            last, _, first = (x.strip() for x in name.partition(","))
            if k and last:
                rows[k] = {"emp": k, "last": last.title(), "first": first.title(),
                           "seat": str(r.get("seat") or (rows.get(k) or {}).get("seat") or "").upper()[:2]}
    out = [dict(r, name=f"{r['last']}, {r['first']}".strip(" ,")) for r in rows.values()]
    _NAME_DIR.update(sig=sig, rows=out)
    return out


def name_lookup(q):
    """1.6.2 (item 11): (matches, why) for a typed name on a pilot instance: at least LOOKUP_MIN_LETTERS letters of
    the last name, letters only (no wildcard, no listing), 'Last' or 'Last, First'. A last name that matches exactly
    wins over longer ones that start with it. why is '' or the reason no list is given."""
    if not LOOKUP_NAME_RE.fullmatch(q):
        return [], "Type letters only: a last name, or Last, First (or the employee number)."
    last, _, first = (x.strip() for x in q.partition(","))
    lk, fk = _nkey(last), _nkey(first)
    if len(lk) < LOOKUP_MIN_LETTERS:
        return [], f"Type at least {LOOKUP_MIN_LETTERS} letters of the last name (or the employee number)."
    rows = name_directory()
    exact = [r for r in rows if _nkey(r["last"]) == lk]
    # 1.6.2 review: the start of a last name matches only from LOOKUP_PREFIX_MIN letters on (3-letter prefixes walked
    # the whole roster); a whole last name always does, and wins over longer ones that start with it
    hits = exact or ([r for r in rows if _nkey(r["last"]).startswith(lk)] if len(lk) >= LOOKUP_PREFIX_MIN else [])
    if fk:
        hits = [r for r in hits if not r["first"] or _nkey(r["first"]).startswith(fk)]
    hits.sort(key=lambda r: (r["name"], r["emp"]))
    if not hits:
        return [], (f"No pilot named '{q}' on the award or seniority list on file. Type the whole last name (or "
                    f"{LOOKUP_PREFIX_MIN} letters of it), or the employee number."
                    if rows else "No award or seniority list is on file to look names up in. Type the employee number.")
    if len(hits) > LOOKUP_MAX:
        return [], (f"More than {LOOKUP_MAX} pilots match '{q}'. Type more of the last name, or Last, First, or the "
                    "employee number.")
    return hits, ""


def pick_id(emp):
    """1.6.2: the opaque id a pick-list entry carries instead of the employee number (this process only)."""
    return hashlib.sha256(f"{PICK_SALT}|{emp}".encode()).hexdigest()[:12]


LOOKUP_WAIT_STATES = ("paused", "yielded", "backoff", "needs_settings")


def pilot_unreadable_status(html):
    """1.7.3 (F#55's live run, Nov 14): the Pilot card's line when the lookup's schedule page is not readable. FLICA's
    application error page (inflt.ERROR_HINTS) was shown raw ('not readable: ok flica.net - application error ... http/1.1
    200 ok\\nex'); it is a plain line now, and any other page's text is kept to one short line."""
    text = LOG_CTRL_RE.sub("", re.sub(r"\s+", " ", visible_text(html or ""))).strip()
    if any(h in text.lower() for h in IF.ERROR_HINTS):
        # review: the Pilot card turns a status matching /application error|customer care/ into its own friendly line
        return "not readable: FLICA application error, try again later"
    return f"not readable: {classify(html or '')} {text[:100]}".strip()[:140]


def pilot_cmd(payload):
    """MQTT flight_watcher/pilot/set {"emp": "10001", "name": "..."}: show that pilot's current month on the
    dashboard. Served from a 6 h cache when fresh, else read on the next check (Schedule Lookup + the
    pairing pages, GET only). 1.6.2 (item 11): on a pilot instance a name is looked up only on the award and
    seniority list files (name_lookup: 3 letters at least, at most 5 matches, name and seat; each match carries an
    opaque 'pick' id, never the employee number, and {"pick": id} runs it); '#10001' is an employee number.
    1.7.2 (contract 1 revision 3, F#49): on every instance the payload must have the pilot/set shape (roles.SHAPE_CMDS:
    keys emp, q, name and pick only; emp 1 to 7 digits; q and name at most 60 code points on one line; pick 12 hex),
    the same the portal's spool and HOM check; anything else is refused with one log line that never carries the
    text."""
    try:
        PT.check_shape("pilot/set", payload)
    except PT.PortalError as e:
        log.info("pilot lookup refused: %s", e)
        return
    try:
        d = json.loads(payload)
        emp = re.sub(r"\D", "", str(d.get("emp") or ""))
    except (ValueError, AttributeError):
        d, emp = {}, ""
    if not isinstance(d, dict):
        d = {}
    q = str(d.get("q") or "").strip()[:80]
    if ROLES.role(INSTANCE) == ROLES.PILOT and not emp:
        if d.get("pick"):
            p = (S.get("pilot_picks") or {}).get(str(d["pick"]))
            if not p or time.time() - float(p.get("at") or 0) > PICK_TTL_S:
                pub_pilot({"emp": "", "name": str(d.get("name") or "")[:60], "matches": [], "month": "", "days": [],
                           "items": [], "totals": {}, "updated": "", "fetched": "", "at": now_iso(),
                           "status": "That pick list is old: type the name again."})
                return
            emp, d["name"] = p["emp"], p["name"]
        elif q:
            digits = re.sub(r"[#\s]", "", q)
            if digits.isdigit():
                emp = digits
            else:
                now = time.time()
                asked = [t for t in S.get("name_queries") or [] if 0 <= now - t < 3600]
                if len(asked) >= LOOKUP_PER_H:  # 1.6.2 review: a per-hour cap, said as a status line
                    pub_pilot({"emp": "", "name": q, "at": now_iso(), "matches": [], "month": "", "days": [],
                               "items": [], "totals": {}, "updated": "", "fetched": "",
                               "status": f"{LOOKUP_PER_H} name lookups in the last hour: the next one at "
                                         f"{hst_hm(asked[len(asked) - LOOKUP_PER_H] + 3600)} HST (or type the "
                                         "employee number)."})
                    return
                S["name_queries"] = asked + [now]
                hits, why = name_lookup(q)
                # 1.6.2 review: even one match is a pick list (name and seat): its employee number is used, and shown,
                # only once the pilot picks it
                picks = {pick_id(h["emp"]): {"emp": h["emp"], "name": h["name"], "at": time.time()} for h in hits}
                S["pilot_picks"] = picks
                save_state(S)
                pub_pilot({"emp": "", "name": q, "at": now_iso(),
                           "status": why or (f"1 pilot matches '{q}': tap the name to read the month" if len(hits) == 1
                                             else f"{len(hits)} pilots match '{q}', pick one"),
                           "matches": [{"pick": k, "name": v["name"], "pos": h["seat"]}
                                       for (k, v), h in zip(picks.items(), hits)],
                           "month": "", "days": [], "items": [], "totals": {}, "updated": "", "fetched": ""})
                return
        q = ""
    if not emp and q:  # 0.8.2 (Ryan): free text: an employee number, or a name from the crew directory
        if q.isdigit():
            emp = q
        else:
            hits = DB.find_crew(q)
            ct = None if hits else contact_emp(q)  # FW-0066: a name only the contact list has
            if ct:
                emp, d["name"] = ct
            elif len(hits) == 1:
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
    pilotver_register(emp, d.get("name") or "")  # FW-0069: Ryan looked this pilot up: his versions are kept
    S["pilot_req"] = {"emp": emp, "name": d.get("name") or "", "at": now_iso()}
    save_state(S)
    cached = DB.get(f"pilot_sched:{emp}")
    if cached and time.time() - cached.get("fetched_ts", 0) < PILOT_CACHE_S:
        pub_pilot({**cached, "status": "cached"})
        S.pop("pilot_req", None)
        save_state(S)
        log.info("pilot %s: schedule served from cache", emp)
        return
    m = S.get("machine") or ""
    if ROLES.role(INSTANCE) == ROLES.PILOT and (m in LOOKUP_WAIT_STATES or m.startswith("stopped")):
        # 1.6.2 (item 11): say why it waits, instead of a loading line that never ends (pilot_req is kept)
        pub_pilot({"emp": emp, "name": d.get("name") or "", "month": "", "days": [], "items": [], "totals": {},
                   "updated": "", "fetched": "", "at": now_iso(),
                   "status": f"waiting: your Watcher is {m.replace('_', ' ')}; this lookup runs on its next FLICA check"})
        log.info("pilot %s: schedule requested (waits: %s)", emp, m)
        return
    pub_pilot({"emp": emp, "name": d.get("name") or "", "status": "loading", "month": "", "days": [], "items": [],
                           "totals": {}, "updated": "", "fetched": "", "at": now_iso()})
    log.info("pilot %s: schedule requested", emp)
    if ROLES.role(INSTANCE) == ROLES.ADMIN:  # 1.6.2: a pilot's lookup waits for his next check (no extra FLICA check)
        WAKE.set()


def pilot_check(fl):
    """Read the requested pilot's month (read only) and publish it for the pilot schedule card."""
    req = S.get("pilot_req")
    if not req:
        return False
    if not BRK.allow("lookup"):  # 1.6.2: kept for when Schedule Lookup reads may run again; the card says so
        if (S.get("pilot_paused_said") or "") != req["emp"]:
            S["pilot_paused_said"] = req["emp"]
            pub_pilot({"emp": req["emp"], "name": req.get("name") or "", "month": "", "days": [], "items": [],
                       "totals": {}, "updated": "", "fetched": now_iso(),
                       "status": f"Schedule Lookup reads are paused until {hst_hm(BRK.until('lookup'))} HST; "
                                 "this lookup runs then"})
        return False
    S.pop("pilot_paused_said", None)
    # 0.8.4: does FLICA's Schedule Lookup prompt offer a name search? Save it once. 1.6.2 (item 8): only while this
    # instance takes captures (a pilot loads no page just to save it), and into its own folder (it was the admin's)
    if not S.get("cm_prompt_captured") and cap_on():
        try:
            html = fl.fetch(f"{BASE}/full/cmschedules.cgi?Prompt=1&SchBrowser=1")
            cap_write("cmschedules_prompt.html", html or "")
            log.info("schedule lookup prompt page saved (%d chars): %s", len(html or ""), visible_text(html)[:200])
            S["cm_prompt_captured"] = True
            save_state(S)
            time.sleep(random.uniform(1.5, 3.5))  # 1.6.2: the FLICA pacing rule (was 1.0 to 2.0 s)
        except Exception as e:
            log.info("schedule lookup prompt capture skipped: %s", e)
    emp = req["emp"]
    cur = local_now()
    bd = f"{cur.month:02d}{cur.year % 100:02d}"
    captured = False
    try:
        sched, html = None, ""
        for i, url in enumerate((IF.CM_SCHED.format(base=BASE, emp=emp), IF.CM_SCHED_MONTH.format(base=BASE, emp=emp, bd=bd))):
            if i:
                time.sleep(random.uniform(1.5, 3.5))
            html = fl.fetch(url)
            sched = IF.parse_cm_month(html) if classify(html) == "ok" and IF.schedule_ok(html) else None
            if sched:
                break
            # 1.7.3 review: page text through page_log (a pilot's only while his captures are on, masked): visible_text
            # lowercases the page and the name masks need a capital letter
            log.info("pilot %s: %s gave %s: %s", emp, url.split("?")[1], classify(html), page_log(visible_text(html)[:200]))
        if not sched:
            pilotver_capture_rebuild(emp, req.get("name") or "")  # FW-0069: the crew index's view, when it has one
            pub_pilot({"emp": emp, "name": req.get("name") or "", "status": pilot_unreadable_status(html),
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
        captured = True  # FW-0069: a readable month is the version source (no rebuild below if a later step fails)
        pilotver_capture_lookup(emp, rec)  # a new version when the pairings changed
        pub_pilot({**rec, "status": "ok"})
        log.info("pilot %s (%s): %s read, %d items, %d pairing pages", emp, rec["name"], sched["month"], len(sched["items"]), n)
        lookup_prev_month(fl, emp, cur)  # FW-0057: trips run into this month from the previous one (the next run reads them)
    except Exception as e:
        log.info("pilot %s: schedule read failed: %s", emp, e)
        if not captured:
            pilotver_capture_rebuild(emp, req.get("name") or "")  # FW-0069
        pub_pilot({"emp": emp, "name": req.get("name") or "", "status": f"error: {e}", "month": "", "days": [],
                               "items": [], "totals": {}, "updated": "", "fetched": now_iso()})
    S.pop("pilot_req", None)
    save_state(S)
    return True


PREV_LOOKUP_TRIES = 2  # FW-0057: reads of one pilot's previous bid month that may fail before it is left alone


def lookup_prev_month(fl, emp, cur):
    """FW-0057 review: a trip another pilot started in the previous bid period and runs into this one is on no
    schedule the Watcher reads, and in no pairing file when that period's package is not on file (Pako has no
    October file). So when CARD_PAIRINGS has no pairings_<previous month>.json, a pilot lookup also reads that pilot's
    previous bid month once (Schedule Lookup, GET only, both safe_get guards, paced 1.5 to 3.5 s) and notes the trips
    on it that end on or after the day before this month starts (a bid period can start on the 31st) for the crew
    index (note_sched_trips). Once per pilot and month (DB 'pilot_prev:<emp>:<YYYY-MM>'; a failed read is tried again
    at most PREV_LOOKUP_TRIES times). Ryan's instance only (the crew index's). Returns the number of new trips."""
    if not has("crew_index"):
        return 0
    first = date(cur.year, cur.month, 1)
    prev = first - timedelta(days=1)
    pm = f"{prev:%Y-%m}"
    if os.path.exists(os.path.join(CARD_PAIRINGS, f"pairings_{pm}.json")) or prev < CREW_FROM:
        return 0  # the package lists those trips, or the index does not reach back that far
    key = f"pilot_prev:{emp}:{pm}"
    st = DB.get(key) or {}
    if st.get("done") or st.get("tries", 0) >= PREV_LOOKUP_TRIES:
        return 0
    url = IF.CM_SCHED_MONTH.format(base=BASE, emp=emp, bd=f"{prev.month:02d}{prev.year % 100:02d}")
    if not (SUB.safe_get(url) and SM.safe_get(url)):
        log.info("pilot %s: previous month url refused by safe_get", emp)
        return 0
    time.sleep(random.uniform(1.5, 3.5))
    try:
        html = fl.fetch(url)
        sched = IF.parse_cm_month(html) if classify(html) == "ok" and IF.schedule_ok(html) else None
    except Exception as e:
        html, sched = "", None
        log.info("pilot %s: previous month read failed: %s", emp, e)
    if not sched:
        DB.put(key, {"tries": st.get("tries", 0) + 1, "at": now_iso()})
        log.info("pilot %s: previous month %s not readable (%s)", emp, pm, classify(html or "") if html else "no page")
        return 0
    floor = prev.isoformat()
    into = [it for it in sched["items"] if (it.get("end") or it.get("start") or "") >= floor]
    n = note_sched_trips(into, "lookup")
    DB.put(key, {"done": True, "at": now_iso(), "trips": len(into)})
    log.info("pilot %s: previous month %s read, %d trips run into this month (%d new for the crew index)", emp, pm,
             len(into), n)
    return n


# ---------------------------------------------------------------- FW-0069 other pilots' schedule versions (pilotver.py)
PILOT_PUB_LOCK = threading.Lock()  # pub_pilot's list file write and sensor publish, one thread at a time
PILOT_SHOWN = {"p": {}}  # "p": the last pilot_schedule payload pub_pilot sent (before its crew index fields), swapped
# whole (pub_pilot runs on the MQTT thread too); republished when a capture after a crew index run or a late award adds
# a version for the pilot the card shows


def shown_emp():
    return str((PILOT_SHOWN["p"] or {}).get("emp") or "")


def pilot_award(emp, month):
    """FW-0069: one pilot's awarded line for a bid month from the award text on file (the shared uploads folder,
    <YYYY-MM>_award.txt, as uploads_check reads it; pdfs.parse_award with that month's pairing package details and
    period start), or None (no award or package on file, the pilot not in it, a header the parser cannot read)."""
    path = os.path.join(UPLOADS, f"{month}_award.txt")
    det = pkg_details_for(month) if os.path.exists(path) else None
    if not det:
        return None
    try:
        return PDF.parse_award(open(path, errors="replace").read(), emp, det, month, pairings_start(month))
    except ValueError:
        return None


def pairings_start(month):
    """The bid period's first day from the month's pairing file (FW-0015: the award's columns start there), else None."""
    try:
        return json.load(open(os.path.join(CARD_PAIRINGS, f"pairings_{month}.json"))).get("start")
    except (OSError, ValueError, AttributeError):
        return None


def pilotver_register(emp, name=""):
    """FW-0069: Ryan looked this pilot up (pilot_cmd, on the MQTT thread): keep his versions from now on."""
    try:
        PV.register(DB, emp, name, now_iso())
    except Exception as e:
        log.info("pilot %s: versions registry skipped: %s", emp, e)


def pilotver_capture_lookup(emp, rec):
    """FW-0069: a readable Schedule Lookup (rec as pilot_check stores it) becomes a version when its pairings changed.
    No FLICA traffic. Never raises."""
    try:
        PV.register(DB, emp, rec.get("name") or "", now_iso())
        first, _, end = CI.grid_range(CARD_PAIRINGS, rec["month"])
        made = PV.capture_lookup(DB, emp, rec.get("name") or "", rec, now_iso(), (first, end), pilot_award)
        if made:
            log.info("pilot %s: schedule version %s (%s, FLICA schedule)", emp, ", ".join(made), rec["month"])
        return made
    except Exception as e:
        log.info("pilot %s: schedule version skipped: %s", emp, e)
        return []


def pilotver_capture_rebuild(emp, name="", month=None, insts=None, rows=None):
    """FW-0069: the crew index's rebuild of one pilot's bid month (the current one by default) becomes a version when
    it changes the pairings (pilotver.merge_rebuild). insts / rows: the crew index when the caller has it. No FLICA
    traffic. Never raises. Returns the version labels made."""
    try:
        month = month or local_now().strftime("%Y-%m")
        insts = crew_instances() if insts is None else insts
        rows = DB.crew_rows() if rows is None else rows
        first, start, end = CI.grid_range(CARD_PAIRINGS, month)
        trips = CI.pilot_trips(insts, DB.crew_by_emp(emp), month, first, rows, pkg_details_for, end)
        made = PV.capture_rebuild(DB, emp, name, month, trips, rows, now_iso(), (first, end), start, end, pilot_award)
        if made:
            log.info("pilot %s: schedule version %s (%s, rebuilt from crew lists)", emp, ", ".join(made), month)
        return made
    except Exception as e:
        log.info("pilot %s: rebuilt schedule version skipped: %s", emp, e)
        return []


def pilotver_run_end(insts=None):
    """FW-0069: after each crew index run, a rebuilt version for every pilot Ryan looked up, for each bid month the
    index holds from the current one on (Ryan's instance only, as the crew index is). The card's pilot is
    republished when he got one. Never raises. Returns the number of pilot-months that got a version."""
    if not has("crew_index"):
        return 0
    try:
        emps = PV.registered(DB)
        if not emps:
            return 0
        insts = crew_instances() if insts is None else insts
        rows = DB.crew_rows()
        cur = local_now().strftime("%Y-%m")
        months = sorted({m for m in (CI.period_of(it) for it in insts.values()) if m and m >= cur})
        names = {e: (v.get("name") or "") for e, v in (DB.get(PV.INDEX_KEY) or {}).items()}
        n, shown = 0, False
        for emp in emps:
            for month in months:
                if pilotver_capture_rebuild(emp, names.get(emp, ""), month, insts, rows):
                    n += 1
                    shown = shown or emp == shown_emp()
        if n:
            log.info("crew index: %d pilot schedule version(s) from this run", n)
        if shown:
            pub_pilot(dict(PILOT_SHOWN["p"]))
        return n
    except Exception as e:
        log.info("crew index: pilot schedule versions skipped: %s", e)
        return 0


def pilotver_awards(month, text, det):
    """FW-0069: an award uploaded after pilots' versions of its month were made goes in as each one's .001 (the rest
    renumbered). Never raises. Returns the number of pilots it changed."""
    try:
        start = pairings_start(month)
        first, _, end = CI.grid_range(CARD_PAIRINGS, month)
        n = 0
        for emp in PV.registered(DB, month):
            try:
                aw = PDF.parse_award(text, emp, det, month, start)
            except ValueError:
                continue  # no date header above his line, or (1.7.2) his line cut off: the next pilot's may read
            if aw and PV.set_award(DB, emp, month, aw, now_iso(), (first, end), first):
                n += 1
                log.info("pilot %s: awarded line is schedule version %s.001", emp, int(month[5:7]))
                if emp == shown_emp():
                    pub_pilot(dict(PILOT_SHOWN["p"]))
        return n
    except Exception as e:
        log.info("pilot schedule versions: award skipped: %s", e)
        return 0


def pilotver_attrs(emp):
    """FW-0069: the pilot card's versions: the list file pilotver_<key>.json (this pilot's versions, written only when
    it changed) and the sensor's short form. {} when it fails (the card then shows no versions bar)."""
    try:
        emp = re.sub(r"\D", "", str(emp or ""))
        key, rev = write_list_file("pilotver", PV.history(DB, emp) if emp else {})
        return {"versions_file_key": key or "", "versions_rev": int(rev, 16) if rev else 0,
                "versions": PV.summary(DB, emp) if emp else {}}
    except Exception as e:
        log.info("pilot lookup: versions skipped: %s", e)
        return {}


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
    that cannot be priced trip by trip.
    FW-0069: it also writes that pilot's schedule versions to pilotver_<key>.json and adds versions_file_key,
    versions_rev (a number) and versions {YYYY-MM: {count, current, awarded}} (pilotver_attrs)."""
    PILOT_SHOWN["p"] = {k: v for k, v in (payload or {}).items() if k not in (
        "reconstructed", "reconstructed_coverage_pct", "reconstructed_month", "reconstructed_from", "reconstructed_to",
        "pay_line", "contact", "versions_file_key", "versions_rev", "versions")}
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
                   # 1.6.2 (item 11): no coverage on a pilot (no crew index runs there: only the crew lists of pages
                   # his own Watcher read), so the card shows no 'Crew index ... 0% of trips read' line
                   "reconstructed_coverage_pct": CI.coverage(insts, rows, None, first, end)[2] if has("crew_index") else None,
                   "reconstructed_month": month, "reconstructed_from": start, "reconstructed_to": end}
        payload.pop("contact", None)
        ct = contact_for(emp, payload.get("name") or "") if emp else None
        if ct:  # FW-0066: the one looked-up pilot's phone and email, for the card's call / text / mail links
            payload["contact"] = ct
        if trips:
            try:
                name = payload.get("name") or next((r.get("name") for r in mine if r.get("name")), "")
                payload["pay_line"] = pilot_pay_line(trips, emp, name, start, end)
            except Exception as e:
                log.info("pilot lookup: pay line skipped: %s", e)
    except Exception as e:
        log.info("pilot lookup: crew index skipped: %s", e)
        payload = {**payload, "reconstructed": [], "reconstructed_coverage_pct": 0.0 if has("crew_index") else None}
        emp = re.sub(r"\D", "", str(payload.get("emp") or ""))
        ct = contact_for(emp, payload.get("name") or "") if emp else None
        if ct:
            payload["contact"] = ct
    with PILOT_PUB_LOCK:  # FW-0069: the list file and the sensor that names its rev go out together (two threads publish)
        payload.update(pilotver_attrs(payload.get("emp")))
        # FW-0066 review: a contact never stays in the broker. The retained copy (what HA reads after a restart) has
        # none; the same payload with it follows, not retained, and that is the one the sensor and the card end on.
        pub("pilot_schedule", {k: v for k, v in payload.items() if k != "contact"})
        if payload.get("contact"):
            pub("pilot_schedule", payload, retain=False)


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
CREW_VARIANT_KEY = "crew_variants"  # FW-0068: {base key: {at, found, v}} package trips probed for a rebuilt copy
# (found: the copies, comma separated; v 2 from 1.4.12, when the copies must name every pilot seat)
VARIANT_PER_CHECK = 2  # package trips probed per check (each up to len(CI.VARIANT_LETTERS) pages)
VARIANT_MAX_AGE_D = 35  # a trip that departed longer ago than this is not probed
CREW_VARIANT_TRIES_KEY = "crew_variant_tries"  # 1.7.3: {base key: {n, at, done, fail}} probes cut short so far
# (1.7.3 review: done, the letters answered, are not read again; fail, the letters whose read failed, are read again
# after the letters not read yet)
VARIANT_MAX_TRIES = 3  # 1.7.3: a probe cut short this often (a fetch error, the budget, a stopped pairing path) is
# recorded with what it found once every letter had a try: before, it was probed again every run until VARIANT_MAX_AGE_D


def note_sched_trips(items, src):
    """FW-0056 / FW-0057: remember the pairings on a schedule the Watcher read (Ryan's own months, October's from
    Schedule Lookup included; a pilot lookup's month; a picker's month), so the crew index reads them even when no
    pairing package lists them (H38xx trips built later, a trade's H3815B, October's trips with no October file).
    Items are the schedule parsers' {trip, start[, end]}; anything not a pairing id (VAC, SCR...) is skipped. Kept in
    the DB (CREW_SCHED_KEY); a trip that ended more than CREW_SCHED_KEEP_D days ago is dropped. Ryan's instance only
    (the crew index's). Returns the number of new trips."""
    if not has("crew_index"):
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
                e["end"] = end  # trip end: a trip end cut short by the old item builder grows to the repaired one
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
    if not has("crew_index"):
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
        live = {k: r for k, r in rows.items() if k in insts}  # a trip gone from the index is never flagged or kept
        flags, rr, new, kept, cleared = CI.overlap_update(CI.overlaps(insts, live), f0, r0,
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
    if not has("crew_index") or DB.get("crew_split_v") == 1:
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
    the schedule did not give them (a picker's month lists starts only); the schedule entry keeps them. FW-0068: a
    rebuilt copy the variant probe found (src 'variant') is filled the same way when it is read again."""
    if it.get("src") not in ("schedule", "variant"):
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


def crew_variant_keep(insts, rows, base, vid, vt, crew, at):
    """FW-0068: the rebuilt copy `vid` of package trip `base` named crew on its page: note it with the schedule trips
    (CREW_SCHED_KEY, src 'variant'; its end from the page's day codes, else the package trip's end; route and report
    from the page), store the read and add both to insts / rows."""
    it = insts[base]
    d, got = it["date"], CI.page_trip(vt)
    end = it.get("end_date") or ""
    if got.get("days"):
        end = (date.fromisoformat(d) + timedelta(days=max(int(got["days"]) - 1, 0))).isoformat()
    e = {"pairing": vid, "date": d, "end": end if end >= d else "", "route": got.get("route") or it.get("route") or "",
         "report": got.get("report") or "", "src": "variant", "seen": now_iso()}
    vk = f"{vid}|{d}"
    reg = DB.get(CREW_SCHED_KEY) or {}
    reg[vk] = e
    DB.put(CREW_SCHED_KEY, reg)
    nit = insts[vk] = CI.extra_instance(CARD_PAIRINGS, e)
    DB.crew_put(vk, vid, d, nit["end_date"], nit["route"], crew, at, "ok")
    rows[vk] = {"key": vk, "pairing": vid, "date": d, "end_date": nit["end_date"], "route": nit["route"], "crew": crew,
                "checked_at": at, "status": "ok", "reason": "", "tries": 0}
    DB.remember_crew(vt)


def crew_variants(fl, insts, rows, budget):
    """FW-0068 (Ryan, Nov 8): FLICA rebuilds a package pairing it changes under the same id plus a letter (H3631 flown
    as H3631B on Nov 6) and the crew moves to it: the package trip's page then names no pilot (seats OPEN), and the new
    id is in no package and on no schedule the Watcher can read, so the trip was missing from that pilot's rebuilt
    month. Called during a run, before its queue (so trips read in earlier runs count too). Up to VARIANT_PER_CHECK
    package trips (crewidx.variant_candidates: departed no more than VARIANT_MAX_AGE_D days ago, read after departure,
    no pilot named, bid period awarded, not probed yet), most recently departed first, are probed: the same pairing
    page URL with each lettered id (crewidx.variant_ids; an id already in the index is not read, and when its read
    names a pilot it is the one), GET only, each URL through SUB.safe_get and SM.safe_get, 1.5 to 3.5 s before every
    read, at most `budget` reads. A page that names that id on that date (crewidx.page_names) with a pilot on its crew
    line is the trip flown: crew_variant_keep indexes it. 1.4.12: the letters are read on until the copies found name as
    many pilots as the package trip has pilot seats (FLICA rebuilt H3631 Nov 6 for the captain alone as H3631B), and a
    copy that leaves seats unnamed is logged with its crew line masked (crewidx.crew_mask). The probe is recorded
    (CREW_VARIANT_KEY {base: {at, found, v}}) once every letter was tried or every seat was named; a record from before
    1.4.12 whose copies leave seats unnamed is probed once more; a fetch error leaves the trip for a later run. 1.7.3: a
    copy that does not exist (a page naming the id with nothing on it) is a miss, never a failed pairing read (PROBE); a
    probe cut short after a read (a fetch error, the budget, the pairing path stopped) counts one try
    (CREW_VARIANT_TRIES_KEY) and the VARIANT_MAX_TRIES-th records the trip with what it found; a stopped path or a load
    the gate gave up ends the probe (halted). 1.7.3 review: a try reads on from the letters not read yet (the ones that
    failed come last, a page that stopped the path is no answer), and a trip is parked only once every letter had a
    try. insts and rows are updated in place. Returns (pages read, 'ok' or 'killed' / 'needs_login' / 'stop' when a
    page said so, halted by pause / re-arm or a stopped path). Ryan's instance only. Logs pairing ids and dates, never
    names."""
    if not has("crew_index") or budget <= 0:
        return 0, "ok", False
    now = local_now()
    try:
        reg0 = DB.get(CREW_VARIANT_KEY) or {}
        cut = (now - timedelta(days=VARIANT_MAX_AGE_D + 30)).isoformat(timespec="seconds")
        probed = {k: v for k, v in reg0.items() if str((v or {}).get("at") or "") >= cut}
        for k, v in list(probed.items()):  # 1.4.12: a copy found before 1.4.12 that left seats unnamed: probe again
            if (v or {}).get("v") != 2 and (v or {}).get("found"):
                d = k.split("|", 1)[1]
                named = set()
                for vid in str(v["found"]).split(","):
                    named |= CI.named_pilots((rows.get(f"{vid}|{d}") or {}).get("crew"))
                if len(named) < max(CI.pilot_seats((rows.get(k) or {}).get("crew")), 1):
                    del probed[k]
        if probed != reg0:
            DB.put(CREW_VARIANT_KEY, probed)
        short0 = DB.get(CREW_VARIANT_TRIES_KEY) or {}  # 1.7.3: probes cut short, dropped once recorded or old
        short = {k: v for k, v in short0.items() if k not in probed and str((v or {}).get("at") or "") >= cut}
        if short != short0:
            DB.put(CREW_VARIANT_TRIES_KEY, short)
        run = S.get("crew_run")
        tried = run.setdefault("variant_tried", []) if run else []  # a fetch error: not again in this run
        cands = CI.variant_candidates(insts, rows, now, set(probed) | set(tried), VARIANT_MAX_AGE_D)[:VARIANT_PER_CHECK]
    except Exception as e:
        log.info("crew index: variant probe skipped: %s", e)
        return 0, "ok", False
    n = 0
    for base in cands:
        it = insts[base]
        d, complete = it["date"], True
        reads, stop = 0, None  # 1.7.3: this trip's pages read; the BreakerOpen that ended the probe
        ids = CI.variant_ids(it["pairing"])
        # 1.4.12: FLICA can split a rebuilt trip's crew over two copies (H3631B names the captain only): the copies are
        # read until they name as many pilots as the package trip has pilot seats (its crew line, OPEN seats counted)
        need = max(CI.pilot_seats((rows.get(base) or {}).get("crew")), 1)
        found, got = [], set()
        for v in ids:  # copies indexed already (from a schedule or an earlier probe) whose read names a pilot
            r = rows.get(f"{v}|{d}") or {}
            if f"{v}|{d}" in insts and r.get("status") == "ok" and CI.has_crew(r.get("crew")):
                found.append(v)
                got |= CI.named_pilots(r.get("crew"))
        if found and len(got) >= need:
            log.info("crew index: %s %s flew as %s (indexed)", it["pairing"], d, ",".join(found))
            ids = []
        prev = short.get(base) or {}  # 1.7.3 review: earlier tries' letters answered (not read again) and failed (last)
        done, failed = set(prev.get("done") or ""), set(prev.get("fail") or "")
        ids = [v for v in ids if v[-1] not in done | failed] + [v for v in ids if v[-1] in failed - done]
        for vid in ids:
            vk = f"{vid}|{d}"
            if vk in insts:  # indexed already, read by the queue, not by this probe
                continue
            if n >= budget:
                complete = False
                break
            if FLAGS["pause"] or FLAGS["rearm"]:
                log.info("crew index: pause / re-arm, variant probe stopped (run continues later)")
                return n, "ok", True
            url = (f"{BASE}/full/mobilepairing.cgi?PID={vid}&DATE={d.replace('-', '')}"
                   "&FROM=MobileOpentimePot&CurrentPage=1")
            if not (SUB.safe_get(url) and SM.safe_get(url)):
                log.info("crew index: %s url refused by safe_get, skipped", vk)
                done.add(vid[-1])  # 1.7.3 review: never read, so never left for a later try
                continue
            time.sleep(random.uniform(1.5, 3.5))  # before every read, the first too (pages read before this check)
            n += 1
            reads += 1
            at = local_now().isoformat(timespec="seconds")
            PROBE["miss_ok"] = True  # 1.7.3: a copy that does not exist is a miss, not a failed pairing read
            try:
                page = fl.fetch(url)
            except GT.BreakerOpen as e:  # 1.7.3: nothing loaded (the pairing path stopped, or the gate gave it up)
                n, reads, stop, complete = n - 1, reads - 1, e, False
                break
            except Exception as e:
                log.info("crew index: %s %s probe of %s failed (%s), tried again in a later run", it["pairing"], d, vid, e)
                tried.append(base)
                failed.add(vid[-1])
                complete = False
                break
            finally:
                PROBE["miss_ok"] = False
            kind = classify(page)
            if kind != "ok":
                log.info("crew index: %s page on %s, run ended", kind, vk)
                return n, {"killed": "killed", "expired": "needs_login", "blocked": "stop"}.get(kind, "ok"), False
            if not BRK.allow("pairing"):  # 1.7.3 review: this page stopped the path (one nothing knows): no answer
                failed.add(vid[-1])
                stop, complete = GT.BreakerOpen("pairing", hst_hm(BRK.until("pairing")) + " HST"), False
                break
            vt = visible_text(page)
            crew = CI.crew_line(vt)
            if not CI.page_names(vt, vid, d) or not CI.has_crew(crew):
                if CI.has_crew(crew):  # a page with crew whose header names another trip or date: say what it named
                    hm = re.search(r"pairing details\s+(\S+)", vt or "")
                    log.info("crew index: %s probe page names %s, not %s %s", vid, hm.group(1) if hm else "no pairing", vid, d)
                done.add(vid[-1])
                failed.discard(vid[-1])
                continue  # no such trip that day (an error page, another date's page) or no pilot on it
            try:
                crew_variant_keep(insts, rows, base, vid, vt, crew, at)
            except Exception as e:
                log.info("crew index: %s %s flew as %s, not kept (%s), tried again in a later run", it["pairing"], d, vid, e)
                tried.append(base)
                failed.add(vid[-1])
                complete = False
                break
            done.add(vid[-1])
            failed.discard(vid[-1])
            found.append(vid)
            got |= CI.named_pilots(crew)
            log.info("crew index: %s %s flew as %s (read)", it["pairing"], d, vid)
            if len(got) >= need:
                break
            log.info("crew index: %s %s names %d of %d pilots, the next letters are read too (crew line: %s)", vid, d,
                     len(got), need, CI.crew_mask(vt))
        parked = 0
        if not complete and reads and (stop is None or type(stop) is GT.BreakerOpen):
            # 1.7.3: cut short after a read (not by a pause or a load the gate left out): one try, the last records it
            if stop is not None:
                tried.append(base)  # the path stopped during its probe: not again in this run
            t = int(prev.get("n") or 0) + 1
            failed -= done
            left = [v for v in CI.variant_ids(it["pairing"]) if v[-1] not in done | failed and f"{v}|{d}" not in insts]
            if t >= VARIANT_MAX_TRIES and not left:  # 1.7.3 review: parked only once every letter had a try
                complete, parked = True, t
                log.info("crew index: %s %s probe cut short %d times, not probed again (%s never answered)", it["pairing"],
                         d, t, "/".join(it["pairing"].upper() + c for c in sorted(failed)))
            else:
                short[base] = {"n": t, "at": local_now().isoformat(timespec="seconds"), "done": "".join(sorted(done)),
                               "fail": "".join(sorted(failed))}
                DB.put(CREW_VARIANT_TRIES_KEY, short)
        if complete:
            probed[base] = {"at": local_now().isoformat(timespec="seconds"), "found": ",".join(found), "v": 2}
            if parked:
                probed[base]["parked"] = parked
                if failed:
                    probed[base]["fail"] = "".join(sorted(failed))  # 1.7.3 review: the letters never answered
            DB.put(CREW_VARIANT_KEY, probed)
            if short.pop(base, None) is not None:
                DB.put(CREW_VARIANT_TRIES_KEY, short)
            if not found and not parked:
                log.info("crew index: %s %s, no rebuilt copy names a pilot (%s tried)", it["pairing"], d,
                         "/".join(CI.variant_ids(it["pairing"])))
        if stop is not None:
            log.info("crew index: variant probe stopped (%s), run continues later", stop)
            return n, "ok", True
    return n, "ok", False


def crew_index_check(fl):
    """Read up to CREW_PER_CHECK pairing pages of the current crew index run (GET only, 1.5-3.5 s apart, each URL
    through SUB.safe_get and SM.safe_get). A run starts at the first check after each 6 h slot (once per slot, saved
    in state) or on Update schedules, and reads at most CREW_PER_RUN pages over as many checks as it takes.
    FW-0058 / FW-0059: trips queued for a re-read (CREW_REREAD_KEY: both trips of a pilot on two overlapping trips, a
    crew line cut at a seat code) are read first, one read each; with no run going a check reads just those. A
    re-read that fails keeps the trip's last good read. FW-0068: during a run, each chunk first probes up to
    VARIANT_PER_CHECK departed package trips that name no pilot for the rebuilt copy the crew flew (crew_variants).
    Returns 'ok', or 'killed' / 'needs_login' / 'stop' when a page says so (the run is ended there)."""
    if not has("crew_index"):
        return "ok"
    if not BRK.allow("pairing"):  # 1.6.2: pairing pages stopped: no page is recorded as failed meanwhile
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
    n, res, halted, reread = 0, "ok", False, set()
    per_check = CREW_PER_CHECK_HUNT if FLAGS.get("hunt") else CREW_PER_CHECK  # hunting: short chunks, pot first
    if not run:
        per_check = min(per_check, CREW_REREAD_PER_CHECK)
    if run:
        # FW-0068: package trips whose crew moved to a rebuilt copy (H3631 flown as H3631B), first; their reads
        # count in this chunk and this run
        n, res, halted = crew_variants(fl, insts, rows, min(per_check, CREW_PER_RUN - run["pages"]))
        run["pages"] += n
        todo = [] if res != "ok" or halted else CI.queue(insts, rows, local_now(), run["started"], again)
    else:  # FW-0059: no run going: only the re-reads, soonest first
        todo = sorted(again, key=lambda k: (CI.departs(insts[k]).isoformat(), k))
    awarded = CI.awarded_periods(insts, rows)  # FW-0016: bid periods with a read that named a pilot
    held0 = CI.held_periods(insts, rows, awarded)  # periods already held (their one probe is in todo)
    held, newly = set(held0), False
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
        good = forced and (rows.get(k) or {}).get("status") == "ok"  # a re-read never loses the last good read
        at = local_now().isoformat(timespec="seconds")
        try:
            page = fl.fetch(url)
        except GT.BreakerOpen:  # 1.6.2 review: given up or left out by the gate: not a failed read
            if run:
                run["pages"] -= 1
            raise
        except Exception as e:
            if good:
                log.info("crew index: re-read of %s failed (%s), last read kept; it stays queued", k, e)
            else:
                DB.crew_put(k, it["pairing"], it["date"], it["end_date"], it["route"], None, at, "fail",
                            f"fetch: {e}"[:200])
            continue
        kind = classify(page)
        if kind != "ok":
            res = {"killed": "killed", "expired": "needs_login", "blocked": "stop"}.get(kind, "ok")
            log.info("crew index: %s page on %s, run ended", kind, k)
            break
        if forced:
            reread.add(k)  # FW-0059: a re-read is done once a page came back (a failed fetch stays queued)
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
        if done:
            pilotver_run_end(insts)  # FW-0069: looked-up pilots' rebuilt versions (DB only, no FLICA page)
    elif n:
        log.info("crew index: %d trips read again (no run going)", n)
    if n or done:
        publish_crew_index(insts, write=done or not run)
    if res == "stop":
        set_machine("stopped_unexpected", "FLICA showed a captcha/MFA/password page (crew index)")
    return res


def publish_crew_index(insts=None, write=False):
    """{T}/crew_index (retained) and, after a run, the month Markdown files."""
    if not has("crew_index"):
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
                       # FW-0068: rebuilt copies of package trips (H3631 flown as H3631B) found by the variant probe
                       "from_variants": sum(1 for it in insts.values() if it.get("src") == "variant"),
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
# 1.7.0 (Release C): publish_tickets runs from the MQTT thread (the handlers), the main loop (check) and, on a pilot,
# the uploads janitor: one at a time
TICKETS_LOCK = threading.Lock()
# 1.7.0: a pilot's answers to his own ticket commands (new, image, act, edit, delete), newest first, the last
# TICKET_ANSWERS_KEEP, sent as "answers" on his tickets sensor so his portal card can say "FW-0071 filed" or "Photo 2
# not saved: <why>". The admin's sensor has no answers (his card is unchanged); "last" keeps its FW-0049 meaning.
TICKET_ANSWERS = []
TICKET_ANSWERS_KEEP = 10
PHOTO_ASM = PH.Assembler()  # 1.7.0: a pilot's one photo upload in flight
TICKETS_FIXED_SEEN = "tickets_fixed_seen.json"  # 1.7.0: under DATA; the fixed moves already announced (portal pilot)
TICKETS_FIXED_KEEP = 500


def ticket_limits():
    """1.7.0: this instance's ticket quotas: roles.PILOT_TICKET_LIMITS on a pilot, None (unlimited) on the admin."""
    return ROLES.PILOT_TICKET_LIMITS if is_pilot() else None


def ticket_answer(ref, tid, action, ok, error="", i=None):
    """1.7.0: one answer on a pilot's tickets sensor (never on the admin's). ref is the card's cid or rid."""
    if not is_pilot():
        return
    a = {"ref": ref if isinstance(ref, str) and RID_RE.match(ref) else "", "id": str(tid or "")[:12],
         "action": action, "ok": bool(ok), "error": str(error or "")[:200], "at": now_iso()}
    if i is not None:
        a["i"] = i
    TICKET_ANSWERS.insert(0, a)
    del TICKET_ANSWERS[TICKET_ANSWERS_KEEP:]


def reporter():
    return INSTANCE or "ryan"


# ---------------------------------------------------------------- 1.4.8 FW-0066 uploads for every user
# Ryan, Nov 7: "Make sure that any user can see and upload pairings and awards and seniority lists and pilot contact
# lists." The uploads card of a user who is not an HA admin (no ingress session) sends the file in chunks over
# mqtt.publish to {T}/upload/chunk (chunks.py); this instance stages, checks and saves it with web.save_upload into the
# shared uploads folder, and answers on {T}/upload/status (not retained). sensor.{T}_uploads lists what is on file.
UPLOAD_STAGING = os.path.join(UPLOADS_SHARED, ".staging", T)  # private: mode 700, chunk files 600
UPLOAD_SWEEP_S = 10  # the janitor drops stalled uploads this often
UPLOADS_PUB_S = 60  # and re-lists what is on file (the other instance or the Web UI may have saved a file)
UPLOAD_STATUS_GAP_S = 1.0  # 'receiving' statuses at most this often per upload (the first and last always go)
UPLOAD_RECENT = 5  # results kept in the status, so a card that missed one update still finds its own
_UP = {"asm": None, "sig": None, "recent": [], "pub_at": {}}
_UP_LOCK = threading.Lock()


def assembler():
    if _UP["asm"] is None:
        _UP["asm"] = UP.Assembler(UPLOAD_STAGING, web.UPLOAD_MAX, key=settings_key,
                                  done_path=os.path.join(DATA, "upload_done.json"))  # FW-0066 review: no replays
    return _UP["asm"]


def publish_upload_status(st):
    """{T}/upload/status, not retained: {state and phase (receiving | checking | reading | done | error; HA keeps state
    as the sensor's state and drops it from the attributes), id, kind, got, total, ok?, message (plain text: file
    names and counts, never file content), at, recent [{id, ok, message, at}]}."""
    st = {**st, "at": now_iso()}
    st["phase"] = st["state"]  # HA's MQTT sensor drops an attribute named state: the card reads phase
    with _UP_LOCK:
        if st["state"] == "receiving" and 0 < st.get("got", 0) < st.get("total", 0):
            last = _UP["pub_at"].get(st["id"], 0)
            if time.time() - last < UPLOAD_STATUS_GAP_S and st.get("got") != 1:
                return False
        _UP["pub_at"][st["id"]] = time.time()
        if st["state"] in ("done", "error"):
            _UP["pub_at"].pop(st["id"], None)
            rec = [r for r in _UP["recent"] if r["id"] != st["id"]]
            _UP["recent"] = ([{k: st.get(k) for k in ("id", "kind", "ok", "message", "at")}] + rec)[:UPLOAD_RECENT]
        st["recent"] = list(_UP["recent"])
    pub("upload/status", st, retain=False)
    return True


def _bg(fn, *args):
    """Run fn on its own daemon thread (tests run it in place)."""
    threading.Thread(target=fn, args=args, daemon=True, name="upload").start()


def upload_chunk(payload):
    """One chunk from {T}/upload/chunk. Never raises (paho would stop its loop). The log has the upload's id prefix,
    kind and counts only."""
    try:
        try:
            msg = json.loads(payload.decode("utf-8") if isinstance(payload, (bytes, bytearray)) else payload)
        except (ValueError, UnicodeDecodeError):
            log.info("upload chunk ignored: not JSON")
            return
        st, ready = assembler().add(msg)
        if st is None:
            return
        if st["state"] == "error":
            log.info("upload %s (%s): refused: %s", st["id"][:6], st.get("kind") or "?", st["message"])
        elif st.get("got") == 1 and st["state"] == "receiving":
            log.info("upload %s (%s): receiving %d parts", st["id"][:6], st["kind"], st["total"])
        publish_upload_status(st)
        if ready:
            _bg(upload_finish, ready)
    except Exception as e:  # noqa: BLE001
        log.warning("upload chunk failed: %s", type(e).__name__)


def upload_finish(ready):
    """A complete upload: check it (chunks.Assembler.finish), then save it exactly like the ingress upload
    (web.save_upload), then say so and re-list the files. Runs on its own thread (pdftotext can take seconds)."""
    m = ready["meta"]
    base = {"id": m["id"], "kind": m["kind"], "got": m["n"], "total": m["n"]}
    try:
        fields, data = assembler().finish(ready)
    except UP.Bad as e:
        log.info("upload %s (%s): refused: %s", m["id"][:6], m["kind"], e)
        publish_upload_status({**base, "state": "error", "ok": False, "message": str(e)})
        return
    except Exception as e:  # noqa: BLE001
        log.warning("upload %s (%s): check failed: %s", m["id"][:6], m["kind"], type(e).__name__)
        publish_upload_status({**base, "state": "error", "ok": False, "message": f"Upload failed ({type(e).__name__})."})
        return
    publish_upload_status({**base, "state": "reading", "message": f"Reading {UP.WHAT.get(m['kind'], 'the file')}..."})
    try:
        r = web.save_upload(fields, data, log, who=reporter())  # 1.7.2: who saved it is its provenance
    except Exception as e:  # noqa: BLE001
        r = {"ok": False, "message": f"Upload failed ({type(e).__name__})."}
    log.info("upload %s (%s, %d KB, %s): %s", m["id"][:6], m["kind"], len(data) // 1024,
             "sealed" if m.get("enc") else "not sealed", "saved" if r.get("ok") else "not saved")
    publish_upload_status({**base, "state": "done" if r.get("ok") else "error", "ok": bool(r.get("ok")),
                           "message": str(r.get("message") or "")[:600]})
    try:
        publish_uploads(force=True)
    except Exception as e:  # noqa: BLE001
        log.info("uploads list not published: %s", type(e).__name__)


def publish_uploads(c=None, force=False):
    """{T}/uploads (retained), sensor.{T}_uploads: web.uploads_json plus count and chunk_bytes. Published when it
    changes (or force); no file content and no contact entry (contacts: counts and the file name only)."""
    try:
        d = web.uploads_json(VERSION, review=has("upload_review"))  # 1.7.2: pilots' uploads, the admin's
    except Exception as e:  # noqa: BLE001
        log.info("uploads list skipped: %s", type(e).__name__)
        return False
    d.update(count=len(d.get("files") or []), chunk_bytes=UP.CHUNK_MAX)
    sig = json.dumps(d, sort_keys=True)
    if not force and sig == _UP["sig"]:
        return False
    _UP["sig"] = sig
    if c is not None:
        c.publish(f"{T}/uploads", json.dumps(cap_attrs("uploads", d)), retain=True)
    else:
        pub("uploads", d)
    return True


# ---------------------------------------------------------------- 1.7.2 (FW-0066, Ryan Nov 11) a pilot's PDF uploads
# A portal pilot uploads the month's pairings package or award from his portal (upload/pdf, contract 1 revision 3): his
# own Watcher puts it together and checks it (pilotpdf.py), then it is used at once when nothing is on file for that
# month and kind, else held in the quarantine folder for the admin (no instance reads it, nothing serves it). The
# admin's Watcher sees each new one in the shared provenance file and publishes {T}/event/pilot_upload once (the HA
# automation "Flight Watcher pilot upload" pushes Ryan's phones, time-sensitive, with Remove or Approve / Reject), and
# takes his answer on {T}/upload/decide (from that push or his Settings uploads card). Every instance follows a
# file's generation (uploads_check): a file removed is forgotten (its pairing details, award version and pairing file),
# a file swapped in is read again.
PILOT_UP_FILE = f"{DATA}/pilot_uploads.json"  # this pilot's upload times (per_day) and the answers his card shows
PILOT_UP_TMP = f"{DATA}/pilot_upload_tmp"  # the extractor's private work folder (0700)
PILOT_UP_ANSWERS = 10
PILOT_UP_ANNOUNCED = "pilot_upload_announced"  # admin DB: {upload id: at}, an upload pushed once
PDF_ASM = PP.Assembler()
_PUP = {"lock": threading.Lock(), "sig": None, "progress_at": 0.0, "refused": collections.OrderedDict()}


def _pup_refuse(uid):
    """An upload refused: its later chunks are ignored (the last 50 ids, this process)."""
    _PUP["refused"][uid] = time.time()
    while len(_PUP["refused"]) > 50:
        _PUP["refused"].popitem(last=False)


def review():
    """The shared provenance and quarantine store: /share/flight_watcher/upload_review/ beside the uploads folder
    (provenance.json, quarantine/, rollback/; 0700, files 0600), as web.review_dir() names it."""
    return PP.Review(UPLOADS_SHARED, os.path.join(os.path.dirname(UPLOADS_SHARED), "upload_review"))


def pilot_uploads_eid():
    return f"sensor.{T}_pilot_uploads"


def _pup_read():
    try:
        with open(PILOT_UP_FILE, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def pilot_upload_answer(uid, ok, state, message):
    """One answer for the pilot's uploads card (the last PILOT_UP_ANSWERS, newest first): {uid, ok, state, message,
    at}. Plain text, never file content."""
    with _PUP["lock"]:
        d = _pup_read()
        ans = [a for a in d.get("answers") or [] if isinstance(a, dict) and a.get("uid") != uid]
        d["answers"] = ([{"uid": str(uid or "")[:40], "ok": bool(ok), "state": state, "message": str(message)[:300],
                          "at": now_iso()}] + ans)[:PILOT_UP_ANSWERS]
        try:
            PT.write_private(PILOT_UP_FILE, json.dumps(d))
        except OSError as e:
            log.info("pilot upload answer not saved: %s", type(e).__name__)
    portal_dirty(pilot_uploads_eid())


def _pup_times(now=None):
    now = time.time() if now is None else now
    return [t for t in (_pup_read().get("times") or []) if isinstance(t, (int, float)) and 0 <= now - t < 86400]


def _pup_count(now=None):
    """This upload, put together whole, counts toward per_day (refused or not), before any check runs."""
    now = time.time() if now is None else now
    with _PUP["lock"]:
        d = _pup_read()
        d["times"] = _pup_times(now) + [now]
        PT.write_private(PILOT_UP_FILE, json.dumps(d))


def pilot_upload_chunk(payload):
    """One upload/pdf chunk on a portal pilot (the spool republished it after its shape check; any MQTT client could
    publish here, so the shape is checked again). Never raises. The log has the upload's id prefix, kind, month and
    counts only."""
    try:
        if not (is_pilot() and portal_on()):
            return
        text = payload.decode("utf-8", errors="replace") if isinstance(payload, (bytes, bytearray)) else str(payload)
        try:
            d = PT.check_shape("upload/pdf", text)
        except PT.PortalError as e:
            log.info("pilot upload chunk refused: %s", e)
            return
        uid = d["uid"]
        if uid in _PUP["refused"]:
            return  # an upload refused already: its later chunks say nothing more (the card shows the first answer)
        why = PP.month_refusal(d["month"], local_now().replace(tzinfo=HST))
        if not why and int(d["part"]) == 1 and len(_pup_times()) >= ROLES.PILOT_UPLOAD_LIMITS["per_day"]:
            why = (f"{ROLES.PILOT_UPLOAD_LIMITS['per_day']} uploads in the last 24 h already: the next one at "
                   f"{hst_hm(min(_pup_times()) + 86400)} HST")
        if why:
            if (PDF_ASM.progress() or ("",))[0] == uid:
                PDF_ASM.drop()
            _pup_refuse(uid)
            log.info("pilot upload %s (%s %s): refused: %s", uid[:6], d["kind"], d["month"], why)
            pilot_upload_answer(uid, False, "error", f"Not stored: {why}.")
            return
        try:
            done = PDF_ASM.add(d)
        except PP.Refused as e:
            _pup_refuse(uid)
            log.info("pilot upload %s (%s %s): refused: %s", uid[:6], d["kind"], d["month"], e)
            pilot_upload_answer(uid, False, "error", f"Not stored: {e}.")
            return
        if done is None:
            pr = PDF_ASM.progress()
            if pr and (pr[1] == 1 or time.time() - _PUP["progress_at"] >= 10):
                _PUP["progress_at"] = time.time()
                if pr[1] == 1:
                    log.info("pilot upload %s (%s %s): receiving %d parts", uid[:6], d["kind"], d["month"], pr[2])
                pilot_upload_answer(uid, True, "receiving", f"Receiving part {pr[1]} of {pr[2]}.")
            return
        meta, raw = done
        _pup_count()
        pilot_upload_answer(uid, True, "checking", "All parts in: checking the file.")
        _bg(pilot_upload_finish, meta, raw)
    except Exception as e:  # noqa: BLE001
        log.warning("pilot upload chunk failed: %s", type(e).__name__)


def pilot_upload_finish(meta, raw):
    """A whole upload: the PDF's shape, its text (pilotpdf.extract: a child process under limits), the parsers for its
    kind, then Review.store (used at once, or held for the admin). Runs on its own thread. The answer says what
    happened in plain words; the log has counts only."""
    uid, kind, month = meta["uid"], meta["kind"], meta["month"]
    tag = f"pilot upload {uid[:6]} ({kind} {month}, {len(raw) // 1024} KB)"
    work = None
    try:
        PP.pdf_shape(raw)
        text, work = PP.extract(raw, PILOT_UP_TMP)
        if kind == "pairings":
            info = PP.check_pairings(text, month)
        else:
            info = PP.check_award(text, month, S.get("own_emp") or "", pkg_details_for(month))
        with web.save_lock():
            rec = review().store(INSTANCE, kind, month, raw, os.path.join(work, "out.txt"), uid, info)
    except PP.Refused as e:
        log.info("%s: refused: %s", tag, e)
        pilot_upload_answer(uid, False, "error", f"Not stored: {e}.")
        return
    except Exception as e:  # noqa: BLE001
        log.warning("%s: check failed: %s", tag, type(e).__name__)
        pilot_upload_answer(uid, False, "error", f"Not stored: the check failed ({type(e).__name__}).")
        return
    finally:
        if work:
            shutil.rmtree(work, ignore_errors=True)
    if rec["state"] == "same":
        log.info("%s: the same file is on file already; nothing stored", tag)
    elif rec["state"] == "live":
        log.info("%s: nothing was on file: in use now (%s)", tag, ", ".join(f"{k} {v}" for k, v in info.items()))
    else:
        log.info("%s: a file is on file: held for the admin (read by no instance until he approves it)", tag)
    _pup_final(uid, kind, month, rec["state"])
    try:
        publish_uploads(force=True)
    except Exception as e:  # noqa: BLE001
        log.info("uploads list not published: %s", type(e).__name__)


def _pup_final(uid, kind, month, state):
    """The answer for a checked upload: same (nothing to do), live (in use now) or pending (held for the admin)."""
    what = f"{PP.month_name(month)} {PP.WHAT.get(kind, kind)}"
    if state == "same":
        pilot_upload_answer(uid, True, "same", f"The {what} on file is this same file: nothing to do.")
    elif state == "live":
        pilot_upload_answer(uid, True, "live", f"Stored: the {what} is on file now and in use. The admin was told and "
                                               "may remove it.")
    else:
        pilot_upload_answer(uid, True, "pending", f"Held for the admin: a {what} is on file already. Yours is used "
                                                  "only if the admin approves it.")


def pilot_upload_stale():
    """1.7.2 (review): an upload the Assembler dropped because no part came within stale_s (a last part lost on the
    way, or the pilot's page closed) gets an error answer, so his card stops waiting. Every sweep, a portal pilot.
    Returns the ids answered."""
    out = []
    for uid, got, parts in PDF_ASM.take_stale():
        if uid in _PUP["refused"]:
            continue
        _pup_refuse(uid)
        log.info("pilot upload %s: dropped, no part for %d s (%d of %d in)", uid[:6], ROLES.PILOT_UPLOAD_LIMITS[
            "stale_s"], got, parts)
        pilot_upload_answer(uid, False, "error", f"Not stored: no part came for {ROLES.PILOT_UPLOAD_LIMITS['stale_s']} s "
                                                 f"({got} of {parts} in), so the upload was dropped. Upload the file "
                                                 "again.")
        out.append(uid)
    return out


def pilot_upload_restarted():
    """1.7.2 (review): at a portal pilot's start, an answer still 'receiving' or 'checking' belonged to the process
    before (its parts were in memory, its check was cut off), so his card would wait on it for good: it gets the
    answer its provenance record gives when the check had finished, else an error. Returns the ids answered."""
    with _PUP["lock"]:
        ans = [a for a in _pup_read().get("answers") or [] if isinstance(a, dict)]
    open_ = [a for a in ans if a.get("state") in ("receiving", "checking") and isinstance(a.get("uid"), str)]
    if not open_:
        return []
    try:
        recs = {r.get("uid"): r for r in review().records() if r.get("who") == INSTANCE and r.get("uid")}
    except OSError:
        recs = {}
    for a in open_:
        r = recs.get(a["uid"])
        if r and r.get("kind") in PP.KINDS:
            _pup_final(a["uid"], r["kind"], r.get("month") or "", "live" if r.get("how") == "first" else "pending")
        else:
            pilot_upload_answer(a["uid"], False, "error", "Not stored: your Watcher restarted before the upload was in "
                                                         "and checked. Upload the file again.")
    log.info("pilot uploads: %d answer(s) left open by the last run settled", len(open_))
    return [a["uid"] for a in open_]


def pilot_uploads_state():
    """{sensor.<T>_pilot_uploads: entry} for a portal pilot's state.json (synthesized from his own records and the
    shared folder, never read from HA): this month and the next two, each kind on file or not and from whom (you, the
    admin or another pilot: never a name), his own uploads (state, month, kind, size, when), the answers and his limits.
    No file content, no sha256, no other pilot's upload."""
    lim = ROLES.PILOT_UPLOAD_LIMITS
    rv = review()
    try:
        recs = rv.records()
        files = rv.load()["files"]
    except OSError:
        recs, files = [], {}

    def by(who):
        return "" if not who else "you" if who == INSTANCE else "the admin" if who == PP.ADMIN else "another pilot"
    months = []
    for m in PP.months_allowed(local_now().replace(tzinfo=HST)):
        row = {"month": m, "name": PP.month_name(m)}
        for k in PP.KINDS:
            on = os.path.exists(os.path.join(UPLOADS_SHARED, f"{m}_{k}.pdf"))
            mine = [r for r in recs if r.get("who") == INSTANCE and (r.get("month"), r.get("kind")) == (m, k)
                    and r.get("state") == "pending"]
            row[k] = {"on_file": on, "by": by((files.get(f"{m}_{k}") or {}).get("who")) if on else "",
                      "pending": bool(mine)}
        months.append(row)
    mine = [{k: r.get(k) for k in ("id", "kind", "month", "state", "size", "at", "decided_at")}
            for r in recs if r.get("who") == INSTANCE][-10:][::-1]
    d = _pup_read()
    used = len(_pup_times())
    pr = PDF_ASM.progress()
    attrs = {"friendly_name": "Pilot uploads", "months": months, "mine": mine,
             "answers": [a for a in d.get("answers") or [] if isinstance(a, dict)][:PILOT_UP_ANSWERS],
             "busy": bool(pr), "receiving": {"uid": pr[0], "got": pr[1], "total": pr[2]} if pr else None,
             "limits": {"file_bytes": lim["file_bytes"], "per_day": lim["per_day"], "used_today": used,
                        "left_today": max(0, lim["per_day"] - used), "chunk_chars": lim["chunk_chars"],
                        "chunk_parts": lim["chunk_parts"], "stale_s": lim["stale_s"], "kinds": list(PP.KINDS)}}
    at = (attrs["answers"][0]["at"] if attrs["answers"] else None)
    return {pilot_uploads_eid(): {"state": str(sum(1 for r in mine if r.get("state") == "pending")),
                                  "attributes": attrs, "last_changed": at, "last_updated": at}}


def pilot_uploads_tick():
    """A portal pilot, once a minute: his uploads view changed (the admin decided, a file came or went): export it."""
    if not EXPORT["on"]:
        return False
    sig = json.dumps(pilot_uploads_state(), sort_keys=True)
    if sig == _PUP["sig"]:
        return False
    _PUP["sig"] = sig
    portal_dirty(pilot_uploads_eid())
    return True


def pilot_upload_announce():
    """The admin, every UPLOADS_PUB_S: each pilot's upload used at once or held (a provenance record of another
    instance, state live or pending) goes once on {T}/event/pilot_upload (the HA automation pushes Ryan's phones with
    Remove, or Approve and Reject). The ids sent are in the DB before the publish. Returns the events sent."""
    if not has("upload_review") or not mqtt_up():
        return []
    try:
        recs = review().records()
    except OSError:
        return []
    done = DB.get(PILOT_UP_ANNOUNCED) or {}
    out = []
    for r in recs:
        if r.get("who") in ("", PP.ADMIN, None) or r.get("state") not in ("live", "pending") or r.get("id") in done:
            continue
        done[r["id"]] = now_iso()
        DB.put(PILOT_UP_ANNOUNCED, dict(sorted(done.items(), key=lambda kv: kv[1])[-200:]))
        what = f"{PP.month_name(r['month'])} {PP.WHAT.get(r['kind'], r['kind'])}"
        size = f"{r.get('size', 0) / 1e6:.1f} MB"
        facts = (f"{r['pairings']} pairings, {r.get('a332', 0)} A332 HNL" if r.get("kind") == "pairings"
                 and r.get("pairings") else f"{r.get('items', 0)} items on his line" if r.get("kind") == "award" else "")
        if r["state"] == "live":
            msg = (f"Nothing was on file, so it is in use now ({size}{', ' + facts if facts else ''}). Tap Remove to "
                   "take it off: nothing is on file then and both Watchers read again.")
        else:
            msg = (f"A file is on file already, so his copy is held ({size}{', ' + facts if facts else ''}). Approve "
                   "uses it and keeps the old file for rollback; Reject deletes his copy.")
        ev = {"id": r["id"], "who": r["who"], "kind": r["kind"], "month": r["month"], "state": r["state"],
              "file": f"{r['month']}_{r['kind']}.pdf", "size": r.get("size", 0), "at": r.get("at"),
              "title": f"{r['who'].capitalize()} uploaded the {what}", "message": msg}
        pub("event/pilot_upload", ev, retain=False)
        log.info("pilot upload %s (%s %s by %s, %s): pushed to the admin", r["id"][:6], r["kind"], r["month"],
                 r["who"], r["state"])
        out.append(ev)
    return out


def upload_decide_cmd(payload):
    """{T}/upload/decide on the admin: {"id": upload id, "action": approve | remove | reject} from his push's buttons
    (the HA automation) or his Settings uploads card. Review.decide does it under the uploads lock; a file removed with
    nothing to restore also takes its pairing file off the shared www folder. Never raises."""
    try:
        if not has("upload_review"):
            return
        try:
            d = json.loads(payload or "{}")
        except ValueError:
            d = None
        if not (isinstance(d, dict) and set(d) == {"id", "action"} and isinstance(d["id"], str)
                and re.fullmatch(ROLES.UPLOAD_ID_PATTERN, d["id"]) and d["action"] in ("approve", "remove", "reject")):
            log.info("upload decision refused: not {id, action}")
            return
        with web.save_lock():
            ok, msg, rec = review().decide(d["id"], d["action"], PP.ADMIN)
            if ok and d["action"] == "remove" and rec and rec.get("kind") == "pairings" and not os.path.exists(
                    os.path.join(UPLOADS_SHARED, f"{rec['month']}_pairings.pdf")):
                try:
                    os.unlink(os.path.join(CARD_PAIRINGS, f"pairings_{rec['month']}.json"))
                except FileNotFoundError:
                    pass
        log.info("upload decision %s %s: %s", d["action"], d["id"][:6], msg)
        if ok:
            UPLOADS_RECHECK.set()
        publish_uploads(force=True)
    except Exception as e:  # noqa: BLE001
        log.info("upload decision failed: %s", type(e).__name__)


UPLOADS_RECHECK = threading.Event()  # a decision changed a shared file: uploads_check runs at the next minute


def upload_gens_pending():
    """A shared file's generation differs from the one this instance last followed (cheap: one small file read)."""
    try:
        gens = review().gens()
    except OSError:
        return False
    seen = S.get("upload_gen") or {}
    return any(seen.get(n) != g for n, g in gens.items())


def upload_gens_check():
    """1.7.2: a file's generation changed (a pilot's upload, an approve, a remove): its 'done' mark goes, so uploads_check
    reads it again; when it is gone (removed with nothing to restore) this instance forgets what it had from it: the
    pairing details and the bid calendar / van caches (pairings) or the awarded line's version (award). Returns the
    names that changed."""
    try:
        gens = review().gens()
    except OSError:
        return []
    seen = S.setdefault("upload_gen", {})
    changed = [n for n, g in gens.items() if seen.get(n) != g and re.fullmatch(r"\d{4}-\d{2}_(pairings|award)", n)]
    if not changed:
        return []
    done = S.setdefault("uploads_done", {})
    for name in changed:
        month, kind = name[:7], name[8:]
        done.pop(f"{name}.txt", None)
        (S.get("pilotver_awards") or {}).pop(f"{name}.txt", None)
        if not os.path.exists(os.path.join(UPLOADS_SHARED, f"{name}.txt")):
            if kind == "pairings":
                DB.put(f"pkg_details:{month}", None)
                _PKG_CACHE.pop(month, None)
                try:
                    os.unlink(os.path.join(CARD_PAIRINGS, f"pairings_{month}.json"))
                except OSError:
                    pass
            else:
                vers = VER.clear_award(DB, month)
                log.info("upload %s removed: the awarded line is no longer version .001 (%d versions)", name, len(vers))
                versions_check(force_pub=True)
                for emp in PV.registered(DB, month):  # 1.7.2 (review): a looked-up pilot's .001 came from it too
                    if PV.clear_award(DB, emp, month):
                        log.info("pilot %s: the removed award is no longer schedule version %s.001", emp,
                                 int(month[5:7]))
                        if emp == shown_emp():
                            pub_pilot(dict(PILOT_SHOWN["p"]))
            log.info("upload %s: removed from the shared folder; forgotten here", name)
        else:
            log.info("upload %s: changed in the shared folder; read again", name)
        seen[name] = gens[name]
    save_state(S)
    return changed


def upload_janitor():
    """Drop stalled uploads (chunks.TIMEOUT_S with no chunk) and re-list what is on file now and then."""
    n = 0
    while True:
        time.sleep(UPLOAD_SWEEP_S)
        try:
            van_tick()  # 1.7.1 (FW-0072): every sweep (10 s), on its own, whatever the state; the admin only
        except Exception as e:  # noqa: BLE001
            log.info("van alerts: %s", type(e).__name__)
        try:
            for st in assembler().sweep():
                log.info("upload %s (%s): %s", st["id"][:6], st.get("kind") or "?", st["message"])
                publish_upload_status(st)
            if is_pilot() and portal_on():
                pilot_upload_stale()  # 1.7.2 (review): a pilot's PDF upload dropped for no part gets its answer
            n += 1
            if n * UPLOAD_SWEEP_S >= UPLOADS_PUB_S:
                n = 0
                try:
                    bidcal_tick()  # 1.7.1 (FW-0070): first and on its own, so an uploads error never skips it
                except Exception as e:  # noqa: BLE001
                    log.info("bid calendar: %s", type(e).__name__)
                try:
                    recall_replay_tick()  # 1.7.1: the admin's recall history, once to each pilot
                except Exception as e:  # noqa: BLE001
                    log.info("recall history replay: %s", type(e).__name__)
                try:
                    fetches_tick()  # 1.7.1 (F#10): a pilot's FLICA loads this hour, for his health line
                except Exception as e:  # noqa: BLE001
                    log.info("FLICA loads this hour: %s", type(e).__name__)
                try:
                    schedule_unread_tick()  # 1.7.2 (contract 1 revision 3): a portal pilot's schedule not read
                except Exception as e:  # noqa: BLE001
                    log.info("schedule not read alert: %s", type(e).__name__)
                try:  # 1.7.2 (FW-0066): a pilot's upload or the admin's decision, followed whatever the state
                    if UPLOADS_RECHECK.is_set() or upload_gens_pending():
                        UPLOADS_RECHECK.clear()
                        uploads_check()
                    pilot_upload_announce()
                    pilot_uploads_tick()
                except Exception as e:  # noqa: BLE001
                    log.info("pilot uploads: %s", type(e).__name__)
                publish_uploads()
                if is_pilot():
                    # 1.7.0 (Release C): a pilot's ticket list (and its fixed alert) follows the folder every
                    # UPLOADS_PUB_S, not only after a FLICA check (paused, yielded or waiting for settings he has
                    # none); a folder rescan, no FLICA load. The admin keeps his check() rescan only.
                    publish_tickets()
        except Exception as e:  # noqa: BLE001
            log.info("upload janitor: %s", type(e).__name__)


# ---------------------------------------------------------------- 1.7.1 FW-0070 bid calendar alerts (Ryan)
# Ryan's ticket: a critical push at 08:00 HST the day before the pairing package publishes ("adjust your vacation if
# needed"; Ryan's Nov 11 answer, bidcal.PUBLISH_ALERT), the night before each practice run, 24 h before bids close and the night before they close (bidcal.py). The uploads
# janitor checks once a minute, whatever the state (paused, yielded, hunting, waiting for settings): no FLICA load, and
# page 1 of the shared package is read only when its file changes. Each alert goes once on {T}/event/bid_calendar
# (not retained). Only Ryan's prefix has an HA automation ("Flight Watcher bid calendar"); a pilot's instance makes the
# same alerts on his own prefix, and from 1.7.2 (contract 1 revision 3) each is a portal event (his Alerts list and
# ntfy) with the same words, built from its fields (portal.event_text, bidcal.alert_text).
BIDCAL_DONE = "bid_calendar_done"  # DB: {alert key: {how: sent | dropped, at, event}}, written before the publish
BIDCAL_KEEP = 40  # keys kept (5 a cycle)
_BIDCAL = {"pkg": {}, "sig": None}  # bid month -> (file time, bidcal.parse of its package); the sensor's last payload


def bidcal_package(bid_month):
    """bidcal.parse of the bid month's pairing package (uploads/<YYYY-MM>_pairings.txt, shared by every instance),
    cached by file time; None when it is not on file (it cannot be before it publishes) or names another month."""
    path = os.path.join(UPLOADS_SHARED, f"{bid_month}_pairings.txt")
    try:
        mt = os.path.getmtime(path)
    except OSError:
        return None
    c = _BIDCAL["pkg"].get(bid_month)
    if c and c[0] == mt:
        return c[1]
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            parsed = BC.parse(f.read(BC.HEAD_BYTES), bid_month)
    except Exception as e:  # noqa: BLE001
        log.info("bid calendar: the %s pairing package was not read: %s", bid_month, type(e).__name__)
        parsed = None
    if parsed and parsed.get("bid_month") != bid_month:
        log.info("bid calendar: %s_pairings.txt is the %s package: the usual dates stay", bid_month,
                 parsed.get("bid_month") or "unnamed")
        parsed = None
    elif parsed:
        cl = parsed.get("close") or {}
        log.info("bid calendar: %s from its pairing package: published %s, practice runs %s, bids close %s %s",
                 bid_month, parsed.get("published") or "?", " and ".join(d or "?" for d in parsed["practice"]),
                 cl.get("date") or "?", cl.get("time") or "?")
    _BIDCAL["pkg"][bid_month] = (mt, parsed)
    return parsed


def mqtt_up():
    """MQ is connected (a client with no is_connected, as in the tests, counts as up)."""
    f = getattr(MQ, "is_connected", None)
    return MQ is not None and (not callable(f) or bool(f()))


def bidcal_tick(now=None):
    """Send each bid calendar alert that is due, once: next month's cycle and the one after (bidcal.cycles), from the
    package's Bid Calendar when it is on file, else the usual dates. A due alert waits while MQTT is down; one missed
    past its deadline (the app was off) is dropped with a log line, never sent late with words no longer true. The
    sent and dropped keys are in the DB before the publish, so a restart never repeats one. Returns the alerts sent."""
    now = now or datetime.now(HST)
    alerts = []
    for bm in BC.cycles(now):
        alerts += BC.schedule(bm, bidcal_package(bm))
    done = DB.get(BIDCAL_DONE) or {}
    send, drop = BC.due(alerts, done, now)
    if send and not mqtt_up():
        send = []  # tried again next minute, until its deadline
    for a in drop:
        done[a["key"]] = {"how": "dropped", "at": now.isoformat(), "event": a["event"]}  # bidcal.is_done
        log.info("bid calendar: %s not sent: its time (%s, kept until %s) passed while the app was off or MQTT down",
                 a["key"], BC.hst_text(a["fire_at"]), BC.hst_text(a["deadline"]))
    for a in send:
        done[a["key"]] = {"how": "sent", "at": now.isoformat(), "event": a["event"]}
    if send or drop:
        DB.put(BIDCAL_DONE, dict(sorted(done.items())[-BIDCAL_KEEP:]))
    at = now.astimezone(HST).replace(microsecond=0)  # 1.7.2: the time the words are from is the at_hst sent
    for a in send:
        title, message = BC.render(a, at)  # worded from now: a late one still says the hours really left
        # 1.7.2 (contract 1 revision 3): alert and cycle_source too, so a pilot's portal event words the same text from
        # the fields alone (bidcal.alert_text); every instance sends the same keys
        pub("event/bid_calendar", {"kind": "bid_calendar", "key": a["key"], "bid_month": a["bid_month"],
                                   "alert": a["kind"], "title": title, "message": message,
                                   "at_hst": at.isoformat(timespec="seconds"),
                                   "event_hst": a["event"], "source": a["source"],
                                   "cycle_source": a["cycle_source"]}, retain=False)
        log.info("bid calendar: %s sent: %s", a["key"], title)
    publish_bid_calendar(alerts, done)
    return send


def publish_bid_calendar(alerts, done, force=False):
    """{T}/bid_calendar (retained), sensor.{T}_bid_calendar: state the next alert's time (HST, a timestamp sensor);
    attributes the next alert, its cycle's dates, source (package or default, each date's own in sources) and that
    cycle's alerts with their status (pending, sent, dropped). Published when it changes (or force). 1.7.1 review:
    never while MQTT is down (paho drops it at qos 0), so the payload kept as sent is one that went out; on_connect
    clears it too, so the next tick sends it again after any reconnect."""
    if not mqtt_up():
        return False
    nxt = BC.next_alert(alerts, done)
    bm = nxt["bid_month"] if nxt else (alerts[-1]["bid_month"] if alerts else None)
    if bm is None:
        return False
    c = BC.cycle_dates(bm, bidcal_package(bm))
    nd = None
    if nxt:
        nd = {"key": nxt["key"], "title": nxt["title"], "message": nxt["message"], "at_hst": BC.hst_text(nxt["fire_at"])}
    d = {"next_at": nxt["fire_at"] if nxt else None, "next": nd, "bid_month": bm, "source": c["source"],
         "sources": c["sources"], "published": c["published"], "practice": c["practice"], "close": c["close"],
         "awards_by": c["awards_by"], "open_time_opens": c["open_time_opens"],
         "alerts": [{"key": a["key"], "kind": a["kind"], "fire_at": a["fire_at"], "at_hst": BC.hst_text(a["fire_at"]),
                     "title": a["title"],
                     "status": (BC.is_done(a, done) and done[a["key"]].get("how")) or "pending"}
                    for a in alerts if a["bid_month"] == bm]}
    sig = json.dumps(d, sort_keys=True)
    if not force and sig == _BIDCAL["sig"]:
        return False
    _BIDCAL["sig"] = sig
    pub("bid_calendar", d)
    return True


# ---------------------------------------------------------------- 1.7.1 FW-0072 van alerts and layover notes (Ryan)
# Ryan's ticket: "a critical alert 30 min prior to van time and 10 min prior to van time pushed to my phone", and "an
# area to leave notes for future layovers in the same cities". The admin's instance only (roles: admin_pushes for the
# van, one_writer for the notes; a pilot has neither). The uploads janitor calls van_tick every UPLOAD_SWEEP_S whatever
# the state (paused, yielded, hunting, waiting for settings): no FLICA load. Hark's sensor is read from HA (the
# Supervisor API, as the export reads states) at most every VAN_READ_S; layover.py parses the van on the layover
# station's clock and says which alert is due. Each alert goes once on {T}/event/van (not retained), its key in the DB
# before the publish, so a restart never repeats one; a new van time is a new key. A van it cannot place (no zone for
# the station, no date in the text, a time a daylight time change skips) is no alert and one log line, never a guess.
# HA's "Flight Watcher van time" automation makes the critical push to Ryan's phones.
HARK_FLIGHT = "sensor.hark_working_flight"
VAN_DONE = "van_alerts_done"  # DB: {alert key: {how: sent | skipped, at}}, written before the publish
VAN_KEEP = 40  # keys kept (2 a van)
VAN_READ_S = 60  # Hark writes its sensor about every 30 min; a changed van is seen within a minute
LAYOVERS_DIR = "/share/flight_watcher/layovers"  # <CITY>.json notes and <CITY>.guide.md (layover.py); never in git
LAYOVER_NOTE_BYTES = 8192  # a layover/note command's payload, at most
LAYOVER_SCAN_S = 30  # the notes folder is looked at this often (a guide Claude wrote shows within it)
_VAN = {"read": None, "status": None, "attrs": None, "state": "", "why": None, "sig": None, "city": "", "last": None,
        "seen": None}  # seen: the last van van_tick placed (1.7.2: the van a setting applies to)
_LN = {"sig": None, "files": None, "checked": None, "last": {}, "city": None}
# the uploads janitor (layover_notes_tick) and the MQTT thread (layover_note_cmd) both publish the notes sensor: one at
# a time, each building its payload under the lock, so a payload built before a note was written is never the last one
# published (it would drop the note and its answer, the card on "Saving..." until the next look at the folder)
_LN_LOCK = threading.Lock()

# 1.7.2 (Ryan, Nov 12: "I like the layover card. Can you add a tick box to turn on the van time alerts and also add van
# time alert settings in the form of sliders in the settings tab?"). S["van"]: on (the layover card's tick box, switch
# van_alerts), first and second (the sliders, number van_alert_first and van_alert_second: minutes before the van;
# second 0 is no second alert). A setting changes only the van in hand when it is made (layover.settle: its skipped
# keys go into the DB at once); a van learned or moved later follows the 1.7.1 rules. Defaults are 1.7.1's alerts: on,
# 30 and 10. The admin only (roles: admin_pushes), like the alerts.
VAN_DEFAULTS = {"on": True, "first": LO.OFFSETS[0], "second": LO.OFFSETS[1]}
VAN_LIMITS = {"first": (5, 120), "second": (0, 60)}  # minutes; the sliders' ranges and the clamp of a command
VAN_SET_SUBS = {"van/alerts/set": "on", "van/first_min/set": "first", "van/second_min/set": "second"}
VAN_STATE_TOPICS = {"on": "van/alerts/state", "first": "van/first_min/state", "second": "van/second_min/state"}
# van_tick (the uploads janitor) and a van setting (the MQTT thread) one at a time: a setting's skipped keys are in the
# DB before the next decision, and the sensor a setting republishes is never overwritten by one built before it
_VAN_LOCK = threading.Lock()


def van_settings():
    """S["van"] with its defaults: on, first and second clamped to VAN_LIMITS (a hand-edited state cannot widen them)."""
    v = S.get("van") if isinstance(S.get("van"), dict) else {}
    out = {"on": v["on"] if isinstance(v.get("on"), bool) else VAN_DEFAULTS["on"]}
    for k, (lo, hi) in VAN_LIMITS.items():
        x = v.get(k)
        out[k] = max(lo, min(hi, x)) if isinstance(x, int) and not isinstance(x, bool) else VAN_DEFAULTS[k]
    return out


def van_offsets(vs=None):
    """The lead times set (layover.offsets_of first and second), largest first, whether alerts are on or not."""
    vs = vs or van_settings()
    return LO.offsets_of(vs["first"], vs["second"])


def van_words(vs):
    """'alerts 30 and 10 min before' or 'alerts off', for a log line."""
    offs = van_offsets(vs)
    if not vs["on"]:
        return "alerts off"
    return "alerts " + " and ".join(str(m) for m in offs) + " min before" if offs else "alerts on, no lead time set"


def publish_van_settings(c=None):
    """{T}/van/alerts/state (ON or OFF), {T}/van/first_min/state and {T}/van/second_min/state, retained: the switch and
    the sliders in HA. At connect and after each van setting command. The admin only."""
    if not has("admin_pushes"):
        return False
    c = c or MQ
    if c is None:
        return False
    vs = van_settings()
    c.publish(f"{T}/{VAN_STATE_TOPICS['on']}", "ON" if vs["on"] else "OFF", retain=True)
    c.publish(f"{T}/{VAN_STATE_TOPICS['first']}", str(vs["first"]), retain=True)
    c.publish(f"{T}/{VAN_STATE_TOPICS['second']}", str(vs["second"]), retain=True)
    return True


def van_setting_cmd(c, sub, payload, now=None):
    """1.7.2: {T}/van/alerts/set ON or OFF (on, off, true, false too), {T}/van/first_min/set (5 to 120 min) and
    {T}/van/second_min/set (0 to 60, 0 is no second alert): a whole number of minutes, clamped, like the check
    frequency sliders ('inf' or 'abc' is ignored). Kept in S["van"] (save_state, so a restart keeps it), one log line
    a change, the state topics published after every command (so HA's switch and sliders show what was kept). The
    change applies at once to the van in hand (the last van van_tick placed, even through a sweep that could not read
    Hark): layover.settle says which lead times that became active are skipped (one whose mark passed while another
    alert is ahead or one has gone, one whose slider's alert has gone), written into the DB now, one log line each;
    one whose mark is ahead goes at it, and the latest one whose mark passed goes at the next sweep when nothing else
    would come for that van. A van learned or moved after it is a new key and follows the 1.7.1 rules. A lead time
    already sent for this van is never sent again (its DB key stays), whatever the switch or the sliders do. Before
    van_tick's first look after a start (one sweep, 10 s) there is no van in hand, and a van then follows the 1.7.1
    late-start rule (an alert late, never none). Returns True when a setting changed. Nothing on a pilot's
    instance."""
    if not has("admin_pushes"):
        log.info("van alert setting refused: not for a pilot instance")
        return False
    what = VAN_SET_SUBS.get(sub)
    if what is None:
        return False
    p = str(payload or "").strip()
    with _VAN_LOCK:
        vs = van_settings()
        if what == "on":
            w = p.lower()
            if w not in ("on", "off", "true", "false"):
                log.info("van alerts: a switch command that is not ON or OFF ignored")
                publish_van_settings(c)
                return False
            new = w in ("on", "true")
        else:
            lo, hi = VAN_LIMITS[what]
            try:
                new = max(lo, min(hi, int(round(float(p)))))
            except (ValueError, OverflowError):  # 'nan', 'inf' or '1e999' must not end paho's thread
                publish_van_settings(c)
                return False
        if new == vs[what]:
            publish_van_settings(c)
            return False
        before = van_offsets(vs) if vs["on"] else ()
        vs[what] = new
        after = van_offsets(vs) if vs["on"] else ()
        t = (now or datetime.now(HST)).astimezone(HST)  # HST like van_tick's keys: van_keep orders them by it
        S["van"] = {"on": vs["on"], "first": vs["first"], "second": vs["second"]}
        save_state(S)
        vs = van_settings()
        name = {"on": "switched " + ("on" if new else "off"), "first": f"first alert {new} min before",
                "second": f"second alert {new} min before" if new else "second alert off"}[what]
        log.info("van alerts: %s (%s)", name, van_words(vs))
        publish_van_settings(c)
        last, info = _VAN.get("last"), _VAN.get("seen")
        done = DB.get(VAN_DONE) or {}
        skip = LO.settle(info, done, t, before, after, vs["first"])
        for m, why in sorted(skip.items(), reverse=True):  # the van in hand only (a later van is a new key)
            done[LO.key(info, m)] = {"how": "skipped", "at": t.isoformat(), "why": why,
                                     "slot": LO.slot_of(m, vs["first"])}
            log.info("van alert %d min before %s not sent: %s", m, LO.key(info, m),
                     "that slider's alert for this van has gone already" if why == "slot_sent" else
                     "that lead time was set or alerts switched on after its mark, so it is never sent late")
        if skip:
            DB.put(VAN_DONE, van_keep(done, info))
        if last is not None:  # the van sensor says the new settings at once (the card's tick box stops waiting)
            publish_layover_van(last[0], last[1], done, t, vs=vs)
    return True


def van_keep(done, info):
    """VAN_DONE bounded: the newest VAN_KEEP keys by when each was written, and always every key of the van in hand, so
    a run of lead time changes (each a skipped key) can never push out an alert already sent for it and send it
    again. The van in hand has at most one key a lead time (1 to 120 min)."""
    pre = LO.key(info, 0).rsplit("|", 1)[0] + "|" if info else None
    when = lambda kv: str((kv[1] or {}).get("at") or "")  # noqa: E731
    mine = {k: v for k, v in done.items() if pre and k.startswith(pre)}
    rest = sorted(((k, v) for k, v in done.items() if k not in mine), key=when)
    n = max(0, VAN_KEEP - len(mine))
    keep = dict(rest[-n:]) if n else {}
    keep.update(mine)
    return dict(sorted(keep.items(), key=when))


def van_read(mono):
    """Hark's sensor from HA, at most every VAN_READ_S (mono: time.monotonic())."""
    if _VAN["read"] is not None and mono - _VAN["read"] < VAN_READ_S:
        return
    _VAN["read"] = mono
    st, js = ha_state_full(HARK_FLIGHT)
    _VAN["status"] = st
    js = js if isinstance(js, dict) else {}
    _VAN["attrs"] = js.get("attributes") if st == 200 and isinstance(js.get("attributes"), dict) else None
    _VAN["state"] = str(js.get("state") or "") if st == 200 else ""


_PKG_VANS = {}  # 1.7.1: bid month -> ((mtime_ns, size), layover.package_vans of its pairings package, or None)


def van_packages(months):
    """layover.package_vans of each month's pairings package (uploads/<YYYY-MM>_pairings.txt, the text copy every
    upload makes, shared), read again only when its file changes: an uploaded or revised package replaces that file,
    so its van times are the ones used from the next sweep (10 s) on. One log line a read. [] for none on file."""
    out = []
    for mo in months:
        path = os.path.join(UPLOADS_SHARED, f"{mo}_pairings.txt")
        try:
            st = os.stat(path)
        except OSError:
            _PKG_VANS.pop(mo, None)
            continue
        sig = (st.st_mtime_ns, st.st_size)
        c = _PKG_VANS.get(mo)
        if not c or c[0] != sig:
            try:
                with open(path, encoding="utf-8", errors="replace") as f:
                    got = LO.package_vans(f.read())
            except Exception as e:  # noqa: BLE001
                log.info("van times: the %s pairings package was not read: %s", mo, type(e).__name__)
                got = None
            if got and got["month"] != mo:
                log.info("van times: %s_pairings.txt is the %s package: not used", mo, got["month"] or "unnamed")
                got = None
            elif got:
                log.info("van times: the %s pairings package read: %d layovers, %d with a van time", mo,
                         got["layovers"], got["with_van"])
            c = _PKG_VANS[mo] = (sig, got)
        if c[1]:
            out.append(c[1])
    return out


def _van_months(leg):
    """The bid months whose package may hold the leg's trip: the month of the trip's first day and of the leg's date,
    and the month before each (November's period runs to Dec 1)."""
    out = []
    for d in (leg.get("start") or "", leg.get("date") or ""):
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d):
            continue
        y, m = int(d[:4]), int(d[5:7])
        for k in (0, -1):
            y2, m2 = divmod(y * 12 + m - 1 + k, 12)
            mo = f"{y2}-{m2 + 1:02d}"
            if mo not in out:
                out.append(mo)
    return out


def hark_leg(a):
    """The leg Hark's working flight is on during a layover (mode layover): pairing, city (its origin), flt (digits),
    dep and date of its departure ('21:40 AEDT (9:40 PM) Thu 2026-11-12'); start '' (not in it). None otherwise."""
    if not isinstance(a, dict) or a.get("mode") != "layover":
        return None
    m = re.search(r"\b(\d{1,2}):(\d{2})\b.*?(\d{4}-\d{2}-\d{2})", str(a.get("dep_sched") or ""))
    return {"pairing": str(a.get("pairing") or "").strip().upper(), "start": "",
            "city": str(a.get("origin") or "").strip().upper(), "flt": re.sub(r"\D", "", str(a.get("flight") or "")),
            "dep": f"{int(m.group(1)):02d}:{m.group(2)}" if m else "", "date": m.group(3) if m else ""}


def van_source(own, a, state):
    """(info, why) in Ryan's order (Nov 11, FW-0072): (a) the pairings package's VAN for this pairing's layover when it
    is not 00:00 (layover.package_van; the layover from his own schedule, else from Hark's sensor in layover mode),
    (b) Hark's van for the same pairing (when his own schedule shows another pairing, Hark's is not used), (c) none:
    no alert, and why (Hark's reason, then the package's when it has the layover but no usable time)."""
    leg = own or hark_leg(a)
    pinfo, pwhy = LO.package_van(van_packages(_van_months(leg)), leg) if leg else (None, "")
    hinfo = None
    if a is None:
        hwhy = "Hark's working flight is not in Home Assistant" if _VAN["status"] == 404 else "Home Assistant did not answer"
    elif own and not LO.same_pairing(a.get("pairing"), own["pairing"]):
        hwhy = f"Hark's working flight is for another pairing than {own['pairing']}"
    else:
        hinfo, hwhy = LO.van_info(a, state)
    if pinfo:
        if hinfo and hinfo["city"] == pinfo["city"]:  # Hark's words for the place ("... lobby") on the same layover
            pinfo.update(place=hinfo["place"] or pinfo["place"], hotel=hinfo["hotel"] or pinfo["hotel"])
        return pinfo, ""
    if hinfo:
        return hinfo, ""
    return None, hwhy + (f"; the pairings package {pwhy}" if pwhy else "")


def van_tick(now=None, mono=None):
    """Send the van alert that is due, once (layover.due: 30 and 10 min before the van by default, only before it, the
    latest one alone after a late start), publish the layover_van sensor and look at the notes folder. Returns the
    offsets sent. Nothing on a pilot's instance. The van comes from van_source: the pairings package's VAN, else
    Hark's. 1.7.2: the lead times and the switch are Ryan's settings (van_settings): off sends nothing; what a setting
    skips for the van in hand is in the DB already (van_setting_cmd, layover.settle). A sent key names its slider
    (slot), so a slider moved after its alert went sends no other for that van."""
    if not has("admin_pushes"):
        return []
    now = now or datetime.now(HST)
    van_read(time.monotonic() if mono is None else mono)
    a = _VAN["attrs"]
    try:
        own = WK.layover_leg(_sched_items(), S.get("own_trips") or {}, now)
    except Exception as e:  # noqa: BLE001
        log.info("van: own layover not read: %s", type(e).__name__)
        own = None
    info, why = van_source(own, a, _VAN["state"])
    with _VAN_LOCK:
        vs = van_settings()
        offs = van_offsets(vs)
        active = offs if vs["on"] else ()
        # one log line each time the van or the reason changes
        seen = (LO.key(info, 0), info["source"]) if info else why
        if seen != _VAN["why"]:
            _VAN["why"] = seen
            if info:
                log.info("van: %s %s %s at %s %s (%s HST %s), %s (from %s)", info["pairing"],
                         info["city"], info["date"], info["local"], info["abbr"], info["hst"], info["hst_date"],
                         van_words(vs), "the pairings package" if info["source"] == "package" else "Hark")
            else:
                log.info("van alerts: none (%s)", why)
        city = info["city"] if info else own["city"] if own else (
            str(a.get("origin") or "").upper() if a and a.get("mode") == "layover" else "")
        _VAN["city"] = city if LO.STATION_RE.match(city) else ""
        _VAN["last"] = (info, why)
        _VAN["seen"] = info or _VAN["seen"]
        done = DB.get(VAN_DONE) or {}
        send, skip = LO.due(info, done, now, active) if info else ([], [])
        if send and not mqtt_up():
            send = []  # tried again at the next sweep, until the van time
        for m in skip:
            done[LO.key(info, m)] = {"how": "skipped", "at": now.isoformat(), "why": "late_start"}
            log.info("van alert %d min before %s not sent: its mark passed with no alert (the app or MQTT was down, "
                     "or the van time came later); a later one goes instead", m, LO.key(info, m))
        for m in send:
            done[LO.key(info, m)] = {"how": "sent", "at": now.isoformat(), "slot": LO.slot_of(m, vs["first"])}
        if send or skip:
            DB.put(VAN_DONE, van_keep(done, info))
        for m in send:
            ev = LO.event(info, m, now, offs)
            pub("event/van", ev, retain=False)
            log.info("van alert sent: %s", ev["message"])
        publish_layover_van(info, why, done, now, vs=vs)
    layover_notes_tick(time.monotonic() if mono is None else mono)
    return send


def forget_layover_sigs():
    """After a (re)connect: the van and notes sensors go again at the next van_tick, even unchanged. A payload
    published while MQTT was down (QoS 0) was dropped, yet its signature was kept, so a van or a note changed during a
    broker restart would not reach the card until it changed again (1.7.1 review)."""
    _VAN["sig"] = None
    _LN["sig"] = _LN["files"] = _LN["checked"] = None


def publish_layover_van(info, why, done, now, force=False, vs=None):
    """{T}/layover_van (retained), sensor.{T}_layover_van: layover.sensor; published when it changes. 1.7.2: with the
    van settings (vs, van_settings): alerts_on, offsets and the alerts of the lead times set."""
    vs = vs or van_settings()
    d = LO.sensor(info, why, done, now, van_offsets(vs), vs["on"])
    sig = json.dumps(d, sort_keys=True)
    if not force and sig == _VAN["sig"]:
        return False
    _VAN["sig"] = sig
    pub("layover_van", d)
    return True


def layover_notes_tick(mono, force=False):
    """Re-publish the notes sensor when a notes file or a guide changed (Claude writes the guides on Pako) or the
    layover station did; the folder is looked at every LAYOVER_SCAN_S."""
    if not has("one_writer"):
        return False
    if not force and _LN["checked"] is not None and mono - _LN["checked"] < LAYOVER_SCAN_S \
            and _LN["city"] == _VAN["city"]:
        return False
    _LN["checked"] = mono
    sig = LO.signature(LAYOVERS_DIR)
    if not force and sig == _LN["files"] and _LN["city"] == _VAN["city"]:
        return False
    _LN["files"], _LN["city"] = sig, _VAN["city"]
    return publish_layover_notes()


def publish_layover_notes(force=False):
    """{T}/layover_notes (retained), sensor.{T}_layover_notes: layover.sensor_payload (the current layover station
    first, within layover.SENSOR_BYTES) and the answer to the last note command."""
    if not has("one_writer"):
        return False
    with _LN_LOCK:
        try:
            d = LO.sensor_payload(LAYOVERS_DIR, _VAN["city"], _LN["last"])
        except Exception as e:  # noqa: BLE001
            log.info("layover notes not published: %s", type(e).__name__)
            return False
        sig = json.dumps(d, sort_keys=True)
        if not force and sig == _LN["sig"]:
            return False
        _LN["sig"] = sig
        if d.get("unreadable"):
            log.info("layover notes: %s left out, the notes file could not be read (nothing changed in it)",
                     ", ".join(d["unreadable"]))
        pub("layover_notes", d)
    return True


def layover_note_cmd(payload):
    """{T}/layover/note {city, text, rid?} adds a note; {city, delete: <note id>, rid?} removes one. Plain text, at most
    layover.NOTE_MAX characters, the city a 3-letter station code; stored in LAYOVERS_DIR/<CITY>.json (0600, folder
    0700). The answer {rid, ok, error, city, action} goes on the notes sensor as "last". Never logs a note's text."""
    if not has("one_writer"):
        log.info("layover note refused: not for a pilot instance")
        return False
    d = None
    if len(payload or "") <= LAYOVER_NOTE_BYTES:
        try:
            d = json.loads(payload or "{}")
        except ValueError:
            d = None
    d = d if isinstance(d, dict) else {}
    rid = str(d.get("rid") or "")
    rid = rid if RID_RE.match(rid) else ""
    city = str(d.get("city") or "").strip().upper()[:3]
    action = "delete" if "delete" in d else "add"
    ok, err = False, ""
    try:
        if not d:
            raise LO.Bad("not a note (JSON with city and text, at most 8 KB)")
        if action == "delete":
            LO.delete(LAYOVERS_DIR, d.get("city"), d.get("delete"), now_iso())
        else:
            LO.add(LAYOVERS_DIR, d.get("city"), d.get("text"), now_iso())
        ok = True
    except LO.Bad as e:
        err = str(e)
    except OSError as e:
        err = f"not saved ({type(e).__name__})"
    except Exception as e:  # noqa: BLE001  anything else still answers, so the card never waits on "Saving..."
        err = f"not saved ({type(e).__name__})"
    _LN["last"] = {"rid": rid, "ok": ok, "error": err, "city": city if LO.STATION_RE.match(city) else "",
                   "action": action, "at": now_iso()}
    log.info("layover note %s %s: %s", action, log_safe(city, 3) or "?", "saved" if ok else err)
    _LN["files"] = None
    publish_layover_notes(force=True)
    return ok


def start_upload_janitor():
    """Start the janitor once (main(), right after MQTT starts: before the wait for a second pilot's settings)."""
    if _UP.get("janitor") is None:
        _UP["janitor"] = threading.Thread(target=upload_janitor, daemon=True, name="uploads")
        _UP["janitor"].start()
    return _UP["janitor"]


_CT_CACHE = {}


def contacts_data():
    """FW-0066: the pilot contact list (web.CONTACTS_FILE, shared by every instance), cached by file time; None when
    there is none. Personal data: never logged, never published but for the one looked-up pilot (contact_for)."""
    path = web.CONTACTS_FILE
    try:
        mt = os.path.getmtime(path)
    except OSError:
        return None
    if _CT_CACHE.get("path") != path or _CT_CACHE.get("mt") != mt:
        _CT_CACHE.update(path=path, mt=mt, data=CT.load(path))
    return _CT_CACHE.get("data")


def contact_emp(q):
    """(emp, name) of the one contact list entry a typed name matches, or None."""
    try:
        return CT.find_by_name(contacts_data(), q)
    except Exception as e:  # noqa: BLE001
        log.info("pilot lookup: contact list not searched: %s", type(e).__name__)
        return None


def contact_for(emp, name=""):
    """The looked-up pilot's {name, phones, emails} from the contact list, or None."""
    try:
        return CT.find(contacts_data(), emp, name)
    except Exception as e:  # noqa: BLE001 (type only: the message could carry a name)
        log.info("pilot lookup: contact skipped: %s", type(e).__name__)
        return None


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


def _cid_of(d, key="cid"):
    v = d.get(key) if isinstance(d, dict) else None
    return v if isinstance(v, str) and RID_RE.match(v) else ""


def ticket_new(payload):
    """{T}/ticket/new {kind, title, narrative, steps?, expected?, page?, version?, image?, cid?, images?}.
    FW-0003: the card sends photos after this, one per {T}/ticket/image message (ticket_image).
    1.7.0: on a pilot the quotas apply (roles.PILOT_TICKET_LIMITS: 10 new tickets in 24 h, 25 open, 3 photos, no
    inline photo) and the answer goes on his sensor; the admin is unlimited."""
    try:
        d = json.loads(payload or "{}")
    except ValueError:
        d = None
    t, err = TK.create(TICKETS_DIR, d, reporter(), now_iso(), limits=ticket_limits())
    if not t:
        log.info("ticket refused: %s", err)
        pub("event/ticket_error", {"error": err, "at": now_iso()}, retain=False)
        if is_pilot():
            ticket_answer(_cid_of(d), "", "new", False, err)
            publish_tickets(force=True)
        return None
    ticket_answer(t.get("cid") or "", t["id"], "new", True)
    # 1.7.0 review: the title on one line (log_safe; TK.create already keeps no control in it), whoever filed it
    log.info("ticket %s (%s) from %s: %s (%d photos to come)", t["id"], t["kind"], t["reporter"],
             log_safe(t["title"]), t["images_expected"] - len(t["images"]))
    pub("event/ticket_new", {"id": t["id"], "kind": t["kind"], "title": t["title"], "reporter": t["reporter"]}, retain=False)
    publish_tickets(force=True)
    return t


def ticket_image(payload):
    """FW-0003 {T}/ticket/image {cid, i, image}: photo i (1 to 10) of the ticket this instance filed with that
    cid, one photo per message. An unknown cid or a bad photo is refused and nothing is written.
    1.7.0: a pilot's photo goes through ticket_photo_pilot (chunks, checks, re-encoding, his limits)."""
    if is_pilot():
        return ticket_photo_pilot(payload)
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


def ticket_photo_pilot(payload):
    """1.7.0 (Release C): a pilot's ticket/image. The portal's chunk form {cid, i, n, part, parts, data} (checked
    again here with portal.check_ticket, whatever sent it) is put together by PHOTO_ASM, one photo at a time; a
    dashboard card's whole form {cid, i, n?, image} is one complete photo. Either way the photo is decoded strictly,
    must be a JPEG or PNG by its magic bytes and within the size cap, is re-encoded (photos.check) and stored with his
    limits (3 photos, 1.5 MB a ticket). A refused chunk or photo leaves nothing written and answers on his sensor."""
    try:
        d = json.loads(payload or "{}")
    except ValueError:
        d = None
    d = d if isinstance(d, dict) else {}
    cid, i = _cid_of(d), d.get("i") if isinstance(d.get("i"), int) and not isinstance(d.get("i"), bool) else None
    lim = ticket_limits()

    def refuse(err):
        if i is not None and any(a.get("ref") == cid and a.get("action") == "image" and a.get("i") == i and not a["ok"]
                                 for a in TICKET_ANSWERS):
            return None  # the rest of a photo already refused (its next chunks): one answer and one log line a photo
        log.info("ticket photo refused: %s", err)
        pub("event/ticket_error", {"error": err, "at": now_iso()}, retain=False)
        ticket_answer(cid, "", "image", False, err, i=i)
        publish_tickets(force=True)
        return None

    try:
        if "part" in d or "data" in d:
            PT.check_ticket("ticket/image", payload)
            if int(d["part"]) == 1:
                why = TK.photo_target(TICKETS_DIR, cid, int(d["i"]), reporter(), lim)
                if why:
                    PHOTO_ASM.drop(cid)
                    return refuse(why)
            done = PHOTO_ASM.add(d)
            if done is None:
                return None  # more chunks to come (or a resend of one already taken)
            _, i, b64 = done
            raw, ext = PH.check(b64)
        else:
            if not cid or i is None:
                return refuse("bad cid or photo number")
            s_ = str(d.get("image") or "")
            b64 = s_.partition(",")[2] if s_.startswith("data:") else s_
            raw, ext = PH.check(b64.strip(), max_bytes=int(lim["ticket_bytes"]))
    except (PT.PortalError, PH.Refused) as e:
        return refuse(str(e))
    t, err = TK.store_photo(TICKETS_DIR, cid, int(i), raw, ext, reporter(), now_iso(), limits=lim)
    if not t:
        return refuse(err)
    log.info("ticket %s: photo %s (%d of %d, %d KB re-encoded)", t["id"], i, len(t["images"]), t["images_expected"],
             len(raw) // 1024)
    ticket_answer(cid, t["id"], "image", True, i=int(i))
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
    t, err = TK.act(TICKETS_DIR, d, reporter(), now_iso(), allowed_reporter=INSTANCE or None,
                    limits=ticket_limits())  # 1.7.0 review: a pilot's change caps
    if not t:
        log.info("ticket action refused: %s", err)
        pub("event/ticket_error", {"error": err, "at": now_iso()}, retain=False)
        if is_pilot():  # 1.7.0: his card shows the refusal on the row (the admin's card is unchanged)
            dd = d if isinstance(d, dict) else {}
            ticket_answer(_cid_of(dd, "rid"), str(dd.get("id") or "")[:12], "act", False, err)
            publish_tickets(force=True)
        return None
    log.info("ticket %s: %s -> %s", t["id"], d.get("action"), t["status"])
    ticket_answer(_cid_of(d, "rid"), t["id"], "act", True)
    publish_tickets(force=True)
    ev = TK.fixed_event(t)
    if ev:
        log.info("ticket %s fixed (v%s): telling %s", ev["id"], ev["version"] or "?", ev["reporter"])
        pub("event/ticket_fixed", ev, retain=False)
    return t


def _ticket_change(fn, verb, payload, **kw):
    """FW-0049: run TK.edit or TK.delete for this instance (a pilot instance: its own tickets only) and say how it
    went in "last" {rid, id, action, ok, error, at} on the next listing, so the card that sent the card-made rid can
    show it. A refusal also goes out as event/ticket_error, like every other ticket message. kw goes to fn (1.7.0
    review: limits for an edit)."""
    try:
        d = json.loads(payload or "{}")
    except ValueError:
        d = None
    t, err = fn(TICKETS_DIR, d, reporter(), now_iso(), allowed_reporter=INSTANCE or None, **kw)
    d = d if isinstance(d, dict) else {}
    rid = str(d.get("rid") or "").strip()
    TICKETS_LAST.clear()
    TICKETS_LAST.update({"rid": rid if RID_RE.match(rid) else "", "id": str(d.get("id") or "")[:20], "action": verb,
                         "ok": bool(t), "error": err, "at": now_iso()})
    ticket_answer(rid, str(d.get("id") or "")[:12], verb, bool(t), err)  # 1.7.0: a pilot's sensor only
    if not t:
        log.info("ticket %s refused: %s", verb, err)
        pub("event/ticket_error", {"error": err, "at": now_iso()}, retain=False)
    publish_tickets(force=True)
    return t


def ticket_edit(payload):
    """FW-0049 {T}/ticket/edit {id, rid?, title?, narrative?, steps?, expected?, page?}: only while the ticket is new
    or reopened; only the fields sent change."""
    t = _ticket_change(TK.edit, "edit", payload, limits=ticket_limits())
    if t:
        log.info("ticket %s edited by %s: %s", t["id"], reporter(), ", ".join(t["history"][-1]["fields"]))
    return t


def ticket_delete(payload):
    """FW-0049 {T}/ticket/delete {id, rid?}: any status; the folder moves to tickets/.deleted/ and leaves the list.
    1.7.0 review: a pilot's only while it is new (TK.delete); when others had written on it (a note), the log says so,
    so the admin sees why it left his list."""
    t = _ticket_change(TK.delete, "delete", payload)
    if t:
        others = sum(1 for h in t.get("history") or [] if isinstance(h, dict)
                     and h.get("actor") not in (reporter(), None)) if is_pilot() else 0
        log.info("ticket %s (%s) deleted by %s%s", t["id"], t.get("status"), reporter(),
                 f" after {others} line{'' if others == 1 else 's'} from others (kept in tickets/.deleted/)"
                 if others else "")
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
    out = {"open": listing.get("open", 0), "total": listing.get("total", 0), "tickets": rows, "rows": "open",
           "file_key": key, "rev": rev, "last": dict(last or {})}
    if is_pilot():  # 1.7.0: his answers and limits for his card (the admin's sensor is unchanged)
        out["answers"] = [dict(a) for a in TICKET_ANSWERS]
        out["limits"] = {k: ROLES.PILOT_TICKET_LIMITS[k] for k in ("new_per_day", "open", "photos", "ticket_bytes")}
    return out


def publish_tickets(force=False):
    """{T}/tickets (retained): Ryan's instance lists every ticket, a pilot instance only its own. Re-published
    when the folder changed (the other instance may have written to it) or when forced. FW-0049: "last" is this
    instance's last edit / delete answer ({} until one). FW-0060: the listing goes to tickets_<key>.json first, then
    the sensor (tickets_payload) announces it with rev. 1.7.0: one caller at a time (TICKETS_LOCK); on a portal pilot
    a new move into fixed of his own tickets becomes one ticket_fixed alert (ticket_fixed_watch)."""
    with TICKETS_LOCK:
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
        try:
            ticket_fixed_watch()
        except Exception as e:  # noqa: BLE001 (an alert never stops the listing)
            log.info("ticket fixed alert skipped: %s", type(e).__name__)


def ticket_fixed_watch():
    """1.7.0 (Release C), a portal pilot only: every move into fixed of his own tickets (tickets.fixed_moves, whoever
    made it: Ryan's instance or Claude's flow) not seen before becomes a portal event ticket_fixed (events.json, and
    ntfy once he has it) carrying only the ticket id(s) and the version; the moves of one pass are one event. The keys
    seen are kept in <data>/tickets_fixed_seen.json {seeded, keys} (0600). A missing or unreadable file seeds the moves
    already there without an alert (no backlog push at the first run or after a restart), and it is written even when
    there is nothing to seed. Returns the event record or None."""
    if not EXPORT["on"] or not is_pilot():
        return None
    moves = TK.fixed_moves(TICKETS_DIR, INSTANCE)
    path = os.path.join(DATA, TICKETS_FIXED_SEEN)
    try:
        d = json.load(open(path, encoding="utf-8"))
        seen = [k for k in d.get("keys") if isinstance(k, str)] if isinstance(d, dict) and d.get("seeded") and \
            isinstance(d.get("keys"), list) else None
    except (OSError, ValueError):
        seen = None
    if seen is None:
        PT.write_private(path, PT.dumps({"seeded": now_iso(), "keys": [m["key"] for m in moves][-TICKETS_FIXED_KEEP:]}))
        log.info("ticket fixed alerts seeded (%d earlier fix%s, no alert)", len(moves), "" if len(moves) == 1 else "es")
        return None
    known = set(seen)
    new = [m for m in moves if m["key"] not in known]
    if not new:
        return None
    keep = [k for k in seen if k in {m["key"] for m in moves}] + [m["key"] for m in new]
    PT.write_private(path, PT.dumps({"seeded": d["seeded"], "keys": keep[-TICKETS_FIXED_KEEP:]}))
    ids = sorted({m["id"] for m in new}, key=lambda x: int(x[3:]))
    rec = portal_event("ticket_fixed", {"key": "|".join(sorted(m["key"] for m in new)),
                                        "ticket": ids[0] if len(ids) == 1 else ids[:20],
                                        "version": new[-1]["version"]})
    log.info("ticket fixed alert: %s", ", ".join(ids))
    return rec


# ---------------------------------------------------------------- 0.7.0 charter watch (CrewTrac, read only)
CHARTER_WAKE = threading.Event()
CHARTER_BUSY = threading.Event()  # 1.6.1: a scan is running; a press then never queues a second one
CHARTER_IDLE_S = CH.SCAN_EVERY_S  # 1.6.1: no login may run (refused, none saved): the status is republished this often
CT_REFUSED_KEEP = 20  # 1.6.1: DB 'crewtrac_refused' keeps this many refused hashes (the newest)


def crewtrac_login(o=None):
    """1.6.1: the CrewTrac (user name, password) in use (or in the options o): the user name stripped, the password
    exactly as saved."""
    o = OPTS if o is None else o
    return (o.get("ctweb_username") or "").strip(), o.get("ctweb_password") or ""


def _hst_iso(dt):
    return dt.replace(tzinfo=HST).isoformat(timespec="seconds")


def crewtrac_where():
    """1.6.1: where new CrewTrac details are saved: Settings for a pilot; for the admin the app Configuration tab,
    unless CrewTrac details saved in Settings (creds.json, which overlays the options) are in use."""
    if INSTANCE:
        return "in Settings"
    c = load_creds()
    if any(isinstance(c.get(k), str) and c[k].strip() for k in ("ctweb_username", "ctweb_password")):
        return "in Settings"
    return "in the app Configuration tab"


def crewtrac_text(state, at=None, nxt=None):
    """1.6.1: the charters status in plain words for a pilot (Settings) or the admin (the app Configuration tab).
    at / nxt are local_now() times (HST). 'unconfirmed': the login form came back once with no refusal message."""
    where = crewtrac_where()
    if state == "not_configured":
        return f"Enter your CrewTrac user ID and password {where}."
    if state == "refused":
        return (f"CrewTrac refused your user ID or password at {at:%H:%M} HST. No more tries until you save new "
                f"CrewTrac details {where}.")
    if state == "unconfirmed":
        return (f"CrewTrac did not let the login through at {at:%H:%M} HST. One more try at {nxt:%H:%M} HST; if that "
                f"fails the same way, no more tries until you save new CrewTrac details {where}.")
    return f"CrewTrac could not be reached at {at:%H:%M} HST. Next try at {nxt:%H:%M} HST."


def crewtrac_state():
    """1.6.1: DB 'crewtrac' for the details in use: {creds (their sha256, never the values), state ok | refused |
    outage | not_configured | '' (not tried yet), at, next_try (HST ISO), block (the hash CrewTrac refused),
    outages, retry_at, press_at, unconfirmed}. Details that differ from the ones it was kept for (saved in Settings
    or the app Configuration tab) start a fresh record: the refusal block, the outage back-off and the press gap
    belong to the old ones. A refusal is also kept in DB 'crewtrac_refused' {hash: at}, so details CrewTrac refused
    stay blocked after they were cleared or swapped and later come back; only a save in Settings lifts that
    (crewtrac_resaved)."""
    u, p = crewtrac_login()
    ct = dict(DB.get("crewtrac") or {})
    if not u or not p:
        if ct.get("state") != "not_configured":
            ct = {"state": "not_configured", "at": _hst_iso(local_now()), "next_try": ""}
            DB.put("crewtrac", ct)
            DB.put("charter_status", crewtrac_text("not_configured"))
        return ct
    h = crewtrac_hash(u, p)
    if ct.get("creds") != h:
        fresh = {"state": "", "at": "", "next_try": "", "creds": h}
        last = DB.get("charter_scan_at")
        was = (DB.get("crewtrac_refused") or {}).get(h)
        if was:  # CrewTrac refused these very details before (cleared or swapped since): still no login
            fresh.update(state=CH.REFUSED, block=h, at=was)
            log.info("charter: CrewTrac refused these details before; no login until other details are saved")
            try:
                when = datetime.fromisoformat(was)
            except (ValueError, TypeError):
                when = local_now()
            DB.put("charter_status", crewtrac_text(CH.REFUSED, when))
        elif DB.get(CT_KEY_LOST):  # 1.7.2: the block key was lost with a refusal on record: no login until a save
            DB.put("charter_status", CT_KEY_LOST_TEXT)
        elif ct:  # other details than before: the old ones' block, back-off and press gap do not apply
            if ct.get("block"):
                log.info("charter: new CrewTrac details in use; the refusal block is lifted")
            DB.put("charter_status", "New CrewTrac details saved: the next scan tries them.")
        elif last:  # first start on 1.6.1: the last scan was a success
            try:
                at = datetime.fromisoformat(last).astimezone(HST).replace(tzinfo=None)
                fresh.update(state=CH.OK, at=_hst_iso(at), next_try=_hst_iso(at + timedelta(seconds=CH.SCAN_EVERY_S)))
            except (ValueError, TypeError):
                pass
        ct = fresh
        DB.put("crewtrac", ct)
    return ct


CT_KEY_FILE = f"{DATA}/crewtrac_hmac.key"  # 1.7.2: the CrewTrac block key, 32 random bytes, 0600, this instance only
CT_HMAC_V = "crewtrac_hmac_v"  # DB: 1 once the records are keyed with it (the 1.7.2 migration ran)
CT_KEY_LOST = "crewtrac_key_lost"  # DB: when the key was found gone with a refusal on record: blocked until a save
CT_KEY_LOST_TEXT = ("CrewTrac is not tried: its refusal record could not be checked. Save your CrewTrac details again "
                    "in Settings to try once.")
_CTK = {"key": None}


def _ct_key_read():
    return _key_file_read(CT_KEY_FILE)  # 1.7.4: the same reader as the FLICA block key's


def crewtrac_key():
    """1.7.2 (contract 1 revision 3, the council's change): the random 32-byte key of this instance's CrewTrac refusal
    block (CH.creds_hash, HMAC-SHA256), in its own data folder (CT_KEY_FILE, mode 0600), made on first use; never
    exported, logged or sent. Made for the first time (1.7.2's first start), it re-keys the 1.7.1 records: the details
    in use get their new key, a bare sha256 of any other details is dropped (it cannot be re-keyed without them).
    Found gone later (a restored or wiped data folder) with a refusal on record, no stored key can be matched any more:
    CrewTrac stays blocked until the next save in Settings (CT_KEY_LOST, crewtrac_stopped, crewtrac_resaved)."""
    if _CTK["key"] is not None:
        return _CTK["key"]
    key = _ct_key_read()
    if key is None:
        key = _key_file_make(CT_KEY_FILE, ".crewtrac_hmac.")
        _CTK["key"] = key
        ct, seen = dict(DB.get("crewtrac") or {}), dict(DB.get("crewtrac_refused") or {})
        if DB.get(CT_HMAC_V) == 1:  # records made with a key that is gone
            if seen or ct.get("block"):
                DB.put(CT_KEY_LOST, now_iso())
                DB.put("charter_status", CT_KEY_LOST_TEXT)
                log.info("charter: the CrewTrac block key was lost with a refusal on record; no CrewTrac login until "
                         "CrewTrac details are saved again in Settings")
            DB.put("crewtrac_refused", {})
            if ct.get("creds") or ct.get("block"):
                ct.pop("creds", None)
                ct.pop("block", None)
                DB.put("crewtrac", ct)
        else:  # 1.7.2's first start: the 1.7.1 records were bare sha256 values
            u, p = crewtrac_login()
            old = CH.legacy_hash(u, p) if u and p else None
            new = CH.creds_hash(u, p, key) if u and p else None
            re_seen = {new: at for h, at in seen.items() if old and h == old}
            for k in ("creds", "block"):
                if ct.get(k):
                    ct[k] = new if old and ct[k] == old else ""
            if ct:
                DB.put("crewtrac", ct)
            DB.put("crewtrac_refused", re_seen)
            log.info("charter: CrewTrac block records keyed with this instance's own key (%d kept, %d dropped)",
                     len(re_seen), len(seen) - len(re_seen))
        DB.put(CT_HMAC_V, 1)
        return key
    _CTK["key"] = key
    return key


def crewtrac_hash(u, p):
    """The refusal block's key of these CrewTrac details (HMAC with this instance's key)."""
    return CH.creds_hash(u, p, crewtrac_key())


def crewtrac_resaved():
    """1.6.1: CrewTrac details were saved in Settings (settings/set, even the same ones again): the pilot says they are
    right (CrewTrac may have unlocked the account since). If CrewTrac refused the details now in use, that block is
    lifted for one more try; refused again, it comes back. True when a block was lifted."""
    u, p = crewtrac_login(load_opts())
    if not u or not p:
        return False
    h = crewtrac_hash(u, p)
    if DB.get(CT_KEY_LOST):  # 1.7.2: the block key was lost: this save is the one the block waited for
        DB.put(CT_KEY_LOST, None)
        DB.put("charter_status", "CrewTrac details saved again: the next scan tries them.")
        log.info("charter: CrewTrac details saved again in Settings; the block kept since the key was lost is lifted")
        return True
    seen = dict(DB.get("crewtrac_refused") or {})
    ct = dict(DB.get("crewtrac") or {})
    if h not in seen and not (ct.get("creds") == h and ct.get("block") == h):
        return False
    seen.pop(h, None)
    DB.put("crewtrac_refused", seen)
    if ct.get("creds") == h:
        ct.update(state="", at="", next_try="", block="", outages=0, retry_at=0, press_at=0, unconfirmed=0)
        DB.put("crewtrac", ct)
    DB.put("charter_status", "CrewTrac details saved again: the next scan tries them once more.")
    log.info("charter: CrewTrac details saved again in Settings; the refusal block is lifted for one more try")
    return True


def crewtrac_stopped(ct):
    """1.6.1: no login may run: no details saved, or CrewTrac refused these very ones (the block matches their hash).
    1.7.2: or the block key was lost with a refusal on record (crewtrac_key), until the next save in Settings."""
    if DB.get(CT_KEY_LOST):
        return True
    return ct.get("state") == "not_configured" or bool(ct.get("block") and ct.get("block") == ct.get("creds"))


def crewtrac_info():
    """The charters sensor's crewtrac attribute: {state, at, next_try}."""
    ct = crewtrac_state()
    return {k: ct.get(k) or "" for k in ("state", "at", "next_try")}


# 1.7.1 (F#22, Ryan Nov 11): shared charters. A pilot's Watcher runs no CrewTrac scan and makes no CrewTrac login: it
# shows the charter flights the admin's scan finds. The admin publishes the flight list its Charters card shows (each
# flight's key, date, flight, route, scheduled time, equipment, tail, why unusual, first seen and gone: CrewTrac's
# Scheduled Service, never anything of the admin's own schedule, fit or CrewTrac login) retained on CHARTERS_SHARED,
# under the admin's own prefix: a pilot's portal publishes only under his prefix (portal_spool_once), so it can never
# write it. Every pilot subscribes to it (subscribe_all) and publishes his charters sensor from it (source admin).
CHARTERS_SHARED = "flight_watcher/charters/shared"
CHARTERS_SHARED_DB = "charters_shared"  # DB on a pilot: {at (the admin's scan), items, got}
CHARTERS_SEEN_DB = "charters_shared_seen"  # DB on a pilot: the keys he was alerted to (or seeded), newest last
SHARED_FIELDS = ("key", "date", "flight", "route", "scheduled", "eqpt", "tail", "why", "first_seen")
SHARED_MAX = 200  # flights in one list (a 30-day scan finds a handful)
SHARED_SEEN_KEEP = 500
CT_NOT_USED = "not_used"  # a pilot's crewtrac state: no CrewTrac login is ever made


def shared_item(r):
    """One flight of the shared list: SHARED_FIELDS as short text and gone, nothing else (the admin's records also
    carry CrewTrac's cancelled, estimated, actual and orig columns, which no card shows)."""
    it = {k: str(r.get(k) if r.get(k) is not None else "")[:80] for k in SHARED_FIELDS}
    it["gone"] = r.get("gone") is True
    return it


def charters_share():
    """1.7.1 (F#22): the admin's last charter scan for every pilot's Watcher, retained on CHARTERS_SHARED (qos 1):
    {v, at (the scan's time), items (shared_item each)}. After each scan that read CrewTrac and once at start; only
    while the add-on runs a pilot, and only after a first scan. False when nothing was sent."""
    if is_pilot() or MQ is None:
        return False
    at = DB.get("charter_scan_at") or ""
    if not at or not pilot_prefixes():
        return False
    known = DB.get("charters") or {}
    items = [shared_item(r) for r in sorted(known.values(), key=lambda r: (r.get("date", ""), r.get("scheduled", "")))]
    MQ.publish(CHARTERS_SHARED, json.dumps({"v": 1, "at": at, "items": items[:SHARED_MAX]}), qos=1, retain=True)
    log.info("charters: the scan of %s (%d flight%s) shared with the pilot Watchers", at, len(items),
             "" if len(items) == 1 else "s")
    return True


def charters_shared_in(payload):
    """1.7.1 (F#22): a pilot takes the admin's shared list (CHARTERS_SHARED). Read as data: a JSON object with an
    items list, each flight cut to SHARED_FIELDS and gone (anything else is dropped), at most SHARED_MAX. A flight new
    to this pilot (not gone, its key not seen) fires his event/charter once, as his own scan did; the first list on an
    instance that never had one is taken quietly (logged), so a start never sends a burst. Returns the new keys."""
    try:
        d = json.loads(payload.decode("utf-8", "replace") if isinstance(payload, bytes) else payload or "")
    except ValueError:
        d = None
    if not isinstance(d, dict) or not isinstance(d.get("items"), list):
        log.info("charters: the admin's shared list skipped: not a list of flights")
        return []
    at = str(d.get("at") or "")[:40]
    try:
        datetime.fromisoformat(at)
    except ValueError:
        at = ""
    items = [shared_item(r) for r in d["items"][:SHARED_MAX] if isinstance(r, dict) and r.get("key") and r.get("flight")]
    seen_l = DB.get(CHARTERS_SEEN_DB)
    first = seen_l is None and not DB.get("charters")  # never a list, nor a scan of his own before 1.7.1
    seen = set(seen_l or []) | set(DB.get("charters") or {})  # the flights his own scans found before 1.7.1 count
    new = [r for r in items if not r["gone"] and r["key"] not in seen]
    DB.put(CHARTERS_SHARED_DB, {"at": at, "items": items, "got": now_iso()})
    keep = list(dict.fromkeys(list(seen_l or []) + [r["key"] for r in items]))[-SHARED_SEEN_KEEP:]
    DB.put(CHARTERS_SEEN_DB, keep)
    if first and new:
        log.info("charters: the admin's first shared list taken quietly (%d flights, no alert)", len(new))
        new = []
    for r in new:
        log.info("CHARTER %s %s %s %s (%s), from the admin's scan", r["date"], r["flight"], r["route"], r["eqpt"], r["why"])
        pub("event/charter", {"key": r["key"], **{f: r[f] for f in ("date", "flight", "route", "scheduled", "eqpt",
                                                                     "tail", "why")}}, retain=False)
    publish_charters()
    return [r["key"] for r in new]


def charters_shared_text(at):
    """'from the admin's scan at 14:05 HST' (the date too when the scan was not today, HST); before any list:
    'waiting for the admin's CrewTrac scan'."""
    try:
        t = datetime.fromisoformat(at).astimezone(HST)
    except (TypeError, ValueError):
        return "waiting for the admin's CrewTrac scan"
    day = "" if t.date() == local_now().date() else f"{t:%b} {t.day} "
    return f"from the admin's scan at {day}{t:%H:%M} HST"


def publish_charters(status=""):
    if is_pilot():  # 1.7.1 (F#22): the admin's list, never a scan of his own
        sh = DB.get(CHARTERS_SHARED_DB) or {}
        items = sorted(sh.get("items") or [], key=lambda r: (r.get("date", ""), r.get("scheduled", "")))
        pub("charters", {"count": len([r for r in items if not r.get("gone")]), "items": items,
                         "last_scan": sh.get("at") or "", "status": charters_shared_text(sh.get("at")),
                         "source": "admin", "regular": sorted(CH.regular_set(OPTS.get("charter_regular"))),
                         "crewtrac": {"state": CT_NOT_USED, "at": "", "next_try": ""}})
        return
    known = DB.get("charters") or {}
    items = sorted(known.values(), key=lambda r: (r.get("date", ""), r.get("scheduled", "")))
    crewtrac = crewtrac_info()
    pub("charters", {"count": len([r for r in items if not r.get("gone")]), "items": items,
                     "last_scan": DB.get("charter_scan_at") or "", "status": status or DB.get("charter_status") or "",
                     "regular": sorted(CH.regular_set(OPTS.get("charter_regular"))), "crewtrac": crewtrac})


def crewtrac_failed(ct, kind, unconfirmed=False):
    """1.6.1: after REFUSED, block these details (no login until others are saved); after an OUTAGE (or a scan that
    failed after the login), back off 30 min, doubling, at most 6 h. unconfirmed: the login form came back with no
    refusal message (an OUTAGE whose next try decides: the same again is a refusal)."""
    now = local_now()
    if kind == CH.REFUSED:
        ct.update(state=CH.REFUSED, block=ct.get("creds", ""), at=_hst_iso(now), next_try="", outages=0, retry_at=0,
                  unconfirmed=0)
        seen = dict(DB.get("crewtrac_refused") or {})
        seen[ct.get("creds", "")] = ct["at"]
        DB.put("crewtrac_refused", dict(sorted(seen.items(), key=lambda kv: kv[1])[-CT_REFUSED_KEEP:]))
        log.info("charter: CrewTrac refused the login; no more tries until new CrewTrac details are saved")
        status = crewtrac_text(CH.REFUSED, now)
    else:
        n = int(ct.get("outages") or 0) + 1
        wait = CH.backoff_s(n)
        nxt = now + timedelta(seconds=wait)
        ct.update(state=CH.OUTAGE, outages=n, retry_at=time.time() + wait, at=_hst_iso(now), next_try=_hst_iso(nxt))
        if unconfirmed:
            ct["unconfirmed"] = 1
        log.info("charter: CrewTrac outage (%d in a row%s); next try in %d min", n,
                 ", the login form came back" if unconfirmed else "", wait // 60)
        status = crewtrac_text("unconfirmed" if unconfirmed else CH.OUTAGE, now, nxt)
    DB.put("crewtrac", ct)
    DB.put("charter_status", status)
    publish_charters()
    return False


def charter_scan():
    """One read-only pass over CrewTrac Scheduled Service: HNL departures and arrivals for the next 30
    days, A330 rows that are 99xx or touch a non-regular station become sensor.flight_watcher_charters
    entries; each new one fires event/charter once (HA pushes it). 1.6.1: no login at all while CrewTrac's refusal
    of these details stands or none are saved (the status is only republished)."""
    if is_pilot():  # 1.7.1 (F#22): a pilot never logs in to CrewTrac (his charters are the admin's)
        publish_charters()
        return False
    ct = crewtrac_state()
    if crewtrac_stopped(ct):
        publish_charters()
        return False
    CHARTER_BUSY.set()
    try:
        return _charter_scan(ct)
    finally:
        CHARTER_BUSY.clear()


def _charter_scan(ct):
    if is_pilot():
        return False
    u, p = crewtrac_login()
    sess = requests.Session()
    sess.headers["User-Agent"] = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                                  "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
    def capture(name, html):  # 0.7.3: first pages saved privately (never committed) to check the parser
        try:  # 1.6.2 (item 8): this instance's folder and policy (a pilot's were landing in the admin's folder)
            cap_write(f"ctweb_{name}.html", html or "")
        except Exception as e:
            log.info("charter capture skipped: %s", e)
    sc = CH.Scanner(sess, u, p, log, sleep=lambda: time.sleep(random.uniform(1.0, 2.5)), capture=capture)
    today = local_now().date()
    try:
        got = sc.login()
        if got == CH.OUTAGE and sc.unconfirmed:
            if ct.get("unconfirmed"):  # the login form came back twice in a row: CrewTrac is not taking these details
                log.info("charter: the login form came back again; taken as CrewTrac refusing these details")
                got = CH.REFUSED
            else:
                return crewtrac_failed(ct, CH.OUTAGE, unconfirmed=True)
        if got != CH.OK:
            return crewtrac_failed(ct, got)
        rows = sc.scan(today)
    except Exception as e:
        log.info("charter scan error: %s", e)
        return crewtrac_failed(ct, CH.OUTAGE)
    if rows is None:
        log.info("charter: CrewTrac session dropped mid-scan")
        return crewtrac_failed(ct, CH.OUTAGE)
    try:  # 1.6.1: an error from here on is a failed scan too: it backs off instead of scanning again in 30 s
        found = CH.unusual(rows, CH.regular_set(OPTS.get("charter_regular")))
        regular = CH.regular_set(OPTS.get("charter_regular"))
        known, new = CH.merge(CH.prune(DB.get("charters") or {}, regular), found, today.isoformat())
        DB.put("charters", known)
        DB.put("charter_scan_at", now_iso())
        now = local_now()
        ct.update(state=CH.OK, at=_hst_iso(now), next_try=_hst_iso(now + timedelta(seconds=CH.SCAN_EVERY_S)),
                  block="", outages=0, retry_at=0, unconfirmed=0)
        DB.put("crewtrac", ct)
        DB.put("charter_status", f"ok: {len(rows)} rows, {len(found)} unusual A330, {len(new)} new")
        log.info("charter scan: %d rows, %d unusual A330 flights, %d new", len(rows), len(found), len(new))
        for k in new:
            r = known[k]
            log.info("CHARTER %s %s %s %s (%s)", r.get("date"), r.get("flight"), r.get("route"), r.get("eqpt"),
                     r.get("why"))
            pub("event/charter", {"key": k, **{f: r.get(f) for f in ("date", "flight", "route", "scheduled", "eqpt",
                                                                        "tail", "why")}}, retain=False)
        publish_charters()
        try:
            charters_share()  # 1.7.1 (F#22): the pilots' Watchers show this list
        except Exception as e:  # noqa: BLE001 (sharing never fails the admin's own scan)
            log.info("charters not shared: %s", type(e).__name__)
    except Exception as e:  # noqa: BLE001
        log.info("charter scan error after the login: %s", e)
        return crewtrac_failed(ct, CH.OUTAGE)
    return True


def charter_wait(now=None):
    """1.6.1: seconds until the timer may scan (<= 0: due), or None when no login may run (none saved, or CrewTrac
    refused these details). After an outage: its back-off; else 6 h after the last scan (none yet: now)."""
    now = time.time() if now is None else now
    ct = crewtrac_state()
    if crewtrac_stopped(ct):
        return None
    if ct.get("state") == CH.OUTAGE:
        return float(ct.get("retry_at") or 0) - now
    last = DB.get("charter_scan_at")
    if not last:
        return 0  # 0.7.1: no scan yet = scan now (0.7.0 waited the full 6 h first)
    try:
        return CH.SCAN_EVERY_S - (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds()
    except ValueError:
        return 0


def charter_press_refusal(now=None, ct=None):
    """Why a Scan CrewTrac now press starts no scan now ('' when it does): one is running, CrewTrac's refusal of these
    details stands or none are saved, the login form came back last time, or the last pressed scan was under
    PRESS_GAP_S ago. 1.7.1 review: it also answers a portal press (press_answer), so the pilot reads why."""
    now = time.time() if now is None else now
    ct = crewtrac_state() if ct is None else ct
    if CHARTER_BUSY.is_set():
        return "a scan is running"
    if crewtrac_stopped(ct):
        return "no CrewTrac details saved" if ct.get("state") == "not_configured" else "CrewTrac refused these details"
    if ct.get("unconfirmed"):
        return "the login form came back last time; the next timed try decides"
    if now - float(ct.get("press_at") or 0) < CH.PRESS_GAP_S:
        return f"the last pressed scan was under {CH.PRESS_GAP_S // 60} min ago"
    return ""


def charter_press(now=None):
    """Scan CrewTrac now (1.6.1): starts a scan only when one may run (charter_press_refusal; the first press after new
    details is not held by PRESS_GAP_S). Otherwise the status is only republished. True when the thread was woken for
    a scan."""
    now = time.time() if now is None else now
    if is_pilot():  # 1.7.1 (F#22)
        log.info("charter scan pressed: %s; status republished, no scan", CHARTERS_NO_SCAN)
        publish_charters()
        return False
    ct = crewtrac_state()
    why = charter_press_refusal(now, ct)
    if why:
        log.info("charter scan pressed: %s; status republished, no scan", why)
        publish_charters()
        return False
    ct["press_at"] = now
    DB.put("crewtrac", ct)
    log.info("charter scan pressed")
    CHARTER_WAKE.set()
    return True


def charter_turn():
    """One turn of the charter thread: wait as charter_wait() says (or for a press), then scan."""
    wait = charter_wait()
    if wait is None:
        charter_scan()  # no login: the status only
        CHARTER_WAKE.wait(CHARTER_IDLE_S)
        CHARTER_WAKE.clear()
        return False
    if not CHARTER_WAKE.is_set():
        CHARTER_WAKE.wait(max(30, wait + random.uniform(0, 600)))
    CHARTER_WAKE.clear()
    try:
        return charter_scan()
    except Exception as e:
        log.info("charter thread: %s", e)
        return False
    finally:
        CHARTER_WAKE.clear()  # a press while it ran never queues a second scan


CHARTER_STARTED = threading.Event()


def start_charter_watch():
    """The charters status, then charter_thread, once per process (main: before the wait for a pilot's FLICA login,
    1.7.1 F#102, and at the usual place otherwise)."""
    if CHARTER_STARTED.is_set():
        return False
    CHARTER_STARTED.set()
    publish_charters()
    if is_pilot():  # 1.7.1 (F#22): no charter thread, no CrewTrac login; the admin's list comes over MQTT
        log.info("charters: shown from the admin's CrewTrac scan; this Watcher makes no CrewTrac login")
        return True
    try:
        charters_share()  # 1.7.1 (F#22): the last scan again for the pilots (retained)
    except Exception as e:  # noqa: BLE001
        log.info("charters not shared: %s", type(e).__name__)
    threading.Thread(target=charter_thread, daemon=True, name="charter").start()
    return True


def charter_thread():
    """Every 6 h (or on the Scan button) in its own thread: CrewTrac is a separate site and session, so
    this never touches the FLICA session or delays the pot checks. 1.6.1: after a failed scan the wait follows
    charter_wait() (refused: none until new details; outage: 30 min doubling to 6 h), not 30 s to 10 min. An error
    a turn lets out is logged and the thread goes on a minute later (it never ends the charter watch)."""
    while True:
        try:
            charter_turn()
        except Exception as e:  # noqa: BLE001
            log.info("charter thread: %s", e)
            CHARTER_WAKE.wait(60)
            CHARTER_WAKE.clear()


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
        if S.get("auto_swap") and has("auto_swap"):
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
        if n >= (FULL_MAX if full else PICKUP_PER_CHECK) or not BRK.allow("pairing"):
            break  # 1.6.2: no try is used up while pairing pages are stopped
        if now < p.get("next", 0) and not full:
            continue
        row = DB.find_row(k)
        url = row and (row.get("detail_url") or detail_url(row))
        if not url:
            pend.pop(k, None)
            continue
        if not (SUB.safe_get(url) and SM.safe_get(url)):  # read only: both guards, as every other FLICA read
            log.info("pickup %s: url refused by safe_get, dropped", k)
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
        except GT.GateSkip:  # 1.6.2 review: left out for a pilot's budget: no try used, the rest wait for a later check
            p["tries"] -= 1
            break
        except GT.BreakerOpen:  # given up (Pause) or the path stopped: not a failed read
            p["tries"] -= 1
            raise
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
    try:
        if inflt_check(fl, FULL_MAX if full else INFLT_PER_CHECK):
            done = True
    except GT.GateSkip:
        pass  # 1.6.2 review: a pilot's budget is kept for the pot; the in-flight reads wait for a later check
    was, RUN["optional"] = RUN["optional"], False  # a lookup the pilot asked for waits for his budget, never left out
    try:
        if pilot_check(fl):  # 0.8.0: a tapped picker's month
            done = True
    finally:
        RUN["optional"] = was
    return done


INFLT_PER_CHECK = 3


def inflt_check(fl, limit=INFLT_PER_CHECK):
    """0.5.2 (Ryan): was the picker in flight when the trip left the pot? See inflt.py (0.5.3)."""
    if not S.get("inflt_reset_v3"):
        DB.reset_inflt()
        S["inflt_reset_v3"] = True
        save_state(S)
    if not (BRK.allow("lookup") and BRK.allow("pairing")):  # 1.6.2: no try is used up while those reads are stopped
        return False
    changed = IF.run(fl, DB, limit, log, local_now, BASE, HST,
                     on_sched=lambda items: note_sched_trips(items, "picker"))  # FW-0056: the crew index reads them too
    if changed:
        publish_finds()
    return changed


FP_VERSION = 2  # bump when header_fingerprint changes, so stored hashes are re-learned


def email_alert(payload):
    """0.4.1: HA forwards each FLICA alert email (imap_content) here. Pairings it names that the
    pot watch never saw are queued; the next check (woken now) reads them and adds them to finds. 1.5.0 (FW-0063):
    the admin's only (admin_pushes)."""
    if not has("admin_pushes"):
        return
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
    the pot any more is stamped gone now and its pickup is tracked like any other find. 1.5.0 (FW-0063): the admin's
    only (admin_pushes): a pilot instance never reads the queue."""
    if not has("admin_pushes"):
        return False
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


def publish_pot(flat):
    """sensor.<prefix>_pot_count: the first 60 pot rows (close-in first). far_why and the FW-0042 smart fields stay off
    the sensor (sensor_row: no card reads them there yet; they would cost rows under cap_attrs' 12 KB): the DB, the
    finds month files, last_new and event/new_pairing keep them (the finds sensor carries FINDS_ATTR_KEYS only)."""
    pub("pot/state", {"count": len(flat), "pairings": [sensor_row(r) for r in flat[:60]]})


CAPTCHA_STOP_NOTE = ("FLICA showed a CAPTCHA page on {where} (never answered); press Re-arm after you have opened "
                     "FLICA yourself")


def check(fl):
    """One pass. Returns next action hint. After Check now (FLAGS full) every cached read is
    refreshed too: schedule, own trip times, pot details, pending pickups, tradeboard."""
    full, FLAGS["full"] = FLAGS.get("full", False), False
    if not S.get("pot_urls"):
        urls = fl.discover_pot_urls()
        if urls in ("captcha", "blocked"):  # 1.6.2 review: a stop, never a new login to get past the challenge
            set_machine("stopped_unexpected", CAPTCHA_STOP_NOTE.format(where="the main menu") if urls == "captcha"
                        else "FLICA showed a captcha/MFA/password page on the main menu")
            return "stop"
        if urls is None:
            return "needs_login"
        if not urls:
            set_machine("stopped_unexpected", f"no 'View Opentime Pot' found under '{OPTS['pot_section']}'")
            return "stop"
        S["pot_urls"] = urls
        S["discovered_at"] = time.time()
        save_state(S)
        log.info("pot pages: %s", list(urls))
    # 1.6.1: with no schedule stored, only the start's first pass forces the read (not every loop); then the back-off
    read_guard(schedule_check, fl, force=full or (not S.get("schedule") and not SCHED_FORCED["used"]))
    read_guard(own_trip_times, fl, full, optional=True)  # 1.6.2 review: optional reads (a pilot's budget, GATE_KEEP)
    publish_working_flight()  # FW-0067
    versions_check()
    uploads_check()
    pot_all = {}
    new_any = False
    was_regular = {k for v in (S.get("baseline") or {}).values() for k in v or ()}  # FW-0034: before this pass's reads
    for month, url in list(S["pot_urls"].items()):
        html = fl.fetch(url)
        kind = classify(html)
        if kind == "killed":
            return "killed"
        if kind == "blocked":
            set_machine("stopped_unexpected", "FLICA showed a captcha/MFA/password page")
            return "stop"
        if kind == "captcha":  # 1.6.2 review: a stop (it was a parse failure and a retry, loading it again)
            set_machine("stopped_unexpected", CAPTCHA_STOP_NOTE.format(where="the open time pot"))
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
        read_guard(capture, fl, month, html)
        read_guard(detail_probe, fl, pot, optional=True)
        read_guard(pot_details, fl, pot, full, optional=True)
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
    ci_rows, ci_kind = {}, "ok"
    try:  # FW-0034: the close-in folder (trips under 16 h to report), read only
        ci_rows, ci_kind = close_in_check(fl, pot_all, full, was_regular)
    except Exception as e:
        log.info("close-in check error: %s", e)
    pot_all[CLOSE_IN_KEY] = ci_rows
    for k in ci_rows:  # a trip FLICA moved to the close-in folder is still open: no pickup to check, never 'hidden'
        S.setdefault("pickup_pending", {}).pop(k, None)
    if ci_kind == "killed":
        return "killed"
    if ci_kind == "blocked":
        set_machine("stopped_unexpected", "FLICA showed a captcha/MFA/password page (close-in folder)")
        return "stop"
    if ci_kind == "captcha":
        set_machine("stopped_unexpected", CAPTCHA_STOP_NOTE.format(where="the close-in folder"))
        return "stop"
    if ci_kind == "expired":
        return "needs_login"
    # drop months no longer published, and cached details of pairings no longer in any pot
    S["baseline"] = {m: v for m, v in S["baseline"].items() if m in S["pot_urls"]}
    live = {k for p in pot_all.values() for k in p}
    S["details"] = {k: v for k, v in S.get("details", {}).items() if k in live}
    S["relogin_streak"] = 0
    save_state(S)
    flat = [dict(v, month=m) for m, p in pot_all.items() for v in p.values()]
    flat.sort(key=lambda r: r.get("src") != "C")  # FW-0034: close-in trips (under 16 h to report) first
    publish_pot(flat)
    read_guard(email_check, fl, pot_all)
    read_guard(pickup_check, fl, full, optional=True)
    publish_finds()  # rows carry live CA / details now, so publish every check
    read_guard(tradeboard_check, fl, full, optional=True)
    read_guard(requests_check, fl, optional=True)  # 1.2.0: swap / add / drop request decisions -> push
    read_guard(grid_check, fl, full, optional=True)
    swap_scan(flat)
    drop_scan()
    if FLAGS.pop("swap_map", False) and has("auto_swap"):
        read_guard(swap_map_probe, fl)
    publish_tickets()  # 0.10.1: cheap folder re-scan, the other instance may have written
    cr = read_guard(crew_index_check, fl, default="ok", optional=True)  # 0.10.1: at most CREW_PER_CHECK pages per check
    if cr != "ok":
        return cr
    pub("last_check", now_iso())
    S["last_check_ts"] = time.time()
    health_note_apply()  # 1.6.2: a start or login note gives way to the gate's and breakers' note ('' when none)
    pub("session", "ON")
    return "ok"


# ---------------------------------------------------------------- 1.6.0 (FW-0061) pilot portal: export, spool, prefs
# Only on a pilot whose option entry has portal: true (portal_on()); the admin never runs any of it. The export thread
# writes this pilot's states (read back from HA, masked), events, command results, list files and card bundle to
# /share/fw_portal/<name>/out/ as signed envelopes (portal.py, PORTAL_CONTRACT.md); the spool thread reads the HOM
# portal's commands from in/ and republishes the allowed ones on this Watcher's own MQTT topics, so the usual handlers
# and their checks run. No FLICA page loads are added.
EXPORT = {"on": False, "lock": threading.Lock(), "wake": threading.Event(), "dirty": set(), "events": False,
          "results": False, "files": True, "manifest": True, "cache": {}, "last": {}, "last_sweep": 0.0,
          "writer": None, "seq": None, "topics": {}, "ids": [], "file_sigs": {}, "files_list": [], "cards": None,
          "blobs": set(), "events_list": [], "results_list": [], "spool": None, "ntfy": None, "logged": set(),
          "retry": {}}
EXPORT_DEBOUNCE_S = 2.0  # a burst of publishes is one write, and writes are at least this far apart
EXPORT_SWEEP_S = 300  # every state is read again (and the files rescanned) this often
EXPORT_RETRY_S = 15  # a state HA had no answer for is read again after this, doubling while it stays missing
SPOOL_POLL_S = 1.0
SPOOL_MAX_PER_POLL = 200
PORTAL_LAYOUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "portal_layout.json")
PORTAL_CARDS_OUT = ("uploads-card", "row-colors", "layover-card")  # not in a portal (1.7.0: the tickets card is,
# revision 2; 1.7.1 FW-0072: the layover card is the admin's only in this release)
PAIRINGS_BACK_M = 2  # the shared pairings packages exported: from this many months back (HST), and every later one


def portal_once(key, msg, *a):
    """A log line once per process (a portal problem that would repeat on every pass)."""
    if key not in EXPORT["logged"]:
        EXPORT["logged"].add(key)
        log.info(msg, *a)


def portal_entity_defs():
    """(comp, oid, cfg) of this pilot's discovery entities a portal serves: the ones it has, minus the features the
    portal does not offer (roles.entity_on_portal: uploads; 1.7.0: his tickets sensor is served)."""
    return [(c, o, cfg) for c, o, cfg, f in entity_defs() if has(f) and ROLES.entity_on_portal(o, INSTANCE)]


def portal_ids():
    """Every entity id state.json carries (contract 3.4): the portal's discovery entities (sensor.<T>_settings among
    them), the rule live switches, and the pref helpers (synthesized from prefs.json, never read from HA)."""
    ids = [cfg["default_entity_id"] for _, _, cfg in portal_entity_defs()]
    with RULE_LOCK:
        rules = list(RULES["list"])
    ids += [f"switch.{RULE_UID}_{r['id']}_live" for r in rules if ROLES.PORTAL_RULE_ID_RE.fullmatch(str(r.get("id")))]
    ids += [ROLES.pref_entity(k, T) for k in ROLES.PREF_KEYS]
    ids.append(pilot_uploads_eid())  # 1.7.2 (FW-0066): synthesized from his upload records, never read from HA
    return list(dict.fromkeys(ids))


def portal_pref_ids():
    """The ids state.json synthesizes (never read from HA): the pref helpers and (1.7.2) the pilot's uploads view."""
    return {ROLES.pref_entity(k, T) for k in ROLES.PREF_KEYS} | {pilot_uploads_eid()}


def portal_topics():
    """{full MQTT topic: {entity ids}} from each portal entity's state and attribute topics: a publish there marks
    those ids for the next export."""
    m = {}
    for _, _, cfg in portal_entity_defs():
        for k in ("state_topic", "json_attributes_topic"):
            if cfg.get(k):
                m.setdefault(cfg[k], set()).add(cfg["default_entity_id"])
    return m


def portal_wrap(c):
    """Wraps c.publish so every publish of a portal pilot is noted (portal_note) after it goes out; a note never
    fails a publish."""
    orig = c.publish

    def publish(topic, payload=None, *a, **k):
        r = orig(topic, payload, *a, **k)
        try:
            portal_note(topic, payload)
        except Exception as e:  # noqa: BLE001
            portal_once("note", "portal note skipped: %s", type(e).__name__)
        return r
    c.publish = publish
    return c


def portal_note(topic, payload):
    """A publish on this Watcher's prefix: an event in roles.PORTAL_EVENTS goes to events.json (and ntfy); a state or
    attribute topic marks its ids dirty; the availability topic marks every id."""
    if not EXPORT["on"] or not isinstance(topic, str) or not topic.startswith(T + "/"):
        return
    sub = topic[len(T) + 1:]
    if sub.startswith("event/"):
        if sub[6:] in ROLES.PORTAL_EVENTS:
            try:
                p = json.loads(payload) if isinstance(payload, (str, bytes)) else payload
            except ValueError:
                p = {}
            portal_event(sub[6:], p if isinstance(p, dict) else {})
        return
    ids = set(EXPORT["topics"].get(topic) or ())
    m = re.fullmatch(r"rule/([a-z0-9_]+)/live/state", sub)
    if m:
        ids.add(f"switch.{RULE_UID}_{m.group(1)}_live")
    if topic == AVAIL:
        ids |= set(EXPORT["ids"])
    if sub == "rules/state":
        EXPORT["manifest"] = True  # a rule came or went: its live switch is in the manifest's services
    if ids:
        with EXPORT["lock"]:
            EXPORT["dirty"] |= ids
        EXPORT["wake"].set()


def portal_dirty(*ids):
    if EXPORT["on"]:
        with EXPORT["lock"]:
            EXPORT["dirty"] |= set(ids)
        EXPORT["wake"].set()


def portal_files_dirty():
    """A list or finds file was written: copy it to out/files on the next export (a portal pilot only)."""
    if EXPORT["on"]:
        EXPORT["files"] = True
        EXPORT["wake"].set()


def _portal_load(name, key):
    try:
        d = json.load(open(f"{DATA}/{name}", encoding="utf-8"))
        v = d.get(key) if isinstance(d, dict) else None
        return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []
    except (OSError, ValueError):
        return []


def portal_event(kind, payload):
    """One portal event (roles.PORTAL_EVENTS or a MACHINE_EVENTS kind): its record (portal.event_record, whitelisted
    fields only) joins the last EVENTS_KEEP in <data>/portal_events.json and events.json, and goes to ntfy when this
    pilot has it. Returns the record (None when the portal is off)."""
    if not EXPORT["on"]:
        return None
    try:
        return _portal_event(kind, payload)
    except Exception as e:  # noqa: BLE001 (never fails set_machine, pub or the MQTT thread)
        portal_once("event:" + type(e).__name__, "portal event skipped: %s", type(e).__name__)
        return None


def _portal_event(kind, payload):
    p = dict(payload) if isinstance(payload, dict) else {}
    if kind == "new_pairing" and not p.get("release"):
        try:
            _, rel = report_release(p)
            if rel:
                p["release"] = rel.strftime("%Y-%m-%d %H%M")
        except Exception:  # noqa: BLE001 (the release is a nicety; never fail the event)
            pass
    rec = PT.event_record(kind, p, EXPORT["seq"].next("event"), now_iso())
    with EXPORT["lock"]:
        EXPORT["events_list"] = (EXPORT["events_list"] + [rec])[-PT.EVENTS_KEEP:]
        try:
            PT.write_private(f"{DATA}/portal_events.json", PT.dumps({"events": EXPORT["events_list"]}))
        except OSError as e:
            portal_once("events_save", "portal events not saved: %s", type(e).__name__)
        EXPORT["events"] = True
    EXPORT["wake"].set()
    if EXPORT["ntfy"] is not None:
        EXPORT["ntfy"].enqueue(rec)
    return rec


PROC_START = time.time()
SCHED_UNREAD_DONE = "schedule_unread_day"  # DB: {day (HST), at} of the last schedule_unread event (one in 24 h)
_SU = {"held_at": 0.0}  # 1.7.2 (review): the last tick that saw him paused, stopped or waiting for his login


def schedule_unread_tick(now=None):
    """1.7.2 (contract 1 revision 3, audit F#3, F#112): a portal pilot whose Watcher has had no good FLICA schedule
    read for roles.SCHEDULE_UNREAD_H hours (since the last good read, or since this start when none came after it)
    gets one schedule_unread event a day (at least 24 h apart, 1.7.2 review: not again at 00:00 HST): his Alerts list
    and ntfy, view schedule, data only its state (failing: reads fail; waiting: none could run) and the hours since
    the last good read. Not while paused, waiting for his FLICA login or stopped: those have their own alert or are his
    own doing, and (1.7.2 review) the 6 h count again from the last tick that saw one, so his Pause off or Re-arm gets
    its first read in before any alert. The time is in the DB before the event. Returns the record or None."""
    if not EXPORT["on"]:
        return None
    now = time.time() if now is None else now
    st = S.get("machine") or ""
    if FLAGS.get("pause") or st in ("paused", "needs_settings") or st.startswith("stopped"):
        _SU["held_at"] = max(_SU["held_at"], now)
        return None
    try:
        last = datetime.fromisoformat(S["sched_read_at"]).timestamp() if S.get("sched_read_at") else 0.0
    except (TypeError, ValueError):
        last = 0.0
    if now - max(last, PROC_START, _SU["held_at"]) < ROLES.SCHEDULE_UNREAD_H * 3600:
        return None
    day = datetime.fromtimestamp(now, HST).strftime("%Y-%m-%d")
    done = DB.get(SCHED_UNREAD_DONE)
    prev = done.get("at") if isinstance(done, dict) else None
    if (isinstance(prev, (int, float)) and now - prev < 86400) or done == day:
        return None
    DB.put(SCHED_UNREAD_DONE, {"day": day, "at": now})
    hours = int((now - (last or PROC_START)) // 3600)
    state = "failing" if int(S.get("sched_fail") or 0) else "waiting"
    log.info("schedule not read for %d h (%s): portal alert", hours, state)
    return portal_event("schedule_unread", {"state": state, "hours": hours, "key": day})


def portal_result(cid, ok, why=""):
    """A command's result {id, ok, why} joins the last RESULTS_KEEP (results.json)."""
    with EXPORT["lock"]:
        EXPORT["results_list"] = (EXPORT["results_list"] + [{"id": cid, "ok": bool(ok), "why": str(why)[:200]}])[
            -PT.RESULTS_KEEP:]
        try:
            PT.write_private(f"{DATA}/portal_results.json", PT.dumps({"results": EXPORT["results_list"]}))
        except OSError as e:
            portal_once("results_save", "portal results not saved: %s", type(e).__name__)
        EXPORT["results"] = True
    EXPORT["wake"].set()


# ---- prefs (pref/set from the portal; contract 3.5)
PREFS_LOCK = threading.Lock()


def prefs_read():
    """{values: {key: value}, updated: {key: iso}, seeded: iso} from prefs.json; a portal pilot only ({} otherwise,
    and the file is never opened)."""
    if not portal_on():
        return {}
    try:
        d = json.load(open(PREFS_FILE, encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def pref_get(key):
    """This portal pilot's pref (roles.PREF_KEYS) from prefs.json, or None: not set, out of bounds, or any instance
    whose portal is off (the admin never reads prefs.json; tax_pct and pay_settings then read the HA helpers)."""
    if not portal_on():
        return None
    v = (prefs_read().get("values") or {}).get(key)
    if v is None:
        return None
    try:
        return ROLES.pref_value(key, v)
    except (ValueError, OverflowError, TypeError):
        return None


def pref_unconfirmed(key):
    """1.6.4: this portal pilot's pref is still flagged unconfirmed (prefs_seed: copied from a never-set helper, not
    set or kept since). False on any instance whose portal is off (prefs.json is never opened there)."""
    return portal_on() and key in (prefs_read().get("unconfirmed") or [])


def _prefs_save(d):
    PT.write_private(PREFS_FILE, json.dumps(d, separators=(",", ":")))


def pref_cmd(payload):
    """{T}/pref/set {"key", "value"} from the portal (republished by the spool): checked again here (bounds of
    roles.PREF_KEYS), saved to prefs.json (0600). True when saved."""
    if not portal_on():
        log.info("pref/set ignored: the portal is off on this instance")
        return False
    try:
        key, v = PT.check_pref(payload)
    except PT.PortalError as e:
        log.info("pref/set refused: %s", e)
        return False
    try:
        with PREFS_LOCK:
            d = prefs_read()
            d.setdefault("values", {})[key] = v
            d.setdefault("updated", {})[key] = now_iso()
            if key in (d.get("unconfirmed") or []):  # 1.6.2: the pilot set (or kept) it: no longer flagged
                d["unconfirmed"] = [k for k in d["unconfirmed"] if k != key]
            _prefs_save(d)
    except OSError as e:  # never reaches paho's thread
        log.info("pref %s not saved: %s", key, type(e).__name__)
        return False
    TAX["pct"] = None  # the pay line's tax % is read again
    log.info("pref %s set from the portal", key)
    portal_dirty(ROLES.pref_entity(key, T))
    return True


PREF_FLAG_KEYS = ("federal_tax_pct", "state_tax_pct", "longevity_year")  # the numbers a never-set helper left at its min
SEED_NEAR_S = 5  # 1.6.0's seed stamped each value a few microseconds apart from 'seeded'


def _iso_ts(v):
    try:
        t = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return (t if t.tzinfo else t.replace(tzinfo=timezone.utc)).timestamp()
    except (TypeError, ValueError):
        return None


def prefs_seed():
    """1.6.2 (Release A item 12): the HA helpers are never read any more (a portal pilot's were deleted with his HA
    dashboard; his prefs come only from pref/set). What the 1.6.0 one-time seed copied from helpers that were never set
    (an input_number starts at its minimum: federal 0 %, state 0 %, longevity year 1) is flagged once (prefs.json
    'checked'): a number pref at its minimum whose time is the seed's and that no pref/set changed since goes into
    'unconfirmed'. It is kept, and the schedule card says 'Set your tax and longevity in Pay settings' until a pref/set
    (or the card's Keep these) confirms it. Returns the keys flagged (None when there was nothing to do)."""
    if not portal_on():
        return None
    with PREFS_LOCK:
        d = prefs_read()
        if d.get("checked"):
            return None
        vals, upd, seeded = d.get("values") or {}, d.get("updated") or {}, _iso_ts(d.get("seeded"))
        took = []
        for key in PREF_FLAG_KEYS:
            t = _iso_ts(upd.get(key))
            try:
                at_min = float(vals.get(key)) == float(ROLES.PREF_KEYS[key]["min"])
            except (TypeError, ValueError):
                at_min = False
            if seeded is not None and t is not None and at_min and abs(t - seeded) <= SEED_NEAR_S:
                took.append(key)
        d["unconfirmed"] = sorted(set(d.get("unconfirmed") or []) | set(took))
        d["checked"] = now_iso()
        _prefs_save(d)
    if took:
        log.info("portal prefs: %d copied from never-set HA helpers flagged for the pilot to set", len(took))
        for k in took:
            portal_dirty(ROLES.pref_entity(k, T))
    return took


def pref_states():
    """The pref helpers as state.json shows them, from prefs.json (the HA helpers are not read for these)."""
    d = prefs_read()
    vals, upd = d.get("values") or {}, d.get("updated") or {}
    flag = set(d.get("unconfirmed") or [])
    out = {}
    for key, spec in ROLES.PREF_KEYS.items():
        v = pref_get(key) if key in vals else None
        attrs = {"friendly_name": key.replace("_", " ").capitalize()}
        if key in flag and v is not None:
            attrs["unconfirmed"] = True  # 1.6.2 (item 12): copied from a never-set helper; the card asks him to set it
        if spec["type"] == "number":
            st = "unknown" if v is None else str(float(v))
            attrs.update({"min": spec["min"], "max": spec["max"], "step": spec["step"], "mode": "box"})
            if spec["unit"]:
                attrs["unit_of_measurement"] = spec["unit"]
        else:
            st = "" if v is None else v
            attrs.update({"min": 0, "max": spec["max_len"], "mode": "text"})
        out[ROLES.pref_entity(key, T)] = {"state": st, "attributes": attrs, "last_changed": upd.get(key),
                                          "last_updated": upd.get(key)}
    return out


# ---- the export
def ha_state_full(entity_id):
    """(HTTP status, the state JSON) of one entity from HA (Supervisor API proxy, as ha_state); (0, None) when HA is
    not reachable."""
    try:
        r = requests.get(f"http://supervisor/core/api/states/{entity_id}",
                         headers={"Authorization": f"Bearer {os.environ.get('SUPERVISOR_TOKEN', '')}"}, timeout=5)
        return r.status_code, (r.json() if r.ok else None)
    except Exception:  # noqa: BLE001
        return 0, None


def _portal_write(kind, body, force=False):
    """Sign and write one out/ file when its payload changed since the last write (or force). True when written."""
    text = body if isinstance(body, str) else PT.dumps(body)
    if EXPORT["last"].get(kind) == text and not force:
        return False
    EXPORT["writer"].write(kind, text)
    EXPORT["last"][kind] = text
    return True


def portal_write_state(ids, read, now=None, beat=False):
    """state.json: the ids in read are fetched from HA again (one GET each), the rest come from the cache; masks of
    contract 3.4 (portal.state_entry); prefs synthesized. Over the 2 MB cap nothing is written (logged once).
    1.7.1 (F#7, F#110): beat (the full sweep, every EXPORT_SWEEP_S) writes it even when nothing changed: the same
    payload in a new envelope, so its seq (the write time) moves at least every 5 min and the portal can tell a live
    Watcher from a dead one in every state, needs_settings too. No new field: contract 1 as it is.
    An id that leaves state.json without an answer (a 404: HA has not made the entity yet, as in its restart; or no
    answer with nothing cached) is read again after EXPORT_RETRY_S, then 2x, 4x... while it stays missing, until the
    wait reaches EXPORT_SWEEP_S (the sweep covers it from then on), so for example the settings sensor and its pubkey
    are back within seconds, not 5 minutes, and an entity HA never has costs a few GETs, not one per pass."""
    now = time.time() if now is None else now
    cache, prefs, ok, retry = EXPORT["cache"], portal_pref_ids(), True, EXPORT["retry"]
    for eid in ids:
        if eid in prefs or eid not in read:
            continue
        code, d = ha_state_full(eid)
        if code == 200 and isinstance(d, dict):
            cache[eid] = PT.state_entry(d)
            retry.pop(eid, None)
            continue
        if code == 404:
            cache.pop(eid, None)
        else:
            ok = False
            if eid in cache:
                continue  # the last answer stays in state.json; the next sweep reads it again
        n = retry.get(eid, (0, None))[0]
        wait = EXPORT_RETRY_S * 2 ** n
        retry[eid] = (n + 1, now + wait if wait < EXPORT_SWEEP_S else None)
    for eid in [e for e in cache if e not in ids]:
        cache.pop(eid, None)
    for eid in [e for e in retry if e not in ids]:
        retry.pop(eid, None)
    states = {eid: cache[eid] for eid in ids if eid in cache}
    states.update(pref_states())
    try:
        states.update(pilot_uploads_state())  # 1.7.2 (FW-0066)
    except Exception as e:  # noqa: BLE001 (never stops the export)
        portal_once("pilot_uploads_state", "portal pilot uploads view skipped: %s", type(e).__name__)
    text = PT.dumps({"states": states, "ha_ok": ok})
    if len(text.encode("utf-8")) > PT.CAPS["state"]:
        portal_once("state_cap", "portal state over %d KB: not written", PT.CAPS["state"] // 1024)
        return False
    return _portal_write("state", text, force=beat)


def _portal_src_dir(path):
    """path when it is a real folder (lstat: not a symlink), else None (logged once): the list file folders are in
    HA's config folder, which other apps can write, and a symlinked one could point the export anywhere."""
    try:
        st = os.lstat(path)
    except OSError:
        return None
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        portal_once("src_dir:" + path, "portal list files in %s skipped: a symlink or not a folder", path)
        return None
    return path


def portal_file_sources():
    """[(kind, path)] of the list files this pilot's portal serves (roles.FILE_KINDS): its finds months and FW-0060 /
    FW-0069 list files under its current key, its school calendar, and the shared pairings packages from
    PAIRINGS_BACK_M months back on. No key goes into a kind. A folder that is a symlink is skipped (_portal_src_dir);
    portal_export_files reads each file without following a symlink."""
    out = []
    key = None
    try:
        key = www_key()
    except Exception:  # noqa: BLE001
        pass
    fdir = finds_dir() if _portal_src_dir(CARD_PAIRINGS) else None
    fdir = _portal_src_dir(fdir) if fdir else None
    try:
        names = sorted(os.listdir(fdir)) if fdir else []
    except OSError:
        names = []
    for n in names:
        m = WF.FINDS_RE.fullmatch(n)
        if m and key and n == WF.finds_name(m.group(1), key):
            out.append((f"file:finds:{m.group(1)}", os.path.join(fdir, n)))
            continue
        m = WF.LIST_RE.fullmatch(n)
        if m and key and n == WF.list_name(m.group(1), key) and m.group(1) in ROLES.FILE_KINDS:
            out.append((f"file:{m.group(1)}", os.path.join(fdir, n)))
            continue
        m = re.fullmatch(r"school_(\d{4}-\d{2})\.json", n)
        if m:
            out.append((f"file:school:{m.group(1)}", os.path.join(fdir, n)))
    t = local_now().date()
    y, mo = divmod(t.year * 12 + t.month - 1 - PAIRINGS_BACK_M, 12)
    first = f"{y:04d}-{mo + 1:02d}"
    try:
        shared = sorted(os.listdir(CARD_PAIRINGS)) if _portal_src_dir(CARD_PAIRINGS) else []
    except OSError:
        shared = []
    for n in shared:
        m = re.fullmatch(r"pairings_(\d{4}-\d{2})\.json", n)
        if m and m.group(1) >= first:
            out.append((f"file:pairings:{m.group(1)}", os.path.join(CARD_PAIRINGS, n)))
    return out


def portal_export_files():
    """Copies each list file whose time, size or inode changed to out/files/ (payload: the file's text exactly) and
    removes the ones gone. Only a plain file is read (lstat, then portal.read_plain: never through a symlink, never
    blocking on a FIFO, at most the 8 MB cap), so nothing another app plants in HA's config folder can make the export
    copy a file of this container (/data) or stall. True when the set of files changed (the manifest lists them)."""
    sigs, present = EXPORT["file_sigs"], set()
    for kind, path in portal_file_sources():
        try:
            st = os.lstat(path)
            if not stat.S_ISREG(st.st_mode):
                raise PT.PortalError("not a plain file")
            if st.st_size > PT.CAPS["file"]:
                portal_once("cap:" + kind, "portal file %s over %d KB: not served", kind, PT.CAPS["file"] // 1024)
                continue
            sig = (st.st_mtime_ns, st.st_size, st.st_ino)
            if sigs.get(kind) != sig:
                raw, fst = PT.read_plain(path, PT.CAPS["file"])
                EXPORT["writer"].write(kind, raw.decode("utf-8"))
                sigs[kind] = (fst.st_mtime_ns, fst.st_size, fst.st_ino)
            present.add(kind)
        except PT.PortalError as e:
            if str(e).startswith("over "):
                portal_once("cap:" + kind, "portal file %s over %d KB: not served", kind, PT.CAPS["file"] // 1024)
            else:
                portal_once("file:" + kind, "portal file %s skipped: %s", kind, e)
        except (OSError, ValueError) as e:
            portal_once("file:" + kind, "portal file %s skipped: %s", kind, type(e).__name__)
    fdir = os.path.join(PORTAL_DIR, "out", "files")
    try:
        on_disk = os.listdir(fdir)
    except OSError:
        on_disk = []
    for n in on_disk:
        k = PT.kind_of("files/" + n)
        if k and k not in present:
            try:
                os.unlink(os.path.join(fdir, n))
            except FileNotFoundError:
                pass
            sigs.pop(k, None)
    files = sorted(k[5:] for k in present)
    if files != EXPORT["files_list"]:
        EXPORT["files_list"] = files
        return True
    return False


def portal_cards():
    """{file name: text} of this pilot's card copies a portal serves (cards.build, as deployed under /local/, with
    FW_PORTAL on: portal.portal_card), without the uploads card and the row colors (1.7.0: the tickets card is in,
    contract 1 revision 2); built once per process."""
    if EXPORT["cards"] is None:
        import cards as CARDS
        out = {}
        for fn, text in CARDS.build(VERSION, [INSTANCE]).items():
            m = re.fullmatch(r"flight-watcher-([a-z-]+)-%s\.js" % re.escape(INSTANCE), fn)
            if m and m.group(1) not in PORTAL_CARDS_OUT:
                out[fn] = PT.portal_card(text)  # FW_PORTAL on: the settings card sends sealed or nothing
        EXPORT["cards"] = out
    return EXPORT["cards"]


def portal_layout():
    """The tabs of portal_layout.json with this pilot's name in place of {name}."""
    with open(PORTAL_LAYOUT, encoding="utf-8") as f:
        return {"tabs": json.loads(f.read().replace("{name}", INSTANCE))["tabs"]}


def _portal_svc(comp, sub):
    if comp == "switch":
        return {"toggle": {"sub": sub, "on": "ON", "off": "OFF"}, "turn_on": {"sub": sub, "payload": "ON"},
                "turn_off": {"sub": sub, "payload": "OFF"}}
    if comp == "button":
        return {"press": {"sub": sub, "payload": "PRESS"}}
    if comp == "number":
        return {"set_value": {"sub": sub}}
    return None


def portal_services():
    """{entity id: {service: how}} for the manifest: each portal entity whose command topic is an allowed portal sub
    (entity_defs), the rule live switches, the pref helpers (pref/set with their key) and the local helpers."""
    sv = {}
    for comp, _, cfg in portal_entity_defs():
        ct = cfg.get("command_topic") or ""
        sub = ct[len(T) + 1:] if ct.startswith(T + "/") else ""
        how = _portal_svc(comp, sub) if ROLES.portal_sub(sub) else None
        if how:
            sv[cfg["default_entity_id"]] = how
    with RULE_LOCK:
        rules = list(RULES["list"])
    for r in rules:
        sub = f"rule/{r.get('id')}/live/set"
        if ROLES.portal_sub(sub):
            sv[f"switch.{RULE_UID}_{r['id']}_live"] = _portal_svc("switch", sub)
    for key in ROLES.PREF_KEYS:
        sv[ROLES.pref_entity(key, T)] = {"set_value": {"sub": "pref/set", "key": key}}
    for spec in ROLES.LOCAL_HELPERS.values():
        sv[spec["entity"].format(prefix=T)] = {s: {"local": True} for s in spec["services"]}
    return sv


def portal_mqtt_subs(cards=None):
    """The allowed subs the bundled cards publish to directly (mqtt.publish), sorted; drop/set (admin only) is not."""
    subs = set()
    for text in (cards if cards is not None else portal_cards()).values():
        subs |= PT.card_subs(text, T)
    return sorted(s for s in subs if ROLES.portal_sub(s))


def portal_write_manifest():
    """The card blobs (content-addressed, out/blobs/<sha256>.js) and manifest.json (contract 3.4)."""
    w, shas = EXPORT["writer"], {}
    for fn, text in sorted(portal_cards().items()):
        shas[fn] = w.blob(text)
    EXPORT["blobs"] = set(shas.values())
    body = {"contract": ROLES.CONTRACT, "revision": ROLES.CONTRACT_REVISION, "app_version": VERSION,
            "pilot": INSTANCE, "prefix": T,
            "role": ROLES.role(INSTANCE), "cards": shas, "layout": portal_layout(), "services": portal_services(),
            "mqtt_subs": portal_mqtt_subs(), "files": list(EXPORT["files_list"]), "ntfy": EXPORT["ntfy"] is not None}
    return _portal_write("manifest", body)


def portal_export_once(full=None, now=None):
    """One export pass: changed states (all of them, the files and the blob sweep on a full pass, every
    EXPORT_SWEEP_S), events, results, files and the manifest, each written only when it changed."""
    now = time.time() if now is None else now
    if full is None:
        full = now - EXPORT["last_sweep"] >= EXPORT_SWEEP_S
    ids = portal_ids()
    with EXPORT["lock"]:
        EXPORT["ids"] = ids
        read = set(ids) if full else EXPORT["dirty"] & set(ids)
        EXPORT["dirty"] = set()
        ev, res, files, man = EXPORT["events"], EXPORT["results"], EXPORT["files"] or full, EXPORT["manifest"] or full
        EXPORT["events"] = EXPORT["results"] = EXPORT["files"] = EXPORT["manifest"] = False
        evs, rss = list(EXPORT["events_list"]), list(EXPORT["results_list"])
    retry = EXPORT["retry"]  # the export thread's own (portal_write_state): no lock
    for eid in [e for e, (_, at) in retry.items() if at is not None and at <= now and e in ids]:
        read.add(eid)  # a state HA had no answer for: read again (portal_write_state sets the next try)
        retry[eid] = (retry[eid][0], None)
    if full:
        try:
            prefs_seed()  # 1.6.2: the one-time flag of never-set helper values (no HA read); at once once done
        except OSError as e:
            portal_once("prefs_seed_save", "portal prefs not checked: %s", type(e).__name__)
    # 1.6.2 (Release A): the list files first, then the manifest when the file set changed, then the state: a state that
    # names a new rev never points at a file not written yet (a card that fetched the old one never asked again)
    if files and portal_export_files():
        man = True
    if man:
        portal_write_manifest()
    if read or full:
        portal_write_state(ids, read, now, beat=full)  # 1.7.1 (F#7, F#110): the full sweep is the heartbeat
    if ev or full:
        _portal_write("events", {"events": evs})
    if res or full:
        _portal_write("results", {"results": rss})
    if full:
        EXPORT["last_sweep"] = now
        EXPORT["writer"].sweep_blobs(EXPORT["blobs"], now)


def portal_wait_s(now=None):
    """How long the export thread waits when no publish wakes it: until the next sweep or the next retry of a state HA
    had no answer for (portal_write_state), whichever comes first; at most EXPORT_SWEEP_S."""
    now = time.time() if now is None else now
    due = [EXPORT["last_sweep"] + EXPORT_SWEEP_S] + [at for _, at in EXPORT["retry"].values() if at is not None]
    return max(0.0, min(EXPORT_SWEEP_S, min(due) - now))


def portal_thread():
    while True:
        try:
            EXPORT["wake"].wait(timeout=portal_wait_s())
            EXPORT["wake"].clear()
            time.sleep(EXPORT_DEBOUNCE_S)
            portal_export_once()
        except Exception as e:  # noqa: BLE001 (the export must never stop the Watcher)
            log.info("portal export skipped: %s: %s", type(e).__name__, e)
            time.sleep(EXPORT_DEBOUNCE_S)


# ---- the spool (contract 3.5)
def portal_spool_once():
    """Reads every command file in in/ once (oldest name first): an accepted command is republished on {T}/{sub}
    (qos 1, not retained), so on_message's own checks run; each file is deleted and gets a result. Returns how many
    were accepted. The in/ folder must be a real folder, owned by the portal's uid when the Watcher runs as root."""
    d = os.path.join(PORTAL_DIR, "in")
    try:
        st = os.lstat(d)
    except OSError:
        return 0
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode) or (
            os.geteuid() == 0 and st.st_uid != PT.PORTAL_UID):
        portal_once("in_dir", "portal in/ folder refused: not the portal's folder")
        return 0
    n, spool = 0, EXPORT["spool"]
    names = spool.names(d)  # never a dotfile; one the portal abandoned long ago is removed
    if spool.reaped:
        portal_once("spool_reaped", "portal in/: temp files the portal left behind (over %d s old) are removed",
                    PT.DOT_STALE_S)
    for name in names[:SPOOL_MAX_PER_POLL]:
        try:
            r = spool.take(os.path.join(d, name))
        except PT.PortalError as e:
            log.info("portal command refused: %s", e)
            if e.cid:
                portal_result(e.cid, False, str(e))
            if name in spool.stuck:
                log.info("portal in/ folder left in place (not empty): skipped from now on")
            continue
        except Exception as e:  # noqa: BLE001 (one bad entry never ends the poll; the type only, once per type)
            portal_once("spool_entry:" + type(e).__name__, "portal command skipped: %s", type(e).__name__)
            continue
        if r is None:
            continue
        cid, sub, payload = r
        ok, why = press_answer(sub)  # 1.7.1 (F#12, F#92, F#149): a press the Watcher would ignore says so, ok false
        if not ok:
            log.info("portal command %s not taken: %s", sub, why)
            portal_result(cid, False, why)
            continue
        try:
            MQ.publish(f"{T}/{sub}", payload, qos=1, retain=False)
        except Exception as e:  # noqa: BLE001
            log.info("portal command %s not republished: %s", sub, type(e).__name__)
            portal_result(cid, False, "not republished")
            continue
        log.info("portal command %s accepted", sub)
        portal_result(cid, True, why or freq_clamp_note(sub, payload))
        n += 1
    return n


def freq_clamp_note(sub, payload):
    """1.6.2 review: a check frequency the portal passed (contract 1's range) but this pilot's Watcher moves into his
    own (FREQ_LIMITS, e.g. hunt 95 s -> 90 s): the result says so instead of a bare ok. '' otherwise. Since Ryan's
    2026-11-10 ranges every value contract 1 passes is inside the Watcher's own, so it says nothing for those."""
    key = {"freq/normal_min/set": "normal_min", "freq/hunt_s/set": "hunt_s"}.get(sub)
    if not key:
        return ""
    try:
        v = int(round(float(payload)))
    except (ValueError, TypeError, OverflowError):
        return ""
    lo, hi = FREQ_LIMITS[key]
    got = max(lo, min(hi, v))
    unit = "min" if key == "normal_min" else "s"
    return f"set to {got} {unit}, the {'fastest' if got == lo else 'slowest'} this Watcher allows" if got != v else ""


def spool_thread():
    while True:
        try:
            portal_spool_once()
        except Exception as e:  # noqa: BLE001
            portal_once("spool", "portal spool skipped: %s", type(e).__name__)
        time.sleep(SPOOL_POLL_S)


def ntfy_start():
    """An ntfy sender when this portal pilot saved a usable topic (sealed settings), else None. 1.6.2 (item 9, Ryan:
    topic-only is allowed): the token is optional; without one each push carries only the pairing, the date and the
    fit (ntfy.plain_text). A saved topic too easy to guess (ntfy.topic_refusal) keeps ntfy off."""
    c = load_creds()
    topic, token = c.get("ntfy_topic"), c.get("ntfy_token") or ""
    if not topic:
        return None
    if not NT.valid(topic, token):
        log.info("ntfy off: the saved topic or token is not usable" + (
            " (a topic needs at least 24 letters and digits: generate a new one on Settings)"
            if NT.topic_refusal(topic) else ""))
        return None
    log.info("ntfy on for this pilot's portal events (%s)", "with an access token" if token else
             "topic only: pairing, date and fit in each push")
    return NT.Ntfy(topic, token, PORTAL_ORIGIN, log=log.info)


def portal_start(threads=True):
    """On a pilot whose portal is on, before the settings wait (James enters his first logins through the portal):
    the signing key (made by run.py; never made or moved here), the writer, saved events and results, the spool, the
    one-time prefs seed, ntfy and the two threads. False (silently) on any other instance."""
    if not portal_on() or EXPORT["on"]:
        return False
    out = os.path.join(PORTAL_DIR, "out")
    try:
        key = PT.load_key(PORTAL_KEY_FILE, create=False)
        st = os.lstat(out)
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
            raise PT.PortalError("out/ is not a folder")
    except (OSError, PT.PortalError) as e:
        log.info("pilot portal off: %s", e if isinstance(e, PT.PortalError) else type(e).__name__)
        return False
    seq = PT.SeqStore(f"{DATA}/portal_seq.json")
    EXPORT.update(seq=seq, writer=PT.Writer(out, INSTANCE, key, seq), topics=portal_topics(),
                  events_list=_portal_load("portal_events.json", "events")[-PT.EVENTS_KEEP:],
                  results_list=_portal_load("portal_results.json", "results")[-PT.RESULTS_KEEP:],
                  spool=PT.Spool(INSTANCE, f"{DATA}/portal_spool.json",
                                 expect_uid=PT.PORTAL_UID if os.geteuid() == 0 else None))
    EXPORT["on"] = True
    try:
        prefs_seed()
    except OSError as e:
        log.info("portal prefs not checked: %s", type(e).__name__)
    EXPORT["ntfy"] = ntfy_start()
    try:
        pilot_upload_restarted()  # 1.7.2 (review): an upload cut off by the restart gets its answer
    except Exception as e:  # noqa: BLE001
        log.info("pilot upload answers not settled: %s", type(e).__name__)
    log.info("pilot portal on: contract %d, export to %s", ROLES.CONTRACT, out)
    if threads:
        threading.Thread(target=portal_thread, daemon=True, name="portal").start()
        threading.Thread(target=spool_thread, daemon=True, name="portal-spool").start()
    EXPORT["wake"].set()
    return True


def enforce_role():
    """1.5.0 (FW-0063): a pilot instance has no auto swap (auto_swap); a value an older version stored is turned off
    once, at start, before on_connect would publish it."""
    if not has("auto_swap") and S.get("auto_swap"):
        S["auto_swap"] = False
        save_state(S)
        log.info("auto swap off: not for a pilot instance")


# 1.6.2 (Release A item 14): machine notes a pilot reads in his portal: no Home Assistant step, no MQTT topic, and no
# other pilot's name (the clock card puts "Someone signed into FLICA with your account." before a yield's note)
NEEDS_SETTINGS_NOTE = "enter your FLICA username and password on the Settings tab"
PAUSED_NOTE = "paused: the Pause switch is on"


def yield_note(cool_s):
    """The yielded note: the admin's as before ('Ryan logged in elsewhere, ...'); a pilot's names nobody."""
    if ROLES.role(INSTANCE) == ROLES.ADMIN:
        return f"Ryan logged in elsewhere, back in {int(cool_s / 60)} min"
    return f"back in {int(cool_s / 60)} min"


def captures_cleanup():
    """1.6.2 review, once (DB caps_cleanup_v): 1.6.1 wrote a pilot's pages into the admin's captures folder and an
    unmasked login screenshot into the pilot's folder. The admin deletes those names from his folder; each pilot
    deletes his screenshot, makes his captures folder 0700 and prunes it. Only a count is logged."""
    if DB.get("caps_cleanup_v") == 1:
        return 0
    try:
        n = CAPS.cleanup_admin(CAPTURE_DIR) if CAP.admin else CAP.cleanup_pilot()
    except Exception as e:  # noqa: BLE001 (never stops a start)
        log.info("captures cleanup skipped: %s", type(e).__name__)
        return 0
    DB.put("caps_cleanup_v", 1)
    log.info("captures cleanup (1.6.2): %d old file%s deleted", n, "" if n == 1 else "s")
    return n


def main():
    global MQ
    migrate_swap_mode()  # FW-0028: before on_connect publishes the mode
    enforce_role()
    flica_key_start()  # 1.7.4: a pilot's refusal record keyed (or its key found lost) before any command reads it
    captures_cleanup()  # 1.6.2 review: what 1.6.1 left of a pilot in the admin's folder, his unmasked screenshot
    MQ = mqtt_start()
    start_upload_janitor()  # FW-0066: chunks arrive as soon as MQTT is up, even while a second pilot waits for settings
    portal_start()  # 1.6.0 (FW-0061): a portal pilot's export and spool, before the settings wait (no-op otherwise)
    time.sleep(2)
    if not OPTS.get("username") or not OPTS.get("password"):
        if not has("addon_config"):  # 0.10.0: a pilot gets credentials over MQTT; wait for them (settings/set restarts us)
            set_machine("needs_settings", NEEDS_SETTINGS_NOTE)  # 1.6.2: words a pilot can act on (no MQTT topic)
            no_next_check()
            pub("session", "OFF")
            log.info("no credentials for instance %s: waiting on %s/settings/set", INSTANCE, T)
            # 1.7.1 (F#102): CrewTrac is its own site and login (charter_thread): a pilot who saved only his CrewTrac
            # details gets its scans and his Scan CrewTrac now while the FLICA watch waits for its login
            start_charter_watch()
            while True:
                time.sleep(3600)
        set_machine("stopped_unexpected", "enter your FLICA username and password: dashboard Settings tab")
    elif S.get("machine", "").startswith("stopped"):
        lost = flica_refused_at() if S.get(FL_KEY_LOST) else None
        if lost is not None:  # 1.7.4: Re-arm cannot lift a block whose key was lost; a save in Settings can
            set_machine(S["machine"], flica_refused_note(lost))
        else:
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
    publish_working_flight(force=True)  # FW-0067
    publish_trade()
    publish_charters()
    publish_improved()
    publish_tickets(force=True)
    publish_crew_index()
    versions_check(force_pub=True)
    uploads_check()
    recall_eval()
    start_charter_watch()
    threading.Thread(target=ccr_thread, daemon=True, name="ccr").start()  # 1.4.6: Hark's answers to CCR requests
    if os.environ.get("FLIGHT_WATCHER_WEB", "1") == "1":  # 0.10.0: only the default instance serves the ingress page
        web.serve(int(os.environ.get("INGRESS_PORT", "8099")), VERSION, lambda: RULES["list"],
                  save_rules_from_page, DB, log, get_settings=lambda: settings_state(load_creds()),
                  save_settings=lambda d: settings_cmd(json.dumps(d)), clear_settings=settings_clear,
                  on_saved=lambda: publish_uploads(force=True), portal_key=PORTAL_PUB)
    last_month_check = None
    with sync_playwright() as pw:
        fl = Flica(pw)
        while True:
            st = S.get("machine", "idle")
            # 1.7.1 (F#92): a Re-arm pressed while stepped aside for the pilot's own FLICA login waits for the
            # step-aside's end (another command waking the loop meanwhile no longer cuts it short); FLAGS rearm stays
            if FLAGS["rearm"] and not (st == "yielded" and time.time() < float(S.get("yield_until") or 0)):
                if st.startswith("stopped") or st in ("yielded", "backoff"):
                    at = flica_refused_at()
                    if at is not None:  # 1.6.2 review: FLICA refused these details: no login until others are saved
                        FLAGS["rearm"] = False
                        set_machine(st, flica_refused_note(at))
                        log.info("re-arm: FLICA refused these login details; no login until others are saved")
                        continue
                    if login_deferred(st, "Re-arm pressed"):  # a pilot's logins are LOGIN_MIN_GAP_S apart
                        continue  # FLAGS rearm stays set: the login runs once the wait is over
                    FLAGS["rearm"] = False
                    S["kills"] = []
                    S["pot_urls"] = {}
                    S["parse_fail"] = 0
                    S["relogin_streak"] = 0
                    if S.pop("fingerprint_pending", None):
                        S["fingerprints"] = {}  # Re-arm after a layout park accepts the new layout
                        log.info("re-arm: pot header fingerprints cleared, re-learned on next check")
                    try_login(fl, "re-arm")
                    continue
                FLAGS["rearm"] = False
            if st.startswith("stopped"):
                no_next_check()
                sleep(3600)
                continue
            if FLAGS["pause"]:
                if st != "paused":
                    set_machine("paused", PAUSED_NOTE)
                no_next_check()
                sleep(3600)
                continue
            if st == "paused":
                if is_pilot():
                    # 1.6.2 review: a pilot's un-pause checks with the session he has (its cookies are kept); a new
                    # login follows only if that check finds the session gone (needs_login, the back-off below)
                    set_machine("hunting" if FLAGS["hunt"] else "idle", "un-paused")
                elif not try_login(fl, "un-pause"):
                    continue
                st = S["machine"]
            if st == "yielded":
                wait_until = S.get("yield_until", 0)
                if time.time() < wait_until:
                    sleep_announced(wait_until - time.time())
                    continue
                if login_deferred(st):
                    continue
                if not try_login(fl, "after yield cooldown"):
                    continue
            if st == "backoff":
                wait_until = S.get("relogin_at", 0)
                if time.time() < wait_until:
                    sleep_announced(wait_until - time.time())
                    continue
                if login_deferred(st):
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
            held_apply()  # 1.6.2 (Ryan 2026-11-10): a pilot's hunt his budget holds says so in the state note
            # 1.6.2: a check starts once GATE_CHECK_TOKENS loads fit the budget (a pilot's 100 an hour, the host's 480);
            # until then the loop waits (WAKE-able: pause and Check now are still read) and the state note says so
            wait, why = budget_hold()
            if wait > 0:
                gate_note(why, time.time() + wait)
                sleep_announced(wait)
                continue
            if HEALTH["gate"]:
                gate_note("", None)
            floor = check_floor_wait()  # 1.6.2 review: a pilot's checks start at least 5 s apart, whatever woke us
            if floor > 0:
                sleep_announced(floor)
                continue
            WAKE_DUE["at"] = 0.0
            S["check_started_ts"] = time.time()
            RUN.update(check=True, aborted="", skipped=set())
            try:
                res = check(fl)
            except GT.GateAbort as e:  # Pause or a stop while a load waited: the check ends, nothing more loaded
                log.info("check ended: %s", e)
                continue
            except Exception as e:
                log.warning("check error: %s", e)
                S["net_fail"] = S.get("net_fail", 0) + 1
                if S["net_fail"] >= 3:
                    set_machine("stopped_unexpected", f"3 check errors in a row: {e}")
                sleep_announced(gap())
                continue
            finally:
                RUN["check"] = False
            S["net_fail"] = 0
            if res == "needs_login":
                pub("session", "OFF")
                streak = S.get("relogin_streak", 0)
                if streak >= len(BACKOFF_MIN):
                    set_machine("stopped_unexpected",
                                f"session lost {streak} times in a row with no good check between; parked")
                    continue
                wait = max(BACKOFF_MIN[streak], round(login_wait() / 60))  # 1.6.2 review: a pilot's login floor too
                S["relogin_streak"] = streak + 1
                S["relogin_at"] = time.time() + max(wait * 60, login_wait())
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
                set_machine("yielded", yield_note(cool))
                continue
            if res == "stop":
                pub("session", "OFF")
                continue
            if res == "ok":
                want = "hunting" if FLAGS["hunt"] else "idle"
                if S["machine"] != want:
                    set_machine(want)
                    health_note_apply()  # 1.6.2: a stopped read path or a budget wait stays in the note
            sleep_announced(gap())


if __name__ == "__main__":
    main()
