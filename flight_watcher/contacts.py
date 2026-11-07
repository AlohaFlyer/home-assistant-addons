"""FW-0066 (Ryan, Nov 7): the pilot contact list. An upload of kind "contacts" (a PDF, CSV or XLSX file) is read for
each pilot's employee number, name, phone numbers and email addresses where the list has them, and kept as
/share/flight_watcher/contacts.json (mode 600, outside /config/www, never in git). The pilot card shows a tap-to-call,
tap-to-text and mail link for the one pilot looked up (sensor.<prefix>_pilot_schedule, attribute `contact`); nothing
else ever carries an entry, and the log and the upload result carry counts only.

Readers, all made for lists laid out one pilot per row:
  * CSV / XLSX: a header row (in the first 10 rows) names the columns: employee number (EMP, EMPLOYEE #, FILE #,
    BADGE), name (NAME, or LAST and FIRST), phones (PHONE, CELL, MOBILE, HOME, WORK, TEL; FAX is left out) and
    emails (EMAIL, E-MAIL). A sheet with no such header is read line by line like a PDF.
  * PDF (the pdftotext -layout copy) and header-less sheets: per line, phone numbers (US, 10 digits), email
    addresses, a "Last, First" name and the employee number (the longest 3 to 7 digit number left once phones and
    dates are taken out). A line with a phone or an email but no name joins the pilot above it (a wrapped row).
Only entries with a phone or an email are kept. The XLSX reader is the standard library's (zipfile and ElementTree):
a workbook that unpacks past XLSX_MAX or declares a DTD is refused."""
import csv
import io
import json
import os
import re
import zipfile
from xml.etree import ElementTree as ET

PARSER = 1  # bump when a parse rule changes
XLSX_MAX = 60_000_000  # unpacked bytes an XLSX may hold
MAX_ROWS = 20_000
NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"

PHONE_RE = re.compile(r"(?<![\w+])(?:\+?1[\s.\-]?)?\(?([2-9]\d{2})\)?[\s.\-]?(\d{3})[\s.\-]?(\d{4})(?!\d)")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}")
DATE_RE = re.compile(r"(?<!\d)\d{1,4}[/\-.]\d{1,2}[/\-.]\d{1,4}(?!\d)")
NUM_RE = re.compile(r"(?<![\d])\d{3,7}(?![\d])")
LABELS = (("cell", "cell"), ("mobile", "cell"), ("mob", "cell"), ("home", "home"), ("work", "work"),
          ("office", "work"), ("business", "work"), ("fax", "fax"), ("c", "cell"), ("h", "home"), ("m", "cell"),
          ("w", "work"))
LABEL_BEFORE = re.compile(r"\b(cell|mobile|mob|home|work|office|business|fax)\b\s*(?:phone|ph|tel|#)?\s*[:.]?\s*$", re.I)
# a one-letter label (C: 808..., H 808...) only after a column gap or another number, never a name's middle initial
LETTER_BEFORE = re.compile(r"(?:^|\s{2,}|[\d)]\s*)([chmw])\s*[:.]?\s*$", re.I)
# words around a name on a crew or contact list that are not part of it
NOISE = re.compile(r"\b(?:cell|mobile|mob|home|work|office|business|fax|phone|ph|tel|email|e-mail|emp|employee|"
                   r"capt|captain|ca|fo|ro|so|f/o|hnl|ogg|koa|lih|a330|a332|332|a321|b717|717|b787|787)\b[:.#]?", re.I)
PARTICLE = r"(?:(?:de|da|del|della|di|du|la|le|van|von|der|den|st\.?|mc|mac)\s+)*"
NAME_RE = re.compile(r"(?<![A-Za-z'])(" + PARTICLE + r"[A-Za-z][A-Za-z'\-]*[A-Za-z])\s*,\s*([A-Za-z][A-Za-z'\-]*[A-Za-z])"
                     r"(?:\s+([A-Za-z])\.?)?(?![A-Za-z])", re.I)


def _title(s):
    """'DOE' -> 'Doe', "O'NEIL" -> "O'Neil", 'SMITH-JONES' -> 'Smith-Jones', 'van der berg' -> 'Van Der Berg'."""
    return re.sub(r"[A-Za-z]+", lambda m: m.group(0)[0].upper() + m.group(0)[1:].lower(), s.strip())


def _phone(area, exch, line, label=""):
    digits = f"{area}{exch}{line}"
    return {"label": label or "phone", "number": f"{area}-{exch}-{line}", "tel": f"+1{digits}"}


def phones_in(text, label=""):
    """[{label, number, tel}] for every US phone number in text; the label from the header (label) or from a word
    right before the number (Cell:, H, Home ...). A fax number is left out."""
    out = []
    for m in PHONE_RE.finditer(text or ""):
        lab = label
        if not lab:
            before = text[:m.start()]
            b = LABEL_BEFORE.search(before[-24:]) or LETTER_BEFORE.search(before)
            lab = dict(LABELS).get(b.group(1).lower(), "") if b else ""
        if lab == "fax":
            continue
        out.append(_phone(*m.groups(), lab))
    return out


def emails_in(text):
    return [e for e in EMAIL_RE.findall(text or "")]


def name_in(text):
    """'Last, First' (title case, the first name's first word; a middle initial dropped) from free text, else ''."""
    t = NOISE.sub(" ", text or "")
    m = NAME_RE.search(t)
    if not m:
        return ""
    return f"{_title(m.group(1))}, {_title(m.group(2))}"


def _emp(text):
    """The employee number on a line: the longest 3 to 7 digit number (phones, emails and dates already out)."""
    nums = NUM_RE.findall(text or "")
    return max(nums, key=len) if nums else ""


def _strip(text):
    t = EMAIL_RE.sub(" ", text or "")
    t = PHONE_RE.sub(" ", t)
    return DATE_RE.sub(" ", t)


def parse_text(text):
    """Contacts from a text copy (or rows with no header): {entries, rejects, lines}."""
    entries, rejects, cur = [], 0, None
    lines = (text or "").splitlines()[:MAX_ROWS]
    for line in lines:
        if not line.strip():
            continue
        ph, em = phones_in(line), emails_in(line)
        rest = _strip(line)
        name = name_in(rest)
        emp = _emp(rest)
        if name:
            cur = {"emp": emp, "name": name, "phones": ph, "emails": em}
            entries.append(cur)
        elif (ph or em) and cur is not None and not emp and not re.search(r"[A-Za-z]{2,}", NOISE.sub(" ", rest)):
            cur["phones"] += ph  # a wrapped row: only a phone or an address (and a label) on the line
            cur["emails"] += em
        elif ph or em:
            rejects += 1  # a number or an address with no pilot to tie it to (a page footer, a note)
    return {"entries": entries, "rejects": rejects, "lines": len(lines)}


def _role(h):
    """A header cell -> (role, label): emp, name, last, first, phone (label), email; ('', '') for anything else."""
    h = re.sub(r"\s+", " ", str(h or "").strip().lower())
    if not h:
        return "", ""
    if re.search(r"e-?mail", h):
        return "email", ""
    if "fax" in h:
        return "", ""
    if re.search(r"\bemp\b|emp\s*(#|no|num|id)|employee|badge|file\s*(#|no|num)|^emp", h):
        return "emp", ""
    if re.search(r"phone|cell|mobile|\btel\b|telephone|\bhome\b|\bwork\b|office", h):
        lab = "cell" if re.search(r"cell|mobile", h) else "home" if "home" in h else "work" if re.search(r"work|office|business", h) else "phone"
        return "phone", lab
    if re.search(r"\blast\b|surname", h):
        return "last", ""
    if re.search(r"\bfirst\b|given", h):
        return "first", ""
    if "name" in h or h in ("pilot", "crew member", "crewmember"):
        return "name", ""
    return "", ""


def _header(rows):
    """(row index, {col: (role, label)}) of the first header row in the first 10 rows, or (None, None). A header
    names a name column (NAME, or LAST and FIRST) and at least one of employee number, phone or email."""
    for i, row in enumerate(rows[:10]):
        roles = {j: _role(c) for j, c in enumerate(row)}
        got = {r for r, _ in roles.values() if r}
        if ("name" in got or "last" in got) and got & {"emp", "phone", "email"}:
            return i, roles
    return None, None


def _name_cell(v):
    """A NAME cell: 'Doe, Jane' as is; 'Jane Doe' -> 'Doe, Jane' (the last word is the last name)."""
    v = re.sub(r"\s+", " ", str(v or "")).strip()
    n = name_in(v)
    if n:
        return n
    w = [x for x in re.split(r"\s+", NOISE.sub(" ", v)) if re.fullmatch(r"[A-Za-z][A-Za-z'\-]*", x)]
    if len(w) >= 2:
        return f"{_title(w[-1])}, {_title(w[0])}"
    return ""


def parse_rows(rows):
    """Contacts from a sheet (a list of rows, each a list of cell strings): {entries, rejects, lines}."""
    rows = [[str(c if c is not None else "").strip() for c in r] for r in rows[:MAX_ROWS]]
    hi, roles = _header(rows)
    if hi is None:  # no header: each row is read as a line ("Doe" and "Jane" in two cells read as "Doe, Jane")
        return parse_text("\n".join(", ".join(c for c in r if c) for r in rows))
    entries, rejects = [], 0
    has_phone_col = any(r == "phone" for r, _ in roles.values())
    has_email_col = any(r == "email" for r, _ in roles.values())
    for row in rows[hi + 1:]:
        if not any(row):
            continue
        cell = {}
        for j, v in enumerate(row):
            r, lab = roles.get(j, ("", ""))
            if r:
                cell.setdefault(r, []).append((v, lab))
        emp = ""
        for v, _ in cell.get("emp", []):
            d = re.sub(r"\.0+$", "", v)
            d = re.sub(r"\D", "", d)
            if 3 <= len(d) <= 7:
                emp = d
                break
        if cell.get("last"):
            last = cell["last"][0][0]
            first = (cell.get("first") or [("", "")])[0][0]
            name = name_in(f"{last}, {first}") if first else _title(last) if re.fullmatch(r"[A-Za-z][A-Za-z' \-]*", last) else ""
        else:
            name = next((n for n in (_name_cell(v) for v, _ in cell.get("name", [])) if n), "")
        phones = [p for v, lab in cell.get("phone", []) for p in phones_in(v, lab)]
        emails = [e for v, _ in cell.get("email", []) for e in emails_in(v)]
        whole = "   ".join(row)
        if not has_phone_col:
            phones = phones_in(whole)
        if not has_email_col:
            emails = emails_in(whole)
        if not (emp or name):
            if phones or emails:
                rejects += 1
            continue
        entries.append({"emp": emp, "name": name, "phones": phones, "emails": emails})
    return {"entries": entries, "rejects": rejects, "lines": len(rows)}


def csv_rows(data):
    """Rows of a CSV file (UTF-8 with or without a BOM, else Windows-1252); the delimiter sniffed (, ; tab |)."""
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("cp1252", errors="replace")
    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    return [r for _, r in zip(range(MAX_ROWS), csv.reader(io.StringIO(text), dialect))]


def _col(ref):
    m = re.match(r"([A-Z]+)", ref or "")
    if not m:
        return None
    n = 0
    for ch in m.group(1):
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def _xml(z, name):
    raw = z.read(name)
    if b"<!DOCTYPE" in raw or b"<!ENTITY" in raw:
        raise ValueError("XLSX part declares a DTD")
    return ET.fromstring(raw)


def _first_sheet(z):
    names = set(z.namelist())
    try:
        wb = _xml(z, "xl/workbook.xml")
        sh = wb.find(f"{NS}sheets/{NS}sheet")
        rid = sh.get(f"{REL_NS}id") if sh is not None else None
        if rid and "xl/_rels/workbook.xml.rels" in names:
            for rel in _xml(z, "xl/_rels/workbook.xml.rels"):
                if rel.get("Id") == rid:
                    t = rel.get("Target", "").lstrip("/")
                    t = t if t.startswith("xl/") else "xl/" + t
                    if t in names:
                        return t
    except (KeyError, ET.ParseError):
        pass
    sheets = sorted(n for n in names if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n))
    if not sheets:
        raise ValueError("no worksheet in the XLSX file")
    return sheets[0]


def _cell_text(c, shared):
    t = c.get("t")
    v = c.find(f"{NS}v")
    if t == "s":
        try:
            return shared[int(v.text)] if v is not None and v.text else ""
        except (ValueError, IndexError):
            return ""
    if t == "inlineStr":
        return "".join(x.text or "" for x in c.iter(f"{NS}t"))
    s = v.text if v is not None and v.text else ""
    if re.fullmatch(r"\d+(\.\d+)?[eE]\+?\d+", s):  # a long number Excel wrote in E notation (a phone typed as a number)
        try:
            s = str(int(float(s)))
        except (ValueError, OverflowError):
            pass
    return re.sub(r"^(\d+)\.0+$", r"\1", s)


def xlsx_rows(data):
    """Rows of the first worksheet of an XLSX file (shared and inline strings, numbers as text)."""
    z = zipfile.ZipFile(io.BytesIO(data))
    if sum(i.file_size for i in z.infolist()) > XLSX_MAX:
        raise ValueError("XLSX file unpacks too large")
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in _xml(z, "xl/sharedStrings.xml").findall(f"{NS}si"):
            shared.append("".join(t.text or "" for t in si.iter(f"{NS}t")))
    rows = []
    for row in _xml(z, _first_sheet(z)).iter(f"{NS}row"):
        cells, k = {}, 0
        for c in row.findall(f"{NS}c"):
            j = _col(c.get("r"))
            j = k if j is None else j
            cells[j] = _cell_text(c, shared)
            k = j + 1
        rows.append([cells.get(i, "") for i in range(max(cells) + 1)] if cells else [])
        if len(rows) >= MAX_ROWS:
            break
    return rows


def sniff(data):
    """'pdf', 'xlsx' or 'csv' for an upload's bytes, else None (the file type is read from the bytes, never the
    name): a PDF starts %PDF; an XLSX is a zip holding xl/workbook.xml or a worksheet; a CSV is text (no NUL, decodes)
    with two lines or more and a delimiter."""
    if not data:
        return None
    if data.startswith(b"%PDF"):
        return "pdf"
    if data.startswith(b"PK\x03\x04"):
        try:
            names = zipfile.ZipFile(io.BytesIO(data)).namelist()
        except zipfile.BadZipFile:
            return None
        return "xlsx" if "xl/workbook.xml" in names or any(n.startswith("xl/worksheets/") for n in names) else None
    head = data[:65536]
    if b"\x00" in head:
        return None
    try:
        text = head.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = head.decode("cp1252")
        except UnicodeDecodeError:
            return None
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) >= 2 and any(d in lines[0] for d in ",;\t|"):
        return "csv"
    return None


def _dedupe(e):
    seen, phones = set(), []
    for p in e["phones"]:
        if p["tel"] not in seen:
            seen.add(p["tel"])
            phones.append(p)
    seen, emails = set(), []
    for m in e["emails"]:
        if m.lower() not in seen:
            seen.add(m.lower())
            emails.append(m)
    return {"emp": e["emp"], "name": e["name"], "phones": phones[:4], "emails": emails[:3]}


def parse(data, kind, text=None):
    """{entries (with a phone or an email), rejects, lines, skipped (entries with neither)} from an upload's bytes;
    kind is sniff()'s answer; a PDF is read from its text copy (text)."""
    if kind == "pdf":
        r = parse_text(text or "")
    elif kind == "xlsx":
        r = parse_rows(xlsx_rows(data))
    elif kind == "csv":
        r = parse_rows(csv_rows(data))
    else:
        raise ValueError("not a PDF, CSV or XLSX file")
    keep = [_dedupe(e) for e in r["entries"]]
    kept = [e for e in keep if e["phones"] or e["emails"]]
    return {"entries": kept, "rejects": r["rejects"], "lines": r["lines"], "skipped": len(keep) - len(kept)}


def build(parsed, file, uploaded_at):
    """contacts.json's content (personal data: mode 600, never logged, never in a sensor but for one pilot)."""
    es = parsed["entries"]
    return {"v": 1, "parser": PARSER, "file": file, "uploaded_at": uploaded_at, "count": len(es),
            "with_phone": sum(1 for e in es if e["phones"]), "with_email": sum(1 for e in es if e["emails"]),
            "with_emp": sum(1 for e in es if e["emp"]), "rejects": parsed["rejects"], "skipped": parsed["skipped"],
            "pilots": es}


def store(path, d):
    """Write contacts.json atomically, mode 600 (never readable by another user, even while it is written)."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(d, f, separators=(",", ":"))
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def load(path):
    try:
        d = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) and isinstance(d.get("pilots"), list) else None


def summary(d):
    """What a sensor and the upload result may say about the list: counts, its file name and upload time only."""
    if not d:
        return None
    return {k: d.get(k, 0) for k in ("count", "with_phone", "with_email", "with_emp", "rejects")} | {
        "file": d.get("file") or "", "uploaded_at": d.get("uploaded_at") or ""}


def _key(name):
    """'Doe, Jane A' / 'DOE, JANE' -> 'doe,jane': last name and the first word of the first name, lower case."""
    s = re.sub(r"[^a-z, ]", "", str(name or "").lower())
    if "," not in s:
        return ""
    last, first = s.split(",", 1)
    first = first.split()
    return f"{' '.join(last.split())},{first[0] if first else ''}"


def find(d, emp="", name=""):
    """The one entry for a looked-up pilot: by employee number, else by name when exactly one entry has it.
    {name, phones, emails} (no employee number: the sensor has it already), or None."""
    if not d:
        return None
    es = [e for e in d.get("pilots") or [] if isinstance(e, dict)]
    emp = re.sub(r"\D", "", str(emp or ""))
    hit = [e for e in es if emp and e.get("emp") == emp]
    if not hit:
        k = _key(name)
        hit = [e for e in es if k and _key(e.get("name")) == k]
        if len({e.get("emp") or id(e) for e in hit}) != 1:
            return None
    e = hit[0]
    return {"name": e.get("name") or "", "phones": list(e.get("phones") or []), "emails": list(e.get("emails") or [])}


def find_by_name(d, q):
    """(emp, name) of the one entry whose name matches a typed name ('doe, jane', 'Doe'), or None (no entry, more
    than one, or no employee number on it). Used when the crew directory has never seen the name."""
    if not d or not q:
        return None
    qk = _key(q) if "," in q else ""
    last = re.sub(r"[^a-z ]", "", q.lower()).strip()
    es = [e for e in d.get("pilots") or [] if isinstance(e, dict) and e.get("emp")]
    hit = [e for e in es if (qk and _key(e.get("name")) == qk) or
           (not qk and _key(e.get("name")).split(",")[0] == last)]
    if len({e["emp"] for e in hit}) != 1:
        return None
    return hit[0]["emp"], hit[0].get("name") or ""
