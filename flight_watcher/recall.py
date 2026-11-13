"""Recall / Over 75 miss check (0.9.2, Ryan, 2026-11-05). Pure, no I/O.

Hark reads the daily HNL recall list from Alaska Flight Ops SharePoint (PingID) and posts it to the Watcher.
Each row says who got a Recall or an Over 75 award that day. This module decides whether Ryan was passed over:

- PWA 22.G.2.d: Over 75 is offered to Reserve Run pilots who give up days off, in seniority order (pay per 4.N).
- PWA 22.G.2.e: Recall goes to volunteers in seniority order who are legal without being removed from a Flight
  Grouping or Reserve day (200% pay per 22.E and 4.M). 22.G.2.f (must be removed from a trip) and 22.G.2.g
  (must be removed from vacation) come after it, so a junior pilot who was clean under (e) beats Ryan there.
- PWA 22.G.2.j/k: junior manning is involuntary and goes in reverse seniority; it is never a miss for Ryan.
- PWA 10.E.1.a: 11 h rest at domicile. FAR 117.25(e) 10 h rest, 117.25(b) 30 h free in 168 h, 117.23(b)(1) 100 h
  flight time in 672 h, 117.23(c) FDP 60 h in 168 h and 190 h in 672 h (far.legality). PWA 2.19.b: a duty period
  starts 1:00 before departure in domicile, 1:15 out of domicile, and ends 15 min after block-in (30 with customs).

A row is MISSED when a pilot junior to Ryan got it, the pairing fits Ryan's line with no trip, vacation or
blocked day in the way, and FAR / PWA rest pass with known times. POSSIBLE when it would have needed a removal
(22.G.2.f/g) or a time is unknown. NO otherwise, with the reason.

1.4.6 (Ryan, Nov 6): each list day is judged against the line Ryan held that day (held_at(), from the schedule
versions in versions.py), never today's schedule, so a later trade neither makes an old row a miss nor clears a real
one. The line at 00:00 HST is checked, and again every version that came in during the day; when they disagree the
row is POSSIBLE. Missing data (days of the line not on file for that day, a trip's times or block unknown) gives
POSSIBLE, never MISSED: such days enter far.legality() as guesses, and a guess can only make a check unknown.

1.4.6 review (Nov 7): a row awarded to Ryan's own seniority number is his own trip (NO); a pairing whose length is not
known (no days or end on the row, no package) is POSSIBLE; package details come from the row's own bid period (a
callable `details`); each FLICA version's 'Schedule Updated' stamp (HST) dates the change it shows, so a version read
late (CAPTCHA, add-on down) still counts from when FLICA changed; the held line reaches back LOOK + 7 days for a trip
that started in the month before; Over 75 eligibility (PWA 22.G.2.d) is per month (me['o75_months']), unknown gives
POSSIBLE."""
import re
from datetime import date, datetime, time, timedelta, timezone

from far import LEGAL_REFS, legality, window

PAIRING = re.compile(r"^[A-Z]\d{4}[A-Z]?$")
SEN_MAX = 99999  # 1.6.2: a seniority number is an int 1..99999 (the award's column is five digits)
# 1.6.2 (item 10): what a row needs before a CCR draft or an alert is made for it (verdict 'missing')
MISSING = {"seniority": "your seniority number", "line": "your line for these days"}  # pot.PAIRING_RE (kept here so this module stays free of bs4)
HST = timezone(timedelta(hours=-10))
NEAR = 8   # days after the list day where a month not yet on file is unknown, not "not awarded yet"
TRIP_MARGIN = 7  # days a pairing can run past the day it starts (the held line reaches this far past LOOK)
LOOK = 29  # days each side of the list day the 672 h limits reach (FAR 117.23(b)(1), (c)(2))

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


def _details(row, details):
    """The package details for the row's bid period: details is {pid: ...} (one period) or a callable period ->
    {pid: ...} (the Watcher's pkg_details_for). Pairing ids repeat across bid periods (FW-0062), so a row is never
    judged with another month's package; a period with no package gives {}."""
    if callable(details):
        d = _d(row.get("date"))
        return (details(f"{d:%Y-%m}") if d else None) or {}
    return details or {}


def _det(row, details):
    p = str(row.get("pairing") or "")
    det = _details(row, details)
    return det.get(p) or det.get(p.rstrip("ABCDEFGHJ")) or {}


def package_entry(pairing, day, details):
    """FW-0039: one pairing's package details for the bid period of `day` ({} when none), as the miss check reads them
    (_det: a changed pairing such as H3815B falls back to H3815)."""
    return _det({"pairing": pairing, "date": day.isoformat()}, details)


def pairing_window(row, details):
    """(start, end, report, last_arr, block_h, length_known) for a recall row, from the row itself or the month's
    package. length_known is False when neither the row (days, end) nor the package (rel_days, duties) gives the
    pairing's length: end is then the start day only as a placeholder, never to be trusted (1.4.6 review)."""
    start = _d(row.get("date"))
    det = _det(row, details)
    report = row.get("report") or det.get("report")
    try:
        days = int(row.get("days") or det.get("rel_days") or 0)
    except (TypeError, ValueError):
        days = 0
    last_arr, end = row.get("last_arr"), _d(row.get("end"))
    duties = det.get("duties") or []
    known = bool(end or days > 0)
    if duties and (not last_arr or not known):  # the package's duty periods give the last arrival and its day
        try:
            arr = max(int(d["arr"]) for d in duties)
            last_arr = last_arr or _hm(arr)
            end, known = (start + timedelta(days=arr // 1440) if start else None), True
        except (KeyError, TypeError, ValueError):
            pass
    if not end and start:
        end = start + timedelta(days=max(days, 1) - 1)
    blk = row.get("blk") or det.get("block") or ""
    try:
        h, m = str(blk).split(":")[:2]
        blk_h = int(h) + int(m) / 60
    except ValueError:
        blk_h = 0
    return start, end, report, last_arr, blk_h, known


def _overlaps(a, b, c, d):
    return a <= d and c <= b


# ---------------------------------------------------------------- the line as held on a list day (1.4.6)
def _at(v):
    try:
        t = datetime.fromisoformat(str(v.get("at") or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _month_span(mk):
    y, m = int(mk[:4]), int(mk[5:7])
    first = date(y, m, 1)
    nxt = date(y + (m == 12), m % 12 + 1, 1)
    return first, nxt - timedelta(days=1)


def _months(a, b):
    out, y, m = [], a.year, a.month
    while (y, m) <= (b.year, b.month):
        out.append(f"{y:04d}-{m:02d}")
        y, m = y + (m == 12), m % 12 + 1
    return out


def _key(it):
    return (it.get("trip"), it.get("start"), it.get("end"))


def _plain(versions, mk):
    """The month's FLICA versions (not the PBS award from the PDF), oldest first."""
    return sorted([v for v in (versions or {}).get(mk) or [] if isinstance(v, dict) and not v.get("award") and _at(v)],
                  key=_at)


UPDATED_FORMATS = ("%b %d, %Y %H:%M:%S", "%b %d, %Y %H:%M", "%B %d, %Y %H:%M:%S", "%B %d, %Y %H:%M")


def _upd(v):
    """When FLICA last changed the line a version shows: its 'Schedule Updated' stamp ('Nov 8, 2026 10:00:00', HST,
    pot.SCHED_UPDATED) as an aware UTC time, or None when the stamp is empty or unreadable, or later than the Watcher
    stored the version (more than 5 min of clock slack): then only 'at' is trusted."""
    raw = " ".join(str((v or {}).get("updated") or "").split())
    for f in UPDATED_FORMATS:
        try:
            t = datetime.strptime(raw, f).replace(tzinfo=HST).astimezone(timezone.utc)
        except ValueError:
            continue
        at = _at(v)
        return t if at is None or t <= at + timedelta(minutes=5) else None
    return None


def _span_months(day):
    """The months the held line covers around list day `day`: back to LOOK + 7 days before it (a trip that started in
    the month before and runs into the 672 h window, the same 7 day trip margin as the forward side), forward to
    LOOK + 7 days after it."""
    return _months(day - timedelta(days=LOOK + TRIP_MARGIN), day + timedelta(days=LOOK + TRIP_MARGIN))


def keeping_since(versions):
    """When the Watcher started keeping schedule versions (the oldest FLICA version on file), or None."""
    ts = [_at(v) for mk in (versions or {}) for v in _plain(versions, mk)]
    return min(ts) if ts else None


def held_at(versions, day, at=None, current=None, current_own=None, since=None):
    """Ryan's line as he held it at `at` (default 00:00 HST on `day`, a list date), from the schedule versions
    (versions.py: {YYYY-MM: [version, ...]}, each stamped 'at' in UTC when the Watcher saw it, the PBS award from
    the PDF flagged 'award'). Per month, LOOK days around the day:
    - the newest FLICA version seen at or before that time, when there is one;
    - a later month with no version by then, while the Watcher was keeping versions (`since`): not awarded yet, so
      no trips (its first NEAR days after the list day stay unknown, in case the Watcher missed it);
    - else the award and the first version seen after it: what both hold is known, what they disagree on is not;
    - else only the award: the awarded line, when the Watcher kept versions from the month's first day (a change
      would have made one); a month that began before that is not on file;
    - else the trips that started before the day, which cannot change once started (from the first later version,
      else the schedule on file now); the rest of the month is unknown.
    1.4.6 review: a version stored after that time whose FLICA 'Schedule Updated' stamp (_upd) is at or before it shows
    the line as it was then (FLICA changed nothing between the stamp and the read), so it is the line held, whatever
    came before it (a read outage: CAPTCHA, MFA, add-on down, the 2 h block / credit wait); it also means the month
    was awarded by then. Months start LOOK + 7 days before the day (_span_months); days not on file are unknown from
    that margin on (never earlier: they cannot matter), and up to 7 days into the next month (a trip that started on
    an unknown day is in its own month's items only).
    Returns {day, items, trips, unknown [(from, to) ISO dates], asof (UTC ISO), line ('11.004'), lines}. Pure."""
    t = at or datetime.combine(day, time(0), HST).astimezone(timezone.utc)
    reach = day - timedelta(days=LOOK + TRIP_MARGIN)
    since = since if since is not None else keeping_since(versions)
    items, trips, unknown, lines = [], {}, [], {}
    seen = set()

    def take(its, trs, keep=lambda it: True):
        for it in its or []:
            if keep(it) and _key(it) not in seen:
                seen.add(_key(it))
                items.append(it)
                k = f"{it.get('trip')}|{it.get('start')}"
                if (trs or {}).get(k) and k not in trips:
                    trips[k] = trs[k]

    started = lambda it: (_d(it.get("start")) or day) < day  # noqa: E731
    for mk in _span_months(day):
        first, last = _month_span(mk)
        plain = _plain(versions, mk)
        award = next((v for v in (versions or {}).get(mk) or [] if isinstance(v, dict) and v.get("award")), None)
        before = [v for v in plain if _at(v) <= t]
        after = [v for v in plain if _at(v) > t]
        stamped = [v for v in after if _upd(v) and _upd(v) <= t]  # read late, but FLICA had it by then
        if stamped:
            v = stamped[-1]
            take(v.get("items"), v.get("trips"))
            lines[mk] = v.get("ver") or mk
        elif before:
            v = before[-1]
            take(v.get("items"), v.get("trips"))
            lines[mk] = v.get("ver") or mk
        elif first > day and since and since <= t and not (award and (_at(award) or t) <= t):
            near = day + timedelta(days=NEAR)
            if first <= near:
                unknown.append((first.isoformat(), min(last, near).isoformat()))
            lines[mk] = "not awarded yet"
        elif award and after:
            nxt = after[0]
            take(nxt.get("items"), nxt.get("trips"), started)
            both = {_key(i) for i in award.get("items") or []} & {_key(i) for i in nxt.get("items") or []}
            take(nxt.get("items"), nxt.get("trips"), lambda it: _key(it) in both)
            for it in (award.get("items") or []) + (nxt.get("items") or []):
                if _key(it) not in both and not started(it) and it.get("start") and it.get("end"):
                    unknown.append((it["start"], it["end"]))
            lines[mk] = f"{award.get('ver') or mk} / {nxt.get('ver') or mk}"
        elif award and since and since <= datetime.combine(first, time(0), HST):
            take(award.get("items"), award.get("trips"))  # versions kept all month and none came: no change
            lines[mk] = award.get("ver") or mk
        else:
            src = after[0] if after else (current or {}).get(mk)
            if src:
                take(src.get("items"), src.get("trips") if after else current_own, started)
            # a trip that starts on an unknown day is in this month's items only and may run TRIP_MARGIN days into the
            # next month, whose own version does not show it: those days are unknown too
            carry = (last + timedelta(days=TRIP_MARGIN)).isoformat()
            if not src:
                unknown.append((max(first, reach).isoformat(), carry))
            elif last >= day:
                unknown.append((max(first, day).isoformat(), carry))
            lines[mk] = "not on file"
    for k, v in (current_own or {}).items():  # times the version did not keep (same trip, same start)
        if any(f"{it.get('trip')}|{it.get('start')}" == k for it in items):
            trips[k] = {**v, **{f: x for f, x in (trips.get(k) or {}).items() if x not in (None, "", [])}}
    return {"day": day.isoformat(), "items": items, "trips": trips, "unknown": unknown, "asof": t.isoformat(),
            "line": lines.get(day.strftime("%Y-%m"), ""), "lines": lines}


def helds_on(versions, day, current=None, current_own=None):
    """Every line Ryan held during the list day (HST): the one at 00:00 and one per version that came in before
    24:00, without repeats. A recall is awarded some time that day, so a row is judged against each."""
    t0 = datetime.combine(day, time(0), HST).astimezone(timezone.utc)
    t1 = t0 + timedelta(days=1)
    since = keeping_since(versions)
    times = {x for mk in _span_months(day) for v in _plain(versions, mk) for x in (_at(v), _upd(v))
             if x and t0 < x < t1}  # 1.4.6 review: FLICA's own change time too, for a version read after the day
    out, sigs = [], set()
    for t in [t0] + sorted(times):
        h = held_at(versions, day, t, current, current_own, since)
        sig = repr((sorted(map(repr, h["items"])), sorted(h["trips"].items()), h["unknown"]))
        if sig not in sigs:
            sigs.add(sig)
            out.append(h)
    return out


# ---------------------------------------------------------------- trips as far.legality() reads them
def _hrs(blk):
    try:
        h, m = str(blk).split(":")[:2]
        return int(h) + int(m) / 60
    except ValueError:
        return None


def _trip(label, a, b, report, last_arr, blk_h, duties, flying=True, unknown_line=False):
    """One trip for far.legality(). duties: [{d, dep, arr, stn?, blk?}] in HST minutes from 00:00 HST of day a (the
    FLICA and package shape, blk in minutes). A later duty starts 1:15 before its departure out of domicile, 1:00 in
    domicile (PWA 2.19.b); the first starts at the trip's report when it is known. With only the dates, whole days
    (00:00 on the first day to 24:00 on the last)."""
    w = window(a, b, report, last_arr) if a else None
    if not w and duties:
        try:
            dep, arr = int(duties[0]["dep"]), max(int(x["arr"]) for x in duties)
            base = datetime.combine(a, time(0))
            w = (base + timedelta(minutes=dep - 60), base + timedelta(minutes=arr + 15))
        except (KeyError, TypeError, ValueError):
            w = None
    if not w or unknown_line:  # only the dates: whole days
        r = datetime.combine(a, time(0))
        e = datetime.combine((b or a) + timedelta(days=1), time(0))
        return {"label": label, "report": r, "release": e + timedelta(minutes=15), "duties": [(r, e, None)],
                "exact": False, "approx": True, "block": None, "flying": flying, "unknown_line": unknown_line}
    rep, rel = w
    out = {"label": label, "report": rep, "release": rel, "exact": False, "approx": False, "block": blk_h,
           "flying": flying}
    du = []
    try:
        base = datetime.combine(a, time(0))
        prev_stn = "HNL"
        for i, x in enumerate(sorted(duties or [], key=lambda y: int(y["dep"]))):
            dep, arr = base + timedelta(minutes=int(x["dep"])), base + timedelta(minutes=int(x["arr"]))
            if arr <= dep:
                raise ValueError("duty ends before it starts")
            s = rep if i == 0 else dep - timedelta(minutes=60 if prev_stn == "HNL" else 75)
            du.append((min(s, dep), arr, int(x["blk"]) / 60 if x.get("blk") not in (None, "") else None))
            prev_stn = str(x.get("stn") or x.get("to") or "")
    except (KeyError, TypeError, ValueError):
        du = []
    if du and abs((du[-1][1] + timedelta(minutes=15) - rel).total_seconds()) <= 3600:
        out.update(duties=du, exact=True)
        if any(d[2] is None for d in du):  # duty blocks incomplete: flight time over the whole trip
            out["ft"] = [(rep, rel - timedelta(minutes=15), blk_h)]
    else:
        out["duties"] = [(rep, rel - timedelta(minutes=15), blk_h)]
        out["exact"] = (b or a) == a  # a one-day trip is one duty period
    return out


def own_records(sched_items, own_trips):
    """Ryan's items (not VAC) as far.legality() trips. A pairing without its times is whole days; a non-pairing code
    (SCR, SICK, training, reserve...) is whole days of possible duty with no flight time or FDP."""
    out = []
    for it in sched_items or []:
        trip = it.get("trip") or ""
        if not trip or trip == "VAC":
            continue
        a, b = _d(it.get("start")), _d(it.get("end"))
        if not a:
            continue
        lab = f"{trip} {a:%b} {a.day}"
        if not PAIRING.match(trip):
            out.append(_trip(lab, a, b, None, None, 0.0, None, flying=False))
            continue
        t = (own_trips or {}).get(f"{trip}|{it.get('start')}") or {}
        out.append(_trip(lab, a, b, t.get("report"), t.get("last_arr"), _hrs(t.get("blk")), t.get("duties")))
    return out


def line_gaps(months, lo, hi, today, near=NEAR):
    """FW-0039: the days from lo to hi (dates) that no schedule month on file covers ({YYYY-MM: {days: [[iso, ...]]}},
    the Watcher's S['schedule']), as [(from, to)] ISO spans: Ryan's current line there is unknown. A day after the
    last day on file and more than `near` days after today is in a month not awarded yet (no trips), as in
    held_at(); nearer ones stay unknown in case the Watcher has not read an awarded month yet."""
    covered = {str(d[0]) for m in (months or {}).values() for d in (m or {}).get("days") or [] if d}
    last = max(covered) if covered else ""
    out, d = [], lo
    while d <= hi:
        iso = d.isoformat()
        if iso not in covered and not (last and iso > last and d > today + timedelta(days=near)):
            if out and out[-1][1] == (d - timedelta(days=1)).isoformat():
                out[-1] = (out[-1][0], iso)
            else:
                out.append((iso, iso))
        d += timedelta(days=1)
    return out


def pickup_trip(label, start, end, report, last_arr, blk_h, duties):
    """FW-0039: a pot / Tradeboard pickup as far.legality() reads it (the same _trip() the miss check builds)."""
    return _trip(label, start, end, report, last_arr, blk_h, duties)


def line_records(months, own_trips, start, end, today, exclude=None):
    """FW-0039: Ryan's current line as far.legality() trips, for the FAR column of a pickup from start to end: his
    items (own_records; `exclude` 'TRIP|YYYY-MM-DD' left out, for a swap) plus the days LOOK + TRIP_MARGIN around the
    pickup that no schedule month on file covers (line_gaps), which can only make a check unknown, never OK.
    1.7.2: a PAYP item is left out (its trip was removed and is not flown; PWA 4.R.1 lets a pickup cover its days).
    The miss check (verdict) reads own_records directly and still counts it as possible duty."""
    items, seen = [], {exclude}
    for m in (months or {}).values():
        for it in (m or {}).get("items") or []:
            k = f"{it.get('trip')}|{it.get('start')}"
            if it.get("trip") == "PAYP":
                continue
            if k not in seen:  # a trip listed by two months counts once
                seen.add(k)
                items.append(it)
    gaps = line_gaps(months, start - timedelta(days=LOOK + TRIP_MARGIN), end + timedelta(days=LOOK + TRIP_MARGIN),
                     today)
    return own_records(items, own_trips) + _gaps_as_trips(gaps)


def _gaps_as_trips(unknown):
    out = []
    for x, y in unknown or []:
        a, b = _d(x), _d(y)
        if a and b:
            out.append(_trip(f"your line {x} to {y}" if x != y else f"your line {x}",
                             a, b, None, None, None, None, unknown_line=True))
    return out


def _spans(g):
    return ", ".join(x if x == y else f"{x} to {y}" for x, y in g)


def _hst(iso):
    try:
        t = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return str(iso)
    t = (t if t.tzinfo else t.replace(tzinfo=timezone.utc)).astimezone(HST)
    return f"{t:%b} {t.day} {t:%H:%M} HST"


def o75_eligible(me, month):
    """PWA 22.G.2.d: Over 75 goes to Reserve Run pilots only. Whether Ryan was on reserve in `month` (YYYY-MM), from
    his per-month answer me['o75_months'] {YYYY-MM: true | false}: True, False, or None when he has not said (the old
    single 'o75' flag is not used: it defaulted to eligible for every month)."""
    v = (me.get("o75_months") or {}).get(month) if isinstance(me.get("o75_months"), dict) else None
    return v if isinstance(v, bool) else None


def evaluate(row, me, sched_items, own_trips, blocked, details, held=None):
    """One verdict dict for one recall-list row against one line. me = {sen, seat, o75_months}. held (held_at()): the
    line as held on the list day, used instead of sched_items / own_trips; its unknown spans can only make a check
    unknown (POSSIBLE), never pass it. Without held, sched_items / own_trips are taken as complete. details: the
    package {pid: ...} or a callable period -> {pid: ...} (_details)."""
    out = _evaluate(row, me, sched_items, own_trips, blocked, details, held)
    if out.get("kind") == "o75" and out["verdict"] == "MISSED":
        d = _d(row.get("date"))
        mk = f"{d:%Y-%m}" if d else ""
        if o75_eligible(me, mk) is None:  # 1.4.6 review: never MISSED on an assumed reserve month
            out["verdict"] = "POSSIBLE"
            out["why"].append(f"reserve status for {d:%b %Y} unknown: Over 75 goes to Reserve Run pilots only (PWA "
                              f"22.G.2.d); say on the tab whether you were on reserve that month")
    return out


def _evaluate(row, me, sched_items, own_trips, blocked, details, held=None):
    kind = (row.get("kind") or "").lower()
    out = {"date": row.get("date"), "kind": kind, "pairing": row.get("pairing") or "", "sen": row.get("sen"),
           "pilot": row.get("pilot") or "", "seat": (row.get("seat") or "FO").upper(), "verdict": "NO", "why": [], "refs": []}
    lab, ref = KINDS.get(kind, ("", ""))
    if ref:
        out["refs"].append(f"PWA {ref}")
    if kind not in ("recall", "o75") or not row.get("pairing"):
        out["why"].append("no award to check" if kind not in KINDS else f"{lab}: involuntary, never a miss (PWA {ref})")
        return out
    if out["seat"] != (me.get("seat") or "FO").upper():
        out["why"].append(f"{out['seat']} seat, you bid {me.get('seat') or 'FO'}")
        return out
    rd = _d(row.get("date"))
    if kind == "o75" and rd and o75_eligible(me, f"{rd:%Y-%m}") is False:
        out["why"].append(f"Over 75 is for Reserve Run pilots (PWA 22.G.2.d); you said you were not on reserve in "
                          f"{rd:%b %Y}")
        return out
    try:
        their = int(row.get("sen"))
    except (TypeError, ValueError):
        out["verdict"] = "POSSIBLE"
        out["why"].append("seniority unknown (the list row has no seniority number)")
        return out
    mine = me.get("sen")
    if isinstance(mine, bool) or not isinstance(mine, int) or not 1 <= mine <= SEN_MAX:
        # 1.6.2 (Release A item 10): the pilot's own number is missing: no CCR draft and no alert, the row says why
        out.update(verdict="POSSIBLE", missing="seniority")
        out["why"].append("seniority unknown: your seniority number is not on file (type it under My seniority #)")
        return out
    if their == mine:  # 1.4.6 review: his own award (the version showing it may come in after the list day)
        out["why"].append(f"awarded to you (#{mine})")
        return out
    if their < mine:
        out["why"].append(f"went to #{their}, senior to you (#{mine})")
        return out
    out["why"].append(f"went to #{their}, junior to you (#{mine})")
    s, e, rep, arr, blk, known = pairing_window(row, details)
    if not s:
        out["verdict"] = "POSSIBLE"
        out["why"].append("date unreadable")
        return out
    days = [(s + timedelta(days=i)).isoformat() for i in range((e - s).days + 1)]
    out.update(start=s.isoformat(), end=e.isoformat(), report=rep or "", last_arr=arr or "")
    line = "your current line"
    if held is not None:
        out["asof"], out["line"] = held.get("asof") or "", held.get("line") or ""
        sched_items, own_trips = held.get("items"), held.get("trips")
        line = f"your line as held at {_hst(held.get('asof'))}" + (
            f" (version {held['line']})" if held.get("line") and held["line"][:1].isdigit() else "")
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
    if trips:
        if kind == "o75":  # Over 75 is for days off (22.G.2.d); it has no removal step
            out["why"].append(f"you were on {', '.join(trips)} ({line}); Over 75 is offered on days off only (PWA 22.G.2.d)")
        else:  # 22.G.2.f only reaches you after every clean 22.G.2.e volunteer
            out["why"].append(f"you were on {', '.join(trips)} ({line}); removal (PWA 22.G.2.f) comes after clean "
                              f"junior volunteers (PWA 22.G.2.e)")
        return out
    if vac:
        out["why"].append(f"you were on vacation ({line}); removal (PWA 22.G.2.g) comes after 22.G.2.e and f"
                          if kind == "recall" else
                          f"you were on vacation ({line}); Over 75 is offered on days off only (PWA 22.G.2.d)")
        return out
    gaps = (held or {}).get("unknown") or []
    in_way = [(x, y) for x, y in gaps if _overlaps(s, e, _d(x) or s, _d(y) or e)]
    if in_way:
        out["verdict"] = "POSSIBLE"
        out["missing"] = "line"  # 1.6.2 (item 10): his line for these days is unknown: no CCR draft and no alert
        out["why"].append(f"{line} is not on file for {_spans(in_way)}: cannot tell whether a trip, vacation or "
                          f"reserve was in the way (PWA 22.G.2.e-g) or check rest and FAR 117")
        return out
    if not window(s, e, rep, arr):
        out["verdict"] = "POSSIBLE"
        out["why"].append("pairing times unknown; upload the month's pairings PDF or add report and arrival")
        return out
    if not known:  # 1.4.6 review: a multi-day pairing must not shrink to one day (its later days unchecked)
        out["verdict"] = "POSSIBLE"
        out["why"].append(f"pairing length unknown; upload the {s:%b %Y} pairings PDF or add days to the row")
        return out
    new = _trip(out["pairing"], s, e, rep, arr, blk or None, _det(row, details).get("duties"))
    res = legality(new, own_records(sched_items, own_trips) + _gaps_as_trips(gaps))
    out["far"] = res["summary"]
    out["refs"] += LEGAL_REFS
    if res["result"] == "OK":
        out["verdict"] = "MISSED"
        out["why"].append(f"open and legal on {line}: {res['summary']}")
    elif res["result"] == "?":
        out["verdict"] = "POSSIBLE"
        out["why"].append(f"legality not provable on {line}: {res['summary']}")
    else:
        out["why"].append(f"not legal on {line}: {res['summary']}")
    return out


def judge(row, me, helds, blocked, details):
    """The row against every line Ryan held during the list day (helds_on()). One answer when they agree; POSSIBLE
    when they do not (the line changed that day and the award time is not on the list). 1.6.2: missing when any of
    them lacks data (the line not on file on one of them)."""
    vs = [evaluate(row, me, None, None, blocked, details, held=h) for h in helds or [None]]
    if len(vs) == 1:
        return vs[0]
    out = dict(vs[0])
    miss = next((v["missing"] for v in vs if v.get("missing")), "")
    if miss:
        out["missing"] = miss
    if len({v["verdict"] for v in vs}) == 1:
        out["why"] = out["why"][:-1] + [f"{out['why'][-1]} (the same on each of the {len(vs)} versions of your line in "
                                         f"force that day)"]
        return out
    out["verdict"] = "POSSIBLE"
    out["why"] = out["why"][:1] + [f"your line changed during the day; at {_hst(h.get('asof'))}: {v['verdict']} ("
                                   f"{v['why'][-1]})" for h, v in zip(helds, vs)]
    out["refs"] = sorted({r for v in vs for r in v.get("refs") or []}, key=lambda r: (not r.startswith("PWA 22"), r))
    out["far"] = " | ".join(v.get("far") or "" for v in vs if v.get("far"))
    return out


def _article(word):
    """'an FO' / 'a CA' (the seat code read aloud: F, R, S begin with a vowel sound)."""
    w = str(word or "FO")
    return f"{'an' if w[:1].upper() in 'AEFHILMNORSX' else 'a'} {w}"


def narrative(v, me, name="", emp=""):
    """CCR narrative Ryan reviews and edits on the Recall/O75 tab before anything is filed. 1.6.2: never prints None
    (a number not on file reads 'not on file'); 'an FO'; a CHECK row starts with a line saying what to check first."""
    lab, ref = KINDS.get(v.get("kind"), ("Recall", ""))
    sen = me.get("sen") if isinstance(me.get("sen"), int) and not isinstance(me.get("sen"), bool) else None
    mine = f"#{sen}" if sen else "# not on file"
    who = f"{name} ({mine})" if name else f"I (seniority {mine})"
    held = f" on my schedule as I held it that day (version {v['line']})" if str(v.get("line") or "")[:1].isdigit() else ""
    lines = [] if v.get("verdict") != "POSSIBLE" else [
        "DRAFT TO CHECK: the Watcher could not confirm this one (" + "; ".join(v.get("why") or [])[:400] +
        "). Check availability and legality yourself before filing."]
    lines += [
        f"On {v.get('date')}, {lab} pairing {v.get('pairing')} ({v.get('start', v.get('date'))} to {v.get('end', v.get('date'))}, "
        f"report {v.get('report') or 'per pairing'}) was awarded to {_article(v.get('seat'))} with seniority #{v.get('sen')}, junior to me.",
        f"{who} was available on those days with no Flight Grouping, Reserve day or vacation in the way, and was legal"
        f"{held} under FAR 117 (117.25(b) 30 h free in 168 h, 117.25(e) 10 h rest, 117.23(b)(1) 100 h flight time in "
        f"672 h, 117.23(c) 60 h FDP in 168 h and 190 h in 672 h) and PWA 10.E.1.a (11 h domicile rest): "
        f"{v.get('far') or 'see schedule'}.",
        f"Under PWA {ref}, the pairing should have been offered to me before a junior pilot. I request {('200% pay per 4.M' if v.get('kind') == 'recall' else 'pay per 4.N in addition to guarantee')} "
        f"for the pairing as compensation for the missed award.",
    ]
    if emp:
        lines.append(f"Employee #{emp}.")
    return "\n\n".join(lines)


def check_day(rows, me, sched_items, own_trips, blocked, details, helds=None):
    """Every row of one list. helds (helds_on()): the lines held that day; without it, the current line. details:
    {pid: ...} or a callable period -> {pid: ...}, so each row reads its own bid period's package."""
    if helds:
        return [judge(r, me, helds, blocked, details) for r in rows or []]
    return [evaluate(r, me, sched_items, own_trips, blocked, details) for r in rows or []]
