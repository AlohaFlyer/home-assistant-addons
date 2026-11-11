"""Bid calendar alerts (1.7.1, FW-0070, Ryan): the PBS bid cycle's dates and the pushes around them.

Ryan's ticket: a critical alert the day before the pairing package publishes, at 08:00 HST ("adjust your vacation if
needed"; Ryan, Nov 11: the morning of the 3rd, not 20:00), one at 20:00 HST the night before each practice run, one 24 h before bids close and one at 20:00 HST the night before
they close. The package for bid month M+1 (uploads/<M+1>_pairings.txt, the text copy the uploads make) prints its Bid
Calendar on page 1, with dates in month M: "Pairing Package Published" (the 4th), "Practice Run #1" and "#2", "CA & FO
Bids Close" (the 11th, 0800HST on a following line), "All Monthly Awards Posted ... no later than 1700HST on <date>"
and "Flica Open Time Window Opens ... 1200HST on <date>". Everything is HST (Pacific/Honolulu, no DST). The page is
two columns (pdftotext -layout): the calendar is the left one, the reserve and credit tables the right one, so a date
line can carry table text after it.

No FLICA, no file or network access, no imports from the app: watcher.py reads the package and sends the alerts.
"""
import re
from datetime import date, datetime, timedelta, timezone

HST = timezone(timedelta(hours=-10))
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December")
DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

# Ryan asked for the alert on the 4th for a package he expected on the 5th. The packages publish on the 4th (Sep 4,
# Oct 4, Nov 4 on their own Bid Calendars), so the same lead time is the day before. Ryan's answer (Nov 11): 08:00 HST
# the day before the publish date, the 3rd by default (20:00 before). One constant, (days before the publish date,
# HH:MM HST). Its kind keeps the name publish_eve (the keys in the DB and the payloads), though it is a morning alert.
PUBLISH_ALERT = (1, "08:00")
EVE_AT = "20:00"  # the night before a practice run and before the close (FW-0070)
CLOSE_LEAD_H = 24  # and this many hours before the close
# A cycle whose package is not on file (it cannot be before it publishes) uses the usual days of month M.
DEFAULT_PUBLISHED = 4
DEFAULT_PRACTICE = (7, 10)
DEFAULT_CLOSE = (11, "08:00")
KINDS = ("publish_eve", "practice_eve_1", "practice_eve_2", "close_24h", "close_eve")
HEAD_BYTES = 64 * 1024  # page 1 of a package is about 10 KB; the reader never needs the 1.3 MB that follows
LEFT_COL = 48  # a text run that starts at or after this column is the right column (the tables start near 65)

_MON = r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|" \
       r"Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
DATE_RE = re.compile(_MON + r"\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?", re.I)
TIME_RE = re.compile(r"([01]\d|2[0-3]):?([0-5]\d)\s?HST(?:\s+on)?", re.I)
HEAD_RE = re.compile(r"\b" + _MON + r"\s+(\d{4})\s+Pairing\s+Package\b", re.I)
RUN_RE = re.compile(r"Practice\s+Run\s*#?\s*([12])\b", re.I)


def _month_no(name):
    n = name[:3].lower()
    return next(i for i, m in enumerate(MONTHS, 1) if m[:3].lower() == n)


def _left(line):
    """The left column of one page line: its runs of text (split where 2 or more spaces are), kept when they start
    before LEFT_COL."""
    return [m.group(0) for m in re.finditer(r"\S+(?: \S+)*", line.expandtabs(8)) if m.start() < LEFT_COL]


def _rows(text):
    """Page 1 (up to the first form feed) as the left column's non-empty rows, each a list of runs."""
    page = (text or "")[:HEAD_BYTES].split("\f", 1)[0]
    return [r for r in (_left(ln) for ln in page.splitlines()[:200]) if r]


def _ymd(m, bid):
    """'YYYY-MM-DD' of a DATE_RE match in the package of bid month bid (year, month): its dates fall before the bid
    month, so a month after it is the year before (December in the January package). None when no such day."""
    mo, by, bm = _month_no(m.group(1)), bid[0], bid[1]
    try:
        return date(by - 1 if mo > bm else by, mo, int(m.group(2))).isoformat()
    except ValueError:
        return None


def _date_of(run, bid):
    m = DATE_RE.fullmatch(run.strip())
    return _ymd(m, bid) if m else None


def _time_of(run):
    m = TIME_RE.fullmatch(run.strip())
    return f"{m.group(1)}:{m.group(2)}" if m else None


def _timed(rows, k, bid, date_row):
    """{date, time} of the label at rows[k] whose date starts rows[date_row]. A date under its label (awards, open
    time): the time is the first "1700HST on" / "1200HST on" that starts a row from the label's row to the date's. A
    date on the label's row (the close): the "0800HST" that starts one of the two rows after it, before the next date.
    time is None when there is none; None without a date."""
    d = _date_of(rows[date_row][0], bid) if date_row is not None else None
    if not d:
        return None
    after = date_row <= k
    span = range(k + 1, min(len(rows), k + 3)) if after else range(k, date_row)
    t = None
    for j in span:
        if after and _date_of(rows[j][0], bid):
            break  # the calendar's next entry
        t = _time_of(rows[j][0])
        if t:
            break
    return {"date": d, "time": t}


def _row_date(rows, k, bid):
    """The row that carries the date of the label at rows[k]: the label's own row (the date first, the label after
    it), else a row of just a date right after or before it (a layout that breaks the line)."""
    if _date_of(rows[k][0], bid):
        return k
    for j in (k + 1, k - 1):
        if 0 <= j < len(rows) and len(rows[j]) == 1 and _date_of(rows[j][0], bid):
            return j
    return None


def _date_under(rows, k, bid, n=3):
    """The row of the date of a label printed above it (awards, open time): the label's own row when it starts with a
    date, else the first of the n rows after it that does."""
    for j in range(k, min(len(rows), k + 1 + n)):
        if _date_of(rows[j][0], bid):
            return j
    return None


def parse(text, bid_month=None):
    """The Bid Calendar of a pairing package's text: {bid_month, published, practice: [d1, d2], close, awards_by,
    open_time_opens}. Dates are 'YYYY-MM-DD' (HST); close, awards_by and open_time_opens are {date, time 'HH:MM' or
    None}. Anything not found is None. bid_month ('YYYY-MM') comes from the page's "<Month> <YYYY> Pairing Package"
    heading, else from the argument (the upload's name); with neither no date can get its year and all are None."""
    out = {"bid_month": None, "published": None, "practice": [None, None], "close": None, "awards_by": None,
           "open_time_opens": None}
    page = (text or "")[:HEAD_BYTES].split("\f", 1)[0]
    h = HEAD_RE.search(page)
    if h:
        out["bid_month"] = f"{int(h.group(2)):04d}-{_month_no(h.group(1)):02d}"
    elif isinstance(bid_month, str) and re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", bid_month):
        out["bid_month"] = bid_month
    if not out["bid_month"]:
        return out
    bid = (int(out["bid_month"][:4]), int(out["bid_month"][5:]))
    rows = _rows(page)
    for k, row in enumerate(rows):
        label = " ".join(row)
        if out["published"] is None and re.search(r"Pairing\s+Package\s+Published", label, re.I):
            r = _row_date(rows, k, bid)
            out["published"] = _date_of(rows[r][0], bid) if r is not None else None
        run = RUN_RE.search(label)
        if run and out["practice"][int(run.group(1)) - 1] is None:
            r = _row_date(rows, k, bid)
            out["practice"][int(run.group(1)) - 1] = _date_of(rows[r][0], bid) if r is not None else None
        if out["close"] is None and re.search(r"Bids\s+Close", label, re.I):
            out["close"] = _timed(rows, k, bid, _row_date(rows, k, bid))
        if out["awards_by"] is None and re.search(r"Awards\s+Posted", label, re.I):
            out["awards_by"] = _timed(rows, k, bid, _date_under(rows, k, bid))
        if out["open_time_opens"] is None and re.search(r"Open\s+Time\s+Window\s+Opens", label, re.I):
            out["open_time_opens"] = _timed(rows, k, bid, _date_under(rows, k, bid))
    return out


# ---------------------------------------------------------------- the alerts of one bid cycle
def _prev_month(bid_month):
    y, m = int(bid_month[:4]), int(bid_month[5:7])
    return (y, m - 1) if m > 1 else (y - 1, 12)


def bid_month_after(ym, n=1):
    y, m = int(ym[:4]), int(ym[5:7]) + n
    y, m = y + (m - 1) // 12, (m - 1) % 12 + 1
    return f"{y:04d}-{m:02d}"


def cycles(now):
    """The bid months whose alerts can come up now (an aware datetime): next month's cycle (its alerts are in this
    month) and the one after (its first alert is early next month, the sensor's next alert once this one closed)."""
    ym = now.astimezone(HST).strftime("%Y-%m")
    return [bid_month_after(ym, 1), bid_month_after(ym, 2)]


def _at(day, hm):
    d = date.fromisoformat(day) if isinstance(day, str) else day
    return datetime(d.year, d.month, d.day, int(hm[:2]), int(hm[3:5]), tzinfo=HST)


def _in_window(day, bid_month):
    """A package date this cycle can use: in the 62 days before its bid month starts (a misread year or day never
    moves an alert months away)."""
    try:
        d = date.fromisoformat(day)
    except (TypeError, ValueError):
        return False
    start = date(int(bid_month[:4]), int(bid_month[5:7]), 1)
    return start - timedelta(days=62) <= d < start


def cycle_dates(bid_month, parsed=None):
    """The dates of the bid cycle for bid_month ('YYYY-MM'): from parsed (bidcal.parse of that month's package) when it
    is this bid month's, else the usual days of the month before. source is package or default, each date's own
    source in sources (a date the package lacks keeps its default)."""
    y, m = _prev_month(bid_month)
    d = lambda day: date(y, m, day).isoformat()  # noqa: E731
    out = {"bid_month": bid_month, "published": d(DEFAULT_PUBLISHED), "practice": [d(x) for x in DEFAULT_PRACTICE],
           "close": {"date": d(DEFAULT_CLOSE[0]), "time": DEFAULT_CLOSE[1]}, "awards_by": None,
           "open_time_opens": None, "source": "default",
           "sources": {"published": "default", "practice_1": "default", "practice_2": "default", "close": "default"}}
    p = parsed if isinstance(parsed, dict) and parsed.get("bid_month") == bid_month else None
    if not p:
        return out
    out["source"] = "package"
    if _in_window(p.get("published"), bid_month):
        out["published"], out["sources"]["published"] = p["published"], "package"
    for i, day in enumerate((p.get("practice") or [None, None])[:2]):
        if _in_window(day, bid_month):
            out["practice"][i], out["sources"][f"practice_{i + 1}"] = day, "package"
    c = p.get("close")
    if isinstance(c, dict) and _in_window(c.get("date"), bid_month):
        out["close"] = {"date": c["date"], "time": c.get("time") or DEFAULT_CLOSE[1]}
        out["sources"]["close"] = "package"
    for k in ("awards_by", "open_time_opens"):
        v = p.get(k)
        if isinstance(v, dict) and v.get("date"):
            out[k] = {"date": v["date"], "time": v.get("time")}
    return out


def day_text(d):
    """'Wed Nov 11' (no locale)."""
    d = date.fromisoformat(d) if isinstance(d, str) else d
    return f"{DAYS[d.weekday()]} {MONTHS[d.month - 1][:3]} {d.day}"


def _rel(at, day):
    """'today', 'tomorrow' or 'in N days': day (a date) seen from at (an aware datetime), in HST."""
    n = (day - at.astimezone(HST).date()).days
    return "today" if n <= 0 else "tomorrow" if n == 1 else f"in {n} days"


def render(alert, at):
    """(title, message) of an alert seen from at: the words say when its event is from the time the push goes out,
    so one sent late (a restart) is still true. Plain words for a pilot, the date and time in HST."""
    ev = datetime.fromisoformat(alert["event"])
    month = MONTHS[int(alert["bid_month"][5:7]) - 1]
    usual = "" if alert["source"] == "package" else " Usual date: the pairing package is not uploaded yet."
    kind = alert["kind"]
    if kind == "publish_eve":
        rel = _rel(at, ev.date())
        return (f"{month} pairing package {rel}",
                f"The {month} pairing package publishes {rel}, {day_text(ev.date())}. Adjust your vacation if needed.")
    if kind.startswith("practice_eve_"):
        n, rel = kind[-1], _rel(at, ev.date())
        tonight = "tonight" if rel == "tomorrow" else "now"
        return (f"PBS Practice Run #{n} {rel}",
                f"Practice Run #{n} for {month} is {rel}, {day_text(ev.date())}. Have your PBS bid in by {tonight}."
                + usual)
    hm = ev.strftime("%H:%M")
    if kind == "close_24h":
        h = max(1, round((ev - at).total_seconds() / 3600))  # a late push says the hours really left
        return (f"Bids close in {h} h",
                f"{month} bids close in {h} h: {day_text(ev.date())} {hm} HST. FLICA closes during award processing."
                + usual)
    rel = _rel(at, ev.date())
    return (f"Bids close {rel} {hm} HST",
            f"{month} bids close {rel} at {hm} HST ({day_text(ev.date())}). Finish your PBS bid "
            f"{'tonight' if rel == 'tomorrow' else 'now'}. FLICA closes during award processing." + usual)


def _alert(c, kind, src, fire_at, event, deadline):
    a = {"key": f"{c['bid_month']}_{kind}", "kind": kind, "bid_month": c["bid_month"], "fire_at": fire_at.isoformat(),
         "event": event.isoformat(), "deadline": deadline.isoformat(), "source": src}
    a["title"], a["message"] = render(a, fire_at)
    return a


def schedule(bid_month, parsed=None):
    """The alerts of the bid cycle for bid_month, in fire order: each {key, kind, bid_month, fire_at, event, deadline,
    source, title, message}, times as ISO text with the HST offset. title and message are as sent on time (render()
    words them again for a late one). An alert is sent from fire_at until its deadline, then dropped: the publish
    alert (08:00 the day before) and the evening alerts until their day starts (they say "tomorrow" and "tonight"),
    close_24h until close_eve takes over (or the close), close_eve until the close."""
    c = cycle_dates(bid_month, parsed)
    s = c["sources"]
    out = []
    pub = date.fromisoformat(c["published"])
    days, hm = PUBLISH_ALERT
    fire, day = _at(pub - timedelta(days=days), hm), _at(pub, "00:00")
    # a PUBLISH_ALERT on the day itself (0 days before) reads "today" and is kept until that day ends
    out.append(_alert(c, "publish_eve", s["published"], fire, day, day if fire < day else day + timedelta(days=1)))
    for i, day in enumerate(c["practice"], 1):
        d = date.fromisoformat(day)
        out.append(_alert(c, f"practice_eve_{i}", s[f"practice_{i}"], _at(d - timedelta(days=1), EVE_AT),
                          _at(d, "00:00"), _at(d, "00:00")))
    close = _at(c["close"]["date"], c["close"]["time"])
    eve = _at(close.date() - timedelta(days=1), EVE_AT)
    f24 = close - timedelta(hours=CLOSE_LEAD_H)
    out.append(_alert(c, "close_24h", s["close"], f24, close, eve if eve > f24 else close))
    out.append(_alert(c, "close_eve", s["close"], eve, close, close))
    return sorted(out, key=lambda a: a["fire_at"])


def due(alerts, done, now):
    """(send, drop) at now (an aware datetime): the alerts whose fire time has come and whose key done (the keys
    already sent or dropped) does not hold. One whose deadline passed is dropped, never sent: its words would no longer
    be true."""
    send, drop = [], []
    for a in sorted(alerts, key=lambda x: x["fire_at"]):
        if a["key"] in done or now < datetime.fromisoformat(a["fire_at"]):
            continue
        (send if now < datetime.fromisoformat(a["deadline"]) else drop).append(a)
    return send, drop


def next_alert(alerts, done):
    """The first alert not sent or dropped yet, in fire order, or None."""
    return next((a for a in sorted(alerts, key=lambda x: x["fire_at"]) if a["key"] not in done), None)


def hst_text(iso):
    """'Wed Nov 11 08:00 HST' of an ISO time."""
    t = datetime.fromisoformat(iso).astimezone(HST)
    return f"{day_text(t.date())} {t.strftime('%H:%M')} HST"
