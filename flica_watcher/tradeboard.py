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


def parse_pickups(html, today=None):
    """{key: row} for each 'Pickup Trip' post. key = pairing|startDDMon|poster."""
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
