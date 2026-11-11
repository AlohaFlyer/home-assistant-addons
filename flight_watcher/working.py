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
the departure day FLICA printed, the date at the origin."""
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
# PWA 2.19.b (as recall._trip applies it): a later duty period reports 1:00 before departure in domicile, 1:15 out of it
REPORT_DOMICILE_MIN, REPORT_AWAY_MIN = 60, 75
VOLATILE = ("updated", "status_as_of")  # move on every call; a payload that differs only here is not news
STN_RE = re.compile(r"^[A-Z]{3}$")
# The zone of every station in pot.TZ (whose offsets are the standard ones): its local time with daylight time
# (1.7.1: and of a few stations pot.TZ does not list; layover.py reads only this table)
ZONES = {"HNL": "Pacific/Honolulu", "OGG": "Pacific/Honolulu", "KOA": "Pacific/Honolulu", "ITO": "Pacific/Honolulu",
         "LIH": "Pacific/Honolulu", "PPT": "Pacific/Tahiti", "RAR": "Pacific/Rarotonga", "PPG": "Pacific/Pago_Pago",
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
    (PWA 2.19.b), shown as local and HST."""
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
                 "date": day.isoformat(), "hst": hst, "report": rep, "duty_start": new_duty}
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


def working_flight(items, own, now, roll_h=2):
    """{"state", "attributes"} for the working leg: of every read leg of every own trip, in departure order, the first
    whose block-in + roll_h hours is after now (it stays on a leg until 2 h after block-in, then rolls to the next;
    sooner only when the next leg blocks out within those 2 h).
    items: the schedule items (trip, start, end, lay); own: own_trips keyed TRIP|YYYY-MM-DD (start, HST) with legs and
    report; now: an aware datetime (a naive one is taken as HST). A trip whose legs are not read yet is skipped for the
    working leg but can be the next pairing; one that has not ended and comes before the working leg's pairing (the
    pilot is on it, or going to it first) shows as "No trip" with that pairing next, rather than a later trip's leg.
    No leg left: state "No trip"."""
    now = now.astimezone(HST) if now.tzinfo else now.replace(tzinfo=HST)
    own = own if isinstance(own, dict) else {}
    today, at = now.date().isoformat(), stamp(now)
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
        return {"state": NO_TRIP, "attributes": {"source": SOURCE, "next": _next_pairing(pairs, today, unread_only=True),
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
