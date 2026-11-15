"""Swap submission (0.5.0, Ryan): compose the exact FLICA swap request the Watcher WOULD file.
Pure, no I/O. Mapped with Ryan in his browser on 2026-11-03 (read only, nothing filed).

Flow: Open Time Requests > Create Request > SWAP > tick the trip to give > Continue > tick the
pot trip to take > Continue > 'Create SWAP Request' review page. That page is ONE form,
POST /full/mobileotswap.cgi, whose Submit button files the request. Everything before it is
selection only. The request then shows on mobileotrequest.cgi?BCID=..&From=MainMenu as a Swap
row with Approved / Denied.

Mode: Test only (FW-0028, Ryan: FLICA stays read-only for good). The Watcher composes the POST a
swap or drop would need, logs it and labels it DRAFT ('draft only, never sent'); nothing sends it.
The old Confirm and Live modes are gone (the Watcher turns a stored one into Test at start), and
WRITES_IMPLEMENTED stays False.

Close-in rule (Ryan, 2026-11-03): any add or swap involving a trip inside CLOSE_IN_H hours to
report must be filed from the 'Close in Opentime: <16 Hrs to RPT' folder (its own BCID, 008.xxx
series) or FLICA denies it. FW-0034: the Watcher finds that BCID on the menu (a link whose text names the
folder, never a guess) and trusts it once the folder's open time page reads (S['close_in_bcid']); until
then such a draft has folder 'close-in' and no BCID. Drafts are never sendable either way."""
import re
from datetime import datetime, timedelta, timezone

MODES = ("Test",)  # FW-0028: Confirm and Live removed for good
DEFAULT_MODE = "Test"
WRITES_IMPLEMENTED = False
DRAFT = "draft only, never sent"
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
           "take": f"{idea['pairing']} {idea['start']}", "form": None, "sendable": False, "draft": DRAFT, "why": ""}
    if not b:
        rec["why"] = f"{DRAFT}: " + ("close-in folder BCID not read yet" if folder == "close-in" else "pot BCID unknown")
        return rec
    rec["form"] = swap_form(b, give_trip, give_start, idea["pairing"], idea["start"], seat)
    rec["why"] = DRAFT
    return rec


# 1.4.1 (Ryan, Nov 6): a crew-to-crew Trade request ('Trade H3604:13NOV and H3659:18NOV With Emp #: ... For
# H3620:12NOV and H3620:15NOV') shows as type Trade, and an undecided request can read Processing as well as Pending.
REQ_RE = re.compile(r"(\d{2}/\d{2})\s+(\d{2}:\d{2})\s+(Add|Swap|Drop|Trade)\s+(Approved|Denied|Pending|Processing)", re.I)
OPEN = ("Pending", "Processing")  # not decided yet: the list is read every 2 min while one is open


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


SEAT_MARK_RE = re.compile(r"\s*\(([fcr])\)", re.I)
SEAT_OF = {"f": "FO", "c": "CA", "r": "RO"}


def _view_legs(text):
    """Legs of a request's view page. Strict: only drop / give up / add / pick up / take, found between the previous
    trip and this one and at most 40 characters before it (a page header such as 'Add/Swap/Drop requests' or a
    'From:' line never labels a trip); each trip and day once (1.4.1: a trade can take the same pairing on two
    days, H3620:12NOV and H3620:15NOV). 1.4.1: FLICA's seat mark after a trip, (F) / (R) / (C), is its seat."""
    legs, prev, seen = [], 0, set()
    for tm in TRIP_RE.finditer(text):
        labels = VIEW_SIDE_RE.findall(text[max(prev, tm.start() - 40):tm.start()])
        prev = tm.end()
        trip = tm.group(1).upper()
        day = f"{int(tm.group(2)):02d}{tm.group(3).upper()}" if tm.group(2) else ""
        if (trip, day) in seen or (not day and any(t == trip for t, _ in seen)):
            continue
        seen.add((trip, day))
        side = VIEW_SIDE_OF.get(re.sub(r"\s+", " ", labels[-1].lower())) if labels else ""
        sm = SEAT_MARK_RE.match(text, tm.end())
        legs.append({"trip": trip, "day": day, "side": side, "seat": SEAT_OF[sm.group(1).lower()] if sm else ""})
    return legs[:6]


CS_RE = re.compile(r"\bcs:\s*(.*?)(?=\s*\bnote:|$)", re.I | re.S)
SWAP_FOR_RE = re.compile(r"\bswap\s+([A-Za-z]\d{4}[A-Za-z]?)\b.*?\bfor\s+([A-Za-z]\d{4}[A-Za-z]?)\b", re.I | re.S)
# 1.4.1: 'Trade <given> and <given> With Emp #: <n> For <taken> and <taken>'
TRADE_RE = re.compile(r"\btrade\b(.*?)\bwith\b.*?\bfor\b(.*?)(?=\b(?:time|status|cm|cs)\s*:|$)", re.I | re.S)


def parse_request_view(text):
    """{legs, trips, detail, reason} from one request's view page (layout checked on the real page, 1.3.0; made-up
    values here): 'Swap H3911:21NOV (F) For H3914B:19NOV (F) Time: ... Status: Denied ... CM: [no comments] CS: <rest
    short on 20nov Note: ...'. FLICA writes a swap as 'Swap <given> For <taken>', so those two get drop / add when the page says so;
    reason = crew scheduling's comment (CS), '' when none."""
    text = text or ""
    legs = _view_legs(text)
    tr = TRADE_RE.search(text)
    if tr:  # 1.4.1: every trip before 'With' is given, every trip after 'For' is taken
        given = {(t.group(1).upper(), f"{int(t.group(2)):02d}{t.group(3).upper()}" if t.group(2) else "") for t in TRIP_RE.finditer(tr.group(1))}
        taken = {(t.group(1).upper(), f"{int(t.group(2)):02d}{t.group(3).upper()}" if t.group(2) else "") for t in TRIP_RE.finditer(tr.group(2))}
        for x in legs:
            k = (x["trip"], x["day"])
            if not x["side"]:
                x["side"] = "drop" if k in given else "add" if k in taken else ""
    m = None if tr else SWAP_FOR_RE.search(text)
    if m:
        give, take = m.group(1).upper(), m.group(2).upper()
        for x in legs:
            if not x["side"]:
                x["side"] = "drop" if x["trip"] == give else "add" if x["trip"] == take else ""
    t = TRIP_RE.search(text)
    detail = re.sub(r"\s+", " ", text[max(0, t.start() - 60):t.start() + 160]).strip() if t else ""
    c = CS_RE.search(text)
    reason = re.sub(r"\s+", " ", c.group(1)).strip()[:160] if c else ""
    if reason.strip("[]").strip().lower() in ("", "no comments", "none"):
        reason = ""
    return {"legs": legs, "trips": [x["trip"] for x in legs], "detail": detail, "reason": reason}


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
        whole = re.sub(r"\s+", " ", text[m.end():end]).strip()
        detail = whole[:200]
        legs = _legs(detail)
        trips = [x["trip"] for x in legs]
        base = f"{d}|{t}|{k}|{'+'.join(sorted(trips))}"
        seen[base] = seen.get(base, 0) + 1
        rows.append({"key": f"{base}|{seen[base]}", "date": d, "time": t, "type": k, "status": st,
                     "trips": trips, "legs": legs, "detail": detail})
        # 1.7.10: the row's own columns after the status: the decision time ('Denied 30 OCT 15:10') and, on a
        # denial for a pickup, the pairing and the picker's employee number (kept when the detail is dropped below)
        sa = status_at(f"{st} {whole[:40]}")
        if sa:
            rows[-1]["st_at"] = " ".join(sa)
        pu = picked_up(whole) if st == "Denied" else None
        if pu:
            rows[-1]["pu"] = {x: pu[x] for x in ("trip", "day", "emp")}
    ids = request_ids(html)
    if ids and len(ids) == len(rows):
        for r, ts in zip(rows, ids):
            r.update({"alt": r["key"], "key": f"ts:{ts}", "ts": ts, "detail": "", "legs": [], "trips": []})
    return rows


# ---------------------------------------------------------------- 1.7.10: the pickup speed cap (Ryan, Nov 15)
# A request FLICA denied because another pilot picked the trip up carries crew scheduling's comment
# 'CS: H3607:17NOV picked up by DOE, JANE (10001)' (made-up values). That picker asked before the pilot whose list
# this is, so his pickup speed ends no later than this request's Requested time (minute precision: its minute + 59 s).
PICKED_RE = re.compile(r"\b([A-Za-z]\d{4}[A-Za-z]?)\s*:\s*(\d{1,2})\s?([A-Za-z]{3})\s+picked\s+up\s+by\s+"
                       r"([A-Za-z\u00c0-\u024f][A-Za-z\u00c0-\u024f'.\- ]{0,40}?,\s*[A-Za-z\u00c0-\u024f'.\- ]{0,40}?)\s*"
                       r"\(\s*(\d{3,7})\s*\)", re.I)
MON3 = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")
STAMP_RE = re.compile(r"\b(\d{1,2})\s?(" + "|".join(MON3) + r")\s+(\d{1,2}):(\d{2})\b", re.I)
STATUS_AT_RE = re.compile(r"\b(?:approved|denied)\s+(?:(\d{1,2})\s?(" + "|".join(MON3) + r")|(\d{2})/(\d{2}))\s+"
                          r"(\d{1,2}):(\d{2})\b", re.I)
REQUESTED_RE = re.compile(r"\b(?:requested|time)\b[^0-9]{0,24}(?:(\d{1,2})\s?(" + "|".join(MON3) + r")|(\d{2})/(\d{2}))\s+"
                          r"(\d{1,2}):(\d{2})\b", re.I)
HST_TZ = timezone(timedelta(hours=-10))


def picked_up(text):
    """{trip, day, name, emp} of a 'H3607:17NOV picked up by DOE, JANE (10001)' comment (any letter case), or None."""
    m = PICKED_RE.search(text or "")
    if not m:
        return None
    return {"trip": m.group(1).upper(), "day": f"{int(m.group(2)):02d}{m.group(3).upper()}",
            "name": re.sub(r"\s+", " ", m.group(4)).strip().title(), "emp": m.group(5).lstrip("0")}


def _md_hm(m):
    """('MM/DD', 'HH:MM') of a match whose groups are (day, MON, MM, DD, hour, minute), or None for a bad date."""
    d, mon, mm, dd, hh, mi = m.groups()[-6:]
    try:
        mo, day = (MON3.index(mon.upper()) + 1, int(d)) if mon else (int(mm), int(dd))
        if not (1 <= mo <= 12 and 1 <= day <= 31 and int(hh) < 24 and int(mi) < 60):
            return None
    except (TypeError, ValueError):
        return None
    return f"{mo:02d}/{day:02d}", f"{int(hh):02d}:{mi}"


def status_at(text):
    """('MM/DD', 'HH:MM') of the decision time in 'Denied 30 OCT 15:10' (or 'Denied 10/30 15:10'), or None."""
    m = STATUS_AT_RE.search(text or "")
    return _md_hm(m) if m else None


def requested_at(text):
    """('MM/DD', 'HH:MM') of a request's own time on its view page ('Requested (HA) 30 OCT 15:08', 'Time: 10/30
    15:08'), or None."""
    m = REQUESTED_RE.search(text or "")
    return _md_hm(m) if m else None


def req_time(md, hm, folder_month=None, ref=None):
    """The HST time (ISO, minute precision) of a request filed 'MM/DD' 'HH:MM'. The page prints no year: with the bid
    folder's month ('YYYY-MM') it is the year that puts the request nearest that month (a request of late December
    in January's folder is last year's; one of early January in December's folder is next year's); else the year
    nearest ref (an aware datetime). None when it cannot be read."""
    try:
        mo, dd = (int(x) for x in str(md).split("/"))
        hh, mi = (int(x) for x in str(hm).split(":"))
        if folder_month:
            anchor = datetime(int(folder_month[:4]), int(folder_month[5:7]), 15, tzinfo=HST_TZ)
        else:
            anchor = ref.astimezone(HST_TZ)
        best = None
        for y in (anchor.year - 1, anchor.year, anchor.year + 1):
            try:
                t = datetime(y, mo, dd, hh, mi, tzinfo=HST_TZ)
            except ValueError:
                continue
            if best is None or abs(t - anchor) < abs(best - anchor):
                best = t
        return best.isoformat(timespec="minutes") if best else None
    except (TypeError, ValueError, AttributeError):
        return None


def row_cap(r):
    """1.7.10: what a Denied request row says for the pickup speed cap: {trip, day, emp} from its 'picked up by'
    comment (the list's own text, kept on the row as 'pu', else its view page's reason or detail), or None. The
    picker's name is not kept."""
    if not isinstance(r, dict) or str(r.get("status") or "").title() != "Denied":
        return None
    pu = r.get("pu") if isinstance(r.get("pu"), dict) else None
    if not pu:
        got = picked_up(str(r.get("reason") or "")) or picked_up(str(r.get("detail") or ""))
        pu = {k: got[k] for k in ("trip", "day", "emp")} if got else None
    if not pu or not all(isinstance(pu.get(k), str) and pu.get(k) for k in ("trip", "day", "emp")):
        return None
    return {k: pu[k] for k in ("trip", "day", "emp")}


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
           "sendable": False, "draft": DRAFT, "why": ""}
    if not b:
        rec["why"] = f"{DRAFT}: " + ("close-in folder BCID not read yet" if folder == "close-in" else "pot BCID unknown")
        return rec
    rec["form"] = drop_form(b, trip, start)
    rec["why"] = f"{DRAFT} (DROP review page not mapped yet)"
    return rec
