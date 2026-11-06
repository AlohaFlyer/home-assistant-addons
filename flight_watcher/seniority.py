"""FW-0062 (1.4.2, Ryan): the pilot seniority list PDF (uploaded on the Web UI, pdftotext -layout copy) -> each
pilot's date of hire, for the pay line under another pilot's rebuilt month (longevity from the date of employment as
a pilot, PWA 3.B.1). Pure parsing, no I/O. The list itself never goes in git; tests use a made-up list.

Layout (as pdftotext prints it): one page per form feed, each with a section label (SENIORITY, ALPHABETICAL, one
per equipment and seat, MANDATORY AGE 65 RETIREMENT AGE) and a header line 'SEN NAME, Initial EMP # ALPA # LAST
NAME FIRST NAME DOH DOR EQUIP SEAT'. The same pilots repeat in every section. Columns shift from page to page and
crowded values run together ('J.A9999', 'ZACHARIAH04/22/19', 'MOEKAI'), so a row is read by the shape of its
values, not by character positions: a seniority number, the short name, the employee number, an optional union
number, the names, the DOH (m/d/yyyy or mm/dd/yy, month first), then DOR / EQUIP / SEAT in any order."""
import re
from datetime import date

PARSER = 2  # bump when a parse rule changes: the Watcher re-reads the list on file with the new rules
DASHES = dict.fromkeys((0x2010, 0x2011, 0x2012, 0x2013, 0x2014, 0x2212), "-")  # the hyphens and dashes pdftotext prints
SECTION_RE = re.compile(r"^(?:SENIORITY|ALPHABETICAL|MANDATORY AGE 65 RETIREMENT AGE|[AB]?\d{3}\s+(?:Captains|First Officers))$", re.I)
DATE_RE = re.compile(r"\d{1,2}/\d{1,2}/\d{2,4}")
HEADER_RE = re.compile(r"^\s*SEN\b.*\bEMP\b.*\bDOH\b", re.I)
ROW_START_RE = re.compile(r"^\s*\d+\s")      # a line that starts with a seniority number
GROUP_RE = re.compile(r"^\s*\d{4}\s*=")       # 'YYYY = n PILOTS' group lines of the retirement section
PAGE_OF_RE = re.compile(r"^\s*\d+\s+of\s+\d+\s*$", re.I)  # a 'n of m' page footer
MAX_LINE = 400  # longer 'rows' are not read (a wrong or garbled file); a real row is about 110 to 200 characters
# Each free text zone (the short name, the names) starts and ends on a character that is neither a space nor a digit,
# so a run of spaces can only be taken by the \s+ / \s* next to it. With \D*? zones a line that does not match
# tried every split of every gap (O(w^4) in the gap width: seconds to hours per line); this form fails in linear time.
# Python 3.10 (the image) has no atomic groups or possessive quantifiers.
ROW_RE = re.compile(
    r"^\s*(?P<sen>\d{1,5})\s+"                         # seniority number
    r"(?:(?P<short>[^\d\s](?:\D*[^\d\s])?)\s*)?"        # 'LAST, F.M.' (may touch the employee number, or lack the comma)
    r"(?P<emp>\d{3,6})"                                 # employee number
    r"(?:\s+(?P<alpa>\d{6,8}))?\s+"                     # union member number, blank for some pilots
    r"(?:(?P<names>[^\d\s](?:\D*[^\d\s])?)\s*)?"        # 'LAST NAME   FIRST NAME' (the first name may touch the date)
    r"(?P<doh>\d{1,2}/\d{1,2}/(?:\d{4}|\d{2}))"         # date of hire, month first
    r"(?P<tail>(?:\s+\S+)*)\s*$")                       # DOR, EQUIP, SEAT (and any new column) in any order
TAIL = (("dor", re.compile(r"^[A-Z][a-z]{2}-\d{2}$")),          # mandatory retirement month, Mon-yy
        ("seat", re.compile(r"^(?:CA|FO|RO|SO|FE)$")),
        ("equip", re.compile(r"^[AB]?\d{3}[A-Z]?$")),              # 330, 321, 717, 767 (A321N, B787 tolerated)
        ("base", re.compile(r"^[A-Z]{3}$")))                      # not on the lists seen so far; kept if added
MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")
MON = r"(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*\.?"
LIST_DATE_RES = (  # a date in the cover text, only next to 'effective', 'as of', 'dated' or 'seniority list'
    re.compile(r"(?:effective|as of|dated|seniority list)\D{0,40}?" + MON + r"\s+(\d{1,2}),?\s+(\d{4})", re.I),
    re.compile(r"(?:effective|as of|dated|seniority list)\D{0,40}?(\d{1,2})\s*" + MON + r"\s*(\d{4})", re.I),
    re.compile(r"(?:effective|as of|dated|seniority list)\D{0,40}?(\d{1,2})/(\d{1,2})/(\d{4})", re.I))
SUFFIX = {"JR", "SR", "II", "III", "IV"}


def _year(y, ref_year):
    y = int(y)
    if y >= 100:
        return y
    return 2000 + y if 2000 + y <= ref_year else 1900 + y


def _doh(s, ref_year):
    m, d, y = s.split("/")
    return date(_year(y, ref_year), int(m), int(d)).isoformat()


def list_date(text):
    """The list's date from its cover text ('Seniority list effective March 1, 2026', 'as of 01 MAR 2026',
    'dated 3/1/2026'), ISO; '' when the text gives none (the lists seen so far do not)."""
    head = (text or "").translate(DASHES)
    m = HEADER_RE.search(head) or re.search(r"^\s*SEN\b", head, re.M)
    head = head[:m.start()] if m else head[:4000]
    for i, rx in enumerate(LIST_DATE_RES):
        g = rx.search(head)
        if not g:
            continue
        try:
            if i == 0:
                return date(int(g.group(3)), MONTHS.index(g.group(1).upper()[:3]) + 1, int(g.group(2))).isoformat()
            if i == 1:
                return date(int(g.group(3)), MONTHS.index(g.group(2).upper()[:3]) + 1, int(g.group(1))).isoformat()
            return date(int(g.group(3)), int(g.group(1)), int(g.group(2))).isoformat()
        except ValueError:
            continue
    return ""


def _split_names(short, names):
    """(last, first). LAST NAME and FIRST NAME are 2+ spaces apart except on crowded pages; there the short
    'LAST, F.' column gives the last name, else the last word is the first name."""
    names = names.strip()
    parts = re.split(r"\s{2,}", names)
    if len(parts) >= 2:
        return parts[0].strip(), " ".join(p.strip() for p in parts[1:])
    last = short.split(",")[0].strip()
    if last and names.upper().startswith(last.upper() + " "):
        return names[:len(last)], names[len(last):].strip()
    head, _, tail = names.rpartition(" ")  # 'MOEKAI' (glued) stays whole: the pilot's cleaner listing wins (parse)
    return (head, tail) if head else (names, "")


def header_order_ok(line):
    """True when a header line puts its columns in the order ROW_RE reads them: EMP # before ALPA # (when the list has
    a union number), the employee number before the date of hire, and DOH the first date column (before DOR, or a DOB
    or other DO? / DATE column). Another order would store the wrong field (a DOR read as the DOH, the ALPA number as
    the employee number), so the rows under such a header are not read ('header-order')."""
    u = line.upper()
    emp, alpa, doh = (re.search(rx, u) for rx in (r"\bEMP\b", r"\bALPA\b", r"\bDOH\b"))
    if not emp or not doh or emp.start() > doh.start() or (alpa and alpa.start() < emp.start()):
        return False
    dates = [m.start() for m in re.finditer(r"\b(?:DO[A-Z]|DATE)\b", u)]
    return min(dates) == doh.start()


def _candidates(lines, rejects):
    """(line_no, line, section, header_ok) for each line under a header that starts with a seniority number. A row
    that wraps (no date on its line, the DOH on the next line, which has no seniority number of its own) is joined to
    that next line; a numbered line with no date that is not joined is reported ('no-date') rather than dropped
    silently. Cover text, 'YYYY = n PILOTS' group lines, page footers and the summary page are not rows."""
    section, header, pending = "", None, None
    for no, raw in enumerate(lines, 1):
        line = raw.replace("\f", "").rstrip()
        s = line.strip()
        if not s:
            continue
        if SECTION_RE.match(s) or HEADER_RE.match(line):
            if pending:
                rejects.append(("no-date", pending[0]))
                pending = None
            if SECTION_RE.match(s):
                section = s.upper()
            else:
                header = header_order_ok(line)
            continue
        if header is None:
            continue  # cover letter, before the first header
        starts = bool(ROW_START_RE.match(line)) and not GROUP_RE.match(line) and not PAGE_OF_RE.match(line)
        dated = bool(DATE_RE.search(line))
        if pending:
            pno, pline = pending
            pending = None
            if not starts and dated:
                yield pno, pline + "   " + s, section, header
                continue
            rejects.append(("no-date", pno))
        if not starts:
            continue
        if not dated:
            if len(line) <= MAX_LINE:
                pending = (no, line)
            else:
                rejects.append(("too-long", no))
            continue
        yield no, line, section, header
    if pending:
        rejects.append(("no-date", pending[0]))


def parse(text, ref_year=None):
    """{'list_date': ISO or '', 'rows': [...], 'rejects': [(reason, line_no)], 'sections': {label: rows}}.
    One row per seniority number, the list's only unique key (a few employee numbers belong to two pilots). The
    first listing of a pilot is kept and the repeats in the other sections are checked against it; a repeat whose
    names split more cleanly replaces the names. ref_year sets the century of two-digit years (the list's year,
    else this year); a DOH after it (or after the list date the text gives) is not read ('future-doh'). A row is
    {sen, emp, last, first, name, doh, equip, seat, listed}. Rejects: no-match, too-long, header-order, no-date,
    bad-date, future-doh, no-name (the line is not read); tail-unknown-token and conflict-* (the row is kept)."""
    text = (text or "").translate(DASHES).replace(" ", " ")
    when = list_date(text)
    ref = ref_year or (int(when[:4]) if when else date.today().year)
    by_sen, rejects, sections = {}, [], {}
    for no, line, section, header_ok in _candidates(text.split("\n"), rejects):
        if len(line) > MAX_LINE:
            rejects.append(("too-long", no))
            continue
        if not header_ok:
            rejects.append(("header-order", no))
            continue
        r = ROW_RE.match(line)
        if not r:
            rejects.append(("no-match", no))
            continue
        try:
            doh = _doh(r["doh"], ref)
        except ValueError:
            rejects.append(("bad-date", no))
            continue
        if int(doh[:4]) > ref or (when and doh > when):
            rejects.append(("future-doh", no))  # a DOH after the list: a misread column, never priced
            continue
        short, names = r["short"] or "", r["names"] or ""
        last, first = _split_names(short, names)
        if not last:
            rejects.append(("no-name", no))
            continue
        tail = {}
        for tok in r["tail"].split():
            k = next((k for k, rx in TAIL if k not in tail and rx.match(tok)), None)
            if k is None:
                tail["_unknown"] = tail.get("_unknown", 0) + 1
            else:
                tail[k] = tok
        if tail.get("_unknown"):
            rejects.append(("tail-unknown-token", no))  # the row is kept; the column layout may have changed
        row = {"sen": int(r["sen"]), "emp": r["emp"], "last": last.title(), "first": first.title(),
               "name": f"{last}, {first}".strip(" ,").title(), "doh": doh, "equip": tail.get("equip", ""),
               "seat": tail.get("seat", "")}
        sections[section] = sections.get(section, 0) + 1
        # how cleanly the names split: crowded columns cut long names short or glue LAST to FIRST
        row["_q"] = (bool(re.search(r"\S\s{2,}\S", names.strip())) + bool(first)
                     + (short.split(",")[0].strip().upper() == last.upper()))
        old = by_sen.get(row["sen"])
        if old is None:
            by_sen[row["sen"]] = dict(row, listed=1)
            continue
        for k in ("emp", "doh", "seat", "equip"):
            if old[k] != row[k]:
                rejects.append((f"conflict-{k}", no))
        a, b = old["last"].upper(), row["last"].upper()
        if not (a.startswith(b) or b.startswith(a)):
            rejects.append(("conflict-name", no))
        if row["_q"] > old["_q"]:
            old.update(last=row["last"], first=row["first"], name=row["name"], _q=row["_q"])
        old["listed"] += 1
    rows = [by_sen[k] for k in sorted(by_sen)]
    for r in rows:
        r.pop("_q", None)
    rejects.sort(key=lambda x: x[1])
    return {"list_date": when, "rows": rows, "rejects": rejects, "sections": sections}


def _emp(v):
    return re.sub(r"\D", "", str(v or "")).lstrip("0")


def to_json(parsed, file, uploaded_at, list_date_given=""):
    """What /share/flight_watcher/uploads/seniority.json holds: {list_date, uploaded_at, file, parser, count,
    newest_doh, sections, rejects, pilots: {emp: {sen, name, last, doh, seat, equip, also?}}}. Keyed on the employee
    number without leading zeros; a number two pilots share keeps the first under the key and the other in 'also'."""
    pilots = {}
    for r in parsed["rows"]:
        rec = {k: r[k] for k in ("sen", "name", "last", "doh", "seat", "equip")}
        k = _emp(r["emp"])
        if not k:
            continue
        if k in pilots:
            pilots[k].setdefault("also", []).append(rec)
        else:
            pilots[k] = rec
    dohs = [r["doh"] for r in parsed["rows"]]
    return {"list_date": list_date_given or parsed.get("list_date") or "", "uploaded_at": uploaded_at, "file": file,
            "parser": PARSER, "count": len(parsed["rows"]), "newest_doh": max(dohs) if dohs else "",
            "sections": parsed.get("sections") or {}, "rejects": len(parsed.get("rejects") or []), "pilots": pilots}


def _last(name):
    """'Doe Jr, Jane' / 'DOE JR' -> 'DOE' (letters only, no Jr / Sr / II), for comparing last names."""
    words = re.sub(r"[^A-Z ]", "", str(name or "").split(",")[0].upper().replace("-", " ")).split()
    return "".join(w for w in words if w not in SUFFIX)


def _first(name):
    return (re.sub(r"[^A-Z ]", " ", str(name or "").partition(",")[2].upper()).split() or [""])[0]


def find(data, emp="", name=""):
    """The seniority record of a pilot: by employee number (the crew line's), a shared number decided by the last
    name; else by 'Last, First' (last name and first given name) when exactly one pilot has it. None otherwise."""
    pilots = (data or {}).get("pilots") or {}
    k = _emp(emp)
    if k and k in pilots:
        cands = [pilots[k]] + list(pilots[k].get("also") or [])
        if len(cands) == 1:
            return cands[0]
        hits = [c for c in cands if name and _last(c["name"]) == _last(name)]
        if len(hits) == 1:
            return hits[0]
    if name and _last(name):
        everyone = [c for p in pilots.values() for c in [p] + list(p.get("also") or [])]
        hits = [c for c in everyone if _last(c["name"]) == _last(name) and _first(c["name"]) == _first(name)]
        if len(hits) == 1:
            return hits[0]
    return None


# ---------------------------------------------------------------- 1.4.5: dates of hire from the monthly award packet
# Ryan (Nov 6): the monthly award packet lists every pilot's date of hire. Two layouts are read, made-up text only
# (the real packet was not available to build on; check the counts on the first real upload):
#  1. a seniority section in the seniority list's own layout (a 'SEN ... EMP # ... DOH' header, then one row per
#     pilot), read by parse() above;
#  2. the bid-line award's pilot blocks, 'SSSSS / EMP' (seniority number / employee number, the line parse_award
#     finds) with the date of hire labeled on the block's lines ('DOH 05/01/88', 'HIRE DATE 5/1/1988', 'DATE OF
#     HIRE ...'). An unlabeled date is never taken for a date of hire.
# The reader that gives more pilot rows wins. Fewer than AWARD_MIN rows is not a seniority section (a stray table,
# an award with no dates of hire): nothing on file changes.
AWARD_MIN = 25
AWARD_PILOT_RE = re.compile(r"^\s*(?P<sen>\d{1,5})\s*/\s*(?P<emp>\d{3,6})(?!\d)(?P<rest>.*)$")
DOH_LABEL_RE = re.compile(r"(?:\bDOH\b|\bD\.O\.H\.?|\bHIRE\s*DATE\b|\bDATE\s+OF\s+HIRE\b|\bHIRED\b)\s*[:#=\-]?\s*"
                          r"(?P<doh>\d{1,2}/\d{1,2}/(?:\d{4}|\d{2}))(?!\d)", re.I)
# each word after the first starts after a comma or one space, so a line that is not a name fails in linear time
AWARD_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z'.\-]*(?:(?:,\s?|\s)[A-Za-z][A-Za-z'.\-]*)*,?$")
AWARD_BLOCK = 6  # lines a pilot block may span (its 'SSSSS / EMP' line and the next five)
VIEW_ONLY = ("as_of", "carried", "base", "award_older")  # seniority.json keys that describe the merge, not a source


def _award_name(s):
    """'DOE, JANE' from the start of an award line (cut before a DOH label; 2+ spaces end the name); '' if none."""
    g = DOH_LABEL_RE.search(s or "")
    s = (s[:g.start()] if g else s or "").strip()
    head = re.split(r"\s{2,}", s)[0].strip() if s else ""
    return head if AWARD_NAME_RE.fullmatch(head) else ""


def _award_blocks(text, ref):
    """Layout 2: {'rows', 'rejects', 'sections', 'list_date'} from 'SSSSS / EMP' pilot blocks with a labeled DOH."""
    lines = text.split("\n")
    when = list_date(text)
    starts = [i for i, ln in enumerate(lines) if AWARD_PILOT_RE.match(ln)]
    by_key, rejects = {}, []
    for j, i in enumerate(starts):
        end = min(starts[j + 1] if j + 1 < len(starts) else len(lines), i + AWARD_BLOCK)
        if len(lines[i]) > MAX_LINE:
            rejects.append(("too-long", i + 1))
            continue
        m = AWARD_PILOT_RE.match(lines[i])
        g = next((x for x in (DOH_LABEL_RE.search(ln) for ln in lines[i:end] if len(ln) <= MAX_LINE) if x), None)
        if not g:
            rejects.append(("no-doh", i + 1))
            continue
        try:
            doh = _doh(g["doh"], ref)
        except ValueError:
            rejects.append(("bad-date", i + 1))
            continue
        if int(doh[:4]) > ref or (when and doh > when):
            rejects.append(("future-doh", i + 1))
            continue
        name = _award_name(m["rest"]) or (_award_name(lines[i + 1]) if i + 1 < end else "")
        if not name:
            rejects.append(("no-name", i + 1))
            continue
        last, _, first = (x.strip() for x in name.partition(","))
        key = (int(m["sen"]), m["emp"])
        old = by_key.get(key)
        if old:
            if old["doh"] != doh:
                rejects.append(("conflict-doh", i + 1))
            old["listed"] += 1
            continue
        by_key[key] = {"sen": key[0], "emp": m["emp"], "last": last.title(), "first": first.title(),
                       "name": f"{last}, {first}".strip(" ,").title(), "doh": doh, "equip": "", "seat": "", "listed": 1}
    rows = [by_key[k] for k in sorted(by_key)]
    return {"list_date": when, "rows": rows, "rejects": sorted(rejects, key=lambda x: x[1]),
            "sections": {"AWARD PILOT LINES": len(rows)} if rows else {}}


def award_parse(text, ref_year=None):
    """Dates of hire from a monthly award packet's text: parse()'s dict for the reader with more pilot rows (a tie
    goes to the seniority section), plus 'reader' ('seniority section' or 'pilot lines')."""
    norm = (text or "").translate(DASHES).replace(" ", " ")
    when = list_date(norm)
    ref = ref_year or (int(when[:4]) if when else date.today().year)
    sec = parse(norm, ref)
    blk = _award_blocks(norm, ref)
    best, reader = max(((sec, "seniority section"), (blk, "pilot lines")), key=lambda x: len(x[0]["rows"]))
    sections = {(k or "AWARD SENIORITY SECTION"): v for k, v in (best.get("sections") or {}).items()}
    return dict(best, reader=reader, sections=sections)


def as_of(d):
    """The date a source's dates of hire stand at: its list date (typed or printed), else an award's bid period
    month (its first day), else the upload day. '' for nothing."""
    d = d or {}
    return str(d.get("list_date") or (f"{d['award_month']}-01" if d.get("award_month") else "")
               or str(d.get("uploaded_at") or "")[:10])


def combine(lst, aw):
    """seniority.json, what the Watcher reads, from the dedicated seniority list (`lst`, to_json + source 'list') and
    the newest award with dates of hire (`aw`, to_json + source 'award YYYY-MM', award_month). The later as_of() is on
    top and a tie goes to the list. An award on top keeps the list's pilots it does not hold ('carried', with the
    list described in 'base'), since an award may cover fewer pilots than the whole list; a list on top stands alone
    (an older award adds nothing). None when there is neither."""
    lst = {k: v for k, v in (lst or {}).items() if k not in VIEW_ONLY} or None
    aw = {k: v for k, v in (aw or {}).items() if k not in VIEW_ONLY} or None
    if not lst and not aw:
        return None
    if lst and (not aw or as_of(lst) >= as_of(aw)):
        out = dict(lst, source="list", as_of=as_of(lst))
        if aw:
            out["award_older"] = {"source": aw.get("source"), "as_of": as_of(aw), "count": aw.get("count", 0)}
        return out
    out = dict(aw, as_of=as_of(aw))
    if lst:
        pilots = dict(lst.get("pilots") or {})
        pilots.update(aw.get("pilots") or {})
        recs = [r for p in pilots.values() for r in [p] + list(p.get("also") or [])]
        out.update(pilots=pilots, count=len(recs), newest_doh=max((r.get("doh") or "" for r in recs), default=""),
                   carried=sum(1 + len(p.get("also") or []) for k, p in (lst.get("pilots") or {}).items()
                               if k not in (aw.get("pilots") or {})),
                   base={"source": "list", "file": lst.get("file", ""), "list_date": lst.get("list_date", ""),
                         "uploaded_at": lst.get("uploaded_at", ""), "as_of": as_of(lst), "count": lst.get("count", 0)})
    return out
