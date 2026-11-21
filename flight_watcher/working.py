"""FW-0067 (Ryan, Nov 8): the working flight from the pilot's own FLICA schedule, for every Watcher instance
(sensor.<prefix>_working_flight), so a second pilot's Working Flight view shows his own line. Hark's
sensor.hark_working_flight (Ryan only) adds the release, MEL, NOTAMs and live status; this one is what the schedule
says ("per schedule").

Pure: no FLICA, no MQTT, no clock of its own. FLICA prints a leg's times in station local time, and pot.parse_legs
turns them into HST with standard offsets (pot.TZ), an hour off at a station on daylight time (SYD, MEL and AKL from
October to April, the US mainland and ANC from March to November). So each leg is rebuilt here from what FLICA
printed: the departure day and time at the origin's own zone (ZONES, daylight time included), the arrival at the
printed time at the destination nearest departure + block. Hawaii keeps no DST, so HST is a fixed UTC-10. A station
in neither ZONES nor pot.TZ: the leg hangs on its known end (known origin: arrival = departure + block; known
destination: departure = arrival - block); with neither end known only the printed local times show. The date is
the departure day FLICA printed, the date at the origin.

1.7.24 (Ryan, Nov 20: "calculate per FAR 117 and PWA when I timeout, both for if I extend or if I do not", and "when
is the last moment I can block out and be legal"): the `timeout` attribute, the working leg's last legal block-out and
its duty period's block-in limits without and with an extension (timeout.duty_timeout), from every duty on file (a
trip's read legs with the pairings package's deadheads, else its duty periods), the crew list's pilots or the pairings
package's crew line, the package's equipment, the schedule months on file (whether the cumulative limits' windows are
all on file, and the days not known) and the trips not read. Absent when it cannot be worked out."""
import re
from datetime import datetime, time as dtime, timedelta, timezone
from zoneinfo import ZoneInfo

from pot import LAYOVER_MIN_H, PAIRING_RE, TZ

HST = timezone(timedelta(hours=-10))
DOMICILE = "HNL"
AIRLINE = "HA"  # the flight as the dashboard shows it (HA865)
FA_URL = "https://www.flightaware.com/live/flight/HAL"  # FlightAware takes the ICAO code (HAL865)
SIGWX_URL = "https://aviationweather.gov/gfa/"
SOURCE = "schedule"
UPDATED_BY = "Flight Watcher"
NO_TRIP = "No trip"
STATE_MAX = 255  # Home Assistant's limit for a state
# PWA 2.A.19.b.1 (as recall._trip applies it): a later duty period reports 1:00 before departure in domicile, 1:15 out
# of it
REPORT_DOMICILE_MIN, REPORT_AWAY_MIN = 60, 75
VOLATILE = ("updated", "status_as_of")  # move on every call; a payload that differs only here is not news
STN_RE = re.compile(r"^[A-Z]{3}$")
# The zone of every station in pot.TZ (whose offsets are the standard ones): its local time with daylight time
# (1.7.1: and of a few stations pot.TZ does not list; layover.py reads only this table)
ZONES = {"HNL": "Pacific/Honolulu", "OGG": "Pacific/Honolulu", "KOA": "Pacific/Honolulu", "ITO": "Pacific/Honolulu",
         "LIH": "Pacific/Honolulu", "MKK": "Pacific/Honolulu", "LNY": "Pacific/Honolulu", "PPT": "Pacific/Tahiti",
         "RAR": "Pacific/Rarotonga", "PPG": "Pacific/Pago_Pago",
         "ANC": "America/Anchorage",
         **{s: "America/Los_Angeles" for s in ("LAX", "SFO", "SEA", "SAN", "OAK", "SMF", "LAS", "PDX", "SJC", "ONT",
                                              "LGB")},
         "PHX": "America/Phoenix", "SLC": "America/Denver", "DEN": "America/Denver",
         **{s: "America/Chicago" for s in ("ORD", "DFW", "AUS", "MSP", "IAH")},
         **{s: "America/New_York" for s in ("JFK", "BOS", "MCO", "IAD", "ATL", "MIA", "EWR")},
         **{s: "Asia/Tokyo" for s in ("NRT", "HND", "KIX", "CTS", "FUK", "NGO")},
         "ICN": "Asia/Seoul", "SYD": "Australia/Sydney", "BNE": "Australia/Brisbane", "MEL": "Australia/Melbourne",
         "AKL": "Pacific/Auckland", "SIN": "Asia/Singapore", "MNL": "Asia/Manila", "CRK": "Asia/Manila",
         "TPE": "Asia/Taipei", "PEK": "Asia/Shanghai", "PVG": "Asia/Shanghai", "HKG": "Asia/Hong_Kong",
         # 1.7.1 (FW-0072): stations in Ryan's pairing and finds files on Pako (Nov 11) that had no zone (charters)
         "BFI": "America/Los_Angeles", "IND": "America/Indiana/Indianapolis", "LAN": "America/Detroit",
         "LNK": "America/Chicago"}
# An origin in neither table lies somewhere from UTC-11 to UTC+13, so its printed time read as HST runs 1 h early to
# 23 h late: the arrival is looked for around that reading minus this many hours (the middle)
UNKNOWN_MID_H = 11


def stamp(dt):
    """'2026-11-08 14:05 HST'."""
    return dt.astimezone(HST).strftime("%Y-%m-%d %H:%M HST")


def _mins(s):
    """'16:30' -> 990; None when it is not H:MM / HH:MM."""
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", str(s or "").strip())
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def _hhmm(m):
    m %= 1440
    return f"{m // 60:02d}:{m % 60:02d}"


def _zone(stn):
    """A station's clock: its zone (ZONES, daylight time included), or its fixed standard offset (pot.TZ) when the
    tz database is missing (the Dockerfile installs tzdata); None for a station in neither."""
    name = ZONES.get(stn)
    if name:
        try:
            return ZoneInfo(name)
        except (KeyError, OSError, ValueError):  # ZoneInfoNotFoundError is a KeyError
            pass
    off = TZ.get(stn)
    return timezone(timedelta(hours=off)) if off is not None else None


def _at(day, m, zone):
    """Minute m (0 to 1439) of a local day at a zone, as an aware HST time."""
    return datetime.combine(day, dtime(m // 60, m % 60), tzinfo=zone).astimezone(HST)


def _snap(m, zone, est):
    """The time printed as minute m at a zone that falls nearest est (HST): a printed arrival put on its day."""
    day = est.astimezone(zone).date()
    return min((_at(day + timedelta(days=k), m, zone) for k in (-1, 0, 1)), key=lambda c: abs(c - est))


def _wall(dt, stn):
    """'HH:MM' at a station for an aware time; '' for a station with no known clock."""
    z = _zone(stn)
    return dt.astimezone(z).strftime("%H:%M") if z else ""


def _pair(local_hm, dt, hst=True):
    """'16:30 local, 16:30 HST'; just 'HH:MM HST' when the local time is unknown, just 'HH:MM local' when the HST time
    is (neither station of the leg known)."""
    if not hst:
        return f"{local_hm} local" if local_hm else ""
    h = dt.astimezone(HST).strftime("%H:%M")
    return f"{local_hm} local, {h} HST" if local_hm else f"{h} HST"


def _pairings(items):
    """The pairings on the line (schedule items whose trip matches PAIRING_RE), once each, in date order."""
    seen, out = set(), []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        trip, start = str(it.get("trip") or ""), str(it.get("start") or "")
        key = f"{trip}|{start}"
        if not PAIRING_RE.match(trip) or key in seen:
            continue
        try:
            day0 = datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=HST)
        except ValueError:
            continue
        seen.add(key)
        out.append({"trip": trip, "start": start, "end": str(it.get("end") or start), "key": key, "day0": day0,
                    "lay": str(it.get("lay") or "").strip().upper()})
    out.sort(key=lambda p: (p["start"], p["trip"]))
    return out


def _report(first, rec, dep, dep_l, frm, hst=True):
    """The report for a duty that starts with this leg. The trip's first duty: FLICA's check in (HNL time, so HST).
    A later duty (after a layover of LAYOVER_MIN_H or more): 1:15 before departure out of domicile, 1:00 in domicile
    (PWA 2.A.19.b.1), shown as local and HST."""
    if first and _mins(rec.get("report")) is not None:
        return f"{_hhmm(_mins(rec.get('report')))} HST"
    before = REPORT_DOMICILE_MIN if frm == DOMICILE else REPORT_AWAY_MIN
    rep = dep - timedelta(minutes=before)
    lm = _mins(dep_l)
    return _pair(_hhmm(lm - before) if lm is not None else _wall(rep, frm), rep, hst)


def _times(p, lg, frm, to):
    """(dep, arr, day, hst) of a leg from what FLICA printed: departure and arrival as aware HST times, the departure
    day at the origin, and whether the HST times are known (False only when neither station is: the printed times
    then stand in for HST). parse_legs's own HST minutes only serve to find the printed day."""
    raw_dep, raw_arr = int(lg["dep"]), int(lg["arr"])
    blk = timedelta(minutes=int(lg["blk"]) if lg.get("blk") not in (None, "") else raw_arr - raw_dep)
    dm, am = _mins(lg.get("dep_l")), _mins(lg.get("arr_l"))
    if dm is None:  # nothing printed to rebuild from: parse_legs's times as they are
        dep = p["day0"] + timedelta(minutes=raw_dep)
        return dep, p["day0"] + timedelta(minutes=raw_arr), dep.date(), True
    # parse_legs took the standard offset off the printed time (raw = printed - shift) only when it knew both ends
    shift = (TZ[frm] + 10) * 60 if frm in TZ and to in TZ else 0
    day = p["day0"].date() + timedelta(days=(raw_dep + shift) // 1440)
    zf, zt = _zone(frm), _zone(to)
    if zf:
        dep = _at(day, dm, zf)
        arr = _snap(am, zt, dep + blk) if zt and am is not None else dep + blk
        return dep, arr, day, True
    if zt and am is not None:
        arr = _snap(am, zt, _at(day, dm, HST) + blk - timedelta(hours=UNKNOWN_MID_H))
        return arr - blk, arr, day, True
    dep = _at(day, dm, HST)
    return dep, dep + blk, day, False


def _legs(p, rec):
    """A pairing's legs on absolute HST time with their number, origin, date at the origin and their duty's report.
    [] when the legs are not read yet (or the record is not usable)."""
    raw = rec.get("legs") if isinstance(rec, dict) else None
    if not isinstance(raw, list) or not raw:
        return []
    out, prev, rep = [], None, ""
    try:
        for i, lg in enumerate(raw):
            frm = str(lg.get("frm") or (prev["to"] if prev else DOMICILE)).upper()
            to = str(lg.get("to") or "").upper()
            dep, arr, day, hst = _times(p, lg, frm, to)
            new_duty = prev is None or dep - prev["arr"] >= timedelta(hours=LAYOVER_MIN_H)
            if new_duty:
                rep = _report(prev is None, rec, dep, lg.get("dep_l"), frm, hst)
            blk = lg.get("blk")
            x = {"trip": p["trip"], "key": p["key"], "i": i, "flt": str(lg.get("flt") or ""), "frm": frm, "to": to,
                 "dep": dep, "arr": arr, "dep_l": str(lg.get("dep_l") or ""), "arr_l": str(lg.get("arr_l") or ""),
                 "blk": int(blk) if blk not in (None, "") else int((arr - dep).total_seconds() // 60),
                 "date": day.isoformat(), "hst": hst, "report": rep, "duty_start": new_duty, "dh": bool(lg.get("dh"))}
            if prev is not None:
                prev["duty_end"] = new_duty
            out.append(x)
            prev = x
    except (KeyError, TypeError, ValueError, AttributeError):
        return []
    prev["duty_end"] = True
    for x in out:
        x["n"] = len(out)
    return out


def _flight(x):
    return f"{AIRLINE}{x['flt']}" if x["flt"] else ""


def _away_station(p):
    """Where a pairing goes: its first layover (a duty that ends away from HNL), else its first arrival that is not
    HNL; from its legs, else its duty periods, else the schedule's layover cell. '' when none is known."""
    legs = p.get("legs") or []
    for x in legs:
        if x.get("duty_end") and x["to"] and x["to"] != DOMICILE:
            return x["to"]
    for x in legs:
        if x["to"] and x["to"] != DOMICILE:
            return x["to"]
    for d in (p.get("rec") or {}).get("duties") or []:
        stn = str((d or {}).get("stn") or "").upper()
        if STN_RE.match(stn) and stn != DOMICILE:
            return stn
    return p["lay"] if STN_RE.match(p["lay"]) and p["lay"] != DOMICILE else ""


def _next_pairing(pairs, today, after=None, unread_only=False):
    """'H3681 SYD 2026-11-09' for the first pairing after `after` (any pairing when None) that has not ended before
    today; unread_only: only one whose legs are not read yet. '' when there is none."""
    for p in pairs:
        if after is not None and (p["start"], p["trip"]) <= (after["start"], after["trip"]):
            continue
        if p["end"] < today or (unread_only and p.get("legs")):
            continue
        return " ".join(s for s in (p["trip"], _away_station(p), p["start"]) if s)
    return ""


# ---------------------------------------------------------------- 1.7.24: the duty timeout's inputs
LOOK_D = 30  # days before the working duty the line on file is checked for the cumulative limits (672 h is 28)
NOT_DUTY = ("VAC", "PAYP")  # schedule codes that are never duty (every other code may be: training, reserve...)


def _report_at(first, rec, p, dep, frm):
    """(report, how) of a duty that starts with a leg leaving `frm` at `dep`: the trip's first duty, FLICA's check in
    (HNL time, so HST) on the trip's first day, the day before when it reads later than the departure; a later duty
    1:00 before departure in domicile, 1:15 out of it (PWA 2.A.19.b.1; 1:00 when separate pilot transport is planned, so
    1:15 is the earlier)."""
    m = _mins(rec.get("report")) if first else None
    if m is not None:
        r = p["day0"] + timedelta(minutes=m)
        if r > dep:
            r -= timedelta(days=1)
        while dep - r >= timedelta(days=1):
            r += timedelta(days=1)
        return r, f"FLICA check-in {_hhmm(m)} HST"
    before = REPORT_DOMICILE_MIN if frm == DOMICILE else REPORT_AWAY_MIN
    where = "in domicile" if frm == DOMICILE else "out of domicile"
    how = f"{before // 60}:{before % 60:02d} before scheduled departure {where} (PWA 2.A.19.b.1)"
    return dep - timedelta(minutes=before), how


def _spans(p, rec):
    """A trip's duty periods as legs when its legs are not read (a record cached before 1.4.9): one span a duty from
    the record's duties [{dep, arr, stn, blk, dep_l, arr_l}] (first departure to last block-in, blk the flown block),
    rebuilt on the station clocks as _legs does. [] when there are none."""
    raw = rec.get("duties") if isinstance(rec, dict) else None
    if not isinstance(raw, list) or not raw:
        return []
    out, frm = [], DOMICILE
    try:
        for du in sorted(raw, key=lambda y: int(y["dep"])):
            to = str(du.get("stn") or "").upper()
            lg = {"dep": du["dep"], "arr": du["arr"], "blk": int(du["arr"]) - int(du["dep"]),
                  "dep_l": du.get("dep_l"), "arr_l": du.get("arr_l")}
            dep, arr, _day, _hst = _times(p, lg, frm, to)
            blk = int(du["blk"]) if du.get("blk") not in (None, "") else int((arr - dep).total_seconds() // 60)
            out.append({"key": p["key"], "frm": frm, "to": to, "dep": dep, "arr": arr, "flt": "", "dh": False,
                        "blk": blk, "duty_start": True, "span": True})
            frm = to
    except (KeyError, TypeError, ValueError, AttributeError):
        return []
    return out


def _flt_no(s):
    """A flight number as the legs keep it ('0123', '1127*' -> '123', '1127'); '' when there is none."""
    m = re.match(r"\s*(\d+)", str(s or ""))
    return str(int(m.group(1))) if m else ""


def _dur_min(s):
    """'5h42' or '5:42' -> 342; None when it is neither."""
    m = re.fullmatch(r"(\d{1,3})[:h](\d{2})", str(s or "").strip())
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def _printed(m, zone, near, after):
    """The time printed as minute m at a zone next to `near`: the first at or after it (after), else the last at or
    before it; None when neither falls within a day."""
    day = near.astimezone(zone).date()
    got = [c for c in (_at(day + timedelta(days=k), m, zone) for k in (-1, 0, 1))
           if (c >= near if after else c <= near)]
    return (min(got) if after else max(got)) if got else None


def _pkg_duty(duty, pk, start):
    """(k, package duty, its legs) for the first package duty from index start whose flown legs are this duty's (the
    same flights from the same stations, in order); None when none is."""
    flown = [x for x in duty["legs"] if not x.get("dh")]
    if not flown or not all(x.get("flt") for x in flown):
        return None
    for k, du in enumerate(((pk or {}).get("duties") or [])[start:], start):
        pl = [lg for lg in (du or {}).get("legs") or [] if isinstance(lg, (list, tuple)) and len(lg) >= 8]
        fl = [lg for lg in pl if str(lg[1]).upper() != "DH"]
        if len(fl) == len(flown) and all(_flt_no(lg[2]) == x["flt"] and str(lg[3]).upper() == x["frm"]
                                         for lg, x in zip(fl, flown)):
            return k, du, pl
    return None


def _with_deadheads(duty, pl):
    """The duty's legs with the package legs' deadheads put in (dh True), each on its stations' clocks: one before the
    first flown leg ends at the printed arrival before the next leg's out, one after a leg leaves at the printed time
    after the previous block-in. Raises ValueError when one cannot be placed."""
    flown = iter([x for x in duty["legs"] if not x.get("dh")])
    out, lead = [], []
    for lg in pl:
        if str(lg[1]).upper() != "DH":
            out.append(next(flown))
            continue
        blk = _dur_min(lg[7])
        if blk is None:
            raise ValueError("deadhead block")
        x = {"frm": str(lg[3]).upper(), "to": str(lg[4]).upper(), "blk": blk, "flt": _flt_no(lg[2]), "dh": True,
             "key": duty["key"], "i": None}
        if not out:
            lead.append((x, _mins(lg[6])))
            continue
        zf, dm = _zone(x["frm"]), _mins(lg[5])
        dep = _printed(dm, zf, out[-1]["arr"], True) if zf and dm is not None else None
        if dep is None:
            raise ValueError("deadhead out")
        out.append(x | {"dep": dep, "arr": dep + timedelta(minutes=blk)})
    nxt = out[0]["dep"]
    for x, am in reversed(lead):
        zt = _zone(x["to"])
        arr = _printed(am, zt, nxt, False) if zt and am is not None else None
        if arr is None:
            raise ValueError("deadhead in")
        nxt = arr - timedelta(minutes=x["blk"])
        out.insert(0, x | {"dep": nxt, "arr": arr})
    return out


def _deadheads(p, duties, pk):
    """1.7.24 review: FLICA's pairing page legs on file carry no deadhead (pot.parse_legs reads the flown legs only), so
    each duty of a read trip takes its deadheads from the pairings package detail (pdfs.package_legs: matched by its
    flown flights) and, when it starts with one or the package prints an earlier REPT, that report (a later duty: the
    earlier of the package's REPT and the PWA 2.A.19.b.1 rule at the deadhead; the first: FLICA's check-in unless the
    deadhead leaves before it). Each duty gets dh_note, what the package said."""
    start = 0
    for n, d in enumerate(duties):
        if not pk or not pk.get("duties"):
            d["dh_note"] = ("FLICA's pairing page lists none and the pairings package has no detail for this pairing, "
                            "so one there would not be counted")
            continue
        m = _pkg_duty(d, pk, start)
        if m is None:
            d["dh_note"] = ("FLICA's pairing page lists none and no duty of the pairings package matches this one's "
                            "flights, so one there would not be counted")
            continue
        start, du, pl = m[0] + 1, m[1], m[2]
        try:
            legs = _with_deadheads(d, pl)
        except (ValueError, StopIteration, TypeError, KeyError, IndexError):
            d["dh_note"] = "the pairings package shows one here that could not be placed on the station clocks"
            continue
        dh = [f"{x['frm']}-{x['to']}" for x in legs if x.get("dh")]
        d["dh_note"] = (f"from the pairings package: {', '.join(dh)} (FLICA's page lists none)" if dh
                        else "the pairings package shows none for this duty")
        d["legs"], cands = legs, []
        if not (str(d.get("report_txt") or "").startswith("FLICA") and legs[0]["dep"] >= d["report"]):
            if legs[0].get("dh"):  # a duty that starts with a deadhead reports before it
                cands.append(_report_at(False, {}, p, legs[0]["dep"], legs[0]["frm"]))
            rm, z0 = _mins(du.get("rept")), _zone(legs[0]["frm"])
            r = _printed(rm, z0, legs[0]["dep"], False) if rm is not None and z0 else None
            if r is not None:
                cands.append((r, f"REPT {_hhmm(rm)} local in the pairings package"))
        d["report"], d["report_txt"] = min([(d["report"], d["report_txt"])] + cands, key=lambda c: c[0])


def _duties(pairs, pkg=None):
    """Every duty on file in time order: {key, report, report_txt, legs, dh_note}; a trip whose legs are not read gives
    its duty periods (_spans); one with neither gives nothing. A read trip's deadheads come from the pairings package
    (_deadheads)."""
    out = []
    for p in pairs:
        legs = p["legs"] or _spans(p, p["rec"])
        cur, mine = None, []
        for j, x in enumerate(legs):
            if x["duty_start"] or cur is None:
                rep, how = _report_at(j == 0, p["rec"], p, x["dep"], x["frm"])
                cur = {"key": p["key"], "report": rep, "report_txt": how, "legs": []}
                mine.append(cur)
            cur["legs"].append({k: x[k] for k in ("dep", "arr", "blk", "frm", "to", "flt", "dh", "key")}
                               | {"i": x.get("i")})
        if p["legs"] and mine:
            _deadheads(p, mine, _pkg_of(pkg, p) if pkg is not None else None)
        out += mine
    out.sort(key=lambda d: d["report"])
    return out


def _known_from(months, pairs, upto, today):
    """The earliest time (00:00 HST of a day) from which the pilot's line is all on file up to `upto` (a date): the
    days the schedule months on file cover (recall.line_gaps) with every pairing on them read (legs or duty periods),
    looking back LOOK_D days. None without months."""
    if not months:
        return None
    import recall as RC
    lo = upto - timedelta(days=LOOK_D)
    start = lo
    for _a, b in RC.line_gaps(months, lo, upto, today):
        start = max(start, datetime.strptime(b, "%Y-%m-%d").date() + timedelta(days=1))
    for p in pairs:
        if p["legs"] or _spans(p, p["rec"]):
            continue
        a, b = p["start"], p["end"]
        if a <= upto.isoformat() and b >= start.isoformat():
            start = max(start, datetime.strptime(b, "%Y-%m-%d").date() + timedelta(days=1))
    return datetime.combine(start, dtime(0), tzinfo=HST)


def _busy(items):
    """[(start, end)] HST whole days of the schedule items that may be duty (not a pairing, VAC or PAYP)."""
    out = []
    for it in items or []:
        t = str((it or {}).get("trip") or "") if isinstance(it, dict) else ""
        if not t or PAIRING_RE.match(t) or t in NOT_DUTY:
            continue
        try:
            a = datetime.strptime(str(it.get("start")), "%Y-%m-%d").replace(tzinfo=HST)
            b = datetime.strptime(str(it.get("end") or it.get("start")), "%Y-%m-%d").replace(tzinfo=HST)
        except ValueError:
            continue
        out.append((a, b + timedelta(days=1)))
    return out


PKG_ERR = {"msg": ""}  # 1.7.24 review: why a package detail lookup failed with an error other than OSError ('' none)


def _pkg_of(pkg, p):
    """The pairings package detail ({eq, crew, ...}) of a pairing: pkg is a dict keyed TRIP|start or a callable
    (trip, start); None when neither gives one. A package that cannot be read is no timeout input, never a failed
    publish: an OSError is silent, any other error's type is kept in PKG_ERR (the Watcher logs it once a change)."""
    try:
        got = pkg.get(p["key"]) if isinstance(pkg, dict) else pkg(p["trip"], p["start"]) if callable(pkg) else None
    except OSError:
        got = None
    except Exception as e:  # noqa: BLE001
        PKG_ERR["msg"] = PKG_ERR["msg"] or f"package detail {type(e).__name__}"
        got = None
    return got if isinstance(got, dict) else None


TIMEOUT_ERR = {"msg": ""}  # 1.7.24 review: why the last working flight has no timeout after an error ('' when none)


def _timeout(items, pairs, cur, p, now, pkg, months, domestic=()):
    """The `timeout` attribute of the working leg's duty (timeout.duty_timeout), or None: also when its inputs cannot
    be read, so the working flight itself is always published. An error is kept in TIMEOUT_ERR (the Watcher logs it
    once a change)."""
    import timeout as TO
    TO.ERR["last"] = ""  # 1.7.24 review: a return before duty_timeout runs never logs the last call's error
    try:
        got = _timeout_of(items, pairs, cur, p, now, pkg, months, domestic)
        TIMEOUT_ERR["msg"] = TO.ERR["last"] if got is None else ""
        return got
    except Exception as e:  # noqa: BLE001
        TIMEOUT_ERR["msg"] = type(e).__name__
        return None


def _crew(rec, pk):
    """(pilots, where from, sure, firm, notes, captains) of a pairing: the crew list's pilot seats when it has a CA; a
    crew list with no CA misses that seat at least (the package crew line when it says as many or more, else the list
    plus one, not sure); else the package crew line. firm: the package crew line says the same (a count that is not
    firm and cannot fly the planned flight time is raised, timeout.py). captains (PWA 10.D.1.c / 10.D.1.d for 4
    pilots): the Captains of the source used, None when not known (a crew list with no CA and no package line to
    count them). (None, '', False, False, [], None) with neither."""
    import timeout as TO
    roster = (rec or {}).get("crew")
    n_r, ca = TO.roster_seats(roster)
    code = str((pk or {}).get("crew") or "")
    n_p = TO.package_pilots(code)
    if n_r >= 2 and ca:
        notes = [f"The crew list shows {n_r} pilot seats, the package crew line {code} {n_p}: the crew list is used."
                 ] if n_p and n_p != n_r else []
        return n_r, "the trip's crew list", not (n_p and n_p > n_r), n_p == n_r, notes, TO.roster_captains(roster)
    if n_r >= 1 and not ca:
        low = min(n_r + 1, 4)
        if n_p and n_p >= low:
            return (n_p, f"package crew line {code}; the crew list has no CA", True, True, [],
                    TO.package_captains(code))
        notes = [f"The package crew line {code} says {n_p}."] if n_p else []
        return low, f"the crew list's {n_r} pilot seats and its missing CA", False, False, notes, None
    if n_p:
        return n_p, f"package crew line {code}", True, True, [], TO.package_captains(code)
    return None, "", False, False, [], None


def _unknown(pairs, months, ds, upto, today):
    """[(start, end)] HST spans of the line that are not known: a pairing whose legs and duty periods are not read (its
    days), and with schedule months on file, the days none covers (recall.line_gaps) from 2 days before the first duty
    on file to upto (a date)."""
    out = []
    for q in pairs:
        if q["legs"] or _spans(q, q["rec"]):
            continue
        end = datetime.strptime(q["end"], "%Y-%m-%d").replace(tzinfo=HST) + timedelta(days=1)
        out.append((q["day0"], end))
    if months and ds:
        import recall as RC
        lo = ds[0]["report"].astimezone(HST).date() - timedelta(days=2)
        for a, b in RC.line_gaps(months, lo, upto, today):
            out.append((datetime.strptime(a, "%Y-%m-%d").replace(tzinfo=HST),
                        datetime.strptime(b, "%Y-%m-%d").replace(tzinfo=HST) + timedelta(days=1)))
    return out


def _timeout_of(items, pairs, cur, p, now, pkg, months, domestic=()):
    import timeout as TO
    if not all(x.get("hst", True) for x in p["legs"]):
        return None
    ds = _duties(pairs, pkg)
    idx = next((j for j, d in enumerate(ds) if d["key"] == cur["key"]
                and any(x.get("i") == cur["i"] for x in d["legs"])), None)
    if idx is None:
        return None
    d = ds[idx]
    # the leg the last out is for: the working leg; once it is in, the duty's next flown leg (still the working one
    # until that leaves, working_flight's roll)
    k = next(j for j, x in enumerate(d["legs"]) if x.get("i") == cur["i"] and x.get("key") == cur["key"])
    if now >= cur["arr"]:
        k = next((j for j in range(k + 1, len(d["legs"])) if not d["legs"][j].get("dh")), k)
    pk = _pkg_of(pkg, p) or {}
    pilots, src, sure, firm, notes, captains = _crew(p["rec"], pk)
    upto = d["report"].astimezone(HST).date()
    known = _known_from(months, pairs, d["legs"][-1]["arr"].astimezone(HST).date(), now.date())
    return TO.duty_timeout(ds, idx, pilots, src, str(pk.get("eq") or ""), known, _busy(items), notes, work=k,
                           pilots_sure=sure, pilots_firm=firm, unknown=_unknown(pairs, months, ds, upto, now.date()),
                           domestic=domestic, dh_note=d.get("dh_note", ""), captains=captains)


def working_flight(items, own, now, roll_h=2, pkg=None, months=None, domestic=()):
    """{"state", "attributes"} for the working leg: of every read leg of every own trip, in departure order, the first
    whose block-in + roll_h hours is after now (it stays on a leg until 2 h after block-in, then rolls to the next;
    sooner only when the next leg blocks out within those 2 h).
    items: the schedule items (trip, start, end, lay); own: own_trips keyed TRIP|YYYY-MM-DD (start, HST) with legs and
    report; now: an aware datetime (a naive one is taken as HST). 1.7.24: pkg, the pairings package detail ({eq, crew})
    by TRIP|start (a dict, or a callable (trip, start)), and months, the schedule months on file (the Watcher's
    S['schedule']), and domestic, the pilot's smart.json "domestic" stations (customs, PWA 2.A.19.b), for the duty
    timeout. A trip whose legs are not read yet is skipped for the
    working leg but can be the next pairing; one that has not ended and comes before the working leg's pairing (the
    pilot is on it, or going to it first) shows as "No trip" with that pairing next, rather than a later trip's leg.
    No leg left: state "No trip"."""
    now = now.astimezone(HST) if now.tzinfo else now.replace(tzinfo=HST)
    own = own if isinstance(own, dict) else {}
    today, at = now.date().isoformat(), stamp(now)
    TIMEOUT_ERR["msg"] = PKG_ERR["msg"] = ""
    pairs = _pairings(items)
    every = []
    for p in pairs:
        rec = own.get(p["key"])
        p["rec"] = rec if isinstance(rec, dict) else {}
        p["legs"] = _legs(p, p["rec"])
        every += p["legs"]
    every.sort(key=lambda x: (x["dep"], x["trip"], x["i"]))
    roll = timedelta(hours=roll_h)
    # a leg is the working one until roll_h after its block-in, or until the next leg blocks out when the turn is
    # shorter than that (HNL-OGG-LAX with 40 min in OGG shows OGG-LAX once it leaves, not HNL-OGG)
    cur = next((x for j, x in enumerate(every)
                if min([x["arr"] + roll] + [y["dep"] for y in every[j + 1:j + 2]]) > now), None)
    p = next((q for q in pairs if q["key"] == cur["key"]), None) if cur else None
    # the first pairing not ended whose legs are not read yet (a new trip, or one cached before 1.4.9): when it comes
    # before the working leg's pairing, the pilot is flying it or flies it first, so no later leg is his working one
    unread = next((q for q in pairs if not q["legs"] and q["end"] >= today), None)
    if p is None or (unread is not None and (unread["start"], unread["trip"]) < (p["start"], p["trip"])):
        return {"state": NO_TRIP, "attributes": {"source": SOURCE,
                                                 "next": _next_pairing(pairs, today, unread_only=True),
                                                 "updated": at, "updated_by": UPDATED_BY}}
    if cur["i"] + 1 < cur["n"]:
        nl = p["legs"][cur["i"] + 1]
        when = f"{nl['dep_l']} local" if nl["dep_l"] else nl["dep"].strftime("%H:%M HST")
        nxt = " ".join(s for s in (_flight(nl), f"{nl['frm']}-{nl['to']}", nl["date"], when) if s)
    else:
        nxt = _next_pairing(pairs, today, after=p)
    if now < cur["dep"]:
        status = "Scheduled"
    elif now < cur["arr"]:
        status = "Enroute per schedule"
    else:
        status = "Arrived per schedule"
    dep_l = cur["dep_l"] or _wall(cur["dep"], cur["frm"])
    arr_l = cur["arr_l"] or _wall(cur["arr"], cur["to"])
    flight = _flight(cur)
    attrs = {
        "pairing": cur["trip"],
        "leg": f"{cur['i'] + 1} of {cur['n']}",
        "flight": flight,
        "date": cur["date"],
        "origin": cur["frm"],
        "dest": cur["to"],
        "dep_sched": _pair(dep_l, cur["dep"], cur["hst"]),
        "arr_sched": _pair(arr_l, cur["arr"], cur["hst"]),
        "block": f"{cur['blk'] // 60}:{cur['blk'] % 60:02d}",
        "report": cur["report"],
        "status": status,
        "status_as_of": at,
        "next": nxt,
        "flightaware_url": FA_URL + cur["flt"] if cur["flt"] else "",
        "sigwx_url": SIGWX_URL,
        "source": SOURCE,
        "release_updated": False,
        "updated": at,
        "updated_by": UPDATED_BY,
    }
    to = _timeout(items, pairs, cur, p, now, pkg, months, set(domestic or ()))
    if to:
        attrs["timeout"] = to
    state = " ".join(s for s in (flight, f"{cur['frm']}-{cur['to']}") if s)
    return {"state": state[:STATE_MAX], "attributes": attrs}


def layover_leg(items, own, now):
    """1.7.1 (FW-0072, the van time source): the leg a layover's van goes to, from the pilot's own read legs: the first
    that starts a duty after a layover (not its trip's first leg) whose trip's previous leg has blocked in by now and
    which has not departed yet. {pairing, start (the trip's first day), city (its origin, the layover station), flt,
    dep ('HH:MM' as FLICA printed it at the origin, '' when not), date (its departure date at the origin)}, or None
    (at home, flying, or no legs read)."""
    now = now.astimezone(HST) if now.tzinfo else now.replace(tzinfo=HST)
    own = own if isinstance(own, dict) else {}
    for p in _pairings(items):
        rec = own.get(p["key"])
        legs = _legs(p, rec if isinstance(rec, dict) else {})
        for j, x in enumerate(legs):
            if j and x["duty_start"] and legs[j - 1]["arr"] <= now < x["dep"]:
                return {"pairing": x["trip"], "start": p["start"], "city": x["frm"], "flt": x["flt"],
                        "dep": _hhmm(_mins(x["dep_l"])) if _mins(x["dep_l"]) is not None else "", "date": x["date"]}
    return None


def news(payload):
    """The payload without the fields that move on every call (VOLATILE), to tell a real change from a re-stamp."""
    a = (payload or {}).get("attributes") or {}
    return {"state": (payload or {}).get("state"), "attributes": {k: v for k, v in a.items() if k not in VOLATILE}}
