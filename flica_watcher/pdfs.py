"""Monthly PDFs (0.9.1, Ryan 2026-11-05): parse `pdftotext -layout` text of
  * the Pilot Pairings package ("11 - November 2026 Pilot Pairings Rev. 1.pdf") into the schedule card's pairing
    file /config/www/flica/pairings_<YYYY-MM>.json (cols id, report, dep, release, rel_days, first_duty_min,
    route, credit, tafb, days), A332 HNL pairings only;
  * the PBS bid-run award ("A332FO PBS BID RUN Award--NOV 2026 ...") into one pilot's awarded line (the
    month's .001 starting schedule).
Pure text parsing; nothing here touches FLICA."""
import re

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


def _cal_days(lines, ndays, start=1, mlen=31):
    """The operating dates printed down the right edge, one cell per day of the bid period in order ('--' =
    not operating). The period runs from the 1st for ndays (Nov 1 to Dec 1 = 31), so a cell past the end of
    the month is next month (D<n>, as the card expects)."""
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
        d = int(t)
        days.append(str(d) if start + i <= mlen else f"D{d}")
    return days


def period_days(text):
    """'November 1 —December 1 (31 Days)' -> 31."""
    m = re.search(r"\((\d{2}) Days\)", text)
    return int(m.group(1)) if m else 31


def period_start(text):
    """'December 2 —December 31 (30 Days)' -> 2 (the bid period does not always start on the 1st)."""
    m = re.search(r"(" + "|".join(MONTHS) + r")\s+(\d{1,2})\s*\W+\s*(?:" + "|".join(MONTHS) + r")\s+\d{1,2}\s*\(\d{2} Days\)", text, re.I)
    return int(m.group(2)) if m else 1


def parse_package(text, base="HNL", eqp="33"):
    """Rows for the card's pairing file, in package order."""
    import calendar
    rows, nd, st = [], period_days(text), period_start(text)
    mk = package_month(text)
    mlen = calendar.monthrange(int(mk[:4]), int(mk[5:7]))[1] if mk else 31
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
                     " ".join(_cal_days(b["pre"] + b["lines"], nd, st, mlen))])
    return rows


def package_json(text, source, base="HNL", eqp="33"):
    return {"month": package_month(text), "source": source,
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


def parse_award(text, emp, details, month):
    """One pilot's awarded line from the PBS bid-run award: {items, days, totals, updated, trips} in the shape
    the Watcher stores a FLICA month (items {trip,start,end,lay}; days [[iso, code, lay]]), trips carrying
    block / credit / seat / duties from the pairing package. None when the pilot is not in the award."""
    import calendar
    from datetime import date, timedelta
    lines = text.splitlines()
    i = next((k for k, ln in enumerate(lines) if re.match(rf"^\d{{5}}\s*/\s*{emp}\b", ln)), None)
    if i is None:
        return None
    hdr = next(lines[k] for k in range(i, 0, -1) if re.match(r"^\s+1\s+2\s+3\s", lines[k]))
    cols = _cols(hdr)
    y, mo = int(month[:4]), int(month[5:7])

    def day_at(pos):
        c = min(cols, key=lambda c: abs(c[0] - pos))
        idx = cols.index(c)
        return date(y, mo, 1) + timedelta(days=idx)  # the header runs from the 1st, one column per day

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
    mlen = calendar.monthrange(y, mo)[1]
    last = max([date.fromisoformat(it["end"]) for it in items] + [date(y, mo, mlen)])
    days = []
    for k in range((last - date(y, mo, 1)).days + 1):  # spill days past the month end, as FLICA shows them
        d = date(y, mo, 1) + timedelta(days=k)
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
