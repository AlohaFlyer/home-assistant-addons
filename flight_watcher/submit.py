"""Swap submission (0.5.0, Ryan): compose the exact FLICA swap request the Watcher WOULD file.
Pure, no I/O. Mapped with Ryan in his browser on 2026-11-03 (read only, nothing filed).

Flow: Open Time Requests > Create Request > SWAP > tick the trip to give > Continue > tick the
pot trip to take > Continue > 'Create SWAP Request' review page. That page is ONE form,
POST /full/mobileotswap.cgi, whose Submit button files the request. Everything before it is
selection only. The request then shows on mobileotrequest.cgi?BCID=..&From=MainMenu as a Swap
row with Approved / Denied.

Modes: TEST logs the composed POST and never sends (the only mode this version implements);
CONFIRM would wait for an Approve press in HA; LIVE would send at most LIVE_PER_DAY a day.
WRITES_IMPLEMENTED stays False: the Watcher refuses CONFIRM and LIVE until Ryan has reviewed
TEST output and the send path is written, tested and switched on by him.

Close-in rule (Ryan, 2026-11-03): any add or swap involving a trip inside CLOSE_IN_H hours to
report must be filed from the 'Close in Opentime: <16 Hrs to RPT' folder (its own BCID, 008.xxx
series) or FLICA denies it. The close-in BCID is not read yet, so such a swap is composed with
folder 'close-in' and no BCID, and is never sendable."""
import re
from datetime import datetime

MODES = ("Test", "Confirm", "Live")
DEFAULT_MODE = "Test"
WRITES_IMPLEMENTED = False
LIVE_PER_DAY = 1
CLOSE_IN_H = 16
SWAP_PATH = "/full/mobileotswap.cgi"
REQUESTS_PATH = "/full/mobileotrequest.cgi"
DANGEROUS = ("QuickDelete", "CreateRequest", "SubmitBid")


def safe_get(url):
    """True when a GET of this URL cannot change anything. The request list's Approved / Denied
    links carry QuickDelete=1 and DELETE the request on a plain GET; never fetch those."""
    return not any(d.lower() in url.lower() for d in DANGEROUS)


def ymd(iso):
    return iso.replace("-", "")


def folder_for(hours_to_report):
    """'close-in' when the trip reports inside CLOSE_IN_H hours, else 'pot'. None hours = 'pot'."""
    if hours_to_report is not None and hours_to_report < CLOSE_IN_H:
        return "close-in"
    return "pot"


def swap_form(bcid, give_trip, give_start, take_trip, take_start, seat="F", priority=1):
    """The hidden fields of the 'Create SWAP Request' form, exactly as mapped. give_start and
    take_start are ISO dates (trip day 1). seat is the open seat letter FLICA shows, 'F' for FO,
    'R' for RO (AddList carries it as a -F / -R suffix)."""
    return {
        "BCID": bcid,
        "Priority": str(priority),
        "DropList": f"{give_trip}:{ymd(give_start)}",
        "AddList": f"{take_trip}:{ymd(take_start)}-{seat}",
        "SubmitBid": "1",
        "CanSplitList": "0",
        "SplitDetail": "Split",
        "SecCanSplitList": "0",
        "SecSplitDetail": "Split",
        "AOT": "",
        "LimoData": "",
        "QuickSwap": "0",
        "Convert": "0",
        "ABI": "",
        "Submit": "Submit",
    }


def compose(idea, bcid, hours_to_report=None, seat="F", close_in_bcid=None):
    """A swap request record for one idea ({'for': 'TRIP|YYYY-MM-DD', 'pairing', 'start'}):
    {'folder', 'bcid', 'url', 'form', 'sendable', 'why'}. Never sends."""
    give_trip, give_start = idea["for"].split("|")
    folder = folder_for(hours_to_report)
    b = close_in_bcid if folder == "close-in" else bcid
    rec = {"folder": folder, "bcid": b, "url": SWAP_PATH, "give": f"{give_trip} {give_start}",
           "take": f"{idea['pairing']} {idea['start']}", "form": None, "sendable": False, "why": ""}
    if not b:
        rec["why"] = "close-in folder BCID not read yet" if folder == "close-in" else "pot BCID unknown"
        return rec
    rec["form"] = swap_form(b, give_trip, give_start, idea["pairing"], idea["start"], seat)
    rec["why"] = "composed, not sent (Test mode)" if not WRITES_IMPLEMENTED else "composed"
    return rec


REQ_RE = re.compile(r"(\d{2}/\d{2})\s+(\d{2}:\d{2})\s+(Add|Swap|Drop)\s+(Approved|Denied|Pending)", re.I)


def parse_requests(text):
    """[{'date': '11/02', 'time': '18:41', 'type': 'Swap', 'status': 'Approved'}] from the visible
    text of the Open Time Requests page, in page order (creation order)."""
    return [{"date": d, "time": t, "type": k.title(), "status": s.title()} for d, t, k, s in REQ_RE.findall(text)]


TRIP_RE = re.compile(r"\b([A-Za-z]\d{4}[A-Za-z]?)\b(?:[\s:]+(\d{1,2})\s?([A-Za-z]{3})\b)?")
SIDE_RE = re.compile(r"\b(drop|give|from|add|take|pick\s?up|to)\b", re.I)
SIDE_OF = {"drop": "drop", "give": "drop", "from": "drop", "add": "add", "take": "add", "pickup": "add", "pick up": "add",
           "to": "add"}
DECIDED = ("Approved", "Denied")


def requests_url(base, bcid):
    """The Open Time Requests list for one bid folder. A plain list GET; the per-row Approved / Denied links
    (QuickDelete=1) are never followed."""
    return f"{base}{REQUESTS_PATH}?BCID={bcid}&From=MainMenu"


def _legs(detail):
    """[{trip, day, side}] of the pairings named in a request's text; side from the last drop / add word before each."""
    legs, prev = [], 0
    for tm in TRIP_RE.finditer(detail):
        labels = SIDE_RE.findall(detail[prev:tm.start()])
        side = SIDE_OF.get(re.sub(r"\s+", " ", labels[-1].lower())) if labels else ""
        day = f"{int(tm.group(2)):02d}{tm.group(3).upper()}" if tm.group(2) else ""
        legs.append({"trip": tm.group(1).upper(), "day": day, "side": side})
        prev = tm.end()
    return legs[:4]


REQ_ID_RE = re.compile(r"ShowRequest=1&(?:amp;)?TimeStamp=([0-9A-Fa-f]{4,}:[0-9A-Fa-f]{4,})")


def request_ids(html):
    """1.2.2: FLICA's own id of each request row (the TimeStamp of its read-only ShowRequest link), in page order."""
    return REQ_ID_RE.findall(html or "")


def request_view_url(base, bcid, ts):
    """The read-only view of one request (its ShowRequest link, with the BCID the page's addMRLink() appends).
    Never the QuickDelete link beside it, which deletes the request on a GET."""
    return f"{base}{REQUESTS_PATH}?ShowRequest=1&TimeStamp={ts}&BCID={bcid}&From=Self&Parent=MainMenu"


VIEW_SIDE_RE = re.compile(r"\b(drop|give\s?up|add|pick\s?up|take)\b", re.I)
VIEW_SIDE_OF = {"drop": "drop", "give up": "drop", "giveup": "drop", "add": "add", "pick up": "add", "pickup": "add",
                "take": "add"}


def _view_legs(text):
    """Legs of a request's view page. Strict: only drop / give up / add / pick up / take, found between the previous
    trip and this one and at most 40 characters before it (a page header such as 'Add/Swap/Drop requests' or a
    'From:' line never labels a trip); each trip once."""
    legs, prev, seen = [], 0, set()
    for tm in TRIP_RE.finditer(text):
        labels = VIEW_SIDE_RE.findall(text[max(prev, tm.start() - 40):tm.start()])
        prev = tm.end()
        trip = tm.group(1).upper()
        if trip in seen:
            continue
        seen.add(trip)
        side = VIEW_SIDE_OF.get(re.sub(r"\s+", " ", labels[-1].lower())) if labels else ""
        day = f"{int(tm.group(2)):02d}{tm.group(3).upper()}" if tm.group(2) else ""
        legs.append({"trip": trip, "day": day, "side": side})
    return legs[:4]


def parse_request_view(text):
    """{legs, trips, detail} from one request's view page: the pairings it drops and adds."""
    legs = _view_legs(text or "")
    m = TRIP_RE.search(text or "")
    detail = re.sub(r"\s+", " ", text[max(0, m.start() - 60):m.start() + 160]).strip() if m else ""
    return {"legs": legs, "trips": [x["trip"] for x in legs], "detail": detail}


def parse_request_rows(text, html=None):
    """1.2.0: the request rows of the Open Time Requests page's visible text, each with the text that follows it
    up to the next row ('detail') and the pairings named there ('trips'). key = date|time|type|trips|n, n counting
    rows that are otherwise identical. 1.2.2: with the page's html, key = 'ts:<FLICA request id>' (stable when
    other requests are cleared) and 'alt' keeps the content key; the list itself names no trips, so detail is
    empty and trips come from the request's own view page."""
    rows, seen = [], {}
    ms = list(REQ_RE.finditer(text))
    for i, m in enumerate(ms):
        d, t, k, st = m.group(1), m.group(2), m.group(3).title(), m.group(4).title()
        end = ms[i + 1].start() if i + 1 < len(ms) else min(len(text), m.end() + 300)
        detail = re.sub(r"\s+", " ", text[m.end():end]).strip()[:200]
        legs = _legs(detail)
        trips = [x["trip"] for x in legs]
        base = f"{d}|{t}|{k}|{'+'.join(sorted(trips))}"
        seen[base] = seen.get(base, 0) + 1
        rows.append({"key": f"{base}|{seen[base]}", "date": d, "time": t, "type": k, "status": st,
                     "trips": trips, "legs": legs, "detail": detail})
    ids = request_ids(html)
    if ids and len(ids) == len(rows):
        for r, ts in zip(rows, ids):
            r.update({"alt": r["key"], "key": f"ts:{ts}", "ts": ts, "detail": "", "legs": [], "trips": []})
    return rows


REQ_PAGE_RE = re.compile(r"\brequests?\b", re.I)


def is_request_page(text, rows):
    """A read counts only when the page is the request list: it has request rows, or at least speaks of requests
    (an empty list). An error, maintenance or interstitial page that classify() lets through is not a read."""
    return bool(rows) or bool(REQ_PAGE_RE.search(text or ""))


def push_key(r):
    return f"{r['key']}|{r['status']}"


def request_news(pushed, rows):
    """Rows to push: Approved / Denied rows whose push_key is not in pushed ({push_key: last seen}, kept in state).
    A row that drops out of one read (an error page) and comes back never fires twice; a row pushed under its
    1.2.1 content key ('alt') is not pushed again under its 1.2.2 id."""
    return [r for r in rows if r["status"] in DECIDED and push_key(r) not in pushed
            and f"{r.get('alt')}|{r['status']}" not in pushed]


def hours_until(report_iso, now):
    """Hours from now (naive HST datetime) to an ISO 'YYYY-MM-DDTHH:MM' report time; None if unparsable."""
    try:
        return (datetime.fromisoformat(report_iso) - now).total_seconds() / 3600
    except (TypeError, ValueError):
        return None


DROP_PATH = "/full/mobileotdrop.cgi"  # UNMAPPED: the DROP review page has not been walked yet; fields are a best guess


def drop_form(bcid, trip, start, priority=1):
    """Best-guess fields of the DROP request form, modelled on the mapped SWAP form (AddList empty).
    Not sendable until the DROP review page is mapped read only with Ryan."""
    return {
        "BCID": bcid, "Priority": str(priority), "DropList": f"{trip}:{ymd(start)}", "AddList": "",
        "SubmitBid": "1", "CanSplitList": "0", "SplitDetail": "Split", "SecCanSplitList": "0",
        "SecSplitDetail": "Split", "AOT": "", "LimoData": "", "QuickSwap": "0", "Convert": "0", "ABI": "",
        "Submit": "Submit",
    }


def compose_drop(key, bcid, hours_to_report=None, close_in_bcid=None):
    """A drop request record for a marked trip 'TRIP|YYYY-MM-DD': {'folder','bcid','url','give','form',
    'sendable','why'}. Never sends; the form is a draft until the DROP page is mapped."""
    trip, start = key.split("|")
    folder = folder_for(hours_to_report)
    b = close_in_bcid if folder == "close-in" else bcid
    rec = {"folder": folder, "bcid": b, "url": DROP_PATH, "give": f"{trip} {start}", "form": None,
           "sendable": False, "why": ""}
    if not b:
        rec["why"] = "close-in folder BCID not read yet" if folder == "close-in" else "pot BCID unknown"
        return rec
    rec["form"] = drop_form(b, trip, start)
    rec["why"] = "draft, not sent (Test mode; DROP review page not mapped yet)"
    return rec
