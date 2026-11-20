"""1.7.20 (Ryan, Nov 20, 2026: "I need this page to calculate per FAR 117 and PWA when I timeout, both for if I extend or
if I do not ... Make sure it's accurate. Keep in mind the flight time, and number of crew and rest"; and that morning:
"The number I need to know is when is the last moment I can block out and be legal ... that means calculating against
the flight time"): the last legal block-out of the working leg (`last_out`, without and with an extension), the block-in
limits of its flight duty period (FDP) and the flight time and cumulative checks, for the Working Flight card
(working.py puts it on sensor.<prefix>_working_flight as `timeout`). Pure: no I/O, no clock of its own; every time is an
aware datetime. No FLICA load: it reads the pilot's own trips and the pairings package.

Rules (FOM 125.4 4.3.2, which reproduces 14 CFR 117 and its Tables A, B and C; FOM 5.1.23.7 and 5.1.23.8 crew rest;
PWA 2.A.19.b duty period; PWA Section 10 hours of service):
- Acclimation (117.3, FOM 4.3.2.4.6). A theater is a span of 60 degrees of longitude (LON, every station in
  working.ZONES). The pilot's duties are walked in time order from acclimated to HNL. A report within 60 degrees of
  the acclimated theater's reference: acclimated. Else he becomes acclimated to the new theater (its report station
  is the new reference) after 36 consecutive hours free from duty before the report, or 72 h in that theater since
  the block-in that brought him there. Else not acclimated: Tables A, B and C are entered on the last acclimated
  theater's clock and the FDP limit is 30 min less (117.13(b), 117.17(b), FOM 4.3.2.4). A station with no longitude,
  or a schedule item that may be duty inside the 36 h: the lower of the readings, marked '?'. A span of the line that
  is not known (a trip whose legs and duty periods are not read, days no schedule month covers) breaks the walk: after
  it only 36 h free from duty acclimates for sure; until then the lowest value of the table on any clock (less 0:30)
  is used, marked '?'.
- Which clock of an acclimated theater: FOM 4.3.2.4 says "the report time at local domicile or the local time in the
  theater to which [he] is acclimated", and FAA interpretations let a carrier use either the local time where the FDP
  series starts or the home base time. Away from the reference station both readings are worked out (the reference
  station's clock and the report station's own, daylight time included): the lower limit is used and, when the other
  differs, the result is marked '?' and the other reading's last out is given in the basis.
- Pilots: the own trip roster's CA, FO, RO and SO seats (an OPEN one too), else the package crew line (CA01FO01RO01 is
  3); working.py says which and whether it is sure (a crew list with no CA misses a seat). A count whose planned flight
  time is over its limit, when not sure, is raised to the fewest pilots that may fly it, marked '?'. 2 pilots: Table B
  (117.13; every leg of the FDP counts as a segment, a deadhead from the pairings package too) and Table A flight time
  (117.11). 3 or 4: Table C (117.17) and 13 or 17 h flight time (117.11, FOM 4.3.2.2); more than 3 segments is flagged
  (FOM 4.3.2.4.2). Unknown: no timeout.
- Rest facility (FOM 5.1.23.7, 5.1.23.8): the A330 LDMCR (bunks 1 and 4) with 3 pilots, all LDMCR available (Table
  5.1.23.8.1(1)): Class 1. Where the FOM also requires a pilot crew rest seat in the cabin (A330 4 pilots: 3C or 3G;
  787 3 pilots: 9A; 4 pilots: 9A and 9J), a rest may be taken in that seat: Class 2, marked '?'. Other or unknown
  equipment: Class 3, marked '?'. The other classes' ends are given too.
- FDP end = report + limit; with the extension (117.19(a), FOM 4.3.2.5) 2:00 more, before takeoff only, both no later
  than the 117.23(c) cumulative FDP caps. After takeoff (117.19(b)) the FDP, the flight time and the cumulative limits
  may be exceeded as needed to land: no fixed time.
- Last out = that end less the scheduled time from the working leg's block-out to the duty's last flown block-in (its
  block, the later legs and the ground times between them): shown on the departure station's clock and HST.
- Flight time is a duration check (FOM 4.3.2.2: no takeoff without a reasonable expectation to land within it): the
  duty's planned flight time against the limit ("11:15 of 13:00"); over it, not legal to dispatch at any time and no
  last out. An FDP extension does not extend it. With the leg out on time, the block-in it allows is given too
  (`no_ext` / `ext`: the block-in limits from the scheduled out; they move with the actual out).
- Cumulative (117.23(b)(1), (c)(1), (c)(2); FOM 4.3.2.3, 4.3.2.6): 100 h flight time in 672 h (a duration check: a later
  out only drops old flying), 60 h FDP in 168 h and 190 h FDP in 672 h (caps on the FDP end: that block-in + what is
  left, the earliest the cap can be), each from the duty's scheduled last block-in. Only when the line on file covers
  the whole window (known_from), else listed under not_checked. Over at the scheduled times: not legal.
- Rest (117.25(e), FOM 4.3.2.7): 10 h free from duty before the report; 117.25(b), FOM 4.3.2.9: 30 consecutive hours
  free in the 168 h before it, when the line on file covers that window; 117.25(g), FOM 4.3.2.10: after deadhead
  transportation past its Table B FDP, a rest as long as the deadhead (no less than 10 h; deadheads after a flown leg a
  '?'); 117.25(d), FOM 4.3.2.11: 56 consecutive hours at home after a trip more than 168 h away that went more than 60
  degrees (a '?' when its start or a span inside it is not on file). Flagged when short.
- PWA 2.A.19.b: the Duty Period ends 15 min after block-in, 30 when clearing customs (a leg between two countries, or
  to or from a station whose country is not on file; the Watcher's US list and the pilot's smart.json "domestic"
  stations are the US): each result's release, after a trailing deadhead's block-in when the duty ends with one. Where
  watcher.release_customs (a last leg from outside the US) gives the other debrief, the basis says so.
- PWA 2023 Section 10 (Hours of Service; Local Times, 2.A.43). Duty limit (10.D): an International Pilot "shall not be
  required to remain in a Duty Period in excess of" the Maximum: 2 pilots 16:00 (Scheduled 14:00, 10.D.1.a as the LOA
  amends it), an IRO Crew (3 pilots, 2.A.40) 18:00 (16:00, 10.D.1.b.1), an Extended Range Crew of 1 Captain (2.A.25)
  18:00 (16:00, 10.D.1.c), one of 2 Captains no PWA hours (Part 117 Table C governs, 10.D.1.d); 4 pilots with the
  Captains not known: 18:00, marked '?'. A grouping (pairing, the duties' `key`) that holds a Mixed Flying Duty Period
  (2.A.45: a flown segment of 3:00 block or more and an interisland one besides a single Repositioning Flight, 2.A.62,
  whose "minimal delay at the neighbor island station" is read as a sit of 2:00 or less; a longer one is Mixed Flying,
  and so is an interisland deadhead read as its interisland Segment, both marked '?' where they set the limit) takes 14:00 standard crew, 16:00 augmented in every duty (10.D.3.a: "a pilot assigned to a grouping
  containing" one). A duty that is all interisland flying is an Interisland Pilot's (2.A.36.b): 10.D.2 (12 / 14 h
  starting 0500-2159, 10 / 12 h 2200-0459, 12 h past 0300 for a duty starting before 2200), with the 10.D.4 pilot
  option said, not used; the lowest Maximum that applies is used. The Duty Period starts at the report (the later of
  the scheduled and actual one, 10.D.5) and ends 15 or 30 min after the duty's last block-in (a trailing deadhead too).
  No 5.A.6 transfer time serves HNL (and 10.D.1.b.2 bars them for an IRO Crew), no pilot option exceeds an
  International Maximum (10.D.4 is Interisland), and a 117.19 extension stays within the CBA (FOM 4.3.2.5): pwa last out
  = report + Maximum - debrief - the scheduled time from this leg's out to the duty's last block-in caps both results.
  Over the Maximum at the scheduled times: not legal; over the Scheduled limit: flagged. Rest (10.E, flags only): 11:00
  in domicile (10.E.1.a); out of it 2 x the preceding Duty Period (10.E.1.a.1; for 2 pilots a rest of 9:00 or more under
  it is a '?': the Company may limit a regular crew's hotel rest to 9:00, 10.E.1.a.2), or in a grouping that holds a
  Mixed Flying Duty Period 9, 10 or 11 h by the landings performed in it (10.E.3.a; until Ryan confirms that the table
  replaces 10.E.1.a.1, a rest it meets but 2 x the Duty Period does not is a '?'); before a duty that is all
  interisland flying (an Interisland Pilot's) 12:00 in domicile, 9:00 out of it (10.E.2.a, 10.E.2.b); 18:00 when a
  segment departs 1400-0359 local and the scheduled Duty Period is 12:00 or more (10.E.1.b; before an interisland duty
  short of it is a '?': it names an International Pilot's Segment). Where a long sit at the neighbor island decides
  whether the grouping is Mixed Flying, both readings are judged and a rest they disagree on is a '?'. From release to
  report: out of domicile the PWA Rest Period is hotel time door to door (2.A.68.b, 10.E.1.a.3), so a rest met by less
  than VAN_RIDES (the two van rides, 2:30) is a '?'. A rest or a landings count that is not sure is a flag of its own
  (rest_q, landings_q: a chip on the card); the box's '?' is for what moves a last out. Landings (10.H.1): 10 scheduled, 11 required, 7 for a duty starting
  2200-0459 local; Mixed Flying 4 (10.H.3); an Interisland Pilot's duty starting before 2200 HST and continuing after
  0300 HST 8 (10.H.2). A station whose Local Time is not on file is never read as HST: 10.E.1.b and the 7 landings may
  apply, a '?'.
"""
import re
from datetime import datetime, time as dtime, timedelta, timezone

import layover as LO
import working as WK

HST = WK.HST
DOMICILE = WK.DOMICILE
# Longitude (decimal degrees, east positive, 0.1 is enough) of every station in working.ZONES (tests check the set)
LON = {"HNL": -157.9, "OGG": -156.4, "KOA": -156.0, "ITO": -155.0, "LIH": -159.3, "PPT": -149.6, "RAR": -159.8,
       "PPG": -170.7, "ANC": -150.0, "LAX": -118.4, "SFO": -122.4, "SEA": -122.3, "SAN": -117.2, "OAK": -122.2,
       "SMF": -121.6, "LAS": -115.2, "PDX": -122.6, "SJC": -121.9, "ONT": -117.6, "LGB": -118.2, "PHX": -112.0,
       "SLC": -112.0, "DEN": -104.7, "ORD": -87.9, "DFW": -97.0, "AUS": -97.7, "MSP": -93.2, "IAH": -95.3,
       "JFK": -73.8, "BOS": -71.0, "MCO": -81.3, "IAD": -77.5, "ATL": -84.4, "MIA": -80.3, "EWR": -74.2,
       "NRT": 140.4, "HND": 139.8, "KIX": 135.2, "CTS": 141.7, "FUK": 130.5, "NGO": 136.8, "ICN": 126.5,
       "SYD": 151.2, "BNE": 153.1, "MEL": 144.8, "AKL": 174.8, "SIN": 104.0, "MNL": 121.0, "CRK": 120.6,
       "TPE": 121.2, "PEK": 116.6, "PVG": 121.8, "HKG": 113.9, "BFI": -122.3, "IND": -86.3, "LAN": -84.6,
       "LNK": -96.8, "MKK": -157.1, "LNY": -156.9}
THEATER_DEG = 60
FREE_ACCL, STAY_ACCL = timedelta(hours=36), timedelta(hours=72)
UNACCL = timedelta(minutes=30)
EXT = timedelta(hours=2)
RELEASE, RELEASE_CUSTOMS = timedelta(minutes=15), timedelta(minutes=30)  # PWA 2.A.19.b
REST_MIN = timedelta(hours=10)  # FAR 117.25(e), FOM 4.3.2.7
FREE_WEEK, WEEK = timedelta(hours=30), timedelta(hours=168)  # FAR 117.25(b), FOM 4.3.2.9
THEATER_REST, AWAY_MAX = timedelta(hours=56), timedelta(hours=168)  # FAR 117.25(d), FOM 4.3.2.11
# FW-0042 review: the stations a leg into the US comes from without clearing customs (watcher.US_STATIONS is this set)
US_STATIONS = frozenset(("HNL", "OGG", "KOA", "ITO", "LIH", "MKK", "LNY", "ANC", "LAX", "SFO", "SEA", "SAN", "OAK", "SMF", "LAS",
                         "PDX", "SJC", "ONT", "LGB", "PHX", "SLC", "DEN", "ORD", "DFW", "AUS", "MSP", "IAH", "JFK",
                         "BOS", "MCO", "IAD", "ATL", "MIA", "EWR"))
# The country (customs territory) of the stations outside the US list: a leg between two of them in one country clears
# no customs; American Samoa (PPG) keeps its own customs. A station in neither: not known, so customs (conservative).
COUNTRY = {**{s: "JP" for s in ("NRT", "HND", "KIX", "CTS", "FUK", "NGO")}, "ICN": "KR",
           **{s: "AU" for s in ("SYD", "BNE", "MEL")}, "AKL": "NZ", "SIN": "SG", "MNL": "PH", "CRK": "PH", "TPE": "TW",
           "PEK": "CN", "PVG": "CN", "HKG": "HK", "PPT": "PF", "RAR": "CK", "PPG": "AS"}
PILOT_SEATS = ("CA", "FO", "RO", "SO")  # pot.PILOT_SEATS, crewidx.PILOT_POS: an OPEN seat is a required seat
ANY = "*"  # an acclimation reading on no known clock: the lowest row of the table
# Table A (117.11): (first minute, last minute of the acclimated report time, hours)
TABLE_A = ((0, 299, 8), (300, 1199, 9), (1200, 1439, 8))
# Table B (117.13): (first, last minute, hours for 1, 2, ... 7+ segments)
TABLE_B = ((0, 239, (9, 9, 9, 9, 9, 9, 9)), (240, 299, (10, 10, 10, 10, 9, 9, 9)),
           (300, 359, (12, 12, 12, 12, 11.5, 11, 10.5)), (360, 419, (13, 13, 12, 12, 11.5, 11, 10.5)),
           (420, 719, (14, 14, 13, 13, 12.5, 12, 11.5)), (720, 779, (13, 13, 13, 13, 12.5, 12, 11.5)),
           (780, 1019, (12, 12, 12, 12, 11.5, 11, 10.5)), (1020, 1319, (12, 12, 11, 11, 10, 9, 9)),
           (1320, 1379, (11, 11, 10, 10, 9, 9, 9)), (1380, 1439, (10, 10, 10, 9, 9, 9, 9)))
# Table C (117.17): (first, last minute, {rest class: (3 pilots, 4 pilots) hours})
TABLE_C = ((0, 359, {1: (15, 17), 2: (14, 15.5), 3: (13, 13.5)}),
           (360, 419, {1: (16, 18.5), 2: (15, 16.5), 3: (14, 14.5)}),
           (420, 779, {1: (17, 19), 2: (16.5, 18), 3: (15, 15.5)}),
           (780, 1019, {1: (16, 18.5), 2: (15, 16.5), 3: (14, 14.5)}),
           (1020, 1439, {1: (15, 17), 2: (14, 15.5), 3: (13, 13.5)}))
AUG_FT = {3: 13, 4: 17}  # 117.11, FOM 4.3.2.2: augmented flight time
AUG_MAX_SEGMENTS = 3  # FOM 4.3.2.4.2
CUM = (("ft_672", timedelta(hours=672), 100, "ft", "100 h flight time in 672 h", "FAR 117.23(b)(1)", "100 h in 672 h"),
       ("fdp_168", timedelta(hours=168), 60, "fdp", "60 h FDP in 168 h", "FAR 117.23(c)(1)", "60 h FDP in 168 h"),
       ("fdp_672", timedelta(hours=672), 190, "fdp", "190 h FDP in 672 h", "FAR 117.23(c)(2)", "190 h FDP in 672 h"))
CUM_BY = {c[0]: c for c in CUM}
# PWA 2023 Section 10 (Hours of Service) for an International Pilot; every time a Local Time (2.A.43)
HAWAII = frozenset(("HNL", "OGG", "KOA", "LIH", "ITO", "MKK", "LNY"))  # an interisland segment: both ends here (2.A.35)
NEIGHBOR = frozenset(("ITO", "KOA", "OGG", "LIH"))  # 2.A.62: the neighbor island stations of a Repositioning Flight
# 2.A.62 "scheduled with minimal delay at the neighbor island station": the PWA gives no figure; the Watcher takes a sit
# of 2:00 or less there (a longer one is no Repositioning Flight: the lower Mixed Flying limits, marked '?')
REPO_SIT = timedelta(hours=2)
MIXED_BLOCK = timedelta(hours=3)  # 2.A.45: a Segment of at least 3 hours
PWA_REST_HOME = timedelta(hours=11)  # 10.E.1.a
PWA_REST_REGULAR = timedelta(hours=9)  # 10.E.1.a.2: a regular crew's hotel rest may be limited to 9 hours
PWA_REST_LATE, PWA_LATE_DP = timedelta(hours=18), timedelta(hours=12)  # 10.E.1.b
PWA_REST_II_HOME, PWA_REST_II_AWAY = timedelta(hours=12), timedelta(hours=9)  # 10.E.2.a, 10.E.2.b (Interisland)
# 2.A.68.b, 10.E.1.a.3: out of domicile the Rest Period is hotel time door to door; FW knows release to report, longer by
# the two van rides, which the schedule does not give: a rest met from release to report by less than this is a '?'
# (review PWA-VAN_RIDES: the two rides at a far-out hotel take 1:30 to 2:30 together; 2:30 until Ryan gives a figure)
VAN_RIDES = timedelta(hours=2, minutes=30)
MIXED_REST = ((5, 9), (7, 10), (999, 11))  # 10.E.3.a: landings performed in the grouping (up to), hours of rest
LANDINGS_SCHED, LANDINGS_REQ, LANDINGS_NIGHT, LANDINGS_MIXED = 10, 11, 7, 4  # 10.H.1, 10.H.3
LANDINGS_II_LATE = 8  # 10.H.2: an Interisland Pilot's duty starting before 2200 HST and continuing after 0300 HST
PWA_NC = "PWA hotel door-to-door rest: van and hotel arrival times not on the schedule"
PWA_NC_IRO = "IRO at the controls 8 h in 24 h (PWA 10.D.1.b.4): depends on the in-flight rest plan"
ERR = {"last": ""}  # the last reason duty_timeout gave no timeout for an error ('' after one worked); working.py logs it


def ang(a, b):
    """Degrees of longitude between two longitudes, across the antimeridian too."""
    return abs(((a - b + 180) % 360) - 180)


def same_theater(s1, s2):
    """True when two stations are within 60 degrees of longitude (117.3 theater); None when either has none."""
    a, b = LON.get(s1), LON.get(s2)
    return None if a is None or b is None else ang(a, b) <= THEATER_DEG


def zone(stn):
    """A station's clock (working.ZONES, daylight time included); HST (the domicile's) for HNL and for none."""
    return HST if stn == DOMICILE else WK._zone(stn) or HST


def known_local(stn):
    """True when a station's Local Time (PWA 2.A.43) is on file: Hawaii's stations (HST) and working.ZONES."""
    return stn in HAWAII or stn == DOMICILE or WK._zone(stn) is not None


def hm(td):
    """A duration as 'H:MM' ('-0:20' below zero)."""
    m = int(round(td.total_seconds() / 60))
    s = "-" if m < 0 else ""
    m = abs(m)
    return f"{s}{m // 60}:{m % 60:02d}"


def _hrs(h):
    return timedelta(minutes=int(round(h * 60)))


def clock(dt, z=None, stn=""):
    """'16:40 HST' (HST, Hawaii's fixed UTC-10, by default), '08:40 EST' on a station's zone; a zone with no letters for
    its time ('UTC+08') is named by the station when one is given ('14:43 SIN')."""
    if z is None or z is HST:
        return f"{dt.astimezone(HST):%H:%M} HST"
    loc = dt.astimezone(z)
    ab = LO.abbr(loc)
    return f"{loc:%H:%M} {stn if stn and not re.fullmatch(r'[A-Z]{2,6}', ab) else ab}"


def sclock(dt, stn):
    """A time on a station's own clock, the station named when its zone has no letters ('14:43 SIN')."""
    return clock(dt, zone(stn), stn)


def hw(td):
    """A duty limit as hours, never read as a clock: '18 h', '13 h 30 min'."""
    m = int(round(td.total_seconds() / 60))
    return f"{m // 60} h" + (f" {m % 60} min" if m % 60 else "")


def day(dt):
    """'Fri Nov 20' in HST."""
    h = dt.astimezone(HST)
    return f"{h:%a %b} {h.day}"


def _row(table, minute):
    return next(r for r in table if r[0] <= minute <= r[1])


def _label(r):
    return f"{r[0] // 60:02d}{r[0] % 60:02d}-{r[1] // 60:02d}{r[1] % 60:02d}"


def _pos(c):
    return str((c.get("pos") if isinstance(c, dict) else c[0] if isinstance(c, (list, tuple)) and c
                else str(c).strip().split(" ", 1)[0] if isinstance(c, str) else "") or "").upper()


def roster_seats(roster):
    """(pilot seats, has a CA seat) of an own trip roster ('CA Doe, Jane (12345)', an OPEN seat too; [pos, name] or
    {pos}). Never a name."""
    pos = [_pos(c) for c in (roster if isinstance(roster, (list, tuple)) else [])]
    return sum(p in PILOT_SEATS for p in pos), "CA" in pos


def package_pilots(code):
    """Pilots of a package crew line ('CA01FO01RO01' is 3); None under 2."""
    m = sum(int(x) for x in re.findall(r"(?:CA|FO|RO|SO)(\d{1,2})", str(code or "").upper()))
    return m if m >= 2 else None


def pilots_of(roster, code=""):
    """(number of pilots, 'roster' | 'package' | '') from the own trip roster when it lists 2 or more pilot seats, else
    the package crew line; (None, '') with neither."""
    n = roster_seats(roster)[0]
    if n >= 2:
        return n, "roster"
    m = package_pilots(code)
    return (m, "package") if m else (None, "")


def roster_captains(roster):
    """The CA seats of an own trip roster (an OPEN one too). Never a name."""
    return sum(_pos(c) == "CA" for c in (roster if isinstance(roster, (list, tuple)) else []))


def package_captains(code):
    """The Captains of a package crew line ('CA02FO02' is 2); None when it names none."""
    m = re.search(r"CA(\d{1,2})", str(code or "").upper())
    return int(m.group(1)) if m and int(m.group(1)) > 0 else None


def pwa_duty(pilots, captains=None, mixed=False, grouping=False):
    """(Scheduled, Maximum, cite, crew words, sure) of an International Pilot's Duty Period (PWA 10.D) for a crew of
    `pilots` with `captains` Captains (None: not known); 10.D.3 when mixed: "a pilot assigned to a grouping containing a
    Mixed Flying Duty Period" (2.A.45), the Mixed Flying duty itself or (grouping) another duty of that grouping.
    Maximum None: the crew has no PWA hours of its own (10.D.1.d: Part 117 Table C governs)."""
    h = lambda x: timedelta(hours=x)  # noqa: E731
    if mixed:
        what = ("a duty of a grouping that holds a Mixed Flying Duty Period (2.A.45; 10.D.3.a covers the grouping)"
                if grouping else "Mixed Flying duty (2.A.45)")
        if not pilots:
            return h(12), h(14), "10.D.3", f"{what}, pilots not known: the standard crew's", False
        if pilots >= 3:
            return h(14), h(16), "10.D.3", f"{what}, augmented crew", True
        return h(12), h(14), "10.D.3", f"{what}, standard crew", True
    if not pilots or pilots < 3:
        return (h(14), h(16), "10.D.1.a", "2 pilots" if pilots else "pilots not known: the 2-pilot limits",
                bool(pilots))
    if pilots == 3:
        return h(16), h(18), "10.D.1.b.1", "IRO Crew (2.A.40)", True
    if captains is not None and captains >= 2:
        return None, None, "10.D.1.d", "Extended Range Crew of 2 Captains and 2 First Officers", True
    if captains == 1:
        return h(16), h(18), "10.D.1.c", "Extended Range Crew of 1 Captain and 3 First Officers (2.A.25)", True
    return (h(16), h(18), "10.D.1.c", "4 pilots, Captains not known: the 1-Captain Extended Range Crew's (2.A.25; 2 "
            "Captains would have no PWA hours, 10.D.1.d)", False)


def _repo(flown, j):
    """2.A.62 for flown leg j: interisland to a neighbor island station for a departure out of the islands from there,
    or to Honolulu from one after an arrival from out of the islands, "scheduled with minimal delay at the neighbor
    island station". (True, sit) when it is a Repositioning Flight (a sit there of REPO_SIT or less), ('long', sit) when it
    would be one but for a longer sit, (False, None) otherwise."""
    x, sit = flown[j], None
    if x["to"] in NEIGHBOR and x["frm"] in HAWAII:
        nx = flown[j + 1] if j + 1 < len(flown) else None
        if nx and nx["frm"] == x["to"] and nx["to"] not in HAWAII:
            sit = nx["dep"] - x["arr"]
    elif x["to"] == DOMICILE and x["frm"] in NEIGHBOR:
        pv = flown[j - 1] if j else None
        if pv and pv["to"] == x["frm"] and pv["frm"] not in HAWAII:
            sit = x["dep"] - pv["arr"]
    if sit is None:
        return False, None
    return (True, sit) if sit <= REPO_SIT else ("long", sit)


def _repositioning(flown, j):
    """2.A.62: flown leg j is a Repositioning Flight (see _repo)."""
    return _repo(flown, j)[0] is True


def mixed_flying(legs, long_sit=False, dh=False):
    """2.A.45 Mixed Flying: the duty's flown segments include one of 3:00 block or more and an interisland one (both ends
    in Hawaii), besides a single Repositioning Flight (2.A.62). Deadheads are no segment flown. long_sit: the other
    reading, a would-be Repositioning Flight with a longer sit at the neighbor island counted as one. dh: the deadhead
    reading (review PWA-deadhead-not-counted-for-mixed-flying): 2.A.62 positions "such aircraft, or operating crew" and
    2.A.45 counts Segments, so an interisland deadhead may be the interisland Segment (or the Repositioning Flight)."""
    flown = [x for x in legs if not x.get("dh")]
    if not any(timedelta(minutes=int(x["blk"])) >= MIXED_BLOCK for x in flown):
        return False
    segs = list(legs) if dh else flown
    inter = [j for j, x in enumerate(segs) if x["frm"] in HAWAII and x["to"] in HAWAII]
    rp = any(_repo(segs, j)[0] is True or (long_sit and _repo(segs, j)[0] == "long") for j in inter)
    return len(inter) - (1 if rp else 0) > 0


def interisland(legs):
    """True when a duty's flown segments are all interisland flying (both ends in Hawaii, 2.A.35): an Interisland
    Pilot's duty (2.A.36.b)."""
    flown = [x for x in legs if not x.get("dh")]
    return bool(flown) and all(x["frm"] in HAWAII and x["to"] in HAWAII for x in flown)


def _t3(rep):
    """0300 HST the morning after the report (10.D.2.b, 10.H.2)."""
    return datetime.combine(rep.astimezone(HST).date() + timedelta(days=1), dtime(3, 0), tzinfo=HST)


def interisland_duty(rep, sched_end):
    """(Scheduled, Maximum, cite, crew words, sure) of an Interisland Pilot's Duty Period (PWA 10.D.2; an International
    Pilot whose duty is all interisland flying is one, 2.A.36.b) reporting at rep and scheduled to end at sched_end, on
    Hawaii's clock (2.A.43): 12 and 14 h starting 0500-2159, 10 and 12 h starting 2200-0459 (10.D.2.a); a duty starting
    before 2200 and continuing after 0300 the next morning 10 and 12 h (10.D.2.b), so where 14 h would pass that 0300
    the Maximum ends at the later of 0300 and 12 h, and a duty scheduled past 0300 has a 10 h Scheduled limit."""
    h = lambda x: timedelta(hours=x)  # noqa: E731
    loc = rep.astimezone(HST)
    m = loc.hour * 60 + loc.minute
    what = "Interisland duty (all its flown segments interisland: an Interisland Pilot, 2.A.36.b)"
    if m >= 22 * 60 or m < 5 * 60:
        return h(10), h(12), "10.D.2.a", f"{what} starting 2200-0459", True
    t3 = _t3(rep)
    mx, cite, more = h(14), "10.D.2.a", "starting 0500-2159"
    if rep + mx > t3:
        mx, cite, more = max(h(12), t3 - rep), "10.D.2.b", "starting before 2200: past 0300 the next morning 12 h"
    sc = h(10) if sched_end > t3 else h(12)
    return sc, mx, cite, f"{what} {more}", True


def _local_min(dt, stn):
    loc = dt.astimezone(zone(stn))
    return loc.hour * 60 + loc.minute


def rest_class(eq, pilots):
    """(class 1 to 3, sure, why) of the crew rest for an augmented crew (FOM 5.1.23.7, 5.1.23.8, Table 5.1.23.8.1(1)).
    Class 1 where every rest is in the pilot bunks; where the FOM also requires a pilot crew rest seat in the cabin, a
    rest may be taken in it: Class 2, not sure (Class 1 if every rest is in the bunks)."""
    e = str(eq or "").strip().upper()
    kind = "A330" if e.startswith("33") else "787" if e.startswith("78") else ""
    if not kind:
        return 3, False, (f"equipment {e or 'not on file'}: rest facility class not known, Class 3 used (the lowest "
                          f"Table C value)")
    where = "LDMCR bunks 1 and 4 (FOM 5.1.23.8)" if kind == "A330" else "OFCR (FOM 5.1.23.7)"
    seat = ("" if pilots < 4 else "3C or 3G") if kind == "A330" else ("9A" if pilots < 4 else "9A and 9J")
    if not seat:
        return 1, True, f"{kind} {where}, all LDMCR available to an augmented crew (Table 5.1.23.8.1(1)): Class 1"
    return 2, False, (f"{kind} {where} with {pilots} pilots: the FOM also requires pilot crew rest seat {seat} (Table "
                      f"5.1.23.8.1(1)), so Class 2 is used (a rest may be taken in that seat; Class 1 if every rest is "
                      f"in the bunks)")


def country(stn, domestic=()):
    """'US' for the Watcher's US list and the pilot's domestic stations, the country of a known foreign station, None
    when not known."""
    return "US" if stn in US_STATIONS or stn in domestic else COUNTRY.get(stn)


def customs(leg, domestic=()):
    """PWA 2.A.19.b ("when required to clear Customs"): True when the leg goes from one country to another, or either
    end's country is not known (conservative: the later release)."""
    a, b = country(leg["frm"], domestic), country(leg["to"], domestic)
    return a is None or b is None or a != b


def _overlap(a, b, c, d):
    return max(timedelta(0), min(b, d) - max(a, c))


def _prep(d, domestic=()):
    """A duty's FDP facts: flown legs, the FDP's legs (to the last flown leg), its end, release and flight time."""
    legs = d["legs"]
    flown = [i for i, x in enumerate(legs) if not x.get("dh")]
    out = dict(d)
    last = legs[-1]
    out["release"] = last["arr"] + (RELEASE_CUSTOMS if customs(last, domestic) else RELEASE)
    if not flown:
        out.update(fdp=False, fdp_end=None, ft=timedelta(0), fdp_legs=[])
        return out
    j = flown[-1]
    out.update(fdp=True, fdp_end=legs[j]["arr"], fdp_legs=legs[:j + 1],
               ft=sum((timedelta(minutes=int(legs[i]["blk"])) for i in flown), timedelta(0)))
    return out


def _hits(spans, a, b):
    """The spans that overlap (a, b); a None is open."""
    return [(x, y) for x, y in spans if y > (a if a is not None else x) and x < b]


def _acclimation(ds, idx, busy, unknown=()):
    """The walk (see the module note) up to duty idx: (options, words, status, free, how). options: [(station whose
    clock enters the tables, or ANY; 0:30 less)], the readings to try (the lowest limit is used); status True / False /
    None (acclimated / not / unknown); free: the time free from duty before the report, from the last release ('release')
    or from the end of a span of the line not known ('unknown': at least that); None (how None) with neither."""
    ref, ref_sure = DOMICILE, True
    stay = {"stn": DOMICILE, "since": None}
    for j in range(idx + 1):
        d = ds[j]
        s, rep = d["legs"][0]["frm"], d["report"]
        prev = ds[j - 1] if j else None
        lo = prev["release"] if prev else None
        gone, how = _hits(unknown, lo, rep), "release" if prev else None
        if gone:  # a span of the line that is not known since the last duty: where he was is not known
            u_end = min(rep, max(y for _x, y in gone))
            lo = max(x for x in (lo, u_end) if x is not None)
            ref, ref_sure = None, False
            stay = {"stn": None, "since": u_end}
            how = "unknown" if lo == u_end else how
        free = rep - lo if lo is not None else None
        busy_gap = lo is not None and bool(_hits(busy, lo, rep))
        in_th = (rep - stay["since"]) if stay.get("since") is not None and same_theater(s, stay["stn"]) else None
        stay_ok = in_th is not None and in_th >= STAY_ACCL
        free_ok = free is not None and free >= FREE_ACCL
        known = s in LON
        far = (f"{s} is {round(ang(LON[s], LON[ref]))} deg from {ref}" if known and ref in LON
               else f"{s} has no longitude on file")
        facts = (f"{hm(free)} free from duty (36 h needed)" if free is not None else "no duty before it on file") + (
            f", {hm(in_th)} in that theater (72 h needed)" if in_th is not None else "")
        if ref is not None and ref_sure and known and same_theater(s, ref):
            st, opts = True, [(ref, False)]
            if WK._zone(s) is not None and rep.astimezone(zone(s)).utcoffset() != rep.astimezone(zone(ref)).utcoffset():
                opts.append((s, False))  # the report station's own clock too: the lower limit is used
            words = (f"acclimated to the {ref} theater" + (f" ({s} is within 60 deg of {ref})" if s != ref else ""))
        elif known and (stay_ok or (free_ok and not busy_gap)):
            why = f"{hm(free)} free from duty" if free_ok and not busy_gap else f"{hm(in_th)} in that theater"
            ref, ref_sure = s, True
            st, opts = True, [(s, False)]
            words = f"acclimated to the {s} theater ({why}; 36 h free from duty or 72 h there acclimates)"
        elif ref is None:
            st, opts = None, [(ANY, True)]
            words = (f"? acclimation not known: a span of your line before this report is not on file (a trip not "
                     f"read, or days no schedule month covers), and {facts}; the lowest value of the table on any clock, "
                     f"less 0:30, is used (conservative)")
        elif known and ref_sure and free_ok and busy_gap:
            st = None
            opts = [(s, False), (ref, True)]
            words = (f"? acclimated to {s} only if the schedule item inside the {hm(free)} free was not duty; the "
                     f"lower of acclimated ({s} time) and not acclimated ({ref} time, less 0:30) is used")
            ref_sure = False
        elif known and ref_sure:
            st, opts = False, [(ref, True)]
            words = (f"not acclimated: {far}, {facts}; the tables are entered on {ref} time (the theater last "
                     f"acclimated to) and the FDP limit is 0:30 less (FAR 117.13(b), 117.17(b), FOM 4.3.2.4)")
        else:  # a station with no longitude, here or since the last acclimation: the lower of the readings
            own = WK._zone(s) is not None
            st, opts = None, [(ref, True)] + ([(s, False)] if s != ref and own else [])
            words = (f"? acclimation not known ({far}, or a station since the last acclimation has none): the lower of "
                     f"{ref} time less 0:30" + (f" and {s} time" if s != ref and own else "") +
                     " is used (conservative)" + ("" if own or s == ref else f"; {s}'s own clock is not on file"))
        if j == idx:
            return opts, words, st, free, how
        for x in d["legs"]:  # where the duty took him: the theater stay starts at the block-in that brought him there
            if not same_theater(x["to"], stay["stn"]):
                stay = {"stn": x["to"], "since": x["arr"]}
            if x["to"] not in LON:
                ref_sure = False
    return [(DOMICILE, True)], "?", None, None, None


def _leg_ft(x, a, end):
    """A flown leg's flight time inside the window (a, end): its block, or the out to in time when that is longer
    (FLICA's printed times and block can disagree: the larger, conservative); a leg across the window's start counts
    the part inside it (plus any block beyond its printed times)."""
    blk = timedelta(minutes=int(x["blk"]))
    el, inside = x["arr"] - x["dep"], _overlap(x["dep"], x["arr"], a, end)
    if inside <= timedelta(0):
        return timedelta(0)
    return min(max(blk, el), inside + max(timedelta(0), blk - el))


def _cum(ds, idx, end, known_from):
    """{key: {limit, used, room, cap_at, cap_txt, line}} for the cumulative limits whose window the line on file
    covers, and [lines for the ones it does not]."""
    got, missing = {}, []
    me = ds[idx]
    for key, span, lim, what, words, ref, short in CUM:
        a = end - span
        if known_from is None or known_from > a:
            since = f" before {day(known_from)}" if known_from is not None else ""
            missing.append(f"{words} ({ref}): your line{since} is not all on file, not checked")
            continue
        used = timedelta(0)
        for d in ds[:idx + 1]:
            if not d["fdp"]:
                continue
            if what == "ft":
                used += sum((_leg_ft(x, a, end) for x in d["legs"] if not x.get("dh")), timedelta(0))
            else:
                used += _overlap(d["report"], end if d is me else d["fdp_end"], a, end)
        room = _hrs(lim) - used
        cap = end + room
        if what == "ft":
            line = (f"{words} ({ref}): {hm(used)} at the scheduled block-in {clock(end)}, "
                    + (f"{hm(room)} spare" if room >= timedelta(0) else f"{hm(-room)} over"))
        else:
            line = (f"{words} ({ref}): {hm(used)} at the scheduled block-in {clock(end)}, {hm(room)} left, so the FDP "
                    f"ends no later than {clock(cap)} {day(cap)}")
        got[key] = {"_cap": cap, "_room": room, "limit": f"{lim}:00", "used": hm(used), "room": hm(room),
                    "cap_at": cap.isoformat(), "cap_txt": clock(cap), "cap_day": day(cap),
                    "txt": f"{short}: " + (f"{hm(room)} spare" if room >= timedelta(0) else f"{hm(-room)} over"),
                    "line": line}
    return got, missing


def _free_week(ds, idx, busy, known_from, rep):
    """FAR 117.25(b): (longest free period in the 168 h before the report counting every schedule item that may be duty,
    the same without them) or None when the line on file does not cover the window."""
    a = rep - WEEK
    if known_from is None or known_from > a:
        return None

    def longest(spans):
        best, at = timedelta(0), a
        for x, y in sorted((max(x, a), min(y, rep)) for x, y in spans if y > a and x < rep):
            best = max(best, x - at)
            at = max(at, y)
        return max(best, rep - at)
    duty = [(d["report"], d["release"]) for d in ds[:idx]]
    return longest(duty + list(busy)), longest(duty)


def _theater_rest(ds, idx, unknown=()):
    """FAR 117.25(d), FOM 4.3.2.11 (review FAR-117.25d): 56 consecutive hours of rest on return to home base after an FDP
    or a series of FDPs that travelled more than 60 degrees of longitude and kept the pilot away from home base more than
    168 consecutive hours. None when duty idx does not follow such a return for sure or may not; else {applies (True, or
    None: may apply), away, start, end, far (the farthest station), deg, why (what is not sure)}. The trip runs from its
    first report at HNL to the release of the duty that brought him home; deadheads travel too."""
    me = ds[idx]
    if idx == 0 or me["legs"][0]["frm"] != DOMICILE or ds[idx - 1]["legs"][-1]["to"] != DOMICILE:
        return None
    k = idx - 1
    while k > 0 and ds[k - 1]["legs"][-1]["to"] != DOMICILE:
        k -= 1
    start, end = ds[k]["report"], ds[idx - 1]["release"]
    away = end - start
    no_start = ds[k]["legs"][0]["frm"] != DOMICILE  # the line on file starts away: the trip began earlier
    gaps = bool(_hits(unknown, start, end))  # he may have been home in a span of the line not on file
    stns = {x[s] for d in ds[k:idx] for x in d["legs"] for s in ("frm", "to")}
    known = sorted((ang(LON[s], LON[DOMICILE]), s) for s in stns if s in LON)
    deg, far = known[-1] if known else (0, "")
    nolon = sorted(s for s in stns if s not in LON)
    a_ok = (None if gaps else True) if away > AWAY_MAX else None if no_start else False
    d_ok = True if deg > THEATER_DEG else None if nolon else False
    if a_ok is False or d_ok is False:
        return None
    why = ([f"the trip's start is not on file (away at least {hm(away)})"] if no_start and away <= AWAY_MAX else []) + (
        ["a span of your line inside the trip is not on file (you may have been home)"] if gaps else []) + (
        [f"{', '.join(nolon)} {'has' if len(nolon) == 1 else 'have'} no longitude on file"] if d_ok is None else [])
    return {"applies": True if a_ok and d_ok else None, "away": away, "start": start, "end": end, "far": far,
            "deg": deg, "why": why}


def _dh_rest(ds, idx):
    """FAR 117.25(g), FOM 4.3.2.10 (review FAR-117.25d, 4.3.2.10): a pilot "engaged in deadhead transportation [that]
    exceeds the applicable FDP in Table B" needs a rest equal to the length of the deadhead transportation, no less than
    10 h, before the next FDP. The duty before idx: all deadheads (sure), or flown legs and then deadheads (a '?': the
    deadheads after the FDP), its report to its last block-in over its Table B FDP (every leg a segment; the lower of the
    HNL and its start station's clock, the lowest row when that clock is not on file). None when it does not apply; else
    {need, length, span, limit, sure, what}."""
    if idx == 0:
        return None
    pv = ds[idx - 1]
    legs = pv["legs"]
    if not any(x.get("dh") for x in legs):
        return None
    flown = [i for i, x in enumerate(legs) if not x.get("dh")]
    trail = legs[flown[-1] + 1:] if flown else legs
    if not trail:
        return None  # its deadheads come before a flown leg: part of the FDP, the 10 h rule
    rep, n = pv["report"], min(len(legs), 7)
    lims, sure = [], not flown
    for stn in dict.fromkeys((DOMICILE, legs[0]["frm"])):
        if stn != DOMICILE and WK._zone(stn) is None:
            lims.append(_hrs(min(r[2][n - 1] for r in TABLE_B)))
            sure = False
            continue
        lims.append(_hrs(_row(TABLE_B, _local_min(rep, stn))[2][n - 1]))
    span = legs[-1]["arr"] - rep
    if span <= min(lims):
        return None
    sure = sure and span > max(lims)
    length = legs[-1]["arr"] - (rep if not flown else trail[0]["dep"])
    what = ("the duty before it was deadhead transportation only" if not flown else
            "the duty before it ended with deadhead transportation after its last flown leg")
    return {"need": max(REST_MIN, length), "length": length, "span": span, "limit": min(lims), "sure": sure,
            "what": what}


def duty_timeout(duties, idx, pilots=None, pilots_src="", eq="", known_from=None, busy=(), notes=(), work=None,
                 pilots_sure=True, pilots_firm=False, unknown=(), domestic=(), dh_note="", captains=None):
    """The `timeout` attribute for duty idx of the pilot's duties (all on file, in time order), or None when it cannot
    be worked out (pilots not known, no flown leg). A duty: {report (aware), report_txt (how it was found), legs:
    [{dep, arr (aware), blk (minutes), frm, to, flt, dh}]}. pilots / pilots_src: how many and where from; pilots_sure:
    False when the count may be short (a crew list with no CA); pilots_firm: two sources agree (else a count that cannot
    fly the planned flight time is raised to the fewest pilots that can, marked '?'). eq: the package's equipment ('332'). known_from: the
    earliest time from which the pilot's line is all on file (None: not known). busy: [(start, end)] schedule items
    that may be duty (no flight time, no FDP: training, reserve). unknown: [(start, end)] spans of the line not known
    (a trip not read, days no schedule month covers). work: the index in the duty's legs of the leg the last out is
    for (the first flown leg when None). domestic: stations counted as the US for customs. notes: more basis lines;
    dh_note: what the pairings package said about deadheads. captains: the crew's Captains (PWA 10.D.1.c / 10.D.1.d
    for 4 pilots; None: not known). A duty's `key` (its pairing, as working.py gives it) makes its grouping for PWA
    10.D.3.a and 10.E.3.a; a duty with none is a grouping of its own. An error is kept in ERR['last'] (working.py logs
    it)."""
    try:
        got = _timeout(duties, idx, pilots, pilots_src, eq, known_from, busy, notes, work, pilots_sure, pilots_firm,
                       unknown, set(domestic or ()), dh_note, captains)
        ERR["last"] = ""
        return got
    except (KeyError, TypeError, ValueError, IndexError, StopIteration, AttributeError, ZeroDivisionError) as e:
        ERR["last"] = type(e).__name__
        return None


def _reading(rep, opts, pilots, eq, segs):
    """The FDP and flight time limits of every reading (options) for a crew of `pilots`, the lowest first."""
    aug = pilots >= 3
    cls, cls_sure, cls_why = rest_class(eq, pilots) if aug else (None, True, "")
    col = 0 if pilots == 3 else 1
    cands = []
    for stn, red in opts:
        cut = UNACCL if red else timedelta(0)
        if stn == ANY:
            if aug:
                base = min(r[2][cls][col] for r in TABLE_C)
                alt = {c: min(r[2][c][col] for r in TABLE_C) for c in (1, 2, 3)}
            else:
                base, alt = min(r[2][min(segs, 7) - 1] for r in TABLE_B), {}
            cands.append({"lim": _hrs(base) - cut, "base": base, "red": red, "row": "lowest row",
                          "clock": "any clock", "alt": alt, "fa": _hrs(AUG_FT[pilots] if aug else 8),
                          "fa_row": "lowest row"})
            continue
        loc = rep.astimezone(zone(stn))
        mnt = loc.hour * 60 + loc.minute
        if aug:
            r = _row(TABLE_C, mnt)
            base, alt = r[2][cls][col], {c: r[2][c][col] for c in (1, 2, 3)}
        else:
            r = _row(TABLE_B, mnt)
            base, alt = r[2][min(segs, 7) - 1], {}
        cands.append({"lim": _hrs(base) - cut, "base": base, "red": red, "row": _label(r),
                      "clock": f"{stn} time {loc:%H:%M}", "alt": alt,
                      "fa": _hrs(AUG_FT[pilots]) if aug else _hrs(_row(TABLE_A, mnt)[2]),
                      "fa_row": _label(_row(TABLE_A, mnt))})
    cands.sort(key=lambda c: (c["lim"], c["fa"]))
    best = cands[0]
    other = next((c for c in cands[1:] if (c["lim"], c["fa"]) != (best["lim"], best["fa"])), None)
    fa_by = min(cands, key=lambda c: c["fa"])
    return {"aug": aug, "cls": cls, "cls_sure": cls_sure, "cls_why": cls_why, "best": best, "other": other,
            "fa_by": fa_by, "ft": fa_by["fa"], "pilots": pilots}


def _late(x):
    """10.E.1.b: True when a segment is scheduled to depart between 1400 and 0359 at its station's Local Time, None when
    that station's clock is not on file (never read as HST)."""
    if not known_local(x["frm"]):
        return None
    m = _local_min(x["dep"], x["frm"])
    return m >= 14 * 60 or m < 4 * 60


def mixed_rest(n):
    """10.E.3.a: the out of domicile rest of a grouping that holds a Mixed Flying Duty Period, by the landings performed
    in the grouping (up to 5: 9:00, 6 or 7: 10:00, 8 or more: 11:00)."""
    return timedelta(hours=next(h for top, h in MIXED_REST if n <= top))


def _pwa_rest(ds, idx, first, dl, sched_dp, free, free_how, busy, known_from, pilots, lines, not_checked, flags,
              mixed_grp=False, land=(0, 0), mixed_alt=None, sits="", inter=False):
    """PWA rest before the duty (lines and flags only: they do not move the last out). In domicile 11:00 (10.E.1.a);
    12:00 before a duty that is all interisland flying (an Interisland Pilot's, 2.A.36.b; 10.E.2.a). Out of it 2 x the
    preceding Duty Period (10.E.1.a.1); 9:00 before an interisland duty (10.E.2.b); in a grouping that holds a Mixed
    Flying Duty Period, 10.E.3.a's table by the landings performed in the grouping before this rest (land: those and
    the whole grouping's on file; the whole grouping's needing more is a '?'). Each other reading that may apply is
    judged too, and a rest the readings disagree on is a '?': the larger of the table and 2 x the Duty Period until Ryan
    confirms that the table replaces 10.E.1.a.1; 2 x the Duty Period before an interisland duty when the duty before it
    was International flying; where a long sit at the neighbor island decides Mixed Flying (mixed_alt: the grouping
    with that leg read as a Repositioning Flight; sits: which leg), that reading's rule. 18:00 when a segment departs
    1400-0359 local on a 12:00 Duty Period (10.E.1.b; before an interisland duty a '?' when short: it names an
    International Pilot's Segment). Release to report is all FW knows; out of domicile the PWA Rest Period is hotel time
    door to door (2.A.68.b, 10.E.1.a.3), so a rest met by less than VAN_RIDES is a '?'. For 2 pilots a rest of 9:00 or
    more but under 2 x the Duty Period is a '?', not short: the Company may limit a regular crew's hotel rest to 9:00
    (10.E.1.a.2; a regular crew is read as 2 pilots). {need, have, ok, cite, late, other, txt, _sit}: ok True / False /
    None (not known); other: another reading's need when it gives another verdict ('12:30 (10.E.1.a.1)'); _sit: the
    long sit's reading is one of them."""
    rep = ds[idx]["report"]
    home = first["frm"] == DOMICILE
    prev = ds[idx - 1] if idx and free_how == "release" else None
    gap_busy = free is not None and bool(_hits(busy, rep - free, rep))
    n0, n1 = land
    mixed_alt = mixed_grp if mixed_alt is None else mixed_alt
    pdp = prev["release"] - prev["report"] if prev is not None else None

    def judge(need, reg=False, hi=None):
        """(ok, words) of release to report against `need`. reg: a 10.E.1.a.1 need that a regular crew's 9:00 may meet
        (10.E.1.a.2); hi: the need of the whole grouping's landings on file (10.E.3.a)."""
        if free_how == "release":
            if free < need:
                if reg and free >= PWA_REST_REGULAR:
                    return None, ("? short of it, but 9:00 or more: met if the Company limits a regular crew's hotel "
                                  "rest to 9:00 (10.E.1.a.2; a regular crew is read as 2 pilots)")
                return False, "SHORT"
            if gap_busy:
                return None, "? a schedule item inside it may be duty"
        elif free_how == "unknown":
            if free < need:
                return None, "? not known"
        else:
            return (True, "met") if known_from is not None and known_from <= rep - need else (None, "? not known")
        if hi is not None and free < hi:
            return None, f"? met for those landings; the {n1} landings of the whole grouping on file would need {hm(hi)}"
        spare = free - need
        if not home and spare < VAN_RIDES:
            return None, (f"? met by {hm(spare)} from release to report, but the hotel time (door to door, 2.A.68.b, "
                          f"10.E.1.a.3) is shorter by the two van rides, which are not on the schedule (under "
                          f"{hm(VAN_RIDES)} spare is not sure)")
        return True, f"met, {hm(spare)} spare"

    two = None  # 10.E.1.a.1: (need, cite, words, reg, hi)
    if pdp is not None:
        two = (2 * pdp, "10.E.1.a.1", f"2 x the preceding Duty Period {hm(pdp)} ({clock(prev['report'])} "
               f"{day(prev['report'])} to release {clock(prev['release'])} {day(prev['release'])}) = {hm(2 * pdp)}",
               pilots == 2 and 2 * pdp > PWA_REST_REGULAR, None)

    def away(mx):
        """The out of domicile requirement under one reading of Mixed Flying (mx)."""
        if mx:
            nd, hi = mixed_rest(n0), mixed_rest(n1)
            return (nd, "10.E.3.a", f"out of domicile in a grouping that holds a Mixed Flying Duty Period, {n0} landing"
                    f"{'' if n0 == 1 else 's'} performed in it before this rest: {hm(nd)} (10.E.3.a: up to 5 landings "
                    f"9:00, 6 or 7 10:00, 8 or more 11:00, in place of 2 x the preceding Duty Period, 10.E.1.a.1)",
                    False, hi if hi > nd else None)
        if inter:
            return (PWA_REST_II_AWAY, "10.E.2.b", "out of domicile before a duty that is all interisland flying (an "
                    "Interisland Pilot's, 2.A.36.b), 9:00", False, None)
        return (two[0], two[1], f"out of domicile, {two[2]}", two[3], None) if two else (
            None, "10.E.1.a.1", "out of domicile, 2 x the preceding Duty Period", False, None)

    if home:
        prim = ((PWA_REST_II_HOME, "10.E.2.a", "in domicile before a duty that is all interisland flying (an Interisland "
                 "Pilot's, 2.A.36.b), 12:00 (10.E.1.a's 11:00 is less)", False, None) if inter else
                (PWA_REST_HOME, "10.E.1.a", "in domicile, 11:00", False, None))
        alts = []
        # review PWA-interisland-second-reading-asymmetric: the other category's rule, both ways, as out of domicile
        p_ii = prev is not None and interisland(prev["legs"])
        if prev is not None and not inter and p_ii:
            r = (PWA_REST_II_HOME, "10.E.2.a", "in domicile after a duty that was all interisland flying, 12:00", False,
                 None)
            alts.append(("as an Interisland Pilot, the duty before it being all interisland flying (2.A.36.b)", [r], [r],
                         False))
        elif prev is not None and inter and not p_ii and any(not x.get("dh") for x in prev["legs"]):
            r = (PWA_REST_HOME, "10.E.1.a", "in domicile, 11:00", False, None)
            alts.append(("as an International Pilot, the duty before it being International flying", [r], [r], False))
    else:
        prim, alts = away(mixed_grp), []  # alts: (reading, its requirements, the ones not in prim, long sit)
        adds = "if 10.E.3.a's table adds to 10.E.1.a.1 rather than replacing it (to confirm)"
        o = away(mixed_alt) if mixed_grp != mixed_alt else None
        add = bool(two and prim[0] is not None and mixed_grp and two[0] > prim[0])
        if o is not None and o[0] is not None:
            # with two > the table, [2 x the Duty Period] and [the table and it] give one verdict: one line for both
            both = add and o[:2] == two[:2]
            alts.append((f"if {sits}, so no Mixed Flying" + (f", or {adds}" if both else ""), [o], [o], True))
            add = add and not both
        if add:
            alts.append((adds, [prim, two], [two], False))
        if two and inter and not mixed_grp and not interisland(prev["legs"]) and two[0] > prim[0]:
            alts.append(("as an International Pilot, the duty before it being International flying", [prim, two],
                         [two], False))
    late = [x for x in dl if _late(x)]
    maybe = [x for x in dl if _late(x) is None]  # a station whose Local Time is not on file
    late_on = bool(late or maybe) and sched_dp >= PWA_LATE_DP

    checks = []  # (need, cite, ok, other) of each rule that applies and can be judged
    have = (f"release to report {hm(free)}" if free_how == "release" else
            f"at least {hm(free)} free (a span of your line before it is not on file)" if free_how == "unknown" else
            "no duty on file before it")
    sit = False
    need_a, cite_a, what, reg, hi = prim
    if need_a is None or (free is None and judge(need_a)[0] is None):
        not_checked.append(f"PWA rest before this duty ({cite_a}): the duty before it is not on file")
    else:
        ok, word = judge(need_a, reg, hi)
        other = []  # the readings whose verdict is another
        for label, reqs, shown, s in alts:
            got = [judge(r[0], r[3], r[4]) for r in reqs]
            oks = [g[0] for g in got]
            o_ok = False if False in oks else None if None in oks else True
            if o_ok != ok:
                other.append((label, shown, [g for r, g in zip(reqs, got) if r in shown], o_ok, s))
        van = "" if home or "van rides" in word else "; hotel time (door to door, 10.E.1.a.3) is shorter by the van rides"
        lines.append(f"PWA rest before this duty ({cite_a}): {what} needed; {have}: {word}{van}"
                     + (". For a regular crew the Company may limit the hotel rest to 9:00 (10.E.1.a.2)"
                        if reg and "10.E.1.a.2" not in word else "") + ".")
        for label, shown, got, o_ok, s in other:
            lines.append(f"? PWA rest, the other reading ({', '.join(r[1] for r in shown)}): {label}: "
                         + "; ".join(f"{r[2]} needed: {g[1]}" for r, g in zip(shown, got))
                         + ". The readings disagree, so the rest is not sure.")
            sit = sit or s
        oth = " or ".join(f"{hm(max(r[0] for r in shown))} ({max(shown, key=lambda r: r[0])[1]})"
                          for _l, shown, _g, _o, _s in other)
        ok = ok if not other else None
        if ok is True and not home and mixed_grp and two is None:
            # review PWA-mixed-rest-table-sure-when-2xDP-unknown: the 10.E.1.a.1 reading cannot be judged, so the
            # table alone is no sure 'met' (the same rest with no Mixed Flying is not checked)
            ok = None
            lines.append("? PWA rest: 2 x the preceding Duty Period (10.E.1.a.1) is not known (the duty before it is "
                         "not on file): 10.E.3.a's table alone is not sure until Ryan confirms it replaces 10.E.1.a.1.")
        checks.append((need_a, cite_a, ok, oth))
        if ok is False:
            lines.append(f"Flag: short of PWA rest ({cite_a}): {hm(free)} of {hm(need_a)}.")
    head = "PWA 10.E.1.b (18:00 rest when a segment departs 1400-0359 local and the scheduled Duty Period is 12:00+): "
    if not late_on:
        x = (late or maybe or [first])[0]
        why = (f"scheduled Duty Period {hm(sched_dp)}, under 12:00" if late or maybe else
               f"{x['frm']}-{x['to']} departs {sclock(x['dep'], x['frm'])}" if len(dl) == 1 else
               f"no segment departs 1400-0359 local; first out {sclock(x['dep'], x['frm'])}")
        lines.append(f"{head}not triggered ({why}).")
    else:
        x = (late or maybe)[0]
        ok, word = judge(PWA_REST_LATE)
        if ok is False and not late:  # only a departure whose Local Time is not on file: '?'
            ok, word = None, "? SHORT if it departs 1400-0359 there"
        if ok is False and inter:  # an Interisland Pilot's duty: 10.E.1.b names an International Pilot's Segment
            ok, word = None, "? SHORT if it applies to an Interisland Pilot's duty"
        checks.append((PWA_REST_LATE, "10.E.1.b", ok, ""))
        where = f"{x['frm']}-{x['to']} departs {sclock(x['dep'], x['frm'])}" + (
            "" if late else f"; {x['frm']} local time is not on file, so it may depart 1400-0359 there") + (
            "; this duty is all interisland flying, an Interisland Pilot's (2.A.36.b), and 10.E.1.b names an "
            "International Pilot's Segment" if inter else "")
        lines.append(f"{head}applies{'' if late and not inter else ' (?)'} ({where}, scheduled Duty Period "
                     f"{hm(sched_dp)}); {have}: {word}.")
        if ok is False:
            lines.append(f"Flag: short of PWA rest (10.E.1.b): {hm(free)} of 18:00.")
    if not checks:
        return {"txt": ""}
    oks = [c[2] for c in checks]
    ok = False if False in oks else None if None in oks else True
    need, cite, _ok, oth = max([c for c in checks if c[2] is False] or [c for c in checks if c[2] is None] or checks,
                               key=lambda c: c[0])
    if ok is False:
        flags.append("pwa_rest")
    got = hm(free) if free is not None else ""
    if not got:
        txt = f"rest met ({cite})" if ok else f"rest not on file ({cite})"
    elif oth:
        txt = f"rest {got}, {hm(need)} ({cite}) or {oth} needed: ?"
    else:
        txt = f"rest {got}, {hm(need)} needed ({cite}): " + ("met" if ok else "SHORT" if ok is False else "?")
    return {"need": hm(need), "have": got, "ok": ok, "cite": cite, "late": late_on, **({"other": oth} if oth else {}),
            "txt": txt, "_sit": sit}


def _landings(rep, first, dl, mixed, lines, flags, inter=False, end=None, mixed_alt=None, sits=""):
    """PWA 10.H.1 (10.H.3 for Mixed Flying; 10.H.2 for an Interisland Pilot's duty, inter, starting before 2200 HST and
    scheduled to end, end, after 0300 HST the next morning: 8): the duty's flown segments (a deadhead is no landing).
    One line. A start station whose Local Time is not on file: 7 may apply (a duty starting 2200-0459), so 8 to 10 is
    a '?'. mixed_alt: this duty's Mixed Flying with a long sit's leg (sits) read as a Repositioning Flight; a count the
    two readings judge apart is a '?' (_sit)."""
    n = sum(not x.get("dh") for x in dl)
    s = first["frm"]
    rm = _local_min(rep, s)
    night = (rm >= 22 * 60 or rm < 5 * 60) if known_local(s) else None
    loc = f"{rm // 60:02d}:{rm % 60:02d}"
    segs = f"{n} flown segment{'' if n == 1 else 's'}"
    ii_late = inter and end is not None and rep.astimezone(HST).hour < 22 and end > _t3(rep)

    def limit(mx):
        if mx:
            return (LANDINGS_MIXED, "10.H.3, Mixed Flying", "", "no more than 4 in a Mixed Flying Duty Period",
                    "4 at most, Mixed Flying")
        if night:
            return (LANDINGS_NIGHT, "10.H.1", f" (the duty starts {loc} local, 2200-0459)",
                    f"no more than 7 when the duty starts 2200-0459 local (it starts {loc})", "7 at most, night start")
        if ii_late:
            return (LANDINGS_II_LATE, "10.H.2", " (an Interisland Pilot's duty starting before 2200 HST and continuing "
                    "after 0300 HST)", "no more than 8 required for an Interisland Pilot's duty starting before 2200 HST "
                    "and continuing after 0300 HST the next morning (10 may be scheduled, 10.H.1)", "8 at most, past 0300")
        rule = "no more than 10 may be scheduled (11 if required to perform)"
        if night is None:
            rule += f"; 7 when the duty starts 2200-0459 local, and {s}'s local time is not on file"
        return (LANDINGS_SCHED, "10.H.1", " that may be scheduled (11 if required to perform)", rule,
                "10 may be scheduled, 11 if required")
    lim, cite, more, rule, short = limit(mixed)
    ok = n <= lim
    if ok and night is None and not mixed and n > LANDINGS_NIGHT:
        ok = None
    sit = mixed_alt is not None and mixed_alt != mixed and (n <= limit(mixed_alt)[0]) != (n <= lim)
    if sit:
        ok = None
        rule += f"; if {sits}, so no Mixed Flying, {limit(mixed_alt)[3]} ({limit(mixed_alt)[1]}): the readings disagree"
    if ok is False:
        lines.append(f"Flag: landings (PWA {cite}): {segs}, over {'the ' if more.startswith(' that') else ''}{lim}{more}.")
        flags.append("landings")
    else:
        lines.append(f"Landings (PWA {cite}): {segs}; {rule}" + (": ?" if ok is None else "") + ".")
    return {"n": n, "max": lim, "ok": ok, "_sit": sit,
            "txt": f"landings {n} ({short})" + (": OVER" if ok is False else "?" if ok is None else "")}


def _timeout(duties, idx, pilots, pilots_src, eq, known_from, busy, notes, work, pilots_sure, pilots_firm, unknown,
             domestic, dh_note, captains=None):
    if not pilots or pilots < 2 or not (0 <= idx < len(duties)):
        return None
    pilots = min(int(pilots), 4)
    ds = [_prep(d, domestic) for d in duties]
    me = ds[idx]
    if not me["fdp"]:
        return None
    rep, legs = me["report"], me["fdp_legs"]
    first, last = legs[0], legs[-1]
    flown = [x for x in legs if not x.get("dh")]
    planned = sum((timedelta(minutes=int(x["blk"])) for x in flown), timedelta(0))
    segs = len(legs)
    lines, not_checked, flags, unsure = [], [], [], []
    opts, acc_words, acc, free, free_how = _acclimation(ds, idx, busy, unknown)
    if acc is None:
        unsure.append("acclimation")
    # ---- pilots: a count that may be short and cannot fly the planned flight time is raised to the fewest that can
    rd = _reading(rep, opts, pilots, eq, segs)
    raised = ""
    if planned > rd["ft"] and not pilots_firm:
        for p2 in range(pilots + 1, 5):
            r2 = _reading(rep, opts, p2, eq, segs)
            if planned <= r2["ft"]:
                raised = (f"Flag: {pilots} pilots ({pilots_src}) may not fly {hm(planned)} of planned flight time "
                          f"(FAR 117.11): the {p2}-pilot limits are used (?); with {pilots} pilots this duty is not "
                          f"legal to dispatch. Check the crew with Crew Scheduling.")
                pilots, pilots_src, rd, captains = p2, f"{pilots_src}, raised to {p2}", r2, None
                break
    if raised or not pilots_sure:
        unsure.append("pilots")
    aug, cls, cls_sure, cls_why, best = rd["aug"], rd["cls"], rd["cls_sure"], rd["cls_why"], rd["best"]
    if aug and not cls_sure:
        unsure.append("rest class")
    oth = rd["other"]
    if oth is not None and acc is not None:
        unsure.append("clock")
    fdp_lim, ft_lim = best["lim"], rd["ft"]
    fdp_end = rep + fdp_lim
    ext_end = fdp_end + EXT
    cut = UNACCL if best["red"] else timedelta(0)
    # ---- the scheduled times
    sched_in = me["fdp_end"]
    lf = flown[-1]
    wi = work if isinstance(work, int) and 0 <= work < len(legs) and not legs[work].get("dh") else legs.index(flown[0])
    wl = legs[wi]
    span = sched_in - wl["dep"]  # the working leg's out to the duty's last flown block-in, as scheduled
    wf = wl["frm"]
    zd = zone(wf)
    cum, cum_missing = _cum(ds, idx, sched_in, known_from)
    fdp_caps = [(cum[k]["_cap"], (f"{w} ({ref})", short)) for k, _s, _l, what, w, ref, short in CUM
                if k in cum and what == "fdp"]
    # ---- PWA 10.D: the Duty Period runs from the report to 15 or 30 min after the duty's last block-in (a trailing
    # deadhead too, 2.A.19.b); its Maximum, less that debrief and the time after the last flown block-in, caps the FDP's
    dl = me["legs"]
    duty_in = dl[-1]["arr"]
    deb = RELEASE_CUSTOMS if customs(dl[-1], domestic) else RELEASE
    sched_dp = duty_in + deb - rep
    tail = duty_in - sched_in  # a trailing deadhead: the duty (and its release) runs on past the FDP's last block-in
    flown_dl = [x for x in dl if not x.get("dh")]
    # Mixed Flying (2.A.45): this duty's, and (10.D.3.a, 10.E.3.a: "a grouping containing a Mixed Flying Duty Period")
    # any duty of the same grouping (pairing); a would-be Repositioning Flight with a long sit at the neighbor island
    # counts as Mixed Flying (the lower duty and landing limits), and the rest is judged both ways (Mixed Flying needs
    # less, 10.E.3.a)
    grp = [d for d in ds if me.get("key") is not None and d.get("key") == me.get("key")] or [me]

    def mx(legs):  # the conservative reading: a long sit counts as Mixed Flying, and so does an interisland deadhead
        return mixed_flying(legs) or mixed_flying(legs, dh=True)
    mixed = mx(dl)
    mixed_grp = mixed or any(mx(d["legs"]) for d in grp if d is not me)
    mixed_alt = any(mixed_flying(d["legs"], True) for d in grp)
    long_sits = [(f"{x['frm']}-{x['to']}", sit) for d in grp for f in ([y for y in d["legs"] if not y.get("dh")],)
                 for j, x in enumerate(f) for k, sit in (_repo(f, j),) if k == "long"]
    dh_ii = [f"{x['frm']}-{x['to']}" for d in grp if mixed_flying(d["legs"], dh=True) and not mixed_flying(d["legs"])
             for x in d["legs"] if x.get("dh") and x["frm"] in HAWAII and x["to"] in HAWAII]
    inter = interisland(dl)
    one = lambda v, a, b: a if len(v) == 1 else b  # noqa: E731
    sits = " and ".join(
        ([f"{', '.join(a for a, _t in long_sits)} {one(long_sits, 'is a Repositioning Flight', 'are Repositioning Flights')}"
          f" (2.A.62)"] if long_sits else []) +
        ([f"the interisland deadhead{one(dh_ii, '', 's')} {', '.join(dh_ii)} {one(dh_ii, 'is', 'are')} no Segment "
          f"(2.A.45)"] if dh_ii else []))
    rules = ([interisland_duty(rep, duty_in + deb)] if inter else []) + (
        [pwa_duty(pilots, captains, mixed_grp, grouping=mixed_grp and not mixed)] if mixed_grp or not inter else [])
    p_sched, p_max, p_cite, p_crew, p_sure = min(rules, key=lambda r: (r[1] is None, r[1] or timedelta(0),
                                                                       r[0] or timedelta(0)))
    pwa_in = rep + p_max - deb - tail if p_max is not None else None  # the last flown block-in
    pwa_by = (f"PWA {p_cite} max duty {hw(p_max)}", f"PWA max duty {hw(p_max)}") if p_max is not None else None
    pcap = [(pwa_in, pwa_by)] if pwa_in is not None else []
    pwa_over = p_max is not None and sched_dp > p_max  # over the Maximum at the scheduled times
    # ---- legal at all: flight time, the cumulative limits and the PWA Maximum at the scheduled times
    nl, nl_short = "", ""
    if planned > ft_lim:
        nl = (f"{hm(planned)} of planned flight time is over the {hm(ft_lim)} limit (FAR 117.11, FOM 4.3.2.2): not "
              f"legal to dispatch at any time")
        nl_short = f"FT {hm(planned)} of {hm(ft_lim)}"
    elif "ft_672" in cum and cum["ft_672"]["_room"] < timedelta(0):
        nl = (f"100 h flight time in 672 h would be {cum['ft_672']['used']} at the scheduled block-in, "
              f"{hm(-cum['ft_672']['_room'])} over (FAR 117.23(b)(1), FOM 4.3.2.3): not legal to dispatch; a later "
              f"out helps only once older flying leaves the 672 h window")
        nl_short = f"100 h in 672 h: {hm(-cum['ft_672']['_room'])} over"
    else:
        for k in ("fdp_168", "fdp_672"):
            if k in cum and cum[k]["_room"] < timedelta(0):
                c, words, short = cum[k], CUM_BY[k][4], CUM_BY[k][6]
                nl = (f"{words} would be {c['used']} at the scheduled FDP end, {hm(-c['_room'])} over (FAR 117.23(c), "
                      f"FOM 4.3.2.6): not legal as scheduled, and a later out only adds to it")
                nl_short = f"{short}: {hm(-c['_room'])} over"
                break
    if not nl and pwa_over:
        nl = (f"the scheduled Duty Period {hm(sched_dp)} (the report to {int(deb.total_seconds() // 60)} min after the "
              f"last block-in, PWA 2.A.19.b) is over the PWA {p_cite} Maximum {hm(p_max)} ({p_crew}): not legal as "
              f"scheduled, the pilot may not be required to remain in it (Crew Scheduling must change it)")
        nl_short = f"PWA duty {hm(sched_dp)} of {hm(p_max)}"
    legal = not nl
    # ---- the last legal block-out (the headline) and the block-in limits
    by_fdp = (f"FDP {hm(fdp_lim)} ({'FAR 117.17, Table C' if aug else 'FAR 117.13, Table B'})", f"FDP {hm(fdp_lim)}")
    end_no, by_no = min([(fdp_end, by_fdp)] + fdp_caps, key=lambda c: c[0])
    by_ext = (f"FDP {hm(fdp_lim)} with the 2:00 extension (FAR 117.19(a))", "FDP + 2:00 ext")
    end_ex, by_ex = min([(ext_end, by_ext)] + fdp_caps, key=lambda c: c[0])
    far_no, far_ex = end_no, end_ex  # FAR 117 alone
    # the PWA Maximum caps both (no pilot option past an International Maximum, 10.D.4 is Interisland; an extension
    # stays within the CBA, FOM 4.3.2.5)
    end_no, by_no = min([(end_no, by_no)] + pcap, key=lambda c: c[0])
    end_ex, by_ex = min([(end_ex, by_ex)] + pcap, key=lambda c: c[0])
    to = last["to"]
    rel_d = tail + deb  # release after a block-in of the last flown leg: the trailing deadhead and its debrief
    # the block-in limits with the leg out on time: flight time from the scheduled out, the FDP, every cap
    before = sum((timedelta(minutes=int(x["blk"])) for x in flown[:-1]), timedelta(0))
    ft_end = lf["dep"] + ft_lim - before
    ft_by = (f"{hm(ft_lim)} flight time (FAR 117.11)", f"{hm(ft_lim)} flight time")
    caps = [(cum[k]["_cap"], (f"{w} ({ref})", short)) for k, _s, _l, _w, w, ref, short in CUM if k in cum]
    no_at, no_by = min([(fdp_end, by_fdp), (ft_end, ft_by)] + caps + pcap, key=lambda c: c[0])
    ex_at, ex_by = min([(ext_end, by_ext), (ft_end, ft_by)] + caps + pcap, key=lambda c: c[0])
    pwa_binds = [k for k, b in (("no_ext", by_no), ("ext", by_ex)) if pwa_by is not None and b is pwa_by] if legal else []
    pwa_counts = bool(pwa_binds) or pwa_by in (no_by, ex_by) or nl_short.startswith("PWA")
    if not p_sure and pwa_counts:
        unsure.append("PWA crew")  # the Captains of a 4-pilot crew not known: 10.D.1.c, not 10.D.1.d, is used
    # PWA rest (10.E) and landings (10.H) before the basis: a long sit they judge apart makes the box unsure too
    k_me = next(j for j, d in enumerate(grp) if d is me)
    land = tuple(sum(not x.get("dh") for d in g for x in d["legs"]) for g in (grp[:k_me], grp))
    r_lines, r_nc, r_flags, l_lines, l_flags = [], [], [], [], []
    pr = _pwa_rest(ds, idx, first, dl, sched_dp, free, free_how, busy, known_from, pilots, r_lines, r_nc, r_flags,
                   mixed_grp, land, mixed_alt, sits, inter)
    landings = _landings(rep, first, dl, mixed, l_lines, l_flags, inter, duty_in + deb, mixed_flying(dl, True), sits)
    # review PWA-rest-unsure-box-inconsistent: only what moves a last out makes the box '?'; a rest or a landings count
    # that is not sure (whatever the reason) shows as its own chip on the box (flags rest_q, landings_q)
    if mixed_grp != mixed_alt and pwa_counts and p_cite == "10.D.3":
        unsure.append("Mixed Flying")  # a long sit or an interisland deadhead: Mixed Flying (2.A.45) or not
    sure = not unsure

    def lt(at, by):
        loc, r = at.astimezone(zd), rep.astimezone(zd)
        return {"at": at.isoformat(), "txt": clock(at, zd, wf), "hst": clock(at), "day": day(at),
                "wd": f"{loc:%a}" if loc.date() != r.date() else "", "z": f"{at.astimezone(timezone.utc):%H:%M}Z",
                "by": by[0], "short": by[1], "early": at < wl["dep"], "sure": sure,
                "leg": f"{wl['frm']}-{wl['to']}", "pwa": by is pwa_by}
    last_out = lt(end_no - span, by_no) if legal else None
    last_ext = lt(end_ex - span, by_ex) if legal else None
    if ex_at != ext_end:
        ex_by = (f"{ex_by[0].split(' (')[0]}; FDP with 2:00 extension {clock(ext_end)}", ex_by[1])

    def res(at, by):
        return {"at": at.isoformat(), "txt": clock(at), "day": day(at), "local": sclock(at, to),
                "z": f"{at.astimezone(timezone.utc):%H:%M}Z", "by": by[0], "short": by[1],
                "release_at": (at + rel_d).isoformat(), "release_txt": clock(at + rel_d), "sure": sure,
                "legal": legal}
    zsn = first["frm"]
    zs = zone(zsn)
    # ---- the basis, one line a rule
    lines.append(f"Report {clock(rep, zs, zsn)} ({clock(rep)} {day(rep)}): {me.get('report_txt') or 'from the schedule'}.")
    lines.append(f"Acclimation (FAR 117.3, FOM 4.3.2.4.6): {acc_words}.")
    roster = f"{pilots} pilots ({pilots_src})" if pilots_src else f"{pilots} pilots"
    kind = "augmented, Table C (FAR 117.17" if aug else "unaugmented, Table B (FAR 117.13"
    lines.append(f"{roster}{'' if pilots_sure else ' (?)'}: {kind}, FOM 4.3.2.4).")
    lines.extend(n for n in notes if n)
    if raised:
        lines.append(raised)
        flags.append("pilots")
    alt = {str(c): clock(rep + _hrs(v) - cut) for c, v in best["alt"].items() if c != cls}
    if aug:
        def cls_out(c):  # a class's last out, no later than the cumulative FDP caps and the PWA one
            return clock(min([rep + _hrs(best["alt"][int(c)]) - cut] + [a for a, _b in fdp_caps + pcap]) - span, zd, wf)
        other_cls = ", ".join(f"Class {c} {alt[c]} (last out {cls_out(c)})" for c in sorted(alt))
        lines.append(f"Rest facility: {cls_why}{'' if cls_sure else ' (?)'}. Class {cls} ends {clock(fdp_end)}; "
                     f"{other_cls}" + (" (Class 1 assumes the bunks are usable: a deferred crew rest lowers it)."
                                       if cls == 1 else "."))
        if segs > AUG_MAX_SEGMENTS:
            lines.append(f"Flag: {segs} segments in an augmented FDP, FOM 4.3.2.4.2 allows 3 (a diversion's aside).")
            flags.append("segments")
    dh = [x for x in legs if x.get("dh")]
    lines.append(f"This FDP: {segs} segment{'s' if segs > 1 else ''}"
                 + (f" ({len(dh)} deadhead{'s' if len(dh) > 1 else ''}, counted: conservative)" if dh else "")
                 + f", {hm(planned)} of planned flight time. Deadheads: "
                 + (dh_note or "FLICA's pairing page lists none and the pairings package was not matched to this duty, "
                                "so one there would not be counted") + ".")
    row_txt = f"Table {'C' if aug else 'B'} row {best['row']} ({best['clock']})"
    cls_txt = (f", Class {cls}{'' if cls_sure else ' ?'}, {pilots} pilots" if aug
               else f", {segs} segment{'s' if segs > 1 else ''}")
    rule = "FAR 117.17" if aug else "FAR 117.13"
    lines.append(f"{row_txt}{cls_txt}: {hm(_hrs(best['base']))}{', less 0:30' if best['red'] else ''} = FDP "
                 f"{hm(fdp_lim)}, ends {clock(fdp_end)} {day(fdp_end)} ({rule})"
                 f"; with the 2:00 extension {clock(ext_end)} {day(ext_end)}.")
    other = None
    if oth is not None:
        o_end = min([rep + oth["lim"]] + [c for c, _b in fdp_caps + pcap])
        other = {"clock": oth["clock"], "row": oth["row"], "limit": hm(oth["lim"]),
                 "last_out_txt": clock(o_end - span, zd, wf), "last_out_ext_txt": clock(min(
                     [rep + oth["lim"] + EXT] + [c for c, _b in fdp_caps + pcap]) - span, zd, wf)}
        why = ("FOM 4.3.2.4 enters the tables on \"the report time at local domicile or the local time in the theater\" "
               "and the FAA lets a carrier use either clock; which one Crew Scheduling uses is not on file, so the "
               "earlier is shown (?)" if acc else "the acclimation line says why the lower is used")
        lines.append(f"Other reading: {oth['clock']} gives row {oth['row']}, FDP {hm(oth['lim'])}"
                     + (f" and {hm(oth['fa'])} flight time" if not aug and oth["fa"] != ft_lim else "")
                     + (f", last out {other['last_out_txt']} ({other['last_out_ext_txt']} with the extension)"
                        if legal else "") + f". {why[0].upper()}{why[1:]}.")
    if legal:
        lines.append(f"Last out (block-out): the FDP end"
                     + (", or the PWA duty limit's last block-in when earlier," if pwa_binds else "")
                     + f" less the scheduled {hm(span)} from this leg's out "
                     f"({clock(wl['dep'], zd, wf)}) to the duty's last block-in ({clock(sched_in)}): {last_out['txt']} "
                     f"({last_out['hst']} {last_out['day']}) without an extension, {last_ext['txt']} ({last_ext['hst']} "
                     f"{last_ext['day']}) with it ("
                     + (f"{last_out['short']} for both" if last_out["short"] == last_ext["short"] else
                        f"{last_out['short']}; {last_ext['short']}") + ").")
        if last_out["early"]:
            lines.append(f"Flag: the scheduled out {clock(wl['dep'], zd, wf)} is after the last out without an extension: "
                         f"the duty as scheduled is over its limit; check with Crew Scheduling.")
            flags.append("early")
    else:
        lines.append(f"Not legal: {nl}.")
        sched_fdp = sched_in - rep
        if sched_fdp > fdp_lim:  # FAR 117 over as scheduled too: said, as the last out line would with a legal duty
            lines.append(f"Flag: FAR 117 is over as scheduled too: the FDP from the report to the last flown block-in "
                         f"({clock(sched_in)}) is {hm(sched_fdp)}, over the {hm(fdp_lim)} limit ({hm(fdp_lim + EXT)} with "
                         f"the 2:00 extension, FAR 117.19(a); {rule}).")
        if pwa_over and not nl_short.startswith("PWA"):  # and the PWA Maximum, when FAR 117 is what makes it not legal
            lines.append(f"Flag: the PWA {p_cite} Maximum is over as scheduled too: the scheduled Duty Period "
                         f"{hm(sched_dp)} of {hm(p_max)} ({p_crew}; to {int(deb.total_seconds() // 60)} min after the "
                         f"last block-in, 2.A.19.b): Crew Scheduling must change it.")
    # ---- PWA 10.D: the duty limit by crew (P1)
    deb_m = int(deb.total_seconds() // 60)
    pwa_out = pwa_in - span if pwa_in is not None else None
    over_s = p_sched is not None and sched_dp > p_sched
    if p_max is None:
        lines.append(f"PWA duty limit ({p_cite}): an {p_crew} has no PWA duty hours of its own: Part 117 Table C "
                     f"governs, and it may not be scheduled past it (the FDP above). PWA duty scheduled "
                     f"{hm(sched_dp)}.")
    else:
        if not legal and nl_short.startswith("PWA"):
            bind = "the scheduled Duty Period is over it: not legal"
        elif not legal and pwa_over:
            bind = "the scheduled Duty Period is over it too: not legal (above)"
        elif not legal:
            bind = "no last out, not legal (above)"
        elif pwa_binds:
            bind = ("binding with and without an extension" if len(pwa_binds) == 2 else
                    "binding with the extension") + (f" (FAR 117 alone: {clock(far_no - span, zd, wf)}, "
                                                     f"{clock(far_ex - span, zd, wf)} with the extension)")
        else:
            bind = "not binding (FAR 117 is earlier)"
        lines.append(f"PWA duty limit ({p_cite}): {p_crew}{'' if p_sure else ' (?)'}: Scheduled {hm(p_sched)}, "
                     f"Maximum {hm(p_max)} of Duty Period (Local Times, 2.A.43; from the later of the scheduled and "
                     f"actual report, 10.D.5, to {deb_m} min after the last block-in"
                     f"{', clearing customs' if deb == RELEASE_CUSTOMS else ''}, 2.A.19.b). From the report "
                     f"{clock(rep, zs, zsn)} it ends by {clock(rep + p_max)} {day(rep + p_max)}, the last block-in by "
                     f"{clock(rep + p_max - deb)}"
                     + (f" ({clock(pwa_in)} for the last flown leg, {hm(tail)} before the trailing deadhead's)"
                        if tail > timedelta(0) else "")
                     + f", so the last out is {clock(pwa_out, zd, wf)} ({clock(pwa_out)} {day(pwa_out)}): {bind}.")
        lines.append(f"{'Flag: ' if over_s and legal else ''}PWA duty scheduled {hm(sched_dp)} of {hm(p_sched)} "
                     f"({p_cite})" + (": scheduled past the PWA limit (the company may not schedule it; not a timeout)"
                                      if over_s else "") + ".")
        if over_s and legal:
            flags.append("pwa_sched")
        if p_cite.startswith("10.D.2"):
            opt = rep + p_max
            lines.append(f"Pilot option (10.D.4): departing {wf}, not your domicile, you may at your option stay past "
                         f"the Interisland Maximum if it has not passed at block-out, so block out before "
                         f"{clock(opt, zd, wf)}; the last outs above do not use the option." if wf != DOMICILE else
                         "Pilot option (10.D.4): none for a departure from HNL, your domicile.")
            lines.append("No 5.A.6 transfer time is added (none serves HNL) and a FAR 117.19 extension stays within the "
                         "CBA (FOM 4.3.2.5): the PWA Maximum caps both last outs.")
        else:
            lines.append("No 5.A.6 transfer time is added (none serves HNL"
                         + ("; 10.D.1.b.2 bars them for an IRO Crew" if p_cite == "10.D.1.b.1" else "")
                         + "), no pilot option exceeds an International Maximum (10.D.4 is Interisland) and a FAR "
                           "117.19 extension stays within the CBA (FOM 4.3.2.5): the PWA Maximum caps both last outs.")
    repo = [f"{x['frm']}-{x['to']}" for j, x in enumerate(flown_dl) if _repositioning(flown_dl, j)]
    if repo and not mixed:
        lines.append(f"Not Mixed Flying (2.A.45): {repo[0]} is a Repositioning Flight (2.A.62; a sit of 2:00 or less "
                     f"at the neighbor island is read as its minimal delay).")
    if mixed_grp and not mixed:
        lines.append("PWA 10.D.3.a: this grouping holds a Mixed Flying Duty Period (2.A.45) and its limits cover \"a "
                     "pilot assigned to a grouping containing\" one, so this duty takes them too (10.H.3's 4 landings "
                     "are per Mixed Flying Duty Period).")
    if mixed_grp != mixed_alt and long_sits:
        lines.append(f"? Mixed Flying (2.A.45): {', '.join(f'{a} (sit {hm(t)})' for a, t in long_sits)} would be a "
                     f"Repositioning Flight (2.A.62) but for a sit at the neighbor island over the 2:00 read as its "
                     f"minimal delay: counted as Mixed Flying for the duty limit and the landings (the lower limits, "
                     f"conservative); the rest before this duty is judged both ways (out of domicile Mixed Flying needs "
                     f"less, 10.E.3.a), not sure where they disagree.")
    if mixed_grp != mixed_alt and dh_ii:
        lines.append(f"? Mixed Flying (2.A.45): the interisland deadhead{one(dh_ii, '', 's')} {', '.join(dh_ii)} may be "
                     f"its interisland Segment (2.A.62 positions \"such aircraft, or operating crew\"; whether 2.A.45 "
                     f"counts a deadhead as a Segment is not on file, Ryan to confirm): counted as Mixed Flying for the "
                     f"duty limit and the landings (the lower limits, conservative); the rest before this duty is judged "
                     f"both ways, not sure where they disagree.")
    if inter:
        not_checked.append("This duty is all interisland flying (an Interisland Pilot's, PWA 2.A.36.b): one who "
                           "completes a Duty Period after 0200 may not start another that calendar day (10.D.2.c), not "
                           "checked against the duties before and after it")
    fa_src = "FAR 117.11, FOM 4.3.2.2" if aug else (f"Table A row {rd['fa_by']['fa_row']} ({rd['fa_by']['clock']}), "
                                                    f"FAR 117.11")
    spare = ft_lim - planned
    lines.append(f"Flight time {hm(planned)} of {hm(ft_lim)} ({fa_src}): "
                 + (f"{hm(spare)} spare, a duration, so it does not move the last out" if spare >= timedelta(0)
                    else f"{hm(-spare)} over")
                 + f". Out on time ({sclock(lf['dep'], lf['frm'])}"
                 + (f", {clock(lf['dep'])}" if sclock(lf["dep"], lf["frm"]) != clock(lf["dep"]) else "")
                 + (f", after {hm(before)} flown earlier" if before else "")
                 + f") the block-in is due by {clock(ft_end)}; it moves with the actual out. An FDP extension does not "
                   f"extend flight time (FOM 4.3.2.2).")
    lines.append(f"Extension (FAR 117.19(a), FOM 4.3.2.5): up to 2:00 before takeoff, for unforeseen operational "
                 f"circumstances, the PIC and the company agreeing: FDP to {clock(ext_end)} {day(ext_end)}.")
    lines.append("After takeoff (FAR 117.19(b), FOM 4.3.2.5.2): the FDP, the flight time and the cumulative limits may "
                 "be exceeded as needed to land at the destination or an alternate: no fixed time.")
    for key, *_ in CUM:
        if key in cum:
            lines.append(cum[key]["line"] + ".")
    if any(k in cum for k in ("fdp_168", "fdp_672")):
        lines.append("The cumulative FDP limits cap an extension before takeoff (FAR 117.19(a), 117.23(c)); after "
                     "takeoff they may be exceeded to land (FOM 4.3.2.3, 4.3.2.6).")
    # ---- rest before this FDP (FAR 117.25(e) and (b))
    rest = {}
    if free_how is None:
        if known_from is not None and known_from <= rep - REST_MIN:
            rest.update(free="", ok=True)
            lines.append("Rest before this FDP (FAR 117.25(e), FOM 4.3.2.7): no duty on file in the 10 h before it: met.")
        else:
            not_checked.append("10 h rest before this FDP (FAR 117.25(e), FOM 4.3.2.7): the duty before it is not on "
                               "file")
    else:
        gap_busy = bool(_hits(busy, rep - free, rep))
        ok = True if free >= REST_MIN and not gap_busy else None if free >= REST_MIN or free_how == "unknown" else False
        rest.update(free=hm(free), ok=ok)
        since = "the last release" if free_how == "release" else "the end of a span of your line not on file (at least)"
        lines.append(f"Rest before this FDP (FAR 117.25(e), FOM 4.3.2.7): {hm(free)} free from duty since {since}, 10 h "
                     f"needed: " + ("met" if ok else "SHORT, check with Crew Scheduling" if ok is False else
                                    "? a schedule item inside it may be duty" if gap_busy else "? not known") + ".")
        if ok is False:
            flags.append("rest")
    if free_how == "release":  # the longer FAR rests that may apply (FAR 117.25(g) and (d)): each its own line
        gap_busy = bool(_hits(busy, rep - free, rep))
        oks, top = [rest["ok"]], REST_MIN
        dhr, thr = _dh_rest(ds, idx), _theater_rest(ds, idx, unknown)
        for need, firm, cite, head, what in (
                (dhr["need"], dhr["sure"], "FAR 117.25(g)", "Rest after deadhead transportation (FAR 117.25(g), FOM "
                 "4.3.2.10)",
                 f"{dhr['what']}, {hm(dhr['span'])} from its report to its last block-in, over its Table B FDP "
                 f"{hm(dhr['limit'])}: a rest as long as the deadhead transportation ({hm(dhr['length'])}"
                 f"{', from the report' if 'only' in dhr['what'] else ''}), no less than 10 h")
                if dhr else (None,) * 5,
                (THEATER_REST, thr["applies"], "FAR 117.25(d)", "Rest on return to home base (FAR 117.25(d), FOM "
                 "4.3.2.11)",
                 f"{hm(thr['away'])} away from HNL ({clock(thr['start'])} {day(thr['start'])} to release "
                 f"{clock(thr['end'])} {day(thr['end'])}, "
                 f"{'more than 168 h' if thr['away'] > AWAY_MAX else 'at least: it may be more than 168 h'}) and "
                 + (f"{thr['far']} is {round(thr['deg'])} deg from HNL (more than 60)" if thr["deg"] > THEATER_DEG
                    else "a station with no longitude on file may be more than 60 deg away")
                 + ": 56 consecutive hours, holding three physiological nights")
                if thr else (None,) * 5):
            if need is None:
                continue
            top = max(top, need) if firm else top  # a rule that may not apply says its need in its line only
            ok = (True if not gap_busy else None) if free >= need else False if firm else None
            oks.append(ok)
            why = thr["why"] if head.startswith("Rest on return") else [] if firm else [
                "the Table B FDP of the duty before it or which of its deadheads count is not sure"]
            lines.append(f"{head}: {what}{' (? ' + '; '.join(why) + ')' if why else ''}; {hm(free)} free: "
                         + ("met" if ok else "SHORT, check with Crew Scheduling" if ok is False else
                            "? a schedule item inside it may be duty" if free >= need else
                            f"? SHORT of {hm(need)} if it applies") + ".")
            if ok is False:
                lines.append(f"Flag: short of FAR rest ({cite}): {hm(free)} of {hm(need)}.")
                if "rest" not in flags:
                    flags.append("rest")
            if head.startswith("Rest on return"):
                not_checked.append("The three physiological nights of the 56 h rest on return to home base (FAR "
                                   "117.25(d), FOM 4.3.2.11): local nights, not on the schedule")
        if top > REST_MIN:
            rest["need"] = hm(top)
        rest["ok"] = False if False in oks else None if None in oks else True
    wk = _free_week(ds, idx, busy, known_from, rep)
    if wk is None:
        not_checked.append("30 h free from duty in the 168 h before this FDP (FAR 117.25(b), FOM 4.3.2.9): your line in "
                           "that window is not all on file")
    else:
        sure_free, may_free = wk
        rest["week"] = hm(sure_free)
        rest["week_ok"] = True if sure_free >= FREE_WEEK else None if may_free >= FREE_WEEK else False
        lines.append(f"30 h free in the 168 h before this FDP (FAR 117.25(b), FOM 4.3.2.9): longest free period "
                     f"{hm(sure_free)}" + (": met" if sure_free >= FREE_WEEK else
                                           f" ({hm(may_free)} if the schedule items in it are not duty): ?"
                                           if may_free >= FREE_WEEK else ": SHORT, check with Crew Scheduling") + ".")
        if may_free < FREE_WEEK:
            flags.append("week")
    lines.extend(r_lines + l_lines)
    not_checked.extend(r_nc)
    flags.extend(r_flags + l_flags)
    # review PWA-rest-unsure-box-inconsistent: a rest or a landings count that is not sure is a chip of its own
    if not any(f in flags for f in ("rest", "week", "pwa_rest")) and (
            None in (rest.get("ok", True), rest.get("week_ok", True)) or (pr.get("ok", True) is None and free is not None)):
        flags.append("rest_q")
    if landings["ok"] is None:
        flags.append("landings_q")
    no, ex = res(no_at, no_by), res(ex_at, ex_by)
    cust = ", clearing customs" if deb == RELEASE_CUSTOMS else ""
    after = (f"the trailing deadhead's block-in ({dl[-1]['frm']}-{dl[-1]['to']}, due {hm(tail)} after the last flown "
             f"one)" if tail > timedelta(0) else "block-in")
    lines.append(f"Duty ends {deb_m} min after {after}{cust} (PWA 2.A.19.b): release "
                 f"{clock(end_no + rel_d)} at the FDP end without an extension, {clock(end_ex + rel_d)} with one.")
    if (dl[-1]["frm"] not in (US_STATIONS | domestic)) != (deb == RELEASE_CUSTOMS):  # watcher.release_customs differs
        lines.append(f"Customs (2.A.19.b): {dl[-1]['frm']}-{dl[-1]['to']} " + (
            "crosses a border (or a country not on file), so the debrief is 30 min here; the Watcher's other checks "
            "(FAR 117 rows, Recall, smart push) count 30 min only for a leg from outside the US, so their release for "
            "this duty is 15 min earlier" if deb == RELEASE_CUSTOMS else
            "stays in one country, so no customs here; the Watcher's other checks (FAR 117 rows, Recall, smart push) "
            "count 30 min for any leg from outside the US, so their release for this duty is 15 min later") + ".")
    not_checked.append("An extension of more than 30 min since your last 30 h free from duty (FAR 117.19(a)(2), FOM "
                       "4.3.2.5): not on file; with one, no pre-takeoff extension")
    not_checked.extend(cum_missing)
    if aug:
        not_checked.append("In-flight rest of an augmented FDP (FOM 4.3.2.4.2): 2 consecutive hours in the second half "
                           "of the FDP for the pilot flying the landing, 90 min for the pilot monitoring")
    not_checked.append("The 8 h sleep opportunity of the rest before this FDP (FAR 117.25(e))")
    not_checked.append("Flying outside your FLICA line (another employer, Part 91) in the cumulative limits (FOM "
                       "2.7.4)")
    not_checked.append("1000 h flight time in 365 days (FAR 117.23(b)(2))")
    if pilots == 3:
        not_checked.append(PWA_NC_IRO)
    not_checked.append(PWA_NC)
    ft_txt = f"{hm(planned)} of {hm(ft_lim)}"
    if p_max is None:
        p_txt = f"no PWA duty hours ({p_cite}): Part 117 Table C; scheduled duty {hm(sched_dp)}"
    else:
        p_end = ("over the Maximum: not legal" if not legal and nl_short.startswith("PWA") else
                 "over the Maximum too (not legal)" if not legal and pwa_over else
                 "no last out (not legal)" if not legal else
                 f"last out {clock(pwa_out, zd, wf)} " + ("(binds)" if len(pwa_binds) == 2 else
                                                          "(binds with the extension)" if pwa_binds else
                                                          "(not binding: FAR 117 is earlier)"))
        sch = (f"scheduled duty {hm(sched_dp)}, over the {hm(p_sched)} Scheduled limit (PAST)" if over_s else
               f"scheduled duty {hm(sched_dp)} (Scheduled limit {hm(p_sched)})")
        p_txt = f"{sch}, Maximum {hm(p_max)} ({p_cite}{'' if p_sure else '?'}): {p_end}"
    pwa = {"crew": p_crew, "cite": p_cite, "sure": p_sure, "mixed": mixed, "mixed_grouping": mixed_grp,
           "scheduled": hm(p_sched) if p_sched is not None else "", "maximum": hm(p_max) if p_max is not None else "",
           "duty": hm(sched_dp), "debrief": hm(deb), "binds": pwa_binds,
           "end_txt": clock(rep + p_max) if p_max is not None else "",
           "in_txt": clock(rep + p_max - deb) if p_max is not None else "",
           "last_out_txt": clock(pwa_out, zd, wf) if pwa_out is not None else "",
           "last_out_hst": clock(pwa_out) if pwa_out is not None else "",
           "rest": {k: v for k, v in pr.items() if k != "txt" and not k.startswith("_")},
           "landings": {k: v for k, v in landings.items() if k != "txt" and not k.startswith("_")},
           "txt": " \u00b7 ".join([p_txt, pr.get("txt") or "rest not on file", landings["txt"]])}
    return {
        "legal": legal, "not_legal": nl, "not_legal_short": nl_short, "sure": sure, "unsure": unsure, "flags": flags,
        "last_out": last_out, "last_out_ext": last_ext,
        "no_ext": no, "ext": ex,
        "fdp": {"limit": hm(fdp_lim), "end_at": fdp_end.isoformat(), "end_txt": clock(fdp_end),
                "end_day": day(fdp_end), "ext_end_at": ext_end.isoformat(), "ext_end_txt": clock(ext_end),
                "ext_end_day": day(ext_end), "in_txt": clock(end_no), "ext_in_txt": clock(end_ex),
                "in_day": day(end_no), "ext_in_day": day(end_ex),
                "release_txt": clock(end_no + rel_d), "ext_release_txt": clock(end_ex + rel_d),
                "table": "C" if aug else "B", "row": f"{best['row']} ({best['clock']})", "acclimated": acc,
                "pilots": pilots, "pilots_from": pilots_src, "pilots_sure": bool(pilots_sure) and not raised,
                "rest_class": cls, "rest_class_sure": cls_sure if aug else None, "segments": segs, "alt": alt,
                "other": other},
        "ft": {"limit": hm(ft_lim), "planned": hm(planned), "spare": hm(spare), "txt": f"{ft_txt} ({hm(spare)} spare)"
               if spare >= timedelta(0) else f"{ft_txt} ({hm(-spare)} over)", "short": f"FT {ft_txt}",
               "end_at": ft_end.isoformat(), "end_txt": clock(ft_end),
               "from": f"scheduled out {sclock(lf['dep'], lf['frm'])}"},
        "cum": {k: {f: v for f, v in c.items() if f not in ("line", "_cap", "_room")} for k, c in cum.items()},
        "rest": rest,
        "report_txt": clock(rep), "report_day": day(rep), "sched_in_txt": clock(sched_in),
        "sched_out_txt": clock(wl["dep"], zd, wf), "pwa": pwa, "lines": lines, "not_checked": not_checked,
    }
