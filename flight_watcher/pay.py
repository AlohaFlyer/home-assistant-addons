"""Pay-Gross of a trip, the same rules as the schedule card's tripFull() (1.2.1, Ryan): the Watcher prices the
trips of a decided open time request so the push can say how much Pay-Gross the swap / pickup added or the
drop / swap took away. Pure, no I/O. tests/test_pay.py runs the card's own JavaScript beside this code, so
the two cannot drift apart.

Rules (2023 PWA): credit x the A330 PAX FO hourly rate for the pilot's longevity year (PWA 3.D.6; the
package credit already carries the 5:00 per calendar day minimum, PWA 4.C.3); plus, per PWA 4.O.1, the IRO
override $4.00 per block hour when flying the RO seat, $3.00 per block hour for an FO on a 3-pilot crew, and
the Extended Range +15% for a type-rated FO on a 4-pilot crew or a SIN trip (or as Ryan's per-trip ER list
says: '+KEY' on, '-KEY' off)."""
import re
from datetime import date

IRO_OVERRIDE, ER_PCT, VAC_H = 4.00, 0.15, 4.0
RATE_DATES = ["2023-03-02", "2024-03-02", "2025-03-02", "2026-03-02", "2027-01-31"]
RATE_TABLE = [
    [81.00, 84.00, 87.00, 90.00, 93.00], [181.30, 188.55, 196.09, 203.93, 210.05], [208.37, 216.70, 225.37, 234.39, 241.42],
    [221.09, 229.94, 239.13, 248.70, 256.16], [230.29, 239.50, 249.08, 259.04, 266.81], [241.46, 251.12, 261.16, 271.61, 279.76],
    [251.28, 261.33, 271.79, 282.66, 291.13], [256.66, 266.93, 277.61, 288.71, 297.37], [262.48, 272.98, 283.90, 295.26, 304.12],
    [266.03, 276.67, 287.74, 299.24, 308.22], [270.00, 280.80, 292.03, 303.71, 312.82], [273.62, 284.56, 295.95, 307.78, 317.02]]


def rate_for(year, iso):
    """PWA 3.D.6 FO hourly rate for longevity year 1..12 (capped) on the date iso (YYYY-MM-DD)."""
    i = 0
    for k, d in enumerate(RATE_DATES):
        if iso >= d:
            i = k
    return RATE_TABLE[min(12, max(1, int(year))) - 1][i]


def doh_year(doh, iso):
    """Longevity year from the date of hire, as the card counts it (365.25-day years, year 1 from the DOH)."""
    a, b = date.fromisoformat(doh), date.fromisoformat(iso)
    return int((b - a).days // 365.25) + 1


def hrs(v):
    """'11h20', '11:20' or a number -> hours (float); None when unreadable."""
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    m = re.match(r"^\s*(\d+)[h:](\d{2})\s*$", str(v))
    return int(m.group(1)) + int(m.group(2)) / 60 if m else None


def crew_n(crew):
    """Pilots on the pairing from the package crew line: CA01FO01RO01 = 3, CA02FO02 = 4."""
    return sum(int(x) for x in re.findall(r"\d{2}", str(crew or "")))


def er_on(key, lay, n, er_list):
    if "-" + key in er_list:
        return False
    if "+" + key in er_list:
        return True
    return n >= 4 if n else bool(re.search(r"\bSIN\b", lay or ""))


def trip_gross(credit_h, block_h, crew, lay, key, seat, rate, er_list=()):
    """The card's tripFull(): None without a credit."""
    if credit_h is None:
        return None
    n = crew_n(crew)
    seat = (seat or "FO").upper()
    ov = 0.0
    if block_h is not None:
        ov = block_h * IRO_OVERRIDE if seat == "RO" else (block_h * 3.00 if seat != "CA" and n == 3 else 0.0)
    return credit_h * rate + ov + (credit_h * rate * ER_PCT if er_on(key, lay, n, er_list) else 0.0)


def usd(v):
    """'+$1,234' / '-$567' (rounded dollars)."""
    r = round(v)
    return ("+" if r >= 0 else "-") + "${:,}".format(abs(r))
