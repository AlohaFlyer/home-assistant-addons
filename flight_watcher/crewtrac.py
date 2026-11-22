"""1.7.22 (Hark, Ryan Nov 20, 2026, option 1): the CrewTrac per-trip pay check. CrewTrac (CTWeb, Sabre) is the
controlling schedule, so each own trip's credit and block in FW is checked against it. Hark reads CrewTrac once a day
(read only, Schedule Detail CT5660 and Pay Report CT8840) and hands FW a snapshot; FW never holds a CrewTrac login
for this.

Snapshot hand-off: Hark posts the snapshot JSON as the attributes of sensor.flight_watcher_crewtrac_snapshot (HA REST
POST /api/states, state = pulled_at). The Watcher reads it (ha_state_full), keeps a copy in
/share/flight_watcher/crewtrac_snapshot.json (so an HA restart, which drops a REST-posted state, loses nothing), and
publishes sensor.flight_watcher_crewtrac_check (MQTT) with the snapshot and its own compare. The schedule card shows
the compare in each trip's Pay tooltip and the month line.

Pure, no I/O. Parsers (parse_schedule_detail, parse_pay_report) read the reports as plain text laid out the way
pdftotext -layout prints the report's printer friendly PDF. build_snapshot makes the snapshot; compare_trips checks FW's
figures against it.

Snapshot schema (version 1):
{version: 1, pulled_at: ISO with zone, source: {schedule_detail, pay_report, how},
 months: {"YYYY-MM": {period: "MMYY", bid: "HNL 332 FO", trips: ["PID|start", ...], codes: [{date, code, from, to,
          tcrd}], pay_report: {as_of, totals: {flt, pay, credit, actual}, rows: [{active, zulu, eqp, pos, flt, fr, to,
          code, flt_h, pay, credit, actual}]} | null}},
 trips: [{pairing, key (first 5 chars), start, end, seat, legs: [{date, flt, fr, to, dep, arr, dh}],
          duties: [{date, day, blkt, tcrd, rel}], block, tcrd, min_guar, credit, pay_report_credit, codes, months}]}
All hours are 'H:MM'. A trip's credit is the sum of its duty days' TCRD (Schedule Detail) plus the Pay Report's
minimum guarantee rows (MF*, the trip rig / MDG top up) dated inside the trip."""
import re
from datetime import date, datetime, timedelta, timezone

VERSION = 1
STALE_H = 36
MON = {m: i + 1 for i, m in enumerate("JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split())}
TRIP_RE = re.compile(r"^(H\d{4}[A-Z]?)\s*/(\d{2})(\d{2}) POS (\w{2}) DAY (\d{2}) REPORT (\d{4})")
LEG_RE = re.compile(r"^(\w{3,4}) ([A-Z]{3}) ([A-Z]{3}) (\d{4}) (\d{4})(\s+DHD)?\b")
DEND_RE = re.compile(r"^D-END (\d{4})(?:/(\d{2}))?\s+BLKT (\d{4}) TCRD (\d{4})")
CODE_RE = re.compile(r"^([A-Z][A-Z0-9/]{1,4})(?:\s+(\d{4})\s+(\d{4}))?(?:\s+TCRD (\d{4}))?\s*$")
DAY_RE = re.compile(r"^(\d{2}) ([A-Z]{3})\b\s*(.*)$")
HM_RE = re.compile(r"^\d{1,3}:\d{2}$")


def m_of(v):
    """'13:30', '1330' (HHMM) or minutes -> minutes; None when unreadable."""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, int):
        return v
    s = str(v).strip()
    m = re.fullmatch(r"(\d{1,3}):(\d{2})", s) or re.fullmatch(r"(\d{2})(\d{2})", s)
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def hm(n):
    """Minutes -> 'H:MM' ('-H:MM' below zero)."""
    if n is None:
        return ""
    s = "-" if n < 0 else ""
    n = abs(int(n))
    return f"{s}{n // 60}:{n % 60:02d}"


def _year_for(mon, pmon, pyear):
    if mon - pmon > 6:
        return pyear - 1
    if pmon - mon > 6:
        return pyear + 1
    return pyear


def _strip(line):
    return re.sub(r"\s*Copyright \(c\).*$", "", line.rstrip("\n"))


def parse_schedule_detail(text):
    """The Schedule Detail report (CT5660) of one bid period: {period, month 'YYYY-MM', bid, duties: [{pairing, start,
    seat, day, date, report, legs, rel, rel_day, blkt, tcrd}], codes: [{date, code, from, to, tcrd}]}. The report is
    printed in two columns; each column is read top to bottom, left column first. None when no PERIOD line."""
    lines = [_strip(x) for x in str(text or "").splitlines()]
    pm = next((re.search(r"PERIOD (\d{2})(\d{2})", x) for x in lines if re.search(r"PERIOD \d{4}", x)), None)
    if not pm:
        return None
    pmon, pyear = int(pm.group(1)), 2000 + int(pm.group(2))
    bm = next((re.search(r"\bBID (.+?)\s*$", x) for x in lines if re.search(r"SEN# \d+ BID ", x)), None)
    i0 = next((i for i, x in enumerate(lines) if "TIMES ARE IN LOCAL" in x), -1) + 1
    body = lines[i0:]
    split = min((m.start(1) for x in body for m in [re.search(r"\S.*?(\b\d{2} [A-Z]{3} )", x)] if m and m.start(1) > 40),
                default=None)
    cols = [[x[:split].rstrip() for x in body], [x[split:] for x in body]] if split else [body]
    out = {"period": f"{pmon:02d}{pyear % 100:02d}", "month": f"{pyear}-{pmon:02d}", "bid": bm.group(1) if bm else "",
           "duties": [], "codes": []}
    for col in cols:
        cur, duty = None, None
        for raw in col:
            s = raw.strip()
            if not s:
                continue
            dm = DAY_RE.match(s)
            if dm and dm.group(2) in MON:
                mon = MON[dm.group(2)]
                cur = date(_year_for(mon, pmon, pyear), mon, int(dm.group(1))).isoformat()
                s = dm.group(3).strip()
                duty = None
                if not s:
                    continue
            if cur is None:
                continue
            tm = TRIP_RE.match(s)
            if tm:
                smon, sday = int(tm.group(2)), int(tm.group(3))
                cy = int(cur[:4])
                st = date(cy if smon <= int(cur[5:7]) else cy - 1, smon, sday).isoformat()
                duty = {"pairing": tm.group(1), "start": st, "seat": tm.group(4), "day": int(tm.group(5)), "date": cur,
                        "report": tm.group(6), "legs": [], "rel": None, "rel_day": None, "blkt": None, "tcrd": None}
                out["duties"].append(duty)
                continue
            lm = LEG_RE.match(s)
            if lm and duty is not None:
                duty["legs"].append({"date": cur, "flt": lm.group(1), "fr": lm.group(2), "to": lm.group(3),
                                     "dep": lm.group(4), "arr": lm.group(5), "dh": bool(lm.group(6))})
                continue
            em = DEND_RE.match(s)
            if em and duty is not None:
                duty.update(rel=em.group(1), rel_day=int(em.group(2)) if em.group(2) else None,
                            blkt=hm(m_of(em.group(3))), tcrd=hm(m_of(em.group(4))))
                continue
            if s.startswith(("TDTY", "PAIRING ")) or re.search(r"\(\d{3}\)", s):
                continue
            cm = CODE_RE.match(s)
            if cm and not s.startswith("D-END"):
                duty = None
                out["codes"].append({"date": cur, "code": cm.group(1), "from": cm.group(2) or "", "to": cm.group(3) or "",
                                     "tcrd": hm(m_of(cm.group(4))) if cm.group(4) else ""})
    out["duties"].sort(key=lambda d: (d["date"], d["day"]))
    out["codes"].sort(key=lambda c: c["date"])
    return out


def _cols(header):
    """Column ends of the Pay Report's hour columns from its second header line (after CODE): flt, pay, credit,
    act_credit, actual."""
    i = header.find("CODE")
    if i < 0:
        return None
    ends = [m.end() + i for m in re.finditer(r"HOURS|CREDIT", header[i:])][:5]
    return dict(zip(("flt_h", "pay", "credit", "act_credit", "actual"), ends)) if len(ends) == 5 else None


ROW_RE = re.compile(r"^\s+(\d{2})/(\d{2})/(\d{2})\s+(\d{3})\s+(\w{2})\s+(\d{2})/(\d{2})/(\d{2})\s+(.*)$")


def _iso(mm, dd, yy):
    return date(2000 + int(yy), int(mm), int(dd)).isoformat()


def _place(line, cols):
    """{column: minutes} of the H:MM values of a row, each to the hour column whose header ends nearest its end;
    values more than 8 characters from every one (duty hours) are left out."""
    got = {}
    for m in re.finditer(r"(?<![\d/:])\d{1,3}:\d{2}(?![\d/])", line):
        k, gap = min(((k, abs(m.end() - e)) for k, e in cols.items()), key=lambda x: x[1])
        if gap <= 8 and k not in got:
            got[k] = m_of(m.group(0))
    return got


def parse_pay_report(text):
    """The Pay Report (CT8840, 'Daily Flight Crew Activity') of one bid period: {as_of, rows, totals} (minutes).
    None when no header was found."""
    cols, rows, totals, as_of = None, [], None, None
    for raw in str(text or "").splitlines():
        line = _strip(raw)
        am = re.search(r"As Of (\d{2})/(\d{2})/(\d{2})", line)
        if am:
            as_of = _iso(*am.groups())
        if "CODE" in line and "HOURS" in line:
            cols = _cols(line) or cols
            continue
        if cols is None:
            continue
        if "EMPLOYEE TOTALS" in line:
            totals = _place(line, cols)
            continue
        rm = ROW_RE.match(line)
        if not rm:
            continue
        rest = rm.group(9)
        fm = re.match(r"(\S{2,4})\s+([A-Z]{3})\s+([A-Z]{3})\s+([A-Z0-9]{3})\b", rest)
        cm = fm or re.match(r"([A-Z][A-Z0-9]{2})\b", rest)
        if not cm:
            continue
        r = {"active": _iso(*rm.group(1, 2, 3)), "eqp": rm.group(4), "pos": rm.group(5), "zulu": _iso(*rm.group(6, 7, 8)),
             "flt": fm.group(1) if fm else "", "fr": fm.group(2) if fm else "", "to": fm.group(3) if fm else "",
             "code": fm.group(4) if fm else cm.group(1)}
        r.update(_place(line, cols))
        rows.append(r)
    if cols is None:
        return None
    tot = {k: hm(v) for k, v in (totals or {}).items() if k in ("flt_h", "pay", "credit", "actual")}
    sums = {k: sum(r.get(k) or 0 for r in rows) for k in ("flt_h", "pay", "credit", "actual")}
    return {"as_of": as_of, "totals": tot, "sums": {k: hm(v) for k, v in sums.items()},
            "rows": [{k: (hm(v) if k in ("flt_h", "pay", "credit", "act_credit", "actual") else v) for k, v in r.items()}
                     for r in rows]}


def _trip_row(r):
    """A Pay Report row that belongs to a trip: a flight (or a protected / deadhead segment, FLT# FR TO) or a minimum
    guarantee (MF*). Never a code day (VAC VC*, PAYP NF5, sick SK*, sim SM*, ground school GS*, PAY)."""
    return bool(r.get("fr")) or str(r.get("code") or "").startswith("MF")


def build_snapshot(details, pays, pulled_at, source=None):
    """details: parse_schedule_detail results (any months, in any order); pays: parse_pay_report results by month
    ('YYYY-MM': report). The snapshot (schema in the module doc)."""
    trips, months = {}, {}
    for sd in [d for d in details if d]:
        mo = months.setdefault(sd["month"], {"period": sd["period"], "bid": sd["bid"], "trips": [], "codes": sd["codes"],
                                             "pay_report": None})
        for du in sd["duties"]:
            k = f"{du['pairing']}|{du['start']}"
            t = trips.setdefault(k, {"pairing": du["pairing"], "key": du["pairing"][:5], "start": du["start"],
                                     "seat": du["seat"], "legs": [], "duties": [], "months": []})
            if any(x["date"] == du["date"] and x["day"] == du["day"] for x in t["duties"]):
                continue
            t["legs"] += du["legs"]
            t["duties"].append({k2: du[k2] for k2 in ("date", "day", "report", "rel", "rel_day", "blkt", "tcrd")})
            if sd["month"] not in t["months"]:
                t["months"].append(sd["month"])
            if k not in mo["trips"]:
                mo["trips"].append(k)
    for mk, pr in (pays or {}).items():
        if pr:
            months.setdefault(mk, {"period": f"{mk[5:7]}{mk[2:4]}", "bid": "", "trips": [], "codes": [],
                                   "pay_report": None})["pay_report"] = pr
    prow = [r for pr in (pays or {}).values() if pr for r in pr["rows"]]
    out = []
    for k, t in sorted(trips.items(), key=lambda x: (x[1]["start"], x[0])):
        t["duties"].sort(key=lambda x: (x["date"], x["day"]))
        last = t["duties"][-1]
        end = date.fromisoformat(last["date"])
        if last.get("rel_day") and last["rel_day"] != end.day:
            end = end + timedelta(days=1)
        t["end"] = end.isoformat()
        tc = [m_of(x["tcrd"]) for x in t["duties"]]
        bl = [m_of(x["blkt"]) for x in t["duties"]]
        inside = [r for r in prow if t["start"] <= r["active"] <= t["end"] and _trip_row(r)]
        mg = sum(m_of(r.get("credit")) or 0 for r in inside if str(r["code"]).startswith("MF"))
        t["tcrd"] = hm(sum(tc)) if None not in tc else ""
        t["block"] = hm(sum(bl)) if None not in bl else ""
        t["min_guar"] = hm(mg)
        t["credit"] = hm(sum(tc) + mg) if None not in tc else ""
        # a trip not flown yet: CrewTrac posts its minimum guarantee (MF*) only after it, so its credit is projected
        # as the greater of the TCRD and the MDG, 5:00 x the calendar days it touches (PWA 4.C.3.a), and marked
        days = (end - date.fromisoformat(t["start"])).days + 1
        if not mg and None not in tc and t["end"] >= str(pulled_at or "")[:10] and 300 * days > sum(tc):
            t["credit"], t["projected"] = hm(300 * days), f"TCRD {t['tcrd']} + MDG to {hm(300 * days)} (posts after the trip)"
        t["pay_report_credit"] = hm(sum(m_of(r.get("credit")) or 0 for r in inside)) if inside else ""
        t["codes"] = sorted({r["code"] for r in inside} | {"DHD" for x in t["legs"] if x.get("dh")})
        out.append(t)
    return {"version": VERSION, "pulled_at": pulled_at, "source": source or {}, "months": months, "trips": out}


def compact(snap):
    """The snapshot as handed to HA (under the recorder's 16 KB): every trip with its legs as 'FLT FR-TO' strings and
    its duties' date, TCRD and BLKT; each month's bid line, credit codes (VAC, PAYP, SICK... with a TCRD) and Pay Report
    totals. The Pay Report rows stay in the full copy Hark keeps."""
    out = {k: snap.get(k) for k in ("version", "pulled_at", "source")}
    out["months"] = {mk: {"period": m.get("period"), "bid": m.get("bid"), "trips": m.get("trips"),
                          "codes": [c for c in m.get("codes") or [] if c.get("tcrd") not in ("", "0:00")],
                          "pay_report": ({"as_of": m["pay_report"].get("as_of"), "totals": m["pay_report"].get("totals")}
                                         if m.get("pay_report") else None)}
                     for mk, m in (snap.get("months") or {}).items()}
    out["trips"] = [{**{k: v for k, v in t.items() if k not in ("legs", "duties")},
                     "legs": [x if isinstance(x, str) else f"{x['flt']}{' DH' if x.get('dh') else ''} {x['fr']}-{x['to']} {x['date'][5:]}"
                              for x in t.get("legs") or []],
                     "duties": [{k: d.get(k) for k in ("date", "blkt", "tcrd")} for d in t.get("duties") or []]}
                    for t in snap.get("trips") or []]
    return out


def card_view(snap):
    """What the schedule card and the check sensor need (a few KB): pulled_at, each trip's id, days, credit, block
    and projection, each month's Pay Report as_of and totals."""
    return {"version": (snap or {}).get("version"), "pulled_at": (snap or {}).get("pulled_at"),
            "months": {mk: {"pay_report": ({"as_of": m["pay_report"].get("as_of"), "totals": m["pay_report"].get("totals")}
                                           if m.get("pay_report") else None)}
                       for mk, m in ((snap or {}).get("months") or {}).items()},
            "trips": [_card_trip(t) for t in (snap or {}).get("trips") or []]}


def _card_trip(t):
    """One trip of card_view. 1.7.25: 'prot', CrewTrac's protected NF2 credit of a broken duty (pay.ct_protected), so
    the card reads ALPA DART 417120's rule from CrewTrac."""
    out = {k: t.get(k) for k in ("pairing", "key", "start", "end", "credit", "block", "projected") if t.get(k)}
    try:
        import pay as PAY  # noqa: PLC0415 (pay is pure; imported here so crewtrac stays importable on its own)
        p = PAY.ct_protected(t)
    except ImportError:
        p = None
    if p:
        out["prot"] = f"{p // 60}:{p % 60:02d}"
    return out


# ---------------------------------------------------------------- the compare (the schedule card's fwCtCompare)
def age_h(snap, now):
    """Hours since the snapshot was pulled (now: an aware datetime); None when unreadable."""
    try:
        t = datetime.fromisoformat(str((snap or {}).get("pulled_at")))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return (now - t).total_seconds() / 3600


def snap_status(snap, now):
    """('ok' | 'missing' | 'stale', age in hours or None)."""
    if not snap or not isinstance(snap.get("trips"), list):
        return "missing", None
    a = age_h(snap, now)
    if a is None or a > STALE_H:
        return "stale", a
    return "ok", a


def find_trip(snap, pid, start):
    """The snapshot trip of FW's trip pid (FLICA's id: H3606A) starting start: the same first five characters (CrewTrac
    may letter it differently, H3606B) on the same first day, else one day either side (FLICA and CrewTrac can date a
    late evening report differently). None when CrewTrac has no such trip."""
    key = str(pid or "")[:5]
    cand = [t for t in (snap or {}).get("trips") or [] if t.get("key") == key]
    for d in (0, -1, 1):
        try:
            iso = (date.fromisoformat(str(start)) + timedelta(days=d)).isoformat()
        except ValueError:
            return None
        hit = next((t for t in cand if t.get("start") == iso), None)
        if hit:
            return hit
    return None


def compare_trip(ct, fw_credit, fw_blk):
    """One trip: {ct_credit, fw_credit, d_credit, ct_blk, fw_blk, d_blk, ok, line}. A difference of 0:01 or more in
    credit or block is a mismatch; CrewTrac controls."""
    cc, fc = m_of((ct or {}).get("credit")), m_of(fw_credit)
    cb, fb = m_of((ct or {}).get("block")), m_of(fw_blk)
    dc = fc - cc if fc is not None and cc is not None else None
    db = fb - cb if fb is not None and cb is not None else None
    ok = (dc is None or dc == 0) and (db is None or db == 0) and cc is not None
    return {"ct_credit": hm(cc), "fw_credit": hm(fc), "d_credit": dc, "ct_blk": hm(cb), "fw_blk": hm(fb), "d_blk": db,
            "ok": ok, "line": trip_line(cc, fc, cb, fb)}


def _d(n):
    return ("+" if n > 0 else "-") + hm(abs(n))


def trip_line(cc, fc, cb, fb):
    """The tooltip line: 'CrewTrac 21:09, FW 21:09 ✓' or the difference (FW minus CrewTrac)."""
    if cc is None:
        return "CrewTrac: no credit for this trip in the snapshot"
    s = f"CrewTrac {hm(cc)}, FW {hm(fc) if fc is not None else '?'}"
    bad = []
    if fc is not None and fc != cc:
        bad.append(f"credit off by {_d(fc - cc)}")
    if cb is not None and fb is not None and fb != cb:
        bad.append(f"block CrewTrac {hm(cb)}, FW {hm(fb)} ({_d(fb - cb)})")
    return s + (" \u2713" if not bad else " \u2717 " + "; ".join(bad) + " (CrewTrac controls)")


def month_line(snap, month, fw_credit):
    """'CrewTrac Pay Report 163:34, FW 152:24 ✗ off by -11:10 (CrewTrac controls)'; '' with no Pay Report."""
    pr = (((snap or {}).get("months") or {}).get(month) or {}).get("pay_report") or {}
    cc, fc = m_of((pr.get("totals") or {}).get("credit")), m_of(fw_credit)
    if cc is None:
        return ""
    s = f"CrewTrac Pay Report {hm(cc)} credit (as of {pr.get('as_of') or '?'}), FW {hm(fc) if fc is not None else '?'}"
    return s + (" \u2713" if fc == cc else (f" \u2717 off by {_d(fc - cc)} (CrewTrac controls)" if fc is not None else ""))


def not_compared(status, age):
    """The line when there is nothing current to compare with."""
    if status == "missing":
        return "CrewTrac not compared (snapshot missing)"
    return f"CrewTrac not compared (snapshot {round(age)} h old)" if age is not None else "CrewTrac not compared (snapshot unreadable)"


def compare_trips(snap, fw_trips, now):
    """FW's own trips ({'PID|start': {credit, blk}}) against the snapshot: {status, age_h, rows: [{trip, start,
    ct_pairing, ...compare_trip}], mismatches}. Trips CrewTrac does not list (outside the months pulled) are left
    out; a trip in the months pulled that CrewTrac lacks is a mismatch (ct_credit '')."""
    st, age = snap_status(snap, now)
    out = {"status": st, "age_h": round(age, 1) if age is not None else None, "rows": [], "mismatches": 0}
    if st != "ok":
        out["line"] = not_compared(st, age)
        return out
    months = set((snap.get("months") or {}).keys())
    for k, t in sorted((fw_trips or {}).items(), key=lambda x: x[0].split("|")[-1]):
        pid, _, start = k.partition("|")
        if not re.fullmatch(r"H\d{4}\w?", pid) or start[:7] not in months:
            continue
        ct = find_trip(snap, pid, start)
        row = {"trip": pid, "start": start, "ct_pairing": (ct or {}).get("pairing", ""), "ct_start": (ct or {}).get("start", "")}
        row.update(compare_trip(ct, (t or {}).get("credit"), (t or {}).get("blk")))
        if not ct:
            row["line"] = f"CrewTrac has no {pid} on {start} \u2717 (CrewTrac controls)"
        out["rows"].append(row)
        out["mismatches"] += 0 if row["ok"] else 1
    return out


def _read(path):
    """A report's text: a .pdf through pdftotext -layout (the printer friendly PDF), else the file as text."""
    if str(path).lower().endswith(".pdf"):
        import subprocess
        return subprocess.run(["pdftotext", "-layout", path, "-"], capture_output=True, text=True, check=True).stdout
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def main(argv=None):
    """Hark's daily run (not the Watcher): crewtrac.py --pulled-at ISO --sched A.pdf B.pdf --pay 2026-11=P.pdf
    --out full.json --compact compact.json. Prints a one-line summary; exits 2 when a report did not parse."""
    import argparse
    import json
    import sys
    ap = argparse.ArgumentParser()
    ap.add_argument("--pulled-at", required=True)
    ap.add_argument("--sched", nargs="+", default=[])
    ap.add_argument("--pay", nargs="*", default=[], help="YYYY-MM=path")
    ap.add_argument("--out", required=True)
    ap.add_argument("--compact", required=True)
    a = ap.parse_args(argv)
    det = [parse_schedule_detail(_read(p)) for p in a.sched]
    pays = {}
    for x in a.pay:
        mk, _, p = x.partition("=")
        pays[mk] = parse_pay_report(_read(p))
    bad = [p for p, d in zip(a.sched, det) if not d] + [x for x in a.pay if not pays[x.partition("=")[0]]]
    off = [mk for mk, pr in pays.items() if pr and pr["totals"].get("credit") != pr["sums"].get("credit")]
    src = {"schedule_detail": "https://ctweb.hawaiianair.com/Pilot/ctwrpform.aspx?RID=CT5660",
           "pay_report": "https://ctweb.hawaiianair.com/Pilot/ctwrpform.aspx?RID=CT8840",
           "how": "Hark daily read (read only), printer friendly PDFs through pdftotext -layout"}
    snap = build_snapshot(det, pays, a.pulled_at, src)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(snap, f, indent=1)
    with open(a.compact, "w", encoding="utf-8") as f:
        json.dump(compact(snap), f, separators=(",", ":"))
    print(json.dumps({"trips": len(snap["trips"]), "months": sorted(snap["months"]), "unparsed": bad,
                      "pay_rows_not_adding_up": off}))
    return 2 if bad or off else 0


if __name__ == "__main__":
    raise SystemExit(main())
