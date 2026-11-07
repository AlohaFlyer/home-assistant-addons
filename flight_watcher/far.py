"""FAR 117 and PWA rest legality of a pairing against Ryan's own trips. Pure, no I/O (0.3.8, 1.4.6, FW-0039).

What it checks (14 CFR 117, unaugmented, all trips start and end at HNL so times are HST), per duty period:
- 117.25(e): at least 10 h rest before and after the pairing (release = last block-in + 15 min, PWA 2.19.b).
- 117.25(b): 30 consecutive hours free from duty in the 168 h before each FDP it affects.
- 117.23(b)(1): flight time at most 100 h in any 672 h.
- 117.23(c)(1) and (2): FDP at most 60 h in any 168 h and 190 h in any 672 h.
- PWA 10.E.1.a: 11 h rest in domicile; PWA 2.19.b: a release 30 min after block-in when clearing customs.
legality() (1.4.6, the Recall / Over 75 miss check) says OK, NO or '?' (data not on file), never guessing.
screen() (FW-0039) is the FAR column of pot, Tradeboard and finds rows: the same checks, in the column's short words
(a pickup that broke 117.23(c) read OK under the old far_check, which is gone). The 11 h PWA rest stays a note there
('OK (CBA rest 10:30)'), as before. The pairing's own FDP is built legal by scheduling and is not re-checked.
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


def _rest(side, m, gap):
    """FAR 117.25(e) 10 h rest before every FDP; PWA 10.E.1.a 11 h rest in domicile (every trip here starts and
    ends in HNL, so the rest on either side of the pairing is domicile rest). gap runs from the release (block-in
    + 15 min); with customs (PWA 2.19.b) the rest can be 15 min shorter. One check dict: far / pwa 'OK' | 'NO' | '?'
    (each rule on its own, for screen()), res (both together, for legality()) and the line legality() reports."""
    worst = gap - CUSTOMS
    guess = bool(m.get("approx") or m.get("unknown_line"))
    if guess:  # the neighbour's release is its latest possible one, so gap is the least rest it can leave
        far = "OK" if worst >= REST else "?"
        pwa = "OK" if worst >= CBA_REST else "?"
    else:
        far = "NO" if gap < REST else "?" if worst < REST else "OK"
        pwa = "NO" if gap < CBA_REST else "?" if worst < CBA_REST else "OK"
    if pwa == "OK":
        res, line = "OK", f"rest {_hh(_hrs(gap))} {side} ({REST_REFS})"
    elif guess:
        res, line = "?", f"rest {side}: {_what(m)} not on file, at least {_hh(_hrs(worst))} ({REST_REFS})"
    elif far == "NO":
        res, line = "NO", f"rest {_hh(_hrs(gap))} {side} ({m['label']}), under 10 h (FAR 117.25(e))"
    elif pwa == "NO":
        res, line = "NO", f"rest {_hh(_hrs(gap))} {side} ({m['label']}), under 11 h domicile rest (PWA 10.E.1.a)"
    else:
        res, line = "?", (f"rest {_hh(_hrs(gap))} {side} ({m['label']}) is under 11 h if that release was 30 min after "
                          f"block-in for customs (PWA 2.19.b, PWA 10.E.1.a)")
    return {"kind": "rest", "side": side, "gap": gap, "worst": worst, "far": far, "pwa": pwa, "res": res,
            "line": line}


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
    cap; only those windows are tried. Returns (result 'OK' | 'NO' | '?', line, hours: the failing window's when NO,
    else the most it can be)."""
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
        return "NO", f"{what} {_hh(fail[0])} h in {n} h, over {lim} h ({ref})", fail[0]
    if fail:
        return "?", (f"{what} in {n} h is over {lim} h even without the pairing ({ref}): the line on file looks "
                     f"incomplete"), fail[0]
    if best_hi > lim:
        guess = sorted({_what(s[6]) for s in segs if not s[4] and worst_w and _ov(s[0], s[1], *worst_w) > 0})
        return "?", (f"{what} in {n} h may pass {lim} h ({ref}): {_hh(best_lo)} h known, up to {_hh(best_hi)} h; "
                     f"{', '.join(guess) or 'some times'} not on file"), best_hi
    return "OK", f"{what} at most {_hh(best_hi)} of {lim} h in {n} h ({ref})", best_hi


CUM = ((H672, FT_672, "flight time", "FAR 117.23(b)(1)", "FT"),
       (H168, FDP_168, "FDP", "FAR 117.23(c)(1)", "FDP"),
       (H672, FDP_672, "FDP", "FAR 117.23(c)(2)", "FDP"))


def _checks(new, mine):
    """Every check of the new pairing against Ryan's trips, in report order: [{kind, res 'OK' | 'NO' | '?', line,
    ...}]. kind 'overlap' (one per trip it may overlap; when one surely overlaps, nothing else is checked), 'rest'
    (before, after: _rest), '30h' (FAR 117.25(b)) and 'cum' (FAR 117.23(b)(1), (c)(1), (c)(2): short, n, hours)."""
    out = []
    for m in mine:
        if m["report"] < new["release"] and new["report"] < m["release"]:
            if m.get("approx") or m.get("unknown_line"):
                out.append({"kind": "overlap", "res": "?", "line": f"may overlap {m['label']}: {_what(m)} not on file"})
            else:
                out.append({"kind": "overlap", "res": "NO", "line": f"overlaps {m['label']}"})
    if any(c["res"] == "NO" for c in out):
        return out
    prev = [m for m in mine if m["release"] <= new["report"]]
    nxt = [m for m in mine if m["report"] >= new["release"]]
    if prev:
        m = max(prev, key=lambda x: x["release"])
        out.append(_rest("before", m, new["report"] - m["release"]))
    if nxt:
        m = min(nxt, key=lambda x: x["report"])
        out.append(_rest("after", m, m["report"] - new["release"]))
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
        out.append({"kind": "30h", "res": "NO", "line": f"no 30 h free from duty in the 168 h before the duty at "
                                                       f"{no30:%b} {no30.day} {no30:%H:%M} (FAR 117.25(b))"})
    elif maybe30:
        guess = sorted({_what(t) for t in trips if not _sure(t) and any(
            s < maybe30[0] and e > maybe30[0] - H168 for s, e, _ in t["duties"])})
        out.append({"kind": "30h", "res": "?", "line": (
            f"30 h free in the 168 h before {maybe30[0]:%b} {maybe30[0].day} {maybe30[0]:%H:%M} not provable: "
            f"{', '.join(guess) or 'some duty times'} not on file (FAR 117.25(b))")})
    else:
        out.append({"kind": "30h", "res": "OK", "line": "30 h free in every 168 h (FAR 117.25(b))"})
    # FAR 117.23(b)(1) 100 h flight time in 672 h; 117.23(c) FDP 60 h in 168 h and 190 h in 672 h
    for span, lim, what, ref, short in CUM:
        res, line, h = _cum(trips, new, span, lim, what, ref)
        out.append({"kind": "cum", "res": res, "line": line, "short": short, "n": int(span.total_seconds() // 3600),
                    "hours": h})
    return out


def legality(new, mine):
    """FAR 117 and PWA rest legality of the new pairing against Ryan's trips as he held them (both as described
    above). Returns {result: 'OK' | 'NO' | '?', issues: [broken rules], unknown: [checks that need data not on file],
    notes: [checks passed], summary}. Every line cites its rule."""
    issues, unknown, notes = [], [], []
    for c in _checks(new, mine):
        (issues if c["res"] == "NO" else unknown if c["res"] == "?" else notes).append(c["line"])
    result = "NO" if issues else "?" if unknown else "OK"
    return {"result": result, "issues": issues, "unknown": unknown, "notes": notes,
            "summary": "; ".join(issues or unknown or notes)}


def screen(new, mine):
    """FW-0039: the FAR column of a pot, Tradeboard or finds row: legality()'s checks (FAR 117.25(e), 117.25(b),
    117.23(b)(1), 117.23(c)(1) and (2), PWA 10.E.1.a, 2.19.b) in the column's short words. Returns {far, why, result}:
    far is 'Conflict', the broken rules joined by ' · ' ('Rest 8:00 before', 'No 30h/168h', 'FT 105h/672h',
    'FDP 65h/168h', 'FDP 191h/672h'), '?' when a FAR check needs data not on file (never OK), else 'OK', or
    'OK (CBA rest 10:30)' when FAR is met but the PWA 10.E.1.a 11 h domicile rest is short ('10:50?' when only a
    customs release, PWA 2.19.b, or a neighbour's unknown times can make it short). why: the lines behind it, each
    citing its rule ('' when OK). result: legality()'s 'OK' | 'NO' | '?'."""
    cs = _checks(new, mine)
    result = "NO" if any(c["res"] == "NO" for c in cs) else "?" if any(c["res"] == "?" for c in cs) else "OK"
    probs, unk, cba, why_no, why_cba = [], [], [], [], []
    for c in cs:
        k, res = c["kind"], c["res"]
        if k == "rest":
            if c["far"] == "NO":
                probs.append(f"Rest {_hm(c['gap'])} {c['side']}")
                why_no.append(c["line"])
            elif c["far"] == "?":
                unk.append(c["line"] if res == "?" else  # known times: only a customs release can make it short
                           f"rest {_hh(_hrs(c['gap']))} {c['side']} is under 10 h if that release was 30 min after "
                           f"block-in for customs (FAR 117.25(e), PWA 2.19.b)")
            elif c["pwa"] != "OK":
                cba.append(f"CBA rest {_hm(c['gap'])}" if c["pwa"] == "NO" else f"CBA rest {_hm(c['worst'])}?")
                why_cba.append(c["line"])
        elif res == "NO":
            probs.append("Conflict" if k == "overlap" else "No 30h/168h" if k == "30h" else
                         f"{c['short']} {c['hours']:.0f}h/{c['n']}h")
            why_no.append(c["line"])
        elif res == "?":
            unk.append(c["line"])
    if probs:
        far = "Conflict" if "Conflict" in probs else " · ".join(dict.fromkeys(probs))
        return {"far": far, "why": "; ".join(why_no), "result": result}
    if unk:
        return {"far": "?", "why": "; ".join(unk + why_cba), "result": result}
    return {"far": "OK" + (f" ({cba[0]})" if cba else ""), "why": "; ".join(why_cba), "result": result}
