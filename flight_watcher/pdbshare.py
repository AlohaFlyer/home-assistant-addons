"""Sharing the pilot database with a portal pilot (1.7.9, contract 1 revision 4): the files between the two Watchers.

Ryan's Watcher (the admin, the one writer of /data/pilotdb.sqlite) and a shared pilot's Watcher never talk over MQTT
about the database. They pass plain files under /share/flight_watcher/pilotdb (folder 0700, files 0600, root):

  portal/<pilot>.json    the admin writes it while that pilot's share is on (pilotdb.export_for: a whitelist) and
                         deletes it when Ryan turns his share off. 1.7.10 (Ryan's decision 1 of Nov 15, "shared with
                         James 100%"): every live record with every field, the notes, the whole log, the pickup
                         history and the AI note. The pilot's Watcher signs it into his portal's out/files/pilotdb.json
                         unchanged, and reads it itself for the record of the pilot his pilot card shows and for the
                         name lookup's pick list.
  inbox/<pilot>/         the pilot's Watcher drops each checked command here (one file, O_EXCL, 0600); the admin's
                         drain applies it with the author taken from the folder's name and deletes the file.
  ai/stats.json, ai/in/  the AI note hand-off with HOM's consultant models (roles.PILOTDB_AI; anonymous statistics out,
                         notes in). Only while Ryan's AI switch is on.

1.7.10 (contract 1 revision 5; Ryan, Nov 16): a portal pilot's contacts list (the CSV export, upload/pdf kind
contacts) travels through the same inbox folder: his Watcher checks the whole file (contacts_check) and drops it as one
inbox file (contacts_put: cmd contacts, its size, sha256 and base64, 0600); the admin's drain checks it again with the
same function and merges it with the author taken from the folder's name (pilotdb.pilot_contacts: adds and updates
only). Nothing of the file is kept after the merge, and no line logged holds a cell of it.

1.7.10: roster.json (1.7.9: every pilot's brief for the one pilot a shared pilot looked up, in the add-on's own
/data/pilotdb_roster) is gone: the file holds every record now. A roster an older version left is removed
(write_files, clear_files).

Nothing here loads FLICA, publishes on MQTT or logs a name, a number or a text. Pure file code, so both sides and the
tests use the same functions.
"""
import base64
import binascii
import contextlib
import csv
import hashlib
import io
import json
import os
import re
import secrets
import sqlite3
import stat
import time
from datetime import datetime, timezone

import contacts as CT
import pilotdb as PDBM
import portal as PT
import roles as ROLES

ROOT = "/share/flight_watcher/pilotdb"
ROSTER = "roster.json"
NAME_RE = PT.INBOX_NAME_RE
INBOX_MAX_BYTES = PT.INBOX_MAX_BYTES
DRAIN_PER_PASS = 50
O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_DIR = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | O_NOFOLLOW
NOTE_KEYS = ("op", "pid", "entry", "base", "text", "rid")
EDIT_KEYS = ("op", "pid", "field", "value", "rev", "why", "rid")
NOT_SHARED = "Not saved: Ryan has not shared the pilot database with you"
NOT_IN_DB = "Not saved: that pilot is not in Ryan's pilot database"
OWN_ONLY = "Not saved: only your own notes can be taken back"
UNREADABLE = "Not saved: it could not be read, send it again"
TOO_OLD = "Not saved: too old, send it again"
BUSY = "Busy: try again in a minute"
# 1.7.10 (revision 5): a pilot's contacts list. Fixed phrases (roles.PILOTDB_ANSWERS), never a cell of the file
CONTACTS_KEYS = ("rid", "size", "sha", "data")
CONTACTS_BAD = "Not merged: that file is not the contacts list (CSV) export"
CONTACTS_EMPTY = "Not merged: no pilot was read from that contacts list"
CONTACTS_BIG = "Not merged: a contacts list is at most {n} KB"
CONTACTS_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")  # no control character but tab, LF and CR


class ContactsRefused(ValueError):
    """A contacts list refused; str() is one of the fixed phrases above."""


def contacts_check(raw, limits=None, today=None):
    """The checks both Watchers run on a pilot's whole contacts list, in order (portal.CONTACTS_CHECKS): at most
    file_bytes; text only (strict UTF-8, a BOM allowed, no control character but tab, CR and LF: so no PDF, no XLSX,
    no binary); its first row is the export's header, cell for cell (case and outer spaces aside); read by the 1.4.8
    parser (contacts.parse, the one Ryan's own upload goes through) it gives at least rows_min pilots. Returns the
    parsed list (contacts.parse's answer); ContactsRefused with a fixed phrase otherwise. Never logs."""
    lim = limits or ROLES.PILOT_CONTACTS_LIMITS
    if not isinstance(raw, (bytes, bytearray)) or not raw:
        raise ContactsRefused(CONTACTS_BAD)
    if len(raw) > lim["file_bytes"]:
        raise ContactsRefused(CONTACTS_BIG.format(n=lim["file_bytes"] // 1024))
    try:
        text = bytes(raw).decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ContactsRefused(CONTACTS_BAD) from None
    kind = CT.sniff(bytes(raw))  # read from the bytes, as Ryan's own upload is: 'csv', or None for a lone header row
    if CONTACTS_CTRL.search(text) or kind not in ("csv", None):
        raise ContactsRefused(CONTACTS_BAD)
    first = next((ln for ln in text.splitlines() if ln.strip()), "")
    try:
        head = next(csv.reader(io.StringIO(first)), [])
    except csv.Error:
        head = []
    if [c.strip().lower() for c in head] != [h.lower() for h in lim["header"]]:
        raise ContactsRefused(CONTACTS_BAD)
    if kind is None:
        raise ContactsRefused(CONTACTS_EMPTY)
    try:
        parsed = CT.parse(bytes(raw), "csv", today=today)
    except Exception:  # noqa: BLE001 (whatever a crafted sheet does to the parser: refused, never raised on)
        raise ContactsRefused(CONTACTS_BAD) from None
    if len(parsed["entries"]) + len(parsed.get("hal_only") or []) < lim["rows_min"]:
        raise ContactsRefused(CONTACTS_EMPTY)
    return parsed


def export_path(pilot, root=ROOT):
    return os.path.join(root, "portal", f"{pilot}.json")


def roster_path(root=ROOT):
    return os.path.join(root, ROSTER)


def inbox_dir(pilot, root=ROOT):
    return os.path.join(root, "inbox", pilot)


def _real_dir(path):
    """True when path is a real folder (never a symlink)."""
    try:
        st = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISDIR(st.st_mode) and not stat.S_ISLNK(st.st_mode)


def ensure_dirs(root, pilots=()):
    """The share folders, 0700 (pilotdb._dir_0700: refused when one is a symlink). True when all are there."""
    ok = True
    for d in [root, os.path.join(root, "portal"), os.path.join(root, "inbox")] + [inbox_dir(p, root) for p in pilots]:
        ok = bool(PDBM._dir_0700(d)) and ok
    return ok


def _unlink(path):
    with contextlib.suppress(FileNotFoundError):
        os.unlink(path)


# ---------------------------------------------------------------- the admin's side: the files it writes
def clear_files(root=ROOT, roster_dir=None):
    """No share can be on (the database did not open at start, 1.7.9 review): every pilot's file goes (and a roster an
    older version left), so nothing a share once wrote stays readable. Returns how many files were removed. Never
    raises."""
    paths = [roster_path(root)] + ([roster_path(roster_dir)] if roster_dir else [])
    with contextlib.suppress(OSError):
        paths += [os.path.join(root, "portal", n) for n in os.listdir(os.path.join(root, "portal")) if n.endswith(".json")]
    n = 0
    for path in paths:
        with contextlib.suppress(OSError):
            os.unlink(path)
            n += 1
    return n


def write_files(db, pilots, root=ROOT, limits=None, roster_dir=None):
    """Each shared pilot's file from the database, and none for a pilot whose share Ryan turned off (his file is
    deleted, his waiting commands are refused). pilots: the configured portal pilots; sharing is on for each unless
    Ryan switched it off (pilotdb.Switches). Returns {pilot: 'on' | 'off' | 'full'}: 'full' when his file is over
    export_bytes (his new notes are refused). 1.7.10: no roster is written; one an older version left (under root or
    roster_dir, the Watcher's /data/pilotdb_roster) is removed."""
    shared = db.shared_with(pilots)
    out = {}
    ensure_dirs(root, shared)
    for p in pilots:
        path = export_path(p, root)
        if p in shared:
            doc = db.export_for(p, limits)
            PT.write_private(path, json.dumps(doc, ensure_ascii=False, separators=(",", ":")))
            out[p] = "full" if doc.get("full") else "on"
        else:
            _unlink(path)
            out[p] = "off"
    try:
        stray = [n for n in os.listdir(os.path.join(root, "portal")) if n.endswith(".json") and n[:-5] not in pilots]
    except OSError:
        stray = []
    for n in stray:  # a pilot no longer configured: his file goes
        _unlink(os.path.join(root, "portal", n))
    _unlink(roster_path(root))
    if roster_dir:
        _unlink(roster_path(roster_dir))
        with contextlib.suppress(OSError):
            os.rmdir(roster_dir)
    return out


# ---------------------------------------------------------------- the admin's side: the inbox drain (spec 11.4)
def inbox_names(folder):
    """The command file names in one pilot's inbox, oldest first; never a dotfile, a folder or a strange name (those
    are removed when plain files, so a planted name cannot fill the folder)."""
    if not _real_dir(folder):
        return []
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return []
    good = []
    for n in names:
        if NAME_RE.fullmatch(n):
            good.append(n)
        elif n.startswith("."):
            with contextlib.suppress(OSError):  # a temp file the writer abandoned (a live one lasts milliseconds)
                if time.time() - os.lstat(os.path.join(folder, n)).st_mtime > 300:
                    os.unlink(os.path.join(folder, n))
        else:
            with contextlib.suppress(OSError):
                os.unlink(os.path.join(folder, n))
    return good


def waiting(folder, rid):
    """True when a command with this rid still waits in the inbox folder."""
    return any(n[14:-5] == rid for n in inbox_names(folder))


def pending(folder):
    """How many commands wait in one pilot's inbox."""
    return len(inbox_names(folder))


def _read_cmd(folder, name):
    """The parsed body of one inbox file, or None: read without following a symlink, at most INBOX_MAX_BYTES (1.7.10:
    a contacts list's file at most roles.PILOT_CONTACTS_LIMITS inbox_bytes; a note or an edit never gets that room)."""
    try:
        raw, _ = PT.read_plain(os.path.join(folder, name), ROLES.PILOT_CONTACTS_LIMITS["inbox_bytes"])
        d = json.loads(raw.decode("utf-8"))
    except (PT.PortalError, ValueError, RecursionError):
        return None
    if not isinstance(d, dict) or (len(raw) > INBOX_MAX_BYTES and d.get("cmd") != "contacts"):
        return None
    return d


def contacts_of(d, limits=None):
    """The bytes of the contacts list one inbox body carries: exactly the keys of a contacts body, a strict base64 of
    size bytes whose sha256 is sha. PortalError when anything is off (answered 'it could not be read')."""
    lim = limits or ROLES.PILOT_CONTACTS_LIMITS
    if set(d) != {"v", "by", "at", "cmd"} | set(CONTACTS_KEYS):
        raise PT.PortalError("contacts: keys")
    size, sha, data = d.get("size"), d.get("sha"), d.get("data")
    if (not isinstance(size, int) or isinstance(size, bool) or not 0 < size <= lim["file_bytes"]
            or not isinstance(sha, str) or not re.fullmatch(ROLES.SHA256_PATTERN, sha) or not isinstance(data, str)):
        raise PT.PortalError("contacts: fields")
    try:
        raw = base64.b64decode(data.encode("ascii"), validate=True)
    except (binascii.Error, ValueError):
        raise PT.PortalError("contacts: not base64") from None
    if len(raw) != size or hashlib.sha256(raw).hexdigest() != sha:
        raise PT.PortalError("contacts: not the file it names")
    return raw


def _contacts_apply(db, pilot, rid, d, now):
    """One contacts list from a pilot's inbox, checked again and merged with the author `pilot` (the folder). Returns
    (ok, why, stats or None, by_db): by_db False when the refusal was made here and still needs its answer."""
    try:
        raw = contacts_of(d)
    except Exception:  # noqa: BLE001
        return False, UNREADABLE, None, False
    try:
        parsed = contacts_check(raw, today=db.today())
    except ContactsRefused as e:
        return False, str(e), None, False
    at = datetime.fromtimestamp(now, PDBM.HST).replace(microsecond=0).isoformat()
    cj = CT.build(parsed, "", at)
    ok, why, stats = db.pilot_contacts(pilot, rid, cj, d["sha"], CT.PARSER)
    return ok, why, stats, True


def check_cmd(cmd, d):
    """The inner fields of a note or an edit, checked by the contract's shape again (portal.check_shape) and by the
    op rules the generic checker cannot say. Returns the fields; PortalError when refused."""
    sub = {"note": "pilotdb/note", "edit": "pilotdb/edit"}.get(cmd) if isinstance(cmd, str) else None
    if sub is None:
        raise PT.PortalError("not a pilotdb command")
    keys = NOTE_KEYS if cmd == "note" else EDIT_KEYS
    inner = {k: d[k] for k in keys if k in d}
    PT.check_shape(sub, json.dumps(inner))
    op = inner["op"]
    if cmd == "note":
        if ("entry" in inner) != (op == "retract") or ("base" in inner) != (op == "field"):
            raise PT.PortalError("pilotdb/note: a key that does not go with the op")
        if op == "retract" and "text" in inner:
            raise PT.PortalError("pilotdb/note: a key that does not go with the op")
        if op == "add" and len(inner.get("text") or "") > ROLES.PILOTDB_NOTE_LIMITS["entry_max"]:
            raise PT.PortalError("pilotdb/note: a note is too long")
    elif ("value" in inner) != (op == "set"):
        raise PT.PortalError("pilotdb/edit: a key that does not go with the op")
    return inner


def drain(db, pilots, root=ROOT, limits=None, full=(), now=None, log=None, per_pass=DRAIN_PER_PASS):
    """One pass over every configured pilot's inbox (oldest name first, at most per_pass files a pilot): each command is
    applied by the database with the author taken from the folder's name (pilotdb.pilot_op), answered and its file
    deleted. A body whose `by` differs from the folder, a file that cannot be read or an old one is refused (answered
    when its name carries a rid); a pilot whose share is off gets 'Ryan has not shared ...'. full: the pilots whose
    file is full. Returns {applied, refused, scrub}. log(msg): op and author names only, never a text or a number."""
    lim = limits or ROLES.PILOTDB_NOTE_LIMITS
    now = time.time() if now is None else now
    say = log or (lambda m: None)
    out = {"applied": 0, "refused": 0, "scrub": False}
    for pilot in pilots:
        folder = inbox_dir(pilot, root)
        for name in inbox_names(folder)[:per_pass]:
            ms, rid = int(name[:13]), name[14:-5]
            d = _read_cmd(folder, name)
            shared = db.is_shared(pilot)
            ok, why, after, by_db = False, UNREADABLE, None, False
            cmd = d.get("cmd") if d else None
            if d is None or d.get("v") != 1 or d.get("rid") != rid:
                say(f"pilot db: a command from {pilot} could not be read: refused")
            elif d.get("by") != pilot:
                say(f"pilot db: a command in {pilot}'s inbox names another author: refused")
            elif not shared:
                why = NOT_SHARED
            elif now - ms / 1000.0 > lim["stale_h"] * 3600:
                why = TOO_OLD
            else:
                # 1.7.9 review: whatever a planted file holds (a cmd that is a list, a value no check foresaw), it is
                # refused as unreadable and removed; it never raises out of the drain and so never blocks the pass
                if cmd == "contacts":  # 1.7.10 (revision 5): a pilot's contacts list, adds and updates only
                    try:
                        ok, why, st, by_db = _contacts_apply(db, pilot, rid, d, now)
                    except sqlite3.Error:
                        raise  # nothing was merged: the file waits for the next pass
                    except Exception:  # noqa: BLE001
                        ok, why, st, by_db = False, UNREADABLE, None, False
                    if not by_db and db.answer_of(pilot, rid) is None:
                        db.put_answer(pilot, rid, False, why, lim["answers"])
                    _unlink(os.path.join(folder, name))
                    out["applied" if ok else "refused"] += 1
                    if st is not None:
                        say(f"pilot db: contacts list from {pilot}: merged ({st.get('rows', 0)} rows, "
                            f"{st.get('added', 0)} added, {st.get('changed', 0) - st.get('added', 0)} changed, "
                            f"{st.get('kept_hand', 0)} kept hand edits, {st.get('conflicts', 0)} held for Ryan)")
                    else:
                        say(f"pilot db: contacts list from {pilot}: {'merged before' if ok else 'refused'}")
                    continue
                try:
                    inner = check_cmd(cmd, d)
                except Exception:  # noqa: BLE001
                    inner = None
                if inner is not None:
                    try:
                        ok, why, after = db.pilot_op(pilot, cmd, inner, lim, full=pilot in full)
                        by_db = True
                    except sqlite3.Error:
                        raise  # the database itself (locked, full disk): nothing was saved, the file waits for the next pass
                    except Exception:  # noqa: BLE001
                        ok, why, after = False, UNREADABLE, None
            if not by_db and db.answer_of(pilot, rid) is None:
                # a refusal made here (not by the database): answered once; the same rid again keeps the first answer
                db.put_answer(pilot, rid, False, why, lim["answers"])
            _unlink(os.path.join(folder, name))
            out["applied" if ok else "refused"] += 1
            out["scrub"] = out["scrub"] or after == "scrub"
            if d is not None and d.get("by") == pilot:
                op = d.get("op")
                say(f"pilot db: {cmd if isinstance(cmd, str) and cmd in ('note', 'edit') else 'command'} "
                    f"{op if isinstance(op, str) and op in ROLES.PILOTDB_NOTE_OPS + ROLES.PILOTDB_EDIT_OPS else '?'} "
                    f"from {pilot}: {'saved' if ok else 'refused'}")
    return out


# ---------------------------------------------------------------- the pilot's side
def inbox_put(pilot, cmd, inner, root=ROOT, now=None):
    """One checked command into the admin's inbox: a dotfile opened O_CREAT | O_EXCL | O_NOFOLLOW, 0600, in the
    folder's own fd, then renamed to <13-digit ms>-<rid>.json. The author is the instance (pilot), never a payload key.
    Returns the file name. OSError when the folder is not there (not shared) or is not a real folder."""
    now = time.time() if now is None else now
    body = {"v": 1, "by": pilot, "at": datetime.fromtimestamp(now, timezone.utc).replace(microsecond=0).isoformat(),
            "cmd": cmd}
    body.update({k: inner[k] for k in (NOTE_KEYS if cmd == "note" else EDIT_KEYS) if k in inner})
    return _inbox_write(pilot, body, inner["rid"], root, now)


def contacts_put(pilot, rid, raw, root=ROOT, now=None):
    """1.7.10 (revision 5): a pilot's checked contacts list into the admin's inbox, as inbox_put writes a command
    (O_EXCL, O_NOFOLLOW, 0600, in the folder's own fd): {v, by, at, cmd: contacts, rid, size, sha, data (base64)}.
    The author is the instance, never anything of the file. Returns the file name; OSError when the folder is not
    there (not shared)."""
    now = time.time() if now is None else now
    if not isinstance(rid, str) or not re.fullmatch(ROLES.UPLOAD_ID_PATTERN, rid):
        raise OSError("contacts: rid")
    body = {"v": 1, "by": pilot, "at": datetime.fromtimestamp(now, timezone.utc).replace(microsecond=0).isoformat(),
            "cmd": "contacts", "rid": rid, "size": len(raw), "sha": hashlib.sha256(raw).hexdigest(),
            "data": base64.b64encode(raw).decode("ascii")}
    return _inbox_write(pilot, body, rid, root, now)


def contacts_waiting(folder):
    """How many contacts lists wait in one pilot's inbox (their bodies are read: the name does not say the cmd)."""
    return sum(1 for n in inbox_names(folder) if ((_read_cmd(folder, n) or {}).get("cmd") == "contacts"))


def _inbox_write(pilot, body, rid, root, now):
    name = f"{int(now * 1000):013d}-{rid}.json"
    dfd = os.open(inbox_dir(pilot, root), _DIR)
    try:
        tmp = f".{name}.{secrets.token_hex(4)}.tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | O_NOFOLLOW, 0o600, dir_fd=dfd)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(body, f, ensure_ascii=False)
                f.flush()
                os.fchmod(f.fileno(), 0o600)
            os.replace(tmp, name, src_dir_fd=dfd, dst_dir_fd=dfd)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp, dir_fd=dfd)
            raise
    finally:
        os.close(dfd)
    return name


class View:
    """A shared pilot's read side: his own file as his Watcher last read it. refresh() re-reads it when its time,
    size or inode moved (lstat; read without following a symlink, capped at what a signed file may be) and says
    whether anything changed. 1.7.10: the file holds every record, so the record of the pilot his pilot card shows
    (by_emp) and the name lookup's rows (names) come from it; there is no roster."""

    def __init__(self, pilot, root=ROOT, roster_dir=None):
        self.pilot, self.root = pilot, root
        self.sig = {"export": None}
        self.state = "off"       # on: his file is there and reads; off: no file; waiting: a file that does not read yet
        self.text = ""           # his file's text exactly (what the portal serves)
        self.rev = ""            # the first 12 hex of sha256(text)
        self.count = 0
        self.updated = ""
        self.pids = set()        # the records of his file
        self.mine = {}           # eid -> pid of his own entries in his file
        self.answers = []        # the file's answers
        self.limits = {}
        self.by_emp = {}         # emp -> [(pid, last name's key)]
        self.names = []          # [(emp, last, first, seat)] of the live pilots whose number no other record shares
        self.sens = {}           # 1.7.10 review: {emp: Sen #} of those pilots (the pick list tells namesakes apart)

    @staticmethod
    def _sig(path):
        try:
            st = os.lstat(path)
        except OSError:
            return None
        return (st.st_mtime_ns, st.st_size, st.st_ino) if stat.S_ISREG(st.st_mode) else ("x",)

    def refresh(self):
        ep = export_path(self.pilot, self.root)
        s = self._sig(ep)
        if s == self.sig["export"]:
            return False
        self.sig["export"] = s
        self._read_export(ep, s)
        return True

    def _read_export(self, path, sig):
        self.text, self.rev, self.count, self.updated = "", "", 0, ""
        self.pids, self.mine, self.answers, self.limits, self.by_emp, self.names = set(), {}, [], {}, {}, []
        self.sens = {}
        if sig is None:
            self.state = "off"
            return
        self.state = "waiting"
        try:
            raw, _ = PT.read_plain(path, PT.CAPS["file"])
            text = raw.decode("utf-8")
            d = json.loads(text)
        except (PT.PortalError, ValueError, RecursionError):
            return
        if not isinstance(d, dict) or d.get("v") != 1 or not isinstance(d.get("records"), list):
            return
        self.state, self.text = "on", text
        self.rev = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
        self.updated = str(d.get("generated") or "")[:40]
        recs = [r for r in d["records"] if isinstance(r, dict) and isinstance(r.get("pid"), str)
                and re.fullmatch(ROLES.PILOTDB_PID_PATTERN, r["pid"])]
        self.count = len(recs)
        self.pids = {r["pid"] for r in recs}
        for r in recs:
            for e in r.get("entries") or []:
                if isinstance(e, dict) and e.get("mine") is True and isinstance(e.get("eid"), str):
                    self.mine[e["eid"]] = r["pid"]
            emp = PDBM.emp_of(r.get("emp"))
            if emp:
                name = str(r.get("name") or "")
                self.by_emp.setdefault(emp, []).append((r["pid"], PDBM.name_key(name)[0] if name else "", r))
        for emp, rows in self.by_emp.items():
            r = rows[0][2]
            if len(rows) == 1 and not r.get("gone"):
                last, _, first = (x.strip() for x in str(r.get("name") or "").partition(","))
                if last:
                    self.names.append((emp, last[:80], first[:80], str(r.get("seat") or "")[:3]))
                    if re.fullmatch(r"\d{1,5}", str(r.get("sen") or "")):
                        self.sens[emp] = str(r["sen"])
        self.by_emp = {e: [(p, lk) for p, lk, _ in rows] for e, rows in self.by_emp.items()}
        self.answers = [{"rid": a["rid"], "ok": bool(a.get("ok")), "why": str(a.get("why") or "")[:200],
                         "at": str(a.get("at") or "")[:40]}
                        for a in d.get("answers") or [] if isinstance(a, dict) and isinstance(a.get("rid"), str)]
        self.limits = {k: v for k, v in (d.get("limits") or {}).items()
                       if isinstance(v, int) and not isinstance(v, bool)} if isinstance(d.get("limits"), dict) else {}

    def shown(self, emp, name=""):
        """Which record of his file the pilot his pilot card shows is: {emp, pid}, {emp, none: true} when he is not
        in the database (or two records share the number and the name does not tell them apart), or None with no
        pilot shown or while not shared. 1.7.10: the record itself (every field, the notes, the log, the pickups, the
        AI note) is in his file, so nothing of it is repeated here."""
        emp = PDBM.emp_of(emp)
        if self.state != "on" or not emp:
            return None
        rows = self.by_emp.get(emp) or []
        pid = rows[0][0] if len(rows) == 1 else None
        if pid is None and rows:
            lk = PDBM.name_key(name)[0] if name else ""
            hit = [p for p, k in rows if lk and k == lk]
            pid = hit[0] if len(hit) == 1 else None
        return {"emp": emp, "pid": pid} if pid else {"emp": emp, "none": True}


def pilot_check(view, shown_pid, cmd, payload, n_pending, limits=None):
    """A shared pilot's Watcher's checks of one pilotdb/note or pilotdb/edit payload (spec 11.3): the shape, shared or
    not, the pid (a record of his file, which holds every live record since 1.7.10), the op rules and the pending
    limit. Returns (inner, '') to queue it or (inner or None, why) to refuse it: why is a fixed phrase. shown_pid is
    kept for callers of 1.7.9 and is not read."""
    lim = limits or ROLES.PILOTDB_NOTE_LIMITS
    try:
        d = PT.check_shape("pilotdb/" + cmd, payload)
    except PT.PortalError:
        try:  # a refusal still reaches his card when the payload names a usable rid (nothing else of it is kept)
            rid = json.loads(payload).get("rid")
        except (ValueError, AttributeError, TypeError, RecursionError):
            rid = None
        ok = isinstance(rid, str) and re.fullmatch(ROLES.TICKET_CID_PATTERN, rid)
        return ({"rid": rid} if ok else None), UNREADABLE
    if view.state != "on":
        return d, NOT_SHARED
    try:
        inner = check_cmd(cmd, d)
    except PT.PortalError as e:
        return d, (f"Not saved: a note is at most {lim['entry_max']} characters" if "too long" in str(e) else UNREADABLE)
    if inner["pid"] not in view.pids:
        return inner, NOT_IN_DB
    if cmd == "note" and inner["op"] == "retract" and view.mine.get(inner["entry"]) != inner["pid"]:
        return inner, OWN_ONLY
    if n_pending >= lim["pending"]:
        return inner, BUSY
    return inner, ""


# ---------------------------------------------------------------- the AI note hand-off (roles.PILOTDB_AI)
def ai_paths(root=ROOT):
    cfg = ROLES.PILOTDB_AI
    d = os.path.join(root, "ai")
    return d, os.path.join(d, cfg["stats_file"]), os.path.join(d, cfg["in_dir"])


def ai_write_stats(db, root=ROOT):
    """stats.json for HOM's consultant models when the pickup statistics moved since the last batch (or no file is
    there). Returns the count written, or None when nothing was written. Only called while Ryan's AI switch is on."""
    d, path, in_dir = ai_paths(root)
    if not (PDBM._dir_0700(root) and PDBM._dir_0700(d) and PDBM._dir_0700(in_dir)):
        return None
    if db.ai_stats_sig() == db.ai_sig() and os.path.exists(path):
        return None  # the same statistics: the file's batch stays the one to answer
    doc, _sig = db.ai_stats()
    PT.write_private(path, json.dumps(doc, ensure_ascii=False, separators=(",", ":")))
    return doc["count"]


def ai_off(root=ROOT):
    """The switch went off: the statistics file and any answer waiting are removed."""
    _d, path, in_dir = ai_paths(root)
    _unlink(path)
    with contextlib.suppress(OSError):
        for n in os.listdir(in_dir):
            with contextlib.suppress(OSError):
                os.unlink(os.path.join(in_dir, n))


def ai_drain(db, root=ROOT, now=None):
    """HOM's answers in ai/in: each <batch>.json (plain file, capped, never through a symlink) is handed to
    pilotdb.ai_take and deleted; anything else in the folder is removed. Returns {files, saved, refused}."""
    cfg = ROLES.PILOTDB_AI
    _d, _path, in_dir = ai_paths(root)
    out = {"files": 0, "saved": 0, "refused": 0}
    if not _real_dir(in_dir):
        return out
    now = time.time() if now is None else now
    try:
        names = sorted(os.listdir(in_dir))
    except OSError:
        return out
    for n in names[:20]:
        path = os.path.join(in_dir, n)
        if n.startswith("."):
            with contextlib.suppress(OSError):
                if now - os.lstat(path).st_mtime > 300:
                    os.unlink(path)
            continue
        if re.fullmatch(cfg["in_file_re"], n):
            try:
                raw, st = PT.read_plain(path, cfg["in_bytes"])
                doc = json.loads(raw.decode("utf-8")) if now - st.st_mtime <= cfg["stale_h"] * 3600 else None
            except (PT.PortalError, ValueError, RecursionError):
                doc = None
            if isinstance(doc, dict) and doc.get("batch") != n[:-5]:
                doc = None
            r = db.ai_take(doc)
            out["files"] += 1
            out["saved"] += r["saved"]
            out["refused"] += r["refused"]
        with contextlib.suppress(OSError):
            os.unlink(path)
    return out
