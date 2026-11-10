"""Charter watch (0.7.0, Ryan): unusual A330 flying on CrewTrac Web (ctweb.hawaiianair.com), 30 days ahead.

Source (Hark, 2026-11-04, Doc Log): Options > Scheduled Service, one date per query:
  /Pilot/ctw4190report.aspx?DeptDate=YYYYMMDD&DeptCity=HNL&ArrvCity=   (HNL departures)
  /Pilot/ctw4190report.aspx?DeptDate=YYYYMMDD&DeptCity=&ArrvCity=HNL   (HNL arrivals; DeptDate is the
  departure station's local date, so arrivals are read from one day earlier)
Table: Cancelled | Flight # | Org-Dest | Scheduled | Estimated | Actual | Eqpt/REG | Tail # | Orig. Date.
Eqpt/REG 332/3 or 333 = A330. Charters show as 99xx flight numbers (9980/9981 SIN) or A330 rows whose
other end is not a regular A330 station. The field strip above the table is stale; only rows count.
Login: plain form at /Pilot/ctwc.aspx (Username = employee number, CrewTrac password), lands on
/Pilot/ctwcmainmenu.aspx, session under 2 h: one login per scan. Read only, GET only after login.
1.6.1: a login has three outcomes (OK, REFUSED, OUTAGE); the Watcher never tries again after CrewTrac refused the same
user ID and password (creds_hash), and backs off after an outage (backoff_s)."""
import hashlib
import json
import re
from datetime import date, timedelta

from bs4 import BeautifulSoup

BASE = "https://ctweb.hawaiianair.com"
LOGIN = f"{BASE}/Pilot/ctwc.aspx"
MENU = "ctwcmainmenu"
REPORT = f"{BASE}/Pilot/ctw4190report.aspx?DeptDate={{ymd}}&DeptCity={{dep}}&ArrvCity={{arr}}"
DAYS_AHEAD = 30
SCAN_EVERY_S = 6 * 3600
HUB = "HNL"
# Regular A330 stations (editable in the app Configuration tab, option charter_regular).
REGULAR = ("HNL OGG KOA LIH ITO LAX SFO SAN SEA PDX LAS PHX SMF OAK SJC JFK BOS "
           "SYD AKL NRT HND KIX ICN PPG PPT")
ISLANDS = {"HNL", "OGG", "KOA", "LIH", "ITO"}  # 99xx legs between these are positioning, not charters
A330 = ("332", "333")
CHARTER_FLT = 9900

HEADERS = ("cancelled", "flight", "route", "scheduled", "estimated", "actual", "eqpt", "tail", "orig")

# 1.6.1: what one login try came to. REFUSED is CrewTrac's own answer to a wrong user ID or password (or a locked
# account); anything else that is not the menu (no login form, an unexpected page, a network error, a timeout) is OUTAGE.
OK, REFUSED, OUTAGE = "ok", "refused", "outage"
REFUSAL_RE = re.compile(
    r"invalid\s+(?:user\s*(?:id|name)?|username|login|employee\s*(?:id|number|#)?)\s*(?:and|or|/|&)\s*password"
    r"|(?:invalid|incorrect|wrong)\s+password|password\s+(?:is\s+|was\s+)?(?:invalid|incorrect|wrong|not\s+valid)"
    r"|(?:user\s*(?:id|name)?|username|login)\s*(?:and|or|/|&)\s*password\s+(?:is\s+|are\s+)?"
    r"(?:invalid|incorrect|wrong|not\s+valid)"
    r"|account\s+(?:is\s+|has\s+been\s+)?(?:locked|disabled)", re.I)
BACKOFF_FIRST_S = 30 * 60  # after the first outage in a row; doubling each further one
BACKOFF_MAX_S = 6 * 3600
PRESS_GAP_S = 30 * 60  # Scan CrewTrac now: at most one scan per 30 min (the first one after new details excepted)


def refused(text):
    """True when a page's text carries CrewTrac's credential refusal ("Invalid User ID or Password")."""
    return bool(REFUSAL_RE.search(text or ""))


def creds_hash(user, password):
    """sha256 of the CrewTrac user name and password in use: the refusal block's key. Never the values themselves."""
    return hashlib.sha256(json.dumps(["crewtrac", user or "", password or ""]).encode()).hexdigest()


def backoff_s(outages):
    """The wait after the n-th outage in a row: 30 min, 60, 120, 240, then 6 h at most."""
    return min(BACKOFF_MAX_S, BACKOFF_FIRST_S * 2 ** min(max(0, int(outages) - 1), 16))


def regular_set(text=None):
    """The built-in regular stations plus any extra ones from the charter_regular option (0.7.5: the
    option adds to the list, it never shrinks it, so an old saved option cannot re-flag PPT)."""
    return {s.strip().upper() for s in (REGULAR + " " + (text or "")).replace(",", " ").split() if s.strip()}


def prune(known, regular):
    """Drop entries the current rules would not flag (e.g. a station added to the regular list)."""
    return {k: v for k, v in known.items() if flag(v, regular)}


def scan_dates(today, ahead=DAYS_AHEAD):
    """Departure dates to query: from the day before the 1st of this month (Ryan: show the month's past
    charters too, e.g. the SIN run; arrivals from Asia land a day after they leave) to today + ahead."""
    first = today.replace(day=1) - timedelta(days=1)
    n = (today - first).days
    return [(first + timedelta(days=i)).isoformat() for i in range(0, n + ahead + 1)]


def report_url(iso, dep="", arr=""):
    return REPORT.format(ymd=iso.replace("-", ""), dep=dep, arr=arr)


def logged_in(html):
    """The CrewTrac main menu or any report page: both carry a Sign Out link and no password input; the
    login page has the input. (0.7.2: the menu says Change Password, so the word alone is no test.)"""
    t = (html or "").lower()
    return "sign out" in t and 'type="password"' not in t and "type='password'" not in t


def login_form(html):
    """(action, fields) of the CrewTrac login form: every hidden/text input plus the username and
    password inputs named by their id/name containing 'user' / 'pass'. Values are not logged."""
    soup = BeautifulSoup(html or "", "html.parser")
    form = None
    for f in soup.find_all("form"):
        if f.find("input", attrs={"type": "password"}):
            form = f
            break
    if form is None:
        return None, {}
    fields, texts, pass_key = {}, [], None
    for inp in form.find_all("input"):
        name = inp.get("name")
        if not name:
            continue
        typ = (inp.get("type") or "text").lower()
        if typ == "password":
            pass_key = name
        elif typ in ("text", "email"):
            texts.append(name)
        if typ in ("hidden", "text", "email", "password", "submit"):
            fields[name] = inp.get("value") or ""
    user_key = next((n for n in texts if "user" in n.lower() or "login" in n.lower()), texts[0] if texts else None)
    return form.get("action") or "", {"fields": fields, "user": user_key, "pass": pass_key}


ROUTE_RE = re.compile(r"[A-Z]{3}-[A-Z]{3}")
FLT_RE = re.compile(r"\d{1,4}[A-Z]?")


def parse_rows(html):
    """[{cancelled, flight, route, scheduled, estimated, actual, eqpt, tail, orig}] from the Scheduled
    Service page. 0.7.4: the header sits in its own table and the rows in TABLE id REPORTINFO, so rows
    are matched by shape (flight number in column 2, XXX-YYY route in column 3). Empty when none."""
    soup = BeautifulSoup(html or "", "html.parser")
    out = []
    body = soup.find("table", id=re.compile("REPORTINFO", re.I)) or soup
    for tr in body.find_all("tr"):
        cells = [c.get_text(" ", strip=True).replace("\xa0", " ").strip() for c in tr.find_all("td", recursive=False)]
        if len(cells) < 7 or not FLT_RE.fullmatch(cells[1] or "") or not ROUTE_RE.fullmatch(cells[2] or ""):
            continue
        cells += [""] * (len(HEADERS) - len(cells))
        out.append(dict(zip(HEADERS, [re.sub(r"\s+", " ", c) for c in cells[:len(HEADERS)]])))
    return out


def is_a330(eqpt):
    return (eqpt or "").strip()[:3] in A330


def sched_date(scheduled):
    """ISO departure date from 'MM/DD/YY HH:MM-HH:MM'."""
    m = re.match(r"(\d{2})/(\d{2})/(\d{2})", scheduled or "")
    return f"20{m.group(3)}-{m.group(1)}-{m.group(2)}" if m else ""


def flag(row, regular):
    """Why this A330 row is unusual: '99xx charter', 'XXX not a regular A330 station', or '' (regular)."""
    if not is_a330(row.get("eqpt")):
        return ""
    try:
        n = int(re.sub(r"\D", "", row.get("flight") or "0") or 0)
    except ValueError:
        n = 0
    org, _, dest = (row.get("route") or "").partition("-")
    org, dest = org.strip().upper(), dest.strip().upper()
    if org == dest or (row.get("cancelled") or "").strip().lower().startswith("y"):
        return ""  # 0.7.4: same-station legs (9940 HNL-HNL) are test or maintenance flights; cancelled rows are not news
    if n >= CHARTER_FLT and not (org in ISLANDS and dest in ISLANDS):
        return "99xx charter"
    for st in (org, dest):
        if st and st not in regular:
            return f"{st} not a regular A330 station"
    return ""


def key(row):
    return f"{row.get('flight')}|{row.get('route')}|{sched_date(row.get('scheduled'))}"


def unusual(rows, regular):
    """The flagged rows, each with 'why', 'date' and 'key', in schedule order, each key once."""
    out, seen = [], set()
    for r in rows:
        why = flag(r, regular)
        k = key(r)
        if not why or k in seen:
            continue
        seen.add(k)
        out.append({**r, "why": why, "date": sched_date(r.get("scheduled")), "key": k})
    out.sort(key=lambda r: (r["date"], r.get("scheduled") or ""))
    return out


def merge(known, found, today_iso):
    """known {key: rec} updated with found rows: new keys get first_seen=today, kept keys keep theirs,
    keys no longer found but dated in the future are kept and marked 'gone' (cancelled or moved),
    keys before the 1st of last month are dropped. Returns (known, new_keys)."""
    new = []
    t = date.fromisoformat(today_iso)
    cutoff = (t.replace(day=1) - timedelta(days=1)).replace(day=1).isoformat()
    fk = {r["key"]: r for r in found}
    for k, r in fk.items():
        if k not in known:
            known[k] = {**r, "first_seen": today_iso, "gone": False}
            new.append(k)
        else:
            known[k].update({**r, "gone": False})
    for k in list(known):
        if known[k].get("date", "") < cutoff:
            del known[k]
        elif k not in fk:
            known[k]["gone"] = True
    return known, new


class Scanner:
    """Read-only CrewTrac client over a requests.Session. Caller supplies the session, the credentials
    and a sleep hook; nothing here is ever written to CrewTrac."""

    def __init__(self, session, username, password, log, sleep=lambda: None, capture=None):
        self.s, self.u, self.p, self.log, self.sleep = session, username, password, log, sleep
        self.capture = capture or (lambda name, html: None)  # 0.7.3: private page captures for debugging
        self._reported = False

    def login(self):
        """One login try: OK, REFUSED (CrewTrac refused the user ID or password) or OUTAGE (no login form, an
        unexpected page, a network error or a timeout). 1.6.1: the log lines keep their 1.6.0 shape; no value typed
        in the form is ever logged."""
        try:
            r = self.s.get(LOGIN, timeout=30)
        except Exception as e:  # noqa: BLE001 (network error, timeout: an outage)
            self.log.info("charter: login page not reached (%s)", type(e).__name__)
            return OUTAGE
        self.capture("login", r.text)
        if logged_in(r.text):
            return OK
        action, f = login_form(r.text)
        self.log.info("charter: login page %s (%d chars), form action %r, fields %s, user field %r, pass field %r",
                      r.url.split("?")[0], len(r.text), action, sorted(f.get("fields", {}).keys()) if f else [],
                      (f or {}).get("user"), (f or {}).get("pass"))
        if not f or not f.get("user") or not f.get("pass"):
            self.log.info("charter: login form not found on %s (%d chars, fields %s)", LOGIN, len(r.text),
                          sorted((f or {}).get("fields", {}).keys()))
            return OUTAGE
        data = dict(f["fields"])
        data[f["user"]] = self.u
        data[f["pass"]] = self.p
        url = action if action.startswith("http") else (LOGIN if not action or action.startswith("?") else
                                                        f"{BASE}/Pilot/{action.lstrip('./')}")
        try:
            r = self.s.post(url, data=data, timeout=30, allow_redirects=True)
        except Exception as e:  # noqa: BLE001
            self.log.info("charter: login response not received (%s)", type(e).__name__)
            return OUTAGE
        self.capture("login_response", r.text)
        ok = logged_in(r.text) or MENU in r.url
        self.log.info("charter: login response %s (%d chars, logged in: %s)", r.url.split("?")[0], len(r.text), ok)
        if ok:
            return OK
        text = re.sub(r"\s+", " ", BeautifulSoup(r.text, "html.parser").get_text(" "))
        if refused(text):
            self.log.info("charter: login refused (%s, %d chars): %s", r.url.split("?")[0], len(r.text), text[:200])
            return REFUSED
        self.log.info("charter: login not confirmed, unexpected page (%s, %d chars): %s", r.url.split("?")[0],
                      len(r.text), text[:200])
        return OUTAGE

    def rows(self, iso, dep="", arr=""):
        r = self.s.get(report_url(iso, dep, arr), timeout=30)
        if not self._reported:
            self._reported = True
            self.capture("report", r.text)
            self.log.info("charter: first report %s (%d chars, logged in: %s): %s", r.url.split("?")[0], len(r.text),
                          logged_in(r.text), re.sub(r"\s+", " ", BeautifulSoup(r.text, "html.parser").get_text(" "))[:300])
        if not logged_in(r.text) or "notloggedin" in r.url.lower():
            return None
        return parse_rows(r.text)

    def scan(self, today, ahead=DAYS_AHEAD):
        """All rows for HNL departures and arrivals over the window, or None when the session died."""
        allrows = []
        for i, iso in enumerate(scan_dates(today, ahead)):
            for dep, arr in ((HUB, ""), ("", HUB)):
                if allrows or i:
                    self.sleep()
                got = self.rows(iso, dep, arr)
                if got is None:
                    return None
                allrows.extend(got)
        return allrows
