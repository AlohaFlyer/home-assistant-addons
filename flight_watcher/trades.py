"""FW-0064 (Ryan, Nov 6 2026): a request decided on the schedule itself. Pure, no I/O.

A crew-to-crew FLICA Trade (Ryan gave two trips and got two others on Nov 6) never shows on the Open Time Requests
list or on Tradeboard My Requests, so the request-decided push never went out: the Watcher only saw its schedule
change, one FLICA "Schedule Updated" at a time (a drop at 11:30, a drop at 12:04, both adds at 14:01 HST). This module
turns those changes into the same decision the request path publishes (event/request_decided, status Approved):

- moves(): each read that changes a month gives its pairings dropped and added (codes such as VAC or SCR are not
  trades), stamped with FLICA's own "Schedule Updated" time (HST) when it is not later than the read.
- A move is explained, never pushed again, when a decision the request path already pushed covers it (its legs:
  trip and day; a decision with no legs read covers what changed between its filing and 10 min after it was seen),
  or when it pairs with the opposite move of the same pairing on the same day (H3815 becoming H3815B is a change of
  the pairing, not a trade).
- match_pending(): a request still Pending or Processing whose every leg (given trips gone, taken trips arrived) is
  on the schedule is decided now, under its own key, so the list path never pushes it a second time.
- groups(): what is left, by HST day of the change. A day with trips both dropped and added is a trade, decided once
  a later schedule read brought nothing new for that day (so a trade processed in steps is one push) and the trips
  taken have their credit read (or 2 h have passed).

The state (moves with their status) lives in the Watcher's saved state, so a restart neither forgets a move nor
pushes it twice. FLICA is never written to: this only reads what the schedule already shows."""
import hashlib
import re
from datetime import datetime, timedelta, timezone

PAIRING = re.compile(r"^[A-Z]\d{4}[A-Z]?$")  # pot.PAIRING_RE
HST = timezone(timedelta(hours=-10))
MON3 = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
UPDATED_FORMATS = ("%b %d, %Y %H:%M:%S", "%b %d, %Y %H:%M", "%B %d, %Y %H:%M:%S", "%B %d, %Y %H:%M")
KEEP_DAYS = 3  # moves older than this are forgotten
LEGLESS_SLACK = timedelta(minutes=10)
PRICE_WAIT = timedelta(hours=2)  # a group waits this long at most for the trips taken to have their credit read


def _utc(iso):
    try:
        t = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def stamp(updated, at_iso):
    """When FLICA changed the line: its 'Schedule Updated' text ('Nov 6, 2026 14:01:09', HST) as UTC ISO, unless it is
    unreadable or more than 5 min after the read (at_iso), when the read time is used."""
    at = _utc(at_iso)
    raw = " ".join(str(updated or "").split())
    for f in UPDATED_FORMATS:
        try:
            t = datetime.strptime(raw, f).replace(tzinfo=HST).astimezone(timezone.utc)
        except ValueError:
            continue
        if at is None or t <= at + timedelta(minutes=5):
            return t.isoformat()
        break
    return (at or datetime.now(timezone.utc)).isoformat()


def hst_day(t_iso):
    t = _utc(t_iso)
    return t.astimezone(HST).date().isoformat() if t else ""


def leg_day(start):
    """'2026-11-13' -> '13NOV' (the request pages' way of writing a trip's day)."""
    try:
        return f"{start[8:10]}{MON3[int(start[5:7]) - 1]}"
    except (ValueError, IndexError, TypeError):
        return ""


def moves(old_items, new_items, month, updated, at_iso, recs=None):
    """The pairings dropped and added between two reads of one month, as move dicts: {id, side, trip, start, end, lay,
    month, at, upd, t, day, rec, state}. recs: {TRIP|start: pay record} of the trips dropped, kept from before they left
    the schedule (credit, blk, seat, n, lay)."""
    key = lambda it: (it.get("trip"), it.get("start"))  # noqa: E731
    old = {key(i): i for i in old_items or [] if PAIRING.match(str(i.get("trip") or ""))}
    new = {key(i): i for i in new_items or [] if PAIRING.match(str(i.get("trip") or ""))}
    t = stamp(updated, at_iso)
    out = []
    for side, src, ks in (("drop", old, sorted(set(old) - set(new))), ("add", new, sorted(set(new) - set(old)))):
        for k in ks:
            it = src[k]
            mid = f"{side}|{k[0]}|{k[1]}|{t}"
            out.append({"id": mid, "side": side, "trip": k[0], "start": k[1], "end": it.get("end") or k[1],
                        "lay": it.get("lay") or "", "month": month, "at": at_iso, "upd": updated or "", "t": t,
                        "day": hst_day(t), "rec": dict((recs or {}).get(f"{k[0]}|{k[1]}") or {}) if side == "drop" else {},
                        "state": "open"})
    return out


def prune(mvs, now_iso):
    cut = (_utc(now_iso) - timedelta(days=KEEP_DAYS)).isoformat()
    return [m for m in mvs or [] if (m.get("t") or "") >= cut]


def leg_matches(leg, mv):
    """A request leg {trip, day 'DDMON', side} names this move: same trip (FLICA may add a suffix letter on the
    schedule), same day when the leg gives one, and the same side when the leg says which."""
    lt, mt = str(leg.get("trip") or "").upper(), str(mv.get("trip") or "").upper()
    if not lt or not (lt == mt or lt[:5] == mt[:5] and (len(lt) == 5 or len(mt) == 5)):
        return False
    d = str(leg.get("day") or "").upper()
    if d and d != leg_day(mv.get("start")):
        return False
    s = leg.get("side") or ""
    return not s or s == mv.get("side")


def explain(mvs, decided):
    """Mark open moves the request path already pushed (decided: [{key, legs, filed, seen}], Approved only) or that are
    a pairing change, not a trade (a drop and an add of the same pairing, the same start, the same day). Returns the
    moves marked."""
    hit = []
    live = [m for m in mvs if m.get("state") == "open"]
    for d in decided or []:
        legs = d.get("legs") or []
        if legs:
            for leg in legs:
                m = next((m for m in live if m["state"] == "open" and leg_matches(leg, m)), None)
                if m:
                    m.update(state="explained", by=d.get("key") or "request")
                    hit.append(m)
            continue
        a, b = _utc(d.get("filed")), _utc(d.get("seen"))
        if not (a and b):
            continue
        for m in live:
            t = _utc(m.get("t"))
            if m["state"] == "open" and t and a - LEGLESS_SLACK <= t <= b + LEGLESS_SLACK:
                m.update(state="explained", by=d.get("key") or "request")
                hit.append(m)
    for m in live:
        if m["state"] != "open" or m["side"] != "drop":
            continue
        twin = next((x for x in live if x["state"] == "open" and x["side"] == "add" and x["trip"][:5] == m["trip"][:5]
                     and x["start"] == m["start"] and x["day"] == m["day"]), None)
        if twin:
            m.update(state="explained", by="pairing change")
            twin.update(state="explained", by="pairing change")
            hit += [m, twin]
    return hit


def match_pending(mvs, rows):
    """[(row, [moves])] for each Pending / Processing request row whose every leg is an open move on the schedule, with
    at least one leg (a Swap or Trade: something given and something taken)."""
    out = []
    for r in rows or []:
        legs = r.get("legs") or []
        if not legs:
            continue
        used, ok = [], True
        for leg in legs:
            m = next((m for m in mvs if m.get("state") == "open" and m not in used and leg_matches(leg, m)), None)
            if not m:
                ok = False
                break
            used.append(m)
        sides = {m["side"] for m in used}
        if ok and used and (sides == {"drop", "add"} or r.get("type") in ("Add", "Drop")):
            out.append((r, used))
    return out


def groups(mvs):
    """{HST day: [open moves]} for days with at least one trip dropped and one added."""
    by = {}
    for m in mvs or []:
        if m.get("state") == "open" and m.get("day"):
            by.setdefault(m["day"], []).append(m)
    return {d: g for d, g in by.items() if {m["side"] for m in g} == {"drop", "add"}}


def settled(group, last_read_iso, now_iso, priced):
    """True when a schedule read after the group's newest move brought nothing new for its day and every trip taken
    has its credit read (priced(move) True), or PRICE_WAIT has passed since that move."""
    newest = max((m.get("at") or "" for m in group), default="")
    if not last_read_iso or last_read_iso <= newest:
        return False
    if all(priced(m) for m in group if m["side"] == "add"):
        return True
    t, now = _utc(newest), _utc(now_iso)
    return bool(t and now and now - t >= PRICE_WAIT)


def group_key(day, group):
    h = hashlib.sha256("|".join(sorted(m["id"] for m in group)).encode()).hexdigest()[:10]
    return f"sched:{day}:{h}"


def group_event(day, group):
    """The request_decided fields of a trade seen on the schedule only: type Trade, status Approved, given trips first,
    stamped with FLICA's time of the last change (HST MM/DD HH:MM)."""
    drops = sorted((m for m in group if m["side"] == "drop"), key=lambda m: (m["t"], m["start"]))
    adds = sorted((m for m in group if m["side"] == "add"), key=lambda m: (m["t"], m["start"]))
    last = _utc(max(m["t"] for m in group)).astimezone(HST)
    legs = [{"trip": m["trip"], "day": leg_day(m["start"]), "side": m["side"],
             "seat": (m.get("rec") or {}).get("seat") or ""} for m in drops + adds]
    words = lambda ms: ", ".join(f"{m['trip']} {leg_day(m['start'])}" for m in ms)  # noqa: E731
    return {"key": group_key(day, group), "date": f"{last:%m/%d}", "time": f"{last:%H:%M}", "type": "Trade",
            "status": "Approved", "trips": [m["trip"] for m in drops + adds], "legs": legs,
            "detail": f"gave {words(drops)}; took {words(adds)} (seen on the FLICA schedule; no request on file)",
            "reason": "",
            "source": "schedule", "changes": list(dict.fromkeys(m["upd"] for m in sorted(group, key=lambda x: x["t"])
                                                                if m.get("upd")))}
