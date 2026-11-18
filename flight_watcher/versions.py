"""Schedule versions (0.9.0, Ryan, 2026-11-05): every change FLICA shows to a month's schedule becomes a
numbered version, MM.NNN (11.001 = the first November schedule the Watcher stored, the awarded line).
A version holds the month's items, days, totals and each trip's block / credit / seat / times at that
moment, so the schedule card can show any version and price it with today's pay settings:
Awarded-Pay-Gross = version .001, Improved-Pay-Gross = current minus awarded.

What counts as a change (Ryan: anything at all): trips added, dropped or swapped, day codes (VAC, SCR,
SICK...), FLICA's totals, and any trip's block, credit, seat, report or final arrival, including the
actuals that move after a trip flies. Versions live in the DB (kv sched_versions:<YYYY-MM>) and are
published on flight_watcher/schedule_versions. Read only; nothing here touches FLICA.

1.7.2 (Ryan, Nov 13): a pay protected trip (PAYP) keeps the removed trip's credit (payp_entries), stored in each
version's trips under PAYP|<start> like any trip, so every pay figure counts it."""
import json
import re
from datetime import date, datetime, timedelta, timezone

import pay as PAY

# 1.7.2: payp / protected / split / of mark a PAYP record (payp_entries); they ride along with the version, not in the
# fingerprint
TRIP_FIELDS = ("blk", "credit", "soft", "seat", "report", "last_arr", "duties", "payp", "protected", "split", "of")
FP_FIELDS = ("blk", "credit", "seat", "report", "last_arr")
MAX_PUBLISHED = 25  # per month: the awarded version plus the latest ones (keeps the sensor small)


def trips_of(items, own_trips):
    """The own_trips records (block / credit / times) for this month's pairings, keyed TRIP|start."""
    out = {}
    for it in items or []:
        k = f"{it.get('trip')}|{it.get('start')}"
        t = (own_trips or {}).get(k)
        if t:
            out[k] = {f: t.get(f) for f in TRIP_FIELDS if t.get(f) not in (None, "", [])}
    return out


def fingerprint(sched, trips):
    core = {"items": [(i.get("trip"), i.get("start"), i.get("end"), i.get("lay")) for i in sched.get("items") or []],
            "days": [(d[0], d[1], d[2]) for d in sched.get("days") or []],
            # FLICA's days_off differs between its own pages (15 vs 19 for the same line), so it is not a change
            "totals": {k: v for k, v in (sched.get("totals") or {}).items() if k != "days_off"},
            "trips": {k: {f: v.get(f) for f in FP_FIELDS} for k, v in sorted(trips.items())}}
    return json.dumps(core, sort_keys=True, default=str)


def diff(old, new):
    """Human lines describing what changed between two versions."""
    out = []
    if old is None:
        return ["first version on file (awarded line)"]
    oi = {(i["trip"], i["start"]) for i in old.get("items") or []}
    ni = {(i["trip"], i["start"]) for i in new.get("items") or []}
    for t, s in sorted(ni - oi):
        out.append(f"added {t} {s}")
    for t, s in sorted(oi - ni):
        out.append(f"dropped {t} {s}")
    oe = {(i["trip"], i["start"]): i.get("end") for i in old.get("items") or []}  # trip end: a trip's last day moved
    for i in new.get("items") or []:
        a = oe.get((i["trip"], i["start"]))
        if a and i.get("end") and a != i["end"]:
            out.append(f"{i['trip']} {i['start']} ends {i['end']} (was {a})")
    # day codes that changed (VAC, SCR, SICK...), skipping days already explained by an added / dropped trip
    moved = {t for t, _ in (ni ^ oi)}
    od = {d[0]: d[1] for d in old.get("days") or []}
    for d in new.get("days") or []:
        a, b = od.get(d[0]), d[1]
        if a is None or a == b or a in moved or b in moved:
            continue
        out.append(f"{d[0]}: {a or 'off'} -> {b or 'off'}")
    ot, nt = old.get("trips") or {}, new.get("trips") or {}
    for k in sorted(set(nt) - set(ot)):  # 1.7.2: a PAYP's kept credit, the first version that has it
        if isinstance(nt[k], dict) and nt[k].get("payp") and nt[k].get("credit"):
            prot = ", ".join(p.replace("|", " ") for p in str(nt[k].get("protected") or "").split(",") if p)
            sp = nt[k].get("split") if isinstance(nt[k].get("split"), dict) else {}
            # 1.7.11 review (FW-0080): the split's keys are bid periods
            by = f"; by bid period (PWA 4.A) {', '.join(f'{m} {v}' for m, v in sorted(sp.items()))}" if sp else \
                "; this bid period's share (PWA 4.A)" if nt[k].get("of") else ""
            out.append(f"PAYP {k.split('|')[1]} keeps {prot or 'the removed trip'}'s credit {nt[k]['credit']} "
                       f"(pay protected{by})")
    for k in sorted(set(ot) & set(nt)):
        for f, lab in (("blk", "block"), ("credit", "credit"), ("seat", "seat"), ("report", "report"), ("last_arr", "arrival")):
            a, b = ot[k].get(f), nt[k].get(f)
            if a != b and b not in (None, ""):
                out.append(f"{k.split('|')[0]} {lab} {a or '?'} -> {b}")
    for f in ("block", "credit"):
        a, b = (old.get("totals") or {}).get(f), (new.get("totals") or {}).get(f)
        if a != b and b not in (None, ""):
            out.append(f"FLICA {f} {a or '?'} -> {b}")
    return out or ["schedule re-read with small differences"]


def update(db, months, own_trips, now_iso):
    """Compare each month on file with its last stored version; store a new one when anything differs.
    Returns the list of (month, version) created."""
    made = []
    for month, sched in (months or {}).items():
        if not sched or not sched.get("days"):
            continue
        key = f"sched_versions:{month}"
        vers = db.get(key) or []
        trips = trips_of(sched.get("items"), own_trips)
        fp = fingerprint(sched, trips)
        last = vers[-1] if vers else None
        if last and last.get("fp") == fp:
            continue
        n = (int(last["ver"].split(".")[1]) if last else 0) + 1
        rec = {"ver": f"{int(month[5:7])}.{n:03d}", "n": n, "at": now_iso, "updated": sched.get("updated") or "",
               "items": sched.get("items") or [], "days": sched.get("days") or [], "totals": sched.get("totals") or {},
               "trips": trips, "fp": fp}
        rec["changes"] = diff(last, rec)
        vers.append(rec)
        db.put(key, vers)
        made.append((month, rec["ver"]))
    return made


def published(db, months):
    """Per month, the awarded version and the latest MAX_PUBLISHED - 1 versions, newest last, without fingerprints.
    FW-0060: this goes to the versions_<key>.json file the schedule card reads (it ran about 33 KB as sensor
    attributes, over HA's 16 KB recorder limit); the sensor carries summary() only."""
    out = {}
    for month in sorted(months or {}):
        vers = db.get(f"sched_versions:{month}") or []
        if not vers:
            continue
        keep = vers if len(vers) <= MAX_PUBLISHED else [vers[0]] + vers[-(MAX_PUBLISHED - 1):]
        out[month] = {"count": len(vers), "current": vers[-1]["ver"], "awarded": vers[0]["ver"],
                      "versions": [{k: v for k, v in r.items() if k != "fp"} for r in keep]}
    return out


def summary(full):
    """FW-0060: the sensor's per-month summary of published(): counts and the awarded / current version, no items."""
    return {mk: {"count": m["count"], "current": m["current"], "awarded": m["awarded"],
                 "current_at": (m["versions"][-1].get("at") or "") if m.get("versions") else ""}
            for mk, m in (full or {}).items()}


# The marker repair_ends() leaves on a version it changed. A plain label, not a ticket number: the trip end fix has
# no ticket filed on Pako, and FW-nnnn numbers come only from the ticket flow (tickets.py).
REPAIR_TAG = "trip-end-1.4.7"


def repair_ends(vers, rebuild):
    """Trip end: versions stored while the item builder cut a trip short (its return day taken by the next trip's row:
    H3681 Nov 9 to 12 stored as Nov 9 to 9) get the end their own days list gives (rebuild(days) -> items, pot's
    schedule_items). Only a pairing's end that moves later changes; the PBS award (built from the PDF) is left alone.
    Each changed version's fingerprint is made again so the next read of the same line is not a new version.
    Returns the number of versions changed (vers is changed in place)."""
    n = 0
    for v in vers or []:
        if not isinstance(v, dict) or v.get("award") or not v.get("days"):
            continue
        try:
            ends = {(i.get("trip"), i.get("start")): i.get("end") for i in rebuild(v["days"]) or []}
        except Exception:
            continue
        hit = False
        for it in v.get("items") or []:
            e = ends.get((it.get("trip"), it.get("start")))
            if e and it.get("end") and e > it["end"] and it.get("trip") not in ("VAC",):
                it["end"] = e
                hit = True
        if hit:
            if "fp" in v:
                v["fp"] = fingerprint(v, v.get("trips") or {})
            v["repaired"] = REPAIR_TAG
            n += 1
    return n


def seed(db, path, iso_of):
    """Import earlier versions rebuilt from HA's recorder (a JSON file {month: [{ts, items, days, totals,
    updated, trips}]}) for months that have no versions yet. Returns the versions created."""
    import os
    if not os.path.exists(path):
        return []
    try:
        data = json.load(open(path))
    except Exception:
        return []
    made = []
    for month, snaps in data.items():
        key = f"sched_versions:{month}"
        if db.get(key):
            continue
        vers = []
        for sn in snaps:
            rec = {"ver": f"{int(month[5:7])}.{len(vers) + 1:03d}", "n": len(vers) + 1, "at": iso_of(sn.get("ts")),
                   "updated": sn.get("updated") or "", "items": sn.get("items") or [], "days": sn.get("days") or [],
                   "totals": sn.get("totals") or {}, "trips": sn.get("trips") or {}, "seeded": True}
            if sn.get("award"):
                rec["award"] = True
            rec["fp"] = fingerprint(rec, rec["trips"])
            rec["changes"] = ["awarded line (PBS bid run)"] if rec.get("award") else diff(vers[-1] if vers else None, rec)
            vers.append(rec)
            made.append((month, rec["ver"]))
        if vers:
            db.put(key, vers)
    return made


def set_award(db, month, sched, iso_now):
    """Make the parsed PBS award this month's version .001 (replacing an earlier award) and renumber the rest
    after it. Returns the version list."""
    key = f"sched_versions:{month}"
    vers = [v for v in (db.get(key) or []) if not v.get("award")]
    rec = {"items": sched["items"], "days": sched["days"], "totals": sched.get("totals") or {},
           "updated": sched.get("updated") or "Award", "trips": sched.get("trips") or {}, "at": iso_now, "award": True}
    rec["fp"] = fingerprint(rec, rec["trips"])
    out = []
    for n, v in enumerate([rec] + vers, 1):
        v = {**v, "ver": f"{int(month[5:7])}.{n:03d}", "n": n}
        v["changes"] = ["awarded line (PBS bid run)"] if v.get("award") else diff(out[-1] if out else None, v)
        out.append(v)
    db.put(key, out)
    return out


def clear_award(db, month):
    """1.7.2 (FW-0066): the month's award file was removed (the admin's Remove of a pilot's upload with nothing to
    restore): the awarded line is no longer version .001, and the rest are numbered again from .001 in order. Returns
    the version list (unchanged when no award was in it)."""
    key = f"sched_versions:{month}"
    old = db.get(key) or []
    vers = [v for v in old if not v.get("award")]
    if len(vers) == len(old):
        return old
    out = []
    for n, v in enumerate(vers, 1):
        v = {**v, "ver": f"{int(month[5:7])}.{n:03d}", "n": n}
        v["changes"] = diff(out[-1], v) if out else ["first version on file (the award was removed)"]
        out.append(v)
    db.put(key, out)
    return out


# ---------------------------------------------------------------- 1.7.2: pay protection (Ryan, Nov 13)
# "My LAS trip today was cancelled and PAYP pay protected. Why did your pay calculations drop?" 2023 PWA Definitions
# item 57: "PAY PROTECT/PAY PROTECTION (PAYP): A Flight Grouping that has been removed from a pilot's schedule, however
# the pilot shall retain the Pay and Credit for such Flight Grouping." FLICA shows the days as PAYP (a code, no pairing
# page), so the removed trip's credit has to come from what the Watcher held before: its own trips record, else the
# schedule versions. PWA 4.R.1: a trip added on PAYP days pays in full on top (it is a trip of its own).
PAYP = "PAYP"
DROP_WAIT = timedelta(hours=24)  # fix pass: a trip FLICA dropped this long at most before its PAYP showed still counts


def _mins(v):
    """'15:00' -> 900 (minutes, exact sums); None when it is not H:MM."""
    m = re.fullmatch(r"\s*(\d+):(\d{2})\s*", str(v or ""))
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def _hm(n):
    return f"{n // 60}:{n % 60:02d}"


def _overlaps(a0, a1, b0, b1):
    return bool(a0 and b0) and a0 <= (b1 or b0) and b0 <= (a1 or a0)


def _duty_end(start, rec):
    """A cached trip's last day from its duty periods (arr: HST minutes from the trip's first day), else ''."""
    arr = [d.get("arr") for d in (rec.get("duties") or []) if isinstance(d, dict) and isinstance(d.get("arr"), (int, float))]
    try:
        return (date.fromisoformat(start) + timedelta(days=int(max(arr) // 1440))).isoformat() if arr else ""
    except ValueError:
        return ""


def _prot(rec):
    return [p for p in str((rec or {}).get("protected") or "").split(",") if p]


def _valid(rec):
    return isinstance(rec, dict) and bool(rec.get("payp")) and _mins(rec.get("credit")) is not None


def _payp_spans(items):
    """[(start, end)] of the PAYP items on the schedule, once each (a month boundary can list one twice), by start."""
    out = {}
    for it in items or []:
        if isinstance(it, dict) and it.get("trip") == PAYP and it.get("start"):
            out[it["start"]] = max(out.get(it["start"], ""), it.get("end") or it["start"])
    return sorted(out.items())


def _months(s, e):
    out, y, m = [], int(s[:4]), int(s[5:7])
    while f"{y:04d}-{m:02d}" <= e[:7] and len(out) < 3:
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _days(s, e):
    """Each ISO day from s to e (62 at most); [] when s is not a date."""
    try:
        a, b = date.fromisoformat(str(s)), date.fromisoformat(str(e or s))
    except ValueError:
        return []
    return [(a + timedelta(days=i)).isoformat() for i in range(min(62, max(0, (b - a).days) + 1))]


def _at(v):
    """A stored version's time ('at', UTC ISO), else None."""
    try:
        t = datetime.fromisoformat(str((v or {}).get("at") or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _cal(iso):
    """The calendar month of a day: the bid period's stand-in when no bounds are on file."""
    return str(iso)[:7]


def _split(st, rec, n, period_of=None, tcrd=None):
    """PWA 4.A: n credit minutes of a trip that starts on st, by bid period (1.7.11, FW-0080: period_of(iso) names the
    bid period of a day, the Watcher's pairing files' bounds; the calendar month when none is given), the schedule
    card's way (pay.split_by_period): each duty period in the bid period that holds its HST departure date (dep: HST
    minutes from the trip's first day), with its TCRD when tcrd lists one per duty (the pairings package's), else its
    block share; the bid period of st keeps the rest. {period_of(st): n} when no duty block is on file."""
    po = period_of or _cal
    du = [d for d in (rec or {}).get("duties") or [] if isinstance(d, dict)]
    if isinstance(tcrd, (list, tuple)) and len(tcrd) == len(du):
        du = [dict(d, tcrd=t) for d, t in zip(du, tcrd)]
    sp = PAY.split_by_period(st, du, po, n / 60)
    if sp is None:
        return {po(st): n}
    return {k: v["credit"] for k, v in sp["by"].items() if v["credit"] is not None}


def _split_of(k, rec, period_of=None):
    """A record's credit by bid period in minutes: its split, else all of it in the bid period its PAYP starts."""
    sp = rec.get("split") if isinstance(rec.get("split"), dict) else {}
    out = {m: _mins(v) for m, v in sp.items() if _mins(v) is not None}
    return out or {(period_of or _cal)(k.split("|", 1)[1]): _mins(rec.get("credit")) or 0}


def _has_duties(rec):
    return isinstance(rec, dict) and any(isinstance(d, dict) and isinstance(d.get("dep"), (int, float))
                                         and isinstance(d.get("blk"), (int, float)) for d in rec.get("duties") or [])


def duty_record(key, own, versions_of):
    """1.7.11 review (FW-0080): the record of trip key ('TRIP|start') that holds its duty periods: the own trips record,
    else the newest stored version that lists it (versions_of(month) -> that month's versions, oldest first; the month
    of its first day, the one before and the one after); None when neither has its duties."""
    rec = (own or {}).get(key)
    if _has_duties(rec):
        return rec
    st = str(key).partition("|")[2]
    try:
        d = date.fromisoformat(st)
    except ValueError:
        return None
    for mk in ((d.replace(day=1) - timedelta(days=1)).strftime("%Y-%m"), st[:7], (d.replace(day=28) + timedelta(days=4)).strftime("%Y-%m")):
        for v in reversed([v for v in (versions_of(mk) or []) if isinstance(v, dict)]):
            rec = (v.get("trips") or {}).get(key)
            if _has_duties(rec):
                return rec
    return None


def _split_payp_days(p, rec, n, period_of, tcrd, s, e):
    """1.7.11 integration review (PWA 4.A, PWA Definitions 57): n credit minutes a PAYP over s..e keeps of removed trip p
    ('TRIP|start') when a pairing with its base id still flies part of it (_net: H9640A flies its Dec 2 and Dec 3
    duties): only the trip's duties that depart on the PAYP's own days split it (the flown ones are paid by that
    pairing), each with its TCRD when tcrd lists one per duty; the bid period of the trip's first day (a PAYP day: the
    removed trip starts on one) keeps the rest, as _split does. {period: minutes}."""
    po, st = period_of or _cal, p.split("|", 1)[1]
    days = set(_days(s, e or s))
    du = [d for d in (rec or {}).get("duties") or [] if isinstance(d, dict)]
    tc = list(tcrd) if isinstance(tcrd, (list, tuple)) and len(tcrd) == len(du) else None
    try:
        t0 = date.fromisoformat(st)
    except ValueError:
        return {po(s): n}
    keep = [i for i, d in enumerate(du) if isinstance(d.get("dep"), (int, float)) and not isinstance(d.get("dep"), bool)
            and (t0 + timedelta(days=int(d["dep"] // 1440))).isoformat() in days]
    return _split(st, dict(rec or {}, duties=[du[i] for i in keep]), n, po, [tc[i] for i in keep] if tc else None)


def payp_resplit(k, rec, find, period_of=None, tcrd_of=None, end=None):
    """1.7.11 review (FW-0080, PWA 4.A): a PAYP record (key PAYP|start) on file split again by the bid period rule, so a
    record written under the calendar month (1.7.10) counts each bid period's part as FLICA does: each protected trip's
    duties (find(trip key) -> its record with duties, duty_record) with their TCRD (tcrd_of), its credit the record's
    (one protected trip) or each trip's own (several, when they add up to the record's credit). The record as it is
    when a protected trip's duties are not on file or the credits do not add up, and for a continuation record ('of':
    its share follows its original, payp_share). Only 'split' changes: never the credit, the trips or the days.
    1.7.11 integration review: one protected trip whose credit is above the record's (a pairing with its base id flies
    part of it, _net) splits only its duties on the PAYP's days (_split_payp_days; end: the PAYP's last day, the
    record's own when not given; the record as it is when neither says)."""
    if not _valid(rec) or rec.get("of"):
        return rec
    parts, n = _prot(rec), _mins(rec.get("credit"))
    recs = [find(p) for p in parts]
    if not parts or any(r is None for r in recs):
        return rec
    ns = [n] if len(parts) == 1 else [_mins(r.get("credit")) for r in recs]
    if None in ns or sum(ns) != n:
        return rec
    po, msplit, end = period_of or _cal, {}, end or rec.get("end") or ""
    for p, r, x in zip(parts, recs, ns):
        tc = tcrd_of(p, r) if tcrd_of else None
        full = _mins(r.get("credit"))
        if len(parts) == 1 and full is not None and x < full:
            if not end:
                return rec
            got = _split_payp_days(p, r, x, po, tc, k.split("|", 1)[1], end)
        else:
            got = _split(p.split("|", 1)[1], r, x, po, tc)
        for m, v in got.items():
            msplit[m] = msplit.get(m, 0) + v
    sp = {m: _hm(v) for m, v in sorted(msplit.items()) if v > 0}
    out = {f: v for f, v in rec.items() if f != "split"}
    if set(sp) - {po(k.split("|", 1)[1])}:
        out["split"] = sp
    return rec if out == rec else out


def _share_key(rs, sp, s, e, po):
    """The bid period whose share of a PAYP record (its PAYP from rs, split sp) a PAYP listed again on the next page
    (s..e) carries: the first of its days in a bid period other than rs's that the split names. FLICA's next page
    starts on the bid period before's last day (December's grid on Dec 1, November's), so its first day alone never
    tells (1.7.11 review: PAYP|12-01 is November's day, its share December's)."""
    return next((po(d) for d in _days(s, e) if po(d) != po(rs) and _mins(sp.get(po(d)))), None)


def payp_share(k, rec, orig, period_of=None):
    """1.7.11 review (FW-0080): the credit of continuation record k (a PAYP listed again on the next page, 'of' its
    original orig) under the bid period rule: orig's split share of the bid period of k's days (_share_key), or None
    when orig gives this PAYP no share (all its credit pays in orig's own bid period)."""
    po = period_of or _cal
    sp = orig.get("split") if isinstance(orig, dict) and isinstance(orig.get("split"), dict) else {}
    key = _share_key(str(rec.get("of") or "").split("|", 1)[-1], sp, k.split("|", 1)[1], rec.get("end") or k.split("|", 1)[1], po)
    return sp[key] if key else None


def _payp_end(v, k):
    """1.7.11 integration review: the last day of the PAYP item a stored version lists at record k's start (PAYP|start),
    '' when it lists none there: a version's records never hold 'end' (trips_of keeps TRIP_FIELDS only)."""
    st = k.split("|", 1)[1]
    ends = [str(i.get("end") or i["start"]) for i in (v.get("items") or []) if isinstance(i, dict) and i.get("trip") == PAYP
            and i.get("start") == st]
    return max(ends) if ends else ""


FILLER = "schedule re-read with small differences"


def _payp_lines(old, new):
    """1.7.11 integration review: a version's change lines with its PAYP lines (those that start "PAYP ") taken from new
    (diff of the repaired versions, the bid period's wording), the others as they were and where they were."""
    old = [c for c in old or [] if isinstance(c, str)]
    mine = [c for c in new or [] if c.startswith(f"{PAYP} ")]
    rest = [c for c in old if not c.startswith(f"{PAYP} ")]
    if not mine and len(rest) == len(old):
        return old  # no PAYP line before or after
    if mine:
        at = next((i for i, c in enumerate(old) if c.startswith(f"{PAYP} ")), len(old))
        before = sum(1 for c in old[:at] if not c.startswith(f"{PAYP} ") and c != FILLER)
        rest = [c for c in rest if c != FILLER]
        rest = rest[:before] + mine + rest[before:]
    return rest or [FILLER]


def resplit_versions(month_versions, own, period_of=None, tcrd_of=None):
    """1.7.11 review (FW-0080): the PAYP records in stored versions ({month: [version, ...]}) split again by bid period,
    as payp_entries does with the ones on file: each record payp_resplit (its protected trips' duties from own trips or
    any of these versions), each continuation record ('of') its original's share there (payp_share; dropped when the
    original gives it none). Changes the versions in place; returns the months changed.
    1.7.11 integration review: a record's span is its version's PAYP item's (a stored record has no 'end'); a
    continuation whose version lists no PAYP item at its start is kept as it is. Each version whose trips changed gets
    its fingerprint made again from them (as repair_ends does), so the next read of the same line is no new version;
    and each version's PAYP change lines are written again with the bid period's wording (diff of the repaired
    versions), so they say what the records now hold."""
    def vo(mk):
        return month_versions.get(mk) or []

    def find(p):
        return duty_record(p, own, vo)
    po, changed, orig, hit = period_of or _cal, set(), {}, set()
    for mk, vers in sorted(month_versions.items()):
        for v in vers:
            tr = v.get("trips") if isinstance(v, dict) and isinstance(v.get("trips"), dict) else {}
            for k, rec in list(tr.items()):
                if not k.startswith(f"{PAYP}|") or not _valid(rec) or rec.get("of"):
                    continue
                new = payp_resplit(k, rec, find, po, tcrd_of, rec.get("end") or _payp_end(v, k))
                if new is not rec:
                    tr[k] = new
                    changed.add(mk)
                    hit.add(id(v))
                orig[k] = new  # the newest version's, the months and their versions in order
    for mk, vers in sorted(month_versions.items()):
        for v in vers:
            tr = v.get("trips") if isinstance(v, dict) and isinstance(v.get("trips"), dict) else {}
            for k, rec in list(tr.items()):
                if not k.startswith(f"{PAYP}|") or not _valid(rec) or not rec.get("of"):
                    continue
                o = orig.get(rec["of"]) or (own or {}).get(rec["of"])  # the original as stored, else on file
                end = rec.get("end") or _payp_end(v, k)
                if not _valid(o) or not end:
                    continue  # its span cannot be read: never dropped on a guess
                share = payp_share(k, dict(rec, end=end), o, po)
                if share is None:
                    tr.pop(k)
                elif share != rec.get("credit"):
                    tr[k] = dict(rec, credit=share)
                else:
                    continue
                changed.add(mk)
                hit.add(id(v))
    for mk, vers in sorted(month_versions.items()):
        prev = None
        for v in vers:
            if not isinstance(v, dict):
                continue
            if id(v) in hit and "fp" in v:
                v["fp"] = fingerprint(v, v.get("trips") or {})
            if prev is not None and not v.get("award") and isinstance(v.get("changes"), list):
                lines = _payp_lines(v["changes"], diff(prev, v))
                if lines != v["changes"]:
                    v["changes"] = lines
                    changed.add(mk)
            prev = v
    return sorted(changed)


def _added_on_payp(month_versions):
    """Fix pass: the trips a stored version shows taken on a day an earlier version already showed as PAYP (a trip
    added on PAYP days, PWA 4.R.1, then dropped again): never the trip a PAYP protects. Keys TRIP|start."""
    out = set()
    for vers in month_versions:
        pday, seen = {}, set()
        for i, v in enumerate(vers):
            its = [it for it in v.get("items") or [] if isinstance(it, dict) and it.get("trip") and it.get("start")]
            for it in its:
                if it["trip"] == PAYP:
                    for d in _days(it["start"], it.get("end")):
                        pday.setdefault(d, i)
            for it in its:
                k = f"{it['trip']}|{it['start']}"
                if it["trip"] != PAYP and k not in seen:
                    seen.add(k)
                    if pday.get(it["start"], i) < i:
                        out.add(k)
    return out


def _net(k, n, end, sched, own):
    """Fix pass: a removed trip's credit less the credit of the pairing FLICA put in its place over its days (a changed
    pairing gets a letter: H3620 becomes H3620A when part of it still flies and the rest is PAYP), so the part flown is
    never counted twice. None while that pairing's credit is not read yet (no record then: the card's estimate)."""
    trip, _, st = k.partition("|")
    for t, s, e in sched:
        if t != trip and t[:5] == trip[:5] and _overlaps(s, e, st, end):  # a new letter, not the same pairing again
            c = _mins((own.get(f"{t}|{s}") or {}).get("credit")) if isinstance(own.get(f"{t}|{s}"), dict) else None
            if c is None:
                return None
            n -= c
    return n


def _from_versions(want, vo, is_pairing, on, held, own, skip):
    """The trips a PAYP took the place of on the days in want, from the stored versions: in each month's newest
    version with no PAYP on those days (the line just before the PAYP), its pairings that start on one of those days
    and are no longer on the schedule. When FLICA first showed the days empty (the trip dropped, the PAYP a read
    later), the version before that, if the days went empty at most DROP_WAIT before the PAYP showed. [(key, minutes,
    seat, record, end)] with their credit from that version (else own trips), and that version's number; ([], '')
    when none is on file."""
    got, ver, ws = {}, "", set(want)

    def payp_on(v):
        return any(isinstance(i, dict) and i.get("trip") == PAYP and ws & set(_days(i.get("start"), i.get("end")))
                   for i in v.get("items") or [])

    def taken_on(v):  # a pairing that starts on these days, or a code (VAC, SICK...) over them
        return any(isinstance(i, dict) and i.get("trip") and i["trip"] != PAYP and (
            i.get("start") in ws if is_pairing(i["trip"]) else ws & set(_days(i.get("start"), i.get("end"))))
            for i in v.get("items") or [])

    for mk in _months(min(want), max(want)):
        vers = vo(mk)
        shown = [t for t in (_at(v) for v in vers if payp_on(v)) if t]
        ref = min(shown) if shown else (_at(vers[-1]) if vers else None)
        before, empty = None, None
        for v in reversed(vers):
            if payp_on(v):
                continue
            if taken_on(v):
                before = v
                break
            empty = v  # the oldest version so far with these days empty
        if not before or (empty is not None and not (_at(empty) and ref and ref - _at(empty) <= DROP_WAIT)):
            continue
        for it in before.get("items") or []:
            k = f"{it.get('trip')}|{it.get('start')}" if isinstance(it, dict) else ""
            if (not k or k in got or k in on or k in held or k in skip or not is_pairing(it.get("trip") or "")
                    or it.get("start") not in ws):
                continue
            rec = (before.get("trips") or {}).get(k) or {}
            n = _mins(rec.get("credit"))
            if n is None:
                rec = own.get(k) if isinstance(own.get(k), dict) else {}
                n = _mins(rec.get("credit"))
            if n is not None:
                got[k] = (k, n, rec.get("seat") or "", rec, it.get("end") or it["start"])
                ver = ver or str(before.get("ver") or "")
    return list(got.values()), ver


def payp_entries(items, own, versions_of, is_pairing, period_of=None, tcrd_of=None):
    """{PAYP|<start>: record} for the PAYP items on the schedule whose removed trip's credit is known. own: the own
    trips records keyed TRIP|start, taken before the ones no longer on the schedule are pruned; versions_of(month) ->
    that month's stored versions (oldest first); is_pairing(trip) -> truthy for a pairing id. Pure, never reads FLICA.

    record: credit (the removed Flight Grouping's credit, PWA Definitions 57), blk and soft "0:00" (nothing is flown:
    the block total, Block Avail and FAR 117 never count a PAYP), payp True, protected (the removed trip's key, or keys
    joined by commas), end (the PAYP's last day), seat (when all removed trips had the same one), src ("own trips" or
    the version the credit was read from, "v11.028"), and split ({month: credit}) when the removed trip's duty periods
    depart in more than one month (PWA 4.A: each month counts its share, as FLICA's month credit does).

    Which trip: an own trips record no longer on the schedule that starts on one of the PAYP's days (a trip that only
    comes home on its first day is not it); else the newest stored version before the PAYP (no PAYP on these days; past
    a read that showed them empty, when FLICA dropped the trip at most a day before it showed the PAYP) and its pairings
    that start on these days and are no longer on the schedule; else none (no record: the schedule card estimates it
    from FLICA's month credit). Never a trip a stored version shows added on days already PAYP (PWA 4.R.1). A changed
    pairing over the removed trip's days (H3620 now H3620A) leaves only what is left of its credit, and no record while
    its credit is not read yet. Several removed trips (one PAYP over parts of two) sum their credits, each one counted in
    full; a removed trip counts for one PAYP only (the first by start date), never twice. A record on file whose PAYP
    has the same days is kept as it is while the PAYP is on the schedule (never dropped because the removed trip is
    gone, never changed by a trip added on the PAYP days and dropped again, PWA 4.R.1). When its days change, it keeps
    its credit and adds any trip removed on the days it gained (own trips, else the versions); a record whose PAYP
    start moved (a new key) hands its trips and credit on to the PAYP now over its days. A PAYP listed again in the
    next month (PAYP|12-01 after PAYP|11-30) gets that month's share of the split. A record whose PAYP left the schedule
    because a trip was added over all its days (PWA 4.R.1: Pay and Credit of the PAYP day plus the added trip's) stays
    while a pairing other than the removed one starts on its days; the card counts it only when FLICA's month credit
    holds it. Never invents a credit: no removed trip with a credit on file gives no record.
    1.7.11 (FW-0080): the split is by bid period (period_of(iso) -> 'YYYY-MM', the Watcher's bid_period_key; the calendar
    month when none is given), each duty's credit its TCRD when tcrd_of(trip key, record) lists one per duty. 1.7.11
    review: a record on file whose PAYP kept its days is split again by that rule (payp_resplit: a 1.7.10 record holds
    the calendar month's split, or none; only its split changes), and a continuation record ('of') always follows its
    original: its share is the bid period of its days (_share_key; the next page's PAYP starts on the bid period
    before's last day, Dec 1), kept as it is only while its original's PAYP is off the pages read."""
    own = own if isinstance(own, dict) else {}
    po = period_of or _cal
    cache = {}

    def vo(mk):
        if mk not in cache:
            cache[mk] = [v for v in (versions_of(mk) or []) if isinstance(v, dict)]
        return cache[mk]

    spans = _payp_spans(items)
    its = [it for it in items or [] if isinstance(it, dict) and it.get("trip") and it.get("start")]
    on = {f"{it['trip']}|{it['start']}" for it in its}
    sched = [(it["trip"], it["start"], it.get("end") or it["start"]) for it in its if is_pairing(it["trip"])]
    cur = {f"{PAYP}|{s}" for s, _ in spans}
    out, taken, moved, cont = {}, set(), set(), set()
    for s, e in spans:  # first: the records on file whose PAYP kept its days, as they are
        rec = own.get(f"{PAYP}|{s}")
        if _valid(rec) and rec.get("end") == e and not rec.get("of"):
            # 1.7.11 review (FW-0080): split again by bid period (a 1.7.10 record has the calendar month's split, or none)
            out[f"{PAYP}|{s}"] = payp_resplit(f"{PAYP}|{s}", rec, lambda p: duty_record(p, own, vo), po, tcrd_of)
            taken.update(_prot(rec))
    months = sorted({mk for s, e in spans for mk in _months(s, e)} | {mk for s, _ in spans for mk in _months(
        (date.fromisoformat(s) - timedelta(days=20)).isoformat(), s)})
    ends = {}  # a removed trip's last day, from the stored versions (else its duty periods)
    for mk in months:
        for v in vo(mk):
            for it in v.get("items") or []:
                if isinstance(it, dict) and it.get("trip") and it.get("start"):
                    ends[f"{it['trip']}|{it['start']}"] = it.get("end") or it["start"]
    added = _added_on_payp(vo(mk) for mk in months) if spans else set()
    for s, e in spans:
        k = f"{PAYP}|{s}"
        if k in out:
            continue
        # a continuation record (of) is never this PAYP's own: its share follows its original (below)
        old = own.get(k) if _valid(own.get(k)) and not own[k].get("of") else None
        parts = list(_prot(old)) if old else []
        mins, seats, src = (_mins(old["credit"]) if old else 0), ([old.get("seat") or ""] if old else []), \
            ((old or {}).get("src") or "")
        msplit = dict(_split_of(k, old, po)) if old else {}
        had = set(_days(s, old.get("end"))) if old else set()  # the days its credit already covers
        mv = []
        for ok, orec in sorted(own.items()):  # a PAYP whose start moved: its trips and credit move with it
            if (ok.startswith(f"{PAYP}|") and ok not in cur and ok not in moved and _valid(orec)
                    and _overlaps(ok.split("|", 1)[1], orec.get("end"), s, e)
                    and not any(p in taken or p in parts for p in _prot(orec))):
                mv.append(ok)
                parts += _prot(orec)
                mins += _mins(orec["credit"])
                seats.append(orec.get("seat") or "")
                src = src or orec.get("src") or ""
                had |= set(_days(ok.split("|", 1)[1], orec.get("end")))
                for m, n in _split_of(ok, orec, po).items():
                    msplit[m] = msplit.get(m, 0) + n
        held = taken | set(parts)
        want = [d for d in _days(s, e) if d not in had]
        new = []
        for ok, orec in sorted(own.items()):
            trip, _, st = ok.partition("|")
            if (not isinstance(orec, dict) or ok in on or ok in held or ok in added or not is_pairing(trip)
                    or _mins(orec.get("credit")) is None or st not in want):
                continue
            new.append((ok, _mins(orec["credit"]), orec.get("seat") or "", orec,
                        ends.get(ok) or _duty_end(st, orec) or st))
        if new:
            src = src or "own trips"
        elif want:
            new, ver = _from_versions(want, vo, is_pairing, on, held, own, added)
            src = src or (f"v{ver}" if new and ver else "")
        nets = [_net(p, n, end, sched, own) for p, n, _, _, end in new]
        if None in nets:  # a changed pairing in its place not read yet: what is on file stays, nothing new
            for ok in mv + ([k] if old else []):
                out[ok] = own[ok]
                taken.update(_prot(own[ok]))
            moved.update(mv)
            continue
        moved.update(mv)
        for (p, full, seat, rec, _), n in zip(new, nets):
            if n > 0:
                parts.append(p)
                mins += n
                seats.append(seat)
                tc = tcrd_of(p, rec) if tcrd_of else None
                # 1.7.11 integration review: a pairing with its base id still flies part of it (_net): only the duties
                # on the PAYP's days split what the PAYP keeps
                got = _split_payp_days(p, rec, n, po, tc, s, e) if n < full else _split(p.split("|", 1)[1], rec, n, po, tc)
                for m, x in got.items():
                    msplit[m] = msplit.get(m, 0) + x
        if not parts:  # the next month's page lists the PAYP again: that bid period's share of the split
            for rk, r in list(out.items()):
                rs, sp = rk.split("|", 1)[1], r.get("split") if isinstance(r.get("split"), dict) else {}
                # 1.7.11 review (FW-0080): the bid period of its days, not of its first day (Dec 1 is November's)
                bk = _share_key(rs, sp, s, e, po)
                if (bk and (rk, bk) not in cont
                        and rs < s <= (date.fromisoformat(r.get("end") or rs) + timedelta(days=1)).isoformat()):
                    cont.add((rk, bk))
                    out[k] = {"credit": sp[bk], "blk": "0:00", "soft": "0:00", "payp": True,
                              "protected": r.get("protected") or "", "end": e, "src": r.get("src") or "", "of": rk}
                    if r.get("seat"):
                        out[k]["seat"] = r["seat"]
                    break
            rec = own.get(k)
            if k not in out and _valid(rec) and rec.get("of") and rec.get("end") == e and rec["of"] not in cur:
                out[k] = rec  # its original's PAYP no longer on the pages read: kept as it is, while its days are
                taken.update(_prot(rec))
            continue
        taken.update(parts)
        seat = seats[0] if seats and all(x == seats[0] for x in seats) else ""
        rec = {"credit": _hm(mins), "blk": "0:00", "soft": "0:00", "payp": True, "protected": ",".join(parts), "end": e,
               "src": src}
        sp = {m: _hm(n) for m, n in sorted(msplit.items()) if n > 0}
        if set(sp) - {po(s)}:
            rec["split"] = sp
        if seat:
            rec["seat"] = seat
        out[k] = rec
    for ok, orec in sorted(own.items()):  # PWA 4.R.1: a trip added over every day of a PAYP (FLICA shows it, not PAYP)
        if not ok.startswith(f"{PAYP}|") or ok in out or ok in cur or ok in moved or not _valid(orec):
            continue
        prot, st = _prot(orec), ok.split("|", 1)[1]
        en, bases = orec.get("end") or st, {p[:5] for p in _prot(orec)}
        if not any(p in taken for p in prot) and any(st <= s2 <= en and f"{t}|{s2}" not in prot and t[:5] not in bases
                                                      for t, s2, _ in sched):
            out[ok] = orec
            taken.update(prot)
    return out
