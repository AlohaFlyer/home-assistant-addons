"""FW-0042 (1.4.13, Hark's rules of Nov 1, Ryan's go-ahead Nov 8): the smart push fields of a pickup row.

- comm(): can the pilot commute non-rev to the report and home after the release? Per airport in the config:
  IN = at least two scheduled nonstops (any airline) from that airport, the same day as the report, scheduled to
  ARRIVE HNL before the report time (PWA 26.QQ.2, the two-flight rule; arrival = departure + the longest block time
  of that route); HOME = at least one scheduled nonstop HNL to that airport departing home_gap_min (60) or more
  after the release, the same day. An overnight release (after midnight and before home_day_start, 05:00, or one
  whose 60 min runs past midnight) has no same-day home, the mirror of the IN rule's overnight report. A customs
  release (PWA 2.19.b: 30 min after block-in, not 15) follows far.py's sure / worst rule: a last leg known to come
  from outside the US judges HOME from the customs release; a last leg whose origin is not on file judges it at both
  releases, and an airport that makes HOME only without customs is unknown (never a No). An airport counts only with
  both. The airports that count, in the config's order, joined with '/' ('AAA/BBB', 'AAA', 'BBB'), 'No' when every
  airport surely fails, '' when none counts but one is unknown (the why says so); ('', '') with no config, no airport
  with both tables, or no report / release time.
- month_type() / month_rule(): the bid month's type from the config, 'line' or 'reserve', and the row against it,
  per bid month the trip touches (a trip across a bid period's end is judged in both, each by its own type). A bid
  month is the bid period, not the calendar month (November 2026 runs Nov 1 to Dec 1, December Dec 2 to 31): each
  day goes to its bid month by the pairing files' period bounds when the caller has them (period=), else by the
  schedule pages on file (bid_month()), else the calendar month. line (bid line): adds only on days off (the fit
  tag's Conflict and the schedule's own days), 11 h minimum rest (PWA 10.E.1.a, the FAR column's CBA rest note), at
  least min_days_off days off after the add over that bid period (FLICA's own Days Off total, which counts VAC days
  as off, less the days off the add uses). reserve: pickups over SCR days only. VAC days are never pickup days
  (either type, or a month with no type). Not checked here: reserve's 48 h in the pot, R-14 and no-GDO conditions.
  No monthly credit cap (1.7.1, Ryan via Hark, Nov 9: the 90 h cap was Hark's error; the PWA does not cap voluntary
  adds): a cap_credit in smart.json is read and ignored (logged once per file change), never 'Over cap' or 'Cap ?'.
- block_672() (1.7.1, Ryan's rule of Nov 9): the pilot's block hours in the 672 h ending at the pickup's release
  (flown + scheduled + the pickup, far.flight_time_to_release: the FAR column's flight time in 672 h machinery)
  against the company's 98 h buffer in that rolling window (BUFFER_672_H; FAR's own limit is 100 h, far.FT_672):
  'Fits 672 (97:59)', 'Over 98/672 (98:01)' or '672 ? (block not read)', in month_rule's parts where 'Over cap' was
  and as the row's own b672 / b672_ok fields. Block (flight) time, never credit. A find over 98/672 is shown and
  tagged, never hidden.
- value(): the trip's credit times the hourly rate, whole dollars.

Nothing personal ships with the code: the airports, the nonstop tables, the month types, VAC dates, the rate and the
break-even live only in smart.json on the pilot's share (/share/flight_watcher/smart.json, a second pilot's under
/share/flight_watcher/<name>/). Without the file every field is '' and nothing changes. Pure functions plus load(),
which caches by the file's contents and never raises. Times are naive HST datetimes (HNL based, no DST)."""
import json
import re
from datetime import date, datetime, timedelta, timezone

import far as FAR

FORMAT = 1  # smart.json "v"
LINE, RESERVE = "line", "reserve"
TYPES = (LINE, RESERVE)
HOME_GAP_MIN = 60  # Hark's rule: a home nonstop 60+ min after release (smart.json home_gap_min overrides)
# A release from midnight to this time is an overnight release: no same-day home (the mirror of the IN rule's
# overnight report; smart.json home_day_start overrides, Hark's call whether a 04:00 to 05:00 release counts)
HOME_DAY_START = 5 * 60
CUSTOMS_MIN = 15  # PWA 2.19.b: a release 30 min after block-in, not 15, when clearing customs (far.CUSTOMS)
RESERVE_CODES = ("SCR",)  # day codes a reserve pickup may cover (smart.json reserve_codes overrides)
OFF_CODES = ("OFF", "GDO")  # day codes that are days off on a line (smart.json off_codes overrides)
IN_NEEDED = 2  # PWA 26.QQ.2: two scheduled flights
WHY_MAX = 240
RULE_MAX = 80  # 1.7.1: room for 'Over 98/672 (101:30)' with the parts 'Over cap' used to sit among
# 1.7.1 (FW-0042, Ryan, Nov 9): the company holds a pilot to 98 h of block in any 672 consecutive hours, a buffer under
# FAR 117's 100 h of flight time in 672 h (far.FT_672, which the FAR column checks); one constant, apart from FAR's
BUFFER_672_H = 98
FITS_672 = "Fits 672"
OVER_672 = f"Over {BUFFER_672_H}/672"
UNK_672 = "672 ?"
# smart.json keys that no longer mean anything: read and ignored, logged once per file change (load())
IGNORED = {"cap_credit": "no monthly credit cap (Ryan, Nov 9: the PWA does not cap voluntary adds); the 672 h block "
                         "check (Fits 672 / Over 98/672) replaces it"}
AP_RE = re.compile(r"^[A-Z]{3}$")
# a pairing id (pot.PAIRING_RE): a schedule page lists a day outside its bid period only for a pairing carried across
# the period's edge, so a day it lists with no pairing on it is a day of that page's own bid period
PAIRING_RE = re.compile(r"^[A-Z]\d{4}[A-Z]?$")
HM_RE = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*$")
MONTH_RE = re.compile(r"^\d{4}-\d{2}$")
MAX_BYTES = 256 * 1024  # smart.json is a few KB; a bigger file is not read
_CACHE = {}  # path -> (the file's bytes, cfg)
HST = timezone(timedelta(hours=-10))  # Hawaii keeps no DST


# ---------------------------------------------------------------- small parsers
def _mins(s):
    """'06:05' -> 365; None when it is not H:MM / HH:MM within a day."""
    m = HM_RE.match(str(s or ""))
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    return h * 60 + mi if h < 24 and mi < 60 else None


def _hm(m):
    return f"{m // 60:02d}:{m % 60:02d}"


def hours(s):
    """'84:30' or '84.30' -> 84.5; a number as it is; None when unreadable (the FLICA forms, as pot.hours)."""
    if isinstance(s, bool):
        return None
    if isinstance(s, (int, float)):
        return float(s)
    m = re.match(r"^\s*(\d{1,3})[:.]?(\d{2})\s*$", str(s or ""))
    if m:
        return int(m.group(1)) + int(m.group(2)) / 60
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _dt(x):
    """A naive HST datetime from a datetime or an ISO text ('2030-01-02T08:00'); None otherwise."""
    if isinstance(x, datetime):
        return x.replace(tzinfo=None) if x.tzinfo is None else x.astimezone(HST).replace(tzinfo=None)
    try:
        d = datetime.fromisoformat(str(x))
    except (TypeError, ValueError):
        return None
    return d if d.tzinfo is None else d.astimezone(HST).replace(tzinfo=None)


def _date(x):
    if isinstance(x, datetime):
        return x.date()
    if isinstance(x, date):
        return x
    try:
        return date.fromisoformat(str(x)[:10])
    except (TypeError, ValueError):
        return None


def _span(a, b):
    out, d = [], a
    while d <= b:
        out.append(d)
        d += timedelta(days=1)
    return out


# ---------------------------------------------------------------- the config file
def normalize(raw):
    """The config as the functions read it, from smart.json's parsed JSON; entries that do not parse are left out
    (never an error). {} when raw is not a dict or names another format version."""
    if not isinstance(raw, dict) or raw.get("v") != FORMAT:
        return {}
    cfg = {"v": FORMAT}
    aps = [str(a).strip().upper() for a in (raw.get("airports") or []) if isinstance(a, str)]
    cfg["airports"] = [a for i, a in enumerate(aps) if AP_RE.match(a) and a not in aps[:i]]
    cfg["in"], cfg["home"] = {}, {}
    rin = raw.get("in") if isinstance(raw.get("in"), dict) else {}
    rhome = raw.get("home") if isinstance(raw.get("home"), dict) else {}
    for ap in cfg["airports"]:
        e = rin.get(ap)
        if isinstance(e, dict):
            deps = sorted(m for m in (_mins(x) for x in (e.get("dep") or []) if isinstance(x, str)) if m is not None)
            try:
                blk = int(e.get("block_max"))
            except (TypeError, ValueError):
                blk = None
            if deps and blk is not None and 0 < blk < 600:
                cfg["in"][ap] = {"dep": deps, "block_max": blk}
        h = rhome.get(ap)
        if isinstance(h, list):
            deps = sorted(m for m in (_mins(x) for x in h if isinstance(x, str)) if m is not None)
            if deps:
                cfg["home"][ap] = deps
    try:
        gap = int(raw.get("home_gap_min", HOME_GAP_MIN))
    except (TypeError, ValueError):
        gap = HOME_GAP_MIN
    cfg["home_gap_min"] = gap if 0 <= gap <= 600 else HOME_GAP_MIN
    hds = _mins(raw.get("home_day_start")) if isinstance(raw.get("home_day_start"), str) else None
    cfg["home_day_start"] = HOME_DAY_START if hds is None else hds
    # stations a last leg can come from without clearing customs, on top of the Watcher's US list (PWA 2.19.b)
    dom = [str(a).strip().upper() for a in (raw.get("domestic") or []) if isinstance(a, str)] \
        if isinstance(raw.get("domestic"), list) else []
    cfg["domestic"] = tuple(a for i, a in enumerate(dom) if AP_RE.match(a) and a not in dom[:i])
    mt = raw.get("month_types") if isinstance(raw.get("month_types"), dict) else {}
    cfg["month_types"] = {k: str(v).strip().lower() for k, v in mt.items()
                          if isinstance(k, str) and MONTH_RE.match(k) and str(v).strip().lower() in TYPES}
    vac = []
    for r in raw.get("vac") or []:
        if isinstance(r, (list, tuple)) and len(r) == 2:
            a, b = _date(r[0]), _date(r[1])
        elif isinstance(r, str):
            a = b = _date(r)
        else:
            a = b = None
        if a and b and a <= b:
            vac.append((a, b))
    cfg["vac"] = vac
    rate = _num(raw.get("rate"))
    cfg["rate"] = rate if rate and rate > 0 else None
    cfg["breakeven"] = _pos_hours(raw.get("breakeven"))
    # 1.7.1: cap_credit (the 90 h cap, Hark's error) is not read into the config: no rule can use it
    cfg["ignored"] = tuple(k for k in IGNORED if k in raw)
    try:
        mdo = int(raw.get("min_days_off")) if raw.get("min_days_off") not in (None, "") else None
    except (TypeError, ValueError):
        mdo = None
    cfg["min_days_off"] = mdo if mdo is not None and 0 <= mdo <= 31 else None
    for k, dflt in (("reserve_codes", RESERVE_CODES), ("off_codes", OFF_CODES)):
        v = raw.get(k)
        cfg[k] = tuple(str(x).strip().upper() for x in v if str(x).strip()) if isinstance(v, list) else dflt
    for k in ("updated", "source"):
        cfg[k] = str(raw.get(k) or "")[:80]
    return cfg


def _num(s):
    """12.5, '12.5' or '$12.50' -> a float; None otherwise (a bool too)."""
    if isinstance(s, bool) or s is None:
        return None
    try:
        return float(str(s).replace(",", "").replace("$", ""))
    except (TypeError, ValueError):
        return None


def _pos_hours(s):
    h = hours(s)
    return h if h is not None and h > 0 else None


def load(path, warn=None):
    """smart.json at path, normalized; {} when the file is missing, unreadable, not JSON or another format. Cached
    by the file's contents: the few KB are read every call (once per pass) and parsed again only when they change, so
    a same-size rewrite inside one file time tick (a coarse kernel clock) is never missed. warn(text) is called once
    per change that does not load (never with the file's contents), and once per change for each key it reads and
    ignores (IGNORED: cap_credit, 1.7.1). Never raises."""
    try:
        with open(path, "rb") as fh:
            data = fh.read(MAX_BYTES + 1)
    except (OSError, TypeError, ValueError):
        _CACHE.pop(path, None)
        return {}
    hit = _CACHE.get(path)
    if hit and hit[0] == data:
        return hit[1]
    cfg, err = {}, ""
    try:
        if len(data) > MAX_BYTES:
            err = "too large"
        else:
            cfg = normalize(json.loads(data.decode("utf-8")))
            if not cfg:
                err = f"not format v{FORMAT}"
    except Exception as e:  # noqa: BLE001: a bad file is a warning, never an error
        cfg, err = {}, type(e).__name__
    _CACHE[path] = (data, cfg)
    if err and warn:
        try:
            warn(f"smart.json not used ({err}); the commute, month and value fields stay blank")
        except Exception:  # noqa: BLE001
            pass
    for k in (cfg or {}).get("ignored") or ():  # once per change of the file, like the warning above
        if warn:
            try:
                warn(f"smart.json {k} ignored: {IGNORED[k]}")
            except Exception:  # noqa: BLE001
                pass
    return cfg


# ---------------------------------------------------------------- commute (PWA 26.QQ.2)
def overnight(rel, cfg):
    """True when a release leaves no same-day home whatever the table: its home_gap_min runs past midnight, or it
    falls after midnight and before home_day_start (the pilot sits in HNL overnight, like a 22:00 release; the
    mirror of the IN rule, where an overnight report before the first arrival is No)."""
    rm = rel.hour * 60 + rel.minute
    return rm + cfg["home_gap_min"] >= 1440 or rm < cfg.get("home_day_start", HOME_DAY_START)


def _airport(ap, rep, rel, cfg):
    """(ok, part of the why text) for one airport. rel is the release HOME is judged from (customs included)."""
    e = cfg["in"].get(ap)
    homes = cfg["home"].get(ap)
    if not e or not homes:
        return False, f"{ap} no table"
    rm = rep.hour * 60 + rep.minute
    arr = [d + e["block_max"] for d in e["dep"]]
    ins = [a for a in arr if a < rm and a < 1440]  # the same day as the report, arriving before it
    late = overnight(rel, cfg)
    lm = rel.hour * 60 + rel.minute + cfg["home_gap_min"]
    outs = [] if late else [d for d in homes if d >= lm]  # the same day as the release
    ok_in, ok_home = len(ins) >= IN_NEEDED, bool(outs)
    part = f"{ap} in {len(ins)}" + (f" by {_hm(max(ins))}" if ins else "") + ("" if ok_in else f" (needs {IN_NEEDED})")
    part += f", home {_hm(outs[0])}" if outs else (", no home (overnight release)" if late else ", no home")
    return ok_in and ok_home, part


def comm(report, release, cfg, customs=False):
    """(result, why): the config's airports that pass both legs joined with '/' ('AAA/BBB', 'AAA'), 'No' when every
    airport surely fails, '' (with the why) when none passes but one is unknown; ('', '') with no config, no airport
    with both tables or no report / release time. report and release: naive HST datetimes or ISO texts; release is
    block-in + 15 min (PWA 2.19.b).
    IN: two scheduled nonstops the report day arriving HNL before report (PWA 26.QQ.2); an overnight report before
    the first arrival is No. HOME: one nonstop HNL to the airport home_gap_min+ after release, the same day; an
    overnight release is No (overnight()).
    customs (PWA 2.19.b, a release 30 min after block-in when clearing customs), far.py's rule: a No needs the sure
    case to fail, a pass needs the worst case to pass. True: the last leg is known to come from outside the US, so the
    customs release is the sure one and HOME uses it. False: known not to clear customs. None: the origin is not on
    file, so HOME is judged at both releases: an airport that passes with customs counts, one that fails without it
    fails, and one that passes only without customs is unknown ('home 21:00 only if no customs' in the why)."""
    try:
        if not cfg or not any(ap in cfg["in"] and ap in cfg["home"] for ap in cfg.get("airports") or ()):
            return "", ""
        rep, rel = _dt(report), _dt(release)
        if not rep or not rel or rel < rep:
            return "", ""
        worst = rel + timedelta(minutes=CUSTOMS_MIN)
        unknown = customs is None
        if customs and not unknown:
            rel = worst
        ok, unk, parts = [], [], []
        for ap in cfg["airports"]:
            good, part = _airport(ap, rep, rel, cfg)
            if unknown and good:
                good_w, part_w = _airport(ap, rep, worst, cfg)
                if not good_w:  # passes only if the last leg does not clear customs
                    unk.append(ap)
                    parts.append(f"{part} only if no customs")
                    continue
                part = part_w
            parts.append(part)
            if good:
                ok.append(ap)
        note = (f" ({worst:%H:%M} if customs, origin not on file, PWA 2.19.b)" if unknown
                else " (customs, PWA 2.19.b)" if customs else "")
        why = (f"rpt {rep:%m-%d %H:%M}, rel {rel:%m-%d %H:%M}{note}: " + "; ".join(parts)
               + f". PWA 26.QQ.2: {IN_NEEDED} nonstops in before report; home 1 nonstop {cfg['home_gap_min']}+ min"
                 " after release, same day")
        return ("/".join(ok) if ok else "" if unk else "No"), why[:WHY_MAX]
    except Exception:  # noqa: BLE001: a field, never an error
        return "", ""


# ---------------------------------------------------------------- month type and rules
def month_type(month, cfg):
    """'line', 'reserve' or '' for a bid month ('YYYY-MM'; a date is read as its calendar month, so a day near a bid
    period's edge passes its bid_month() key instead)."""
    try:
        if not cfg:
            return ""
        mk = month if isinstance(month, str) else f"{month:%Y-%m}"
        return (cfg.get("month_types") or {}).get(str(mk)[:7], "")
    except Exception:  # noqa: BLE001
        return ""


def vac_days(cfg, months=None):
    """Every VAC day: the config's ranges and the VAC items of the schedule months on file."""
    out = set()
    for a, b in (cfg or {}).get("vac") or []:
        out.update(_span(a, b))
    for sch in (months or {}).values():
        for it in (sch or {}).get("items") or []:
            if str(it.get("trip") or "").upper() == "VAC":
                a, b = _date(it.get("start")), _date(it.get("end") or it.get("start"))
                if a and b:
                    out.update(_span(a, b))
    return out


def _codes(months):
    """{day: code} of every schedule item on file (trips and day codes), and the days the schedules cover."""
    busy, covered = {}, set()
    for sch in (months or {}).values():
        rows, codes = _page(sch)
        covered |= rows
        for d, c in codes.items():
            busy.setdefault(d, c)
    return busy, covered


def _page(sch):
    """(the days one schedule month's page lists, {day: code} of its items: trips and day codes)."""
    rows, codes = set(), {}
    for d in (sch or {}).get("days") or []:
        dd = _date(d[0]) if isinstance(d, (list, tuple)) and d else None
        if dd:
            rows.add(dd)
    for it in (sch or {}).get("items") or []:
        a, b = _date(it.get("start")), _date(it.get("end") or it.get("start"))
        if a and b:
            for d in _span(a, b):
                codes.setdefault(d, str(it.get("trip") or "").upper())
    return rows, codes


def bid_month(months, period=None):
    """day -> the key ('YYYY-MM') of the bid month that day belongs to, which judges it (its type, its schedule and
    its days off). Hawaiian's bid periods are not calendar months (November 2026 runs Nov 1 to Dec 1, December
    Dec 2 to 31), and FLICA's Days Off total counts the bid period. In order:
    1. period(day), the pilot's pairing files' period bounds (the Watcher passes crewidx.period_for's), when it
       gives a 'YYYY-MM' (None: those bounds are not on file);
    2. the schedule pages on file: a page lists a day outside its bid period only for a pairing carried across the
       edge, so a page that lists the day with no pairing on it owns it; else a page that lists it at all (a carried
       trip day, which conflicts whichever month judges it); the calendar month's page first in both;
    3. the calendar month."""
    pages = {mk: _page(s) for mk, s in (months or {}).items()}
    memo = {}

    def of(d):
        if d in memo:
            return memo[d]
        mk = None
        if period:
            try:
                p = period(d)
            except Exception:  # noqa: BLE001: the pages and the calendar still answer
                p = None
            mk = p if isinstance(p, str) and MONTH_RE.match(p) else None
        if mk is None:
            cal = f"{d:%Y-%m}"
            listing = sorted(k for k, (rows, _) in pages.items() if d in rows)
            own = [k for k in listing if not PAIRING_RE.match(pages[k][1].get(d, ""))]
            group = own or listing
            mk = cal if cal in group or not group else group[0]
        memo[d] = mk
        return mk

    of.pages = pages
    return of


def days_off(mk, months, cfg, add=(), period=None):
    """Days off in bid month mk after adding the days in `add`, over that bid period (bid_month(); not the calendar
    month): FLICA's own Days Off total on mk's page (it counts VAC days as off) less the days of `add` in that bid
    period that are off on it (no item or an off code, cfg off_codes; a VAC day stays off, it is never a pickup
    day); without that total, a recount of the page's own bid period days: every day with no item, a VAC day or an
    off code, less the same days of `add`. None when mk's page is not on file."""
    if mk not in (months or {}):
        return None
    return _days_off(mk, months, cfg, set(add), bid_month(months, period))


def _days_off(mk, months, cfg, add, bid):
    rows, codes = bid.pages[mk]
    vac = vac_days(cfg, months)
    off_codes = set((cfg or {}).get("off_codes") or OFF_CODES)

    def off(d):
        c = codes.get(d)
        return c is None or c in off_codes or d in vac

    mine = [d for d in rows if bid(d) == mk]  # the page's own bid period days
    used = sum(1 for d in mine if d in add and off(d) and d not in vac)
    tot = ((months.get(mk) or {}).get("totals") or {}).get("days_off")
    try:
        tot = None if isinstance(tot, bool) or tot in (None, "") else int(tot)
    except (TypeError, ValueError):
        tot = None
    return (tot if tot is not None else sum(1 for d in mine if off(d))) - used


def _rest(far):
    """The 11 h minimum rest (PWA 10.E.1.a) from the FAR column: 'OK (CBA rest 10:30)' -> 'Rest 10:30'; the possible
    form, short only if the neighbour clears customs (PWA 2.19.b), keeps its '?': 'OK (CBA rest 10:50?)' -> 'Rest
    10:50?'; a FAR rest failure as the column says it ('Rest 9:00 before'); '' otherwise."""
    far = str(far or "")
    m = re.search(r"CBA rest (\d+:\d{2}\??)", far)
    if m:
        return f"Rest {m.group(1)}"
    m = re.match(r"(Rest \d+:\d{2} (?:before|after))", far)
    return m.group(1) if m else ""


def _join(items):
    """The rule's parts joined with ', ' at most RULE_MAX long, cut between parts (the first ones kept)."""
    out = ""
    for x in items:
        t = f"{out}, {x}" if out else x
        if len(t) > RULE_MAX:
            break
        out = t
    return out or (items[0][:RULE_MAX] if items else "")


def month_rule(start, end, credit, fit, far, months, cfg, period=None, b672=""):
    """The row against the type of each bid month it touches (a trip across a bid period's end is judged in both, each
    by its own type): 'OK', or what fails joined with ', ' ('VAC', 'Conflict H3659', 'Days off 11', 'Over 98/672
    (98:01)', 'Rest 10:30', 'Not SCR'), the unknowns ('Rest ?', 'Rest 10:50?', '672 ? (block not read)', 'No sched'
    when a schedule month is not on file) never read as OK; 'VAC' alone for a VAC day in a month with no type; '' with
    no config, or with no type for any of its months and no VAC day. start / end: dates. Never raises.
    b672 (1.7.1): block_672()'s tag, put among the parts where 'Over cap' was (after the months' own parts, before the
    rest) when a month the trip touches has a type; a 'Fits 672 (97:59)' is no fail ('OK, Fits 672 (97:59)' when
    nothing else is said). credit: no longer read (1.7.1: no monthly credit cap; a cap_credit in smart.json is
    ignored), kept for the callers.
    Each day's bid month is bid_month(months, period)'s: period(day) gives the pairing files' bounds (the Watcher's),
    else the schedule pages and the calendar month decide; that month's type, schedule page and days off judge it.
    line: a day holding a trip or a duty code (not an off code, not VAC) is a Conflict, read from the schedule itself
    as well as the fit tag (which says 'No sched' for a trip across a month end, and names an off code such as GDO
    as a Conflict, which a line is free to fly on); days off per bid month. reserve: every day of that month is SCR.
    A month with no type next to one with a type: a day holding a trip is still a Conflict."""
    try:
        a, b = _date(start), _date(end or start)
        if not cfg or not a:
            return ""
        b = b if b and b >= a else a
        days = _span(a, b)
        months = months or {}
        bid = bid_month(months, period)
        by = {}
        for d in days:
            by.setdefault(bid(d), []).append(d)
        types = {mk: month_type(mk, cfg) for mk in by}
        vac = bool(set(days) & vac_days(cfg, months))  # never a pickup day, line, reserve or no type
        if not any(types.values()):
            return "VAC" if vac else ""
        out, nosched, line = (["VAC"] if vac else []), False, False
        busy, covered = _codes(months)
        off = set(cfg.get("off_codes") or OFF_CODES)
        res = set(cfg.get("reserve_codes") or RESERVE_CODES)
        f = str(fit or "")
        fcode = f.split(" ", 1)[1].strip().upper() if f.startswith("Conflict ") else ""
        mdo = cfg.get("min_days_off")

        def code(d, mk):  # the day's code on its own bid month's page, else on any page that lists it
            rows, codes = bid.pages.get(mk, ((), {}))
            return codes.get(d) if d in rows else busy.get(d)

        def duty(c, mt):  # a day code that is not free for a pickup in a month of type mt
            return bool(c) and c not in off and c != "VAC" and (mt == LINE or c not in res)

        for mk, md in by.items():
            mt = types[mk]
            # a typed month is judged on its own page; a month with no type on any page (its trips still conflict)
            listed = (bid.pages[mk][0] if mk in bid.pages else set()) if mt else covered
            if any(d not in listed for d in md):
                nosched = True  # this month's days are not on file: its checks cannot run
                continue
            if mt == RESERVE:
                if any(code(d, mk) not in res for d in md):
                    out.append("Not SCR")
                continue
            if mt == LINE and mk == bid(a) and fcode and fcode != "VAC" and fcode not in off:
                out.append(f)  # the fit tag, as the schedule card shows it ('Conflict VAC' is the VAC above)
            else:  # an off code in the fit tag is a day off on a line: the schedule's own days decide
                hit = next((code(d, mk) for d in md if duty(code(d, mk), mt)), None)
                if hit:
                    out.append(f"Conflict {hit}")
            if mt != LINE:
                continue
            line = True
            if mdo is not None:
                n = _days_off(mk, months, cfg, set(md), bid)
                if n is not None and n < mdo:
                    out.append(f"Days off {n}")
        if b672:
            out.append(str(b672))  # the 672 h block buffer, one per trip, where 'Over cap' was (1.7.1)
        if line:
            r = _rest(far)
            near = [a - timedelta(days=1), b + timedelta(days=1)]  # the days either side: a trip there needs rest
            if r:
                out.append(r)
            elif str(far or "") == "?" and (f.startswith("Check rest") or any(
                    duty(code(d, bid(d)), month_type(bid(d), cfg) or LINE) for d in near)):
                out.append("Rest ?")  # next to a trip and the times are not on file yet: never read as OK
        if nosched:
            out.append("No sched")
        out = [x for i, x in enumerate(out) if x not in out[:i]]
        if all(x.startswith(FITS_672) for x in out):
            out.insert(0, "OK")  # nothing fails: the 672 tag is a note
        return _join(out)
    except Exception:  # noqa: BLE001: a field, never an error
        return ""


# ---------------------------------------------------------------- the 672 h block buffer (1.7.1, FW-0042)
def _hmm(m):
    """Minutes as H:MM, the hours unpadded (97:59, 6:00, 101:30)."""
    return f"{m // 60}:{m % 60:02d}"


def _b672(tag, hm="", ok=""):
    return {"tag": tag, "b672": hm, "b672_ok": ok}


def block_672(new, mine):
    """Ryan's rule (Nov 9, via Hark): the pilot's block hours in the 672 consecutive hours ending at the pickup's last
    release, flown + scheduled + the pickup, against the company's 98 h buffer (BUFFER_672_H; FAR 117's own flight
    time limit is 100 h in 672 h, far.FT_672, whose section far.py cites). Block (flight) time, never credit.
    new / mine: the pickup and the pilot's line as far.py reads them (the Watcher's far_trips(), the FAR column's
    own); far.flight_time_to_release() sums them with the FAR column's flight time machinery. Returns {tag, b672,
    b672_ok}:
    - 'Fits 672 (97:59)', b672 '97:59', b672_ok True: at most 98:00 (exactly 98:00 fits);
    - 'Over 98/672 (98:01)', b672 '98:01', b672_ok False: over it; with a block not on file, the blocks on file are
      over already (an unknown can only add);
    - '672 ? (block not read)': a block in the window is not on file (a trip of the pilot's whose pairing page was not
      read, or the pickup's own), '672 ? (line not on file)': days in the window with no schedule month on file,
      '672 ? (times not read)': the pickup's report or release is not known (new is None), '672 ? (97:30 to 98:40)':
      only a trip across the window's start decides it (its block known, not how much of it flew inside); b672 '',
      b672_ok '' (never guessed). A trip across the window's start counts in a Fits up to its overlap (the most it can
      be), so that Fits holds whatever the split.
    Never raises."""
    try:
        if not new:
            return _b672(f"{UNK_672} (times not read)")
        r = FAR.flight_time_to_release(new, mine or [])
        known, worst, lim = int(round(r["known"] * 60)), int(round(r["worst"] * 60)), BUFFER_672_H * 60
        if known > lim:
            return _b672(f"{OVER_672} ({_hmm(known)})", _hmm(known), False)
        if r["unknown_block"]:
            return _b672(f"{UNK_672} (block not read)")
        if r["unknown_line"]:
            return _b672(f"{UNK_672} (line not on file)")
        top = max(known, worst)  # worst, unless a block on file is longer than its own span (a page's slip)
        if top <= lim:
            return _b672(f"{FITS_672} ({_hmm(top)})", _hmm(top), True)
        return _b672(f"{UNK_672} ({_hmm(known)} to {_hmm(top)})")
    except Exception:  # noqa: BLE001: a field, never an error
        return _b672(f"{UNK_672} (block not read)")


# ---------------------------------------------------------------- pairing value
def value(credit, cfg):
    """Whole dollars of credit x the hourly rate; '' with no rate or an unreadable credit."""
    try:
        rate = (cfg or {}).get("rate")
        h = hours(credit)
        if not rate or h is None or h < 0:
            return ""
        return int(round(h * rate))
    except Exception:  # noqa: BLE001
        return ""

