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

1.7.0 (Release C): contract 1 revision 2 adds tickets on the portal: the five ticket subs with their shape rules
(TICKET_CMDS, data the HOM portal checks with one generic checker), the actions a pilot may take on his own tickets
(PILOT_TICKET_ACTIONS), his quotas (PILOT_TICKET_LIMITS), the tickets list file, the Tickets tab and the Watcher's own
ticket_fixed event (OWN_EVENTS). Additive: fwp and contract stay 1.

1.7.2: contract 1 revision 3 (council Nov 11, Ryan's decisions): two pilot alerts (bid_calendar from his own bid calendar
publish, schedule_unread after 6 h without a good schedule read), the pilot/set shape (SHAPE_CMDS), recall/set off the
portal (a pilot's recall lists come only from the admin's forward), and a pilot's upload of the monthly pairings package
or award (upload/pdf, PILOT_UPLOAD_LIMITS; FW-0066) with the admin's Approve, Remove and Reject (upload/decide, never on
a portal). Additive again: fwp and contract stay 1.

1.7.9: contract 1 revision 4 (Ryan's Nov 14 decisions): his pilot database shared with a pilot by his own switch (the
feature pilotdb, the file kind pilotdb, the commands pilotdb/note and pilotdb/edit with their shapes, limits and fixed
answers, the synthesized pilotdb state with the looked-up pilot's phones and emails), the swap alert for a new swap idea
(F#107) and the AI note hand-off with HOM's consultant models (PILOTDB_AI). Additive: fwp and contract stay 1.

1.7.10 (Ryan's Nov 15 decisions), still contract 1 revision 4: the shared pilot reads two more keys, union_id (his
union id edit was blind) and ai_note (read only, labeled as an AI note, only while Ryan's AI switch is on), on the
records of his pilotdb file and on the looked-up pilot's brief. Two boundary changes, both additive reads: PORTAL_CMDS,
PORTAL_REFUSED, FEATURES, every limit, the noted-pilots-only file and the anti-walk rule are as in 1.7.9.

1.7.10, Ryan's decisions 1 to 4 of Nov 15 ("The pilot database should be shared with James 100%; we work on a shared
system; we do have our own schedules and pay rates though"), still contract 1 revision 4: the pilotdb file holds
EVERY live record with every field (the employee number, phones and emails too), the notes, the whole log (there is
no "Only me" entry any more), each picker's pickup history and the AI note; sharing is on by default for every portal
pilot and the AI notes are on by default (Ryan's card keeps an OFF switch for each, stored in the Watcher's own
switches file, never in the database); a contact list or an award a pilot's instance saves merges into the one
database like Ryan's, with that pilot as its author. The noted-pilots-only file, phones and emails only for the
looked-up pilot, the roster and its anti-walk rule and the 20-an-hour brief cap are gone (they only limited what a
shared pilot saw of the database). PORTAL_CMDS, PORTAL_REFUSED, every command shape, every limit and quota of a
shared pilot's writes, the upload kinds, and every FLICA budget, pacing and read limit are as in 1.7.9.

1.7.10, contract 1 REVISION 5 (Ryan, Nov 16: "His uploads should update the shared database too", and the contacts
list upload on a pilot's portal "Now, in 1.7.10"): upload/pdf takes a third kind, contacts: the airline contacts list
as its CSV export (PILOT_CONTACTS_LIMITS: 1 MiB, the header row). The pilot's Watcher checks the whole file and hands
it to the admin's Watcher through his pilotdb inbox folder (the author is the folder's name, never a payload key); the
admin's Watcher checks it again and merges it into the one database with that pilot as the author. A pilot's list
only adds and updates (pilotdb.merge_contacts, additive). The command's shape changed (one more value of kind), so
HOM 1.9.1 goes live first; HOM 1.9.0 refuses kind contacts with its own shape check and serves everything else as it
did. PORTAL_CMDS, PORTAL_REFUSED, FEATURES and every other shape, limit and quota are as in revision 4.

1.7.11, contract 1 REVISION 6 (Ryan's yes of Nov 17, FW-0076: "This month and next month buttons on the pilot lookup,
on both instances. One FLICA load per tap, inside the budget."): pilot/set takes one more key, month (YYYY-MM,
MONTH_PATTERN). The command is revision 1's; the key is revision 6's (KEY_SINCE, the way revision 5 marked a value in
VALUE_SINCE), so HOM 1.9.2 takes a pilot/set with month only for a Watcher whose manifest names revision 6, and HOM
1.9.1's pinned shape refuses the key. The Watcher takes only this HST month or the next (watcher.lookup_months). FW-0078
(the same release): the pick list shows each pilot's base and employee number; no shape or mask changed for it.
PORTAL_CMDS, PORTAL_REFUSED, FEATURES and every other shape, limit and quota are as in revision 5.
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
                                 "file sweep of other folders, and the pilot database (pilotdb: imports, hand edits, "
                                 "notes, the ingress API, seniority.md, backups)"),
    "web_ui": (ADMIN, False, "the ingress Web UI (run.py starts it for the default instance only)"),
    "addon_config": (ADMIN, False, "the FLICA and CrewTrac logins from the add-on Configuration tab"),
    "drop_mark": (ADMIN, False, "would drop marks (drop/set), the drop scan, event/drop_ready, sensor would_drop"),
    "auto_swap": (ADMIN, False, "the auto swap dry run switch (auto_swap/set) and the swap page mapping "
                                "(swap_map/press)"),
    "paycheck": (ADMIN, False, "the paycheck check card on Ryan's dashboard (no Watcher code)"),
    "admin_pushes": (ADMIN, False, "FLICA alert emails HA forwards (email/alert) and the email check"),
    "tickets": (ALL, True, "tickets (ticket/new, image, act, edit, delete); a pilot sees and acts on his own, on HA or "
                           "his portal"),
    "uploads": (ALL, False, "uploads in chunks (upload/chunk) and the uploads sensors"),
    "pilot_uploads": (ALL, True, "a pilot's upload of the monthly pairings package or award from his portal "
                                 "(upload/pdf), checked by his own Watcher; used at once when nothing is on file, else "
                                 "held for the admin; and of the contacts list (CSV) into the shared pilot database, "
                                 "while it is shared with him"),
    "upload_review": (ADMIN, False, "the admin's Approve, Remove and Reject of a pilot's upload (upload/decide) and its "
                                    "push (event/pilot_upload)"),
    # 1.7.9 (contract 1 revision 4, B14). 1.7.10 (Ryan, Nov 15): shared 100% with every portal pilot, on by default;
    # Ryan's card keeps an OFF switch per pilot (while it is off there is no file, the sensor says off and every
    # command is refused)
    "pilotdb": (ALL, True, "the pilot database shared with a portal pilot (on by default; Ryan can turn it off): the "
                           "pilotdb file (every live record with every field, the notes, the log, the pickup history "
                           "and the AI note), the synthesized pilotdb sensor (which record the pilot card's pilot "
                           "is), pilotdb/note (notes field and log) and pilotdb/edit (record fields), each applied by "
                           "the admin's Watcher"),
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
    "layover/note": "one_writer",  # 1.7.1 (FW-0072): the admin's layover notes (one writer of the shared folder)
    "pref/set": "prefs",  # 1.6.0 (FW-0061): portal only (PORTAL_SUBS), never on the admin
    "upload/decide": "upload_review",  # 1.7.2 (FW-0066): the admin's Approve / Remove / Reject of a pilot's upload
    "upload/pdf": "pilot_uploads",  # 1.7.2 (FW-0066): portal only (PORTAL_SUBS), a pilot's upload in chunks
    # 1.7.2 (Ryan, Nov 12): the van alerts' switch and lead times, the admin's (a pilot has no van alerts)
    "van/alerts/set": "admin_pushes", "van/first_min/set": "admin_pushes", "van/second_min/set": "admin_pushes",
    "van/adjust/set": "admin_pushes",  # 1.7.11 (FW-0075): Ryan moves the van in hand in 5 minute steps (layover card)
    # 1.7.9 (revision 4): portal only (PORTAL_SUBS), a shared pilot's note and field edit; his Watcher only checks them
    # and hands them to the admin's inbox (the admin never subscribes: it reads the inbox folder)
    "pilotdb/note": "pilotdb", "pilotdb/edit": "pilotdb",
}
# FW-0066: chunks at qos 1; 1.7.9: a note or an edit too (its text is typed once); every other subscription at qos 0
QOS = {"upload/chunk": 1, "upload/pdf": 1, "pilotdb/note": 1, "pilotdb/edit": 1}
# 1.6.0 (FW-0061): subscriptions taken only on a pilot instance whose portal is on (option pilots[].portal); the
# admin never takes them, so its list stays the 1.4.12 one. 1.7.2: upload/pdf too (a pilot uploads from his portal only)
PORTAL_SUBS = ("pref/set", "upload/pdf", "pilotdb/note", "pilotdb/edit")

# every event topic (after <prefix>/event/) and its feature
EVENTS = {
    "new_pairing": "core", "hidden": "core", "charter": "core", "request_decided": "core", "rule_match": "core",
    "rule_refused": "core", "schedule_changed": "core", "schedule_version": "core", "swap": "core",
    "swap_test": "core", "recall_miss": "core", "recall_approved": "core",
    "recall_file_requested": "hark_ccr", "recall_ccr_filed": "hark_ccr", "recall_hark_alert": "hark_ccr",
    "drop_ready": "drop_mark", "swap_map": "auto_swap",
    "ticket_new": "tickets", "ticket_fixed": "tickets", "ticket_error": "tickets",
    "bid_calendar": "core",  # 1.7.1 (FW-0070): every instance; only the admin's prefix has an HA push
    "van": "admin_pushes",  # 1.7.1 (FW-0072): van alerts from Hark's working flight, the admin only
    "pilot_upload": "upload_review",  # 1.7.2 (FW-0066): a pilot's upload for the admin's push (Approve / Remove / Reject)
}

# discovery oids that are not core (every other entity is core)
ENTITY_FEATURE = {"auto_swap": "auto_swap", "swap_map": "auto_swap", "drop_away": "drop_mark",
                  "crew_index": "crew_index", "crew_scan": "crew_index",
                  "layover_van": "admin_pushes", "layover_notes": "one_writer",  # 1.7.1 (FW-0072)
                  # 1.7.2 (Ryan, Nov 12): the van alerts' switch and sliders
                  "van_alerts": "admin_pushes", "van_alert_first": "admin_pushes", "van_alert_second": "admin_pushes",
                  "pilotdb": "one_writer"}  # 1.7.8 (B5): sensor.flight_watcher_pilotdb, the pilot database's counts

# Words of lowercase letters and digits joined by single underscores, 1 to 32 characters: HA keeps no entity id with
# "__" or a trailing "_" (sensor.flight_watcher_jane__state), so "jane_", "a__b" and "_x" are refused. config.yaml
# (option pilots), cards.py and ha/check_push_isolation.py use this same pattern.
NAME_RE = re.compile(r"^(?=.{1,32}$)[a-z0-9]+(?:_[a-z0-9]+)*$")
MAX_PILOTS = 3  # pilots besides the admin: each runs its own Chromium and its own FLICA session
# A pilot's ids are <comp>.flight_watcher_<name>_<suffix> and its folders /data/<name>, /share/flight_watcher/<name>:
# a name whose first word starts one of the admin's entity ids (sensor.flight_watcher_last_check), topics, helpers,
# share folders or /data files would collide with them, so it is refused (run.py). ha/check_push_isolation.py reads
# an id whose first word is here as the admin's. 1.7.2: "ready" (automation.flight_watcher_ready_to_update_ask_hark,
# the Working Flight button that asks Hark, Ryan Nov 12) and "van" (switch.flight_watcher_van_alerts and
# number.flight_watcher_van_alert_first and _second, the van alert settings, Ryan Nov 12). 1.7.8: "pilotdb" (the pilot
# database: /data/pilotdb_backup, /share/flight_watcher/pilotdb, sensor.flight_watcher_pilotdb and its topic). 1.7.14:
# "near" (sensor.flight_watcher_near_misses and its topic near/state, the near misses in the open time pot).
RESERVED = frozenset({
    "admin", "auto", "bid", "blocked", "captures", "ccr", "charter", "charters", "check", "crew", "default", "drop",
    "email", "er", "event", "federal", "fetches", "finds", "flica", "freq", "grid", "hunt", "improved", "last",
    "layover", "layovers", "longevity", "map", "month", "near", "new", "next", "normal", "ot", "own", "pause", "pickers",
    "pilot", "pilotdb", "pot", "pref", "re", "rearm", "ready", "recall", "reserve", "rule", "rules", "ryan", "scan", "schedule", "session",
    "settings", "show",
    "state", "status", "swap", "ticket", "tickets", "trade", "tradeboard", "update", "upload", "uploads", "van",
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
# 1.7.0 (Release C): tickets (2); 1.7.2: pilot alerts, shapes, uploads (3); 1.7.9: the shared pilot database, the swap
# idea alert (4); 1.7.10: a pilot's contacts list upload, kind contacts on upload/pdf (5); 1.7.11: the pilot lookup's
# month, the key month on pilot/set (6); additive within 1
CONTRACT_REVISION = 6
# 1.7.2 (revision 3): recall/set leaves the list (F#78: a crafted paste from the portal could replace or blank a day on
# the pilot's own instance; his lists come only from the admin's forward, 1.7.1) and upload/pdf joins it (FW-0066)
PORTAL_CMDS = ("hunt/set", "pause/set", "rearm/press", "check_now/press", "charter_scan/press", "freq/normal_min/set",
               "freq/hunt_s/set", "rule/+/live/set", "blocked/set", "trade/set", "pilot/set", "improved/set",
               "recall/act", "settings/set", "pref/set", "ticket/new", "ticket/image", "ticket/act",
               "ticket/edit", "ticket/delete", "upload/pdf", "pilotdb/note", "pilotdb/edit")
# the revision each portal command came in (HOM refuses a newer command to a Watcher that names an older revision in its
# manifest, with a plain message; a manifest with no revision is revision 2 or older) and the one it left in
COMMAND_SINCE = {"ticket/new": 2, "ticket/image": 2, "ticket/act": 2, "ticket/edit": 2, "ticket/delete": 2,
                 "upload/pdf": 3, "pilotdb/note": 4, "pilotdb/edit": 4}
COMMAND_REMOVED = {"recall/set": 3}
# 1.7.10 (revision 5): the revision one VALUE of a command's field came in, when the command itself is older:
# {sub: {field: {value: revision}}}. HOM refuses such a value to a Watcher whose manifest names an older revision
# (it would refuse the chunk itself), as it does a whole command by COMMAND_SINCE.
VALUE_SINCE = {"upload/pdf": {"kind": {"contacts": 5}}}
# 1.7.11 (revision 6, FW-0076): the revision one KEY of a command came in, when the command itself is older:
# {sub: {key: revision}}. HOM refuses a payload with such a key to a Watcher whose manifest names an older revision (an
# older Watcher's own shape check would refuse it), as it does a value by VALUE_SINCE and a command by COMMAND_SINCE.
KEY_SINCE = {"pilot/set": {"month": 6}}
PORTAL_RULE_ID_RE = re.compile(r"^[a-z0-9_]{1,40}$")
# contract 1's check frequency ranges (freq/normal_min/set in minutes, freq/hunt_s/set in seconds): a portal's
# freq/*/set must be a finite number within them (portal.check_freq). Contract 1 is pinned (its fixture and sha256).
# Revision 2 (1.7.0, Release C) brings normal up to 90 min, Ryan's Nov 10 range on every instance (1 to 20 before); in
# the HOM-first order a 1.6.x Watcher still refuses over 20 with its own copy and its slider stops at 20.
FREQ_LIMITS = {"normal_min": (1, 90), "hunt_s": (5, 90)}
# 1.6.2 (Ryan 2026-11-10, replacing the pilot's 120 s hunt floor): every instance, the admin and each pilot, hunts every
# 5 to 90 s and checks every 1 to 90 min in normal mode. These are the number entities' ranges and the Watcher's clamp
# of freq/*/set and of a stored value. A pilot's FLICA budget (gate.PILOT_BUDGET_H, 100 loads an hour), the host's cap
# (480 an hour) and the 1.5 s host gap stay: a pilot's hunt faster than his budget keeps up (about one check every
# 1.5 min, watcher.budget_pace_s) runs at that pace, and the state note says so.
WATCHER_FREQ_LIMITS = {"normal_min": (1, 90), "hunt_s": (5, 90)}


def freq_limits(instance):
    """The check frequency ranges of an instance: WATCHER_FREQ_LIMITS on every instance since 1.6.2 (Ryan 2026-11-10;
    a pilot had 120 to 300 s before)."""
    return WATCHER_FREQ_LIMITS


def entity_freq_limits(instance, portal=False):
    """The ranges the number entities advertise: the instance's (freq_limits) and, on a pilot whose portal is on, kept
    within contract 1's FREQ_LIMITS, so his portal offers only what it can send (revision 2: the same 1 to 90 min and 5
    to 90 s; normal stopped at 20 min on the portal before Release C)."""
    own = freq_limits(instance)
    if not (portal and role(instance) == PILOT):
        return own
    return {k: (max(lo, FREQ_LIMITS[k][0]), min(hi, FREQ_LIMITS[k][1])) for k, (lo, hi) in own.items()}


PORTAL_REFUSED = ("email/alert", "crew_scan/press", "upload/chunk", "drop/set", "auto_swap/set", "swap_map/press",
                  "hunt/state", "pause/state", "recall/set", "layover/note", "upload/decide")
# 1.7.1 (FW-0072): subs added after a contract revision that a portal never offers, refused as "anything else" until a
# later revision names them in PORTAL_REFUSED (1.7.2, revision 3: layover/note is named there now). 1.7.2 (after
# revision 3, Ryan Nov 12): the admin's van alert settings (the spool refuses anything not in PORTAL_CMDS). 1.7.11
# (FW-0075): the admin's van move, never a portal's (no contract change)
NOT_ON_PORTAL = ("van/alerts/set", "van/first_min/set", "van/second_min/set", "van/adjust/set")
# the tabs of the portal (portal_layout.json), and the one each event opens (ntfy Click, the events list); 1.7.0: the
# Tickets tab last, so the five tabs before it keep their places in the tab bar
PORTAL_TABS = ("watcher", "schedule", "pilot", "recall", "settings", "tickets")
PORTAL_EVENTS = ("new_pairing", "rule_match", "recall_miss", "request_decided", "schedule_changed", "charter",
                 "hidden", "bid_calendar",  # 1.7.2 (revision 3): bid_calendar, the pilot's own (FW-0070)
                 # 1.7.9 (revision 4, F#107): a new swap idea for a trip the pilot marked "would trade" (trade/set, his
                 # opt-in: no mark, no idea, no alert); the pot card on the Watcher tab lists the ideas
                 "swap")
MACHINE_EVENTS = ("needs_settings", "stopped_*")  # sensor.<prefix>_state turning to one of these (stopped_ any)
# 1.7.0 (Release C): events the Watcher makes from its own files, never from an MQTT event topic (so a publish can never
# become one): ticket_fixed, from a move into fixed in the pilot's own tickets (tickets.fixed_moves)
# 1.7.2 (revision 3): schedule_unread, from the Watcher's own schedule read times (after SCHEDULE_UNREAD_H without a
# good FLICA schedule read, at most once an HST day)
OWN_EVENTS = ("ticket_fixed", "schedule_unread")
EVENT_VIEWS = {"new_pairing": "watcher", "rule_match": "watcher", "recall_miss": "recall",
               "request_decided": "schedule", "schedule_changed": "schedule", "charter": "watcher",
               "hidden": "watcher", "needs_settings": "settings", "stopped_*": "watcher", "ticket_fixed": "tickets",
               "bid_calendar": "watcher", "schedule_unread": "schedule", "swap": "watcher"}
SCHEDULE_UNREAD_H = 6
# the only fields an event's data (events.json) carries; the title and body are built from these alone, so no name,
# employee number, captain, contact, URL, commute reason or pay amount (value, pay) ever leaves the Watcher in one.
# 1.7.0: ticket (a ticket id, or a list of them) and version (the release that fixed it); never a ticket's title or text
EVENT_FIELDS = ("pairing", "dates", "start", "end", "days", "month", "date", "layover", "report", "release",
                "credit", "block", "fit", "far", "vac", "comm", "month_rule", "verdict", "type", "status", "added",
                "removed", "flight", "route", "rule_id", "state", "ticket", "version")
# 1.7.2 (revision 3): fields one event kind carries besides EVENT_FIELDS (event_data adds them for that kind only, so
# another kind's payload never brings them along): the bid calendar alert's own keys (the same as the admin's push:
# its month, which alert, the event's and the send's HST time, where the date came from) and the hours a schedule went
# unread. Never a title or a message: the text is built from these (portal.event_text renders the bid calendar's words
# with bidcal.render, as the admin's push has them).
EVENT_KIND_FIELDS = {"bid_calendar": ("bid_month", "alert", "event_hst", "at_hst", "source", "cycle_source"),
                     "schedule_unread": ("hours",),
                     # 1.7.9 (revision 4, F#107): the trip he would give up, the gains as the pot card words them and
                     # where the pickup is (O open time, T Tradeboard); never the idea's reason text, a URL or a draft
                     "swap": ("for_trip", "for_date", "soft_gain", "credit_gain", "src")}
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
                 "item_re": r"[+-][A-Z0-9]{1,8}\|[0-9]{4}-[0-9]{2}-[0-9]{2}"},  # 1.7.0 review: ASCII digits
}
# helpers the cards read and set that stay in the portal's page (never sent to the Watcher)
LOCAL_HELPERS = {"month_offset": {"entity": "input_number.{prefix}_month_offset",
                                  "services": ["set_value", "increment", "decrement"]}}
# the list files a portal serves: kind -> its argument's pattern ("" = none). finds_<YYYY-MM>, the shared
# pairings_<YYYY-MM> package, school_<YYYY-YY> and FW-0060 / FW-0069's list files; 1.7.0 (contract 1 revision 2): the
# pilot's own tickets list (tickets.listing for his name only)
FILE_KINDS = {"finds": r"\d{4}-\d{2}", "pairings": r"\d{4}-\d{2}", "school": r"\d{4}-\d{2}", "versions": "",
              "pickers": "", "recall": "", "pilotver": "", "tickets": "",
              "pilotdb": ""}  # 1.7.9 (revision 4, B12): the pilots with shared notes, only while Ryan shares


# ---------------------------------------------------------------- 1.7.0 (Release C): tickets on the portal
# A pilot files, sees and acts on his own tickets only: his Watcher is the authority (reporter is the instance, never
# the payload; tickets.listing, act, edit and delete take allowed_reporter). The portal and the spool check the shape
# below and nothing else, so they can narrow what reaches the Watcher but never widen it.
# ticket/act on a pilot: verify (closes a fixed ticket), reopen and note. triage, progress, fixed and close are for
# whoever works the ticket (the admin's instance and Claude's process-tickets flow), never a pilot.
PILOT_TICKET_ACTIONS = ("verify", "reopen", "note")
# a pilot instance's ticket quotas, kept by his Watcher whatever sent the command (portal or a dashboard card); the
# admin has none. new_per_day: tickets filed in the last 24 h (deleted ones count); open: open at once; photos: a
# ticket; ticket_bytes: one ticket as stored, its photos (after the Watcher re-encodes them) and its ticket.json
# together (1.5 MB, the council's total); in_flight: photo uploads being put together at once; chunk_chars and
# chunk_parts: one photo comes in at most chunk_parts ticket/image commands of at most chunk_chars base64 characters
# each (under the 64 KB command cap); photo_side_max: the longest side the Watcher re-encodes (the portal card sends at
# most 1600 px); photo_stale_s: a photo whose next chunk does not come within this time is dropped.
# 1.7.0 review: his notes, reopens, verifies and edits are capped as well (each rewrites ticket.json in the folder both
# instances share): changes_per_day in 24 h over all his tickets, history of his own history lines on one ticket, and
# text_bytes of one ticket.json; a verify or a reopen with no text is never refused by these (it follows a fix by
# whoever works the ticket, so he cannot repeat one on his own).
PILOT_TICKET_LIMITS = {"new_per_day": 10, "open": 25, "photos": 3, "ticket_bytes": 1536 * 1024, "in_flight": 1,
                       "chunk_chars": 60000, "chunk_parts": 8, "photo_side_max": 2048, "photo_stale_s": 120,
                       "changes_per_day": 30, "history": 50, "text_bytes": 256 * 1024}
TICKET_ID_PATTERN = r"^FW-[0-9]{4,6}$"  # 1.7.0 review: ASCII digits (Python's \d also takes other scripts' digits)
TICKET_CID_PATTERN = r"^[A-Za-z0-9_-]{6,40}$"  # tickets.CID_RE; also a card-made rid
TICKET_DATA_PATTERN = r"^[A-Za-z0-9+/]+={0,2}$"  # one chunk: a slice of the photo's base64 (no data: prefix)
# 1.7.0 review: what ticket text may hold (BMP escapes only, so Python's re and a JavaScript RegExp with no flags read
# them the same). A one-line field (title, page, version): no control character (U+0000 to U+001F, U+007F to U+009F),
# no line or paragraph separator (U+2028, U+2029) and no bidi embedding, override or isolate (U+202A to U+202E, U+2066
# to U+2069), so ticket text never starts a line of its own in the add-on log or turns round on a card. A text field
# (narrative, steps, expected, a note): the same, but tab, line feed and carriage return are allowed.
TICKET_LINE_PATTERN = r"^[^\x00-\x1f\x7f-\x9f\u2028\u2029\u202a-\u202e\u2066-\u2069]*$"
TICKET_TEXT_PATTERN = r"^[^\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\u2028\u2029\u202a-\u202e\u2066-\u2069]*$"
# How the HOM portal and the spool read TICKET_CMDS (the same words in the fixture, commands.ticket_rules): one generic
# checker on each side, so the two cannot drift.
TICKET_RULES = (
    "The payload is the JSON text of an object (not an array, a string or null).",
    "Its keys are a subset of keys, include every key in required and, when any_of is given, at least one of any_of.",
    "Every key present is checked by its fields entry; a null value is the wrong type.",
    "text: a JSON string whose length in Unicode code points (Python len, JavaScript [...s].length) is from min to "
    "max; with pattern, the whole string matches it (Python re.fullmatch; JavaScript new RegExp(pattern) with no flags "
    "and the pattern's own ^ and $), so a trailing newline is refused.",
    "text is well-formed Unicode: no lone surrogate (Python: s.encode('utf-8') succeeds; JavaScript: "
    "s.isWellFormed()).",
    "int: a JSON number, never a boolean or a string, with a whole value from min to max; 2.0 counts as 2 (JavaScript "
    "cannot tell them apart); 2.5, true, \"2\" and 1e999 are refused.",
    "enum: a JSON string equal to one of values.",
    "le: each [a, b] means the value of a is at most the value of b.",
    "nonempty_when: each {field, is, then} means that when field equals is, then is present with at least 1 code point.",
)


_LINE, _TEXT = TICKET_LINE_PATTERN, TICKET_TEXT_PATTERN


def _text(lo, hi, pattern=None):
    d = {"type": "text", "min": lo, "max": hi}
    if pattern:
        d["pattern"] = pattern
    return d


def _int(lo, hi):
    return {"type": "int", "min": lo, "max": hi}


_PHOTOS, _PARTS = PILOT_TICKET_LIMITS["photos"], PILOT_TICKET_LIMITS["chunk_parts"]
TICKET_CMDS = {
    "ticket/new": {
        "keys": ["kind", "title", "narrative", "steps", "expected", "page", "version", "cid", "images"],
        "required": ["kind", "title", "narrative"],
        "fields": {"kind": {"type": "enum", "values": ["bug", "feature"]}, "title": _text(1, 200, _LINE),
                   "narrative": _text(1, 10000, _TEXT), "steps": _text(0, 5000, _TEXT),
                   "expected": _text(0, 5000, _TEXT), "page": _text(0, 300, _LINE), "version": _text(0, 40, _LINE),
                   "cid": _text(6, 40, TICKET_CID_PATTERN), "images": _int(0, _PHOTOS)}},
    "ticket/image": {
        "keys": ["cid", "i", "n", "part", "parts", "data"],
        "required": ["cid", "i", "n", "part", "parts", "data"],
        "fields": {"cid": _text(6, 40, TICKET_CID_PATTERN), "i": _int(1, _PHOTOS), "n": _int(1, _PHOTOS),
                   "part": _int(1, _PARTS), "parts": _int(1, _PARTS),
                   "data": _text(1, PILOT_TICKET_LIMITS["chunk_chars"], TICKET_DATA_PATTERN)},
        "le": [["i", "n"], ["part", "parts"]]},
    "ticket/act": {
        "keys": ["id", "action", "text", "rid"],
        "required": ["id", "action"],
        "fields": {"id": _text(7, 9, TICKET_ID_PATTERN), "action": {"type": "enum", "values": list(PILOT_TICKET_ACTIONS)},
                   "text": _text(0, 5000, _TEXT), "rid": _text(6, 40, TICKET_CID_PATTERN)},
        "nonempty_when": [{"field": "action", "is": "note", "then": "text"}]},
    "ticket/edit": {
        "keys": ["id", "rid", "title", "narrative", "steps", "expected", "page"],
        "required": ["id"],
        "any_of": ["title", "narrative", "steps", "expected", "page"],
        "fields": {"id": _text(7, 9, TICKET_ID_PATTERN), "rid": _text(6, 40, TICKET_CID_PATTERN),
                   "title": _text(1, 200, _LINE), "narrative": _text(1, 10000, _TEXT),
                   "steps": _text(0, 5000, _TEXT), "expected": _text(0, 5000, _TEXT), "page": _text(0, 300, _LINE)}},
    "ticket/delete": {
        "keys": ["id", "rid"],
        "required": ["id"],
        "fields": {"id": _text(7, 9, TICKET_ID_PATTERN), "rid": _text(6, 40, TICKET_CID_PATTERN)}},
}


# ---------------------------------------------------------------- 1.7.2 (revision 3): command shapes and pilot uploads
# The same rules as TICKET_CMDS (TICKET_RULES, one generic checker on each side) for two more portal commands.
# pilot/set (F#49): what the pilot lookup cards send, nothing else: an employee number (1 to 7 ASCII digits), a typed
# query or a name (at most 60 code points, one line), or a pick id (pilot.pick_id: 12 lowercase hex). The Watcher
# refuses the same (watcher.pilot_cmd, every instance), and its log line never carries the text. 1.7.11 (revision 6,
# FW-0076): and a month (YYYY-MM): the pilot card's month buttons; the Watcher takes this HST month or the next only.
# upload/pdf (FW-0066, Ryan Nov 11): one chunk of a pilot's upload of the monthly pairings package or the award (never
# the seniority list; 1.7.10, revision 5: the contacts list as its CSV export too, PILOT_CONTACTS_LIMITS below), cut like ticket photos so each
# command stays under the 64 KB cap. Every chunk carries the upload's fields; the pilot's Watcher (pilotpdf.py) puts
# one upload together at a time and checks it whole before anything is stored.
PRINTABLE_PATTERN = TICKET_LINE_PATTERN  # one line: no control character, line or paragraph separator, bidi control
PICK_PATTERN = r"^[0-9a-f]{12}$"
UPLOAD_ID_PATTERN = r"^[A-Za-z0-9_-]{16,40}$"
MONTH_PATTERN = r"^[0-9]{4}-(0[1-9]|1[0-2])$"
SHA256_PATTERN = r"^[0-9a-f]{64}$"
# a pilot's uploads, kept by his Watcher whatever sent them: kinds (pairings and award only), file_bytes (4 MB a file),
# per_day (uploads put together in 24 h, refused or not), in_flight (one at a time), chunk_chars (base64 characters a
# chunk) and chunk_parts (the most chunks a 4 MB file needs), stale_s (an upload whose next chunk does not come within
# this time is dropped), months_ahead (the month is this HST month or one of the next two), and the text extraction's
# limits (pdftotext -layout in a child process: extract_timeout_s, extract_mem_mb, extract_cpu_s), then
# min_pairings: a pairings package must hold at least this many pairings (every base and fleet), at least one of them
# an A332 HNL one, and name that month; an award must name that month and hold the pilot's own line.
PILOT_UPLOAD_LIMITS = {"kinds": ["pairings", "award"], "file_bytes": 4 * 1024 * 1024, "per_day": 4, "in_flight": 1,
                       "chunk_chars": 60000, "chunk_parts": 94, "stale_s": 120, "months_ahead": 2,
                       "extract_timeout_s": 30, "extract_mem_mb": 512, "extract_cpu_s": 30, "min_pairings": 100}
_UL = PILOT_UPLOAD_LIMITS
# 1.7.10 (revision 5; Ryan, Nov 16): a third kind on upload/pdf, the airline contacts list as its CSV export. kinds
# above stays the two PDF kinds (their checks, their quarantine and the months on file are theirs alone). A contacts
# list: file_bytes (1 MiB; the export is about 200 KB) in at most chunk_parts chunks; text only (encodings, no control
# character but tab, CR and LF) whose first row is header, cell for cell (case and outer spaces aside); rows_min
# pilots read by the 1.4.8 parser (contacts.parse); pending: one list of a pilot waits for the admin's Watcher at a
# time; per_day: lists the admin's Watcher merges for one pilot in 24 h (his own Watcher counts every upload toward
# PILOT_UPLOAD_LIMITS per_day as well); inbox_bytes: the inbox file that carries it (its base64 and its envelope).
# It carries a month like every upload/pdf chunk (this HST month); the month is checked and not used.
# Review fixes (Nov 16), each a bound on what one pilot's list can do to the one shared database: encodings (the 1.4.8
# parser's own: UTF-8, a BOM allowed, else Windows-1252, so a pilot's export is read exactly as Ryan's is); rows_max
# rows under the header (the export has about 1230); cell_chars characters a cell and notes_chars for the Notes cell
# (the last of header), and no text in a cell beyond the header's columns: so no cell can hold the parser for
# seconds; new_max: the live records a pilot's lists made that no list of Ryan's (seniority list, award, his own
# contacts list) holds, all pilots' lists together: a list that would take the database over it is refused whole and
# changes nothing.
PILOT_UPLOAD_KINDS = tuple(_UL["kinds"]) + ("contacts",)
PILOT_CONTACTS_LIMITS = {"kind": "contacts", "file_bytes": 1024 * 1024, "chunk_parts": 24, "rows_min": 1,
                         "pending": 1, "per_day": 4, "inbox_bytes": 1536 * 1024,
                         "encodings": ["utf-8", "cp1252"], "rows_max": 2500, "cell_chars": 200, "notes_chars": 2000,
                         "new_max": 250,
                         "header": ["First Name", "Middle Name", "Last Name", "Suffix", "Company", "Job Title",
                                    "Mobile Phone", "Email", "Employee ID", "Notes"]}
SHAPE_CMDS = {
    "pilot/set": {
        "keys": ["emp", "q", "name", "pick", "month"],
        "required": [],
        "any_of": ["emp", "q", "pick"],
        "fields": {"emp": _text(1, 7, r"^[0-9]{1,7}$"), "q": _text(1, 60, PRINTABLE_PATTERN),
                   "name": _text(0, 60, PRINTABLE_PATTERN), "pick": _text(12, 12, PICK_PATTERN),
                   "month": _text(7, 7, MONTH_PATTERN)}},  # 1.7.11 (revision 6): KEY_SINCE
    "upload/pdf": {
        "keys": ["uid", "kind", "month", "size", "sha", "part", "parts", "data"],
        "required": ["uid", "kind", "month", "size", "sha", "part", "parts", "data"],
        "fields": {"uid": _text(16, 40, UPLOAD_ID_PATTERN), "kind": {"type": "enum", "values": list(PILOT_UPLOAD_KINDS)},
                   "month": _text(7, 7, MONTH_PATTERN), "size": _int(1, _UL["file_bytes"]),
                   "sha": _text(64, 64, SHA256_PATTERN), "part": _int(1, _UL["chunk_parts"]),
                   "parts": _int(1, _UL["chunk_parts"]),
                   "data": _text(1, _UL["chunk_chars"], TICKET_DATA_PATTERN)},
        "le": [["part", "parts"]]},
}


# ---------------------------------------------------------------- 1.7.9 (revision 4): the shared pilot database
# Ryan's pilot database (pilotdb.py, the admin's Watcher, one writer) shared with a portal pilot (1.7.9: by Ryan's own
# switch, off by default; 1.7.10, Ryan's decisions of Nov 15: 100% of it, on by default, with an OFF switch on his card).
# The pilot's Watcher never opens the database: it checks a command and drops it into the admin's inbox folder; the
# admin applies it, with the author taken from the instance (the inbox folder's name), never from the payload.
# pilotdb/note: the notes field (op field: compare-and-set on base, the rev it was read at) and the notes log (add,
# retract of his own entry). pilotdb/edit (Ryan, Nov 14: "he can be trusted and edit all"): one record field, set or
# unset (back to the uploads' value), compare-and-set on rev (the record's rev it was read at); every earlier value
# stays in the record's log and Ryan can put any back. value is text: phones a JSON list of {label, number} (at most
# 4), emails a JSON list of addresses (at most 3), every other field as Ryan's card types it; the admin's Watcher runs
# the same checks as on Ryan's own edit (pilotdb.check). No author key, no employee number and no name in either.
PILOTDB_PID_PATTERN = r"^p[0-9a-f]{10}$"
PILOTDB_ENTRY_PATTERN = r"^n[0-9a-f]{10}$"
PILOTDB_REV_PATTERN = r"^[0-9a-f]{12}$"
PILOTDB_NOTE_OPS = ("add", "retract", "field")
PILOTDB_EDIT_OPS = ("set", "unset")
PILOTDB_EDIT_FIELDS = ("name", "sen", "doh", "status", "retire", "seat", "equip", "phones", "emails", "union_id")
# A shared pilot's limits, kept by the admin's Watcher (Ryan has the size limits only): entry_max and field_max in
# code points; adds_per_day entries, changes_per_day notes field saves plus retracts and edits_per_day field edits in
# 24 h; entries_per_record on one record, all authors; pending inbox files waiting per pilot; stale_h: an older inbox
# file is refused; answers kept per pilot; export_entries newest entries per record in his file (export_entries_min
# when the file is over export_bytes; 1.7.10: his file holds every record and never passes pilotdb.EXPORT_HARD, 7 MiB,
# under the 8 MiB a signed file may be); value_max: a field edit's value; why_max: its reason line.
PILOTDB_NOTE_LIMITS = {"entry_max": 2000, "field_max": 4000, "adds_per_day": 40, "changes_per_day": 40,
                       "edits_per_day": 40, "entries_per_record": 500, "pending": 10, "stale_h": 24, "answers": 20,
                       "export_entries": 50, "export_entries_min": 20, "export_bytes": 4 * 1024 * 1024,
                       "value_max": 1000, "why_max": 200}
_PL = PILOTDB_NOTE_LIMITS
SHAPE_CMDS.update({
    "pilotdb/note": {
        "keys": ["op", "pid", "entry", "base", "text", "rid"],
        "required": ["op", "pid", "rid"],
        "fields": {"op": {"type": "enum", "values": list(PILOTDB_NOTE_OPS)},
                   "pid": _text(11, 11, PILOTDB_PID_PATTERN),
                   "entry": _text(11, 11, PILOTDB_ENTRY_PATTERN),
                   "base": _text(12, 12, PILOTDB_REV_PATTERN),
                   "text": _text(0, _PL["field_max"], _TEXT),
                   "rid": _text(6, 40, TICKET_CID_PATTERN)},
        "nonempty_when": [{"field": "op", "is": "add", "then": "text"},
                          {"field": "op", "is": "retract", "then": "entry"},
                          {"field": "op", "is": "field", "then": "base"}]},
    "pilotdb/edit": {
        "keys": ["op", "pid", "field", "value", "rev", "why", "rid"],
        "required": ["op", "pid", "field", "rev", "rid"],
        "fields": {"op": {"type": "enum", "values": list(PILOTDB_EDIT_OPS)},
                   "pid": _text(11, 11, PILOTDB_PID_PATTERN),
                   "field": {"type": "enum", "values": list(PILOTDB_EDIT_FIELDS)},
                   "value": _text(0, _PL["value_max"], _LINE),
                   "rev": _int(1, 2147483647),
                   "why": _text(0, _PL["why_max"], _LINE),
                   "rid": _text(6, 40, TICKET_CID_PATTERN)},
        "nonempty_when": [{"field": "op", "is": "set", "then": "value"}]},
})
# The only answers a note or an edit gets (the synthesized sensor's answers[].why, the file's answers[].why). <author>
# is ryan or a pilot's instance name, <n> a limit, <field> one of PILOTDB_EDIT_FIELDS, HH:MM an HST time; never text
# anyone typed.
PILOTDB_ANSWERS = (
    "Saved",
    "Not saved: changed by <author> at HH:MM HST; your text is still in the box",
    "Not saved: the record changed since you opened it; your change is still in the box",
    "Not saved: only your own notes can be taken back",
    "Not saved: over <n> notes in 24 h",
    "Not saved: over <n> changes in 24 h",
    "Not saved: over <n> edits in 24 h",
    "Not saved: a note is at most <n> characters",
    "Not saved: the notes field is at most <n> characters",
    "Not saved: that value is not valid for <field>",
    "Not saved: that pilot is not in Ryan's pilot database",
    "Not saved: the log for that pilot is full",
    "Not saved: the shared notes file is full",
    "Not saved: Ryan has not shared the pilot database with you",
    "Not saved: too old, send it again",
    "Not saved: it could not be read, send it again",
    "Busy: try again in a minute",
    # 1.7.10 (revision 5): a pilot's contacts list (upload/pdf kind contacts), answered under the upload's uid. <n>
    # are counts; never a name, a number or a cell of the file
    "Contacts merged: <n> rows read, <n> pilots added, <n> updated, <n> held for Ryan",
    "Not merged: that file is not the contacts list (CSV) export",
    "Not merged: no pilot was read from that contacts list",
    "Not merged: a contacts list is at most <n> KB",
    "Not merged: over <n> contacts lists in 24 h",
    "Not merged: a contacts list is at most <n> rows",
    "Not merged: over <n> pilots that no list of Ryan's holds; ask Ryan to upload his own list first",
)
# The AI note (Ryan, Nov 14: "Through HOM's models"): HOM's consultant models write one short note per pilot with at
# least min_pickups pickups, from anonymous pickup statistics only. 1.7.10 (Ryan's decision 3 of Nov 15): on by
# default; Ryan's own switch on his card turns it off (and on again). A shared pilot reads a note, read only, on the
# records of his file; nobody but HOM's hand-off writes one. Flight Watcher
# writes the statistics file; each pilot
# in it has an id made new for every batch (random, kept only in Ryan's database, so nobody else can map it back), and
# no name, employee number, record id, seniority number, date of hire, pairing number or exact date. HOM answers with
# one file per batch; a note is note_max code points of plain text at most (the ticket text rule, no "@" and no
# "://"), stored apart from the human notes (pilotdb's ai_notes), labeled AI with its model, never an instruction.
# 1.7.10 review: refuse_re (a search, no flags) is everything a note may not hold now that a shared pilot reads it: an
# address ("@"), a link ("://", "http:", "https:", "www." in any case), 5 or more digits in a row (an employee number)
# and a phone shaped run (3 digits, a hyphen, period or space, 4 digits). A pickup pattern needs none of them. A name
# or an order in words cannot be told by a pattern: the note stays untrusted plain text wherever it is read.
PILOTDB_AI = {"min_pickups": 3, "note_max": 600, "model_max": 80, "batch_keep": 2, "max_pilots": 2000,
              "in_bytes": 2 * 1024 * 1024, "stale_h": 72,
              "dir": "/share/flight_watcher/pilotdb/ai", "stats_file": "stats.json", "in_dir": "in",
              "in_file_re": r"^[0-9a-f]{16}\.json$", "id_re": r"^a[0-9a-f]{16}$", "batch_re": r"^[0-9a-f]{16}$",
              "model_re": r"^[A-Za-z0-9][A-Za-z0-9 ._:/()+-]{0,79}$",
              "refuse_re": r"@|://|\b[Hh][Tt][Tt][Pp][Ss]?:|\b[Ww][Ww][Ww]\.|[0-9]{5,}|[0-9]{3}[-. ][0-9]{4}"}


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


# discovery oids a pilot has whose feature a portal may not offer: the uploads sensors (uploads stay off the portal).
# 1.7.0: sensor.<prefix>_tickets passes now (the tickets feature is offered), with his own tickets only
ENTITY_PORTAL_FEATURE = {"tickets": "tickets", "uploads": "uploads", "upload_status": "uploads"}
# 1.7.14 (Ryan, Nov 17): discovery oids a pilot has in HA that his portal does not serve yet, whatever their feature. The
# near misses sensor (sensor.<prefix>_near_misses) is core and every instance computes its own, but a new exported state
# is a portal contract change (PORTAL_CONTRACT.md 4.2): it waits for a later contract revision, so contract 1 revision 6
# and a pilot's state.json stay exactly as they are.
ENTITY_OFF_PORTAL = frozenset({"near_misses"})


def entity_on_portal(oid, instance):
    """True when a portal serves this discovery entity of instance: the instance has its feature, FEATURES offers that
    feature on a portal, and (1.7.14) the entity is not one held back for a later contract revision (ENTITY_OFF_PORTAL)."""
    if oid in ENTITY_OFF_PORTAL:
        return False
    f = ENTITY_FEATURE.get(oid) or ENTITY_PORTAL_FEATURE.get(oid, "core")
    return allowed(f, instance) and FEATURES[f][1]
