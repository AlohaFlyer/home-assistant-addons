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

PARSER = 1  # bump when a parse rule changes: the Watcher re-reads the last upload with the new rules
DASHES = dict.fromkeys((0x2010, 0x2011, 0x2012, 0x2013, 0x2014, 0x2212), "-")  # the hyphens and dashes pdftotext prints
SECTION_RE = re.compile(r"^(?:SENIORITY|ALPHABETICAL|MANDATORY AGE 65 RETIREMENT AGE|[AB]?\d{3}\s+(?:Captains|First Officers))$", re.I)
DATE_RE = re.compile(r"\d{1,2}/\d{1,2}/\d{2,4}")
HEADER_RE = re.compile(r"^\s*SEN\b.*\bEMP\b.*\bDOH\b", re.I)
ROW_RE = re.compile(
    r"^\s*(?P<sen>\d{1,5})\s+"                      # seniority number
    r"(?P<short>\D*?)\s*"                            # 'LAST, F.M.' (may touch the employee number, or lack the comma)
    r"(?P<emp>\d{3,6})"                              # employee number
    r"(?:\s+(?P<alpa>\d{6,8}))?\s+"                  # union member number, blank for some pilots
    r"(?P<names>\D*?)\s*"                            # 'LAST NAME   FIRST NAME' (the first name may touch the date)
    r"(?P<doh>\d{1,2}/\d{1,2}/(?:\d{4}|\d{2}))"      # date of hire, month first
    r"(?P<tail>(?:\s+\S+)*)\s*$")                    # DOR, EQUIP, SEAT (and any new column) in any order
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


def parse(text, ref_year=None):
    """{'list_date': ISO or '', 'rows': [...], 'rejects': [(reason, line_no)], 'sections': {label: rows}}.
    One row per seniority number, the list's only unique key (a few employee numbers belong to two pilots). The
    first listing of a pilot is kept and the repeats in the other sections are checked against it; a repeat whose
    names split more cleanly replaces the names. ref_year sets the century of two-digit years (the list's year,
    else this year). A row is {sen, emp, last, first, name, doh, equip, seat, listed}."""
    text = (text or "").translate(DASHES).replace(" ", " ")
    when = list_date(text)
    ref = ref_year or (int(when[:4]) if when else date.today().year)
    section, header_seen = "", False
    by_sen, rejects, sections = {}, [], {}
    for no, raw in enumerate(text.split("\n"), 1):
        line = raw.replace("\f", "").rstrip()
        s = line.strip()
        if not s:
            continue
        if SECTION_RE.match(s):
            section = s.upper()
            continue
        if HEADER_RE.match(line):
            header_seen = True
            continue
        if not header_seen or not re.match(r"^\s*\d+\s", line) or not DATE_RE.search(line):
            continue  # cover letter, summary counts, 'YYYY = n PILOTS' group lines, page numbers
        r = ROW_RE.match(line)
        if not r:
            rejects.append(("no-match", no))
            continue
        try:
            doh = _doh(r["doh"], ref)
        except ValueError:
            rejects.append(("bad-date", no))
            continue
        last, first = _split_names(r["short"], r["names"])
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
        row["_q"] = (bool(re.search(r"\S\s{2,}\S", r["names"].strip())) + bool(first)
                     + (r["short"].split(",")[0].strip().upper() == last.upper()))
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
