"""Schedule versions (0.9.0, Ryan, 2026-11-05): every change FLICA shows to a month's schedule becomes a
numbered version, MM.NNN (11.001 = the first November schedule the Watcher stored, the awarded line).
A version holds the month's items, days, totals and each trip's block / credit / seat / times at that
moment, so the schedule card can show any version and price it with today's pay settings:
Awarded-Pay-Gross = version .001, Improved-Pay-Gross = current minus awarded.

What counts as a change (Ryan: anything at all): trips added, dropped or swapped, day codes (VAC, SCR,
SICK...), FLICA's totals, and any trip's block, credit, seat, report or final arrival, including the
actuals that move after a trip flies. Versions live in the DB (kv sched_versions:<YYYY-MM>) and are
published on flight_watcher/schedule_versions. Read only; nothing here touches FLICA."""
import json

TRIP_FIELDS = ("blk", "credit", "soft", "seat", "report", "last_arr", "duties")
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
