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

from pot import CM_PAIR_RE, classify, inflight_at, parse_legs, visible_text

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
    items = []
    for k, (d, code, lay) in enumerate(days):
        if not code:
            continue
        if not re.match(r"^[A-Z]\d{4}[A-Z]?$", code):
            if items and items[-1]["trip"] == code and items[-1]["_k"] == k - 1:
                items[-1].update(end=d, _k=k)
            else:
                items.append({"trip": code, "start": d, "end": d, "lay": "", "_k": k})
            continue
        end = d
        for j in range(k + 1, min(k + 8, len(days))):
            if days[j][1]:
                break
            if days[j][2] == "HNL":
                end = days[j][0]
                break
        items.append({"trip": code, "start": d, "end": end, "lay": lay if lay not in ("-", "") else "", "_k": k})
    for it in items:
        it.pop("_k", None)
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


CM_SCHED = "{base}/full/cmschedules.cgi?GO=1&SchBrowser=1&Prompt=1&EmployeeID={emp}"
CM_SCHED_MONTH = "{base}/full/cmschedules.cgi?Prompt=1&EmployeeID={emp}&bd={bd}&SchBrowser=1"
PROBE = {"logged": 0}
RESET_V = 5  # bump when the parser changes so stored verdicts are re-checked once


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
    changed_early = False
    if db.get("score_email_v") != 1:  # 0.5.6 one-shot: score the email-caught pickups recorded before 0.5.6
        for k in db.unscored_pickups():
            if db.score_pickup(k) is not None:
                changed_early = True
        db.put("score_email_v", 1)
    if db.get("inflt_reset_v") != RESET_V:  # verdicts from an older parser are looked up again, once
        db.reset_inflt()
        db.put("inflt_reset_v", RESET_V)
    todo = db.pickups_without_inflt(50)
    if not todo:
        return changed_early
    cur = local_now()
    cur_bd = f"{cur.month:02d}{cur.year % 100:02d}"
    cache, n, changed = {}, 0, changed_early
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
