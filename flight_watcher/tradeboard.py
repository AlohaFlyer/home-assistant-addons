"""Tradeboard (read only): find posts whose Response Method is 'Pickup Trip' (a drop up for grabs).

Pure parsing, no network. Row shape on tb_otherrequests.cgi (Nov 2026):
Type | Trip (H3646:26NOV, HNL 332 FO) | Days | Report/Depart/Arrive | Blk/TPay | L/O | Comments | Name + posted | Response
"""
import re
from datetime import timedelta
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from pot import row_date, soft_time

TRIP_RE = re.compile(r"\b([A-Z]\d{4}):(\d{2})([A-Z]{3})\b")
TIME_RE = re.compile(r"\b(\d{1,2}:\d{2})\b")
PICKUP_RE = re.compile(r"pick\s*-?\s*up\s+trip", re.I)
POSTED_RE = re.compile(r"([A-Z][a-z]{2} \d{1,2}, \d{4} \d{2}:\d{2}:\d{2})")


def other_requests_url(frame_html, frame_url):
    """From tb_frame.cgi, the All Requests page (tb_otherrequests.cgi)."""
    soup = BeautifulSoup(frame_html, "html.parser")
    for tag in soup.find_all(["a", "frame", "iframe"]):
        u = tag.get("href") or tag.get("src") or ""
        if "tb_otherrequests" in u.lower():
            return urljoin(frame_url, u)
    m = re.search(r"['\"]([^'\"]*tb_otherrequests\.cgi[^'\"]*)['\"]", frame_html, re.I)
    if m:
        return urljoin(frame_url, m.group(1))
    return None


def _leaf_rows(soup):
    """Rows that hold a trip id and are not wrappers around other such rows."""
    out = []
    for tr in soup.find_all("tr"):
        txt = tr.get_text(" ", strip=True)
        if not TRIP_RE.search(txt):
            continue
        if any(TRIP_RE.search(inner.get_text(" ", strip=True)) for inner in tr.find_all("tr")):
            continue
        out.append(tr)
    return out


JS_TYPES = {"D": "Drop", "X": "Trade/Drop", "T": "Trade", "G": "Pickup", "R": "Reserve", "V": "Vacation"}
PICKUP_TYPES = ("D", "X")  # posts answered with the "Pickup Trip" button


def _js_args(src, i):
    """Split the argument list starting at src[i] (just after 'new A(') into raw tokens."""
    out, cur, q = [], "", None
    while i < len(src):
        ch = src[i]
        if q:
            cur += ch
            if ch == "\\" and i + 1 < len(src):
                cur += src[i + 1]
                i += 1
            elif ch == q:
                q = None
        elif ch in "\"'":
            q = ch
            cur += ch
        elif ch == ",":
            out.append(cur.strip())
            cur = ""
        elif ch == ")":
            out.append(cur.strip())
            return out
        else:
            cur += ch
        i += 1
    return out


def _v(tok):
    if len(tok) >= 2 and tok[0] == tok[-1] and tok[0] in "\"'":
        from urllib.parse import unquote
        return unquote(tok[1:-1]).replace("&nbsp;", "").strip()
    return tok


def parse_js(html, today=None):
    """Tradeboard rows come as r[i]=new A(request_id, response_id, n, cid, TYPE, "H3606",
    "Nov 4, 2026", "04NOV", "20261104", flica, email, phone, first, last, comments, auto,
    created, accepted, accepted_id, hasdetails, report, days, blk, credit, layover, dep, arr, ...)."""
    out = {}
    for m in re.finditer(r"new\s+A\s*\(", html):
        a = _js_args(html, m.end())
        if len(a) < 27:
            continue
        typ = a[4]
        if typ not in PICKUP_TYPES:
            continue
        v = [_v(x) for x in a]
        pairing, date2 = v[5], v[7]
        start = f"{date2[:2]}{date2[2:5].title()}" if len(date2) >= 5 else date2
        days = v[21]
        r = {"pairing": pairing, "start": start, "days": days, "layover": v[24],
             "report": v[20], "depart": v[25], "arrive": v[26], "blk": v[22], "credit": v[23],
             "poster": f"{v[12]} {v[13]}".title().strip(), "posted": v[16], "post_type": JS_TYPES.get(typ, typ),
             "comments": v[14][:200], "request_id": a[0], "source": "tradeboard"}
        d = row_date(start, today)
        r["end"] = ""
        if d and days.isdigit() and int(days) > 0:
            e = d + timedelta(days=int(days) - 1)
            r["end"] = f"{e.day:02d}{e.strftime('%b')}"
        r["dates"] = f"{r['start']}-{r['end']}" if r["end"] else r["start"]
        r["soft"] = soft_time(r["credit"], r["blk"]) or ""
        out[f"{pairing}|{start}|{a[0]}"] = r
    return out


def has_rows(html):
    return bool(re.search(r"new\s+A\s*\(\s*\d", html)) or bool(TRIP_RE.search(html))


def parse_pickups(html, today=None):
    """{key: row} for each 'Pickup Trip' post (JS data first, HTML table fallback)."""
    if re.search(r"new\s+A\s*\(\s*\d", html):
        return parse_js(html, today)
    soup = BeautifulSoup(html, "html.parser")
    out = {}
    for tr in _leaf_rows(soup):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all("td", recursive=False)] or \
                [c.get_text(" ", strip=True) for c in tr.find_all("td")]
        txt = " | ".join(cells)
        if not PICKUP_RE.search(txt):
            continue
        m = TRIP_RE.search(txt)
        pairing, dd, mon = m.group(1), m.group(2), m.group(3)
        start = f"{dd}{mon.title()}"
        after = txt[m.end():]
        dm = re.search(r"\|\s*(\d{1,2})\s*\|", after)
        days = dm.group(1) if dm else ""
        times = TIME_RE.findall(after)
        lo = re.search(r"\|\s*([A-Z]{3})\s*\|", after)
        posted = POSTED_RE.search(txt)
        name = ""
        if posted:
            seg = txt[:posted.start()].rsplit("|", 1)[-1].strip()
            name = seg
        r = {"pairing": pairing, "start": start, "days": days, "layover": lo.group(1) if lo else "",
             "report": times[0] if len(times) > 0 else "", "depart": times[1] if len(times) > 1 else "",
             "arrive": times[2] if len(times) > 2 else "", "blk": times[3] if len(times) > 3 else "",
             "credit": times[4] if len(times) > 4 else (times[3] if len(times) > 3 else ""),
             "poster": name.title(), "posted": posted.group(1) if posted else "",
             "source": "tradeboard", "row": txt[:300]}
        d = row_date(start, today)
        if d and days.isdigit():
            e = d + timedelta(days=int(days) - 1)
            r["end"] = f"{e.day:02d}{e.strftime('%b')}"
        else:
            r["end"] = ""
        r["dates"] = f"{r['start']}-{r['end']}" if r["end"] else r["start"]
        r["soft"] = soft_time(r["credit"], r["blk"]) or ""
        out[f"{pairing}|{start}|{name}"] = r
    return out
