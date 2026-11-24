"""In-flight pickups (0.5.2/0.5.3, Ryan): was the picker airborne when the trip left the pot?

Source: Tools > Schedule Lookup (cmschedules.cgi, mapped read only 2026-11-04) gives a pilot's month with
pair('H3648','20261103') links; each pairing's legs come from the mobile pairing page the Watcher already
parses. A pickup counts as in flight only between a leg's block-out and block-in: layover rest and ground
time do not. No pairing covering the pickup day = not in flight. Read only, GET only."""
import os
import random
import re
import time
from datetime import date, datetime
from urllib.parse import unquote

from captures import mask_emp
from pot import (TZ, CM_PAIR_RE, classify, inflight_leg, leg_local_date, parse_legs, schedule_items, trip_minute,
                 visible_text)

# 0.5.5: the page builds its rows in JS: TAry[...]=new Task(1, "SU", "01", "H3647", "PHX", "20261101", 1, 0, 'H3647');
TASK_RE = re.compile(r'new Task\(\s*\d+,\s*"[A-Z]{2}",\s*"\d{2}",\s*"([A-Z]\d{4}[A-Z]?)",\s*"[^"]*",\s*"(\d{8})"')


def parse_cm_schedule(html):
    """[{'trip', 'start'}] from a crewmember schedule page: its JS Task(...) rows (real pages) or
    pair('H3648','20261103') links (rendered DOM), in page order, each pairing once."""
    out, seen = [], set()
    for trip, ymd in TASK_RE.findall(html or "") + CM_PAIR_RE.findall(html or ""):
        k = (trip, ymd)
        if k in seen:
            continue
        seen.add(k)
        out.append({"trip": trip, "start": f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}"})
    return out

DAY_RE = re.compile(r'new Task\(\s*(\d),\s*"([A-Z]{2})",\s*"(\d{2})",\s*"([^"]*)",\s*"([^"]*)",\s*"(\d{0,8})"')
NAME_RE = re.compile(r"([A-Z][A-Z' .-]*,\s*[A-Z][A-Z' .-]*?)\s*\(Emp#\s*(\d+)\)")  # FLICA prints LAST, FIRST in caps
MON3 = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


def parse_cm_month(html):
    """0.8.0 (Ryan: a picker's month at a tap). The whole crewmember schedule page as the schedule card
    wants it: {'month': 'YYYY-MM', 'name', 'emp', 'updated', 'days': [[iso, code, lay]], 'items':
    [{'trip','start','end','lay'}], 'totals': {'block','credit','days_off'}}. Every Task(...) row is a
    day: code is the pairing (or VAC/SCR...) on its first day, lay the layover station ('-' mid trip,
    'HNL' on the day back home, '' on a day off). None when the page is not a schedule."""
    h = html or ""
    rows = DAY_RE.findall(h)
    sel = re.search(r'<option value="(\d{4})"\s+selected', h)
    if not rows or not sel:
        return None
    mm, yy = int(sel.group(1)[:2]), 2000 + int(sel.group(1)[2:])
    # rows run from the end of last month to the start of next; the first row's own date anchors the month
    first_dd = int(rows[0][2])
    mon, yr = (mm - 1, yy) if (first_dd > 20 and rows[0][5][4:6] != f"{mm:02d}") else (mm, yy)
    if mon == 0:
        mon, yr = 12, yr - 1
    days, prev = [], None
    for _yn, _dow, dd, code, lay, _pd in rows:
        dd = int(dd)
        if prev is not None and dd < prev:
            mon, yr = (1, yr + 1) if mon == 12 else (mon + 1, yr)
        prev = dd
        code = re.sub(r"&nbsp;", "", unquote(code)).strip()  # 0.8.6: FLICA URL-encodes codes (O%2FK = O/K)
        lay = lay.strip()
        try:
            iso = date(yr, mon, dd).isoformat()
        except ValueError:
            continue
        days.append([iso, code, lay])
    items = schedule_items(days, "HNL")  # trip end: the mobile schedule's builder (a trip home the day the next starts)
    tot = {}
    for key, pat in (("block", r"Block\s*(?:&nbsp;\s*)*</TD>\s*<TD[^>]*>\s*([\d.:]+)"),
                     ("credit", r"Credit\s*(?:&nbsp;\s*)*</TD>\s*<TD[^>]*>\s*([\d.:]+)"),
                     ("days_off", r"Days Off\s*(?:&nbsp;\s*)*</TD>\s*<TD[^>]*>\s*(\d+)")):
        m = re.search(pat, h, re.I)
        if m:
            tot[key] = int(m.group(1)) if key == "days_off" else m.group(1).replace(".", ":")
    nm = NAME_RE.search(re.sub(r"<[^>]+>", " ", h))  # raw case: visible_text lowercases
    up = re.search(r"Last Updated:\s*([A-Za-z]{3}\s+\d{1,2},\s*\d{4}\s+\d{1,2}:\d{2}(?::\d{2})?)", h)
    return {"month": f"{yy}-{mm:02d}", "name": nm.group(1).strip().title() if nm else "", "emp": nm.group(2) if nm else "",
            "updated": up.group(1) if up else "", "days": days, "items": items, "totals": tot}


# 1.7.7 (Ryan, Nov 14: "when it says picked up in flight. I want to know what flight he was flying to be certain. Add
# the flight number... i.e AS808/06NOV and date"): the leg a pickup was made on, kept on the pickup as inflt_leg
# {flt, frm, to, dep_l, date, dh, src}: flt the flight number, dep_l its printed local departure, date its local
# departure date at its origin (ISO), dh True for a deadhead (airborne all the same), src "page" (FLICA's pairing page
# the check read) or "package" (the pairings package, a backfill with no FLICA load).
def page_leg(leg, start_iso):
    """inflt_leg from a parse_legs leg of a trip that started on start_iso."""
    return {"flt": leg["flt"], "frm": leg["frm"], "to": leg["to"], "dep_l": leg["dep_l"],
            "date": leg_local_date(start_iso, leg), "dh": bool(leg.get("dh")), "src": "page"}


def _pkg_min(v):
    hit = re.fullmatch(r"(\d{1,3})[:h](\d{2})", str(v or "").strip())
    return int(hit.group(1)) * 60 + int(hit.group(2)) if hit else None


def package_leg(detail, start_iso, at_utc_iso):
    """1.7.7 backfill, no FLICA load: inflt_leg from the pairings package's detail of the picker's pairing
    (pdfs.package_legs: duties with legs [DAY, DH, flight, from, to, departure L, arrival L, BLKT, ...], DAY the trip
    day, times local at each station as printed) for a trip that started on start_iso, when the UTC instant falls
    inside one of its legs (departure plus block): the leg's departure in HST minutes is (DAY - 1) days plus its local
    departure less the origin's offset from HST (pot.TZ; a station not in TZ: that leg is not placed). None when no leg
    holds it."""
    m = trip_minute(start_iso, at_utc_iso)
    if m is None or not isinstance(detail, dict):
        return None
    for du in detail.get("duties") or []:
        for lg in (du.get("legs") if isinstance(du, dict) else None) or []:
            if not isinstance(lg, list) or len(lg) < 8:
                continue
            day, dh, flt, frm, to, depl, _arrl, blkt = (str(x or "") for x in lg[:8])
            dep, blk = _pkg_min(depl), _pkg_min(blkt)
            if not day.isdigit() or not 1 <= int(day) <= 40 or frm not in TZ or dep is None or blk is None:
                continue
            dep_h = (int(day) - 1) * 1440 + dep - (TZ[frm] + 10) * 60
            if dep_h <= m <= dep_h + blk:
                f = re.sub(r"\*+$", "", flt).lstrip("0") or flt
                return {"flt": f, "frm": frm, "to": to, "dep_l": depl.zfill(5),
                        "date": date.fromordinal(date.fromisoformat(start_iso).toordinal() + int(day) - 1).isoformat(),
                        "dh": dh == "DH", "src": "package"}
    return None


CM_SCHED = "{base}/full/cmschedules.cgi?GO=1&SchBrowser=1&Prompt=1&EmployeeID={emp}"
CM_SCHED_MONTH = "{base}/full/cmschedules.cgi?Prompt=1&EmployeeID={emp}&bd={bd}&SchBrowser=1"
PROBE = {"logged": 0}
RESET_V = 5  # bump when the parser changes so stored verdicts are re-checked once
RECHECK_NO_V = 1  # FW-0013: 'not in flight' verdicts (some were read off the error page below) are looked up again, once
# 1.7.8 (Ryan, Nov 15: "Re-check them"): the verdicts 1.7.7 dropped as made for another pilot (inflt_skip) are looked up
# again once for the picker (store.recheck_inflt_skip); the other picker of a both-seats pickup gets his own lookup
RECHECK_SKIP_V = 1
# 1.7.9 (Ryan, Nov 15): the pickups whose open-seat picker is not known (the pot showed no open seat and the pickup
# names two pilots: the ones 1.7.7 dropped the verdict of) are queued once so EACH pilot named gets his own lookup
# (store.queue_inflt_named, verdicts in inflt_named by employee number), the oldest too, within the paced budget
NAMED_V = 1


CAPTURE_DIR = "/share/flight_watcher/captures"
# 1.6.2 (Release A item 8): watcher.py sets CAPTURE_DIR to this instance's folder and WRITE to its capture policy
# (captures.py: the admin's as before; a pilot's only while captures are on, masked, in his own folder)
WRITE = None
# 1.7.3 review: set by the Watcher (watcher.page_log): page text for a log line, a pilot's only while his captures are on
PAGE_LOG = None


# FW-0013: FLICA's "Application Error" page ("An error has occurred, please contact CAE Customer Care ... No Schedule
# Available for Nov 2026.") still says "(Emp# n) Schedule" and "Last Updated: Unknown". It holds no schedule, so it is
# unreadable (retried later), never a month with no trips in it.
ERROR_HINTS = ("application error", "an error has occurred", "no schedule available", "last updated: unknown")


def schedule_ok(html):
    """The crewmember schedule page proper (not a forwarding, prompt or error page): it names the pilot
    (Emp#) and carries a Last Updated stamp. 'pair(' alone is not enough: the page's own JS defines
    function pair(...) even when no pairing links are rendered."""
    t = visible_text(html).lower()
    if any(h in t for h in ERROR_HINTS):
        return False
    return "last updated" in t and ("emp#" in t or "new task(" in (html or "").lower())  # 0.8.7: Ryan's own page has no Emp#


def capture(html, emp, log):
    """0.5.4: save the first two schedule pages to the private share folder so the parser can be
    checked against the real HTML (never committed)."""
    if PROBE.get("saved", 0) >= 2:
        return
    try:
        if WRITE is not None:
            if not WRITE(f"cmschedule_{emp}.html", html):
                return  # a pilot with captures off: nothing saved, nothing counted
        else:
            os.makedirs(CAPTURE_DIR, exist_ok=True)
            open(f"{CAPTURE_DIR}/cmschedule_{emp}.html", "w").write(html)
        PROBE["saved"] = PROBE.get("saved", 0) + 1
        log.info("inflt: a picker's schedule page saved (%d chars, %d pair links)", len(html),  # review: no number
                 len(parse_cm_schedule(html)))
    except Exception as e:
        # 1.7.9 review: the kind of fault only: its text names the file, and the file's name carries the number
        log.info("inflt: capture skipped: %s", type(e).__name__)


def fetch_schedule(fl, base, emp, bd, cur_bd, log, key):
    """The parsed month for one picker, or None (logged once with the page text)."""
    urls = [CM_SCHED.format(base=base, emp=emp)] if bd == cur_bd else []
    urls.append(CM_SCHED_MONTH.format(base=base, emp=emp, bd=bd))
    for i, url in enumerate(urls):
        if i:
            time.sleep(random.uniform(1.5, 3.5))
        html = fl.fetch(url)
        if classify(html) == "ok" and schedule_ok(html):
            capture(html, emp, log)
            return parse_cm_schedule(html)
        if PROBE["logged"] < 3:
            PROBE["logged"] += 1
            txt = visible_text(html)[:300]
            # review: the month and the answer, never the query (it carries the employee number); 1.7.9: nor the
            # number the page itself prints ("(emp# n) schedule last updated"), masked here whoever quotes the page
            log.info("inflt %s: schedule lookup %s gave %s: %s", key, bd, classify(html),
                     mask_emp(PAGE_LOG(txt) if PAGE_LOG else txt))
    return None


def run(fl, db, limit, log, local_now, base, hst, on_sched=None, period_of=None):
    """Three lookups per check: look the picker's month up, read the pairings around the pickup day,
    decide. 1.7.9: a pickup whose picker is not known is looked up for each pilot it names (his own verdict). Returns True when any verdict was written. FW-0056: on_sched(items) gets each picker month read
    ([{trip, start}]), so the crew index reads those trips too. 1.8.2 (LIVE-10): period_of(iso) gives a day's bid
    month ('YYYY-MM'): the picker's month is the pickup day's bid month (a Dec 1 pickup reads his November page,
    bd=1126, whose trip runs Nov 29 to Dec 1). FLICA's default page (no bd) is tried first only for a pickup whose bid
    month is the calendar month of today, so never on Dec 1 (a pickup on or before it is November's, or earlier), when
    the default page may show either month. None: the calendar month, as before."""

    def bid_bd(d):
        try:
            k = str(period_of(d.isoformat()) if period_of else "")
        except Exception:  # noqa: BLE001: the calendar month still answers
            k = ""
        return f"{k[5:7]}{k[2:4]}" if re.fullmatch(r"\d{4}-\d{2}", k) else f"{d.month:02d}{d.year % 100:02d}"

    changed_early = False
    if db.get("score_email_v") != 1:  # 0.5.6 one-shot: score the email-caught pickups recorded before 0.5.6
        for k in db.unscored_pickups():
            if db.score_pickup(k) is not None:
                changed_early = True
        db.put("score_email_v", 1)
    if db.get("inflt_reset_v") != RESET_V:  # verdicts from an older parser are looked up again, once
        db.reset_inflt()
        db.put("inflt_reset_v", RESET_V)
    if db.get("inflt_recheck_no_v") != RECHECK_NO_V:
        db.reset_inflt(only=False)
        db.put("inflt_recheck_no_v", RECHECK_NO_V)
    if db.get("inflt_skip_recheck_v") != RECHECK_SKIP_V:
        n_skip = db.recheck_inflt_skip()
        db.put("inflt_skip_recheck_v", RECHECK_SKIP_V)
        if n_skip:  # review: the number queued (each listed first until looked up), not the number flagged
            log.info("in-flight: %d pickups whose verdict 1.7.7 dropped (made for another pilot) are queued to be "
                     "looked up again once for the picker, first, within the paced in-flight budget", n_skip)
    if db.get("inflt_named_v") != NAMED_V:
        n_named = db.queue_inflt_named()
        db.put("inflt_named_v", NAMED_V)
        if n_named:
            log.info("in-flight: %d pickups whose open-seat picker is not known are queued so each pilot named gets "
                     "his own lookup once, first, within the paced in-flight budget", n_named)
    todo = db.pickups_without_inflt(50)
    if not todo:
        return changed_early
    cur = local_now()
    # 1.8.2 (G1-TEST-1): the default page only for a pickup of the calendar month (on Dec 1 none: theirs is 1126)
    cur_bd = f"{cur.month:02d}{cur.year % 100:02d}"
    cache, n, changed = {}, 0, changed_early
    for key, emp, gone, tries in todo:
        if n >= limit:
            break
        n += 1
        try:
            d = datetime.fromisoformat(gone.replace("Z", "+00:00")).astimezone(hst)
            bd = bid_bd(d.date())  # 1.8.2 (LIVE-10): the pickup day's bid month
            ck = (emp, bd)
            if ck not in cache:
                if n > 1:
                    time.sleep(random.uniform(1.5, 3.5))
                sched = fetch_schedule(fl, base, emp, bd, cur_bd, log, key)
                if sched is None:
                    db.set_inflt(key, None, tries=tries + 1, emp=emp)  # 1.7.8: this picker's try
                    continue
                cache[ck] = sched
                if on_sched:
                    try:
                        on_sched(sched)
                    except Exception as e:
                        log.info("inflt %s: schedule trips not passed on: %s", key, mask_emp(e))
            day = d.date()
            cands = [p for p in cache[ck] if 0 <= (day - date.fromisoformat(p["start"])).days <= 6]
            verdict, trip, leg = False, "", None
            for pr in cands:
                time.sleep(random.uniform(1.5, 3.5))
                page = fl.fetch(f"{base}/full/mobilepairing.cgi?PID={pr['trip']}&DATE={pr['start'].replace('-', '')}"
                                "&FROM=MobileOpentimePot&CurrentPage=1")
                if classify(page) != "ok":
                    continue
                # 1.7.7 review: inflight_leg puts a first leg that leaves after midnight of the start day on its own day
                lg = inflight_leg(parse_legs(visible_text(page), dh=True), pr["start"], gone)
                if lg is not None:  # 1.7.7: the leg itself, a deadhead too
                    verdict, trip, leg = True, f"{pr['trip']} {pr['start']}", page_leg(lg, pr["start"])
                    break
            db.set_inflt(key, verdict, trip, tries=tries + 1, emp=emp, leg=leg)
            on = (f"IN FLIGHT on {trip} ({'DH ' if leg['dh'] else ''}{leg['flt']} {leg['frm']}-{leg['to']} "
                  f"{leg['date']})" if verdict else "not in flight")
            # review: the picker by his seat order (picker 1, picker 2), never his employee number; 1.7.9: a pilot
            # named on a pickup whose picker is not known by his place in its 'by' (named pilot 1, named pilot 2)
            log.info("inflt %s: %s %s at pickup (%s)", key, db.inflt_who(key, emp), on,
                     ", ".join(p["trip"] + " " + p["start"] for p in cands) or "no trip that day")
            changed = True
        except Exception as e:
            log.info("inflt %s skipped: %s", key, mask_emp(e))  # 1.7.9: a load error can quote the query
            db.set_inflt(key, None, tries=tries + 1, emp=emp)
    return changed
