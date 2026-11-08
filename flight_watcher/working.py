"""FW-0067 (Ryan, Nov 8): the working flight from the pilot's own FLICA schedule, for every Watcher instance
(sensor.<prefix>_working_flight), so a second pilot's Working Flight view shows his own line. Hark's
sensor.hark_working_flight (Ryan only) adds the release, MEL, NOTAMs and live status; this one is what the schedule
says ("per schedule").

Pure: no FLICA, no MQTT, no clock of its own. Times: an own trip's legs are HST minutes from 00:00 HST of the trip's
first day (pot.parse_legs). Hawaii keeps no DST, so HST is a fixed UTC-10. A station's local time is HST plus its
standard offset (pot.TZ), the same table parse_legs used to turn FLICA's printed local times into HST, so the date at
the origin is the day FLICA printed. A station missing from pot.TZ shows its printed local time and HST, and its date
falls back to the HST date."""
import re
from datetime import datetime, timedelta, timezone

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


def _local(dt, stn):
    """Station wall clock (naive) for an aware time, from the standard offset in pot.TZ; None for a station not in it."""
    off = TZ.get(stn)
    if off is None:
        return None
    return (dt.astimezone(timezone.utc) + timedelta(hours=off)).replace(tzinfo=None)


def _pair(local_hm, dt):
    """'16:30 local, 16:30 HST'; just 'HH:MM HST' when the local time is unknown."""
    hst = dt.astimezone(HST).strftime("%H:%M")
    return f"{local_hm} local, {hst} HST" if local_hm else f"{hst} HST"


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


def _report(first, rec, dep, dep_l, frm):
    """The report for a duty that starts with this leg. The trip's first duty: FLICA's check in (HNL time, so HST).
    A later duty (after a layover of LAYOVER_MIN_H or more): 1:15 before departure out of domicile, 1:00 in domicile
    (PWA 2.19.b), shown as local and HST."""
    if first and _mins(rec.get("report")) is not None:
        return f"{_hhmm(_mins(rec.get('report')))} HST"
    before = REPORT_DOMICILE_MIN if frm == DOMICILE else REPORT_AWAY_MIN
    rep = dep - timedelta(minutes=before)
    lm = _mins(dep_l)
    if lm is not None:
        local = _hhmm(lm - before)
    else:
        loc = _local(rep, frm)
        local = loc.strftime("%H:%M") if loc else ""
    return _pair(local, rep)


def _legs(p, rec):
    """A pairing's legs on absolute HST time with their number, origin, date at the origin and their duty's report.
    [] when the legs are not read yet (or the record is not usable)."""
    raw = rec.get("legs") if isinstance(rec, dict) else None
    if not isinstance(raw, list) or not raw:
        return []
    out, prev, rep = [], None, ""
    try:
        for i, lg in enumerate(raw):
            dep = p["day0"] + timedelta(minutes=int(lg["dep"]))
            arr = p["day0"] + timedelta(minutes=int(lg["arr"]))
            frm = str(lg.get("frm") or (prev["to"] if prev else DOMICILE)).upper()
            to = str(lg.get("to") or "").upper()
            new_duty = prev is None or dep - prev["arr"] >= timedelta(hours=LAYOVER_MIN_H)
            if new_duty:
                rep = _report(prev is None, rec, dep, lg.get("dep_l"), frm)
            loc = _local(dep, frm)
            blk = lg.get("blk")
            x = {"trip": p["trip"], "key": p["key"], "i": i, "flt": str(lg.get("flt") or ""), "frm": frm, "to": to,
                 "dep": dep, "arr": arr, "dep_l": str(lg.get("dep_l") or ""), "arr_l": str(lg.get("arr_l") or ""),
                 "blk": int(blk) if blk not in (None, "") else int((arr - dep).total_seconds() // 60),
                 "date": (loc or dep.astimezone(HST)).date().isoformat(), "report": rep, "duty_start": new_duty}
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
    working leg but can be the next pairing. No leg left: state "No trip"."""
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
    if cur is None:
        return {"state": NO_TRIP, "attributes": {"source": SOURCE, "next": _next_pairing(pairs, today, unread_only=True),
                                                 "updated": at, "updated_by": UPDATED_BY}}
    p = next(q for q in pairs if q["key"] == cur["key"])
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
    dep_loc, arr_loc = _local(cur["dep"], cur["frm"]), _local(cur["arr"], cur["to"])
    dep_l = cur["dep_l"] or (dep_loc.strftime("%H:%M") if dep_loc else "")
    arr_l = cur["arr_l"] or (arr_loc.strftime("%H:%M") if arr_loc else "")
    flight = _flight(cur)
    attrs = {
        "pairing": cur["trip"],
        "leg": f"{cur['i'] + 1} of {cur['n']}",
        "flight": flight,
        "date": cur["date"],
        "origin": cur["frm"],
        "dest": cur["to"],
        "dep_sched": _pair(dep_l, cur["dep"]),
        "arr_sched": _pair(arr_l, cur["arr"]),
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


def news(payload):
    """The payload without the fields that move on every call (VOLATILE), to tell a real change from a re-stamp."""
    a = (payload or {}).get("attributes") or {}
    return {"state": (payload or {}).get("state"), "attributes": {k: v for k, v in a.items() if k not in VOLATILE}}
