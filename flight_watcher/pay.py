"""Pay-Gross of a trip, the same rules as the schedule card's tripFull() (1.2.1, Ryan): the Watcher prices the
trips of a decided open time request so the push can say how much Pay-Gross the swap / pickup added or the
drop / swap took away. Pure, no I/O. tests/test_pay.py runs the card's own JavaScript beside this code, so
the two cannot drift apart.

Rules (2023 PWA): credit x the A330 PAX FO hourly rate for the pilot's longevity year (PWA 3.D.6; the
package credit already carries the 5:00 per calendar day minimum, PWA 4.C.3); plus, per PWA 4.O.1, the IRO
override $4.00 per block hour when flying the RO seat, $3.00 per block hour for an FO on a 3-pilot crew, and
the Extended Range +15% for a type-rated FO on a 4-pilot crew or a SIN trip (or as Ryan's per-trip ER list
says: '+KEY' on, '-KEY' off).

FW-0062 (1.4.2, Ryan): another pilot's month rebuilt from crew lines gets a pay line too, priced for the seat that
pilot flew on each trip: a Captain at the PWA 3.C.4 A330 PAX / B787 Captain rate (same effective dates as the FO
table), an FO or RO at the PWA 3.D.6 FO rate, the longevity year from the date of hire (PWA 3.B.1: from the date of
employment as a pilot; both tables stop at year 12). pay_line() totals the trips the pilot card draws."""
import math
import re
from datetime import date, timedelta

IRO_OVERRIDE, ER_PCT, VAC_H = 4.00, 0.15, 4.0
CA_OVERRIDE = 5.00  # PWA 4.O.1.a/b: a Captain on an IRO or Extended Range crew, "under all circumstances"
FO3_OVERRIDE = 3.00  # PWA 4.O.1.a: a First Officer on an IRO crew
RATE_DATES = ["2023-03-02", "2024-03-02", "2025-03-02", "2026-03-02", "2027-01-31"]
RATE_TABLE = [
    [81.00, 84.00, 87.00, 90.00, 93.00], [181.30, 188.55, 196.09, 203.93, 210.05], [208.37, 216.70, 225.37, 234.39, 241.42],
    [221.09, 229.94, 239.13, 248.70, 256.16], [230.29, 239.50, 249.08, 259.04, 266.81], [241.46, 251.12, 261.16, 271.61, 279.76],
    [251.28, 261.33, 271.79, 282.66, 291.13], [256.66, 266.93, 277.61, 288.71, 297.37], [262.48, 272.98, 283.90, 295.26, 304.12],
    [266.03, 276.67, 287.74, 299.24, 308.22], [270.00, 280.80, 292.03, 303.71, 312.82], [273.62, 284.56, 295.95, 307.78, 317.02]]
# PWA 3.C.4 B787 Captain and A330 PAX Captain hourly rate by longevity year (1-12), on the RATE_DATES. Year 1 is a
# real Captain rate: the first-year rate of PWA 3.D.1 is for First Officers only.
RATE_TABLE_CA = [
    [359.68, 374.07, 389.03, 404.59, 416.73], [362.59, 377.09, 392.17, 407.86, 420.10], [365.55, 380.17, 395.38, 411.20, 423.54],
    [368.49, 383.23, 398.56, 414.50, 426.94], [371.43, 386.29, 401.74, 417.81, 430.34], [374.36, 389.33, 404.90, 421.10, 433.73],
    [377.31, 392.40, 408.10, 424.42, 437.15], [380.24, 395.45, 411.27, 427.72, 440.55], [383.19, 398.52, 414.46, 431.04, 443.97],
    [386.11, 401.55, 417.61, 434.31, 447.34], [389.05, 404.61, 420.79, 437.62, 450.75], [392.00, 407.68, 423.99, 440.95, 454.18]]


def rate_for(year, iso, seat="FO"):
    """Hourly rate for longevity year 1..12 (capped) on the date iso (YYYY-MM-DD): the PWA 3.D.6 FO table, or for
    seat 'CA' the PWA 3.C.4 Captain table. An RO (any seat but CA) is paid the FO rate."""
    i = 0
    for k, d in enumerate(RATE_DATES):
        if iso >= d:
            i = k
    table = RATE_TABLE_CA if str(seat or "").strip().upper() == "CA" else RATE_TABLE
    return table[min(12, max(1, int(year))) - 1][i]


def doh_year(doh, iso):
    """Longevity year on the date iso from the date of hire: year 1 from the DOH, and a new year on each anniversary
    of it (PWA 3.B.1 counts from the date of employment; PWA 3.D.2 'completed one (1) year of active service'). The
    schedule card's dohYear() counts the same way (tests/test_pay.py runs both). A Feb 29 DOH turns over on Mar 1 in a
    common year."""
    a, b = date.fromisoformat(doh), date.fromisoformat(iso)
    return b.year - a.year - ((b.month, b.day) < (a.month, a.day)) + 1


def hrs(v):
    """'11h20', '11:20' or a number -> hours (float); None when unreadable."""
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    m = re.match(r"^\s*(\d+)[h:](\d{2})\s*$", str(v))
    return int(m.group(1)) + int(m.group(2)) / 60 if m else None


def crew_n(crew):
    """Pilots on the pairing from the package crew line: CA01FO01RO01 = 3, CA02FO02 = 4. A whole number is the
    count itself (FW-0062: the pilots on a FLICA crew line, crewidx.pilot_trips 'n')."""
    if isinstance(crew, int) and not isinstance(crew, bool):
        return crew
    return sum(int(x) for x in re.findall(r"\d{2}", str(crew or "")))


def er_on(key, lay, n, er_list):
    if "-" + key in er_list:
        return False
    if "+" + key in er_list:
        return True
    return n >= 4 if n else bool(re.search(r"\bSIN\b", lay or ""))


def trip_gross(credit_h, block_h, crew, lay, key, seat, rate, er_list=(), ca_rules=False):
    """The card's tripFull(): None without a credit. ca_rules (FW-0062, the pay line of another pilot's rebuilt
    month): a CA seat is paid as PWA 4.O.1 words it, $5.00 per block hour on any crew of 3 or more pilots (IRO or
    Extended Range, "under all circumstances") and never the type-rated FO's 15%. Off by default, so Ryan's own
    pay and the schedule card's tripFull() stay exactly as they are."""
    if credit_h is None:
        return None
    n = crew_n(crew)
    seat = (seat or "FO").upper()
    if ca_rules and seat == "CA":
        return credit_h * rate + (block_h * CA_OVERRIDE if block_h is not None and n >= 3 else 0.0)
    ov = 0.0
    if block_h is not None:
        ov = block_h * IRO_OVERRIDE if seat == "RO" else (block_h * FO3_OVERRIDE if seat != "CA" and n == 3 else 0.0)
    return credit_h * rate + ov + (credit_h * rate * ER_PCT if er_on(key, lay, n, er_list) else 0.0)


def overrides_due(seat, n):
    """True when PWA 4.O.1 pays this seat a per block hour override on a crew of n pilots, so a trip priced without
    its block is short: RO always, CA on 3 or more (ca_rules), FO on exactly 3."""
    seat = (seat or "FO").upper()
    return seat == "RO" or (seat == "CA" and n >= 3) or (seat not in ("CA", "RO") and n == 3)


def hm(h):
    """Hours -> 'H:MM' (rounded to the minute)."""
    mm = round(h * 60)
    return f"{mm // 60}:{mm % 60:02d}"


def _days(start, end, cap=15):
    """ISO days start..end (at most cap, as the pilot card draws a trip); [] when a date is unreadable."""
    try:
        d, e = date.fromisoformat(start), date.fromisoformat(end or start)
    except (TypeError, ValueError):
        return []
    return [(d + timedelta(days=k)).isoformat() for k in range(cap) if d + timedelta(days=k) <= e]


# ---------------------------------------------------------------- 1.7.11 (FW-0080): totals by bid period
# PWA 4.A: a segment pays on the date it originates, and FLICA totals a bid period, not a calendar month (December 2026
# runs Dec 2 to Dec 31, November Nov 1 to Dec 1). Each duty counts in the bid period that holds its HST departure date;
# its credit is its own TCRD (the pairings package's duty credit) when that is on file, else its block share (an
# estimate). The bid period of the trip's first day keeps the rest of the trip credit (rig, minimums), so the parts of
# one trip always add up to its credit. The schedule card's fwSplit() does the same (tests/test_fw1711_totals.py runs
# both). Ryan, Nov 17, 2026: "Everywhere" (another pilot's month, Ryan's own month and the versions).
def mins(v):
    """'6h39', '6:39' or a whole number of minutes -> minutes; None when unreadable."""
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(round(v))
    m = re.fullmatch(r"\s*(\d{1,3})[h:](\d{2})\s*", str(v or ""))
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def _half_up(x):
    """x rounded to a whole number, halves up (JavaScript's Math.round, so the card and the Watcher agree)."""
    return int(math.floor(x + 0.5))


def duty_dates(st, duties):
    """[(HST departure date ISO, block minutes, TCRD minutes or None)] of the duties that have a numeric dep (HST
    minutes from 00:00 HST of the trip's first day st) and blk, in order; [] when st is not a date."""
    try:
        t0 = date.fromisoformat(str(st))
    except (TypeError, ValueError):
        return []
    out = []
    for d in duties or []:
        if not isinstance(d, dict):
            continue
        dep, blk = d.get("dep"), d.get("blk")
        if isinstance(dep, bool) or isinstance(blk, bool) or not isinstance(dep, (int, float)) or not isinstance(blk, (int, float)):
            continue
        out.append(((t0 + timedelta(days=int(dep // 1440))).isoformat(), int(blk), mins(d.get("tcrd"))))
    return out


def split_by_period(st, duties, period_of, credit=None, blk=None):
    """A trip's credit and block by bid period. period_of(iso) names the bid period of a day; the trip's first day st
    names its home period. credit, blk: the whole trip's (H:MM, hours or None). Block: each period its duties' block
    share of the trip's block, the home period the rest. Credit: each period other than the home one the TCRD of its
    duties when every one of them has it (est False), else their block share (est True); the home period keeps the rest
    (rig and minimums, PWA 4.C.3). None when no duty is placed (the whole trip then pays in its home period). Returns
    {by: {period: {credit, blk}} (minutes, None when the trip's figure is unknown), home, est}."""
    du = duty_dates(st, duties)
    tot_b = sum(b for _d, b, _t in du)
    if not du or tot_b <= 0:
        return None
    home = period_of(str(st))
    keys = [period_of(d) for d, _b, _t in du]
    parts = {}
    for k, (_d, b, t) in zip(keys, du):
        p = parts.setdefault(k, {"b": 0, "t": 0, "tok": True})
        p["b"] += b
        if t is None:
            p["tok"] = False
        else:
            p["t"] += t
    parts.setdefault(home, {"b": 0, "t": 0, "tok": True})
    c_h, b_h = hrs(credit), hrs(blk)
    c_m = int(round(c_h * 60)) if c_h is not None else None
    b_m = int(round(b_h * 60)) if b_h is not None else None
    others = [k for k in parts if k != home]
    est = not all(parts[k]["tok"] for k in others)
    by = {k: {"credit": None, "blk": None} for k in parts}
    if b_m is not None:
        for k in others:
            by[k]["blk"] = _half_up(b_m * parts[k]["b"] / tot_b)
        by[home]["blk"] = max(0, b_m - sum(by[k]["blk"] for k in others))
    if c_m is not None:
        for k in others:
            by[k]["credit"] = min(c_m, _half_up(c_m * parts[k]["b"] / tot_b) if est else parts[k]["t"])
        by[home]["credit"] = max(0, c_m - sum(by[k]["credit"] for k in others))
    return {"by": by, "home": home, "est": est}


def period_share(st, start, end, duties, credit=None, blk=None):
    """FW-0080: a trip's part in the bid period start..end (ISO, both days in it), split_by_period's rule. Returns
    {in: any part of it pays here, whole: all of it does, credit, blk, soft (H:MM, this period's part; '' when the trip's
    figure is unknown), out_credit, out_blk (H:MM, the part paid in another bid period), side ('before' / 'after' / '':
    where that other period lies), est (the credit split by block share: no TCRD on file), placed (False: no duty says
    when, so the whole trip pays in the bid period of its first day)}."""
    def where(iso):
        return "in" if start <= iso <= end else ("before" if iso < start else "after")
    sp = split_by_period(st, duties, where, credit, blk)
    cr_h, bl_h = hrs(credit), hrs(blk)
    full = {"credit": hm(cr_h) if cr_h is not None else "", "blk": hm(bl_h) if bl_h is not None else ""}
    if sp is None:
        here = where(str(st)) == "in"
        side = "" if here else where(str(st))
        return {"in": here, "whole": here, "credit": full["credit"] if here else ("0:00" if cr_h is not None else ""),
                "blk": full["blk"] if here else ("0:00" if bl_h is not None else ""),
                "soft": (hm(max(0.0, cr_h - bl_h)) if here and cr_h is not None and bl_h is not None else ""),
                "out_credit": "" if here else full["credit"], "out_blk": "" if here else full["blk"], "side": side,
                "est": False, "placed": False}
    mine = sp["by"].get("in") or {"credit": 0 if cr_h is not None else None, "blk": 0 if bl_h is not None else None}
    side = next((k for k in sp["by"] if k != "in"), "")
    whole = not side

    def f(m):
        return "" if m is None else hm(m / 60)
    c_in, b_in = mine["credit"], mine["blk"]
    return {"in": "in" in sp["by"], "whole": whole, "credit": f(c_in), "blk": f(b_in),
            "soft": f(max(0, c_in - b_in)) if c_in is not None and b_in is not None else "",
            "out_credit": "" if whole or cr_h is None else hm(cr_h - (c_in or 0) / 60),
            "out_blk": "" if whole or bl_h is None else hm(bl_h - (b_in or 0) / 60),
            "side": side, "est": bool(sp["est"]) and not whole, "placed": True}


def rate_steps(doh, period_from, period_to):
    """1.7.7 review: the days after period_from on which this pilot's hourly rates change inside the period (a DOH
    anniversary: a new longevity year, PWA 3.B.1; or a PWA 3.C.4 / 3.D.6 rate date), each {from, year, CA, FO}; [] when
    the first day's rates hold all period (or a date is unreadable)."""
    try:
        d, e = date.fromisoformat(period_from), date.fromisoformat(period_to)
        prev = (min(12, doh_year(doh, period_from)), sum(1 for x in RATE_DATES if period_from >= x))
    except (TypeError, ValueError):
        return []
    out = []
    for k in range(1, min(62, (e - d).days) + 1):
        iso = (d + timedelta(days=k)).isoformat()
        cur = (min(12, doh_year(doh, iso)), sum(1 for x in RATE_DATES if iso >= x))
        if cur != prev:
            out.append({"from": iso, "year": max(1, cur[0]), "CA": rate_for(cur[0], iso, "CA"), "FO": rate_for(cur[0], iso, "FO")})
            prev = cur
    return out


def pay_line(trips, doh, period_from, period_to, tax_pct, ca_rules=True, vac=(), payp=(), flica_credit=None,
             rate_ok=None, vac_seat="FO"):
    """FW-0062: the pay line under another pilot's rebuilt month. trips: the trips the pilot card draws in its grid
    (crewidx.grid_pick), each {pairing, start, end, seat, credit, blk, soft, lay, route, n}. The totals cover the
    trips that start in the bid period (period_from..period_to, ISO), as the card's own totals do; Days Off are the
    bid period's days no drawn trip covers (reserve, training and days off look alike on crew lists). Each trip is
    priced for its own seat (rate_for: CA PWA 3.C.4, FO and RO PWA 3.D.6) on its own start date, for the longevity
    year from doh (doh_year, capped at 12, PWA 3.B.1), with the PWA 4.O.1 overrides and the Extended Range +15% per
    er_on (no per-trip list: that list is Ryan's own). No doh: no amounts. Returns (pay_line, {'PID|start': gross}).
    1.7.7 review (a month FLICA showed, or a version of it; the schedule card's rules): plus vac (ISO days of vacation
    in the bid period, PWA 6.J.1.c: VAC_H credit a day at the vac_seat rate) and payp (the PAYP days, PWA Definitions
    57): their credit is FLICA's month credit (flica_credit, hours) less everything else counted, an estimate, when that
    leaves some and every trip has its credit; else unknown, not counted. rate_ok(seat): False for a seat whose rates
    are not on file (another fleet): its trips are not priced (no_rate). rate_steps: the days the rates change inside
    the period (rate_steps()). 1.7.11 (FW-0080, PWA 4.A): the bid period, never the calendar month: a trip with
    in_period (period_share: its credit and block already its part in the bid period) counts when that is True, so a
    trip from the bid period before counts the duties it flies in this one; any other trip counts when it starts in the
    bid period."""
    tot = [t for t in trips if (bool(t["in_period"]) if "in_period" in t
                                else period_from <= (t.get("start") or "") <= period_to)]
    covered = {d for t in trips for d in _days(t.get("start"), t.get("end"))}
    period = _days(period_from, period_to, cap=62)
    sums = {"credit": [0.0, 0], "blk": [0.0, 0], "soft": [0.0, 0]}
    for t in tot:
        for k, v in sums.items():
            h = hrs(t.get(k))
            if h is not None:
                v[0] += h
                v[1] += 1
    out = {"doh_known": False, "doh": "", "year": None, "year_to": None, "seat_rates": {},
           "seats": sorted({(t.get("seat") or "FO").upper() for t in tot}), "trips": len(tot), "trips_priced": 0,
           "credit": hm(sums["credit"][0]), "credit_n": sums["credit"][1], "block": hm(sums["blk"][0]),
           "block_n": sums["blk"][1], "soft": hm(sums["soft"][0]), "soft_n": sums["soft"][1], "gross": None,
           "net": None, "tax_pct": tax_pct, "days_off": sum(1 for d in period if d not in covered) if period else None,
           "missing": [{"pairing": t.get("pairing") or "", "start": t.get("start") or ""}
                       for t in tot if hrs(t.get("credit")) is None], "no_block": []}
    ok = rate_ok or (lambda seat: True)
    vac = sorted(set(vac or ()))
    # the vacation days and the PAYP's credit (the schedule card's Vacation and PAYP groups), inside Credit
    if vac:
        out["vac_days"], out["vac"] = len(vac), hm(len(vac) * VAC_H)
    pp_h = None
    if payp:
        counted = sums["credit"][0] + len(vac) * VAC_H
        if flica_credit is not None and not out["missing"] and flica_credit - counted > 1 / 120:
            pp_h = round((flica_credit - counted) * 60) / 60
            out.update(payp=hm(pp_h), payp_est=True)
        else:
            out["payp_unk"] = True
    if vac or pp_h:
        out["credit"] = hm(sums["credit"][0] + len(vac) * VAC_H + (pp_h or 0))
    per = {}
    try:
        yr, yr_to = (max(1, min(12, doh_year(doh, d))) for d in (period_from, period_to))
    except (TypeError, ValueError):
        return out, per
    seats_ok = [s for s in ("CA", "FO") if ok(s)]
    out.update(doh_known=True, doh=doh, year=yr, year_to=yr_to if yr_to != yr else None,
               seat_rates={s: rate_for(yr, period_from, s) for s in seats_ok},
               rate_steps=[{k: v for k, v in r.items() if k in ("from", "year") or k in seats_ok}
                           for r in rate_steps(doh, period_from, period_to)])
    if not out["rate_steps"]:
        out.pop("rate_steps")
    gross = 0.0
    vs = (vac_seat or "FO").upper()
    for d in vac if ok(vs) else ():
        gross += VAC_H * rate_for(min(12, doh_year(doh, d)), d, vs)
    if pp_h and ok(vs):
        d0 = min(str(p.get("start") or period_from) for p in payp)
        gross += pp_h * rate_for(min(12, doh_year(doh, d0)), d0, vs)
    if (vac or pp_h) and not ok(vs):
        out.setdefault("no_rate", []).append({"pairing": "VAC" if vac else "PAYP", "start": (vac or [period_from])[0], "seat": vs})
    for t in tot:
        cr, bl = hrs(t.get("credit")), hrs(t.get("blk"))
        if cr is None:
            continue
        seat, n, key = (t.get("seat") or "FO").upper(), int(t.get("n") or 0), f"{t.get('pairing')}|{t['start']}"
        if not ok(seat):
            out.setdefault("no_rate", []).append({"pairing": t.get("pairing") or "", "start": t["start"], "seat": seat})
            continue
        lay = t.get("lay") or "/".join(x for x in str(t.get("route") or "").split("-") if x and x != "HNL")
        rate = rate_for(min(12, doh_year(doh, t["start"])), t["start"], seat)
        g = trip_gross(cr, bl, n, lay, key, seat, rate, (), ca_rules=ca_rules)
        per[key] = round(g, 2)
        gross += g
        out["trips_priced"] += 1
        if bl is None and overrides_due(seat, n):
            out["no_block"].append({"pairing": t.get("pairing") or "", "start": t["start"]})
    if out["trips_priced"] or (gross and (vac or pp_h)):
        out["gross"] = round(gross, 2)
        out["net"] = round(gross * (1 - float(tax_pct or 0) / 100), 2)
    return out, per


def usd(v):
    """'+$1,234' / '-$567' (rounded dollars)."""
    r = round(v)
    return ("+" if r >= 0 else "-") + "${:,}".format(abs(r))
