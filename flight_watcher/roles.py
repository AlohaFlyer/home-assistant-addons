"""Flight Watcher pilots and roles (1.5.0, FW-0063): what each Watcher instance may do.

The default instance (prefix flight_watcher, /data, Ryan's) is the only admin. Every other instance (option `pilots`,
or the older `second_pilot`) is a pilot. The role comes from the instance, never from an option, so it cannot disagree
with what is already hard-wired to the default instance: its prefix and /data, the add-on Configuration tab, Hark's
CCR folder and the duties that need one writer.

One table, FEATURES, says who has each feature and whether a pilot's portal (1.6.0) may offer it; README.md carries
the same table (tests/test_roles.py keeps them equal). SUBS maps every MQTT command topic an instance subscribes to
onto a feature, EVENTS every event topic, and ENTITY_FEATURE the discovery entities that are not core. Plain Python,
no imports from the app, so ha/check_push_isolation.py can read RESERVED too.

1.6.0 (FW-0061): the pilot portal's contract 1 (the bottom of this file): what a portal may send, which events and
fields it gets, the prefs it may set and the files it serves. portal.py builds tests/fixtures/portal_contract_v1.json
from these; PORTAL_CONTRACT.md documents them.
"""
import math
import re

ADMIN, PILOT = "admin", "pilot"
ALL = "all"
INTERNAL = "internal"  # a retained state topic the instance reads back after a restart (never a command)

# name: (who has it: "admin" or "all", offered on a pilot's portal, what it gates)
FEATURES = {
    "core": (ALL, True, "pot watch, schedule, finds, pickups, Tradeboard, recall check, versions, rules, pilot "
                        "lookup, charters, swap ideas, trade and blocked marks, switches, buttons and sliders"),
    "prefs": (ALL, True, "the pay and tax helpers the schedule card and the Watcher read (federal and state tax %, "
                         "longevity year, ER trips)"),
    "crew_index": (ADMIN, False, "the crew index runs (crew_scan/press, sensor crew_index, button update_schedules), "
                                 "previous-month lookups and pilot schedule versions from the index"),
    "hark_ccr": (ADMIN, False, "CCR requests to Hark (/share/flight_watcher/ccr_requests) and the poll of its "
                               "replies"),
    "one_writer": (ADMIN, False, "files with one writer: the seniority list re-read, the versions seed, the finds "
                                 "file sweep of other folders"),
    "web_ui": (ADMIN, False, "the ingress Web UI (run.py starts it for the default instance only)"),
    "addon_config": (ADMIN, False, "the FLICA and CrewTrac logins from the add-on Configuration tab"),
    "drop_mark": (ADMIN, False, "would drop marks (drop/set), the drop scan, event/drop_ready, sensor would_drop"),
    "auto_swap": (ADMIN, False, "the auto swap dry run switch (auto_swap/set) and the swap page mapping "
                                "(swap_map/press)"),
    "paycheck": (ADMIN, False, "the paycheck check card on Ryan's dashboard (no Watcher code)"),
    "admin_pushes": (ADMIN, False, "FLICA alert emails HA forwards (email/alert) and the email check"),
    "tickets": (ALL, False, "tickets (ticket/new, image, act, edit, delete); a pilot sees and acts on his own"),
    "uploads": (ALL, False, "uploads in chunks (upload/chunk) and the uploads sensors"),
}

# every MQTT command topic (after <prefix>/) an instance subscribes to, in the 1.4.12 order, and its feature
SUBS = {
    "hunt/set": "core", "pause/set": "core", "rearm/press": "core",
    "hunt/state": INTERNAL, "pause/state": INTERNAL,
    "rule/+/live/set": "core", "check_now/press": "core", "freq/normal_min/set": "core", "freq/hunt_s/set": "core",
    "email/alert": "admin_pushes", "blocked/set": "core", "trade/set": "core", "auto_swap/set": "auto_swap",
    "swap_map/press": "auto_swap", "drop/set": "drop_mark", "charter_scan/press": "core", "pilot/set": "core",
    "improved/set": "core", "recall/set": "core", "recall/act": "core", "settings/set": "core",
    "ticket/new": "tickets", "ticket/image": "tickets", "ticket/act": "tickets", "ticket/edit": "tickets",
    "ticket/delete": "tickets", "crew_scan/press": "crew_index",
    "upload/chunk": "uploads",
    "pref/set": "prefs",  # 1.6.0 (FW-0061): portal only (PORTAL_SUBS), never on the admin
}
QOS = {"upload/chunk": 1}  # FW-0066: chunks at qos 1; every other subscription at qos 0
# 1.6.0 (FW-0061): subscriptions taken only on a pilot instance whose portal is on (option pilots[].portal); the
# admin never takes them, so its list stays the 1.4.12 one
PORTAL_SUBS = ("pref/set",)

# every event topic (after <prefix>/event/) and its feature
EVENTS = {
    "new_pairing": "core", "hidden": "core", "charter": "core", "request_decided": "core", "rule_match": "core",
    "rule_refused": "core", "schedule_changed": "core", "schedule_version": "core", "swap": "core",
    "swap_test": "core", "recall_miss": "core", "recall_approved": "core",
    "recall_file_requested": "hark_ccr", "recall_ccr_filed": "hark_ccr", "recall_hark_alert": "hark_ccr",
    "drop_ready": "drop_mark", "swap_map": "auto_swap",
    "ticket_new": "tickets", "ticket_fixed": "tickets", "ticket_error": "tickets",
}

# discovery oids that are not core (every other entity is core)
ENTITY_FEATURE = {"auto_swap": "auto_swap", "swap_map": "auto_swap", "drop_away": "drop_mark",
                  "crew_index": "crew_index", "crew_scan": "crew_index"}

# Words of lowercase letters and digits joined by single underscores, 1 to 32 characters: HA keeps no entity id with
# "__" or a trailing "_" (sensor.flight_watcher_jane__state), so "jane_", "a__b" and "_x" are refused. config.yaml
# (option pilots), cards.py and ha/check_push_isolation.py use this same pattern.
NAME_RE = re.compile(r"^(?=.{1,32}$)[a-z0-9]+(?:_[a-z0-9]+)*$")
MAX_PILOTS = 3  # pilots besides the admin: each runs its own Chromium and its own FLICA session
# A pilot's ids are <comp>.flight_watcher_<name>_<suffix> and its folders /data/<name>, /share/flight_watcher/<name>:
# a name whose first word starts one of the admin's entity ids (sensor.flight_watcher_last_check), topics, helpers,
# share folders or /data files would collide with them, so it is refused (run.py). ha/check_push_isolation.py reads
# an id whose first word is here as the admin's.
RESERVED = frozenset({
    "admin", "auto", "blocked", "captures", "ccr", "charter", "charters", "check", "crew", "default", "drop",
    "email", "er", "event", "federal", "fetches", "finds", "flica", "freq", "grid", "hunt", "improved", "last",
    "longevity", "map", "month", "new", "next", "normal", "ot", "own", "pause", "pickers", "pilot", "pot", "pref",
    "re", "rearm", "recall", "reserve", "rule", "rules", "ryan", "scan", "schedule", "session", "settings", "show",
    "state", "status", "swap", "ticket", "tickets", "trade", "tradeboard", "update", "upload", "uploads",
    "versions", "working", "would", "www",
})


def role(instance):
    """'admin' for the default instance (""), 'pilot' for any named one."""
    return PILOT if instance else ADMIN


def allowed(feature, instance):
    """True when this instance has the feature; an unknown feature is never allowed (fail closed)."""
    f = FEATURES.get(feature)
    return bool(f) and (f[0] == ALL or role(instance) == ADMIN)


def features(instance):
    """The names of every feature this instance has, in table order."""
    return [k for k in FEATURES if allowed(k, instance)]


def sub_key(sub):
    """The SUBS key for a topic after <prefix>/ ('rule/<id>/live/set' -> 'rule/+/live/set'), or None."""
    if sub in SUBS:
        return sub
    if sub.startswith("rule/") and sub.endswith("/live/set") and sub.count("/") == 3:
        return "rule/+/live/set"
    return None


def sub_allowed(sub, instance, portal=False):
    """True when this instance acts on a message on <prefix>/<sub>. An internal topic is every instance's; a topic
    SUBS does not name is left to on_message (it ignores it). 1.6.0: a PORTAL_SUBS topic only on a pilot whose portal
    is on."""
    k = sub_key(sub)
    if k is None:
        return True
    if k in PORTAL_SUBS and not (portal and role(instance) == PILOT):
        return False
    f = SUBS[k]
    return f == INTERNAL or allowed(f, instance)


def subscriptions(instance, portal=False):
    """[(sub, qos)] this instance subscribes to under its prefix, in the 1.4.12 order. portal: the pilot's portal is
    on (1.6.0: then PORTAL_SUBS follow; the admin never takes them)."""
    out = [(s, QOS.get(s, 0)) for s, f in SUBS.items()
           if s not in PORTAL_SUBS and (f == INTERNAL or allowed(f, instance))]
    if portal and role(instance) == PILOT:
        out += [(s, QOS.get(s, 0)) for s in PORTAL_SUBS if (s, QOS.get(s, 0)) not in out]
    return out


def event_allowed(name, instance):
    """True when this instance may publish <prefix>/event/<name>; an event EVENTS does not name is core."""
    return allowed(EVENTS.get(name, "core"), instance)


def entity_allowed(oid, instance):
    return allowed(ENTITY_FEATURE.get(oid, "core"), instance)


def name_refusal(name, taken=()):
    """Why a pilot name may not be used ('' when it may): the pattern, a reserved first word, a duplicate, or a name
    that starts with one already taken (or the reverse) followed by '_' (flight_watcher_jane_last_check could be
    either jane's last_check or jane_last's check)."""
    if not isinstance(name, str) or not NAME_RE.fullmatch(name):
        return "use 1 to 32 lowercase letters, digits and single underscores between words"
    if name.split("_")[0] in RESERVED:
        return f"its first word {name.split('_')[0]!r} is one of the admin's entity, topic or folder names"
    for t in taken:
        if name == t:
            return "named twice"
        if name.startswith(t + "_") or t.startswith(name + "_"):
            return f"its ids would mix with pilot {t!r}'s"
    return ""


# ---------------------------------------------------------------- 1.6.0 (FW-0061): the pilot portal, contract v1
# What a pilot's portal (HOM, a separate unprivileged process) may do through this pilot's Watcher, and nothing more:
# the command subs it may send (PORTAL_CMDS; PORTAL_REFUSED names every other subscription so a test proves each is
# refused), the events it shows and ntfy pushes (PORTAL_EVENTS, MACHINE_EVENTS) with only EVENT_FIELDS in their data,
# the pay and tax prefs it may set (PREF_KEYS), the helpers that stay view state in the portal (LOCAL_HELPERS) and the
# list files it serves (FILE_KINDS). portal.py builds the contract fixture (tests/fixtures/portal_contract_v1.json)
# from these; PORTAL_CONTRACT.md documents it. The admin has no portal: none of this runs on the default instance.
CONTRACT = 1
PORTAL_CMDS = ("hunt/set", "pause/set", "rearm/press", "check_now/press", "charter_scan/press", "freq/normal_min/set",
               "freq/hunt_s/set", "rule/+/live/set", "blocked/set", "trade/set", "pilot/set", "improved/set",
               "recall/set", "recall/act", "settings/set", "pref/set")
PORTAL_RULE_ID_RE = re.compile(r"^[a-z0-9_]{1,40}$")
# the check frequency sliders (number entities; freq/normal_min/set in minutes, freq/hunt_s/set in seconds): the
# Watcher clamps a dashboard value into these, and a portal's freq/*/set must be a finite number within them
FREQ_LIMITS = {"normal_min": (1, 20), "hunt_s": (5, 90)}
# 1.6.2 (Release A, Ryan 2026-11-10): a pilot instance hunts no faster than every 120 s (and checks no faster than every
# 2 min in normal mode, so normal is never quicker than the hunt floor); the admin keeps FREQ_LIMITS. These are the
# pilot's slider ranges and the clamp of his freq/*/set. The portal contract keeps FREQ_LIMITS (contract 1 is
# unchanged): a portal value in it below the pilot's floor is accepted there and raised to the floor by the Watcher.
PILOT_FREQ_LIMITS = {"normal_min": (2, 20), "hunt_s": (120, 300)}


def freq_limits(instance):
    """The check frequency ranges of an instance: FREQ_LIMITS for the admin, PILOT_FREQ_LIMITS for a pilot."""
    return PILOT_FREQ_LIMITS if role(instance) == PILOT else FREQ_LIMITS
PORTAL_REFUSED = ("email/alert", "crew_scan/press", "ticket/new", "ticket/image", "ticket/act", "ticket/edit",
                  "ticket/delete", "upload/chunk", "drop/set", "auto_swap/set", "swap_map/press", "hunt/state",
                  "pause/state")
# the tabs of the portal (portal_layout.json), and the one each event opens (ntfy Click, the events list)
PORTAL_TABS = ("watcher", "schedule", "pilot", "recall", "settings")
PORTAL_EVENTS = ("new_pairing", "rule_match", "recall_miss", "request_decided", "schedule_changed", "charter",
                 "hidden")
MACHINE_EVENTS = ("needs_settings", "stopped_*")  # sensor.<prefix>_state turning to one of these (stopped_ any)
EVENT_VIEWS = {"new_pairing": "watcher", "rule_match": "watcher", "recall_miss": "recall",
               "request_decided": "schedule", "schedule_changed": "schedule", "charter": "watcher",
               "hidden": "watcher", "needs_settings": "settings", "stopped_*": "watcher"}
# the only fields an event's data (events.json) carries; the title and body are built from these alone, so no name,
# employee number, captain, contact, URL, commute reason or pay amount (value, pay) ever leaves the Watcher in one
EVENT_FIELDS = ("pairing", "dates", "start", "end", "days", "month", "date", "layover", "report", "release",
                "credit", "block", "fit", "far", "vac", "comm", "month_rule", "verdict", "type", "status", "added",
                "removed", "flight", "route", "rule_id", "state")
# the pay and tax helpers the portal sets with pref/set (feature prefs); the Watcher keeps them in <data>/prefs.json
# and shows them as these entities. Bounds: the schedule card's own pickers (federal 0 to 45 % by 0.5, state 0 to
# 15 % by 0.25), the longevity year 1 to 12 (PWA 3.B.1, 3.D.6 table caps at 12), the Extended Range list the schedule
# card writes (PWA 4.O.1.b: +TRIP|YYYY-MM-DD forces it on, -TRIP|YYYY-MM-DD off; HA's 255-character text cap)
PREF_KEYS = {
    "federal_tax_pct": {"entity": "input_number.{prefix}_federal_tax_pct", "type": "number", "min": 0, "max": 45,
                        "step": 0.5, "unit": "%"},
    "state_tax_pct": {"entity": "input_number.{prefix}_state_tax_pct", "type": "number", "min": 0, "max": 15,
                      "step": 0.25, "unit": "%"},
    "longevity_year": {"entity": "input_number.{prefix}_longevity_year", "type": "number", "min": 1, "max": 12,
                       "step": 1, "unit": ""},
    "er_trips": {"entity": "input_text.{prefix}_er_trips", "type": "text", "max_len": 255,
                 "item_re": r"[+-][A-Z0-9]{1,8}\|\d{4}-\d{2}-\d{2}"},
}
# helpers the cards read and set that stay in the portal's page (never sent to the Watcher)
LOCAL_HELPERS = {"month_offset": {"entity": "input_number.{prefix}_month_offset",
                                  "services": ["set_value", "increment", "decrement"]}}
# the list files a portal serves: kind -> its argument's pattern ("" = none). finds_<YYYY-MM>, the shared
# pairings_<YYYY-MM> package, school_<YYYY-YY> and FW-0060 / FW-0069's list files (tickets are not in contract 1)
FILE_KINDS = {"finds": r"\d{4}-\d{2}", "pairings": r"\d{4}-\d{2}", "school": r"\d{4}-\d{2}", "versions": "",
              "pickers": "", "recall": "", "pilotver": ""}


def portal_sub(sub):
    """The PORTAL_CMDS entry a portal command's sub falls under ('rule/<id>/live/set' -> 'rule/+/live/set' for an id
    of PORTAL_RULE_ID_RE), or None: refused."""
    if not isinstance(sub, str):
        return None
    if sub in PORTAL_CMDS and sub != "rule/+/live/set":
        return sub
    p = sub.split("/")
    if len(p) == 4 and p[0] == "rule" and p[2:] == ["live", "set"] and PORTAL_RULE_ID_RE.fullmatch(p[1]):
        return "rule/+/live/set"
    return None


def machine_event(state):
    """The MACHINE_EVENTS kind a Watcher state is ('needs_settings', 'stopped_*'), or ''."""
    if state == "needs_settings":
        return "needs_settings"
    return "stopped_*" if isinstance(state, str) and state.startswith("stopped_") else ""


def pref_entity(key, prefix):
    return PREF_KEYS[key]["entity"].format(prefix=prefix)


def pref_value(key, value):
    """The value pref/set may store for key (PREF_KEYS), normalized (a number on its step, an int when whole; the ER
    list as given); ValueError saying why when it is refused."""
    spec = PREF_KEYS.get(key) if isinstance(key, str) else None
    if spec is None:
        raise ValueError("unknown pref key")
    if spec["type"] == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            raise ValueError(f"{key}: not a number")
        try:
            v = float(value)  # a JSON integer too large for a float is OverflowError, not ValueError
        except (ValueError, OverflowError, TypeError):
            raise ValueError(f"{key}: not a number") from None
        if not math.isfinite(v) or not spec["min"] <= v <= spec["max"]:
            raise ValueError(f"{key}: outside {spec['min']} to {spec['max']}")
        steps = (v - spec["min"]) / spec["step"]
        if abs(steps - round(steps)) > 1e-9:
            raise ValueError(f"{key}: not a multiple of {spec['step']}")
        v = round(spec["min"] + round(steps) * spec["step"], 4)
        return int(v) if float(v).is_integer() else v
    if not isinstance(value, str) or len(value) > spec["max_len"]:
        raise ValueError(f"{key}: not text of at most {spec['max_len']} characters")
    items = value.split(",") if value else []
    if any(not re.fullmatch(spec["item_re"], x) for x in items):
        raise ValueError(f"{key}: each item is +TRIP|YYYY-MM-DD or -TRIP|YYYY-MM-DD")
    return value


# discovery oids a pilot has whose feature its portal does not offer (contract 1 has no tickets or uploads)
ENTITY_PORTAL_FEATURE = {"tickets": "tickets", "uploads": "uploads", "upload_status": "uploads"}


def entity_on_portal(oid, instance):
    """True when a portal serves this discovery entity of instance: the instance has its feature and FEATURES offers
    that feature on a portal."""
    f = ENTITY_FEATURE.get(oid) or ENTITY_PORTAL_FEATURE.get(oid, "core")
    return allowed(f, instance) and FEATURES[f][1]
