"""Monthly PDFs (0.9.1, Ryan 2026-11-05): parse `pdftotext -layout` text of
  * the Pilot Pairings package ("11 - November 2026 Pilot Pairings Rev. 1.pdf") into the schedule card's pairing
    file /config/www/flight-watcher/pairings_<YYYY-MM>.json (cols id, report, dep, release, rel_days, first_duty_min,
    route, credit, tafb, days), A332 HNL pairings only, and (1.7.7) each one's legs, duties, layovers and totals for
    the pairing detail panel (package_legs);
  * the PBS bid-run award ("A332FO PBS BID RUN Award--NOV 2026 ...") into one pilot's awarded line (the
    month's .001 starting schedule).
Pure text parsing; nothing here touches FLICA."""
import calendar
import json
import re
from datetime import date, timedelta

PAIR_HDR = re.compile(r"^\s*(H\d{4}[A-Z]?)\s+BASE REPT:\s+(\d{1,2}:\d{2})L")
BASE_RE = re.compile(r"BASE\s*:\s*([A-Z]{3})")
LEG_RE = re.compile(r"^\s*\S+\s+(DH\s+)?(?:\d{1,4}[A-Z]?\*?)\s+([A-Z]{3})\s*-\s*([A-Z]{3})\s+(\d{1,2}:\d{2})/\d{1,2}:\d{2}\s+\d{1,2}:\d{2}/\d{1,2}:\d{2}\s+\d+h\d{2}\s+\d{1,2}:\d{2}(?:\s+\d{1,2}:\d{2})?\s+(\w{3})\b")
DEND_RE = re.compile(r"D-END:\s+(\d{1,2}:\d{2})L")
TOT_RE = re.compile(r"TOTALS\s+BLOCK\s+(\d+h\d{2}).*?CREDIT\s+(\d+h\d{2})\s+T\.A\.F\.B\.\s+(\d+h\d{2})")
CAL_RE = re.compile(r"((?:\s+(?:\d{2}|--))+)\s*$")
# 1.7.2 (review of contract 1 revision 3): CAL_RE.search takes time quadratic in a line's length (every start position
# backtracks through the run after it), so a pilot's crafted package with long lines kept a thread busy for minutes.
# _cal_tail finds the same run in one pass: CAL_TAIL_RE matched once at the start of the line reversed.
CAL_TAIL_RE = re.compile(r"\s*((?:(?:\d{2}|--)\s+)+)")
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


# The bid period line ('December 2', a dash, 'December 31 (30 Days)'). 1.7.2 (review): \W+ between the two dates,
# as before (\s*\W+\s* matched exactly the same text, since a space is a \W too), but its three overlapping runs took
# cubic time to fail: "January 1" then 1200 empty pages froze the Watcher (re holds the GIL) for minutes
PERIOD_RE = re.compile(r"(" + "|".join(MONTHS) + r")\s+(\d{1,2})\W+(?:" + "|".join(MONTHS) + r")\s+\d{1,2}\s*\(\d{2} Days\)",
                       re.I)


def _cal_tail(ln):
    """What CAL_RE.search(ln).group(1) gives (the run of day cells at the line's right end, each after whitespace),
    or None, in time linear in the line: the run read backwards from the end (CAL_TAIL_RE on the reversed line)."""
    m = CAL_TAIL_RE.match(ln[::-1])
    return m.group(1)[::-1] if m else None


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
            if ln.strip().startswith("====="):
                pre = []
            else:
                pre.append(ln)  # 1.7.2: append, not pre + [ln] (a copy per line: quadratic in the lines before a header)
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
        run = _cal_tail(ln)  # 1.7.2: CAL_RE's run in linear time
        if run and ln.rfind(run.strip()) >= 100:
            toks += run.split()
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
    hit = PERIOD_RE.search(text)
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


def _accepted(text, base="HNL", eqp="33"):
    """The pairing blocks the card's pairing file keeps, in package order: based at base, every flown leg on eqp
    equipment (A330: 332, or 33L in December; deadheads ride other equipment, the 717 interisland), a TOTALS and a
    D-END line, and a route from base back to base. Yields (block, legs, totals match, D-END match, route)."""
    for b in _blocks(text):
        body = "\n".join(b["lines"])
        bm = BASE_RE.search(body)
        if not bm or bm.group(1) != base:
            continue
        legs = [m for m in (LEG_RE.match(ln) for ln in b["lines"]) if m]
        flown = [m for m in legs if not m.group(1)]
        if not flown or any(not m.group(5).startswith(eqp) for m in flown):
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
        yield b, legs, tot, dend, route


def parse_package(text, base="HNL", eqp="33"):
    """Rows for the card's pairing file, in package order (_accepted)."""
    rows, nd = [], period_days(text)
    mk = package_month(text)
    st = period_start(text, mk) or date(2000, 1, 1)
    mk = mk or st.strftime("%Y-%m")
    for b, legs, tot, dend, route in _accepted(text, base, eqp):
        rep = _min(b["report"])
        end = rep + _min(tot.group(3))
        rows.append([b["id"], _hm(rep), legs[0].group(4).zfill(5), _hm(end % 1440), end // 1440,
                     (_min(dend.group(1)) - rep) % 1440, "-".join(route), tot.group(2), tot.group(3),
                     " ".join(_cal_days(b["pre"] + b["lines"], nd, st, mk))])
    return rows


def package_json(text, source, base="HNL", eqp="33"):
    """The card's pairing file. FW-0014: start / end are the bid period's first and last day (ISO), so a reader
    can place a last-month day ('31' in January = Dec 31) without guessing. 1.7.7: "detail" holds each row's legs,
    duties, layovers and totals (package_legs) for the pairing detail panel, "dv" the parser that wrote it
    (PKG_PARSER); cols and rows are as before."""
    start, end = period_bounds(text)
    rows = parse_package(text, base, eqp)
    detail, cut = public_detail(package_legs(text, {r[0] for r in rows}, base, eqp))
    out = {"month": package_month(text), "source": source, "start": start, "end": end,
           "cols": ["id", "report", "dep", "release", "rel_days", "first_duty_min", "route", "credit", "tafb", "days"],
           "rows": rows, "dv": PKG_PARSER, "detail": detail}
    if cut:
        out["dcut"] = cut
    return out


# 1.7.7 review: the pairing file is served at a fixed URL with no login (/local/flight-watcher/pairings_<YYYY-MM>.json)
# and every pilot's portal copies it, so it keeps the routes and times only: never the crew hotels or their van
# times (DETAIL_PRIVATE), which stay in the DB (package_hotels) for the pilot's own trips. And it has a whole-file
# budget: a pilot's upload is untrusted, and the portal skips any file over its 8 MB cap (portal.CAPS['file']), rows
# and all. Past DETAIL_FILE_MAX bytes of detail (or DETAIL_MAX_PAIRINGS pairings), the rest have no detail ('dcut'
# counts them) and the card says the package detail is not on file; the rows stay as in 1.7.5.
DETAIL_PRIVATE = ("hotel", "van")
DETAIL_FILE_MAX = 1_500_000
DETAIL_MAX_PAIRINGS = 600


def public_detail(detail):
    """(detail without DETAIL_PRIVATE, number of pairings left out by the budget), in package order."""
    out, size, cut = {}, 0, 0
    for pid, d in detail.items():
        pub = dict(d, duties=[{k: v for k, v in du.items() if k not in DETAIL_PRIVATE} for du in d.get("duties") or []])
        n = len(json.dumps(pub, separators=(",", ":"))) + len(pid) + 4
        if len(out) >= DETAIL_MAX_PAIRINGS or size + n > DETAIL_FILE_MAX:
            cut += 1
            continue
        out[pid] = pub
        size += n
    return out, cut


def package_hotels(text, base="HNL", eqp="33"):
    """{pairing: [[station, hotel, van], ...] one per duty with a layover after it} from package_legs: the hotel lines
    the pairing detail draws for the pilot's own trips (publish_own_trips), kept out of the public pairing file."""
    out = {}
    for pid, d in package_legs(text, None, base, eqp).items():
        du = d.get("duties") or []
        hs = [[x.get("stn") or "", x.get("hotel") or "", x.get("van") or ""] for x in du[:-1]]
        if any(h[1] or h[2] for h in hs):
            out[pid] = hs
    return out


# ---------------------------------------------------------------- 1.7.7: the pairing detail panel
# Ryan, Nov 14: "click on a pairing and have the actual pairing pop open below the schedule", like FLICA's pairing
# printout. Each A330 HNL pairing of the package keeps its legs ([DAY, DH, flight, from, to, departure L, arrival L,
# BLKT, SGCRD, GRNT, EQP], local times as printed), its duties (report and D-END local, TBLK, TCRD, DUTY and LAYO as
# printed, TDHD and FDP computed from the GMT columns: FDP from report to the last flight's block-in, FAR 117.3; a
# deadhead after it is duty, not FDP), each layover's station, hotel name and VAN (layover.hotel_name: never the
# phone; VAN 00:00 is no van time; review: the DB's and the pilot's own trips only, never the public file,
# public_detail) and the TOTALS line, with TRIP RIG as printed or, when none is, credit less the
# summed segment credit (rig_c). A pilot's approved upload is untrusted: lines are cut at DETAIL_LINE_MAX characters
# before any pattern runs, each pattern is anchored with no nested repeats, and legs and duties are capped.
PKG_PARSER = 2  # the pairing file's parser version; the Watcher reads a package text copy again when it changes
DETAIL_MAX_LEGS = 30
DETAIL_MAX_DUTIES = 12
DETAIL_LINE_MAX = 400
DLEG_RE = re.compile(r"^\s*(\S{1,3})\s+(DH\s+)?(\d{1,4}[A-Z]?\*?)\s+([A-Z]{3})\s*-\s*([A-Z]{3})\s+(\d{1,2}:\d{2})/(\d{1,2}:\d{2})\s+"
                     r"(\d{1,2}:\d{2})/(\d{1,2}:\d{2})\s+(\d{1,3}h\d{2})(?:\s+(\d{1,3}:\d{2}))?(?:\s+(\d{1,3}:\d{2}))?\s+(\w{3})\b"
                     r"((?:\s+\d{1,3}h\d{2}){0,4})")
HREPT_RE = re.compile(r"BASE REPT:\s+(\d{1,2}:\d{2})L/(\d{1,2}:\d{2})GMT")
DEND_LG_RE = re.compile(r"^\s*D-END:\s+(\d{1,2}:\d{2})L/(\d{1,2}:\d{2})GMT")
REPT_LG_RE = re.compile(r"^\s*REPT:\s+(\d{1,2}:\d{2})L/(\d{1,2}:\d{2})GMT")
CX_RE = re.compile(r"^\s*BASE\s*:\s*[A-Z]{3}\s+((?:[A-Z]{2}\d{2}){1,6})\b")
TOTS_RE = {k: re.compile(p) for k, p in (("block", r"\bBLOCK\s+(\d{1,3}h\d{2})"), ("fdp", r"\bFDP\s+(\d{1,3}h\d{2})"),
                                         ("dhd", r"\bDHD\s+(\d{1,3}h\d{2})"), ("ldgs", r"\bLDGS:\s*(\d{1,3})\b"),
                                         ("credit", r"\bCREDIT\s+(\d{1,3}h\d{2})"), ("tafb", r"T\.A\.F\.B\.:?\s+(\d{1,3}h\d{2})"))}
RIG_RE = re.compile(r"\bTRIP\s+RIG:?\s+(\d{1,3})[h:](\d{2})\b")


def _dur(m):
    """Minutes as the package prints a duration ('6h42'); '' for None or below zero."""
    return "" if m is None or m < 0 else f"{m // 60}h{m % 60:02d}"


def _hm2m(s):
    """'5:42' or '5h42' -> 342; None for ''."""
    hit = re.fullmatch(r"(\d{1,3})[:h](\d{2})", s or "")
    return int(hit.group(1)) * 60 + int(hit.group(2)) if hit else None


def package_legs(text, ids=None, base="HNL", eqp="33"):
    """{pairing: {eq, crew, rept, duties, tot}} for the pairing blocks whose id is in ids (all when None): the pairing
    detail panel's data (see the note above). eq = the flown legs' equipment, crew = the crew complement code
    ('CA01FO01'), rept = the base report (local). A duty: {legs, rept (its report, local, '' when the package prints
    none), dend, tblk, tcrd, duty, layo, tdhd, fdp, stn (where it ends), hotel, van}. 1.7.7 review: only the blocks the
    pairing file keeps (_accepted: the base, the A330 legs), and the first of them per id, so another fleet's block with
    the same number never replaces an A330 pairing's detail."""
    import layover as LO
    out = {}
    for b, *_ in _accepted(text, base, eqp):
        if (ids is not None and b["id"] not in ids) or b["id"] in out:
            continue
        lines = [ln[:DETAIL_LINE_MAX] for ln in b["lines"]]
        h = HREPT_RE.search(lines[0])
        rep_l, rep_g = (h.group(1).zfill(5), _min(h.group(2))) if h else (b["report"].zfill(5), None)
        crew, eq, duties, cur, nlegs = "", "", [], None, 0
        pend = None  # the duty just ended: its hotel line and the next report follow
        nxt = {"rept": rep_l, "g": rep_g}
        tot_line, rig = "", None
        for ln in lines:
            if not crew:
                c = CX_RE.match(ln)
                if c:
                    crew = c.group(1)
                    continue
            m = DLEG_RE.match(ln)
            if m:
                if nlegs >= DETAIL_MAX_LEGS:
                    continue
                if cur is None:
                    if len(duties) >= DETAIL_MAX_DUTIES:
                        continue
                    if pend is not None and nxt["g"] is None and pend.get("_end") is not None and pend.get("_lay") is not None:
                        nxt["g"] = (pend["_end"] + pend["_lay"]) % 1440  # no REPT line: the release plus the layover
                    cur = {"legs": [], "rept": nxt["rept"], "_g": nxt["g"], "_fl": None, "_dh": 0, "_sg": 0, "_sgok": True}
                    nxt = {"rept": "", "g": None}
                    pend = None
                dh = bool(m.group(2))
                blk = _min(m.group(10))
                sg, gr = m.group(11) or "", m.group(12) or ""
                cur["legs"].append([m.group(1), "DH" if dh else "", m.group(3), m.group(4), m.group(5), m.group(6).zfill(5),
                                    m.group(8).zfill(5), m.group(10), sg, gr, m.group(13)])
                nlegs += 1
                if dh:
                    cur["_dh"] += blk
                else:
                    cur["_fl"] = _min(m.group(9))
                    eq = eq or m.group(13)
                if sg:
                    cur["_sg"] += _hm2m(sg)
                else:
                    cur["_sgok"] = False
                cur["stn"] = m.group(5)
                tail = m.group(14).split()
                if tail:
                    for k, v in zip(("tblk", "tcrd", "duty", "layo"), tail):
                        cur[k] = v
                continue
            d = DEND_LG_RE.match(ln)
            if d and cur is not None:
                cur["dend"] = d.group(1).zfill(5)
                end = _min(d.group(2))
                if cur["_g"] is not None and cur["_fl"] is not None:
                    cur["fdp"] = _dur((cur["_fl"] - cur["_g"]) % 1440)
                if "duty" not in cur and cur["_g"] is not None:
                    cur["duty"] = _dur((end - cur["_g"]) % 1440)
                cur["tdhd"] = _dur(cur["_dh"]) if cur["_dh"] else ""
                duties.append(cur)
                pend, cur = cur, None
                pend["_end"] = end
                pend["_lay"] = _hm2m(pend.get("layo", ""))
                if rig is None:
                    r = RIG_RE.search(ln)
                    rig = int(r.group(1)) * 60 + int(r.group(2)) if r else None
                continue
            if pend is not None and "hotel" not in pend:
                v = LO.PKG_VAN_RE.search(ln)
                if v:
                    van = LO._hm(v.group(1), v.group(2))
                    pend["hotel"], pend["van"] = LO.hotel_name(ln[:v.start()]), "" if van in ("", "00:00") else van
                    continue
            r = REPT_LG_RE.match(ln)
            if r:
                nxt = {"rept": r.group(1).zfill(5), "g": _min(r.group(2))}
                continue
            if "TOTALS" in ln and not tot_line:
                tot_line = ln
                r = RIG_RE.search(ln)
                if r:
                    rig = int(r.group(1)) * 60 + int(r.group(2))
        sgok = all(x["_sgok"] for x in duties)
        sg_all = sum(x["_sg"] for x in duties)
        for x in duties:
            for k in [k for k in x if k.startswith("_")]:
                del x[k]
            for k in ("tblk", "tcrd", "duty", "layo", "tdhd", "fdp", "stn", "hotel", "van", "dend"):
                x.setdefault(k, "")
            if x["layo"] and x is duties[-1]:
                x["layo"] = ""
        tot = {}
        for k, rx in TOTS_RE.items():
            hit = rx.search(tot_line)
            if hit:
                tot[k] = int(hit.group(1)) if k == "ldgs" else hit.group(1)
        if rig is not None:
            tot["rig"] = _dur(rig)
        elif sgok and duties and _hm2m(tot.get("credit")) is not None and _hm2m(tot["credit"]) - sg_all >= 0:
            tot["rig"], tot["rig_c"] = _dur(_hm2m(tot["credit"]) - sg_all), True
        out[b["id"]] = {"eq": eq, "crew": crew, "rept": rep_l, "duties": duties, "tot": tot}
    return out


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


def _day_header(line):
    """FW-0015: the award's date header as [(column, day)]: the run of day numbers the line starts with, at least
    7, each the day after the one before ('2 3 4 ... 31' in December, '1 2 ... 30 1' in November, '31 1 2 ...'
    for a period that starts last month). Whatever follows the run (a label, a stray mark) is ignored, as the
    pre-FW-0015 matcher '^\\s+1\\s+2\\s+3\\s' did; None when the line does not start with such a run."""
    cols = []
    for m in re.finditer(r"\S+", line):
        t = m.group()
        if not re.fullmatch(r"\d{1,2}", t):
            break
        n = int(t)
        if not 1 <= n <= 31 or (cols and not (n == cols[-1][1] + 1 or (n == 1 and cols[-1][1] >= 28))):
            break
        cols.append((m.start(), n))
    return cols if len(cols) >= 7 else None


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


AWARD_PARSER = 2  # 1.8.2 (T5): the award parser's version; the Watcher reads an award text copy again when it changes
MON3 = [m[:3].title() for m in MONTHS]
CARRY_MARK_RE = re.compile(r"\b(" + "|".join(MON3) + r")(\d{1,2})\b")  # 'Nov30': a carry-in's first day
REL_TIME_RE = re.compile(r"(?<![\d:])\d{1,2}:\d{2}(?![\d:])")


def _rel_days(dt):
    try:
        return int((dt or {}).get("rel_days") or 0)
    except (TypeError, ValueError):
        return 0


def parse_award(text, emp, details, month, pstart=None, prev_details=None):
    """One pilot's awarded line from the PBS bid-run award: {items, days, totals, updated, trips} in the shape
    the Watcher stores a FLICA month (items {trip,start,end,lay}; days [[iso, code, lay]]), trips carrying
    block / credit / seat / duties from the pairing package. None when the pilot is not in the award.
    FW-0015: the date header runs from the bid period's first day (Dec 2 in December), one column per day;
    `pstart` is the package's period start when known (award_start). ValueError when no header is found or the
    pilot's line is cut off by the end of the text (1.7.2).
    1.8.2 (T5, LIVE-3): a trip carried in from the bid period before prints in FLICA's C/IN column, left of the first
    day column, with its first day ('Nov30') under it on the line below the pilot's number. It is dated from that
    marker (else from its release day), its details are the previous period's package's (`prev_details`, never this
    period's same-numbered pairing) and period_credit is its Cr row share (this period's part). With no marker, a token
    there is a carry-in only when the previous period's package has it and its release does not print where this
    period's same-numbered pairing releases (else it is that first-day trip, squeezed left; the award is read again
    when the previous package comes).
    Every other pairing (and VA) stays on 1.8.1's nearest day column unless its release time, which prints under its
    last day (start + rel_days), is not under that day and is under the day of the column span that holds it (the cell
    after the previous header): a token squeezed right of the Dec 2 header whose release prints under Dec 5 is a Dec 3
    trip. A line 1.8.1 read right (its releases where its days say) reads the same."""
    lines = text.splitlines()
    i = next((k for k, ln in enumerate(lines) if re.match(rf"^\d{{5}}\s*/\s*{emp}\b", ln)), None)
    if i is None:
        return None
    if i + 4 >= len(lines):  # 1.7.2: its credit, pairing and seat lines are the next four; a line cut off by the end of
        raise ValueError("the pilot's line is cut off at the end of the award")  # the text was an IndexError
    hk = next((k for k in range(i, -1, -1) if _day_header(lines[k])), None)
    if hk is None:
        raise ValueError("no date header (a line of day numbers) above the pilot's line")
    cols = _day_header(lines[hk])
    y, mo = int(month[:4]), int(month[5:7])
    first = award_start(cols, month, pstart)
    hdr = [c[0] for c in cols]

    def near(pos):  # the column nearest a position (a release time prints under its day)
        return min(range(len(hdr)), key=lambda k: abs(hdr[k] - pos))

    def span(pos):  # 1.8.2 (T5): the column whose cell holds a position: the cell after the previous header
        return next((k for k, h in enumerate(hdr) if h >= pos), len(hdr) - 1)

    # 1.8.2 (T5): the C/IN column (the weekday line above the day numbers), the carry-in markers and the release times
    cin = next((m.start() for k in range(max(0, hk - 2), hk + 1) for m in re.finditer(r"C/IN\b", lines[k])), None)
    marks = [(m.start(), m.group(1), int(m.group(2))) for m in CARRY_MARK_RE.finditer(lines[i + 1])]
    rels = [[m.start(), near(m.start()), False] for m in REL_TIME_RE.finditer(lines[i + 1])]

    def rel_on(k, take=False, within=None):  # a release time not yet used printed under day k (0 = the first day)
        r = next((r for r in rels if r[1] == k and not r[2] and (not within or within[0] <= r[0] < within[1])), None)
        if r and take:
            r[2] = True
        return r is not None

    def carry_day(pos):  # a 'Nov30' marker under the token: that day, when it is before the period
        for p, mon, d in marks:
            if abs(p - pos) <= 3:
                mm = MON3.index(mon) + 1
                try:
                    v = date(first.year - (1 if mm > first.month else 0), mm, d)
                except ValueError:
                    return None
                return v if first - timedelta(days=15) <= v < first else None
        return None

    ids, seats, crs = lines[i + 3], lines[i + 4], lines[i + 2]
    items, trips = [], {}
    toks = list(re.finditer(r"\b(H\d{4}[A-Z]?|VA)\b", ids))
    for j, m in enumerate(toks):
        tok, pos = m.group(1), m.start()
        if tok == "VA":
            start = first + timedelta(days=near(pos))  # 1.8.2 (G4A-1): 1.8.1's nearest column (no release to check)
            cr = re.search(r"(\d{3}):(\d{2})", crs[pos:pos + 10])
            n = max(1, (int(cr.group(1)) * 60 + int(cr.group(2))) // 240) if cr else 1  # 4:00 a day (PWA 6.J)
            items.append({"trip": "VAC", "start": start.isoformat(), "end": (start + timedelta(days=n - 1)).isoformat(), "lay": ""})
            continue
        seat = seats[pos:pos + 4].strip()
        cst = carry_day(pos)
        nxt = toks[j + 1].start() if j + 1 < len(toks) else len(ids) + 400
        rk = next((x for x in rels if not x[2] and pos - 2 <= x[0] < nxt), None)  # its release, before the next
        left = pos + len(tok) <= hdr[0] or (cin is not None and abs(pos - cin) < abs(pos - hdr[0]))
        if left and not cst and (tok not in (prev_details or {}) or (
                tok in (details or {}) and rk and rk[1] == _rel_days(details[tok]))):
            left = False  # 1.8.2 (G4A-2): no marker, and not in the previous period's package or its release where this
            # period's same-numbered pairing releases: this period's first-day trip squeezed left, no carry-in
        if cst or left:
            # 1.8.2 (T5): the carry-in: the previous period's trip, this period's share of its credit
            dt = (prev_details or {}).get(tok) or {}
            r = _rel_days(dt)
            if cst is None:  # no marker: its release day less its length, else the day before the period
                cst = first + timedelta(days=rk[1] - r) if rk and r else first - timedelta(days=1)
            end = cst + timedelta(days=r) if dt else (first + timedelta(days=rk[1]) if rk else first)
            end = max(end, first)
            if rk and (first + timedelta(days=rk[1])) == end:
                rk[2] = True
            cr = re.search(r"(\d{3}):(\d{2})", crs[pos:pos + 10])
            share = f"{int(cr.group(1))}:{cr.group(2)}" if cr else None
            items.append({"trip": tok, "start": cst.isoformat(), "end": end.isoformat(), "lay": dt.get("lay", "")})
            trips[f"{tok}|{cst.isoformat()}"] = {k: v for k, v in {
                "blk": dt.get("block"), "credit": dt.get("credit"), "seat": seat, "report": dt.get("report"),
                "duties": dt.get("duties"), "period_credit": share}.items() if v}
            continue
        dt = details.get(tok) or {}
        r = _rel_days(dt)
        # 1.8.2 (G4A-1): 1.8.1's nearest column, unless the trip is in the package, no release prints under its day +
        # rel_days and its own (after it, before the next token and that token's day) prints under the span's day +
        # rel_days: the next day's trip squeezed right of the header before (T5: 3 right of Dec 2, release Dec 5)
        kd, sk = near(pos), span(pos)
        lim = near(toks[j + 1].start()) if j + 1 < len(toks) else len(hdr) + 99
        if dt and sk + r < lim and not rel_on(kd + r) and rel_on(sk + r, within=(pos - 2, nxt)):
            kd = sk
        rel_on(kd + r, take=True)
        start = first + timedelta(days=kd)
        end = start + timedelta(days=r)
        items.append({"trip": tok, "start": start.isoformat(), "end": end.isoformat(), "lay": dt.get("lay", "")})
        trips[f"{tok}|{start.isoformat()}"] = {k: v for k, v in {
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
