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


def pay_line(trips, doh, period_from, period_to, tax_pct, ca_rules=True):
    """FW-0062: the pay line under another pilot's rebuilt month. trips: the trips the pilot card draws in its grid
    (crewidx.grid_pick), each {pairing, start, end, seat, credit, blk, soft, lay, route, n}. The totals cover the
    trips that start in the bid period (period_from..period_to, ISO), as the card's own totals do; Days Off are the
    bid period's days no drawn trip covers (reserve, training and days off look alike on crew lists). Each trip is
    priced for its own seat (rate_for: CA PWA 3.C.4, FO and RO PWA 3.D.6) on its own start date, for the longevity
    year from doh (doh_year, capped at 12, PWA 3.B.1), with the PWA 4.O.1 overrides and the Extended Range +15% per
    er_on (no per-trip list: that list is Ryan's own). No doh: no amounts. Returns (pay_line, {'PID|start': gross})."""
    tot = [t for t in trips if (t.get("start") or "") >= period_from]
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
    per = {}
    try:
        yr, yr_to = (max(1, min(12, doh_year(doh, d))) for d in (period_from, period_to))
    except (TypeError, ValueError):
        return out, per
    out.update(doh_known=True, doh=doh, year=yr, year_to=yr_to if yr_to != yr else None,
               seat_rates={"CA": rate_for(yr, period_from, "CA"), "FO": rate_for(yr, period_from, "FO")})
    gross = 0.0
    for t in tot:
        cr, bl = hrs(t.get("credit")), hrs(t.get("blk"))
        if cr is None:
            continue
        seat, n, key = (t.get("seat") or "FO").upper(), int(t.get("n") or 0), f"{t.get('pairing')}|{t['start']}"
        lay = t.get("lay") or "/".join(x for x in str(t.get("route") or "").split("-") if x and x != "HNL")
        rate = rate_for(min(12, doh_year(doh, t["start"])), t["start"], seat)
        g = trip_gross(cr, bl, n, lay, key, seat, rate, (), ca_rules=ca_rules)
        per[key] = round(g, 2)
        gross += g
        out["trips_priced"] += 1
        if bl is None and overrides_due(seat, n):
            out["no_block"].append({"pairing": t.get("pairing") or "", "start": t["start"]})
    if out["trips_priced"]:
        out["gross"] = round(gross, 2)
        out["net"] = round(gross * (1 - float(tax_pct or 0) / 100), 2)
    return out, per


def usd(v):
    """'+$1,234' / '-$567' (rounded dollars)."""
    r = round(v)
    return ("+" if r >= 0 else "-") + "${:,}".format(abs(r))
