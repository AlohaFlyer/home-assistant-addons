"""Pure page logic: classify, parse, fingerprint, month links. No network, no MQTT.

Kept free of side effects so tests/ can run it against saved HTML fixtures.
"""
import hashlib
import re
from datetime import date
from urllib.parse import urljoin

from bs4 import BeautifulSoup

KILLED_TXT = "new session under this account was detected"
EXPIRED_HINTS = ("session has expired", "session expired", "please log in", "please sign in")
BLOCK_HINTS = ("captcha", "verification code", "one-time", "one time pass", "change your password",
               "password has expired", "account is locked", "account locked")
PAIRING_RE = re.compile(r"^[A-Z]\d{4}$")
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


# Detail text (Nov 1, 2026): "... blk : 1218 tafb : 2609 pay : 1218 crew: ca 14157 dimaya jr, fedelino fo open"
CA_RE = re.compile(r"crew\s*:.*?\bca\s+(?:\d{3,7}\s+)?(.+?)(?=\s+(?:fo|ro|fa|so|ca)\b|$)", re.I)
CHECKIN_RE = re.compile(r"check\s*in\s*:\s*(\d{1,2}:?\d{2})", re.I)
# A leg: flight number then STN-STN ("Th 865 HNL-PPG 1630 ..."). The column header "Dps-Ars"
# has no flight number in front, so it never matches.
LEG_RE = re.compile(r"\b\d{1,4}\s+([A-Za-z]{3})-([A-Za-z]{3})\b")
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
        name = m.group(1).strip(" ,")
        out["captain"] = "OPEN" if name.lower() == "open" else name.title()
    m = CHECKIN_RE.search(text)
    if m:
        out["report"] = _hm(m.group(1))
    for k, rx in TOT_RE.items():
        found = rx.findall(text)
        if found:
            out[k] = _hm(found[-1])
    legs = [(a.upper(), b.upper()) for a, b in LEG_RE.findall(text)]
    if legs:
        base = legs[0][0]
        out["route"] = "-".join([base] + [b for _, b in legs])
        away = [b for _, b in legs if b != base]
        # Where the trip lands away from base: a turn's only stop (PPG), or every stop in order.
        out["turn"] = "/".join(dict.fromkeys(away))
    return out


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
        end = d
        for j in range(k + 1, min(k + 8, len(days))):
            if days[j][1]:
                break
            if days[j][2] == domicile:
                end = days[j][0]
                break
        items.append({"trip": act, "start": d, "end": end, "lay": lay if lay != "-" else "", "_k": k})
    for it in items:
        it.pop("_k", None)
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
