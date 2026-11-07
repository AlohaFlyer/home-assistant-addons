"""FAR 117 screen for a pot pairing against Ryan's own trips. Pure, no I/O (0.3.8).

What it checks (14 CFR 117, unaugmented, all trips start and end at HNL so times are HST):
- 117.25(e): at least 10 h rest before and after the pickup (release = last block-in + 15 min).
- 117.25(b): 30 consecutive hours free from duty in the 168 h before each report it affects.
- 117.23(b): flight time at most 100 h in any 672 h (trip block counted whole).
It also notes the company 11 h minimum rest (Hark's rules, bid line month) when FAR passes.
far_check (the pot and Tradeboard screen) does not check cumulative FDP 60 h / 168 h and 190 h / 672 h.
legality() (1.4.6, the Recall / Over 75 miss check) checks all of the above per duty period, adds FAR 117.23(c)
FDP 60 h in 168 h and 190 h in 672 h and PWA 10.E.1.a 11 h domicile rest, and says '?' instead of guessing.
The pairing's own FDP is built legal by scheduling and is not re-checked.
"""
from datetime import datetime, time, timedelta

REST = timedelta(hours=10)
CBA_REST = timedelta(hours=11)
DEBRIEF = timedelta(minutes=15)
H168, H672 = timedelta(hours=168), timedelta(hours=672)


def _t(hhmm):
    try:
        h, m = str(hhmm).replace(".", ":").split(":")[:2]
        return time(int(h), int(m))
    except (ValueError, AttributeError):
        return None


def window(start, end, report, last_arr):
    """(report_dt, release_dt) from dates and HH:MM strings, or None when a time is missing."""
    r, a = _t(report), _t(last_arr)
    if not (start and r and a):
        return None
    rep = datetime.combine(start, r)
    rel = datetime.combine(end or start, a) + DEBRIEF
    if rel <= rep:
        rel += timedelta(days=1)
    return rep, rel


def _hm(td):
    m = int(td.total_seconds() // 60)
    return f"{m // 60}:{m % 60:02d}"


def free_30_in_168(duties, at):
    """True when the 168 h ending at `at` holds 30 consecutive hours with no duty."""
    ws = at - H168
    busy = sorted((max(r, ws), min(e, at)) for r, e, _ in duties if e > ws and r < at)
    cur = ws
    for r, e in busy:
        if r - cur >= timedelta(hours=30):
            return True
        cur = max(cur, e)
    return at - cur >= timedelta(hours=30)


def far_check(new, mine):
    """new: (report, release, block_hours). mine: list of the same for Ryan's trips; an entry may
    carry approx=True as a 4th item when its times are whole-day guesses. Returns 'OK', 'OK (CBA
    rest 10:40)', a ' · '-joined list of problems, 'Conflict' or '?'."""
    nr, ne, nb = new[:3]
    for m in mine:
        if m[0] < ne and nr < m[1]:
            return "Conflict"
    issues, notes = [], []
    prev = [m for m in mine if m[1] <= nr]
    nxt = [m for m in mine if m[0] >= ne]
    if prev:
        p = max(prev, key=lambda m: m[1])
        if len(p) > 3 and p[3]:
            return "?"
        gap = nr - p[1]
        if gap < REST:
            issues.append(f"Rest {_hm(gap)} before")
        elif gap < CBA_REST:
            notes.append(f"CBA rest {_hm(gap)}")
    if nxt:
        n = min(nxt, key=lambda m: m[0])
        if len(n) > 3 and n[3]:
            return "?"
        gap = n[0] - ne
        if gap < REST:
            issues.append(f"Rest {_hm(gap)} after")
        elif gap < CBA_REST:
            notes.append(f"CBA rest {_hm(gap)}")
    duties = [m[:3] for m in mine] + [(nr, ne, nb)]
    points = [nr] + [m[0] for m in mine if nr < m[0] <= ne + H168]
    if not all(free_30_in_168(duties, p) for p in points):
        issues.append("No 30h/168h")
    for p in [ne] + [m[1] for m in mine if ne < m[1] <= ne + H672]:
        ft = sum(b or 0 for r, e, b in duties if p - H672 < e <= p)
        if ft > 100:
            issues.append(f"FT {ft:.0f}h/672h")
            break
    if issues:
        return " · ".join(issues)
    return "OK" + (f" ({notes[0]})" if notes else "")


# ---------------------------------------------------------------- 1.4.6: full legality for the recall miss check
# legality() judges a pairing against Ryan's trips as he held them (recall.py builds both). A trip is a dict:
#   label; report, release (naive HST datetimes; release = last block-in + 15 min, PWA 2.19.b);
#   duties [(duty start, block-in, block hours or None)]: one per duty period when `exact`, else one span for the
#   whole trip (report to last block-in), or whole days when only the dates are known (`approx`);
#   flying (False for SCR, SICK, training and other day codes: duty, but no flight time or FDP);
#   ft (optional) [(start, end, block hours)]: the trip's flight time as one span when its duty blocks are not known;
#   unknown_line (True for a span of days where the line held then is not on file).
# PWA 2.19.b (Duty Period, International): starts 1:00 before the first departure in domicile, 1:15 out of domicile;
# ends 15 min after block-in, 30 min when clearing customs. FAR 117.3: an FDP runs from report to the last block-in.
# Every check runs twice: with what is surely known (a NO needs that to fail) and with the worst case of every guess
# (an OK needs that to pass). Anything between is unknown ('?'), never a NO and never an OK.
FT_672, FDP_168, FDP_672 = 100, 60, 190
CUSTOMS = timedelta(minutes=15)  # PWA 2.19.b: 30 min after block-in instead of 15 when clearing customs
LEGAL_REFS = ["FAR 117.25(e)", "PWA 10.E.1.a", "FAR 117.25(b)", "FAR 117.23(b)(1)", "FAR 117.23(c)(1)",
              "FAR 117.23(c)(2)", "PWA 2.19.b"]
REST_REFS = "FAR 117.25(e) 10 h, PWA 10.E.1.a 11 h in domicile"


def _hh(h):
    m = int(round(h * 60))
    return f"{m // 60}:{m % 60:02d}"


def _hrs(td):
    return td.total_seconds() / 3600


def _ov(a, b, c, d):
    """Hours of [a, b] that fall inside [c, d]."""
    return max(0.0, _hrs(min(b, d) - max(a, c)))


def _sure(t):
    """True when the trip's duty periods are known (not a whole-trip or whole-day guess)."""
    return bool(t.get("exact")) and not t.get("approx") and not t.get("unknown_line")


def _busy(trips, sure):
    """Duty intervals for 30 h free in 168 h. sure: only known duty periods, released 15 min after block-in;
    else every trip, guesses whole, released 30 min after block-in (customs)."""
    out = []
    for t in trips:
        if sure and not _sure(t):
            continue
        for s, e, _ in t["duties"]:
            out.append((s, e + DEBRIEF + (timedelta(0) if sure else CUSTOMS), 0))
    return out


def _starts(t):
    """FDP start times to test 30 h free in 168 h before. A guessed span is busy end to end in the worst case and
    the latest possible start is the worst one (the 168 h window then holds the least free time), so its end."""
    if _sure(t):
        return [s for s, _, _ in t["duties"]]
    return [t["report"], t["duties"][-1][1]]


def _what(t):
    """What is missing for a guessed trip: its duty times, or the line itself for days not on file."""
    return t["label"] if t.get("unknown_line") else f"{t['label']} times"


def _rest(side, m, gap, issues, unknown, notes):
    """FAR 117.25(e) 10 h rest before every FDP; PWA 10.E.1.a 11 h rest in domicile (every trip here starts and
    ends in HNL, so the rest on either side of the pairing is domicile rest). gap runs from the release (block-in
    + 15 min); with customs (PWA 2.19.b) the rest can be 15 min shorter."""
    worst = gap - CUSTOMS
    if worst >= CBA_REST:
        notes.append(f"rest {_hh(_hrs(gap))} {side} ({REST_REFS})")
    elif m.get("approx") or m.get("unknown_line"):
        unknown.append(f"rest {side}: {_what(m)} not on file, at least {_hh(_hrs(worst))} ({REST_REFS})")
    elif gap < REST:
        issues.append(f"rest {_hh(_hrs(gap))} {side} ({m['label']}), under 10 h (FAR 117.25(e))")
    elif gap < CBA_REST:
        issues.append(f"rest {_hh(_hrs(gap))} {side} ({m['label']}), under 11 h domicile rest (PWA 10.E.1.a)")
    else:
        unknown.append(f"rest {_hh(_hrs(gap))} {side} ({m['label']}) is under 11 h if that release was 30 min after "
                       f"block-in for customs (PWA 2.19.b, PWA 10.E.1.a)")


def _segments(t, what):
    if t.get("flying") is False:  # SCR, SICK, training...: no flight time, no FDP
        return []
    return t["duties"] if what == "FDP" else (t.get("ft") or t["duties"])


def _cum(trips, new, span, lim, what, ref):
    """FAR 117.23: the most flight time / FDP hours in any `span` window that holds part of the new pairing.
    sure (lo): FDP = overlap of known duty periods; flight time = block of every span wholly inside the window.
    worst (hi): FDP = overlap of every span; flight time = the lesser of each span's block (its length when the block
    is unknown) and its overlap. Both are piecewise linear in the window's position, so their maxima are at the
    windows that start at a span's start or at its end less its cap, or end at a span's end or at its start plus its
    cap; only those windows are tried."""
    lo_h, hi_h = new["report"] - span, new["release"] + span
    segs = []  # (start, end, cap h, block h or None, sure, is_new, trip)
    for t in trips:
        for s, e, blk in _segments(t, what):
            if e <= lo_h or s >= hi_h:
                continue
            dur = _hrs(e - s)
            cap = dur if what == "FDP" or blk is None else min(blk, dur)
            segs.append((s, e, cap, blk, _sure(t), t is new, t))
    cands = set()
    for s, e, cap, _, _, _, _ in segs:
        c = timedelta(hours=cap)
        for x in (s, e - c):
            cands.add((x, x + span))
        for y in (e, s + c):
            cands.add((y - span, y))
    best_lo, best_hi, worst_w, fail = 0.0, 0.0, None, None
    for a, b in sorted(cands):
        if not (a < new["release"] and new["report"] < b):
            continue
        lo = hi = lo_mine = 0.0
        for s, e, cap, blk, sure, is_new, t in segs:
            ov = _ov(s, e, a, b)
            if ov <= 0:
                continue
            if what == "FDP":
                hi += ov
                add = ov if sure else 0.0
            else:
                hi += min(cap, ov)
                add = blk if (blk is not None and s >= a and e <= b and not t.get("approx")
                              and not t.get("unknown_line")) else 0.0
            lo += add
            lo_mine += 0.0 if is_new else add
        if hi > best_hi:
            best_hi, worst_w = hi, (a, b)
        best_lo = max(best_lo, lo)
        if lo > lim and fail is None:
            fail = (lo, lo_mine)
    n = int(span.total_seconds() // 3600)
    if fail and fail[1] <= lim:
        return "NO", f"{what} {_hh(fail[0])} h in {n} h, over {lim} h ({ref})"
    if fail:
        return "?", (f"{what} in {n} h is over {lim} h even without the pairing ({ref}): the line on file looks "
                     f"incomplete")
    if best_hi > lim:
        guess = sorted({_what(s[6]) for s in segs if not s[4] and worst_w and _ov(s[0], s[1], *worst_w) > 0})
        return "?", (f"{what} in {n} h may pass {lim} h ({ref}): {_hh(best_lo)} h known, up to {_hh(best_hi)} h; "
                     f"{', '.join(guess) or 'some times'} not on file")
    return "OK", f"{what} at most {_hh(best_hi)} of {lim} h in {n} h ({ref})"


def legality(new, mine):
    """FAR 117 and PWA rest legality of the new pairing against Ryan's trips as he held them (both as described
    above). Returns {result: 'OK' | 'NO' | '?', issues: [broken rules], unknown: [checks that need data not on file],
    notes: [checks passed], summary}. Every line cites its rule."""
    issues, unknown, notes = [], [], []
    for m in mine:
        if m["report"] < new["release"] and new["report"] < m["release"]:
            if m.get("approx") or m.get("unknown_line"):
                unknown.append(f"may overlap {m['label']}: {_what(m)} not on file")
            else:
                issues.append(f"overlaps {m['label']}")
    if issues:
        return {"result": "NO", "issues": issues, "unknown": unknown, "notes": notes, "summary": "; ".join(issues)}
    prev = [m for m in mine if m["release"] <= new["report"]]
    nxt = [m for m in mine if m["report"] >= new["release"]]
    if prev:
        m = max(prev, key=lambda x: x["release"])
        _rest("before", m, new["report"] - m["release"], issues, unknown, notes)
    if nxt:
        m = min(nxt, key=lambda x: x["report"])
        _rest("after", m, m["report"] - new["release"], issues, unknown, notes)
    # FAR 117.25(b): 30 consecutive hours free from all duty in the 168 h before every FDP the pairing touches
    trips = mine + [new]
    hi_all, lo_all, lo_mine = _busy(trips, False), _busy(trips, True), _busy(mine, True)
    own_pts = set(_starts(new)) if _sure(new) else {new["report"]}  # FDP starts of the pairing that are certain
    pts = sorted({p for t in trips for p in _starts(t) if new["report"] <= p <= new["release"] + H168})
    no30, maybe30 = None, []
    for p in pts:
        if free_30_in_168(hi_all, p):
            continue
        # sure NO: fails with only known duty; at a later trip's start, only if that trip was fine without the pairing
        if not free_30_in_168(lo_all, p) and (p in own_pts or free_30_in_168(lo_mine, p)):
            no30 = no30 or p
        else:
            maybe30.append(p)
    if no30:
        issues.append(f"no 30 h free from duty in the 168 h before the duty at {no30:%b} {no30.day} {no30:%H:%M} (FAR 117.25(b))")
    elif maybe30:
        guess = sorted({_what(t) for t in trips if not _sure(t) and any(
            s < maybe30[0] and e > maybe30[0] - H168 for s, e, _ in t["duties"])})
        unknown.append(f"30 h free in the 168 h before {maybe30[0]:%b} {maybe30[0].day} {maybe30[0]:%H:%M} not provable: "
                       f"{', '.join(guess) or 'some duty times'} not on file (FAR 117.25(b))")
    else:
        notes.append("30 h free in every 168 h (FAR 117.25(b))")
    # FAR 117.23(b)(1) 100 h flight time in 672 h; 117.23(c) FDP 60 h in 168 h and 190 h in 672 h
    for span, lim, what, ref in ((H672, FT_672, "flight time", "FAR 117.23(b)(1)"),
                                 (H168, FDP_168, "FDP", "FAR 117.23(c)(1)"),
                                 (H672, FDP_672, "FDP", "FAR 117.23(c)(2)")):
        res, line = _cum(trips, new, span, lim, what, ref)
        (issues if res == "NO" else unknown if res == "?" else notes).append(line)
    result = "NO" if issues else "?" if unknown else "OK"
    return {"result": result, "issues": issues, "unknown": unknown, "notes": notes,
            "summary": "; ".join(issues or unknown or notes)}
