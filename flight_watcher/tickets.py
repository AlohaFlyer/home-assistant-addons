"""Tickets (0.10.1, Ryan): bug reports and feature requests from the dashboard, kept as files.

/share/flight_watcher/tickets/FW-0001/ticket.json, numbered FW-0001, FW-0002 ... across every Watcher instance
(a counter file under fcntl.flock). No network, no MQTT.

Photos (FW-0003): up to 10 per ticket, screenshot.jpg (photo 1), screenshot_2.jpg ... screenshot_10.jpg (.png
for a PNG), listed in index order in ticket.json "images"; "image" stays the first one for older readers. The
card sends the ticket first with a client-made "cid" and its photo count, then each photo as its own message
{cid, i, image} (add_image), so no single MQTT message carries more than one photo.
"""
import base64
import binascii
import fcntl
import json
import os
import re
from contextlib import contextmanager

KINDS = ("bug", "feature")
ID_RE = re.compile(r"^FW-(\d{4,})$")
MAX_IMAGE = 2 * 1024 * 1024
MAX_IMAGES = 10  # FW-0003: photos per ticket
CID_RE = re.compile(r"^[A-Za-z0-9_-]{6,40}$")
MAX_TEXT = {"title": 200, "narrative": 10000, "steps": 5000, "expected": 5000, "page": 300, "version": 40}
# action -> new status (None keeps the status); verify closes a fixed ticket
ACTIONS = {"triage": "triaged", "progress": "in_progress", "fixed": "fixed", "verify": "closed",
           "reopen": "reopened", "close": "closed", "note": None}
OPEN = ("new", "triaged", "in_progress", "fixed", "reopened")


@contextmanager
def _locked(base):
    os.makedirs(base, exist_ok=True)
    with open(os.path.join(base, ".lock"), "a+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def _write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=1)
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
    n = max([n] + [int(ID_RE.match(d).group(1)) for d in os.listdir(base) if ID_RE.match(d)]) + 1
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
    m = re.match(r"^screenshot(?:_(\d+))?\.(?:jpg|png)$", name or "")
    return int(m.group(1) or 1) if m else 0


def images(t):
    """The ticket's photo file names, photo 1 first; a ticket from before FW-0003 has only "image"."""
    v = t.get("images")
    if isinstance(v, list):
        return [x for x in v if isinstance(x, str) and x]
    return [t["image"]] if t.get("image") else []


def create(base, payload, reporter, now):
    """(ticket, '') or (None, error). payload {kind, title, narrative, steps?, expected?, page?, version?, image?,
    cid?, images?}. image is photo 1 sent inline (cards before FW-0003). cid (client-made) and images (how many
    photos the card will send on ticket/image, 0 to 10; 10 when left out) open the ticket for add_image."""
    if not isinstance(payload, dict):
        return None, "not an object"
    kind = str(payload.get("kind") or "").strip().lower()
    if kind not in KINDS:
        return None, "kind must be bug or feature"
    f = {k: str(payload.get(k) or "").strip()[:n] for k, n in MAX_TEXT.items()}
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
    if cid:
        want = max(want, min(MAX_IMAGES, _int(payload.get("images"), MAX_IMAGES)))
    with _locked(base):
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
    with _locked(base):
        t = None
        for tid in sorted(_ids(base), key=lambda x: int(x[3:]), reverse=True):  # newest first: just filed
            x = load(base, tid)
            if x and x.get("cid") == cid and x.get("reporter") == reporter:
                t = x
                break
        if not t:
            return None, "no ticket for that photo"
        names = images(t)
        want = _int(t.get("images_expected") or 0, 0)
        if i > want:
            return None, f"{t['id']} takes {want} photos, not photo {i}"
        if any(_photo_no(n) == i for n in names):
            return None, f"{t['id']} already has photo {i}"
        if len(names) >= MAX_IMAGES:
            return None, f"{t['id']} already has {MAX_IMAGES} photos"
        name = image_name(i, ext)
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
        return json.load(open(os.path.join(base, tid, "ticket.json")))
    except (OSError, ValueError):
        return None


def act(base, payload, actor, now, allowed_reporter=None):
    """(ticket, '') or (None, error). payload {id, action, text?, version?}. allowed_reporter limits a pilot
    instance to its own tickets. verify needs a fixed ticket; only reopen and note touch a closed one."""
    if not isinstance(payload, dict):
        return None, "not an object"
    tid, action = str(payload.get("id") or "").strip().upper(), str(payload.get("action") or "").strip().lower()
    if not ID_RE.match(tid):
        return None, "bad id"
    if action not in ACTIONS:
        return None, f"unknown action {action}"
    with _locked(base):
        t = load(base, tid)
        if not t:
            return None, f"{tid} not found"
        if allowed_reporter and t.get("reporter") != allowed_reporter:
            return None, f"{tid} is not {allowed_reporter}'s ticket"
        st = t.get("status")
        if action == "verify" and st != "fixed":
            return None, f"{tid} is {st}, not fixed"
        if st == "closed" and action not in ("reopen", "note"):
            return None, f"{tid} is closed"
        if action == "reopen" and st not in ("closed", "fixed"):
            return None, f"{tid} is {st}, nothing to reopen"
        h = {"at": now, "actor": actor, "action": action, "from": st}
        text = str(payload.get("text") or "").strip()[:5000]
        if text:
            h["text"] = text
        new = ACTIONS[action]
        if new:
            t["status"] = new
        h["to"] = t["status"]
        if action == "fixed":
            t["version_fixed"] = str(payload.get("version") or "").strip()[:40]
            h["version"] = t["version_fixed"]
        t.setdefault("history", []).append(h)
        t["updated_at"] = now
        _write_json(os.path.join(base, tid, "ticket.json"), t)
    return t, ""


def summary(t):
    n = len(images(t))
    return {"id": t["id"], "kind": t.get("kind"), "title": t.get("title"), "status": t.get("status"),
            "reporter": t.get("reporter"), "created_at": t.get("created_at"), "updated_at": t.get("updated_at"),
            "version_fixed": t.get("version_fixed") or "", "has_image": n > 0, "image_count": n,
            "narrative": (t.get("narrative") or "")[:500], "history_count": len(t.get("history") or [])}


def listing(base, reporter=None):
    """{open, total, tickets: [summary] newest first}; reporter limits it to that reporter's tickets."""
    rows = []
    for tid in _ids(base):
        t = load(base, tid)
        if t and (not reporter or t.get("reporter") == reporter):
            rows.append(summary(t))
    rows.sort(key=lambda r: int(r["id"][3:]), reverse=True)
    return {"open": sum(1 for r in rows if r["status"] in OPEN), "total": len(rows), "tickets": rows}


def signature(base):
    """Cheap change marker for the folder: (id, mtime) of every ticket.json."""
    out = []
    for tid in _ids(base):
        try:
            out.append((tid, os.path.getmtime(os.path.join(base, tid, "ticket.json"))))
        except OSError:
            pass
    return tuple(out)
