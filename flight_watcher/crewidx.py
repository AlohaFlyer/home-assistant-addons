"""Crew index (0.10.1, Ryan): rebuild any HNL A330 pilot's month from the crew lines on the pairing pages.

Pure logic, no network and no MQTT: trip instances from the card's pairing files (www/flight-watcher/pairings_<YYYY-MM>.json),
the order the crawl reads them in, the crew line parser and the per-month Markdown. watcher.py does the paced GETs
(read only) and stores the result through store.py (crew_idx / crew_emp tables).
"""
import calendar
import json
import os
import re
from datetime import date, datetime, timedelta

from pot import CREW_RE, clean_name, soft_time

CREW_FROM = date(2026, 10, 31)  # nothing before this is read
PILOT_POS = ("CA", "FO", "RO", "SO")
FILE_RE = re.compile(r"^pairings_(\d{4})-(\d{2})\.json$")
WRAP_MIN = 25  # a day number above this, ahead of a smaller one in the same list, is last month's
SOON_H = 72
SOON_STALE_H = 6
FAIL_RETRY_H = 24
FAIL_MAX_PAST = 3  # a departed instance that keeps failing is given up after this many tries
HOLD_AFTER = 3  # FW-0016: this many reads in a row naming no pilot hold a bid period until names appear


def _ym(month):
    return int(month[:4]), int(month[5:7])


def _shift(y, m, k):
    y2, m2 = divmod(y * 12 + m - 1 + k, 12)
    return y2, m2 + 1


def _prev_tokens(month, toks):
    """Day numbers in this list that are last month's: larger than the month, or > WRAP_MIN and ahead of a
    smaller number (the list runs in bid period order, so '31 2 5' in November starts on Oct 31). The wrap rule
    also applies to a 'D' token ('D31 2' in November), which otherwise means next month."""
    y, m = _ym(month)
    mlen = calendar.monthrange(y, m)[1]
    nums = [int(t.lstrip("Dd")) if t.lstrip("Dd").isdigit() else None for t in toks]
    out = set()
    for i, n in enumerate(nums):
        if n is None:
            continue
        if n > mlen and toks[i].isdigit():
            out.add(i)
        elif n > WRAP_MIN and any(x is not None and x < n and toks[j].isdigit() for j, x in enumerate(nums[i + 1:], i + 1)):
            out.add(i)
    return out


def file_prev_from(month, day_lists):
    """The first day of the bid period when it starts in the previous month, judged over the whole file
    (smallest day number any row shows as last month's), else None."""
    found = []
    for toks in day_lists:
        for i in _prev_tokens(month, toks):
            found.append(int(toks[i].lstrip("Dd")))
    return min(found) if found else None


def month_dates(month, days, prev_from=None):
    """Dates of a pairing's operating days in the file of `month` ('2026-11'). `days` is the space separated
    list ('2 5 9', 'D1' = day 1 of next month as pdfs.py writes it). A number larger than the month, a number
    > WRAP_MIN ahead of a smaller one, or (file level) a number >= prev_from > WRAP_MIN is last month's."""
    y, m = _ym(month)
    toks = [t for t in str(days or "").split() if t]
    prev_idx = _prev_tokens(month, toks)
    py, pm = _shift(y, m, -1)
    ny, nm = _shift(y, m, 1)
    out = []
    for i, t in enumerate(toks):
        try:
            if t[0] in "Dd" and t[1:].isdigit() and i not in prev_idx:
                out.append(date(ny, nm, int(t[1:])))
                continue
            n = int(t.lstrip("Dd"))
            if i in prev_idx or (prev_from and prev_from > WRAP_MIN and n >= prev_from):
                out.append(date(py, pm, n))
            else:
                out.append(date(y, m, n))
        except (ValueError, IndexError):
            continue
    return out


def _cell(r, i):
    """A pairing file row's cell as text ('' when the file has no such column or the row is short)."""
    return str(r[i] if r[i] is not None else "").strip() if i is not None and i < len(r) else ""


def instances(pdir, crew_from=CREW_FROM):
    """{key 'H3601|2026-11-02': {key, pairing, date, end_date, report, route, credit, block, tafb, first_duty_min,
    days, month, period}} from every pairing
    file, on or after crew_from. rel_days (pdfs.py: release day minus report day) gives the trip end."""
    out = {}
    try:
        files = sorted(f for f in os.listdir(pdir) if FILE_RE.match(f))
    except OSError:
        return out
    for f in files:
        y, m = FILE_RE.match(f).groups()
        month = f"{y}-{m}"
        try:
            d = json.load(open(os.path.join(pdir, f)))
            cols = d.get("cols") or []
            ix = {c: cols.index(c) for c in ("id", "report", "rel_days", "first_duty_min", "route", "credit", "tafb", "days",
                                             "block") if c in cols}
            rows = d.get("rows") or []
        except Exception:
            continue
        if "id" not in ix or "days" not in ix:
            continue
        lists = [str(r[ix["days"]] or "").split() for r in rows if len(r) > ix["days"]]
        prev_from = file_prev_from(month, lists)
        st = str(d.get("start") or "")  # FW-0014: pdfs.py writes the period's first day; it settles '31' in January
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", st) and st < f"{month}-01":
            prev_from = int(st[8:])
        for r in rows:
            try:
                pid = str(r[ix["id"]]).strip()
                rel = int(r[ix["rel_days"]] or 0) if "rel_days" in ix else 0
            except (ValueError, TypeError, IndexError):
                continue
            if not pid:
                continue
            for dt in month_dates(month, r[ix["days"]], prev_from):
                if dt < crew_from:
                    continue
                k = f"{pid}|{dt.isoformat()}"
                out.setdefault(k, {"key": k, "pairing": pid, "date": dt.isoformat(),
                                   "end_date": (dt + timedelta(days=max(rel, 0))).isoformat(),
                                   "report": str(r[ix["report"]]) if "report" in ix else "",
                                   "route": str(r[ix["route"]]) if "route" in ix else "",
                                   "credit": str(r[ix["credit"]] or "") if "credit" in ix else "",
                                   # FW-0062: block, TAFB and the first duty's length, for a rebuilt trip without its package
                                   "block": _cell(r, ix.get("block")), "tafb": _cell(r, ix.get("tafb")),
                                   "first_duty_min": _cell(r, ix.get("first_duty_min")),
                                   "days": max(rel, 0) + 1, "month": dt.strftime("%Y-%m"), "period": month})
    return out


def departs(inst):
    """HST wall-clock departure (report time on the start date; 00:00 when unknown)."""
    d = datetime.fromisoformat(inst["date"])
    m = re.match(r"^\s*(\d{1,2}):(\d{2})", inst.get("report") or "")
    return d.replace(hour=int(m.group(1)), minute=int(m.group(2))) if m and int(m.group(1)) < 24 else d


def has_crew(crew):
    """FW-0016: True when a crew line names at least one pilot (an OPEN seat or a flight attendant is not one).
    Before the award FLICA's pairing pages list nobody, and such a read is not counted as read."""
    return any(c.get("pos") in PILOT_POS and c.get("name") and c.get("name") != "OPEN" for c in crew or [])


def period_of(it):
    """The bid period (pairing file month) an instance came from; its calendar month for older records."""
    return it.get("period") or it.get("month") or str(it.get("date") or "")[:7]


def awarded_periods(insts, rows):
    """FW-0016: bid periods with a read that named a pilot: the award is out. A row keeps the last crew read with
    names ('empty' and 'fail' reads do not replace it), so a period seen awarded stays awarded."""
    return {period_of(it) for k, it in insts.items() if has_crew((rows.get(k) or {}).get("crew"))}


def held_periods(insts, rows, awarded=None):
    """FW-0016: bid periods none of whose reads has ever named a pilot (awarded_periods) and HOLD_AFTER or more of
    whose reads found no names: the award is not out, so the crawl reads one page of such a period per run (a
    probe) instead of all of them. An awarded period is never held: after the award an open-time trip ('CA Open
    FO Open') names nobody either, and it is read like any other."""
    awarded = awarded_periods(insts, rows) if awarded is None else awarded
    n = {}
    for k, it in insts.items():
        r = rows.get(k) or {}
        if r.get("status") == "empty" and r.get("checked_at"):
            n[period_of(it)] = n.get(period_of(it), 0) + 1
    return {p for p, c in n.items() if c >= HOLD_AFTER and p not in awarded}


def queue(insts, rows, now, run_started=None):
    """Keys to read, in order: (0) FW-0016: one probe per held bid period (held_periods) per run: a future
    instance never read, soonest first, else the one checked longest ago, so the probe moves through the
    period; (1) never checked, soonest first (past dates too), and future pages read with no crew names before
    their period's award was seen (FW-0016: stale once it is); (1b) failed, or read with no crew names in a
    period with no award seen yet (and not held), more than FAIL_RETRY_H ago; (2) departing within SOON_H and
    checked more than SOON_STALE_H ago; (2b) departed but last checked before departure (one read for the
    final crew); (3) the oldest-checked future ones. Nothing else of a held period is read. Departed instances
    checked after departure are never re-read (FW-0016: a page read with no crew names included); nothing read
    in this run is read again. `now` and checked_at are HST wall clock (naive ISO)."""
    nowi = now.isoformat()
    soon = (now + timedelta(hours=SOON_H)).isoformat()
    stale = (now - timedelta(hours=SOON_STALE_H)).isoformat()
    retry = (now - timedelta(hours=FAIL_RETRY_H)).isoformat()
    awarded = awarded_periods(insts, rows)
    held = held_periods(insts, rows, awarded)
    probe, probed = {}, set()
    c1, c1b, c2, c2b, c3 = [], [], [], [], []
    for k, it in insts.items():
        r = rows.get(k) or {}
        dep = departs(it).isoformat()
        per = period_of(it)
        at = r.get("checked_at") or ""
        if per in held:
            if run_started and at >= run_started:
                probed.add(per)  # this period had its read in this run
            elif dep > nowi:  # never read (soonest) before read (longest ago), so no one trip pins the probe
                cand = (1, at, dep, k) if at else (0, dep, "", k)
                if per not in probe or cand < probe[per]:
                    probe[per] = cand
            continue
        if not at:
            c1.append((dep, k))
            continue
        if run_started and at >= run_started:
            continue
        st = r.get("status")
        if st == "empty" and dep > nowi:
            if per in awarded:  # read before the award was seen: stale now, read again first
                c1.append((dep, k))
            elif at < retry:
                c1b.append((dep, k))
            continue
        if st not in ("ok", "empty"):
            if at < retry and (dep > nowi or int(r.get("tries") or 0) < FAIL_MAX_PAST):
                c1b.append((dep, k))
            continue
        if dep <= nowi:  # 'ok', or 'empty' of a departed trip: crew that can no longer change, no retries
            if at < dep:
                c2b.append((dep, k))
            continue
        if dep <= soon:
            if at < stale:
                c2.append((dep, k))
            continue
        c3.append((at, dep, k))
    c0 = sorted(v for p, v in probe.items() if p not in probed)
    return ([k for *_, k in c0] + [k for _, k in sorted(c1)] + [k for _, k in sorted(c1b)] + [k for _, k in sorted(c2)]
            + [k for _, k in sorted(c2b)] + [k for *_, k in sorted(c3)])


NAME_RE = re.compile(r"^([a-z][a-z'.\- ]*?(?: jr| sr| ii| iii)?,\s*[a-z][a-z'.\-]*(?:\s[a-z][a-z'.\-]*)?)\b", re.I)


def crew_line(text):
    """[{pos, name, emp}] from a pairing page's crew line, in page order (OPEN seats kept, name 'OPEN', emp '');
    None when the page has no crew line. Same regex as pot.parse_crew / crew_ids. FW-0017: FLICA's check pilot
    tag ('Doe, Ckp Jane') is taken out of the name and kept as ckp: true."""
    m = re.search(r"crew\s*:\s*(.*)$", text or "", re.I | re.S)
    if not m:
        return None
    out = []
    for pos, emp, name in CREW_RE.findall(m.group(1)):
        name, ckp = clean_name(name)
        if name.lower() == "open":
            out.append({"pos": pos.upper(), "name": "OPEN", "emp": ""})
            continue
        nm = NAME_RE.match(name)  # the last name on the line can run into page text after it
        c = {"pos": pos.upper(), "name": (nm.group(1) if nm else name[:40]).strip().title(), "emp": emp or ""}
        if ckp:
            c["ckp"] = True
        out.append(c)
    return out


def coverage(insts, rows, month=None, date_from=None, date_to=None):
    """(instances, checked ok, percent) over all instances, one month's, or (FW-0002, the pilot card's grid)
    those starting date_from..date_to (ISO, inclusive) whatever file they came from."""
    ks = [k for k, it in insts.items() if (not month or it["month"] == month)
          and (not date_from or it["date"] >= date_from) and (not date_to or it["date"] <= date_to)]
    ok = sum(1 for k in ks if (rows.get(k) or {}).get("status") == "ok")
    return len(ks), ok, round(100.0 * ok / len(ks), 1) if ks else 0.0


def render_month(month, insts, rows, now_s, held=None):
    """Markdown for one month: header, then one section per pilot (sorted by name) with a table of trips.
    FW-0016: pages read with no crew names are counted apart, and a held bid period (held_periods) says so."""
    n, ok, pct = coverage(insts, rows, month)
    fails = sum(1 for k, it in insts.items() if it["month"] == month and (rows.get(k) or {}).get("status") == "fail")
    empty = sum(1 for k, it in insts.items() if it["month"] == month and (rows.get(k) or {}).get("status") == "empty")
    held = held_periods(insts, rows) if held is None else held
    waiting = sorted({period_of(it) for it in insts.values() if it["month"] == month and period_of(it) in held})
    pilots = {}
    for k, it in insts.items():
        r = rows.get(k) or {}
        if it["month"] != month or r.get("status") != "ok":
            continue
        for c in r.get("crew") or []:
            if c.get("pos") not in PILOT_POS or c.get("name") == "OPEN":
                continue
            pid = c.get("emp") or c["name"]
            p = pilots.setdefault(pid, {"name": c["name"], "emp": c.get("emp") or "", "trips": []})
            p["trips"].append((it["date"], it["pairing"], c["pos"], it.get("route") or "", it.get("days") or 1))
    lines = [f"# Crew index {month}", "",
             f"Coverage {pct}% ({ok} of {n} trip instances read, {fails} failed, {empty} with no crew names yet). "
             f"Updated {now_s} HST.",
             "Rebuilt from the crew lines on FLICA pairing pages (read only). A trip picked up or dropped after",
             "it was read shows the crew at the time of the read.", ""]
    for p in waiting:
        lines += [f"Waiting for the award: the {p} bid period's pages name no crew yet. One page is read per run",
                  "until names appear, then the whole period.", ""]
    for p in sorted(pilots.values(), key=lambda p: (p["name"], p["emp"])):
        lines += [f"### {p['name']} ({p['emp'] or '?'})", "", "| Date | Pairing | Seat | Route | Days |",
                  "|---|---|---|---|---|"]
        lines += [f"| {d} | {pr} | {pos} | {rt} | {dy} |" for d, pr, pos, rt, dy in sorted(p["trips"])]
        lines.append("")
    return "\n".join(lines)


def _file_bound(pdir, month, key):
    """FW-0014: the bid period's 'start' / 'end' (ISO) that pdfs.py writes into the pairing file, or ''."""
    try:
        v = str(json.load(open(os.path.join(pdir, f"pairings_{month}.json"))).get(key) or "")
    except (OSError, ValueError, TypeError, AttributeError):
        return ""
    return v if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v) else ""


def _day_lists(pdir, month):
    """The 'days' token lists of `month`'s pairing file, or None when there is no readable file."""
    try:
        d = json.load(open(os.path.join(pdir, f"pairings_{month}.json")))
        i = (d.get("cols") or []).index("days")
        return [str(r[i] or "").split() for r in d.get("rows") or [] if len(r) > i]
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def file_next_to(month, day_lists):
    """The last next-month day of the bid period ('D1' in November = Dec 1, as pdfs.py writes days past the
    month end), judged over the whole file (largest D day that is not a wrapped last-month one), else None."""
    found = []
    for toks in day_lists or []:
        prev = _prev_tokens(month, toks)
        found += [int(t[1:]) for i, t in enumerate(toks) if i not in prev and t[:1] in "Dd" and t[1:].isdigit()]
    return max(found) if found else None


def period_start(pdir, month):
    """First day of `month`'s bid period, judged from the pairing files the way instances() places their days:
    a last-month day in this month's file ('31' in November = Oct 31), else the day after the previous month's
    period end when that runs into this month ('D1' in November's file: December starts Dec 2), else the 1st."""
    own = _file_bound(pdir, month, "start")
    if own:
        return own
    y, m = _ym(month)
    py, pm = _shift(y, m, -1)
    pf = file_prev_from(month, _day_lists(pdir, month) or [])
    try:
        if pf:
            return date(py, pm, pf).isoformat()
        nx = file_next_to(f"{py}-{pm:02d}", _day_lists(pdir, f"{py}-{pm:02d}"))
        if nx:
            return (date(y, m, nx) + timedelta(days=1)).isoformat()
    except ValueError:
        pass
    return f"{month}-01"


def period_end(pdir, month):
    """Last day of `month`'s bid period (FW-0002): the largest next-month day in this month's file ('D1' in
    November = Dec 1), else the day before the next month's period start when that is in this month ('31' in
    January's file: December ends Dec 30), else the month's last day."""
    own = _file_bound(pdir, month, "end")
    if own:
        return own
    y, m = _ym(month)
    ny, nm = _shift(y, m, 1)
    nxt = f"{ny}-{nm:02d}"
    try:
        nx = file_next_to(month, _day_lists(pdir, month))
        if nx:
            return date(ny, nm, nx).isoformat()
        pf = file_prev_from(nxt, _day_lists(pdir, nxt) or [])
        if pf:
            return (date(y, m, pf) - timedelta(days=1)).isoformat()
    except ValueError:
        pass
    return date(y, m, calendar.monthrange(y, m)[1]).isoformat()


def grid_range(pdir, month):
    """(first, period start, period end) of the pilot card's grid for `month`: FLICA's schedule grid starts on
    the day before the bid period (Oct 31 for a November that runs Nov 1 to Dec 1) and ends on its last day."""
    ps, pe = period_start(pdir, month), period_end(pdir, month)
    return (date.fromisoformat(ps) - timedelta(days=1)).isoformat(), ps, pe


def _hm(v):
    """'12h05' (pairing file) or '12:05' -> '12:05'; anything else ''."""
    m = re.fullmatch(r"\s*(\d{1,3})[h:](\d{2})\s*", str(v or ""))
    return f"{int(m.group(1))}:{m.group(2)}" if m else ""


def _mins(v):
    """'44h55' / '44:55' / 350 -> minutes; None when unreadable."""
    s = str(v if v is not None else "").strip()
    m = re.fullmatch(r"(\d{1,3})[h:](\d{2})", s)
    return int(m.group(1)) * 60 + int(m.group(2)) if m else (int(s) if s.isdigit() else None)


def route_lay(route, it, start="", end=""):
    """FW-0062: the layover when the pairing package has none for a trip: the route's stations other than its base (its
    first station, in route order, '/' joined: 'HNL-LAS-HNL' -> 'LAS'), only when the trip lays over: it runs over more
    than one day (a trip that ends on its start day has no layover, as on the card) and, when the pairing file has
    them, its TAFB is longer than its first duty (a one-duty red-eye turn, HNL-PPT-HNL released the next day, has
    none). '' otherwise."""
    st = [s for s in str(route or "").split("-") if s.strip()]
    if len(st) < 2:
        return ""
    days = (end > start) if start and end else None
    tafb, first = _mins((it or {}).get("tafb")), _mins((it or {}).get("first_duty_min"))
    duties = tafb > first + 60 if tafb is not None and first is not None else None
    if days is False or not (duties if duties is not None else days):
        return ""
    outs = []
    for s in st[1:]:
        if s != st[0] and s not in outs:
            outs.append(s)
    return "/".join(outs)


def _details_for(details, period):
    """FW-0062: the pairing package details of one bid period. `details` is a function of the period (the
    Watcher's pkg_details_for), {period: {pid: det}}, or (older callers) one flat {pid: det} for every trip."""
    if callable(details):
        return details(period) or {}
    if details and all(re.fullmatch(r"\d{4}-\d{2}", str(k)) for k in details):
        return details.get(period) or {}
    return details or {}


def pilot_trips(insts, rows_for_emp, month=None, start_from=None, crew_rows=None, details=None, end_to=None):
    """reconstructed list for the pilot lookup, by start: [{pairing, start, end, seat, route, checked_at, lay, blk,
    credit, soft, crew, period, n}]. month keeps the trips on any of its days; start_from / end_to (ISO, inclusive;
    FW-0002, grid_range: the day before the bid period to its last day, which can be in the next month) replace that
    calendar-month test on their side; a trip that starts before the range and runs into it is kept. FW-0002: the card draws these in the schedule grid, so each trip also carries
    the layover, block and credit from the pairing package (`details`, pdfs.package_details; each falls back to the
    pairing file: its credit and block columns, the layover from its route, route_lay) and the crew line it was read
    with (`crew_rows`, [[pos, name]]); '' / [] when unknown.
    FW-0062: details are looked up in the trip's own bid period (a trip from October's file on the grid's first
    row, Oct 31, gets October's package, not November's; the same id can be another trip in another month), by the
    exact id, else the id without its trailing letter; n is the pilots on the whole crew line (OPEN seats count,
    flight attendants do not), for the PWA 4.O.1 overrides."""
    out, crew_rows = [], crew_rows or {}
    lo, hi = start_from or (f"{month}-01" if month else ""), end_to or (f"{month}-31" if month else "~")
    for r in rows_for_emp:
        it = insts.get(r["key"]) or {}
        start = r.get("date") or it.get("date") or ""
        end = r.get("end_date") or it.get("end_date") or start
        if not start or start > hi or end < lo:  # 1.3.0 review: a trip running into the grid from before it counts
            continue
        pid = r.get("pairing") or it.get("pairing") or ""
        per = period_of(it) if it else start[:7]
        dets = _details_for(details, per)
        det = dets.get(pid) or dets.get(re.sub(r"(?<=\d)[A-Z]$", "", pid)) or {}
        # FW-0062: a period without its package (or a pairing the package lacks) takes block and layover from the
        # pairing file itself ('12h19' block column; the layover from the route), as credit already did
        blk, credit = _hm(det.get("block")) or _hm(it.get("block")), _hm(det.get("credit")) or _hm(it.get("credit"))
        route = r.get("route") or it.get("route") or ""
        line = (crew_rows.get(r["key"]) or {}).get("crew") or []
        crew = [[c.get("pos") or "", c.get("name") or ""] for c in line][:6]
        out.append({"pairing": pid, "start": start, "end": end, "seat": r.get("pos") or "",
                    "route": route, "checked_at": r.get("checked_at") or "",
                    "lay": det.get("lay") or route_lay(route, it, start, end), "blk": blk, "credit": credit,
                    "soft": soft_time(credit, blk) or "",
                    "crew": crew, "period": per, "n": sum(1 for c in line if c.get("pos") in PILOT_POS)})
    return sorted(out, key=lambda x: (x["start"], x["pairing"]))


def _iso_days(start, end, cap):
    d, e = date.fromisoformat(start), date.fromisoformat(end)
    return [(d + timedelta(days=k)).isoformat() for k in range(cap) if d + timedelta(days=k) <= e]


def grid_pick(trips):
    """(grid, also): FW-0062, the same choice as the pilot card's _rebuild: the crew index can hold two trips on
    the same days (a trade between reads), so the newest read goes in the grid and a trip on a day already taken
    goes to `also`. Both sorted by start. A trip without a readable start is left out, as on the card."""
    ok = [dict(t, end=t["end"] if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(t.get("end") or "")) and t["end"] >= t["start"]
               else t["start"]) for t in trips
          if t and t.get("pairing") and re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(t.get("start") or ""))]
    ok.sort(key=lambda t: (t["start"], t["pairing"]))
    ok.sort(key=lambda t: t.get("checked_at") or "", reverse=True)  # stable: newest read first, then start, pairing
    used, grid, also = set(), [], []
    for t in ok:
        ds = _iso_days(t["start"], t["end"], 15)
        if any(d in used for d in ds):
            also.append(t)
            continue
        used.update(ds)
        grid.append(t)
    return sorted(grid, key=lambda t: t["start"]), sorted(also, key=lambda t: (t["start"], t["pairing"]))
