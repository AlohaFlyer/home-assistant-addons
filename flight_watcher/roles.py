"""Flight Watcher pilots and roles (1.5.0, FW-0063): what each Watcher instance may do.

The default instance (prefix flight_watcher, /data, Ryan's) is the only admin. Every other instance (option `pilots`,
or the older `second_pilot`) is a pilot. The role comes from the instance, never from an option, so it cannot disagree
with what is already hard-wired to the default instance: its prefix and /data, the add-on Configuration tab, Hark's
CCR folder and the duties that need one writer.

One table, FEATURES, says who has each feature and whether a pilot's portal (1.6.0) may offer it; README.md carries
the same table (tests/test_roles.py keeps them equal). SUBS maps every MQTT command topic an instance subscribes to
onto a feature, EVENTS every event topic, and ENTITY_FEATURE the discovery entities that are not core. Plain Python,
no imports from the app, so ha/check_push_isolation.py can read RESERVED too.
"""
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
}
QOS = {"upload/chunk": 1}  # FW-0066: chunks at qos 1; every other subscription at qos 0
PORTAL_SUBS = ()  # subscriptions taken only when the pilot's portal is on: none in 1.5.0 (1.6.0 adds pref/set)

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
    "longevity", "map", "month", "new", "next", "normal", "ot", "own", "pause", "pickers", "pilot", "pot", "re",
    "rearm", "recall", "reserve", "rule", "rules", "ryan", "scan", "schedule", "session", "settings", "show",
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


def sub_allowed(sub, instance):
    """True when this instance acts on a message on <prefix>/<sub>. An internal topic is every instance's; a topic
    SUBS does not name is left to on_message (it ignores it)."""
    k = sub_key(sub)
    if k is None:
        return True
    f = SUBS[k]
    return f == INTERNAL or allowed(f, instance)


def subscriptions(instance, portal=False):
    """[(sub, qos)] this instance subscribes to under its prefix, in the 1.4.12 order. portal: the pilot's portal is
    on (no subscription depends on it in 1.5.0)."""
    out = [(s, QOS.get(s, 0)) for s, f in SUBS.items() if f == INTERNAL or allowed(f, instance)]
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
