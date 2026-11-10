"""Tickets (0.10.1, Ryan): bug reports and feature requests from the dashboard, kept as files.

/share/flight_watcher/tickets/FW-0001/ticket.json, numbered FW-0001, FW-0002 ... across every Watcher instance
(a counter file under fcntl.flock). No network, no MQTT.

Photos (FW-0003): up to 10 per ticket, screenshot.jpg (photo 1), screenshot_2.jpg ... screenshot_10.jpg (.png
for a PNG), listed in index order in ticket.json "images"; "image" stays the first one for older readers. The
card sends the ticket first with a client-made "cid" and its photo count, then each photo as its own message
{cid, i, image} (add_image), so no single MQTT message carries more than one photo.

Fixed push (FW-0007): fixed_event() turns the ticket act() just returned into the event/ticket_fixed payload when
that action moved it to fixed (once per move: a second "fixed" on a fixed ticket only corrects the version).

Edit and delete (FW-0049, Ryan): edit() changes title, narrative, steps, expected or page while the ticket is still
new or reopened (EDITABLE), so nothing changes under whoever is working it; each edit keeps the old text in its
history line. delete() works in any status and moves the folder to tickets/.deleted/<id>-<stamp> (nothing is
destroyed); listings skip it and its number is never given out again. Both take allowed_reporter like act(): a
pilot instance only touches its own tickets, Ryan's instance any.

1.7.0 (Release C, tickets on a pilot's portal): with allowed_reporter set (a pilot instance) act() takes only the
pilot's own actions (roles.PILOT_TICKET_ACTIONS: verify, reopen, note), and a ticket of another reporter answers
"<id> not found", the same as a missing one, so a pilot cannot tell which ids exist. create() and store_photo() take
the pilot's quotas (roles.PILOT_TICKET_LIMITS) as limits; count_recent() and open_count() feed the daily and open
caps; fixed_moves() lists every move into fixed of one reporter's tickets for the Watcher's own ticket_fixed alert.
The admin (allowed_reporter None, limits None) works exactly as before.

1.7.0 review (Release C security review): every ticket text is checked and cleaned here, whoever sent it: text that is
not well-formed Unicode (a lone surrogate, which Home Assistant's JSON parser refuses, so one ticket would freeze
every tickets sensor that lists it) is refused; a one-line field (title, page, version) keeps no control character,
line or paragraph separator or bidi control and no run of spaces, so it can never start a forged line in the add-on
log; a text field (narrative, steps, expected, a note) keeps only \\n and \\t among the controls. With limits (a
pilot) act() and edit() keep his caps too: at most limits["changes_per_day"] notes, reopens, verifies and edits in
24 h (a small ledger under .quota/), limits["history"] of his history lines on one ticket, limits["text_bytes"] of
ticket.json and limits["ticket_bytes"] for ticket.json and its photos together; a verify or a reopen with no text is
never refused by them (each follows a fix by whoever works the ticket). A pilot deletes a ticket only while it is new.
ticket.json is written as UTF-8 (ensure_ascii off), so a non-ASCII character costs its UTF-8 bytes, not a 6 or 12
byte escape. Ticket ids are ASCII digits only.
"""
import base64
import binascii
import fcntl
import json
import os
import re
from contextlib import contextmanager
from datetime import datetime, timezone

import roles

KINDS = ("bug", "feature")
ID_RE = re.compile(r"^FW-([0-9]{4,})$")  # 1.7.0 review: ASCII digits only (\d takes any Unicode digit)
MAX_IMAGE = 2 * 1024 * 1024
MAX_IMAGES = 10  # FW-0003: photos per ticket
CID_RE = re.compile(r"^[A-Za-z0-9_-]{6,40}$")
MAX_TEXT = {"title": 200, "narrative": 10000, "steps": 5000, "expected": 5000, "page": 300, "version": 40}
# action -> new status (None keeps the status); verify closes a fixed ticket
ACTIONS = {"triage": "triaged", "progress": "in_progress", "fixed": "fixed", "verify": "closed",
           "reopen": "reopened", "close": "closed", "note": None}
OPEN = ("new", "triaged", "in_progress", "fixed", "reopened")
EDITABLE = ("new", "reopened")  # FW-0049: edits only before anyone works it (or after its reporter reopened it)
EDIT_FIELDS = ("title", "narrative", "steps", "expected", "page")
DELETED = ".deleted"  # FW-0049: tickets/.deleted/<id>-<stamp>/, out of every listing
DELETED_RE = re.compile(r"^FW-([0-9]{4,})-")
LINE_FIELDS = ("title", "page", "version")  # 1.7.0 review: one-line fields; the rest of MAX_TEXT is text
QUOTA_DIR = ".quota"  # 1.7.0 review: <base>/.quota/<pilot>.json, the times of his accepted changes (24 h)
# characters a one-line field never keeps (they become a space): controls (Cc), line and paragraph separators and the
# bidi embeddings, overrides and isolates; a text field keeps \n and \t (\r and the separators become \n)
_BIDI = "\u202a-\u202e\u2066-\u2069"
_LINE_DROP_RE = re.compile(f"[\x00-\x1f\x7f-\x9f\u2028\u2029{_BIDI}]")
_TEXT_DROP_RE = re.compile(f"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f{_BIDI}]")


class NotUnicode(ValueError):
    """Ticket text that is not well-formed Unicode (a lone surrogate)."""


def well_formed(s):
    """True when s encodes as UTF-8 (no lone surrogate, which json.loads lets through as \\ud800)."""
    try:
        s.encode("utf-8")
        return True
    except UnicodeEncodeError:
        return False


def clean_line(v, n):
    """A one-line field as stored: no control character, separator or bidi control, one space between words, at
    most n code points. NotUnicode for text that is not well-formed Unicode."""
    s = str(v or "")
    if not well_formed(s):
        raise NotUnicode("text is not valid Unicode")
    return re.sub(r"\s+", " ", _LINE_DROP_RE.sub(" ", s)).strip()[:n]


def clean_text(v, n):
    """A text field as stored: CR LF, CR and the line and paragraph separators as LF, no other control character
    but LF and tab and no bidi control, at most n code points. NotUnicode for text that is not well-formed Unicode."""
    s = str(v or "")
    if not well_formed(s):
        raise NotUnicode("text is not valid Unicode")
    s = re.sub("\r\n?|[\u2028\u2029]", "\n", s)
    return _TEXT_DROP_RE.sub("", s).strip()[:n]


def clean_field(k, v):
    """clean_line or clean_text for a MAX_TEXT field."""
    return (clean_line if k in LINE_FIELDS else clean_text)(v, MAX_TEXT[k])


def _wf(v):
    """A value as it may go on a sensor: a str with every lone surrogate as U+FFFD (Home Assistant's JSON parser
    refuses one), anything else as it is. Tickets written before the 1.7.0 review, or straight into the folder."""
    if isinstance(v, str) and not well_formed(v):
        return v.encode("utf-16", "surrogatepass").decode("utf-16", "replace")
    return v


@contextmanager
def _locked(base):
    os.makedirs(base, exist_ok=True)
    with open(os.path.join(base, ".lock"), "a+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def _json_bytes(obj):
    """ticket.json's bytes: UTF-8 with ensure_ascii off (1.7.0 review: an astral character is its 4 bytes, not a
    12-byte escape); a value that cannot be UTF-8 (a lone surrogate from before the review) keeps the escapes."""
    try:
        return json.dumps(obj, indent=1, ensure_ascii=False).encode("utf-8")
    except UnicodeEncodeError:
        return json.dumps(obj, indent=1).encode("ascii")


def _write_json(path, obj, data=None):
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(_json_bytes(obj) if data is None else data)
    os.replace(tmp, path)


def _ids(base):
    try:
        return sorted(d for d in os.listdir(base) if ID_RE.match(d) and os.path.isfile(os.path.join(base, d, "ticket.json")))
    except OSError:
        return []


def _next_id(base):
    """Next number from the counter file, never below a ticket folder already there. Call under _locked."""
    cpath = os.path.join(base, "counter")
    try:
        n = int(open(cpath).read().strip() or 0)
    except (OSError, ValueError):
        n = 0
    nums = [int(ID_RE.match(d).group(1)) for d in os.listdir(base) if ID_RE.match(d)]
    try:  # FW-0049: a deleted ticket's number is never given out again, even with the counter file lost
        nums += [int(DELETED_RE.match(d).group(1)) for d in os.listdir(os.path.join(base, DELETED)) if DELETED_RE.match(d)]
    except OSError:
        pass
    n = max([n] + nums) + 1
    tmp = cpath + ".tmp"
    open(tmp, "w").write(str(n))
    os.replace(tmp, cpath)
    return f"FW-{n:04d}"


def _int(v, default=None):
    """int(v), or default when v is not a number. json.loads takes Infinity and 1e999 (float inf), and int() of
    those raises OverflowError, so all three errors are caught here."""
    try:
        return int(v)
    except (TypeError, ValueError, OverflowError):
        return default


def decode_image(data_url):
    """(bytes, ext) from 'data:image/jpeg;base64,...' (or bare base64); JPEG or PNG by magic bytes only.
    Raises ValueError with the reason."""
    s = str(data_url or "").strip()
    if s.startswith("data:"):
        head, _, s = s.partition(",")
        if ";base64" not in head:
            raise ValueError("image must be base64")
    if len(s) > (MAX_IMAGE * 4) // 3 + 8:
        raise ValueError("image over 2 MB")
    try:
        raw = base64.b64decode(s, validate=False)
    except (binascii.Error, ValueError):
        raise ValueError("image is not valid base64")
    if len(raw) > MAX_IMAGE:
        raise ValueError("image over 2 MB")
    if raw[:3] == b"\xff\xd8\xff":
        return raw, "jpg"
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        return raw, "png"
    raise ValueError("image is not a JPEG or PNG")


def image_name(i, ext):
    """Photo i (1-based) -> screenshot.jpg, screenshot_2.jpg ... (ext jpg or png)."""
    return f"screenshot.{ext}" if i == 1 else f"screenshot_{i}.{ext}"


def _photo_no(name):
    m = re.match(r"^screenshot(?:_([0-9]+))?\.(?:jpg|png)$", name or "")
    return int(m.group(1) or 1) if m else 0


def images(t):
    """The ticket's photo file names, photo 1 first; a ticket from before FW-0003 has only "image"."""
    v = t.get("images")
    if isinstance(v, list):
        return [x for x in v if isinstance(x, str) and x]
    return [t["image"]] if t.get("image") else []


def create(base, payload, reporter, now, limits=None):
    """(ticket, '') or (None, error). payload {kind, title, narrative, steps?, expected?, page?, version?, image?,
    cid?, images?}. image is photo 1 sent inline (cards before FW-0003). cid (client-made) and images (how many
    photos the card will send on ticket/image, 0 to 10; 10 when left out) open the ticket for add_image.
    1.7.0: limits (a pilot's roles.PILOT_TICKET_LIMITS): at most limits["photos"] photos, no inline image (his photos
    come on ticket/image, where the Watcher checks and re-encodes them), and the daily and open caps are the caller's
    (count_recent, open_count, under the same lock: create_limited)."""
    if not isinstance(payload, dict):
        return None, "not an object"
    if limits and payload.get("image"):
        return None, "photos are sent after the ticket, one by one"
    kind = str(payload.get("kind") or "").strip().lower()
    if kind not in KINDS:
        return None, "kind must be bug or feature"
    try:
        f = {k: clean_field(k, payload.get(k)) for k in MAX_TEXT}
    except NotUnicode as e:
        return None, str(e)
    if not f["title"]:
        return None, "title is required"
    if not f["narrative"]:
        return None, "narrative is required"
    img = None
    if payload.get("image"):
        try:
            img = decode_image(payload["image"])
        except ValueError as e:
            return None, str(e)
    cid = str(payload.get("cid") or "").strip()
    if not CID_RE.match(cid):
        cid = ""  # the ticket still files; it just takes no photos later
    want = 1 if img else 0
    top = min(MAX_IMAGES, int(limits["photos"])) if limits else MAX_IMAGES
    if cid:
        want = max(want, min(top, _int(payload.get("images"), top)))
    with _locked(base):
        if limits:
            why = quota_refusal(base, reporter, limits, now)
            if why:
                return None, why
        tid = _next_id(base)
        d = os.path.join(base, tid)
        os.makedirs(d, exist_ok=True)
        names = []
        if img:
            names.append(image_name(1, img[1]))
            with open(os.path.join(d, names[0]), "wb") as fh:
                fh.write(img[0])
        t = {"id": tid, "kind": kind, "title": f["title"], "narrative": f["narrative"], "steps": f["steps"],
             "expected": f["expected"], "page": f["page"], "version": f["version"], "reporter": reporter,
             "status": "new", "created_at": now, "updated_at": now, "version_fixed": "",
             "image": names[0] if names else "", "images": names, "cid": cid, "images_expected": want,
             "history": []}
        _write_json(os.path.join(d, "ticket.json"), t)
    return t, ""


def add_image(base, payload, reporter, now):
    """(ticket, '') or (None, error). payload {cid, i (1 to 10), image}: photo i of the newest ticket this reporter
    filed with that cid. Refused, with nothing written: an unknown cid, a photo number past the count the ticket was
    opened for, a photo number already there, an 11th photo, or an image that fails decode_image."""
    if not isinstance(payload, dict):
        return None, "not an object"
    cid = str(payload.get("cid") or "").strip()
    if not CID_RE.match(cid):
        return None, "bad cid"
    i = _int(payload.get("i"))
    if i is None:
        return None, "bad photo number"
    if not 1 <= i <= MAX_IMAGES:
        return None, f"photo number must be 1 to {MAX_IMAGES}"
    try:
        raw, ext = decode_image(payload.get("image"))
    except ValueError as e:
        return None, str(e)
    return store_photo(base, cid, i, raw, ext, reporter, now)


def photo_target(base, cid, i, reporter, limits=None):
    """'' when photo i may still be stored on the newest ticket this reporter filed with cid, else why not (the same
    words store_photo gives). The Watcher asks before it puts a pilot's chunks together, so a photo that cannot be
    stored is refused at its first chunk."""
    with _locked(base):
        t, err = _photo_ticket(base, cid, i, reporter, limits)
    return err


def _photo_ticket(base, cid, i, reporter, limits):
    """(ticket, '') or (None, why) for photo i of cid. Call under _locked."""
    top = min(MAX_IMAGES, int(limits["photos"])) if limits else MAX_IMAGES
    if not isinstance(i, int) or isinstance(i, bool) or not 1 <= i <= top:
        return None, f"photo number must be 1 to {top}"
    t = None
    for tid in sorted(_ids(base), key=lambda x: int(x[3:]), reverse=True):  # newest first: just filed
        x = load(base, tid)
        if x and x.get("cid") == cid and x.get("reporter") == reporter:
            t = x
            break
    if not t:
        return None, "no ticket for that photo"
    names = images(t)
    want = min(_int(t.get("images_expected") or 0, 0), top)
    if i > want:
        return None, f"{t['id']} takes {want} photos, not photo {i}"
    if any(_photo_no(n) == i for n in names):
        return None, f"{t['id']} already has photo {i}"
    if len(names) >= top:
        return None, f"{t['id']} already has {top} photos"
    return t, ""


def photo_bytes(base, t):
    """The bytes of the photos a ticket holds now (its folder's files named in images)."""
    n = 0
    for name in images(t):
        try:
            n += os.path.getsize(os.path.join(base, t["id"], os.path.basename(name)))
        except OSError:
            pass
    return n


def store_photo(base, cid, i, raw, ext, reporter, now, limits=None):
    """(ticket, '') or (None, error): photo i (raw bytes, ext jpg or png) on the newest ticket this reporter filed
    with cid. 1.7.0: limits (a pilot's): at most limits["photos"] photos and limits["ticket_bytes"] bytes in the
    ticket, counted with this one (1.7.0 review: its photos and ticket.json together, the council's total)."""
    if ext not in ("jpg", "png") or not isinstance(raw, (bytes, bytearray)) or not raw:
        return None, "image is not a JPEG or PNG"
    with _locked(base):
        t, err = _photo_ticket(base, cid, i, reporter, limits)
        if not t:
            return None, err
        names = images(t)
        name = image_name(i, ext)
        if limits:
            after = sorted(names + [name], key=_photo_no)
            size = photo_bytes(base, t) + len(raw) + len(_json_bytes({**t, "images": after, "image": after[0],
                                                                      "updated_at": now}))
            if size > int(limits["ticket_bytes"]):
                mb = int(limits["ticket_bytes"]) / (1024 * 1024)
                return None, f"{t['id']} would be over {mb:g} MB in all with this photo"
        path = os.path.join(base, t["id"], name)
        with open(path + ".tmp", "wb") as fh:
            fh.write(raw)
        os.replace(path + ".tmp", path)
        names = sorted(names + [name], key=_photo_no)
        t["images"], t["image"], t["updated_at"] = names, names[0], now
        _write_json(os.path.join(base, t["id"], "ticket.json"), t)
    return t, ""


def load(base, tid):
    try:
        with open(os.path.join(base, tid, "ticket.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _quota_path(base, reporter):
    return os.path.join(base, QUOTA_DIR, f"{reporter}.json")


def _changes(base, reporter, since):
    """1.7.0 review: the times (UTC timestamps) of reporter's accepted changes (notes, reopens, verifies, edits) at or
    after since, from <base>/.quota/<reporter>.json. Call under _locked. Kept outside ticket.json so a delete does not
    reset the count, and read in one small file instead of every ticket on every command."""
    if not roles.NAME_RE.fullmatch(str(reporter or "")):
        return []
    try:
        with open(_quota_path(base, reporter), encoding="utf-8") as f:
            d = json.load(f)
        v = d.get("changes") if isinstance(d, dict) else None
    except (OSError, ValueError):
        v = None
    return [x for x in v or [] if isinstance(x, (int, float)) and not isinstance(x, bool) and x >= since]


def _note_change(base, reporter, now, limits):
    """Record one accepted change of reporter at now (ISO). Call under _locked."""
    if not roles.NAME_RE.fullmatch(str(reporter or "")):
        return
    t = _ts(now)
    t = datetime.now(timezone.utc).timestamp() if t is None else t
    keep = _changes(base, reporter, t - 86400)[-(int(limits["changes_per_day"]) - 1 or 1):] + [t]
    os.makedirs(os.path.join(base, QUOTA_DIR), exist_ok=True)
    _write_json(_quota_path(base, reporter), None, json.dumps({"changes": keep}).encode("ascii"))


def change_refusal(base, t, reporter, limits, now, size, free=False):
    """1.7.0 review: why a pilot's change to ticket t may not be stored ('' when it may). size is the bytes of
    ticket.json as it would be written. free (a verify or reopen with no text: each follows a fix by whoever works the
    ticket, so he cannot repeat one on his own) passes every cap. Call under _locked."""
    if free:
        return ""
    now_t = _ts(now)
    now_t = datetime.now(timezone.utc).timestamp() if now_t is None else now_t
    per_day = int(limits["changes_per_day"])
    if len(_changes(base, reporter, now_t - 86400)) >= per_day:
        return f"ticket limit reached: {per_day} changes in 24 h"
    mine = sum(1 for h in t.get("history") or [] if isinstance(h, dict) and h.get("actor") == reporter)
    if mine >= int(limits["history"]):
        return f"ticket limit reached: {int(limits['history'])} changes on {t['id']}"
    if size > int(limits["text_bytes"]):
        return f"ticket limit reached: {t['id']} would be over {int(limits['text_bytes']) // 1024} KB of text"
    if size + photo_bytes(base, t) > int(limits["ticket_bytes"]):
        mb = int(limits["ticket_bytes"]) / (1024 * 1024)
        return f"ticket limit reached: {t['id']} would be over {mb:g} MB in all"
    return ""


def act(base, payload, actor, now, allowed_reporter=None, limits=None):
    """(ticket, '') or (None, error). payload {id, action, text?, version?}. allowed_reporter limits a pilot
    instance to its own tickets. verify needs a fixed ticket; only reopen and note touch a closed one.
    1.7.0 review: limits (a pilot's, with allowed_reporter) keep his caps (change_refusal); the text is clean_text."""
    if not isinstance(payload, dict):
        return None, "not an object"
    try:
        text = clean_text(payload.get("text"), 5000)
    except NotUnicode as e:
        return None, str(e)
    tid, action = str(payload.get("id") or "").strip().upper(), str(payload.get("action") or "").strip().lower()
    if not ID_RE.match(tid):
        return None, "bad id"
    if action not in ACTIONS:
        return None, f"unknown action {action}"
    if allowed_reporter and action not in roles.PILOT_TICKET_ACTIONS:  # 1.7.0: the worker statuses are not his
        return None, f"a pilot may only {', '.join(roles.PILOT_TICKET_ACTIONS[:-1])} or add a note, not {action}"
    if allowed_reporter and action == "note" and not text:
        return None, "a note needs text"
    with _locked(base):
        t = load(base, tid)
        if not t or (allowed_reporter and t.get("reporter") != allowed_reporter):
            return None, f"{tid} not found"  # 1.7.0: another reporter's ticket reads as missing (no id probing)
        st = t.get("status")
        if action == "verify" and st != "fixed":
            return None, f"{tid} is {st}, not fixed"
        if st == "closed" and action not in ("reopen", "note"):
            return None, f"{tid} is closed"
        if action == "reopen" and st not in ("closed", "fixed"):
            return None, f"{tid} is {st}, nothing to reopen"
        h = {"at": now, "actor": actor, "action": action, "from": st}
        if text:
            h["text"] = text
        before = dict(t)
        new = ACTIONS[action]
        if new:
            t["status"] = new
        h["to"] = t["status"]
        if action == "fixed":
            try:
                t["version_fixed"] = clean_line(payload.get("version"), 40)
            except NotUnicode as e:
                return None, str(e)
            h["version"] = t["version_fixed"]
        t["history"] = list(t.get("history") or []) + [h]
        t["updated_at"] = now
        data = _json_bytes(t)
        if limits and allowed_reporter:
            why = change_refusal(base, before, allowed_reporter, limits, now, len(data),
                                 free=action in ("verify", "reopen") and not text)
            if why:
                return None, why
            if not (action in ("verify", "reopen") and not text):
                _note_change(base, allowed_reporter, now, limits)  # first: a ledger that cannot be written stops it
        _write_json(os.path.join(base, tid, "ticket.json"), t, data)
    return t, ""


def _own(base, payload, allowed_reporter):
    """(tid, ticket, '') or (tid, None, error) for edit / delete. Call under _locked."""
    tid = str(payload.get("id") or "").strip().upper()
    if not ID_RE.match(tid):
        return tid, None, "bad id"
    t = load(base, tid)
    if not t or (allowed_reporter and t.get("reporter") != allowed_reporter):
        return tid, None, f"{tid} not found"  # 1.7.0: another reporter's ticket reads as missing (no id probing)
    return tid, t, ""


def edit(base, payload, actor, now, allowed_reporter=None, limits=None):
    """FW-0049: (ticket, '') or (None, error). payload {id, title?, narrative?, steps?, expected?, page?}: only the
    fields sent change (cleaned and cut to MAX_TEXT like create). Only while the ticket is new or reopened; title and
    narrative cannot be blanked; a message that changes nothing is refused. The history line keeps the replaced text.
    1.7.0 review: limits (a pilot's, with allowed_reporter) keep his caps (change_refusal), which bound that too."""
    if not isinstance(payload, dict):
        return None, "not an object"
    try:
        new = {k: clean_field(k, payload.get(k)) for k in EDIT_FIELDS if k in payload}
    except NotUnicode as e:
        return None, str(e)
    if not new:
        return None, "nothing to edit"
    for k in ("title", "narrative"):
        if k in new and not new[k]:
            return None, f"{k} is required"
    with _locked(base):
        tid, t, err = _own(base, payload, allowed_reporter)
        if not t:
            return None, err
        st = t.get("status")
        if st not in EDITABLE:
            return None, f"{tid} is {str(st).replace('_', ' ')}: edits only while new or reopened"
        changed = [k for k in EDIT_FIELDS if k in new and new[k] != (t.get(k) or "")]
        if not changed:
            return None, "nothing changed"
        h = {"at": now, "actor": actor, "action": "edit", "from": st, "to": st, "fields": changed,
             "before": {k: t.get(k) or "" for k in changed}}
        before = dict(t)
        for k in changed:
            t[k] = new[k]
        t["history"] = list(t.get("history") or []) + [h]
        t["updated_at"] = now
        data = _json_bytes(t)
        if limits and allowed_reporter:
            why = change_refusal(base, before, allowed_reporter, limits, now, len(data))
            if why:
                return None, why
            _note_change(base, allowed_reporter, now, limits)  # first: a ledger that cannot be written stops it
        _write_json(os.path.join(base, tid, "ticket.json"), t, data)
    return t, ""


def _stamp(now):
    """A folder-safe stamp from the time given: '2026-11-06T20:15:00.1+00:00' -> '20261106T201500'."""
    return re.sub(r"[^0-9A-Za-z]", "", str(now or "")[:19]) or "x"


def delete(base, payload, actor, now, allowed_reporter=None):
    """FW-0049: (ticket as deleted, '') or (None, error). payload {id}. Any status. The folder moves whole (photos and
    all) to <base>/.deleted/<id>-<stamp>, its ticket.json marked deleted_at / deleted_by with a history line, so it
    can be put back by hand; nothing is destroyed. 1.7.0 review: a pilot (allowed_reporter) deletes his ticket only
    while it is new (the council lets him verify, reopen and note; once someone works it, it stays on the list)."""
    if not isinstance(payload, dict):
        return None, "not an object"
    with _locked(base):
        tid, t, err = _own(base, payload, allowed_reporter)
        if not t:
            return None, err
        if allowed_reporter and t.get("status") != "new":
            st = str(t.get("status") or "").replace("_", " ")
            return None, f"{tid} is {st}: it is being worked, so it stays (add a note instead)"
        bin_ = os.path.join(base, DELETED)
        os.makedirs(bin_, exist_ok=True)
        dest, n = os.path.join(bin_, f"{tid}-{_stamp(now)}"), 1
        while os.path.exists(dest):
            n += 1
            dest = os.path.join(bin_, f"{tid}-{_stamp(now)}_{n}")
        t.setdefault("history", []).append({"at": now, "actor": actor, "action": "delete", "from": t.get("status"),
                                            "to": t.get("status")})
        t["deleted_at"], t["deleted_by"], t["updated_at"] = now, actor, now
        _write_json(os.path.join(base, tid, "ticket.json"), t)
        os.replace(os.path.join(base, tid), dest)
    return t, ""


def fixed_event(t):
    """FW-0007: {id, kind, title, reporter, version} for the ticket act() just returned when that action moved it to
    fixed from any other status, else None. Read from the history line act() wrote under the lock (its "from"), so
    a repeated "fixed" (a version correction, a retained or doubled message) never makes a second push; fixed again
    after a reopen does."""
    t = t if isinstance(t, dict) else {}
    h = t.get("history") or []
    last = h[-1] if isinstance(h, list) and h and isinstance(h[-1], dict) else {}
    if t.get("status") != "fixed" or last.get("action") != "fixed" or last.get("from") == "fixed":
        return None
    return {"id": t.get("id"), "kind": t.get("kind"), "title": _wf(t.get("title")), "reporter": t.get("reporter"),
            "version": t.get("version_fixed") or ""}


def summary(t):
    """One listing row. FW-0049: "editable" (new or reopened) and "page"; an editable ticket carries its whole
    narrative plus steps and expected, so the card's Edit form starts from the full text (others keep 500 chars)."""
    n = len(images(t))
    ed = t.get("status") in EDITABLE
    r = {"id": t["id"], "kind": t.get("kind"), "title": t.get("title"), "status": t.get("status"),
         "reporter": t.get("reporter"), "created_at": t.get("created_at"), "updated_at": t.get("updated_at"),
         "version_fixed": t.get("version_fixed") or "", "has_image": n > 0, "image_count": n,
         "narrative": (t.get("narrative") or "") if ed else (t.get("narrative") or "")[:500],
         "history_count": len(t.get("history") or []), "page": t.get("page") or "", "editable": ed}
    if ed:
        r["steps"], r["expected"] = t.get("steps") or "", t.get("expected") or ""
    return {k: _wf(v) for k, v in r.items()}  # 1.7.0 review: never a lone surrogate on a sensor or in a list file


def listing(base, reporter=None):
    """{open, total, tickets: [summary] newest first}; reporter limits it to that reporter's tickets."""
    rows = []
    for tid in _ids(base):
        t = load(base, tid)
        if t and (not reporter or t.get("reporter") == reporter):
            rows.append(summary(t))
    rows.sort(key=lambda r: int(r["id"][3:]), reverse=True)
    return {"open": sum(1 for r in rows if r["status"] in OPEN), "total": len(rows), "tickets": rows}


def _ts(v):
    """An ISO time as a UTC timestamp, or None."""
    try:
        t = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return (t if t.tzinfo else t.replace(tzinfo=timezone.utc)).timestamp()
    except (TypeError, ValueError):
        return None


RECENT_SLACK_S = 3600  # count_recent reads on this far past since (two instances' clocks and lock order)


def count_recent(base, reporter, since):
    """1.7.0: how many tickets reporter filed at or after since (a UTC timestamp), deleted ones too, so filing and
    deleting cannot get past the daily cap. 1.7.0 review: newest number first, live and deleted together, and it stops
    at the first ticket filed RECENT_SLACK_S before since (numbers are given out in time order under the lock), so a
    ticket/new reads the last day's tickets, not every ticket.json ever written."""
    ent = [(int(ID_RE.match(tid).group(1)), base, tid) for tid in _ids(base)]
    dbase = os.path.join(base, DELETED)
    try:
        ent += [(int(DELETED_RE.match(d).group(1)), dbase, d) for d in os.listdir(dbase) if DELETED_RE.match(d)]
    except OSError:
        pass
    n = 0
    for _, b, name in sorted(ent, key=lambda e: (e[0], e[2]), reverse=True):
        t = load(b, name)
        at = _ts(t.get("created_at")) if isinstance(t, dict) else None
        if at is None:
            continue
        if at < since - RECENT_SLACK_S:
            break
        if t.get("reporter") == reporter and at >= since:
            n += 1
    return n


def open_count(base, reporter):
    """1.7.0: how many of reporter's tickets are open (OPEN) now."""
    return sum(1 for tid in _ids(base) for t in [load(base, tid)]
               if t and t.get("reporter") == reporter and t.get("status") in OPEN)


def quota_refusal(base, reporter, limits, now):
    """1.7.0: why a pilot may not file another ticket now ('' when he may): limits["new_per_day"] in the last 24 h,
    or limits["open"] open at once. now is the ISO time of the new ticket."""
    t = _ts(now)
    t = datetime.now(timezone.utc).timestamp() if t is None else t
    if count_recent(base, reporter, t - 86400) >= int(limits["new_per_day"]):
        return f"ticket limit reached: {int(limits['new_per_day'])} new tickets in 24 h"
    if open_count(base, reporter) >= int(limits["open"]):
        return f"ticket limit reached: {int(limits['open'])} open tickets"
    return ""


def fixed_moves(base, reporter):
    """1.7.0: [{key "<id>|<at>", id, at, version, status}] for every history line that moved one of reporter's
    tickets into fixed (action fixed from another status), whatever its status is now (a fix then closed still
    counts), oldest first. A note, a version correction (fixed while fixed) or a deleted ticket adds none."""
    out = []
    for tid in _ids(base):
        t = load(base, tid)
        if not t or t.get("reporter") != reporter:
            continue
        for h in t.get("history") or []:
            if isinstance(h, dict) and h.get("action") == "fixed" and h.get("from") != "fixed" and h.get("at"):
                out.append({"key": f"{tid}|{h['at']}", "id": tid, "at": str(h["at"]),
                            "version": str(h.get("version") or "")[:40], "status": t.get("status")})
    out.sort(key=lambda m: (_ts(m["at"]) or 0, m["id"]))
    return out


def signature(base):
    """Cheap change marker for the folder: (id, mtime) of every ticket.json."""
    out = []
    for tid in _ids(base):
        try:
            out.append((tid, os.path.getmtime(os.path.join(base, tid, "ticket.json"))))
        except OSError:
            pass
    return tuple(out)
