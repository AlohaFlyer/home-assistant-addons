"""Crew index (0.10.1, Ryan): rebuild any HNL A330 pilot's month from the crew lines on the pairing pages.

Pure logic, no network and no MQTT: trip instances from the card's pairing files (www/flica/pairings_<YYYY-MM>.json),
the order the crawl reads them in, the crew line parser and the per-month Markdown. watcher.py does the paced GETs
(read only) and stores the result through store.py (crew_idx / crew_emp tables).
"""
import calendar
import json
import os
import re
from datetime import date, datetime, timedelta

from pot import CREW_RE

CREW_FROM = date(2026, 10, 31)  # nothing before this is read
PILOT_POS = ("CA", "FO", "RO", "SO")
FILE_RE = re.compile(r"^pairings_(\d{4})-(\d{2})\.json$")
WRAP_MIN = 25  # a day number above this, ahead of a smaller one in the same list, is last month's
SOON_H = 72
SOON_STALE_H = 6
FAIL_RETRY_H = 24
FAIL_MAX_PAST = 3  # a departed instance that keeps failing is given up after this many tries


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


def instances(pdir, crew_from=CREW_FROM):
    """{key 'H3601|2026-11-02': {key, pairing, date, end_date, report, route, days, month}} from every pairing
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
            ix = {c: cols.index(c) for c in ("id", "report", "rel_days", "route", "days") if c in cols}
            rows = d.get("rows") or []
        except Exception:
            continue
        if "id" not in ix or "days" not in ix:
            continue
        lists = [str(r[ix["days"]] or "").split() for r in rows if len(r) > ix["days"]]
        prev_from = file_prev_from(month, lists)
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
                                   "days": max(rel, 0) + 1, "month": dt.strftime("%Y-%m")})
    return out


def departs(inst):
    """HST wall-clock departure (report time on the start date; 00:00 when unknown)."""
    d = datetime.fromisoformat(inst["date"])
    m = re.match(r"^\s*(\d{1,2}):(\d{2})", inst.get("report") or "")
    return d.replace(hour=int(m.group(1)), minute=int(m.group(2))) if m and int(m.group(1)) < 24 else d


def queue(insts, rows, now, run_started=None):
    """Keys to read, in order: (1) never checked, soonest first (past dates too); (1b) failed more than
    FAIL_RETRY_H ago; (2) departing within SOON_H and checked more than SOON_STALE_H ago; (2b) departed
    but last checked before departure (one read for the final crew); (3) the oldest-checked future ones.
    Departed instances checked after departure are never re-read; nothing read in this run is read again.
    `now` and checked_at are HST wall clock (naive ISO)."""
    nowi = now.isoformat()
    soon = (now + timedelta(hours=SOON_H)).isoformat()
    stale = (now - timedelta(hours=SOON_STALE_H)).isoformat()
    retry = (now - timedelta(hours=FAIL_RETRY_H)).isoformat()
    c1, c1b, c2, c2b, c3 = [], [], [], [], []
    for k, it in insts.items():
        r = rows.get(k)
        dep = departs(it).isoformat()
        if not r or not r.get("checked_at"):
            c1.append((dep, k))
            continue
        at = r["checked_at"]
        if run_started and at >= run_started:
            continue
        if r.get("status") != "ok":
            if at < retry and (dep > nowi or int(r.get("tries") or 0) < FAIL_MAX_PAST):
                c1b.append((dep, k))
            continue
        if dep <= nowi:
            if at < dep:
                c2b.append((dep, k))
            continue
        if dep <= soon:
            if at < stale:
                c2.append((dep, k))
            continue
        c3.append((at, dep, k))
    return ([k for _, k in sorted(c1)] + [k for _, k in sorted(c1b)] + [k for _, k in sorted(c2)]
            + [k for _, k in sorted(c2b)] + [k for *_, k in sorted(c3)])


NAME_RE = re.compile(r"^([a-z][a-z'.\- ]*?(?: jr| sr| ii| iii)?,\s*[a-z][a-z'.\-]*(?:\s[a-z][a-z'.\-]*)?)\b", re.I)


def crew_line(text):
    """[{pos, name, emp}] from a pairing page's crew line, in page order (OPEN seats kept, name 'OPEN', emp '');
    None when the page has no crew line. Same regex as pot.parse_crew / crew_ids."""
    m = re.search(r"crew\s*:\s*(.*)$", text or "", re.I | re.S)
    if not m:
        return None
    out = []
    for pos, emp, name in CREW_RE.findall(m.group(1)):
        name = name.strip(" ,")
        if name.lower() == "open":
            out.append({"pos": pos.upper(), "name": "OPEN", "emp": ""})
            continue
        nm = NAME_RE.match(name)  # the last name on the line can run into page text after it
        out.append({"pos": pos.upper(), "name": (nm.group(1) if nm else name[:40]).strip().title(), "emp": emp or ""})
    return out


def coverage(insts, rows, month=None):
    """(instances, checked ok, percent) over all instances or one month's."""
    ks = [k for k, it in insts.items() if not month or it["month"] == month]
    ok = sum(1 for k in ks if (rows.get(k) or {}).get("status") == "ok")
    return len(ks), ok, round(100.0 * ok / len(ks), 1) if ks else 0.0


def render_month(month, insts, rows, now_s):
    """Markdown for one month: header, then one section per pilot (sorted by name) with a table of trips."""
    n, ok, pct = coverage(insts, rows, month)
    fails = sum(1 for k, it in insts.items() if it["month"] == month and (rows.get(k) or {}).get("status") == "fail")
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
             f"Coverage {pct}% ({ok} of {n} trip instances read, {fails} failed). Updated {now_s} HST.",
             "Rebuilt from the crew lines on FLICA pairing pages (read only). A trip picked up or dropped after",
             "it was read shows the crew at the time of the read.", ""]
    for p in sorted(pilots.values(), key=lambda p: (p["name"], p["emp"])):
        lines += [f"### {p['name']} ({p['emp'] or '?'})", "", "| Date | Pairing | Seat | Route | Days |",
                  "|---|---|---|---|---|"]
        lines += [f"| {d} | {pr} | {pos} | {rt} | {dy} |" for d, pr, pos, rt, dy in sorted(p["trips"])]
        lines.append("")
    return "\n".join(lines)


def pilot_trips(insts, rows_for_emp, month=None):
    """reconstructed list for the pilot lookup: [{pairing, start, end, seat, route, checked_at}] by start."""
    out = []
    for r in rows_for_emp:
        it = insts.get(r["key"]) or {}
        start = r.get("date") or it.get("date") or ""
        if month and start[:7] != month:
            continue
        out.append({"pairing": r.get("pairing") or it.get("pairing") or "", "start": start,
                    "end": r.get("end_date") or it.get("end_date") or start, "seat": r.get("pos") or "",
                    "route": r.get("route") or it.get("route") or "", "checked_at": r.get("checked_at") or ""})
    return sorted(out, key=lambda x: (x["start"], x["pairing"]))
