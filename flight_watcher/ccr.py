"""CCR requests to Hark (1.4.6, Ryan, Nov 6). Small file I/O, no FLICA, no network.

When Ryan taps "Have Hark file this CCR" on a Recall / Over 75 row whose narrative he approved, the Watcher writes a
request file that the Home Office Manager (HOM) app turns into a task for Hark. Hark files the CCR on hal.alpa.org
only from that task; nothing here files anything. The folder is shared by both apps (both map /share):

  /share/flight_watcher/ccr_requests/
    <rid>.json         written ONLY by the Watcher (atomic tmp + rename):
                       {v: 1, rid, id ('date|pairing|kind'), pilot, date, pairing, kind, seat, narrative (as approved),
                        approved_at, requested_at}
    <rid>.task.json    written ONLY by HOM when it created the task: {v: 1, rid, task_id, imported_at}
    <rid>.done.json    written ONLY by HOM when the task is completed with a CCR number:
                       {v: 1, rid, ccr, filed_at, by, note (max 500 chars)}
    <rid>.status.json  written ONLY by HOM when the task is parked, set waiting or closed without a CCR number:
                       {v: 1, rid, status: blocked | cancelled, reason (max 500 chars), at}

rid = YYYY-MM-DD_<PAIRING>_<recall|o75>[_<pilot>]. Each side rejects any other name, never follows a symlink, reads at
most 64 KB, and treats the other side's content as untrusted data (checked, trimmed, never run).

1.4.6 review (Nov 7): the date in a rid is a real calendar date. HOM makes one task per rid, ever, so the Watcher never
sends a second request under a rid HOM already made a task of. The contract has no message from the Watcher to HOM
after the request: before HOM's import the Watcher can take its own <rid>.json back (remove_request); after it, Ryan
completes the HOM task as skipped himself."""
import json
import os
import re
import secrets
import stat
import unicodedata
from datetime import date, datetime, timezone

RID_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}_[A-Z0-9]{4,7}_(recall|o75)(_[a-z0-9]{1,20})?")
MAX_BYTES = 64 * 1024
REPLIES = ("task", "done", "status")
NOTE_MAX = 500


class Refused(Exception):
    """The request or reply breaks the file contract (the message says how)."""


def valid_rid(rid):
    return isinstance(rid, str) and RID_RE.fullmatch(rid) is not None


def rid_for(act_id, pilot=""):
    """'2026-11-10|H3601|recall' -> '2026-11-10_H3601_recall' (+ '_<pilot>' for a second pilot), or None when the
    act id does not make a valid rid. 1.4.6 review: the date must be a real calendar date (HOM ignores a name like
    2026-11-31 and would never answer, leaving the draft 'filing')."""
    parts = str(act_id or "").split("|")
    if len(parts) != 3:
        return None
    try:
        if date.fromisoformat(parts[0]).isoformat() != parts[0]:
            return None
    except ValueError:
        return None
    rid = f"{parts[0]}_{parts[1]}_{parts[2]}" + (f"_{pilot}" if pilot else "")
    return rid if valid_rid(rid) else None


def _folder_ok(folder, create=False):
    """The folder exists (made when create) and is a real directory, not a symlink."""
    try:
        st = os.lstat(folder)
    except FileNotFoundError:
        if not create:
            return False
        os.makedirs(folder, exist_ok=True)
        st = os.lstat(folder)
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        raise Refused(f"{folder} is not a plain folder")
    return True


def write_request(folder, rec):
    """Write <rid>.json atomically (a new temp file in the same folder, then rename over the name). Refuses a bad
    rid, a symlink at the name or as the folder, and anything over 64 KB. Returns the path."""
    rid = rec.get("rid")
    if not valid_rid(rid):
        raise Refused(f"bad rid {rid!r}")
    _folder_ok(folder, create=True)
    path = os.path.join(folder, f"{rid}.json")
    if os.path.islink(path):
        raise Refused(f"{rid}.json is a symlink")
    data = json.dumps(rec, ensure_ascii=False, indent=1, sort_keys=True).encode()
    if len(data) > MAX_BYTES:
        raise Refused(f"{rid}.json would be {len(data)} bytes, over 64 KB")
    tmp = os.path.join(folder, f".{rid}.{secrets.token_hex(6)}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o644)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return path


def remove_request(folder, rid):
    """Take back this side's own <rid>.json (1.4.6 review: Withdraw from Hark, or a dismiss / Mark filed while HOM has
    not made a task yet). HOM imports only a request it can still read, so a request removed before the import never
    becomes a task. Refuses a bad rid, a symlinked folder and anything at the name that is not a plain file. Returns
    True when a file was removed, False when there was none."""
    if not valid_rid(rid):
        raise Refused(f"bad rid {rid!r}")
    if not _folder_ok(folder):
        return False
    path = os.path.join(folder, f"{rid}.json")
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return False
    if not stat.S_ISREG(st.st_mode):
        raise Refused(f"{rid}.json is not a plain file")
    try:
        os.unlink(path)
    except FileNotFoundError:
        return False
    return True


def _read_json(path):
    """A small regular file's JSON object; None when absent. Refuses symlinks, non-files and files over 64 KB."""
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    except FileNotFoundError:
        return None
    except OSError as e:  # ELOOP: a symlink at the name
        raise Refused(f"{os.path.basename(path)} not readable as a plain file ({e.strerror})")
    with os.fdopen(fd, "rb") as f:
        st = os.fstat(f.fileno())
        if not stat.S_ISREG(st.st_mode):
            raise Refused(f"{os.path.basename(path)} is not a plain file")
        if st.st_size > MAX_BYTES:
            raise Refused(f"{os.path.basename(path)} is over 64 KB")
        raw = f.read(MAX_BYTES + 1)
        mtime = st.st_mtime
    if len(raw) > MAX_BYTES:
        raise Refused(f"{os.path.basename(path)} is over 64 KB")
    try:
        d = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise Refused(f"{os.path.basename(path)} is not JSON")
    if not isinstance(d, dict):
        raise Refused(f"{os.path.basename(path)} is not a JSON object")
    d["_mtime"] = datetime.fromtimestamp(mtime, timezone.utc).isoformat()
    return d


def clean(s, n, lines=False):
    """Text from the other side: a string or number, control and format characters out (newlines kept when
    lines), trimmed to n characters."""
    if isinstance(s, bool) or not isinstance(s, (str, int, float)):
        return ""
    out = []
    for ch in str(s):
        if ch == "\n" and lines:
            out.append(ch)
        elif unicodedata.category(ch) in ("Cc", "Cf", "Cs", "Co", "Zl", "Zp"):
            out.append(" " if ch in "\t\r\n  " else "")
        else:
            out.append(ch)
    return "".join(out).strip()[:n]


def iso(s):
    """An ISO time from the other side, normalized to UTC ISO; None when it is not one."""
    if not isinstance(s, str) or len(s) > 40:
        return None
    t = s.strip().replace("Z", "+00:00").replace("z", "+00:00")
    m = re.fullmatch(r"(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2})?)(?:\.(\d+))?([+-]\d{2}:?\d{2})?", t)
    if not m:
        return None
    frac = (m.group(2) or "")[:6].ljust(6, "0") if m.group(2) else ""
    tz = m.group(3) or ""
    if tz and ":" not in tz:
        tz = tz[:3] + ":" + tz[3:]
    try:
        d = datetime.fromisoformat(m.group(1) + (f".{frac}" if frac else "") + tz)
    except ValueError:
        return None
    return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).astimezone(timezone.utc).isoformat()


def read_reply(folder, rid, kind):
    """HOM's <rid>.<kind>.json (task, done, status), checked and trimmed; None when it is not there yet.
    Raises Refused when it breaks the contract (bad rid, symlink, not a plain file, over 64 KB, not JSON, v not 1,
    rid not the file's, missing or bad fields)."""
    if kind not in REPLIES:
        raise ValueError(kind)
    if not valid_rid(rid):
        raise Refused(f"bad rid {rid!r}")
    if not _folder_ok(folder):
        return None
    d = _read_json(os.path.join(folder, f"{rid}.{kind}.json"))
    if d is None:
        return None
    if d.get("v") != 1 or d.get("rid") != rid:
        raise Refused(f"{rid}.{kind}.json: v must be 1 and rid {rid}")
    out = {"rid": rid, "mtime": d["_mtime"]}
    if kind == "task":
        out["task_id"] = clean(d.get("task_id"), 80)
        out["imported_at"] = iso(d.get("imported_at"))
        if not out["task_id"]:
            raise Refused(f"{rid}.task.json: no task_id")
    elif kind == "done":
        out["ccr"] = clean(d.get("ccr"), 40)
        out["filed_at"] = iso(d.get("filed_at"))
        by = clean(d.get("by"), 30).lower()
        out["by"] = by if re.fullmatch(r"[a-z0-9 ._-]{1,30}", by or "") else "hark"
        out["note"] = clean(d.get("note"), NOTE_MAX, lines=True)
        if not out["ccr"]:
            raise Refused(f"{rid}.done.json: no CCR number")
    else:
        st = d.get("status")
        if st not in ("blocked", "cancelled"):
            raise Refused(f"{rid}.status.json: status must be blocked or cancelled")
        out["status"] = st
        out["reason"] = clean(d.get("reason"), NOTE_MAX, lines=True)
        out["at"] = iso(d.get("at"))
    return out


def fresh(reply, requested_at, field):
    """True when HOM's reply belongs to this request: written (file time) or stamped (its own time field) no earlier
    than the request, with a minute of slack. Keeps a reply to an earlier request from closing a new one."""
    if not reply:
        return False
    ts = [datetime.fromisoformat(t).timestamp() for t in (iso(reply.get(field)), iso(reply.get("mtime"))) if t]
    req = iso(requested_at)
    if not req:
        return True
    return bool(ts) and max(ts) >= datetime.fromisoformat(req).timestamp() - 60
