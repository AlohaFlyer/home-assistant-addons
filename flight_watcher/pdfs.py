"""Monthly PDFs (0.9.1, Ryan 2026-11-05): parse `pdftotext -layout` text of
  * the Pilot Pairings package ("11 - November 2026 Pilot Pairings Rev. 1.pdf") into the schedule card's pairing
    file /config/www/flight-watcher/pairings_<YYYY-MM>.json (cols id, report, dep, release, rel_days, first_duty_min,
    route, credit, tafb, days), A332 HNL pairings only;
  * the PBS bid-run award ("A332FO PBS BID RUN Award--NOV 2026 ...") into one pilot's awarded line (the
    month's .001 starting schedule).
Pure text parsing; nothing here touches FLICA."""
import calendar
import re
from datetime import date, timedelta

PAIR_HDR = re.compile(r"^\s*(H\d{4}[A-Z]?)\s+BASE REPT:\s+(\d{1,2}:\d{2})L")
BASE_RE = re.compile(r"BASE\s*:\s*([A-Z]{3})")
LEG_RE = re.compile(r"^\s*\S+\s+(DH\s+)?(?:\d{1,4}[A-Z]?\*?)\s+([A-Z]{3})\s*-\s*([A-Z]{3})\s+(\d{1,2}:\d{2})/\d{1,2}:\d{2}\s+\d{1,2}:\d{2}/\d{1,2}:\d{2}\s+\d+h\d{2}\s+\d{1,2}:\d{2}(?:\s+\d{1,2}:\d{2})?\s+(\w{3})\b")
DEND_RE = re.compile(r"D-END:\s+(\d{1,2}:\d{2})L")
TOT_RE = re.compile(r"TOTALS\s+BLOCK\s+(\d+h\d{2}).*?CREDIT\s+(\d+h\d{2})\s+T\.A\.F\.B\.\s+(\d+h\d{2})")
CAL_RE = re.compile(r"((?:\s+(?:\d{2}|--))+)\s*$")
MONTHS = ["JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE", "JULY", "AUGUST", "SEPTEMBER", "OCTOBER",
          "NOVEMBER", "DECEMBER"]


def _min(hm):
    h, m = re.split(r"[:h]", hm)
    return int(h) * 60 + int(m)


def _hm(m):
    return f"{m // 60:02d}:{m % 60:02d}"


def package_month(text):
    """'2026-11' from 'November 2026 Pairing Package'."""
    m = re.search(r"(" + "|".join(MONTHS) + r")\s+(\d{4})\s+Pairing Package", text, re.I)
    return f"{m.group(2)}-{MONTHS.index(m.group(1).upper()) + 1:02d}" if m else ""


def _blocks(text):
    """Split the package into pairing blocks: from a 'Hxxxx BASE REPT' line to the '====' rule."""
    cur, pre = None, []
    for ln in text.splitlines():
        h = PAIR_HDR.match(ln)
        if h:
            # some blocks print their first calendar cell above the header line: keep the lines since the last rule
            cur = {"id": h.group(1), "report": h.group(2), "lines": [ln], "pre": [x for x in pre if "DAY" not in x]}
            pre = []
            continue
        if cur is None:
            pre = [] if ln.strip().startswith("=====") else pre + [ln]
            continue
        if ln.strip().startswith("====="):
            yield cur
            cur, pre = None, []
            continue
        cur["lines"].append(ln)


def _cal_days(lines, ndays, start, month):
    """The operating dates printed down the right edge, one cell per day of the bid period in order ('--' =
    not operating). Cell i is the period's first day (`start`, a date) + i days (FW-0014: by date, so a period
    that starts last month, Dec 31 to Jan 30 in January, is not shifted). A day after the package `month`
    ('2026-11') is next month (D<n>, as the card expects); a day of the package month or of the month before
    is its plain number ('31 1 2' in January: Dec 31, Jan 1, Jan 2; crewidx and the card place it with the
    file's 'start')."""
    ym = (int(month[:4]), int(month[5:7]))
    toks = []
    for ln in lines:
        if "Mo Tu We" in ln:
            continue
        m = CAL_RE.search(ln)
        if m and ln.rfind(m.group(1).strip()) >= 100:
            toks += m.group(1).split()
    days = []
    for i, t in enumerate(toks[:ndays]):
        if t == "--":
            continue
        d = start + timedelta(days=i)
        days.append(f"D{int(t)}" if (d.year, d.month) > ym else str(int(t)))
    return days


def period_days(text):
    """'November 1 —December 1 (31 Days)' -> 31."""
    m = re.search(r"\((\d{2}) Days\)", text)
    return int(m.group(1)) if m else 31


def _shift(y, m, k):
    y2, m2 = divmod(y * 12 + m - 1 + k, 12)
    return y2, m2 + 1


def period_start(text, month=""):
    """The bid period's first day as a date (FW-0014: with its month and year, not only the day number):
    'December 2 —December 31 (30 Days)' in the December 2026 package -> 2026-12-02, 'December 31 —January 30
    (31 Days)' in the January 2027 package -> 2026-12-31. `month` ('2027-01') defaults to package_month(text);
    without a period line the 1st of that month (None without a month either)."""
    month = month or package_month(text)
    if not month:
        return None
    y, m = int(month[:4]), int(month[5:7])
    hit = re.search(r"(" + "|".join(MONTHS) + r")\s+(\d{1,2})\s*\W+\s*(?:" + "|".join(MONTHS) + r")\s+\d{1,2}\s*\(\d{2} Days\)", text, re.I)
    if hit:
        sm = MONTHS.index(hit.group(1).upper()) + 1
        for k in (0, -1, 1):  # the package month, the month before (Dec 31 for January), the month after
            sy, sm2 = _shift(y, m, k)
            if sm2 == sm:
                try:
                    return date(sy, sm2, int(hit.group(2)))
                except ValueError:
                    break
    return date(y, m, 1)


def period_bounds(text, month=""):
    """(first day, last day) of the bid period as ISO dates, '' when the package names no month."""
    st = period_start(text, month)
    if not st:
        return "", ""
    return st.isoformat(), (st + timedelta(days=period_days(text) - 1)).isoformat()


def parse_package(text, base="HNL", eqp="33"):
    """Rows for the card's pairing file, in package order."""
    rows, nd = [], period_days(text)
    mk = package_month(text)
    st = period_start(text, mk) or date(2000, 1, 1)
    mk = mk or st.strftime("%Y-%m")
    for b in _blocks(text):
        body = "\n".join(b["lines"])
        bm = BASE_RE.search(body)
        if not bm or bm.group(1) != base:
            continue
        legs = [m for m in (LEG_RE.match(ln) for ln in b["lines"]) if m]
        flown = [m for m in legs if not m.group(1)]  # deadheads ride other equipment (717 interisland)
        if not flown or any(not m.group(5).startswith(eqp) for m in flown):  # A330: 332, or 33L in December
            continue
        tot = TOT_RE.search(body)
        dend = DEND_RE.search(body)
        if not tot or not dend:
            continue
        route = [legs[0].group(2)]
        for m in legs:
            if route[-1] != m.group(2):
                route.append(m.group(2))
            route.append(m.group(3))
        if route[0] != base or route[-1] != base:
            continue
        rep = _min(b["report"])
        end = rep + _min(tot.group(3))
        rows.append([b["id"], _hm(rep), legs[0].group(4).zfill(5), _hm(end % 1440), end // 1440,
                     (_min(dend.group(1)) - rep) % 1440, "-".join(route), tot.group(2), tot.group(3),
                     " ".join(_cal_days(b["pre"] + b["lines"], nd, st, mk))])
    return rows


def package_json(text, source, base="HNL", eqp="33"):
    """The card's pairing file. FW-0014: start / end are the bid period's first and last day (ISO), so a reader
    can place a last-month day ('31' in January = Dec 31) without guessing."""
    start, end = period_bounds(text)
    return {"month": package_month(text), "source": source, "start": start, "end": end,
            "cols": ["id", "report", "dep", "release", "rel_days", "first_duty_min", "route", "credit", "tafb", "days"],
            "rows": parse_package(text, base, eqp)}


FLEG_RE = re.compile(r"^\s*(\S+)\s+(DH\s+)?(?:\d{1,4}[A-Z]?\*?)\s+([A-Z]{3})\s*-\s*([A-Z]{3})\s+(\d{1,2}:\d{2})/(\d{1,2}:\d{2})\s+"
                     r"(\d{1,2}:\d{2})/(\d{1,2}:\d{2})\s+(\d+)h(\d{2})(.*)$")
LAYO_RE = re.compile(r"(\d+h\d{2})\s+(\d+h\d{2})\s+(\d+h\d{2})\s+(\d+h\d{2})\s*(?:\s{2,}|$)")


def package_details(text, base="HNL", eqp="33"):
    """{pairing: {report, block, credit, tafb, rel_days, lay, route, duties}} for the A330 HNL pairings. duties
    are in HST minutes from 00:00 HST of the report day, the shape the Watcher reads from FLICA:
    [{d, dep, arr, stn, blk}], one per duty period (blk = flown block, deadheads excluded). Times come from
    the GMT columns; each duty after a layover is placed from the previous release plus the printed layover."""
    rows = {r[0]: r for r in parse_package(text, base, eqp)}
    out = {}
    for b in _blocks(text):
        if b["id"] not in rows:
            continue
        r = rows[b["id"]]
        rep = _min(b["report"])
        duties, cur, last_arr, next_min = [], None, None, rep
        for ln in b["lines"]:
            m = FLEG_RE.match(ln)
            if m:
                g = _min(m.group(6))
                tod = (g - 600) % 1440  # GMT -> HST
                dep = tod + 1440 * max(0, -(-(next_min - tod) // 1440))  # first HST time at or after next_min
                arr = dep + int(m.group(9)) * 60 + int(m.group(10))
                if cur is None:
                    cur = {"dep": dep, "arr": arr, "stn": m.group(4), "blk": 0}
                cur["arr"], cur["stn"] = arr, m.group(4)
                if not m.group(2):
                    cur["blk"] += int(m.group(9)) * 60 + int(m.group(10))
                last_arr, next_min = arr, arr
                lay = LAYO_RE.search(m.group(11))
                if lay:  # end of a duty with a layover after it: next report = release + layover
                    cur["layo"] = _min(lay.group(4))
                continue
            if ln.strip().startswith("D-END") and cur is not None:
                cur["d"] = cur["dep"] // 1440
                end = last_arr + 15
                next_min = end + cur.pop("layo", 0)
                duties.append(cur)
                cur = None
        tot = TOT_RE.search("\n".join(b["lines"]))
        lay = next((d["stn"] for d in duties if d["stn"] != base), "")
        out[b["id"]] = {"report": r[1], "block": tot.group(1).replace("h", ":") if tot else "", "credit": r[7].replace("h", ":"),
                        "tafb": r[8], "rel_days": r[4], "lay": lay, "route": r[6], "duties": duties}
    return out


def _cols(line):
    """Column start of each day number in the award's date header."""
    return [(m.start(), int(m.group())) for m in re.finditer(r"\b\d{1,2}\b", line)]


def _day_header(line):
    """FW-0015: the award's date header as [(column, day)]: a line of day numbers only, at least 7, each the day
    after the one before ('2 3 4 ... 31' in December, '1 2 ... 30 1' in November, '31 1 2 ...' for a period
    that starts last month); None for any other line."""
    if not line.strip() or re.search(r"[^\d\s]", line):
        return None
    cols = _cols(line)
    if len(cols) < 7 or any(not (b == a + 1 or (b == 1 and a >= 28)) for (_, a), (_, b) in zip(cols, cols[1:])):
        return None
    return cols


def award_start(cols, month, start=None):
    """FW-0015: the date of the header's first column. `start` (the pairing package's period start, ISO or a
    date) wins when its day matches; else the first number is a day of `month` unless the header runs from it
    to the end of the month before and wraps to 1 ('31 1 2' in January: Dec 31)."""
    y, mo = int(month[:4]), int(month[5:7])
    d0 = cols[0][1]
    try:
        st = start if isinstance(start, date) else date.fromisoformat(str(start or "")[:10])
    except ValueError:
        st = None
    if st and st.day == d0:
        return st
    wrap = next((k for k in range(1, len(cols)) if cols[k][1] < cols[k - 1][1]), None)
    py, pm = _shift(y, mo, -1)
    if d0 > 1 and wrap is not None and d0 + wrap - 1 == calendar.monthrange(py, pm)[1]:
        return date(py, pm, d0)
    return date(y, mo, d0)


def parse_award(text, emp, details, month, pstart=None):
    """One pilot's awarded line from the PBS bid-run award: {items, days, totals, updated, trips} in the shape
    the Watcher stores a FLICA month (items {trip,start,end,lay}; days [[iso, code, lay]]), trips carrying
    block / credit / seat / duties from the pairing package. None when the pilot is not in the award.
    FW-0015: the date header runs from the bid period's first day (Dec 2 in December), one column per day;
    `pstart` is the package's period start when known (award_start). ValueError when no header is found."""
    lines = text.splitlines()
    i = next((k for k, ln in enumerate(lines) if re.match(rf"^\d{{5}}\s*/\s*{emp}\b", ln)), None)
    if i is None:
        return None
    cols = next((c for c in (_day_header(lines[k]) for k in range(i, -1, -1)) if c), None)
    if not cols:
        raise ValueError("no date header (a line of day numbers) above the pilot's line")
    y, mo = int(month[:4]), int(month[5:7])
    first = award_start(cols, month, pstart)

    def day_at(pos):
        c = min(cols, key=lambda c: abs(c[0] - pos))
        return first + timedelta(days=cols.index(c))  # one column per day from the period's first day

    ids, seats, crs = lines[i + 3], lines[i + 4], lines[i + 2]
    items, trips = [], {}
    for m in re.finditer(r"\b(H\d{4}[A-Z]?|VA)\b", ids):
        start = day_at(m.start())
        if m.group(1) == "VA":
            cr = re.search(r"(\d{3}):(\d{2})", crs[m.start():m.start() + 10])
            n = max(1, (int(cr.group(1)) * 60 + int(cr.group(2))) // 240) if cr else 1  # 4:00 a day (PWA 6.J)
            items.append({"trip": "VAC", "start": start.isoformat(), "end": (start + timedelta(days=n - 1)).isoformat(), "lay": ""})
            continue
        dt = details.get(m.group(1)) or {}
        end = start + timedelta(days=int(dt.get("rel_days") or 0))
        items.append({"trip": m.group(1), "start": start.isoformat(), "end": end.isoformat(), "lay": dt.get("lay", "")})
        seat = seats[m.start():m.start() + 4].strip()
        trips[f"{m.group(1)}|{start.isoformat()}"] = {k: v for k, v in {
            "blk": dt.get("block"), "credit": dt.get("credit"), "seat": seat, "report": dt.get("report"),
            "duties": dt.get("duties")}.items() if v}
    # the period's last day: the header's last column when it spans the period, else the month's last day
    pend = first + timedelta(days=len(cols) - 1) if len(cols) >= 28 else date(y, mo, calendar.monthrange(y, mo)[1])
    last = max([date.fromisoformat(it["end"]) for it in items] + [pend])
    days = []
    for k in range((last - first).days + 1):  # from the period's first day; spill days past its end, as FLICA shows them
        d = first + timedelta(days=k)
        iso, code, lay = d.isoformat(), "", ""
        for it in items:
            if it["start"] <= iso <= it["end"]:
                if it["trip"] == "VAC":
                    code = "VAC"
                elif iso == it["start"]:
                    code, lay = it["trip"], it["lay"] or "-"
                else:
                    lay = "HNL" if iso == it["end"] else "-"
        days.append([iso, code, lay])
    cr = re.search(r"Cr:(\d{3}):(\d{2})", lines[i + 2])
    off = re.search(r"Days Off:\s*(\d+)", lines[i + 3])
    totals = {}
    if cr:
        totals["credit"] = f"{int(cr.group(1))}:{cr.group(2)}"
    if off:
        totals["days_off"] = int(off.group(1))
    posted = re.search(r"Posted\s+([A-Za-z]+ \d{1,2}, \d{4})", text)
    return {"items": items, "days": days, "totals": totals, "updated": f"Award posted {posted.group(1)}" if posted else "Award",
            "trips": trips}
