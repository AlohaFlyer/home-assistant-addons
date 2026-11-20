"""1.7.20 (Ryan, Nov 20, 2026, flying HA829 JFK-HNL on H3606: "I need this page to calculate per FAR 117 and PWA when I
timeout, both for if I extend or if I do not ... Make sure it's accurate. Keep in mind the flight time, and number of
crew and rest"): the latest block-in of the working leg's flight duty period (FDP), without and with an extension, for
the Working Flight card (working.py puts it on sensor.<prefix>_working_flight as `timeout`). Pure: no I/O, no clock of
its own; every time is an aware datetime. No FLICA load: it reads the pilot's own trips and the pairings package.

Rules (FOM 125.4 4.3.2, which reproduces 14 CFR 117 and its Tables A, B and C; FOM 5.1.23.7 and 5.1.23.8 crew rest;
PWA 2.19.b duty period):
- Acclimation (117.3, FOM 4.3.2.4.6). A theater is a span of 60 degrees of longitude (LON, every station in
  working.ZONES). The pilot's duties are walked in time order from acclimated to HNL. A report within 60 degrees of
  the acclimated theater's reference: acclimated. Else he becomes acclimated to the new theater (its report station
  is the new reference) after 36 consecutive hours free from duty before the report, or 72 h in that theater since
  the block-in that brought him there. Else not acclimated: Tables A, B and C are entered on the last acclimated
  theater's clock and the FDP limit is 30 min less (117.13(b), 117.17(b), FOM 4.3.2.4). A station with no longitude,
  or a schedule item that may be duty inside the 36 h: the lower of the readings, marked '?'.
- Which clock of an acclimated theater: 117 and FOM 4.3.2.4 say "the local time in the theater to which [he] is
  acclimated", which spans up to four time zones. Away from the reference station both readings are worked out (the
  reference station's clock and the report station's own, daylight time included) and the lower limit is used.
- Pilots: the own trip roster's CA, FO, RO and SO seats (an OPEN one too), else the package crew line (CA01FO01RO01 is
  3). 2 pilots: Table B (117.13; every leg of the FDP counts as a segment, a deadhead too) and Table A flight time
  (117.11). 3 or 4: Table C (117.17) and 13 or 17 h flight time (117.11, FOM 4.3.2.2); more than 3 segments is flagged
  (FOM 4.3.2.4.2). Unknown: no timeout.
- Rest facility (FOM 5.1.23.7, 5.1.23.8): A330 (eq 33x) LDMCR bunks 1 and 4 and 787 (78x) OFCR: Class 1 with 3 pilots;
  with 4 the FOM also hard-blocks a cabin seat (Table 5.1.23.8.1(1)), so Class 2. Other or unknown equipment: Class 3,
  marked '?'. Class 1 assumes the bunks are usable; the Class 2 and 3 ends are given too.
- FDP end = report + limit; with the extension (117.19(a), FOM 4.3.2.5) 2:00 more, before takeoff only. After takeoff
  (117.19(b)) the FDP, the flight time and the cumulative limits may be exceeded as needed to land: no fixed time.
- Flight time end = the last flown leg's scheduled block-out + (limit - the duty's earlier flown block): not moved by
  an FDP extension (FOM 4.3.2.2, 4.3.2.3: no takeoff without a reasonable expectation to land within it).
- Cumulative (117.23(b)(1), (c)(1), (c)(2); FOM 4.3.2.3, 4.3.2.6): 100 h flight time in 672 h, 60 h FDP in 168 h and 190
  h FDP in 672 h, each from the duty's scheduled last block-in: cap = that block-in + what is left (the window only
  drops old flying as it moves, so this is the earliest the cap can be). Only when the line on file covers the whole
  window (known_from), else listed under not_checked.
- Results: no_ext = min(FDP end, flight time end, caps); ext = min(FDP end + 2:00, flight time end, caps), with the
  rule that binds. PWA 2.19.b.2: the duty period ends 15 min after block-in, 30 when clearing customs (arriving in the
  US from a station outside it, the Watcher's US list): each result's release. PWA Section 10 (Hours of Service) is not
  on file: never a PWA duty limit here, it is listed under not_checked.
"""
import re
from datetime import timedelta, timezone

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
       "LNK": -96.8}
THEATER_DEG = 60
FREE_ACCL, STAY_ACCL = timedelta(hours=36), timedelta(hours=72)
UNACCL = timedelta(minutes=30)
EXT = timedelta(hours=2)
RELEASE, RELEASE_CUSTOMS = timedelta(minutes=15), timedelta(minutes=30)  # PWA 2.19.b.2
# FW-0042 review: the stations a leg into the US comes from without clearing customs (watcher.US_STATIONS is this set)
US_STATIONS = frozenset(("HNL", "OGG", "KOA", "ITO", "LIH", "ANC", "LAX", "SFO", "SEA", "SAN", "OAK", "SMF", "LAS",
                         "PDX", "SJC", "ONT", "LGB", "PHX", "SLC", "DEN", "ORD", "DFW", "AUS", "MSP", "IAH", "JFK",
                         "BOS", "MCO", "IAD", "ATL", "MIA", "EWR"))
PILOT_SEATS = ("CA", "FO", "RO", "SO")  # pot.PILOT_SEATS, crewidx.PILOT_POS: an OPEN seat is a required seat
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
PWA10 = "PWA Section 10 (Hours of Service) duty limits: not on file, not checked"


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


def hm(td):
    """A duration as 'H:MM' ('-0:20' below zero)."""
    m = int(round(td.total_seconds() / 60))
    s = "-" if m < 0 else ""
    m = abs(m)
    return f"{s}{m // 60}:{m % 60:02d}"


def _hrs(h):
    return timedelta(minutes=int(round(h * 60)))


def clock(dt, z=None):
    """'16:40 HST' (HST, Hawaii's fixed UTC-10, by default), '08:40 EST' on a station's zone."""
    if z is None or z is HST:
        return f"{dt.astimezone(HST):%H:%M} HST"
    loc = dt.astimezone(z)
    return f"{loc:%H:%M} {LO.abbr(loc)}"


def day(dt):
    """'Fri Nov 20' in HST."""
    h = dt.astimezone(HST)
    return f"{h:%a %b} {h.day}"


def _row(table, minute):
    return next(r for r in table if r[0] <= minute <= r[1])


def _label(r):
    return f"{r[0] // 60:02d}{r[0] % 60:02d}-{r[1] // 60:02d}{r[1] % 60:02d}"


def pilots_of(roster, code=""):
    """(number of pilots, 'roster' | 'package' | '') from the own trip roster ('CA Doe, Jane (12345)', an OPEN seat too;
    [pos, name] or {pos}) when it lists 2 or more pilot seats, else the package crew line ('CA01FO01RO01' is 3)."""
    n = 0
    for c in roster if isinstance(roster, (list, tuple)) else []:
        pos = (c.get("pos") if isinstance(c, dict) else c[0] if isinstance(c, (list, tuple)) and c
               else str(c).strip().split(" ", 1)[0] if isinstance(c, str) else "")
        n += str(pos or "").upper() in PILOT_SEATS
    if n >= 2:
        return n, "roster"
    m = sum(int(x) for x in re.findall(r"(?:CA|FO|RO|SO)(\d{1,2})", str(code or "").upper()))
    return (m, "package") if m >= 2 else (None, "")


def rest_class(eq, pilots):
    """(class 1 to 3, sure, why) of the crew rest for an augmented crew (FOM 5.1.23.7, 5.1.23.8)."""
    e = str(eq or "").strip().upper()
    kind = "A330" if e.startswith("33") else "787" if e.startswith("78") else ""
    if not kind:
        return 3, False, (f"equipment {e or 'not on file'}: rest facility class not known, Class 3 used (the lowest "
                          f"Table C value)")
    where = "LDMCR bunks 1 and 4 (FOM 5.1.23.8)" if kind == "A330" else "OFCR (FOM 5.1.23.7)"
    if pilots >= 4:
        seat = "3C or 3G" if kind == "A330" else "9A and 9J"
        return 2, True, (f"{kind} {where} with 4 pilots: the FOM also hard-blocks cabin seat {seat} (Table "
                         f"5.1.23.8.1(1)), so Class 2 is used (a rest may be taken in that seat)")
    return 1, True, f"{kind} {where}: Class 1 rest facility with 3 pilots"


def customs(leg):
    """PWA 2.19.b.2: True when the leg arrives in the US from a station outside it (the Watcher's US list)."""
    return leg["to"] in US_STATIONS and leg["frm"] not in US_STATIONS


def _overlap(a, b, c, d):
    return max(timedelta(0), min(b, d) - max(a, c))


def _prep(d):
    """A duty's FDP facts: flown legs, the FDP's legs (to the last flown leg), its end, release and flight time."""
    legs = d["legs"]
    flown = [i for i, x in enumerate(legs) if not x.get("dh")]
    out = dict(d)
    last = legs[-1]
    out["release"] = last["arr"] + (RELEASE_CUSTOMS if customs(last) else RELEASE)
    if not flown:
        out.update(fdp=False, fdp_end=None, ft=timedelta(0), fdp_legs=[])
        return out
    j = flown[-1]
    out.update(fdp=True, fdp_end=legs[j]["arr"], fdp_legs=legs[:j + 1],
               ft=sum((timedelta(minutes=int(legs[i]["blk"])) for i in flown), timedelta(0)))
    return out


def _acclimation(ds, idx, busy):
    """The walk (see the module note) up to duty idx: (options, words, status). options: [(station whose clock enters
    the tables, 0:30 less)], the readings to try (the lowest limit is used); status True / False / None (acclimated /
    not / unknown)."""
    ref, ref_sure = DOMICILE, True
    stay = {"stn": DOMICILE, "since": None}
    for j in range(idx + 1):
        d = ds[j]
        s, rep = d["legs"][0]["frm"], d["report"]
        prev = ds[j - 1] if j else None
        free = rep - prev["release"] if prev else None
        busy_gap = bool(prev) and any(b0 < rep and b1 > prev["release"] for b0, b1 in busy)
        in_th = (rep - stay["since"]) if stay.get("since") is not None and same_theater(s, stay["stn"]) else None
        stay_ok = in_th is not None and in_th >= STAY_ACCL
        free_ok = free is not None and free >= FREE_ACCL
        known = s in LON
        far = f"{s} is {round(ang(LON[s], LON[ref]))} deg from {ref}" if known and ref in LON else f"{s} has no longitude on file"
        facts = (f"{hm(free)} free from duty (36 h needed)" if free is not None else "no duty before it on file") + (
            f", {hm(in_th)} in that theater (72 h needed)" if in_th is not None else "")
        if ref_sure and known and same_theater(s, ref):
            st, opts = True, [(ref, False)]
            if rep.astimezone(zone(s)).utcoffset() != rep.astimezone(zone(ref)).utcoffset():
                opts.append((s, False))  # the report station's own clock too: the lower limit is used
            words = (f"acclimated to the {ref} theater" + (f" ({s} is within 60 deg of {ref})" if s != ref else ""))
        elif known and (stay_ok or (free_ok and not busy_gap)):
            why = f"{hm(free)} free from duty" if free_ok and not busy_gap else f"{hm(in_th)} in that theater"
            ref, ref_sure = s, True
            st, opts = True, [(s, False)]
            words = f"acclimated to the {s} theater ({why}, 36 h free or 72 h there makes it)"
        elif known and ref_sure and free_ok and busy_gap:
            st = None
            opts = [(s, False), (ref, True)]
            words = (f"? acclimated to {s} only if the schedule item inside the {hm(free)} free was not duty; the lower "
                     f"of acclimated ({s} time) and not acclimated ({ref} time, less 0:30) is used")
            ref_sure = False
        elif known and ref_sure:
            st, opts = False, [(ref, True)]
            words = (f"not acclimated: {far}, {facts}; the tables are entered on {ref} time (the theater last "
                     f"acclimated to) and the FDP limit is 0:30 less (FAR 117.13(b), 117.17(b), FOM 4.3.2.4)")
        else:
            st, opts = None, [(ref, True)]
            words = (f"? acclimation not known ({far}, or an earlier station has none): {ref} time, FDP 0:30 less "
                     f"(conservative)")
        if j == idx:
            return opts, words, st
        for x in d["legs"]:  # where the duty took him: the theater stay starts at the block-in that brought him there
            if not same_theater(x["to"], stay["stn"]):
                stay = {"stn": x["to"], "since": x["arr"]}
            if x["to"] not in LON:
                ref_sure = False
    return [(DOMICILE, True)], "?", None


def _cum(ds, idx, end, known_from):
    """{key: {limit, used, room, cap_at, cap_txt, line}} for the cumulative limits whose window the line on file
    covers, and [lines for the ones it does not]."""
    got, missing = {}, []
    me = ds[idx]
    for key, span, lim, what, words, ref, _short in CUM:
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
                for x in d["legs"]:
                    if not x.get("dh"):
                        used += min(timedelta(minutes=int(x["blk"])), _overlap(x["dep"], x["arr"], a, end))
            else:
                used += _overlap(d["report"], end if d is me else d["fdp_end"], a, end)
        room = _hrs(lim) - used
        cap = end + room
        got[key] = {"_cap": cap, "limit": f"{lim}:00", "used": hm(used), "room": hm(room), "cap_at": cap.isoformat(),
                    "cap_txt": clock(cap), "cap_day": day(cap),
                    "line": (f"{words} ({ref}): {hm(used)} at the scheduled block-in {clock(end)}, {hm(room)} left, so "
                             f"no later than {clock(cap)} {day(cap)}")}
    return got, missing


def duty_timeout(duties, idx, pilots=None, pilots_src="", eq="", known_from=None, busy=(), notes=()):
    """The `timeout` attribute for duty idx of the pilot's duties (all on file, in time order), or None when it cannot
    be worked out (pilots not known, no flown leg). A duty: {report (aware), report_txt (how it was found), legs:
    [{dep, arr (aware), blk (minutes), frm, to, flt, dh}]}. pilots / pilots_src: pilots_of(). eq: the package's
    equipment ('332'). known_from: the earliest time from which the pilot's line is all on file (None: not known).
    busy: [(start, end)] schedule items that may be duty (no flight time, no FDP: training, reserve). notes: more basis
    lines (the roster against the package)."""
    try:
        return _timeout(duties, idx, pilots, pilots_src, eq, known_from, busy, notes)
    except (KeyError, TypeError, ValueError, IndexError, StopIteration, AttributeError):
        return None


def _timeout(duties, idx, pilots, pilots_src, eq, known_from, busy, notes):
    if not pilots or pilots < 2 or not (0 <= idx < len(duties)):
        return None
    pilots = min(int(pilots), 4)
    ds = [_prep(d) for d in duties]
    me = ds[idx]
    if not me["fdp"]:
        return None
    rep, legs = me["report"], me["fdp_legs"]
    first, last = legs[0], legs[-1]
    flown = [x for x in legs if not x.get("dh")]
    segs = len(legs)
    lines, not_checked = [], []
    opts, acc_words, acc = _acclimation(ds, idx, busy)
    # ---- FDP limit: the lowest of the readings (clock, unacclimated or not)
    aug = pilots >= 3
    cls, cls_sure, cls_why = rest_class(eq, pilots) if aug else (None, True, "")
    col = 0 if pilots == 3 else 1
    best = None
    for stn, red in opts:
        loc = rep.astimezone(zone(stn))
        mnt = loc.hour * 60 + loc.minute
        if aug:
            r = _row(TABLE_C, mnt)
            base = r[2][cls][col]
            alt = {str(c): r[2][c][col] for c in (2, 3)}
        else:
            r = _row(TABLE_B, mnt)
            base = r[2][min(segs, 7) - 1]
            alt = {}
        lim = _hrs(base) - (UNACCL if red else timedelta(0))
        fa = _hrs(AUG_FT[pilots]) if aug else _hrs(_row(TABLE_A, mnt)[2])
        cand = {"lim": lim, "base": base, "red": red, "row": _label(r), "clock": f"{stn} time {loc:%H:%M}",
                "alt": alt, "fa": fa, "fa_row": _label(_row(TABLE_A, mnt))}
        if best is None or (lim, fa) < (best["lim"], best["fa"]):
            if best is not None:
                cand["other"] = best
            best = cand
        else:
            best.setdefault("other", cand)
    fdp_lim, ft_lim = best["lim"], min(c for c in [best["fa"]] + ([best["other"]["fa"]] if "other" in best else []))
    fdp_end = rep + fdp_lim
    ext_end = fdp_end + EXT
    alt = {k: clock(rep + _hrs(v) - (UNACCL if best["red"] else timedelta(0))) for k, v in best["alt"].items()}
    # ---- flight time end: the last flown leg's scheduled out + what the limit leaves after the earlier flown legs
    lf = flown[-1]
    before = sum((timedelta(minutes=int(x["blk"])) for x in flown[:-1]), timedelta(0))
    ft_end = lf["dep"] + ft_lim - before
    sched_in = me["fdp_end"]
    cum, cum_missing = _cum(ds, idx, sched_in, known_from)
    # ---- results
    table, rule = ("C", "FAR 117.17") if aug else ("B", "FAR 117.13")
    fdp_by = (f"FDP {hm(fdp_lim)} ({rule}, Table {table})", f"FDP {hm(fdp_lim)}")
    ft_by = (f"{hm(ft_lim)} flight time (FAR 117.11)", f"{hm(ft_lim)} flight time")
    caps = [(cum[key]["_cap"], (f"{w} ({ref})", short)) for key, _s, _l, _w, w, ref, short in CUM if key in cum]
    cands = [(fdp_end, fdp_by), (ft_end, ft_by)] + caps
    no_at, no_by = min(cands, key=lambda c: c[0])
    ext_cands = [(ext_end, (f"FDP {hm(fdp_lim)} with the 2:00 extension (FAR 117.19(a))", "FDP + 2:00 ext"))]
    ext_cands += [(ft_end, ft_by)] + caps
    ex_at, ex_by = min(ext_cands, key=lambda c: c[0])
    if ex_at != ext_end:
        ex_by = (f"{ex_by[0].split(' (')[0]}; FDP with 2:00 extension {clock(ext_end)}", ex_by[1])
    to = last["to"]
    rel_d = RELEASE_CUSTOMS if customs(last) else RELEASE

    def res(at, by):
        return {"at": at.isoformat(), "txt": clock(at), "day": day(at), "local": clock(at, zone(to)),
                "z": f"{at.astimezone(timezone.utc):%H:%M}Z", "by": by[0], "short": by[1],
                "release_at": (at + rel_d).isoformat(), "release_txt": clock(at + rel_d)}

    zs = zone(first["frm"])
    # ---- the basis, one line a rule
    lines.append(f"Report {clock(rep, zs)} ({clock(rep)} {day(rep)}): {me.get('report_txt') or 'from the schedule'}.")
    lines.append(f"Acclimation (FAR 117.3, FOM 4.3.2.4.6): {acc_words}.")
    roster = f"{pilots} pilots ({pilots_src})" if pilots_src else f"{pilots} pilots"
    lines.append(f"{roster}: {'augmented, Table C (FAR 117.17, FOM 4.3.2.4)' if aug else 'unaugmented, Table B (FAR 117.13, FOM 4.3.2.4)'}.")
    lines.extend(n for n in notes if n)
    if aug:
        lines.append(f"Rest facility: {cls_why}{'' if cls_sure else ' (?)'}. Class 1 assumes the bunks are usable (a "
                     f"deferred crew rest lowers it): Class 2 ends {alt['2']}, Class 3 {alt['3']}.")
        if segs > AUG_MAX_SEGMENTS:
            lines.append(f"Flag: {segs} segments in an augmented FDP, FOM 4.3.2.4.2 allows 3 (a diversion's aside).")
    else:
        lines.append(f"Segments: {segs} in this FDP (every leg counted, a deadhead too: conservative).")
    oth = best.get("other")
    alt_clock = (f"; {oth['clock']} gives row {oth['row']}, {hm(oth['lim'])}: the lower is used"
                 if oth and oth["lim"] != best["lim"] else "")
    red = ", less 0:30" if best["red"] else ""
    cls_txt = f", Class {cls}{'' if cls_sure else ' ?'}, {pilots} pilots" if aug else f", {segs} segment{'s' if segs > 1 else ''}"
    lines.append(f"Table {table} row {best['row']} ({best['clock']}){cls_txt}: {hm(_hrs(best['base']))}{red} = FDP "
                 f"{hm(fdp_lim)}, ends {clock(fdp_end)} {day(fdp_end)} ({rule}){alt_clock}.")
    zo = zone(lf["frm"])
    ft_src = f"scheduled out {clock(lf['dep'], zo)}"
    fa_src = "FAR 117.11, FOM 4.3.2.2" if aug else f"Table A row {best['fa_row']} ({best['clock']}), FAR 117.11"
    lines.append(f"Flight time {hm(ft_lim)} ({fa_src}): "
                 f"from {ft_src} ({clock(lf['dep'])}){f' after {hm(before)} flown earlier' if before else ''}, block-in by "
                 f"{clock(ft_end)}; moves with the actual out. An FDP extension does not extend it (FOM 4.3.2.2).")
    if sched_in > no_at:
        lines.append(f"Flag: the scheduled block-in {clock(sched_in)} is after {clock(no_at)}: check with Crew "
                     f"Scheduling.")
    lines.append(f"Extension (FAR 117.19(a), FOM 4.3.2.5): up to 2:00 before takeoff, for unforeseen operational "
                 f"circumstances, the PIC and the company agreeing: FDP to {clock(ext_end)} {day(ext_end)}.")
    lines.append("After takeoff (FAR 117.19(b), FOM 4.3.2.5.2): the FDP, the flight time and the cumulative limits may "
                 "be exceeded as needed to land at the destination or an alternate: no fixed time.")
    for key, *_ in CUM:
        if key in cum:
            lines.append(cum[key]["line"] + ".")
    if cum:
        lines.append("The cumulative limits cap an extension before takeoff (FAR 117.19(a), 117.23(c)); after takeoff "
                     "they may be exceeded to land (FOM 4.3.2.3, 4.3.2.6).")
    no, ex = res(no_at, no_by), res(ex_at, ex_by)
    lines.append(f"Duty ends {int(rel_d.total_seconds() // 60)} min after block-in{', clearing customs' if rel_d == RELEASE_CUSTOMS else ''} (PWA "
                 f"2.19.b.2): release {no['release_txt']} without an extension, {ex['release_txt']} with one.")
    not_checked.append(PWA10)
    not_checked.append("An extension of more than 30 min since your last 30 h free from duty (FAR 117.19(a)(2), FOM "
                       "4.3.2.5): not on file; with one, no pre-takeoff extension")
    not_checked.extend(cum_missing)
    not_checked.append("Flying outside your FLICA line (another employer, Part 91) in the cumulative limits (FOM 2.7.4)")
    not_checked.append("1000 h flight time in 365 days (FAR 117.23(b)(2))")
    return {
        "no_ext": no, "ext": ex,
        "fdp": {"limit": hm(fdp_lim), "end_at": fdp_end.isoformat(), "end_txt": clock(fdp_end),
                "ext_end_at": ext_end.isoformat(), "ext_end_txt": clock(ext_end), "table": table,
                "row": f"{best['row']} ({best['clock']})", "acclimated": acc, "pilots": pilots,
                "pilots_from": pilots_src, "rest_class": cls, "rest_class_sure": cls_sure if aug else None,
                "segments": segs, "alt": alt},
        "ft": {"limit": hm(ft_lim), "end_at": ft_end.isoformat(), "end_txt": clock(ft_end), "from": ft_src},
        "cum": {k: {f: v for f, v in c.items() if f not in ("line", "_cap")} for k, c in cum.items()},
        "report_txt": clock(rep), "report_day": day(rep), "sched_in_txt": clock(sched_in),
        "lines": lines, "not_checked": not_checked,
    }
