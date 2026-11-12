"""FW-0069 (Ryan, 2026-11-09: "When we look at pilots' schedules, can we make it like when I view mine, where we give
schedules a version and we can cycle through them as you capture them? MM.01 style?"). Other pilots' schedule
versions, numbered M.NNN per bid month like Ryan's own (versions.py: 11.001 is the first November version, the
awarded line when the award is on file), for the pilot card.

What makes a version: only the pilot's pairings. A pairing is (trip id upper-cased, start date) for an item whose trip
is a pairing id (pot.PAIRING_RE: H3631, H3631B); its end date, seat, crew, block / credit, reserve or VAC days, FLICA's
totals and where the schedule came from do not count, because the three sources compute those differently and a
version must mean a change of trips. Only pairings that start on the pilot card's grid for that bid month count
(crewidx.grid_range: the day before the bid period to its last day), so the edges of FLICA's page and of the crew
index line up.

Sources (record "source"):
* lookup: FLICA Schedule Lookup (watcher.pilot_check, read only). Authoritative for the month it read: a new version
  whenever its pairings differ from the latest version of that pilot-month.
* rebuild: the crew index's reconstruction from pairing crew lines (watcher.pilot_check when the lookup is not
  readable, and after each crew index run for every pilot Ryan looked up). Partial (not every trip is read), so it
  never flip-flops against a lookup: the candidate is the rebuilt pairings plus every pairing of the latest version
  the crew index does not contradict (an ok read of that same trip and date taken after the latest version, whose crew
  line does not hold this employee number). A rebuilt pairing the latest version lacks is left out when its crew read
  is older than the latest version (that version saw the schedule after the read and the trip was not on it).
* award: the PBS award text on file (uploads, <YYYY-MM>_award.txt, pdfs.parse_award for any employee number). When
  a pilot-month gets its first version and the award parses for that pilot, the award is .001 and the capture becomes
  .002 only when its pairings differ. An award that arrives later is put in as .001 and the rest renumbered (as
  versions.set_award does for Ryan).

Storage (DB kv): pilot_versions_index = {emp: {name, months, last_seen}} (pilots Ryan looked up; last_seen is the
last lookup), pilot_versions:<emp>:<YYYY-MM> = [record, ...] oldest first. Caps: 60 pilots (the least recently looked
up go with their records), 4 bid months per pilot (the oldest goes), and per month the first version (the award)
plus the latest 24 (versions.MAX_PUBLISHED = 25). Records hold ver, n, at (UTC ISO), source, updated (FLICA's Last
Updated for a lookup), items [{trip, start, end, lay, seat}], days [[iso, code, lay]] (FLICA's for a lookup, the award
text's for the award, built here for a rebuild the way the pilot card's _rebuild draws it), totals, changes (pilot
neutral lines such as "added H3631B Nov 6-8 LAX"), and in the DB only fp (the pairing set) and win (the grid used).

Read only: nothing here touches FLICA, the network or MQTT. The functions that take db serialize on one lock, as the
watcher calls them from its check loop and (pub_pilot, pilot_cmd) from the MQTT thread."""
import json
import re
import threading
from datetime import date, datetime, timedelta, timezone

import crewidx as CI
import versions as VER
from pot import PAIRING_RE

INDEX_KEY = "pilot_versions_index"
MAX_PER_MONTH = VER.MAX_PUBLISHED  # the award (or first version) plus the latest 24, like Ryan's published list
MAX_PILOTS = 60
MAX_MONTHS = 4
SOURCES = ("award", "lookup", "rebuild")
FIRST_SAYS = {"award": "first version on file (awarded line)", "lookup": "first version on file (FLICA schedule)",
              "rebuild": "first version on file (rebuilt from crew lists)"}
INTERNAL = ("fp", "win")  # kept in the DB, never in the list file the card reads
BASE = "HNL"
HST = timezone(timedelta(hours=-10))
MON = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
ISO_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
MONTH_RE = re.compile(r"\d{4}-\d{2}")
_LOCK = threading.RLock()


# ---------------------------------------------------------------- pure helpers
def rec_key(emp, month):
    return f"pilot_versions:{emp}:{month}"


def ver_label(month, n):
    """'11.003': the month number and three digits, like versions.py."""
    return f"{int(month[5:7])}.{n:03d}"


def _iso(v):
    s = str(v or "")
    return s if ISO_RE.fullmatch(s) else ""


def _in(start, window):
    return not window or (window[0] or "") <= start <= (window[1] or "~")


def ident(it):
    """(TRIP, start) of a pairing item, None for anything else (VAC, SCR, a row without a start date)."""
    t, s = str((it or {}).get("trip") or "").strip().upper(), _iso((it or {}).get("start"))
    return (t, s) if s and PAIRING_RE.match(t) else None


def idents(items, window=None):
    """The pairing set of a list of items: {(TRIP, start)} for the pairings that start in window (lo, hi), ISO
    inclusive; every pairing when window is None."""
    out = set()
    for it in items or []:
        k = ident(it)
        if k and _in(k[1], window):
            out.add(k)
    return out


def fingerprint(items, window=None):
    """The pairing set as text (sorted), kept in the DB with each version."""
    return json.dumps(sorted(idents(items, window)))


def clean_items(items):
    """[{trip, start, end, lay, seat?}] sorted by start: the item fields a version keeps (crew, legs, block, credit and
    the like are the live payload's). A pairing id is upper-cased; an end before the start becomes the start."""
    out = []
    for it in items or []:
        s = _iso((it or {}).get("start"))
        t = str((it or {}).get("trip") or "").strip()
        if not s or not t:
            continue
        if PAIRING_RE.match(t.upper()):
            t = t.upper()
        e = _iso(it.get("end"))
        rec = {"trip": t, "start": s, "end": e if e >= s else s, "lay": str(it.get("lay") or "")}
        if it.get("seat"):
            rec["seat"] = str(it["seat"])
        out.append(rec)
    return sorted(out, key=lambda r: (r["start"], r["trip"]))


def _md(iso):
    d = date.fromisoformat(iso)
    return f"{MON[d.month - 1]} {d.day}"


def span(start, end):
    """'Nov 6', 'Nov 6-8', 'Nov 30-Dec 2'."""
    if not end or end <= start:
        return _md(start)
    if start[:7] == end[:7]:
        return f"{_md(start)}-{int(end[8:])}"
    return f"{_md(start)}-{_md(end)}"


def _line(word, it):
    lay = str(it.get("lay") or "").strip().upper()
    return f"{word} {it['trip'].upper()} {span(it['start'], it.get('end') or it['start'])}" + \
        (f" {lay}" if lay and lay not in ("-", BASE) else "")


def diff(old, new, window=None):
    """Pilot-neutral lines for what changed from old to new (two version records): 'added H3631B Nov 6-8 LAX',
    'removed H3631 Nov 6', by date (a removal ahead of an addition on the same day, so a swap reads in order). The
    first version of a month says where it came from."""
    if old is None:
        return [FIRST_SAYS.get((new or {}).get("source"), "first version on file")]
    oi = {ident(i): i for i in old.get("items") or [] if ident(i) and _in(ident(i)[1], window)}
    ni = {ident(i): i for i in new.get("items") or [] if ident(i) and _in(ident(i)[1], window)}
    rows = [(k[1], 0, k[0], _line("removed", oi[k])) for k in set(oi) - set(ni)]
    rows += [(k[1], 1, k[0], _line("added", ni[k])) for k in set(ni) - set(oi)]
    return [r[3] for r in sorted(rows)] or ["no pairing change"]


def _add(iso, n):
    return (date.fromisoformat(iso) + timedelta(days=n)).isoformat()


def _month_end(month):
    y, m = int(month[:4]), int(month[5:7])
    return (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)).isoformat()


def build_days(items, month, frm="", to="", base=BASE):
    """The pilot card's _rebuild grid as [[iso, code, lay]] (FW-0002, ported): one row a day from the day before the
    bid period (frm, its first day; the 1st when unknown) to its last day (to; the month's last day when unknown),
    widened for a trip that starts before or runs past it. A pairing's code and layover on its first day, '-' on the
    days away and the base on the day home; a trip that starts and ends the same day shows the base. A later trip's
    day is never overwritten by an earlier trip's tail, as on the card. Pairing items only; the rows stop at 45."""
    if not MONTH_RE.fullmatch(str(month or "")):
        return []
    frm = _iso(frm) or f"{month}-01"
    first, last = _add(frm, -1), _iso(to)
    trips = sorted((dict(i, end=_iso(i.get("end")) if _iso(i.get("end")) >= i["start"] else i["start"])
                    for i in items or [] if ident(i)), key=lambda i: (i["start"], i["trip"]))
    if not last:
        last = _month_end(month)
        for x in trips:
            last = max(last, x["end"])
    for x in trips:
        if x["start"] < first:
            first = x["start"]
        if x["start"] > last:
            last = x["end"]
    at = {}
    for x in trips:
        lay = str(x.get("lay") or "") or (base if x["start"] == x["end"] else "")
        d, k = _add(x["start"], 1), 0
        while d <= x["end"] and k < 14:
            if not (at.get(d) and at[d][0]):
                at[d] = ["", base if d == x["end"] else "-"]
            d, k = _add(d, 1), k + 1
        at[x["start"]] = [x["trip"].upper(), lay]
    days, d, k = [], first, 0
    while d <= last and k < 45:
        days.append([d, *(at.get(d) or ["", ""])])
        d, k = _add(d, 1), k + 1
    return days


def rebuild_items(trips):
    """crewidx.pilot_trips output -> version items, the trips the card draws in its grid (crewidx.grid_pick: of two
    trips on the same days the newest read). The layover the way the card's _rebuild shows it on the first day (the
    package's, else the route's one outstation; the base for a trip home the same day). Each item keeps its crew read
    time under 'read' for the merge (taken out before it is stored)."""
    grid, _ = CI.grid_pick([t for t in trips or [] if t])
    out = []
    for x in grid:
        st = [s for s in str(x.get("route") or "").split("-") if s]
        base = st[0] if st else BASE
        outs = []
        for s in st:
            if s != base and s not in outs:
                outs.append(s)
        lay = base if x["start"] == x["end"] else (x.get("lay") or (outs[0] if len(outs) == 1 else ""))
        it = {"trip": str(x["pairing"]).upper(), "start": x["start"], "end": x["end"], "lay": lay}
        if x.get("seat"):
            it["seat"] = x["seat"]
        if x.get("checked_at"):
            it["read"] = x["checked_at"]
        out.append(it)
    return out


def ts(v):
    """An aware datetime from an ISO text; a naive one (the crew index's HST wall clock) is HST. None when unreadable."""
    try:
        d = datetime.fromisoformat(str(v or ""))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=HST)


def contradicted(key, crew_rows, emp, after):
    """True when the crew index has an ok read of pairing key (TRIP, start) taken after `after` (an aware datetime;
    None: any time) whose crew line does not hold employee number emp."""
    t, s = key
    r = (crew_rows or {}).get(f"{t}|{s}")
    if not r or r.get("status") != "ok":
        return False
    at = ts(r.get("checked_at"))
    if at is None or (after is not None and at <= after):
        return False
    return str(emp) not in {str(c.get("emp") or "") for c in r.get("crew") or [] if isinstance(c, dict)}


def merge_rebuild(latest, rb_items, crew_rows, emp, window=None):
    """The rebuild's candidate pairings against the latest version (FW-0069 R3): the rebuilt pairings plus every
    pairing of the latest version that the crew index does not contradict (contradicted()); the items of a pairing
    the latest version holds come from it, the rest from the rebuild. A rebuilt pairing the latest version lacks whose
    crew read is not newer than that version is left out. No latest version: the rebuilt pairings. Rebuilt trips that
    start outside window (one running into the grid from before it) ride along for the days drawn and count for
    nothing."""
    rb = {ident(i): i for i in rb_items or [] if ident(i) and _in(ident(i)[1], window)}
    edge = [i for i in rb_items or [] if ident(i) and not _in(ident(i)[1], window)]
    if not latest:
        return sorted(list(rb.values()) + edge, key=lambda i: (i["start"], i["trip"]))
    after = ts(latest.get("at"))
    li = {ident(i): i for i in latest.get("items") or [] if ident(i) and _in(ident(i)[1], window)}
    out = {}
    for k, it in rb.items():
        if k in li:
            out[k] = li[k]
            continue
        read = ts(it.get("read"))
        if after is not None and read is not None and read <= after:
            continue  # read before the latest version, which does not have it: likely traded away since the read
        out[k] = it
    for k, it in li.items():
        if k not in out and not contradicted(k, crew_rows, emp, after):
            out[k] = it
    return sorted(list(out.values()) + edge, key=lambda i: (i["start"], i["trip"]))


def _strip(items):
    return [{k: v for k, v in i.items() if k != "read"} for i in items or []]


def record(month, n, at, source, items, days, totals=None, updated="", prev=None, window=None):
    """One version record (items cleaned, changes against prev)."""
    items = clean_items(_strip(items))
    rec = {"ver": ver_label(month, n), "n": n, "at": at, "source": source, "updated": updated or "", "items": items,
           "days": [list(d) for d in days or []],
           "totals": {k: v for k, v in (totals or {}).items() if k in ("block", "credit", "days_off") and v not in (None, "")},
           "fp": fingerprint(items, window), "win": list(window) if window else None}
    rec["changes"] = diff(prev, rec, window)
    return rec


def renumber(month, vers):
    """Number the versions 1.. in order and say again what each changed from the one before it (versions.set_award
    does the same for Ryan's)."""
    out = []
    for n, v in enumerate(vers, 1):
        v = {**v, "ver": ver_label(month, n), "n": n}
        v["changes"] = diff(out[-1] if out else None, v, v.get("win"))
        out.append(v)
    return out


def cap_month(vers):
    """The first version (the award when there is one) and the latest MAX_PER_MONTH - 1."""
    return vers if len(vers) <= MAX_PER_MONTH else [vers[0]] + vers[-(MAX_PER_MONTH - 1):]


POSTED_RE = re.compile(r"posted\s+([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2}),\s*(\d{4})", re.I)


def posted_at(updated):
    """The award's posting day ('Award posted Oct 20, 2026') as UTC ISO for 00:00 HST, '' when not given."""
    m = POSTED_RE.search(str(updated or ""))
    if not m or m.group(1).title() not in MON:
        return ""
    try:
        d = datetime(int(m.group(3)), MON.index(m.group(1).title()) + 1, int(m.group(2)), tzinfo=HST)
    except ValueError:
        return ""
    return d.astimezone(timezone.utc).isoformat()


def award_record(month, aw, now_iso, window=None, first=""):
    """pdfs.parse_award's line for one pilot as a version (source award): its items with the seat the award lists,
    its days (one empty row put ahead for the day before the bid period, first, so it lines up with the other
    versions), credit and days off. at is the posting day when the award text gives it (so a crew read after it can
    contradict an awarded trip), else now."""
    trips = (aw or {}).get("trips") or {}
    items = []
    for it in (aw or {}).get("items") or []:
        seat = (trips.get(f"{it.get('trip')}|{it.get('start')}") or {}).get("seat")
        items.append({**it, "seat": seat} if seat else dict(it))
    days = [list(d) for d in (aw or {}).get("days") or []]
    first = _iso(first)
    while first and days and _iso(days[0][0]) and days[0][0] > first:
        days.insert(0, [_add(days[0][0], -1), "", ""])
    return record(month, 1, posted_at((aw or {}).get("updated")) or award_fallback_at(now_iso, first), "award", items,
                  days, (aw or {}).get("totals"), (aw or {}).get("updated") or "Award", None, window)


def award_fallback_at(now_iso, first=""):
    """When the award text gives no posting day: 00:00 HST ten days before the grid's first day (awards post about
    then), or now when that is earlier. Not now on its own: a crew read made before now and after the award would
    then count as older than the award, and a rebuild would never add the trips it found."""
    first = _iso(first)
    if not first:
        return now_iso
    guess = datetime.fromisoformat(_add(first, -10)).replace(tzinfo=HST).astimezone(timezone.utc)
    now = ts(now_iso)
    return now_iso if now is not None and now <= guess else guess.isoformat()


# ---------------------------------------------------------------- the DB side (kv, one lock)
def _drop(db, key):
    """Delete one kv record (store.Store has no delete of its own: its connection, under its lock)."""
    if hasattr(db, "delete"):
        db.delete(key)
    elif hasattr(db, "db") and hasattr(db, "lock"):
        with db.lock:
            db.db.execute("DELETE FROM kv WHERE k=?", (key,))
    else:
        db.put(key, None)


def _index(db):
    idx = db.get(INDEX_KEY)
    return idx if isinstance(idx, dict) else {}


def _cap_pilots(db, idx, keep=""):
    """At most MAX_PILOTS pilots: the least recently looked up go, with every month of theirs."""
    while len(idx) > MAX_PILOTS:
        out = min((e for e in idx if e != keep), key=lambda e: (idx[e].get("last_seen") or "", e), default=None)
        if out is None:
            break
        for m in idx[out].get("months") or []:
            _drop(db, rec_key(out, m))
        del idx[out]


def register(db, emp, name="", now_iso=""):
    """Ryan looked this pilot up (watcher.pilot_cmd / pilot_check): add him to the registry or refresh his name and
    last_seen. Returns the registry entry."""
    emp = re.sub(r"\D", "", str(emp or ""))
    if not emp:
        return None
    with _LOCK:
        idx = _index(db)
        ent = dict(idx.get(emp) or {"name": "", "months": [], "last_seen": ""})
        if name:
            ent["name"] = str(name)
        ent["last_seen"] = now_iso or ent.get("last_seen") or ""
        idx[emp] = ent
        _cap_pilots(db, idx, emp)
        db.put(INDEX_KEY, idx)
        return ent


def registered(db, month=None):
    """The registered employee numbers (most recently looked up first); with month, those with versions of it."""
    with _LOCK:
        idx = _index(db)
    emps = [e for e in idx if not month or month in (idx[e].get("months") or [])]
    return sorted(emps, key=lambda e: (idx[e].get("last_seen") or "", e), reverse=True)


def versions_of(db, emp, month):
    with _LOCK:
        v = db.get(rec_key(emp, month))
    return v if isinstance(v, list) else []


def _save(db, emp, month, vers, name="", now_iso=""):
    """Store one pilot-month (capped), and the registry: the month added, the oldest beyond MAX_MONTHS dropped with
    its record (the month itself when it is the oldest), the pilot cap kept. Caller holds _LOCK."""
    idx = _index(db)
    ent = dict(idx.get(emp) or {"name": name or "", "months": [], "last_seen": now_iso or ""})
    if name and not ent.get("name"):
        ent["name"] = name
    months = sorted(set(ent.get("months") or []) | {month})
    drop = months[:-MAX_MONTHS] if len(months) > MAX_MONTHS else []
    for m in drop:
        if m != month:
            _drop(db, rec_key(emp, m))
    if month not in drop:
        db.put(rec_key(emp, month), cap_month(vers))
    ent["months"] = [m for m in months if m not in drop]
    idx[emp] = ent
    _cap_pilots(db, idx, emp)
    db.put(INDEX_KEY, idx)


def _seed(emp, month, award, now_iso, window, first):
    """[the award record] when the award text on file parses for this pilot, else []."""
    if not award:
        return []
    try:
        aw = award(emp, month)
    except Exception:
        aw = None
    if not aw or not aw.get("items"):
        return []
    return [award_record(month, aw, now_iso, window, first)]


def capture_lookup(db, emp, name, sched, now_iso, window=None, award=None):
    """A readable FLICA Schedule Lookup of the pilot's bid month sched["month"] ({month, updated, days, items,
    totals}): a new version when its pairings differ from the latest version of that pilot-month. award(emp, month)
    gives the pilot's awarded line (pdfs.parse_award) or None, for a month with no version yet. window is the card's
    grid for the month (crewidx.grid_range: first, last). Returns the version labels made ([] when none)."""
    emp = re.sub(r"\D", "", str(emp or ""))
    month = str((sched or {}).get("month") or "")
    if not emp or not MONTH_RE.fullmatch(month) or not (sched.get("days") or sched.get("items")):
        return []
    with _LOCK:
        vers = versions_of(db, emp, month)
        made = []
        if not vers:
            vers = _seed(emp, month, award, now_iso, window, (window or ("",))[0])
            made = [v["ver"] for v in vers]
        latest = vers[-1] if vers else None
        items = clean_items(sched.get("items"))
        if latest is None or idents(items, window) != idents(latest.get("items"), window):
            n = (latest["n"] if latest else 0) + 1
            vers = vers + [record(month, n, now_iso, "lookup", items, sched.get("days"), sched.get("totals"),
                                  sched.get("updated"), latest, window)]
            made.append(vers[-1]["ver"])
        if made:
            _save(db, emp, month, vers, name, now_iso)
        return made


def capture_rebuild(db, emp, name, month, trips, crew_rows, now_iso, window=None, frm="", to="", award=None):
    """The crew index's rebuild of the pilot's bid month (trips: crewidx.pilot_trips; crew_rows: store.crew_rows)
    against the latest version (merge_rebuild). frm / to: the bid period's first and last day, for the days drawn.
    A month with no version and nothing rebuilt makes none. Returns the version labels made ([] when none)."""
    emp = re.sub(r"\D", "", str(emp or ""))
    if not emp or not MONTH_RE.fullmatch(str(month or "")):
        return []
    rb = rebuild_items(trips)
    with _LOCK:
        vers = versions_of(db, emp, month)
        made = []
        if not vers:
            vers = _seed(emp, month, award, now_iso, window, (window or ("",))[0])
            made = [v["ver"] for v in vers]
        latest = vers[-1] if vers else None
        if latest is None and not idents(rb, window):
            return []
        cand = merge_rebuild(latest, rb, crew_rows, emp, window)
        if latest is None or idents(cand, window) != idents(latest.get("items"), window):
            n = (latest["n"] if latest else 0) + 1
            vers = vers + [record(month, n, now_iso, "rebuild", cand, build_days(cand, month, frm, to), {}, "",
                                  latest, window)]
            made.append(vers[-1]["ver"])
        if made:
            _save(db, emp, month, vers, name, now_iso)
        return made


def set_award(db, emp, month, aw, now_iso, window=None, first=""):
    """The award for a pilot-month that already has versions (it came after them): it becomes .001 (replacing an
    earlier award) and the rest are renumbered after it; a first version with the same pairings as the award goes
    (the award stands for it). Nothing changes when the same award is on file already. Returns True when stored."""
    emp = re.sub(r"\D", "", str(emp or ""))
    if not emp or not MONTH_RE.fullmatch(str(month or "")) or not (aw or {}).get("items"):
        return False
    rec = award_record(month, aw, now_iso, window, first)
    with _LOCK:
        vers = versions_of(db, emp, month)
        if not vers:
            return False
        old = [v for v in vers if v.get("source") == "award"]
        if old and old[0].get("items") == rec["items"] and old[0].get("days") == rec["days"]:
            return False
        rest = [v for v in vers if v.get("source") != "award"]
        if rest and idents(rest[0].get("items"), window) == idents(rec["items"], window):
            rest = rest[1:]
        _save(db, emp, month, renumber(month, [rec] + rest))
        return True


def clear_award(db, emp, month):
    """1.7.2 (review of contract 1 revision 3): the month's award file was removed (the admin's Remove of a pilot's
    upload with nothing to restore): this pilot's award record for it goes and the rest are numbered again from .001
    (versions.clear_award does the same for the instance's own pilot). True when one went."""
    emp = re.sub(r"\D", "", str(emp or ""))
    if not emp or not MONTH_RE.fullmatch(str(month or "")):
        return False
    with _LOCK:
        vers = versions_of(db, emp, month)
        rest = [v for v in vers if v.get("source") != "award"]
        if len(rest) == len(vers):
            return False
        db.put(rec_key(emp, month), cap_month(renumber(month, rest)))
        return True


def history(db, emp):
    """The list file's content for one pilot: {emp: {name, months: {YYYY-MM: [record, ...]}}}, records oldest first
    without fp / win; {} for a pilot not in the registry."""
    emp = re.sub(r"\D", "", str(emp or ""))
    with _LOCK:
        ent = _index(db).get(emp) if emp else None
        if not ent:
            return {}
        months = {}
        for m in sorted(ent.get("months") or []):
            vers = versions_of(db, emp, m)
            if vers:
                months[m] = [{k: v for k, v in r.items() if k not in INTERNAL} for r in vers]
    return {emp: {"name": ent.get("name") or "", "months": months}}


def summary(db, emp):
    """The sensor's short form: {YYYY-MM: {count, current, awarded}} (awarded '' when no award is on file)."""
    out = {}
    for m, vers in ((history(db, emp).get(re.sub(r"\D", "", str(emp or ""))) or {}).get("months") or {}).items():
        out[m] = {"count": len(vers), "current": vers[-1]["ver"],
                  "awarded": vers[0]["ver"] if vers[0].get("source") == "award" else ""}
    return out
