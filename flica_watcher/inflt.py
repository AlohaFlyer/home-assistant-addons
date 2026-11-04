"""In-flight pickups (0.5.2/0.5.3, Ryan): was the picker airborne when the trip left the pot?

Source: Tools > Schedule Lookup (cmschedules.cgi, mapped read only 2026-11-04) gives a pilot's month with
pair('H3648','20261103') links; each pairing's legs come from the mobile pairing page the Watcher already
parses. A pickup counts as in flight only between a leg's block-out and block-in: layover rest and ground
time do not. No pairing covering the pickup day = not in flight. Read only, GET only."""
import os
import random
import time
from datetime import date, datetime

from pot import classify, inflight_at, parse_cm_schedule, parse_legs, visible_text

CM_SCHED = "{base}/full/cmschedules.cgi?GO=1&SchBrowser=1&Prompt=1&EmployeeID={emp}"
CM_SCHED_MONTH = "{base}/full/cmschedules.cgi?Prompt=1&EmployeeID={emp}&bd={bd}&SchBrowser=1"
PROBE = {"logged": 0}
RESET_V = 4  # bump when the parser changes so stored verdicts are re-checked once


CAPTURE_DIR = "/share/flica_watcher/captures"


def schedule_ok(html):
    """The crewmember schedule page proper (not a forwarding or prompt page): it names the pilot
    (Emp#) and carries a Last Updated stamp. 'pair(' alone is not enough: the page's own JS defines
    function pair(...) even when no pairing links are rendered."""
    t = visible_text(html).lower()
    return "emp#" in t and "last updated" in t


def capture(html, emp, log):
    """0.5.4: save the first two schedule pages to the private share folder so the parser can be
    checked against the real HTML (never committed)."""
    if PROBE.get("saved", 0) >= 2:
        return
    try:
        os.makedirs(CAPTURE_DIR, exist_ok=True)
        open(f"{CAPTURE_DIR}/cmschedule_{emp}.html", "w").write(html)
        PROBE["saved"] = PROBE.get("saved", 0) + 1
        log.info("inflt: schedule page for %s saved (%d chars, %d pair links)", emp, len(html),
                 len(parse_cm_schedule(html)))
    except Exception as e:
        log.info("inflt: capture skipped: %s", e)


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
            log.info("inflt %s: schedule lookup %s gave %s: %s", key, url.split("?")[1], classify(html),
                     visible_text(html)[:300])
    return None


def run(fl, db, limit, log, local_now, base, hst):
    """Three pickups per check: look the picker's month up, read the pairings around the pickup day,
    decide. Returns True when any verdict was written."""
    if db.get("inflt_reset_v") != RESET_V:  # verdicts from an older parser are looked up again, once
        db.reset_inflt()
        db.put("inflt_reset_v", RESET_V)
    todo = db.pickups_without_inflt(50)
    if not todo:
        return False
    cur = local_now()
    cur_bd = f"{cur.month:02d}{cur.year % 100:02d}"
    cache, n, changed = {}, 0, False
    for key, emp, gone, tries in todo:
        if n >= limit:
            break
        n += 1
        try:
            d = datetime.fromisoformat(gone.replace("Z", "+00:00")).astimezone(hst)
            bd = f"{d.month:02d}{d.year % 100:02d}"
            ck = (emp, bd)
            if ck not in cache:
                if n > 1:
                    time.sleep(random.uniform(1.5, 3.5))
                sched = fetch_schedule(fl, base, emp, bd, cur_bd, log, key)
                if sched is None:
                    db.set_inflt(key, None, tries=tries + 1)
                    continue
                cache[ck] = sched
            day = d.date()
            cands = [p for p in cache[ck] if 0 <= (day - date.fromisoformat(p["start"])).days <= 6]
            verdict, trip = False, ""
            for pr in cands:
                time.sleep(random.uniform(1.5, 3.5))
                page = fl.fetch(f"{base}/full/mobilepairing.cgi?PID={pr['trip']}&DATE={pr['start'].replace('-', '')}"
                                "&FROM=MobileOpentimePot&CurrentPage=1")
                if classify(page) != "ok":
                    continue
                if inflight_at(parse_legs(visible_text(page)), pr["start"], gone):
                    verdict, trip = True, f"{pr['trip']} {pr['start']}"
                    break
            db.set_inflt(key, verdict, trip, tries=tries + 1)
            log.info("inflt %s: picker %s %s at pickup (%s)", key, emp,
                     "IN FLIGHT on " + trip if verdict else "not in flight",
                     ", ".join(p["trip"] + " " + p["start"] for p in cands) or "no trip that day")
            changed = True
        except Exception as e:
            log.info("inflt %s skipped: %s", key, e)
            db.set_inflt(key, None, tries=tries + 1)
    return changed
