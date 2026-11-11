"""FW-0072 (Ryan, Nov 11, 1.7.1): the layover page's van alerts and layover notes, for the admin's instance only.

Van alerts. Hark's sensor.hark_working_flight (Hark writes it over HA REST) gives the van as text at the layover
station's local time, e.g. "7:40 PM (19:40) Thu 2026-11-12, Example Hotel lobby" (and in its state "Layover SYD, van
2026-11-12 19:40"). parse_van reads the date, the 24 h time and the place after it; van_info puts it on the clock of
the layover station (the origin of the leg the van goes to: working.ZONES, daylight time included, so AEDT in the
southern summer) and returns the instant, the zone's abbreviation and the HST time. A station with no zone in
working.ZONES, a tz database that cannot load it, a van with no date or a local time a daylight time change skips is
no alert, with the reason for one log line: never a guess. So is a van whose text says a weekday the date is not
("Fri 2026-11-12", a Thursday) and a 'YYYY-MM-DD HH:MM' with AM or PM, seconds or a zone after it ("2026-11-12 7:40
PM", "2026-11-12T08:40:00Z"): read as the station's 24 h time those would be 12 h or the zone's offset off. A wall time
that happens twice (the hour a daylight time change repeats) is read as the first of the two, so an alert comes early
rather than late.

due() says which alert goes now: each of OFFSETS (30 and 10 min before the van) is due from its mark until the van
time, once per (pairing, van instant, offset), the key in the DB. A new van time is a new key, so it re-arms both. A
late start (the app was off at the 30 min mark) sends only the latest alert still due before the van time and skips
the earlier ones, worded with the minutes really left; after the van time nothing is sent.

Layover notes. Ryan's notes per layover station (the IATA code, e.g. SYD), one JSON file each under
/share/flight_watcher/layovers (directory 0700, files 0600; never in git, never in a portal export): plain text, each
note at most NOTE_MAX characters, at most NOTES_MAX a station. <CITY>.guide.md is the tidied guide Claude writes in
the ticket flow ("Tidy the <CITY> layover notes", HANDOFF.md, Layover notes); read here at most GUIDE_MAX characters.
sensor_payload() builds the sensor's attributes within SENSOR_BYTES: the current layover station first (its guide and
its newest notes), then the others by their latest change; what does not fit is counted, not sent. The folder is under
/share, which the HOM app maps too, so every read and write goes through the folder opened without following a link
(O_NOFOLLOW, then *at calls on its fd): a file is read only when it is a plain file (never through a symlink, never
waiting on a FIFO, size capped), and a folder that is a symlink is refused, never chmod'ed or written through. A notes
file that is there but cannot be read (a hand edit that broke its JSON, not an object) is never taken as empty: a note
command on it is refused with nothing changed, and the sensor leaves that city out ("unreadable").

No MQTT, no HA, no clock of its own: watcher.py reads Hark's sensor, keeps the sent keys and publishes.
"""
import contextlib
import json
import math
import os
import re
import secrets
import stat
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from working import ZONES

HST = timezone(timedelta(hours=-10))
UTC = timezone.utc
OFFSETS = (30, 10)  # minutes before the van (Ryan's ticket: 30 and 10)
STATION_RE = re.compile(r"^[A-Z]{3}$")
PAIRING_RE = re.compile(r"^[A-Z]\d{3,5}[A-Z]?$")
# the card (www/flight-watcher-layover-card.js _parseVan) reads the van with the same three patterns
VAN_24_RE = re.compile(r"\((\d{1,2}):(\d{2})\)\s*(?:([A-Za-z]{3,9})\.?,?\s+)?(\d{4}-\d{2}-\d{2})")
# never followed by more of a time, AM or PM, or a zone ('Z', '+11', 'UTC', 'GMT'): those fall through to no alert
VAN_ISO_RE = re.compile(r"(?:\b([A-Za-z]{3,9})\.?,?\s+)?(\d{4}-\d{2}-\d{2})[ T](\d{1,2}):(\d{2})"
                        r"(?![\d:]|\s*[AaPp]\.?\s*[Mm](?![A-Za-z])|\s*(?:Z\b|[+-]\d|UTC|GMT))")
VAN_12_RE = re.compile(r"\b(\d{1,2}):(\d{2})\s*([AaPp])\.?\s*[Mm]\.?(?![A-Za-z])(.*?)(\d{4}-\d{2}-\d{2})")
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")  # date.weekday() order
PLACE_MAX = 120
# lone surrogates too: json.loads lets "\ud83d" through, and a UTF-8 file cannot hold one
CTRL_RE = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\u2028\u2029\u202a-\u202e\u2066-\u2069\ud800-\udfff]")
LINE_CTRL_RE = re.compile("[\x00-\x1f\x7f-\x9f\u2028\u2029\u202a-\u202e\u2066-\u2069\ud800-\udfff]")
NOTE_MAX = 1000  # characters a note
NOTES_MAX = 200  # notes a station
GUIDE_MAX = 6000  # characters of a guide read
SENSOR_BYTES = 12000  # the notes sensor's attributes, under HA's 16 KB recorder limit (ASCII-escaped JSON)
NOTES_FILE_MAX = 4 * 1024 * 1024  # bytes of a notes file read (NOTES_MAX notes of NOTE_MAX characters fit in 1 MB)
ID_RE = re.compile(r"^[0-9a-f]{12}$")
O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
O_NONBLOCK = getattr(os, "O_NONBLOCK", 0)
O_DIRECTORY = getattr(os, "O_DIRECTORY", 0)


# ---------------------------------------------------------------- van alerts
def _line(s, n):
    return LINE_CTRL_RE.sub(" ", str(s if s is not None else "")).strip()[:n].strip()


def weekdays(s):
    """The weekday names in s ('Thu', 'Thurs', 'Thursday', 3 letters at least), as {'Thu'}; empty when it names none."""
    out = set()
    for w in re.findall(r"[A-Za-z]+", str(s or "")):
        lw = w.lower()
        if 3 <= len(lw) <= 9:
            out.update(f[:3].title() for f in WEEKDAYS if f.startswith(lw))
    return out


def parse_van(text):
    """(date 'YYYY-MM-DD', time 'HH:MM', place) from Hark's van text, or None when it has no date and time. The 24 h
    time in parentheses wins, then 'YYYY-MM-DD HH:MM' (none with AM, PM, seconds or a zone after it), then a 12 h time
    with AM or PM before the date. A weekday in it that is not the date's ('Fri 2026-11-12') is None: the text
    contradicts itself, so no alert rather than one a day off. The place is what follows the date (or the time) after
    a comma ('Example Hotel lobby'), '' when there is none."""
    s = str(text or "")
    for rx, kind in ((VAN_24_RE, "24"), (VAN_ISO_RE, "iso"), (VAN_12_RE, "12")):
        m = rx.search(s)
        if not m:
            continue
        if kind == "24":
            h, mi, wd, d = int(m.group(1)), int(m.group(2)), m.group(3), m.group(4)
        elif kind == "iso":
            wd, d, h, mi = m.group(1), m.group(2), int(m.group(3)), int(m.group(4))
        else:
            h, mi, ap, wd, d = int(m.group(1)), int(m.group(2)), m.group(3).upper(), m.group(4), m.group(5)
            if not 1 <= h <= 12:
                continue
            h = h % 12 + (12 if ap == "P" else 0)
        if not (0 <= h <= 23 and 0 <= mi <= 59):
            continue
        try:
            day = datetime.strptime(d, "%Y-%m-%d")
        except ValueError:
            continue
        said = weekdays(wd)
        if said and said != {WEEKDAYS[day.weekday()][:3].title()}:
            return None
        rest = s[m.end():]
        place = rest.split(",", 1)[1] if rest.lstrip().startswith(",") else ""
        return d, f"{h:02d}:{mi:02d}", _line(place, PLACE_MAX)
    return None


def zone_of(stn):
    """The station's tz database zone (working.ZONES), or None: no zone, or tzdata cannot load it. Never a fixed offset
    (pot.TZ has no daylight time)."""
    name = ZONES.get(str(stn or ""))
    if not name:
        return None
    try:
        return ZoneInfo(name)
    except (KeyError, OSError, ValueError):  # ZoneInfoNotFoundError is a KeyError
        return None


def local_instant(date_s, hhmm, zone):
    """The aware time of a wall clock reading at a zone; None when that reading does not exist there (the hour a
    daylight time change skips). A reading that happens twice is the first of the two (fold 0)."""
    wall = datetime.strptime(f"{date_s} {hhmm}", "%Y-%m-%d %H:%M")
    loc = wall.replace(tzinfo=zone, fold=0)
    if loc.astimezone(UTC).astimezone(zone).replace(tzinfo=None) != wall:
        return None
    return loc


def abbr(dt):
    """'AEDT', 'PST', 'HST'; a zone that has no letters for it ('+11') as 'UTC+11'."""
    n = dt.tzname() or ""
    return n if re.fullmatch(r"[A-Z]{2,6}", n) else f"UTC{n}" if re.fullmatch(r"[+-]\d{2,4}", n) else n or "local"


def van_info(attrs, state=""):
    """(info, '') or (None, why) from Hark's sensor: its attributes and state. info: pairing, city (the layover
    station: the origin of the leg the van goes to), zone, abbr, date and local ('19:40') at the station, hst and
    hst_date, at (an aware UTC time), place (after the date in the van text, else the hotel), hotel, text (the van
    text read). The state's "van YYYY-MM-DD HH:MM" stands in only when the van attribute has no date at all: one with a
    date that cannot be read for sure (a weekday that is not the date's, AM or PM after a 24 h time) is no alert, never
    the state's reading of the same (likely wrong) date."""
    a = attrs if isinstance(attrs, dict) else {}
    pairing = str(a.get("pairing") or "").strip().upper()
    if not PAIRING_RE.match(pairing):
        return None, "no pairing"
    city = str(a.get("origin") or "").strip().upper()
    if not STATION_RE.match(city):
        return None, "no layover station"
    text = str(a.get("van") or "")
    got = parse_van(text)
    if not got and not re.search(r"\d{4}-\d{2}-\d{2}", text):
        m = re.search(r"\bvan\b(.*)$", str(state or ""), re.I)
        got = parse_van(m.group(1)) if m else None
        text = str(state or "") if got else text
    if not got:
        return None, "no van time" if not text.strip() else \
            "van time not read: no date and time in it that is sure (a weekday that is not the date's, AM or PM or " \
            "a zone after a 24 h time)"
    date_s, hhmm, place = got
    zone = zone_of(city)
    if zone is None:
        return None, f"no time zone known for {city}"
    loc = local_instant(date_s, hhmm, zone)
    if loc is None:
        return None, f"{date_s} {hhmm} does not exist at {city} (a daylight time change)"
    hst = loc.astimezone(HST)
    hotel = _line(a.get("hotel"), PLACE_MAX)
    return {"pairing": pairing, "city": city, "zone": ZONES[city], "abbr": abbr(loc), "date": date_s, "local": hhmm,
            "weekday": loc.strftime("%a"), "hst": hst.strftime("%H:%M"), "hst_date": hst.strftime("%Y-%m-%d"),
            "hst_weekday": hst.strftime("%a"), "at": loc.astimezone(UTC), "place": place or hotel, "hotel": hotel,
            "text": _line(text, 200), "source": "hark"}, ""


def key(info, minutes):
    """The DB key of one alert: pairing, the van instant (UTC) and the offset."""
    return f"{info['pairing']}|{info['at'].astimezone(UTC).strftime('%Y-%m-%dT%H:%MZ')}|{minutes}"


def due(info, done, now):
    """(send, skip): the offsets to send now (at most one) and the earlier ones a late start skips. An offset is due
    from its mark until the van time and only while its key is not in done."""
    at = info["at"]
    if now >= at:
        return [], []
    ready = [m for m in OFFSETS if now >= at - timedelta(minutes=m) and key(info, m) not in done]
    if not ready:
        return [], []
    last = min(ready)
    return [last], sorted((m for m in ready if m != last), reverse=True)


def minutes_left(info, now):
    return max(1, math.ceil((info["at"] - now).total_seconds() / 60))


def render(info, minutes, now):
    """(title, message) of one alert, worded from now: 'Van in 30 min: 19:40 AEDT (22:40 HST), Example Hotel
    lobby'."""
    left = minutes_left(info, now)
    where = info["place"] or info["hotel"] or info["city"]
    title = f"Van {info['city']} {info['local']} {info['abbr']}"
    message = f"Van in {left} min: {info['local']} {info['abbr']} ({info['hst']} HST), {where}"
    return title, message


def event(info, minutes, now):
    """The {T}/event/van payload."""
    title, message = render(info, minutes, now)
    return {"kind": "van", "key": key(info, minutes), "pairing": info["pairing"], "city": info["city"],
            "van_local": info["local"], "van_date": info["date"], "abbr": info["abbr"], "van_hst": info["hst"],
            "van_hst_date": info["hst_date"], "minutes": minutes, "minutes_left": minutes_left(info, now),
            "hotel": info["hotel"], "place": info["place"], "title": title, "message": message,
            "van_utc": info["at"].astimezone(UTC).isoformat(timespec="seconds"),
            "at_hst": now.astimezone(HST).isoformat(timespec="seconds")}


def sensor(info, why, done, now):
    """The layover_van sensor's payload: state the van instant (a timestamp, None without one); the van as the card
    shows it, where it comes from (source: package or hark) and each alert's status (pending, sent, skipped, missed).
    Only what the card reads from it: not Hark's
    van text or hotel (the card shows those from Hark's own sensor), so the retained topic and HA's recorder keep no
    more of Hark's sensor than the card shows."""
    if not info:
        return {"at": None, "why": why}
    alerts = []
    for m in OFFSETS:
        st = (done.get(key(info, m)) or {}).get("how")
        if not st:
            st = "missed" if now >= info["at"] else "pending"
        alerts.append({"minutes": m, "status": st,
                       "at_hst": (info["at"] - timedelta(minutes=m)).astimezone(HST).strftime("%H:%M")})
    return {"at": info["at"].astimezone(UTC).isoformat(timespec="seconds"), "why": "",
            **{k: info[k] for k in ("pairing", "city", "abbr", "date", "local", "weekday", "hst", "hst_weekday",
                                    "place")},
            "source": info.get("source") or "hark", "alerts": alerts}


# ---------------------------------------------------------------- the pairings package's van times
# Ryan, Nov 11: "remember van times are published in the pairings pack monthly and can be updated from time to time".
# The package's text copy (uploads/<YYYY-MM>_pairings.txt, pdftotext -layout of each uploaded PDF) prints, inside each
# pairing, after a duty that ends away from base: the "D-END:" line, the hotel line ("<HOTEL>   <phone>   VAN HH:MM";
# calendar cells may follow on the right), the next duty's "REPT: HH:MML/HH:MMGMT" and its legs. VAN 00:00 is no van
# time given (every hotel line of the Oct to Dec 2026 packages reads 00:00 but four "HOTEL TBA" charter lines reading
# 00:30, which is no pickup before their reports: a ride time, not a clock time). So a VAN is taken as the van's
# local time at the layover station only when it is not 00:00 and falls at most VAN_BEFORE_REPT_MIN before the next
# duty's report (the van takes the crew to that report); anything else is no van time from the package, with the
# reason, and the van falls through to Hark's. Phone numbers are never read.
PKG_LEG_RE = re.compile(r"^\s*(\S+)\s+(DH\s+)?(\d{1,4})[A-Z]?\*?\s+([A-Z]{3})\s*-\s*([A-Z]{3})\s+(\d{1,2}):(\d{2})/"
                        r"\d{1,2}:\d{2}\s+\d{1,2}:\d{2}/\d{1,2}:\d{2}")
PKG_DEND_RE = re.compile(r"^\s*D-END:\s+\d{1,2}:\d{2}L")
PKG_REPT_RE = re.compile(r"^\s+REPT:\s+(\d{1,2}):(\d{2})L")
PKG_VAN_RE = re.compile(r"\bVAN\s+(\d{1,2}):(\d{2})\b")
VAN_BEFORE_REPT_MIN = 180  # a package VAN this long before the next report at most is the van to that report
HOTEL_MAX = 80


def _hm(h, m):
    h, m = int(h), int(m)
    return f"{h:02d}:{m:02d}" if 0 <= h <= 23 and 0 <= m <= 59 else ""


def _mins(hm):
    return int(hm[:2]) * 60 + int(hm[3:]) if hm else None


def pickup_ok(x):
    """A layover's package VAN is a pickup time: given (not 00:00) and at most VAN_BEFORE_REPT_MIN before its report."""
    return bool(x["van"] and x["rept"]) and (_mins(x["rept"]) - _mins(x["van"])) % 1440 <= VAN_BEFORE_REPT_MIN


def package_vans(text):
    """The van times of a pairings package's text copy: {month ('2026-12'), start, end (the bid period, ISO), pairings
    ({id: [layover]}), layovers, with_van}. A layover: stn (the station the next duty leaves from), flt (its first
    leg's flight number), dep (that leg's local departure 'HH:MM'), rept (the duty's local report), van ('HH:MM' as
    printed, '' for 00:00), hotel (the name before the phone, never the phone), day (the DAY cell), n (its order in the
    pairing). with_van counts the layovers whose VAN is a pickup time (pickup_ok). Only blocks with a pairing header (pdfs._blocks: 'Hxxxx BASE REPT'); a layover whose next leg leaves
    another station than the one the duty ended at is left out."""
    import pdfs as PDF
    out = {}
    n_lay = n_van = 0
    for b in PDF._blocks(text):
        lays, last_to, pend = [], "", None
        for ln in b["lines"]:
            m = PKG_LEG_RE.match(ln)
            if m:
                if pend is not None and pend["rept"] and pend["stn"] == m.group(4):
                    dep = _hm(m.group(6), m.group(7))
                    if dep:
                        lays.append({**pend, "flt": m.group(3).lstrip("0") or "0", "dep": dep, "day": m.group(1),
                                     "n": len(lays) + 1})
                pend = None
                last_to = m.group(5)
                continue
            if PKG_DEND_RE.match(ln):
                pend = {"stn": last_to, "hotel": "", "van": "", "rept": "", "hv": False} if last_to else None
                continue
            if pend is None:
                continue
            v = PKG_VAN_RE.search(ln)
            if v and not pend["hv"]:
                pend["hv"] = True
                van = _hm(v.group(1), v.group(2))
                pend["van"] = "" if van in ("", "00:00") else van
                # the name ends at a run of spaces, a parenthesis or a phone-like run of digits (never kept)
                name = re.split(r"\s{2,}|\(|\+?\d[\d\s().-]{6,}", ln[:v.start()].strip(), maxsplit=1)[0]
                pend["hotel"] = _line(name, HOTEL_MAX)
                continue
            r = PKG_REPT_RE.match(ln)
            if r and not pend["rept"]:
                pend["rept"] = _hm(r.group(1), r.group(2))
        for x in lays:
            x.pop("hv", None)
        if lays:
            out.setdefault(b["id"], []).extend(lays)
            n_lay += len(lays)
            n_van += sum(1 for x in lays if pickup_ok(x))
    start, end = PDF.period_bounds(text)
    return {"month": PDF.package_month(text), "start": start, "end": end, "pairings": out, "layovers": n_lay,
            "with_van": n_van}


def _base_id(pairing):
    return re.sub(r"[A-Z]$", "", pairing) if re.match(r"^[A-Z]\d{3,5}[A-Z]$", pairing) else pairing


def same_pairing(a, b):
    """True when two pairing ids are the same trip: equal, or one a FLICA-rebuilt copy of the other (H3631B, H3631)."""
    a, b = str(a or "").strip().upper(), str(b or "").strip().upper()
    return bool(a and b) and _base_id(a) == _base_id(b)


def package_van(packages, leg):
    """(info, '') or (None, why): the van of the layover the leg leaves from, from the pairings packages (package_vans
    each). leg: pairing, start (the trip's first day, '' when not known), city (the leg's origin, the layover station),
    flt (its flight number, digits), dep ('HH:MM' local, '' when not known), date (its departure date at the origin).
    The layover is the one of that pairing (the exact id, else a rebuilt copy's base id) at that station whose next leg
    is this one: the same flight number and local departure where both are known, at least one of them. A package
    whose bid period does not hold the trip's first day is not looked in. info is van_info's, source 'package'. why is
    '' when no package covers the layover (none on file, or not in it); when one does but gives no van time, why
    follows "the pairings package" in a sentence ("gives no van time for H3681 SYD (VAN 00:00)", "VAN 00:30 for ...
    is no pickup before the 21:10 report", two that differ)."""
    pairing = str(leg.get("pairing") or "").strip().upper()
    city = str(leg.get("city") or "").strip().upper()
    flt = str(leg.get("flt") or "").strip().lstrip("0")
    dep = str(leg.get("dep") or "").strip()
    start = str(leg.get("start") or "")
    if not PAIRING_RE.match(pairing) or not STATION_RE.match(city) or not packages:
        return None, ""
    hits = []
    for pk in packages:
        if start and pk.get("start") and pk.get("end") and not pk["start"] <= start <= pk["end"]:
            continue
        lays = (pk.get("pairings") or {}).get(pairing)
        if lays is None:
            lays = (pk.get("pairings") or {}).get(_base_id(pairing)) or []
        for x in lays:
            if x["stn"] != city:
                continue
            checks = [(flt, x["flt"]), (dep, x["dep"])]
            known = [(a, b) for a, b in checks if a and b]
            if known and all(a == b for a, b in known):
                hits.append((pk.get("month") or "", x))
    if not hits:
        return None, ""
    if len({(x["van"], x["rept"], x["dep"]) for _, x in hits}) > 1:
        return None, f"lists more than one {city} layover of {pairing} for this leg"
    month, x = hits[0]
    if not x["van"]:
        return None, f"gives no van time for {pairing} {city} (VAN 00:00)"
    van, rept, depm = _mins(x["van"]), _mins(x["rept"]), _mins(x["dep"])
    if not pickup_ok(x):
        return None, f"VAN {x['van']} for {pairing} {city} is no pickup before the {x['rept']} report"
    try:
        day = datetime.strptime(str(leg.get("date") or ""), "%Y-%m-%d")
    except ValueError:
        return None, "has the layover, but the leg's date is not known"
    rept_day = day - timedelta(days=1 if rept > depm else 0)  # a report before midnight for a departure after it
    van_day = rept_day - timedelta(days=1 if van > rept else 0)  # a van before midnight for a report after it
    zone = zone_of(city)
    if zone is None:
        return None, f"has the layover, but no time zone is known for {city}"
    date_s = van_day.strftime("%Y-%m-%d")
    loc = local_instant(date_s, x["van"], zone)
    if loc is None:
        return None, f"VAN {date_s} {x['van']} does not exist at {city} (a daylight time change)"
    hst = loc.astimezone(HST)
    return {"pairing": pairing, "city": city, "zone": ZONES[city], "abbr": abbr(loc), "date": date_s, "local": x["van"],
            "weekday": loc.strftime("%a"), "hst": hst.strftime("%H:%M"), "hst_date": hst.strftime("%Y-%m-%d"),
            "hst_weekday": hst.strftime("%a"), "at": loc.astimezone(UTC), "place": x["hotel"], "hotel": x["hotel"],
            "text": f"VAN {x['van']} in the {month or 'uploaded'} pairings package", "source": "package",
            "package": month, "report": x["rept"]}, ""


# ---------------------------------------------------------------- layover notes
class Bad(ValueError):
    """A note command refused, with the reason in plain words."""


def city_ok(city):
    c = str(city or "").strip().upper()
    if not STATION_RE.match(c):
        raise Bad("the city must be a 3-letter station code")
    return c


def clean_note(text):
    """Plain text: line feeds kept (CR LF as LF, at most two blank lines in a row), every other control, line or
    paragraph separator and bidi override out, trimmed; refused when empty or over NOTE_MAX characters."""
    if not isinstance(text, str):
        raise Bad("the note must be text")
    s = CTRL_RE.sub("", text.replace("\r\n", "\n").replace("\r", "\n"))
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s).strip()
    if not s:
        raise Bad("the note is empty")
    if len(s) > NOTE_MAX:
        raise Bad(f"the note is over {NOTE_MAX} characters")
    return s


FOLDER_BAD = "the layover notes folder is a link or not a folder: nothing changed"


@contextlib.contextmanager
def _folder(root, create=False):
    """The notes folder's fd, opened without following a symlink (O_NOFOLLOW | O_DIRECTORY); None when it is not
    there (made 0700 first with create). Bad when it is a symlink or not a folder."""
    if create:
        os.makedirs(os.path.dirname(os.path.abspath(root)), exist_ok=True)
        try:
            os.mkdir(root, 0o700)
        except FileExistsError:
            pass
    try:
        fd = os.open(root, os.O_RDONLY | O_DIRECTORY | O_NOFOLLOW)
    except FileNotFoundError:
        if create:
            raise
        fd = None
    except OSError:
        raise Bad(FOLDER_BAD) from None
    try:
        if fd is not None and not stat.S_ISDIR(os.fstat(fd).st_mode):
            raise Bad(FOLDER_BAD)
        yield fd
    finally:
        if fd is not None:
            os.close(fd)


def _read(dfd, name, cap, whole=True):
    """(bytes, os.stat_result) of name in the folder dfd: a plain file only, never through a symlink (O_NOFOLLOW),
    never waiting on a FIFO (O_NONBLOCK), the read itself stopping at cap + 1 bytes. whole: a file over cap is a
    ValueError; else its first cap bytes. FileNotFoundError when there is none (portal.read_plain's rules)."""
    fd = os.open(name, os.O_RDONLY | O_NOFOLLOW | O_NONBLOCK, dir_fd=dfd)
    chunks, n = [], 0
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise ValueError("not a plain file")
        if whole and st.st_size > cap:
            raise ValueError("too big")
        while n <= cap:
            b = os.read(fd, min(1024 * 1024, cap + 1 - n))
            if not b:
                break
            chunks.append(b)
            n += len(b)
    finally:
        os.close(fd)
    if whole and n > cap:
        raise ValueError("too big")
    return b"".join(chunks)[:cap], st


def _names(dfd):
    return sorted(n for n in os.listdir(dfd) if re.fullmatch(r"[A-Z]{3}(?:\.json|\.guide\.md)", n))


def ensure_dir(root):
    """The notes folder, made 0700 when missing and set 0700 through its own fd (never chmod through a link)."""
    with _folder(root, create=True) as dfd:
        os.fchmod(dfd, 0o700)


def load(root, city):
    """{city, notes: [{id, at, text}], updated} of a station (oldest note first); empty when it has no file. Bad when
    its file is there but cannot be read (not a plain file, too big, not UTF-8 JSON, not an object with a list of
    notes) or the folder is a link: never taken as empty, so a write never replaces notes it could not read."""
    c = city_ok(city)
    try:
        with _folder(root) as dfd:
            raw = _read(dfd, f"{c}.json", NOTES_FILE_MAX)[0] if dfd is not None else None
        d = json.loads(raw.decode("utf-8")) if raw is not None else {}
    except FileNotFoundError:
        d = {}
    except Bad:
        raise
    except (OSError, ValueError):  # JSONDecodeError and UnicodeDecodeError are ValueErrors
        raise Bad(f"the {c} notes file could not be read: nothing changed") from None
    if not isinstance(d, dict) or not isinstance(d.get("notes") or [], list):
        raise Bad(f"the {c} notes file could not be read: nothing changed")
    notes = [n for n in (d.get("notes") or []) if isinstance(n, dict) and isinstance(n.get("text"), str)
             and ID_RE.match(str(n.get("id") or ""))]
    return {"city": c, "notes": notes, "updated": str(d.get("updated") or "")}


def _write(root, city, doc):
    """<CITY>.json, atomically: a 0600 temp file made in the folder's fd (O_EXCL | O_NOFOLLOW), then renamed over the
    old one in the same folder (a symlink in its place is replaced, never followed)."""
    name = f"{city_ok(city)}.json"
    with _folder(root, create=True) as dfd:
        os.fchmod(dfd, 0o700)
        tmp = f"{name}.{secrets.token_hex(4)}.tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | O_NOFOLLOW, 0o600, dir_fd=dfd)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(doc, f, ensure_ascii=False, indent=1)
                f.flush()
                os.fchmod(f.fileno(), 0o600)
            os.replace(tmp, name, src_dir_fd=dfd, dst_dir_fd=dfd)
        except BaseException:
            try:
                os.unlink(tmp, dir_fd=dfd)
            except OSError:
                pass
            raise


def add(root, city, text, now_iso):
    """Add one note; the station's doc after it. Bad when refused."""
    c, t = city_ok(city), clean_note(text)
    d = load(root, c)
    if len(d["notes"]) >= NOTES_MAX:
        raise Bad(f"{c} has {NOTES_MAX} notes already: tidy them first")
    d["notes"].append({"id": secrets.token_hex(6), "at": now_iso, "text": t})
    d["updated"] = now_iso
    _write(root, c, d)
    return d


def delete(root, city, nid, now_iso):
    """Remove one note by its id; the station's doc after it. Bad when there is no such note."""
    c, nid = city_ok(city), str(nid or "")
    d = load(root, c)
    keep = [n for n in d["notes"] if n["id"] != nid]
    if not ID_RE.match(nid) or len(keep) == len(d["notes"]):
        raise Bad("no such note")
    d["notes"], d["updated"] = keep, now_iso
    _write(root, c, d)
    return d


def guide(root, city):
    """(text, 'YYYY-MM-DDTHH:MM' HST of its file time) of <CITY>.guide.md, at most GUIDE_MAX characters (cut at a line
    when it is longer); ('', '') when there is none, or it is a symlink, a FIFO or anything but a plain file (the HOM
    app maps /share: a link to /data/options.json must never become a guide on the sensor)."""
    c = city_ok(city)
    try:
        with _folder(root) as dfd:
            if dfd is None:
                return "", ""
            raw, st = _read(dfd, f"{c}.guide.md", (GUIDE_MAX + 1) * 4, whole=False)
    except (OSError, ValueError):  # Bad (the folder a link) is a ValueError
        return "", ""
    s = raw.decode("utf-8", errors="replace")[:GUIDE_MAX + 1]
    mt = st.st_mtime
    s = CTRL_RE.sub("", s.replace("\r\n", "\n"))
    if len(s) > GUIDE_MAX:
        s = s[:GUIDE_MAX].rsplit("\n", 1)[0] + "\n\n(cut here: the guide is longer)"
    return s.strip(), datetime.fromtimestamp(mt, HST).strftime("%Y-%m-%dT%H:%M")


def cities(root):
    """The stations with notes or a guide, from the file names; none when the folder is missing or a link."""
    try:
        with _folder(root) as dfd:
            names = _names(dfd) if dfd is not None else []
    except (OSError, ValueError):
        return []
    return sorted({n[:3] for n in names})


def signature(root):
    """What changes when a notes file or a guide changes (names, kinds, sizes and times; a link is not followed), for
    a cheap re-publish check."""
    out = []
    try:
        with _folder(root) as dfd:
            for n in (_names(dfd) if dfd is not None else []):
                try:
                    st = os.stat(n, dir_fd=dfd, follow_symlinks=False)
                    out.append((n, stat.S_IFMT(st.st_mode), st.st_size, int(st.st_mtime_ns)))
                except OSError:
                    pass
    except (OSError, ValueError):
        return []
    return out


def _size(o):
    return len(json.dumps(o, separators=(",", ":")))


def sensor_payload(root, current="", last=None, limit=SENSOR_BYTES):
    """{count, current, cities: {CITY: {notes (newest first), guide, guide_at, total, left_out}}, order, last,
    left_out, unreadable}: the current station first, then the others by their latest change, within limit bytes. A
    station's oldest notes go first when it does not fit whole; a station that does not fit at all is in left_out; one
    whose notes file cannot be read (load's Bad) is in unreadable, and the others still go."""
    cur = str(current or "").upper() if STATION_RE.match(str(current or "").upper()) else ""
    docs, unreadable = {}, []
    for c in cities(root):
        try:
            d = load(root, c)
        except Bad:
            unreadable.append(c)
            continue
        g, gat = guide(root, c)
        docs[c] = {"notes": list(reversed(d["notes"])), "guide": g, "guide_at": gat, "updated": d["updated"] or gat}
    others = sorted((c for c in docs if c != cur), key=lambda c: (docs[c]["updated"], c), reverse=True)
    order = ([cur] if cur in docs else []) + others
    out = {"count": sum(len(d["notes"]) for d in docs.values()), "current": cur, "cities": {}, "order": [],
           "last": last or {}, "left_out": [], "unreadable": unreadable}
    for c in order:
        d = docs[c]
        entry = {"notes": d["notes"], "guide": d["guide"], "guide_at": d["guide_at"], "total": len(d["notes"]),
                 "left_out": 0}
        trial = {**out, "cities": {**out["cities"], c: entry}, "order": out["order"] + [c]}
        while _size(trial) > limit and entry["notes"]:
            entry["notes"] = entry["notes"][:-1]
            entry["left_out"] += 1
            trial = {**out, "cities": {**out["cities"], c: entry}, "order": out["order"] + [c]}
        if _size(trial) > limit and entry["guide"]:
            entry["guide"] = ""
            entry["guide_left_out"] = True
            trial = {**out, "cities": {**out["cities"], c: entry}, "order": out["order"] + [c]}
        if _size(trial) > limit:
            out["left_out"].append(c)
            continue
        out = trial
    return out
