"""Recall / Over 75 miss check (0.9.2, Ryan, 2026-11-05). Pure, no I/O.

Hark reads the daily HNL recall list from Alaska Flight Ops SharePoint (PingID) and posts it to the Watcher.
Each row says who got a Recall or an Over 75 award that day. This module decides whether Ryan was passed over:

- PWA 22.G.2.d: Over 75 is offered to Reserve Run pilots who give up days off, in seniority order (pay per 4.N).
- PWA 22.G.2.e: Recall goes to volunteers in seniority order who are legal without being removed from a Flight
  Grouping or Reserve day (200% pay per 22.E and 4.M). 22.G.2.f (must be removed from a trip) and 22.G.2.g
  (must be removed from vacation) come after it, so a junior pilot who was clean under (e) beats Ryan there.
- PWA 22.G.2.j/k: junior manning is involuntary and goes in reverse seniority; it is never a miss for Ryan.
- PWA 10.E.1.a: 11 h rest at domicile. FAR 117.25(e) 10 h rest, 117.25(b) 30 h free in 168, 117.23(b)(1) 100 h
  in 672 (far.py).

A row is MISSED when a pilot junior to Ryan got it, the pairing fits Ryan's line with no trip, vacation or
blocked day in the way, and FAR / PWA rest pass with known times. POSSIBLE when it would have needed a removal
(22.G.2.f/g) or a time is unknown. NO otherwise, with the reason."""
from datetime import date, datetime, timedelta

from far import far_check, window

KINDS = {"recall": ("Recall", "22.G.2.e, 22.E, 4.M (200%)"),
         "o75": ("Over 75", "22.G.2.d, 4.N"),
         "junior": ("Junior manning", "22.G.2.j/k")}


def _d(s):
    try:
        return date.fromisoformat(str(s)[:10])
    except ValueError:
        return None


def _hm(m):
    m = int(m)
    return f"{(m // 60) % 24:02d}:{m % 60:02d}"


def pairing_window(row, details):
    """(start, end, report, last_arr, block_h) for a recall row, from the row itself or the month's package."""
    start = _d(row.get("date"))
    det = (details or {}).get(str(row.get("pairing") or "").rstrip("ABCDEFGHJ")) or (details or {}).get(row.get("pairing")) or {}
    report = row.get("report") or det.get("report")
    days = int(row.get("days") or det.get("rel_days") or 1)
    last_arr, end = row.get("last_arr"), _d(row.get("end"))
    duties = det.get("duties") or []
    if not last_arr and duties:
        arr = max(d["arr"] for d in duties)
        last_arr, end = _hm(arr), start + timedelta(days=arr // 1440) if start else None
    if not end and start:
        end = start + timedelta(days=days - 1)
    blk = row.get("blk") or det.get("block") or ""
    try:
        h, m = str(blk).split(":")[:2]
        blk_h = int(h) + int(m) / 60
    except ValueError:
        blk_h = 0
    return start, end, report, last_arr, blk_h


def _overlaps(a, b, c, d):
    return a <= d and c <= b


def evaluate(row, me, sched_items, own_trips, blocked, details):
    """One verdict dict for one recall-list row. me = {sen, seat, o75}."""
    kind = (row.get("kind") or "").lower()
    out = {"date": row.get("date"), "kind": kind, "pairing": row.get("pairing") or "", "sen": row.get("sen"),
           "pilot": row.get("pilot") or "", "seat": (row.get("seat") or "FO").upper(), "verdict": "NO", "why": [], "refs": []}
    lab, ref = KINDS.get(kind, ("", ""))
    if ref:
        out["refs"].append(f"PWA {ref}")
    if kind not in ("recall", "o75") or not row.get("pairing"):
        out["why"].append("no award to check" if kind not in KINDS else f"{lab}: involuntary, never a miss")
        return out
    if out["seat"] != (me.get("seat") or "FO").upper():
        out["why"].append(f"{out['seat']} seat, you bid {me.get('seat') or 'FO'}")
        return out
    if kind == "o75" and not me.get("o75", True):
        out["why"].append("Over 75 is for Reserve Run pilots (22.G.2.d); you are not on reserve")
        return out
    try:
        their, mine = int(row.get("sen")), int(me.get("sen"))
    except (TypeError, ValueError):
        out["verdict"] = "POSSIBLE"
        out["why"].append("seniority unknown")
        return out
    if their < mine:
        out["why"].append(f"went to #{their}, senior to you (#{mine})")
        return out
    out["why"].append(f"went to #{their}, junior to you (#{mine})")
    s, e, rep, arr, blk = pairing_window(row, details)
    if not s:
        out["verdict"] = "POSSIBLE"
        out["why"].append("date unreadable")
        return out
    days = [(s + timedelta(days=i)).isoformat() for i in range((e - s).days + 1)]
    out.update(start=s.isoformat(), end=e.isoformat(), report=rep or "", last_arr=arr or "")
    hit_block = [d for d in days if d in (blocked or [])]
    if hit_block:
        out["why"].append(f"you blocked {', '.join(hit_block)} as unavailable")
        return out
    trips, vac = [], []
    for it in sched_items or []:
        a, b = _d(it.get("start")), _d(it.get("end"))
        if not (a and b and _overlaps(s, e, a, b)):
            continue
        (vac if it.get("trip") == "VAC" else trips).append(it.get("trip"))
    if trips:  # 22.G.2.f only reaches you after every clean 22.G.2.e volunteer; Over 75 (d) has no removal step
        out["why"].append(f"you were on {', '.join(trips)}; removal (22.G.2.f) comes after clean junior volunteers (22.G.2.e)")
        return out
    if vac:
        out["why"].append("you were on vacation; removal (22.G.2.g) comes after 22.G.2.e and f")
        return out
    w = window(s, e, rep, arr)
    if not w:
        out["verdict"] = "POSSIBLE"
        out["why"].append("pairing times unknown; upload the month's pairings PDF or add report and arrival")
        return out
    mine_w = []
    for it in sched_items or []:
        if it.get("trip") == "VAC" or not it.get("trip"):
            continue
        t = (own_trips or {}).get(f"{it['trip']}|{it['start']}") or {}
        a, b = _d(it["start"]), _d(it["end"])
        ow = window(a, b, t.get("report"), t.get("last_arr"))
        if ow:
            mine_w.append((ow[0], ow[1], _h(t.get("blk"))))
        elif a and b:
            mine_w.append((datetime.combine(a, datetime.min.time()), datetime.combine(b, datetime.max.time()), 0, True))
    far = far_check((w[0], w[1], blk), mine_w)
    out["far"] = far
    out["refs"] += ["PWA 10.E.1.a", "FAR 117.25(b)(e)", "FAR 117.23(b)(1)"]
    if far.startswith("OK"):
        out["verdict"] = "MISSED"
        out["why"].append(f"open, legal (FAR 117 and PWA rest: {far})")
    elif far == "?":
        out["verdict"] = "POSSIBLE"
        out["why"].append("a neighbouring trip's times are unknown")
    else:
        out["why"].append(f"not legal: {far}")
    return out


def _h(blk):
    try:
        h, m = str(blk).split(":")[:2]
        return int(h) + int(m) / 60
    except ValueError:
        return 0


def narrative(v, me, name="", emp=""):
    """CCR narrative Ryan reviews and edits on the Recall/O75 tab before anything is filed."""
    lab, ref = KINDS.get(v.get("kind"), ("Recall", ""))
    who = f"{name} (#{me.get('sen')})" if name else f"I (seniority #{me.get('sen')})"
    lines = [
        f"On {v.get('date')}, {lab} pairing {v.get('pairing')} ({v.get('start', v.get('date'))} to {v.get('end', v.get('date'))}, "
        f"report {v.get('report') or 'per pairing'}) was awarded to a {v.get('seat')} with seniority #{v.get('sen')}, junior to me.",
        f"{who} was available on those days with no Flight Grouping, Reserve day or vacation in the way, and was legal "
        f"under FAR 117 (117.25(b) 30 h free in 168 h, 117.25(e) 10 h rest, 117.23(b)(1) 100 h in 672 h) and PWA 10.E.1.a "
        f"(11 h domicile rest): {v.get('far') or 'see schedule'}.",
        f"Under PWA {ref}, the pairing should have been offered to me before a junior pilot. I request {('200% pay per 4.M' if v.get('kind') == 'recall' else 'pay per 4.N in addition to guarantee')} "
        f"for the pairing as compensation for the missed award.",
    ]
    if emp:
        lines.append(f"Employee #{emp}.")
    return "\n\n".join(lines)


def check_day(rows, me, sched_items, own_trips, blocked, details):
    return [evaluate(r, me, sched_items, own_trips, blocked, details) for r in rows or []]
