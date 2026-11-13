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
from datetime import date, timedelta

# 1.7.2: payp / protected mark a PAYP record (payp_entries); they ride along with the version, not in the fingerprint
TRIP_FIELDS = ("blk", "credit", "soft", "seat", "report", "last_arr", "duties", "payp", "protected")
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
            out.append(f"PAYP {k.split('|')[1]} keeps {prot or 'the removed trip'}'s credit {nt[k]['credit']} "
                       "(pay protected)")
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


# ---------------------------------------------------------------- 1.7.2: pay protection (Ryan, Nov 13)
# "My LAS trip today was cancelled and PAYP pay protected. Why did your pay calculations drop?" 2023 PWA Definitions
# item 57: "PAY PROTECT/PAY PROTECTION (PAYP): A Flight Grouping that has been removed from a pilot's schedule, however
# the pilot shall retain the Pay and Credit for such Flight Grouping." FLICA shows the days as PAYP (a code, no pairing
# page), so the removed trip's credit has to come from what the Watcher held before: its own trips record, else the
# schedule versions. PWA 4.R.1: a trip added on PAYP days pays in full on top (it is a trip of its own).
PAYP = "PAYP"


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


def _from_versions(s, e, versions_of, is_pairing, on, taken, own):
    """The trips the PAYP s..e took the place of, from the stored versions: in the newest version of each month the
    PAYP touches that has no PAYP item over these days (the line just before the PAYP), the pairings over these days
    that are no longer on the schedule. [(key, minutes, seat)] with their credit from that version (else own trips),
    and that version's number; ([], '') when none is on file."""
    got, ver = {}, ""
    for mk in _months(s, e):
        vers = [v for v in (versions_of(mk) or []) if isinstance(v, dict)]
        before = next((v for v in reversed(vers) if not any(
            isinstance(i, dict) and i.get("trip") == PAYP and _overlaps(i.get("start"), i.get("end"), s, e)
            for i in v.get("items") or [])), None)
        if not before:
            continue
        for it in before.get("items") or []:
            k = f"{it.get('trip')}|{it.get('start')}" if isinstance(it, dict) else ""
            if (not k or k in got or k in on or k in taken or not is_pairing(it.get("trip") or "")
                    or not _overlaps(it.get("start"), it.get("end"), s, e)):
                continue
            rec = (before.get("trips") or {}).get(k) or {}
            n = _mins(rec.get("credit"))
            if n is None:
                rec = own.get(k) if isinstance(own.get(k), dict) else {}
                n = _mins(rec.get("credit"))
            if n is not None:
                got[k] = (k, n, rec.get("seat") or "")
                ver = ver or str(before.get("ver") or "")
    return list(got.values()), ver


def payp_entries(items, own, versions_of, is_pairing):
    """{PAYP|<start>: record} for the PAYP items on the schedule whose removed trip's credit is known. own: the own
    trips records keyed TRIP|start, taken before the ones no longer on the schedule are pruned; versions_of(month) ->
    that month's stored versions (oldest first); is_pairing(trip) -> truthy for a pairing id. Pure, never reads FLICA.

    record: credit (the removed Flight Grouping's credit, PWA Definitions 57), blk and soft "0:00" (nothing is flown:
    the block total, Block Avail and FAR 117 never count a PAYP), payp True, protected (the removed trip's key, or keys
    joined by commas), end (the PAYP's last day), seat (when all removed trips had the same one) and src ("own trips"
    or the version the credit was read from, "v11.028").

    Which trip: an own trips record no longer on the schedule whose days overlap the PAYP's; else the newest stored
    version before the PAYP (no PAYP item over these days) and its pairings over these days that are no longer on the
    schedule; else none (no record: the schedule card estimates it from FLICA's month credit). Several removed trips
    (one PAYP over parts of two) sum their credits, each one counted in full; a removed trip counts for one PAYP only
    (the first by start date), never twice. A record on file whose PAYP has the same days is kept as it is while the
    PAYP is on the schedule (never dropped because the removed trip is gone, never changed by a trip added on the PAYP
    days and dropped again, PWA 4.R.1). When its days change, it keeps its credit and adds any trip removed over the
    new days; a record whose PAYP start moved (a new key) hands its trips and credit on to the PAYP now over its days.
    Never invents a credit: no removed trip with a credit on file gives no record."""
    own = own if isinstance(own, dict) else {}
    spans = _payp_spans(items)
    on = {f"{it.get('trip')}|{it.get('start')}" for it in items or [] if isinstance(it, dict) and it.get("trip")}
    cur = {f"{PAYP}|{s}" for s, _ in spans}
    out, taken = {}, set()
    for s, e in spans:  # first: the records on file whose PAYP kept its days, as they are
        rec = own.get(f"{PAYP}|{s}")
        if _valid(rec) and rec.get("end") == e:
            out[f"{PAYP}|{s}"] = rec
            taken.update(_prot(rec))
    ends = {}  # a removed trip's last day, from the stored versions (else its duty periods)
    for mk in sorted({mk for s, e in spans for mk in _months(s, e)} | {mk for s, _ in spans for mk in _months(
            (date.fromisoformat(s) - timedelta(days=20)).isoformat(), s)}):
        for v in versions_of(mk) or []:
            for it in (v.get("items") or []) if isinstance(v, dict) else []:
                if isinstance(it, dict) and it.get("trip") and it.get("start"):
                    ends[f"{it['trip']}|{it['start']}"] = it.get("end") or it["start"]
    for s, e in spans:
        k = f"{PAYP}|{s}"
        if k in out:
            continue
        old = own.get(k) if _valid(own.get(k)) else None
        parts = [(p, None, None) for p in _prot(old)] if old else []
        mins, seats, src = (_mins(old["credit"]) if old else 0), ([old.get("seat") or ""] if old else []), \
            ((old or {}).get("src") or "")
        for ok, orec in sorted(own.items()):  # a PAYP whose start moved: its trips and credit move with it
            if (ok.startswith(f"{PAYP}|") and ok not in cur and _valid(orec)
                    and _overlaps(ok.split("|", 1)[1], orec.get("end"), s, e)
                    and not any(p in taken or p in {q for q, _, _ in parts} for p in _prot(orec))):
                parts += [(p, None, None) for p in _prot(orec)]
                mins += _mins(orec["credit"])
                seats.append(orec.get("seat") or "")
                src = src or orec.get("src") or ""
        held = taken | {p for p, _, _ in parts}
        new = []
        for ok, orec in sorted(own.items()):
            trip, _, st = ok.partition("|")
            if (not isinstance(orec, dict) or ok in on or ok in held or not is_pairing(trip)
                    or _mins(orec.get("credit")) is None):
                continue
            if _overlaps(st, ends.get(ok) or _duty_end(st, orec) or st, s, e):
                new.append((ok, _mins(orec["credit"]), orec.get("seat") or ""))
        if new:
            src = src or "own trips"
        elif not parts:
            new, ver = _from_versions(s, e, versions_of, is_pairing, on, held, own)
            src = f"v{ver}" if new and ver else src
        if not parts and not new:
            continue
        for p, n, seat in new:
            parts.append((p, n, seat))
            mins += n
            seats.append(seat)
        taken.update(p for p, _, _ in parts)
        seat = seats[0] if seats and all(x == seats[0] for x in seats) else ""
        rec = {"credit": _hm(mins), "blk": "0:00", "soft": "0:00", "payp": True,
               "protected": ",".join(p for p, _, _ in parts), "end": e, "src": src}
        if seat:
            rec["seat"] = seat
        out[k] = rec
    return out
