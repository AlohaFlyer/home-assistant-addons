"""FW-0072 (Ryan, Nov 11, 1.7.1): the layover page's van alerts and layover notes, for the admin's instance only.

Van alerts. Hark's sensor.hark_working_flight (Hark writes it over HA REST) gives the van as text at the layover
station's local time, e.g. "7:40 PM (19:40) Thu 2026-11-12, Example Hotel lobby" (and in its state "Layover SYD, van
2026-11-12 19:40"). parse_van reads the date, the 24 h time and the place after it; van_info puts it on the clock of
the layover station (the origin of the leg the van goes to: working.ZONES, daylight time included, so AEDT in the
southern summer) and returns the instant, the zone's abbreviation and the HST time. A station with no zone in
working.ZONES, a tz database that cannot load it, a van with no date or a local time a daylight time change skips is
no alert, with the reason for one log line: never a guess. A wall time that happens twice (the hour a daylight time
change repeats) is read as the first of the two, so an alert comes early rather than late.

due() says which alert goes now: each of OFFSETS (30 and 10 min before the van) is due from its mark until the van
time, once per (pairing, van instant, offset), the key in the DB. A new van time is a new key, so it re-arms both. A
late start (the app was off at the 30 min mark) sends only the latest alert still due before the van time and skips
the earlier ones, worded with the minutes really left; after the van time nothing is sent.

Layover notes. Ryan's notes per layover station (the IATA code, e.g. SYD), one JSON file each under
/share/flight_watcher/layovers (directory 0700, files 0600; never in git, never in a portal export): plain text, each
note at most NOTE_MAX characters, at most NOTES_MAX a station. <CITY>.guide.md is the tidied guide Claude writes in
the ticket flow ("Tidy the <CITY> layover notes", HANDOFF.md, Layover notes); read here at most GUIDE_MAX characters.
sensor_payload() builds the sensor's attributes within SENSOR_BYTES: the current layover station first (its guide and
its newest notes), then the others by their latest change; what does not fit is counted, not sent.

No MQTT, no HA, no clock of its own: watcher.py reads Hark's sensor, keeps the sent keys and publishes.
"""
import json
import math
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from working import ZONES

HST = timezone(timedelta(hours=-10))
UTC = timezone.utc
OFFSETS = (30, 10)  # minutes before the van (Ryan's ticket: 30 and 10)
STATION_RE = re.compile(r"^[A-Z]{3}$")
PAIRING_RE = re.compile(r"^[A-Z]\d{3,5}[A-Z]?$")
VAN_24_RE = re.compile(r"\((\d{1,2}):(\d{2})\)\s*(?:[A-Za-z]{3,9}\.?,?\s+)?(\d{4}-\d{2}-\d{2})")
VAN_ISO_RE = re.compile(r"(\d{4}-\d{2}-\d{2})[ T](\d{1,2}):(\d{2})(?!\d)")
VAN_12_RE = re.compile(r"\b(\d{1,2}):(\d{2})\s*([AaPp])\.?\s*[Mm]\.?(?![A-Za-z]).*?(\d{4}-\d{2}-\d{2})")
PLACE_MAX = 120
CTRL_RE = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\u2028\u2029\u202a-\u202e\u2066-\u2069]")
LINE_CTRL_RE = re.compile("[\x00-\x1f\x7f-\x9f\u2028\u2029\u202a-\u202e\u2066-\u2069]")
NOTE_MAX = 1000  # characters a note
NOTES_MAX = 200  # notes a station
GUIDE_MAX = 6000  # characters of a guide read
SENSOR_BYTES = 12000  # the notes sensor's attributes, under HA's 16 KB recorder limit (ASCII-escaped JSON)
ID_RE = re.compile(r"^[0-9a-f]{12}$")


# ---------------------------------------------------------------- van alerts
def _line(s, n):
    return LINE_CTRL_RE.sub(" ", str(s if s is not None else "")).strip()[:n].strip()


def parse_van(text):
    """(date 'YYYY-MM-DD', time 'HH:MM', place) from Hark's van text, or None when it has no date and time. The 24 h
    time in parentheses wins, then 'YYYY-MM-DD HH:MM', then a 12 h time with AM or PM before the date. The place is
    what follows the date after a comma ('Example Hotel lobby'), '' when there is none."""
    s = str(text or "")
    for rx, kind in ((VAN_24_RE, "24"), (VAN_ISO_RE, "iso"), (VAN_12_RE, "12")):
        m = rx.search(s)
        if not m:
            continue
        if kind == "24":
            h, mi, d = int(m.group(1)), int(m.group(2)), m.group(3)
        elif kind == "iso":
            d, h, mi = m.group(1), int(m.group(2)), int(m.group(3))
        else:
            h, mi, ap, d = int(m.group(1)), int(m.group(2)), m.group(3).upper(), m.group(4)
            if not 1 <= h <= 12:
                continue
            h = h % 12 + (12 if ap == "P" else 0)
        if not (0 <= h <= 23 and 0 <= mi <= 59):
            continue
        try:
            datetime.strptime(d, "%Y-%m-%d")
        except ValueError:
            continue
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
    text read)."""
    a = attrs if isinstance(attrs, dict) else {}
    pairing = str(a.get("pairing") or "").strip().upper()
    if not PAIRING_RE.match(pairing):
        return None, "no pairing"
    city = str(a.get("origin") or "").strip().upper()
    if not STATION_RE.match(city):
        return None, "no layover station"
    text = str(a.get("van") or "")
    got = parse_van(text)
    if not got:
        m = re.search(r"\bvan\b(.*)$", str(state or ""), re.I)
        got = parse_van(m.group(1)) if m else None
        text = str(state or "") if got else text
    if not got:
        return None, "no van time" if not text.strip() else "van time not read: no date and 24 h time in it"
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
            "text": _line(text, 200)}, ""


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
    shows it and each alert's status (pending, sent, skipped, missed)."""
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
            **{k: info[k] for k in ("pairing", "city", "zone", "abbr", "date", "local", "weekday", "hst", "hst_date",
                                    "hst_weekday", "place", "hotel", "text")},
            "alerts": alerts}


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


def ensure_dir(root):
    os.makedirs(root, mode=0o700, exist_ok=True)
    os.chmod(root, 0o700)


def _path(root, city, ext):
    return os.path.join(root, f"{city_ok(city)}{ext}")


def load(root, city):
    """{city, notes: [{id, at, text}], updated} of a station (oldest note first); empty when it has none."""
    c = city_ok(city)
    try:
        with open(_path(root, c, ".json"), encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        d = {}
    notes = [n for n in (d.get("notes") or []) if isinstance(n, dict) and isinstance(n.get("text"), str)
             and ID_RE.match(str(n.get("id") or ""))]
    return {"city": c, "notes": notes, "updated": str(d.get("updated") or "")}


def _write(root, city, doc):
    ensure_dir(root)
    path = _path(root, city, ".json")
    tmp = f"{path}.{secrets.token_hex(4)}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
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
    when it is longer); ('', '') when there is none."""
    p = _path(root, city, ".guide.md")
    try:
        with open(p, encoding="utf-8", errors="replace") as f:
            s = f.read(GUIDE_MAX + 1)
        mt = os.path.getmtime(p)
    except OSError:
        return "", ""
    s = CTRL_RE.sub("", s.replace("\r\n", "\n"))
    if len(s) > GUIDE_MAX:
        s = s[:GUIDE_MAX].rsplit("\n", 1)[0] + "\n\n(cut here: the guide is longer)"
    return s.strip(), datetime.fromtimestamp(mt, HST).strftime("%Y-%m-%dT%H:%M")


def cities(root):
    """The stations with notes or a guide, from the file names."""
    try:
        names = os.listdir(root)
    except OSError:
        return []
    out = set()
    for n in names:
        m = re.fullmatch(r"([A-Z]{3})(?:\.json|\.guide\.md)", n)
        if m:
            out.add(m.group(1))
    return sorted(out)


def signature(root):
    """What changes when a notes file or a guide changes (names, sizes and times), for a cheap re-publish check."""
    out = []
    for c in cities(root):
        for ext in (".json", ".guide.md"):
            try:
                st = os.stat(os.path.join(root, c + ext))
                out.append((c + ext, st.st_size, int(st.st_mtime_ns)))
            except OSError:
                pass
    return out


def _size(o):
    return len(json.dumps(o, separators=(",", ":")))


def sensor_payload(root, current="", last=None, limit=SENSOR_BYTES):
    """{count, current, cities: {CITY: {notes (newest first), guide, guide_at, total, left_out}}, order, last,
    left_out}: the current station first, then the others by their latest change, within limit bytes. A station's
    oldest notes go first when it does not fit whole; a station that does not fit at all is in left_out."""
    cur = str(current or "").upper() if STATION_RE.match(str(current or "").upper()) else ""
    docs = {}
    for c in cities(root):
        d = load(root, c)
        g, gat = guide(root, c)
        docs[c] = {"notes": list(reversed(d["notes"])), "guide": g, "guide_at": gat, "updated": d["updated"] or gat}
    others = sorted((c for c in docs if c != cur), key=lambda c: (docs[c]["updated"], c), reverse=True)
    order = ([cur] if cur in docs else []) + others
    out = {"count": sum(len(d["notes"]) for d in docs.values()), "current": cur, "cities": {}, "order": [],
           "last": last or {}, "left_out": []}
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
