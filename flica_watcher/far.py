"""FAR 117 screen for a pot pairing against Ryan's own trips. Pure, no I/O (0.3.8).

What it checks (14 CFR 117, unaugmented, all trips start and end at HNL so times are HST):
- 117.25(e): at least 10 h rest before and after the pickup (release = last block-in + 15 min).
- 117.25(b): 30 consecutive hours free from duty in the 168 h before each report it affects.
- 117.23(b): flight time at most 100 h in any 672 h (trip block counted whole).
It also notes the company 11 h minimum rest (Hark's rules, bid line month) when FAR passes.
Not checked: cumulative FDP 60 h / 168 h and 190 h / 672 h (needs per-duty-day times).
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
