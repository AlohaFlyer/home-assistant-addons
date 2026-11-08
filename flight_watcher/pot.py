"""Pure page logic: classify, parse, fingerprint, month links. No network, no MQTT.

Kept free of side effects so tests/ can run it against saved HTML fixtures.
"""
import hashlib
import re
from datetime import date, datetime, timedelta, timezone
from html import unescape
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

KILLED_TXT = "new session under this account was detected"
EXPIRED_HINTS = ("session has expired", "session expired", "please log in", "please sign in")
BLOCK_HINTS = ("captcha", "verification code", "one-time", "one time pass", "change your password",
               "password has expired", "account is locked", "account locked")
PAIRING_RE = re.compile(r"^[A-Z]\d{4}[A-Z]?$")  # 0.4.8: FLICA adds a letter to a changed pairing (H3815B)
PAIRING_ANY = re.compile(r"\b([A-Z]\d{4}[A-Z]?)\b")
DAY_MON = re.compile(r"^(\d{1,2})\s*([A-Za-z]{3})")
MON3 = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]

# Column order of the mobile open time pot (mobileopentimepot.cgi). Header reads
# Pair | Start | End | Crd/Dy | Layover | Prem; confirmed Nov 1, 2026 against the H3619 detail page:
# H3619 | 01Nov | 02Nov | 12.18 | LAS | | | 13:10 | 14:04 | 2 |  = pay 12:18, first leg departs 1310,
# last leg arrives 1404, 2 days. Block and check-in come only from the detail page (enrich()).
MOBILE_COLS = ["pairing", "start", "end", "credit", "layover", "x1", "x2", "depart", "arrive",
               "days", "prem"]


def visible_text(html):
    """Text a person would read: drops scripts/styles so words like 'captcha' in
    page code (FLICA's main menu loads a captcha script) don't count as a block."""
    try:
        soup = BeautifulSoup(html, "html.parser")
        for t in soup(["script", "style", "noscript", "template"]):
            t.decompose()
        return soup.get_text(" ", strip=True).lower()
    except Exception:
        return html.lower()


def classify(html):
    low = html.lower()
    if KILLED_TXT in low:
        return "killed"
    if any(h in visible_text(html) for h in BLOCK_HINTS):
        return "blocked"
    if 'type="password"' in low or "type=password" in low or any(h in low for h in EXPIRED_HINTS):
        return "expired"
    return "ok"


def is_pot_page(html, mobile=True):
    if "Opentime Pot" in html:
        return True
    if mobile:
        vt = visible_text(html)
        return "open time" in vt or "opentime" in vt
    return False


def _cells(tr, tags=("td",)):
    return [c.get_text(" ", strip=True) for c in tr.find_all(list(tags))]


def _row(cells):
    c = cells + [""] * (len(MOBILE_COLS) - len(cells))
    r = dict(zip(MOBILE_COLS, c))
    r["dates"] = f"{r['start']}-{r['end']}" if r["end"] else r["start"]
    r.pop("x1", None)
    r.pop("x2", None)
    if re.match(r"^\d{1,3}[.:]\d{2}$", r["credit"] or ""):
        r["credit"] = r["credit"].replace(".", ":").lstrip("0") or "0:00"
        if r["credit"].startswith(":"):
            r["credit"] = "0" + r["credit"]
    r["blk"] = ""
    r["report"] = ""
    return r


def parse_pot(html):
    """Return {key: row}. key = pairing|start, same as v0.1.x so baselines carry over."""
    soup = BeautifulSoup(html, "html.parser")
    out = {}
    for tr in soup.find_all("tr"):
        cells = _cells(tr)
        if len(cells) >= 10 and PAIRING_RE.match(cells[0]):
            r = _row(cells)
            out[f"{cells[0]}|{cells[1]}"] = r
    if not out:  # looser layout: any row naming a pairing number
        for tr in soup.find_all("tr"):
            cells = _cells(tr, ("td", "th"))
            row = " | ".join(x for x in cells if x)
            m = PAIRING_ANY.search(row)
            if m and len(cells) >= 2 and cells[0] == m.group(1):
                r = _row(cells)
                r["row"] = row[:300]
                out.setdefault(f"{m.group(1)}|{cells[1]}", r)
    return out


def header_fingerprint(html):
    """Hash of the row just above the first pairing row, digits stripped (a header can carry
    a date or time). None when the pot has no rows, so an empty pot never trips it."""
    soup = BeautifulSoup(html, "html.parser")
    prev = None
    for tr in soup.find_all("tr"):
        cells = _cells(tr, ("td", "th"))
        if cells and PAIRING_RE.match(cells[0]):
            # Own cells only: FLICA never closes a pairing's <tr>, so html.parser nests every
            # later row inside the first one and len(cells) grew with the pot (0.3.5 fix; it
            # parked the watcher 9 times on Nov 1, 2026).
            ncols = len(tr.find_all(("td", "th"), recursive=False)) or len(cells)
            if prev is None:
                sig = f"noheader|cols={ncols}"
            else:
                sig = "|".join(re.sub(r"\d", "", x).strip().lower() for x in prev) + f"|cols={ncols}"
            return hashlib.sha1(sig.encode()).hexdigest()[:12]
        # A wrapper row (nested table) or any row naming a pairing is data, not the header:
        # using it made the hash change every time the first pot pairing changed (0.2.9).
        if cells and any(cells) and not tr.find("tr") and not PAIRING_ANY.search(" ".join(cells)):
            prev = cells
    return None


def pot_links(html, page_url):
    """Links on a pot page to other mobile pot pages (other bid months), made absolute."""
    soup = BeautifulSoup(html, "html.parser")
    out, seen = [], set()
    for a in soup.find_all("a", href=True):
        if "opentimepot" in a["href"].lower():
            url = urljoin(page_url, a["href"])
            if url not in seen:
                seen.add(url)
                out.append({"url": url, "text": a.get_text(" ", strip=True)})
    return out


def bcid(url):
    m = re.search(r"BCID=([\d.]+)", url or "")
    return m.group(1) if m else None


# FW-0034: the close-in open time folder. FLICA's alert emails name it 'Close in Opentime: <16 Hrs to RPT'; Ryan
# (2026-11-03): a trip under 16 h to report is added or swapped only from it, and it has its own BCID (an 008.xxx
# series). Taken only from a menu link whose text names the folder (or the first link under a heading that does),
# never guessed.
CLOSE_IN_RE = re.compile(r"close[\s-]*in\s*open\s*time|<\s*16\s*hrs?\.?\s*to\s*rpt", re.I)
BCID_IN = re.compile(r"\bBCID=(\d{3}\.\d{1,4})\b|['\"](\d{3}\.\d{3})['\"]", re.I)
BCID_ONLY = re.compile(r"^\d{3}\.\d{1,4}$")
JS_CALL_RE = re.compile(r"\b(?:\w+\.)?add[A-Z]\w*\s*\((.*?)\)\s*;", re.S)
JS_STR_RE = re.compile(r"'((?:[^'\\]|\\.)*)'|\"((?:[^\"\\]|\\.)*)\"")
MONTH_WORD = re.compile(r"^\s*(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b", re.I)
LINK_ATTRS = ("href", "onclick", "src", "action")


def _bcids(text):
    return [a or b for a, b in BCID_IN.findall(text or "")]


def _html_entries(soup):
    """(label, [bcid]) in page order: each <a> or onclick element (its text and title; BCIDs in href / onclick), each
    <option> whose value is a BCID, each other text node. Entities are decoded (&lt;16 reads <16)."""
    out = []

    def walk(node):
        for ch in node.children:
            if isinstance(ch, Tag):
                if ch.name in ("script", "style", "noscript", "template"):
                    continue
                if ch.name == "a" or ch.get("onclick"):
                    attrs = " ".join(str(ch.get(k) or "") for k in LINK_ATTRS)
                    out.append((f"{ch.get_text(' ', strip=True)} {ch.get('title') or ''}".strip(), _bcids(attrs)))
                    continue
                if ch.name == "option" and BCID_ONLY.match(str(ch.get("value") or "").strip()):
                    out.append((ch.get_text(" ", strip=True), [str(ch.get("value")).strip()]))
                    continue
                walk(ch)
            elif isinstance(ch, NavigableString) and not isinstance(ch, Comment):
                t = str(ch).strip()
                if t:
                    out.append((t, []))
    walk(soup)
    return out


def _js_entries(soup):
    """(label, [bcid]) of every JS menu-tree call (M.addC / M.addE ...) in the page's scripts, in order: the label is
    its first quoted string, the BCIDs come from all of its arguments."""
    out = []
    for sc in soup.find_all("script"):
        for m in JS_CALL_RE.finditer(sc.string or sc.get_text() or ""):
            strs = [unescape(a or b) for a, b in JS_STR_RE.findall(m.group(1))]
            out.append((re.sub(r"<[^>]+>", " ", strs[0]).strip() if strs else "", _bcids(unescape(m.group(1)))))
    return out


def close_in_folders(html, exclude=()):
    """FW-0034: [{'bcid', 'text'}] of the close-in open time folder named on a menu or open time page: a link (or a
    folder <option>) whose own text names it, or the first link under a heading that names it, before the next
    heading (any other text with letters that is not a month name). BCIDs in `exclude` (the regular pot and
    Tradeboard folders) are never taken. [] when the page does not name the folder: nothing is guessed."""
    found, seen = [], set(exclude or ())
    soup = BeautifulSoup(html or "", "html.parser")
    for entries in (_html_entries(soup), _js_entries(soup)):
        sect = None
        for label, ids in entries:
            ids = [b for b in ids if b not in seen]
            if CLOSE_IN_RE.search(label):
                if ids:
                    seen.add(ids[0])
                    found.append({"bcid": ids[0], "text": label[:80]})
                    sect = None
                else:
                    sect = label
                continue
            if sect is None:
                continue
            if ids:
                seen.add(ids[0])
                found.append({"bcid": ids[0], "text": sect[:80]})
                sect = None
            elif re.search(r"[A-Za-z]{2}", label) and not MONTH_WORD.match(label):
                sect = None  # the next heading: the close-in section ended without a link
    return found


# FW-0064: a menu entry naming crew-to-crew trades ('Trades', 'Crew Trade', 'Pending Trades', 'Trade Requests'...);
# the Tradeboard (its own 001.n folders, already read) and the open time Add/Swap/Drop requests are not it
TRADE_WORD = re.compile(r"\btrades?\b|crew[\s-]*(?:to|2)[\s-]*crew", re.I)
TRADEBOARD = re.compile(r"trade\s*board|tb_frame|\bBCID=0*01\.|['\"]0*01\.\d+['\"]", re.I)
TARGET_RE = re.compile(r"(?:https?://[^\s'\"<>]+|/?(?:full|online)/[\w./-]+\.cgi[^\s'\"<>)]*)", re.I)


def _targets(soup):
    """(label, target) in page order: each <a> or onclick element (its text and title; the first URL-like path in its
    href / onclick), each JS menu-tree call (M.addC / M.addE: its first quoted string; a URL in the rest); other text
    nodes as headings (target ''). Entities are decoded."""
    out = []

    def walk(node):
        for ch in node.children:
            if isinstance(ch, Tag):
                if ch.name in ("script", "style", "noscript", "template"):
                    continue
                if ch.name == "a" or ch.get("onclick"):
                    attrs = unescape(" ".join(str(ch.get(k) or "") for k in LINK_ATTRS))
                    m = TARGET_RE.search(attrs)
                    out.append((f"{ch.get_text(' ', strip=True)} {ch.get('title') or ''}".strip(),
                                m.group(0) if m else attrs.strip()[:160]))
                    continue
                walk(ch)
            elif isinstance(ch, NavigableString) and not isinstance(ch, Comment):
                t = str(ch).strip()
                if t:
                    out.append((t, ""))
    walk(soup)
    for sc in soup.find_all("script"):
        for m in JS_CALL_RE.finditer(sc.string or sc.get_text() or ""):
            strs = [unescape(a or b) for a, b in JS_STR_RE.findall(m.group(1))]
            rest = " ".join(strs[1:])
            u = TARGET_RE.search(rest)
            out.append((re.sub(r"<[^>]+>", " ", strs[0]).strip() if strs else "",
                        u.group(0) if u else rest.strip()[:160]))
    return out


def trade_pages(html):
    """FW-0064: [{'text', 'url'}] of the menu entries that name crew-to-crew trades: an entry whose own text names
    them, or an entry with a target under a heading that does (until the next heading). Tradeboard entries are left
    out. Read only: nothing here is fetched, the Watcher only logs what it finds. Session tokens are masked."""
    found, sect = [], None
    for label, target in _targets(BeautifulSoup(html or "", "html.parser")):
        if TRADEBOARD.search(label) or TRADEBOARD.search(target):
            sect = None
            continue
        if TRADE_WORD.search(label):
            if target and not target.lower().startswith("javascript:void"):
                found.append({"text": label[:80], "url": re.sub(r"token=[0-9A-Za-z]+", "token=MASKED", target)})
                sect = None
            else:
                sect = label
            continue
        if sect is None:
            continue
        if target:
            found.append({"text": f"{sect[:60]}: {label[:40]}",
                          "url": re.sub(r"token=[0-9A-Za-z]+", "token=MASKED", target)})
        elif re.search(r"[A-Za-z]{2}", label) and not MONTH_WORD.match(label):
            sect = None
    out, seen = [], set()
    for f in found:
        if (f["text"], f["url"]) not in seen:
            seen.add((f["text"], f["url"]))
            out.append(f)
    return out


def pick_close_in(found, periods=()):
    """The close-in BCID for the bid periods watched (the regular pot BCIDs' last part, e.g. '152'): the first found
    for the earliest such period, else the first found; None when nothing was found."""
    for p in sorted(periods or (), key=lambda x: int(x) if str(x).isdigit() else 0):
        for f in found or []:
            if f["bcid"].split(".")[-1] == str(p):
                return f["bcid"]
    return (found or [{}])[0].get("bcid")


def bcid_key(b):
    return tuple(int(x) for x in b.split(".") if x.isdigit())


def bcid_after(b, mine):
    return bcid_key(b) > bcid_key(mine)


def row_date(s, today=None):
    """'01Nov' -> date, year picked so the date is no more than ~2 months in the past."""
    today = today or date.today()
    m = DAY_MON.match((s or "").strip())
    if not m or m.group(2).upper() not in MON3:
        return None
    mon = MON3.index(m.group(2).upper()) + 1
    yr = today.year
    if mon < today.month - 2:
        yr += 1
    elif mon > today.month + 9:
        yr -= 1
    try:
        return date(yr, mon, int(m.group(1)))
    except ValueError:
        return None


def hours(s):
    """'11:04' or '11.04' -> 11.067 hours; '' -> None."""
    m = re.match(r"^\s*(\d{1,3})[:.]?(\d{2})\s*$", s or "")
    if m:
        return int(m.group(1)) + int(m.group(2)) / 60
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def hhmm(s):
    """'11.27' or '1127' or '11:27' -> '11:27'; else None."""
    m = re.match(r"^\s*(\d{1,2})[:.]?(\d{2})\s*$", s or "")
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        return None
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def detail_url(row, today=None):
    """Mobile pairing detail page for a pot row (same link the pot page shows)."""
    d = row_date(row.get("start", ""), today)
    if not d or not row.get("pairing"):
        return None
    return (f"https://ha2.flica.net/full/mobilepairing.cgi?PID={row['pairing']}&DATE={d:%Y%m%d}"
            "&FROM=MobileOpentimePot&CurrentPage=1")


# Detail text (Nov 1, 2026): "... blk : 1218 tafb : 2609 pay : 1218 crew: ca 10007 lane jr, chris fo open" (names made up)
# FW-0058: a seat code counts only in FLICA's seat position, standing alone and followed by the employee number or
# 'Open' ("CA 10001 ..." / "FO Open"); the same letters inside a name ("LEE, SO YOUNG", made up) are part of the name.
SEAT_AT = r"(?<![\w'.,-])(?:CA|FO|RO|FA|SO)\s+(?=\d+\b|open\b)"
CA_RE = re.compile(r"crew\s*:.*?(?<![\w'.,-])ca\s+(?=\d+\b|open\b)(?:\d{3,7}\s+)?(.+?)(?=\s+" + SEAT_AT + r"|$)", re.I)
# Crew line (Nov 1, 2026): "Crew: CA 10001 SMITH JR, JOHN CA 10002 DOE, JANE FO Open" (names made up)
CREW_POS = ("CA", "FO", "RO", "FA", "SO")
CREW_RE = re.compile(r"(?<![\w'.,-])(CA|FO|RO|FA|SO)\s+(?=\d+\b|open\b)(?:(\d{3,7})\s+)?(.+?)(?=\s+" + SEAT_AT + r"|\s*$)",
                     re.I)
# FLICA tags a check pilot in the name ("CA 10001 DOE, CKP JANE", Nov 2026; FW-0017)
CKP_RE = re.compile(r"(?<![\w'-])ckp(?![\w'-])", re.I)
CHECKIN_RE = re.compile(r"check\s*in\s*:\s*(\d{1,2}:?\d{2})", re.I)
# A leg: flight number then STN-STN ("Th 865 HNL-PPG 1630 ..."). The column header "Dps-Ars"
# has no flight number in front, so it never matches.
LEG_RE = re.compile(r"\b\d{1,4}\s+([A-Za-z]{3})-([A-Za-z]{3})\b(?:\s+(\d{4})\s+(\d{4}))?")
LEG_DOW = ["SU", "MO", "TU", "WE", "TH", "FR", "SA"]
DAY_LEG_RE = re.compile(r"\b(su|mo|tu|we|th|fr|sa)\s+\d{1,4}\s+[A-Za-z]{3}-[A-Za-z]{3}\b", re.I)
TOT_RE = {
    "blk": re.compile(r"\bblk\s*:\s*(\d{1,3}:?\d{2})", re.I),
    "credit": re.compile(r"\bpay\s*:\s*(\d{1,3}:?\d{2})", re.I),
    "tafb": re.compile(r"\btafb\s*:\s*(\d{1,3}:?\d{2})", re.I),
}


def _hm(v):
    v = v.replace(":", "")
    return f"{int(v[:-2])}:{v[-2:]}"


def parse_detail(html):
    """Best effort from a mobile pairing page: captain name and trip totals. Missing -> absent."""
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style", "noscript", "template"]):
        t.decompose()
    text = soup.get_text(" ", strip=True)
    out = {}
    m = CA_RE.search(text)
    if m:
        name = clean_name(m.group(1))[0]
        out["captain"] = "OPEN" if name.lower() == "open" else name.title()
        emp = crew_ids(text).get(out["captain"])
        if emp:
            out["captain"] = f"{out['captain']} ({emp})"
    m = CHECKIN_RE.search(text)
    if m:
        out["report"] = _hm(m.group(1))
    for k, rx in TOT_RE.items():
        # only H:MM-sized values: some pages carry a second "Pay : 1000000001" (an id), 0.4.3
        found = [v for v in rx.findall(text) if len(v.replace(":", "")) <= 5]
        if found:
            out[k] = _hm(found[0] if k == "credit" else found[-1])
    codes = DAY_LEG_RE.findall(text)
    if codes:  # trip length from the leg day codes (Su 804 ... Tu 933 ... = 3 days)
        idx = [LEG_DOW.index(c.upper()) for c in codes]
        span = sum((b - a) % 7 for a, b in zip(idx, idx[1:]))
        out["days"] = str(span + 1)
    crew = parse_crew(text)
    if crew:
        out["open_seats"] = ",".join(p for p, n in crew if n == "OPEN" and p in ("FO", "RO"))
        out["crew"] = [[p, n] for p, n in crew]  # roster while in the pot, for pickup diffs (0.4.0)
    found = LEG_RE.findall(text)
    legs = [(a.upper(), b.upper()) for a, b, _, _ in found]
    if found and found[-1][3]:
        v = found[-1][3]
        out["last_arr"] = f"{v[:2]}:{v[2:]}"  # final block-in at base (HST)
    if legs:
        base = legs[0][0]
        out["route"] = "-".join([base] + [b for _, b in legs])
        away = [b for _, b in legs if b != base]
        # Where the trip lands away from base: a turn's only stop (PPG), or every stop in order.
        out["turn"] = "/".join(dict.fromkeys(away))
    duties = parse_duties(text)
    if duties:
        out["duties"] = duties
    return out


LEG_FULL_RE = re.compile(r"\b(su|mo|tu|we|th|fr|sa)\s+\d{1,4}\s+([A-Za-z]{3})-([A-Za-z]{3})\s+(\d{4})\s+(\d{4})\s+(\d{4})\b", re.I)
# FW-0067: the same leg with its flight number captured too (LEG_FULL_RE keeps its 6 groups for watcher.py)
LEG_FLT_RE = re.compile(r"\b(su|mo|tu|we|th|fr|sa)\s+(\d{1,4})\s+([A-Za-z]{3})-([A-Za-z]{3})\s+(\d{4})\s+(\d{4})\s+(\d{4})\b",
                        re.I)
LAYOVER_MIN_H = 8  # a gap this long between legs is a layover, so a new duty period
# Standard UTC offsets (hours) of the stations on the HNL A330 package; DST is absorbed by snapping the
# printed arrival to the nearest day candidate (an hour off never moves it a day).
TZ = {"HNL": -10, "OGG": -10, "KOA": -10, "ITO": -10, "LIH": -10, "PPT": -10, "RAR": -10, "PPG": -11, "ANC": -9,
      "LAX": -8, "SFO": -8, "SEA": -8, "SAN": -8, "OAK": -8, "SMF": -8, "LAS": -8, "PDX": -8, "SJC": -8, "ONT": -8, "LGB": -8,
      "PHX": -7, "SLC": -7, "DEN": -7, "ORD": -6, "DFW": -6, "AUS": -6, "MSP": -6, "IAH": -6,
      "JFK": -5, "BOS": -5, "MCO": -5, "IAD": -5, "ATL": -5, "MIA": -5, "EWR": -5,
      "NRT": 9, "HND": 9, "KIX": 9, "CTS": 9, "FUK": 9, "NGO": 9, "ICN": 9, "SYD": 10, "BNE": 10, "MEL": 10,
      "AKL": 12, "SIN": 8, "MNL": 8, "CRK": 8, "TPE": 8, "PEK": 8, "PVG": 8, "HKG": 8}


def parse_legs(text):
    """0.5.2: every leg of a pairing page in HST minutes from the trip's first day (00:00 HST):
    [{dep, arr, to, blk, dep_l, arr_l, flt, frm}], same conversion as parse_duties. A pickup made between a
    leg's dep and arr happened in flight (blocked out, away from the gate). FW-0067: flt is the flight number
    ("865", leading zeros dropped) and frm the origin station, for the working flight sensor."""
    legs, off, last_idx = [], 0, None
    for dow, flt, a, b, dep, arr, blk in LEG_FLT_RE.findall(text or ""):
        idx = LEG_DOW.index(dow.upper())
        if last_idx is not None:
            off += (idx - last_idx) % 7
        last_idx = idx
        a, b = a.upper(), b.upper()
        dmin, amin, bmin = (int(dep[:2]) * 60 + int(dep[2:]), int(arr[:2]) * 60 + int(arr[2:]),
                            int(blk[:2]) * 60 + int(blk[2:]))
        sh_a, sh_b = (TZ[a] + 10) * 60 if a in TZ else None, (TZ[b] + 10) * 60 if b in TZ else None
        if sh_a is None or sh_b is None:
            dep_h = off * 1440 + dmin
            arr_h = dep_h + bmin
        else:
            dep_h = off * 1440 + dmin - sh_a              # printed local -> HST
            est = dep_h + bmin                             # arrival in HST from block time
            cands = [(off + k) * 1440 + amin - sh_b for k in (-1, 0, 1, 2)]
            arr_h = min(cands, key=lambda c: abs(c - est))
        legs.append({"dep": dep_h, "arr": arr_h, "to": b, "blk": bmin, "dep_l": f"{dmin // 60:02d}:{dmin % 60:02d}",
                     "arr_l": f"{amin // 60:02d}:{amin % 60:02d}", "flt": str(int(flt)), "frm": a})
    return legs


def parse_duties(text):
    """Duty periods from the leg list (0.4.15, Ryan: a 30 in 7 can happen on a layover). FLICA prints
    leg times in station local time; each is converted to HST minutes from the trip's first day
    (00:00 HST) with the TZ table, and the printed arrival is snapped to the day that best matches
    departure + block. A gap of LAYOVER_MIN_H+ between legs starts a new duty. Each duty: {d: dep
    day offset (HST), dep: HST minutes, arr: HST minutes, stn: station it ends at, dep_l/arr_l: the
    printed local times}. Report = dep - 1:00, release = arr + 0:15 (PWA 2, 4.2.2) are left to the
    reader. Stations missing from TZ fall back to the printed-time heuristic (arr < dep = next day)."""
    legs = parse_legs(text)
    if not legs:
        return []
    duties, cur = [], None
    for lg in legs:
        if cur is not None and lg["dep"] - cur["arr"] >= LAYOVER_MIN_H * 60:
            duties.append(cur)
            cur = None
        if cur is None:
            cur = dict(lg)
        else:
            cur.update(arr=lg["arr"], to=lg["to"], arr_l=lg["arr_l"], blk=cur["blk"] + lg["blk"])
    duties.append(cur)
    return [{"d": x["dep"] // 1440, "dep": x["dep"], "arr": x["arr"], "stn": x["to"], "blk": x["blk"], "dep_l": x["dep_l"], "arr_l": x["arr_l"]}
            for x in duties]


def clean_name(name):
    """(name, ckp) without FLICA's check pilot tag (FW-0017): 'DOE, CKP JANE' -> ('DOE, JANE', True). The tag is
    a word of its own, after the comma on the live pages, taken out wherever it stands."""
    s = re.sub(r"\s+", " ", str(name or "")).strip(" ,")
    out = CKP_RE.sub(" ", s)
    if out == s:
        return s, False
    return re.sub(r"\s+", " ", re.sub(r"\s*,\s*", ", ", out)).strip(" ,"), True


def parse_crew(text):
    """[(pos, name)] from the crew line, in page order. An open seat's name is 'OPEN'. FW-0017: names without
    the CKP tag."""
    m = re.search(r"crew\s*:\s*(.*)$", text or "", re.I | re.S)
    if not m:
        return []
    out = []
    for pos, _emp, name in CREW_RE.findall(m.group(1)):
        name = clean_name(name)[0]
        out.append((pos.upper(), "OPEN" if name.lower() == "open" else name.title()))
    return out


def crew_ids(text):
    """{name: employee number} from the crew line (0.4.11: Ryan wants the numbers shown), names as parse_crew
    gives them."""
    m = re.search(r"crew\s*:\s*(.*)$", text or "", re.I | re.S)
    if not m:
        return {}
    out = {}
    for _pos, emp, name in CREW_RE.findall(m.group(1)):
        name = clean_name(name)[0]
        if emp and name.lower() != "open":
            out[name.title()] = emp
    return out


def with_ids(who, ids):
    """'FO Roe, Rick; RO Poe, Pat' -> 'FO Roe, Rick (10003); RO Poe, Pat (10005)' when known."""
    parts = []
    for part in (who or "").split("; "):
        pos, _, name = part.partition(" ")
        emp = ids.get(name)
        parts.append(f"{part} ({emp})" if emp else part)
    return "; ".join(p for p in parts if p)


def pickup_result(crew, seats):
    """Who now holds the seats that were open. seats: e.g. ['FO']; [] = unknown, report every
    FO and RO. Returns (status, text): filled / open / unknown."""
    want = seats or ["FO", "RO"]
    rows = [(p, n) for p, n in crew if p in want]
    if not rows:
        return "unknown", ""
    filled = [f"{p} {n}" for p, n in rows if n != "OPEN"]
    if seats and any(n == "OPEN" for p, n in rows):
        return "open", "; ".join(filled)
    return ("filled", "; ".join(filled)) if filled else ("open", "")


def pickup_diff(before, after):
    """Who took the trip, by comparing the FO/RO roster seen while it was in the pot (before)
    with the roster after it left (after). FLICA shows the open seat either as 'FO Open' or
    not at all, so a newcomer in an FO/RO seat is the pickup either way.
    Returns (status, text, known): filled + 'FO Name' (known=True); open = a FO/RO seat still
    reads Open; unchanged = same FO/RO crew as before (dropper kept it, or trip changed)."""
    if before is None:
        return (*pickup_result(after, []), False)
    if not any(p in ("FO", "RO") or p == "CA" for p, _ in after):
        return "unknown", "", False
    seen = {(p, clean_name(n)[0]) for p, n in before}  # FW-0017: a roster stored before the fix can carry 'Ckp'
    new = [f"{p} {n}" for p, n in after if p in ("FO", "RO") and n != "OPEN" and (p, n) not in seen]
    if new:
        return "filled", "; ".join(new), True
    if any(p in ("FO", "RO") and n == "OPEN" for p, n in after):
        return "open", "", True
    return "unchanged", "", True


def soft_time(credit, blk):
    """Credit minus block, as H:MM. None when either is missing or block >= credit gives 0:00."""
    c, b = hours(credit), hours(blk)
    if c is None or b is None:
        return None
    mins = max(0, round((c - b) * 60))
    return f"{mins // 60}:{mins % 60:02d}"


# ---- My schedule (mobileschedule.cgi), read only (0.3.0) ----
DOW = ("SU", "MO", "TU", "WE", "TH", "FR", "SA")
SCHED_MONTH = re.compile(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{4})\s+Schedule", re.I)
SCHED_UPDATED = re.compile(r"Schedule Updated:\s*([A-Za-z]{3}\s+\d{1,2},\s*\d{4}\s+\d{1,2}:\d{2}(?::\d{2})?)")


def parse_schedule(html, domicile="HNL"):
    """Ryan's month schedule from the mobile schedule page. Returns None unless it looks like one.
    {'month': 'YYYY-MM', 'updated': 'Nov 1, 2026 09:54:34', 'days': [[iso, act, lay]],
     'items': [{'trip','start','end','lay'}], 'totals': {...}}. act is '' on an empty day."""
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)
    m = SCHED_MONTH.search(text)
    if not m:
        return None
    mon, yr = MON3.index(m.group(1)[:3].upper()) + 1, int(m.group(2))
    days, prev_dd = [], 0
    for tr in soup.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"], recursive=False)]
        i = next((k for k, c in enumerate(cells) if c.upper() in DOW), None)
        if i is None or i + 2 >= len(cells) or not re.fullmatch(r"\d{1,2}", cells[i + 1]):
            continue
        dd = int(cells[i + 1])
        if dd < prev_dd:  # rolled into the next month (trip ending after month end)
            mon, yr = (1, yr + 1) if mon == 12 else (mon + 1, yr)
        prev_dd = dd
        rest = [c for c in cells[i + 2:]]
        act = rest[0] if rest else ""
        lay = rest[1] if len(rest) > 1 else ""
        act = "" if act in ("-", "") else act
        try:
            days.append([date(yr, mon, dd).isoformat(), act, lay])
        except ValueError:
            continue
    if len(days) < 20:
        return None
    items = schedule_items(days, domicile)
    tot = {}
    for key, pat in (("block", r"Block\s+([\d.:]+)"), ("credit", r"Credit\s+([\d.:]+)"),
                     ("ytd", r"YTD\s+([\d.:]+)"), ("days_off", r"Days Off\s+(\d+)")):
        t = re.search(pat, text)
        if t:
            tot[key] = int(t.group(1)) if key == "days_off" else t.group(1)
    if "days_off" not in tot:  # the OT drop view has no totals; FLICA counts VAC days as off
        y0, m0 = days[0][0][:4], days[0][0][5:7]
        work = set()
        for it in items:
            if PAIRING_RE.match(it["trip"]):
                for d in _span(date.fromisoformat(it["start"]), date.fromisoformat(it["end"])):
                    work.add(d.isoformat())
        tot["days_off"] = sum(1 for d in days if d[0][:7] == f"{y0}-{m0}" and d[0] not in work)
    u = SCHED_UPDATED.search(text)
    first = date.fromisoformat(days[0][0])
    return {"month": f"{first.year}-{first.month:02d}", "updated": u.group(1) if u else "",
            "days": days, "items": items, "totals": tot}


def _away(lay, domicile):
    """A layover cell that means Ryan is still away at the end of that day: a station other than domicile. FLICA writes
    '-' on a trip's middle days and on days off alike, so '-' says nothing either way."""
    return bool(lay) and lay not in ("-", domicile)


def schedule_items(days, domicile="HNL"):
    """The items of a month from its days [[iso, act, lay]] (parse_schedule; also used to repair stored versions).
    A pairing ends on the first later day whose layover cell is domicile. Trip end: when the next activity starts on the
    day the trip comes home (H3681 SYD Nov 9 to 12, then H3620 on Nov 12), FLICA shows only that activity's row on that
    day, so there is no domicile cell: a trip still away (its first layover a station, nothing but '-' since) ends on
    the day the next activity starts. Codes (VAC, SCR...) merge over consecutive days."""
    items = []
    for k, (d, act, lay) in enumerate(days):
        if not act:
            continue
        if not PAIRING_RE.match(act):  # VAC, SCR, etc: merge consecutive identical codes
            if items and items[-1]["trip"] == act and items[-1]["_k"] == k - 1:
                items[-1].update(end=d, _k=k)
            else:
                items.append({"trip": act, "start": d, "end": d, "lay": "", "_k": k})
            continue
        end, away = d, _away(lay, domicile)
        for j in range(k + 1, min(k + 8, len(days))):
            if days[j][1]:
                if away and days[j][0] > end:
                    end = days[j][0]  # trip end: home that morning, out again on the next activity
                break
            if days[j][2] == domicile:
                end = days[j][0]
                break
            if days[j][2] not in ("-",) and not _away(days[j][2], domicile):
                away = False  # an empty layover cell: not on the trip any more
        items.append({"trip": act, "start": d, "end": end, "lay": lay if lay != "-" else "", "_k": k})
    for it in items:
        it.pop("_k", None)
    return items


def _span(a, b):
    from datetime import timedelta
    out, d = [], a
    while d <= b:
        out.append(d)
        d += timedelta(days=1)
    return out


def fit_tag(start, end, sched):
    """'Fits', 'Conflict H3659', 'Check rest H3628', 'Days off 11' or '' when the schedule
    doesn't cover those dates. start/end are dates. Days off: 12 in a 30-day month, 13 in a
    31-day month (10.G). Rest next to a trip needs times the schedule page lacks, so it is flagged."""
    from datetime import timedelta
    if not sched or not start:
        return ""
    end = end or start
    covered = {d[0] for d in sched.get("days", [])}
    if start.isoformat() not in covered or end.isoformat() not in covered:
        return ""
    busy = {}
    for it in sched.get("items", []):
        for d in _span(date.fromisoformat(it["start"]), date.fromisoformat(it["end"])):
            busy[d] = it["trip"]
    mine = _span(start, end)
    hit = [busy[d] for d in mine if d in busy]
    if hit:
        return f"Conflict {hit[0]}"
    near = [t for t in (busy.get(start - timedelta(days=1)), busy.get(end + timedelta(days=1)))
            if t and PAIRING_RE.match(t)]
    near = near[0] if near else None
    if near:
        return f"Check rest {near}"
    off = sched.get("totals", {}).get("days_off")
    if isinstance(off, int):
        y, m = map(int, sched["month"].split("-"))
        nxt = date(y + (m == 12), m % 12 + 1, 1)
        mdays = (nxt - date(y, m, 1)).days
        need = 13 if mdays == 31 else 12
        used = sum(1 for d in mine if d.year == y and d.month == m)
        if off - used < need:
            return f"Days off {off - used}"
    return "Fits"


def layout_still_parses(html):
    """True when the pot page still yields well-formed rows: a pairing id, a start date the
    parser understands and a credit in hours. Anything less is a real layout change."""
    try:
        rows = parse_pot(html)
        return bool(rows) and all(r.get("pairing") and row_date(r.get("start") or (r.get("dates") or "").split("-")[0])
                                  and hours(r.get("credit")) is not None for r in rows.values())
    except Exception:
        return False


# FLICA alert email (Nov 1, 2026): "3 alert matched pairings 'Nov 13-20 Max': H3627:18NOV from
# 'OPEN TIME- Add/Swap/Drop requests - November', H3627:18NOV from 'Close in Opentime: ...'"
ALERT_RE = re.compile(r"\b([A-Z]\d{4}):(\d{2})([A-Za-z]{3})\b(?:\s+from\s+'([^']*)')?")


def parse_alert_email(text):
    """[{key, pairing, start, sources}] from a FLICA alert email, one per pairing and date.
    key matches the pot keys ('H3627|18Nov')."""
    out = {}
    for pid, dd, mon, src in ALERT_RE.findall(text or ""):
        start = f"{dd}{mon.title()}"
        k = f"{pid}|{start}"
        e = out.setdefault(k, {"key": k, "pairing": pid, "start": start, "sources": []})
        if src and src.strip() not in e["sources"]:
            e["sources"].append(src.strip())
    return list(out.values())


CM_PAIR_RE = re.compile(r"pair\(\s*'([A-Z]\d{4}[A-Z]?)'\s*,\s*'(\d{8})'")


def parse_cm_schedule(html):
    """0.5.2: pairings on a crewmember schedule page (Tools > Schedule Lookup, cmschedules.cgi):
    [{'trip': 'H3648', 'start': '2026-11-03'}] from its pair('H3648','20261103',0) links, in page
    order, duplicates kept once."""
    out, seen = [], set()
    for trip, ymd in CM_PAIR_RE.findall(html or ""):
        k = (trip, ymd)
        if k in seen:
            continue
        seen.add(k)
        out.append({"trip": trip, "start": f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}"})
    return out


def inflight_at(legs, start_iso, at_utc_iso):
    """True when the UTC instant falls inside a leg (block out to block in) of a pairing that
    started on start_iso (HST day 0); False otherwise; None when the inputs do not parse."""
    try:
        start = datetime.strptime(start_iso, "%Y-%m-%d")
        at = datetime.fromisoformat(at_utc_iso.replace("Z", "+00:00"))
        if at.tzinfo is not None:
            at = at.astimezone(timezone.utc).replace(tzinfo=None)
        at_hst = at - timedelta(hours=10)
        m = (at_hst - start).total_seconds() / 60
    except (TypeError, ValueError):
        return None
    return any(lg["dep"] <= m <= lg["arr"] for lg in legs or [])


def parse_schedule_desktop(html, domicile="HNL"):
    """0.7.1: Ryan's month from the desktop Schedules page (scheduledetail.cgi). Same result shape as
    parse_schedule. Returns None until the page layout is known (first captures land in /share)."""
    return None
