"""Sharing the pilot database with a portal pilot (1.7.9, contract 1 revision 4): the files between the two Watchers.

Ryan's Watcher (the admin, the one writer of /data/pilotdb.sqlite) and a shared pilot's Watcher never talk over MQTT
about the database. They pass plain files under /share/flight_watcher/pilotdb (folder 0700, files 0600, root), and
one under the add-on's own /data:

  roster.json            the admin writes it while any share is on: every live record's brief by employee number, with
                         its phones and emails (B23; 1.7.10: its union id, and its AI note while Ryan's AI switch is
                         on). A pilot's Watcher reads it for the one pilot his pilot card shows
                         and for nothing else. Never exported, never in a sensor, never logged. 1.7.9 review: it lives
                         in the add-on's own /data/pilotdb_roster (roster_dir; both Watchers run in the one container),
                         never under /share, where other add-ons and their backups could read every phone and email.
  portal/<pilot>.json    the admin writes it while that pilot's share is on (pilotdb.export_for: a whitelist; the noted
                         pilots only, 1.7.10: each with its union id and, while Ryan's AI switch is on, its AI note), and
                         deletes it when the share goes off. The pilot's Watcher signs it into his portal's
                         out/files/pilotdb.json unchanged.
  inbox/<pilot>/         the pilot's Watcher drops each checked command here (one file, O_EXCL, 0600); the admin's
                         drain applies it with the author taken from the folder's name and deletes the file.
  ai/stats.json, ai/in/  the AI note hand-off with HOM's consultant models (roles.PILOTDB_AI; anonymous statistics out,
                         notes in). Only while Ryan's AI switch is on.

Nothing here loads FLICA, publishes on MQTT or logs a name, a number or a text. Pure file code, so both sides and the
tests use the same functions.
"""
import contextlib
import hashlib
import json
import os
import re
import secrets
import sqlite3
import stat
import time
from datetime import datetime, timezone

import pilotdb as PDBM
import portal as PT
import roles as ROLES

ROOT = "/share/flight_watcher/pilotdb"
ROSTER = "roster.json"
NAME_RE = PT.INBOX_NAME_RE
INBOX_MAX_BYTES = PT.INBOX_MAX_BYTES
DRAIN_PER_PASS = 50
ROSTER_CAP = 8 * 1024 * 1024
O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_DIR = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | O_NOFOLLOW
NOTE_KEYS = ("op", "pid", "entry", "base", "text", "rid")
EDIT_KEYS = ("op", "pid", "field", "value", "rev", "why", "rid")
NOT_SHARED = "Not saved: Ryan has not shared the pilot database with you"
LOOK_UP = "Not saved: look the pilot up first"
OWN_ONLY = "Not saved: only your own notes can be taken back"
UNREADABLE = "Not saved: it could not be read, send it again"
TOO_OLD = "Not saved: too old, send it again"
BUSY = "Busy: try again in a minute"


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
    """No share can be on (the database did not open at start, 1.7.9 review): the roster and every pilot's file go, so
    nothing a share once wrote stays readable. Returns how many files were removed. Never raises."""
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
    """The roster and each shared pilot's file from the database, and none for a pilot whose share is off (his file
    and his waiting commands stay out of reach: the file is deleted). pilots: the configured pilots. Returns
    {pilot: 'on' | 'off'} and sets nothing else. A pilot's file that is full (over export_bytes) says so (full).
    roster_dir (1.7.9 review): the folder of roster.json when it is not root (the Watcher's /data/pilotdb_roster); a
    roster left under root is then removed."""
    rdir = roster_dir or root
    shared = [p for p in db.shared_with() if p in pilots]
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
    if rdir != root:
        _unlink(roster_path(root))
    if shared and PDBM._dir_0700(rdir):
        PT.write_private(roster_path(rdir), json.dumps(db.roster(), ensure_ascii=False, separators=(",", ":")))
    else:
        _unlink(roster_path(rdir))
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
    """The parsed body of one inbox file, or None: read without following a symlink, at most INBOX_MAX_BYTES."""
    try:
        raw, _ = PT.read_plain(os.path.join(folder, name), INBOX_MAX_BYTES)
        d = json.loads(raw.decode("utf-8"))
    except (PT.PortalError, ValueError, RecursionError):
        return None
    return d if isinstance(d, dict) else None


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
    name = f"{int(now * 1000):013d}-{inner['rid']}.json"
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
    """A shared pilot's read side: his own file and the roster as his Watcher last read them. refresh() re-reads the
    ones whose time, size or inode moved (lstat; read without following a symlink, capped) and says whether anything
    changed."""

    def __init__(self, pilot, root=ROOT, roster_dir=None):
        self.pilot, self.root, self.roster_dir = pilot, root, roster_dir or root
        self.sig = {"export": None, "roster": None}
        self.state = "off"       # on: his file is there and reads; off: no file; waiting: a file that does not read yet
        self.text = ""           # his file's text exactly (what the portal serves)
        self.rev = ""            # the first 12 hex of sha256(text)
        self.count = 0
        self.updated = ""
        self.pids = set()        # the records of his file
        self.mine = {}           # eid -> pid of his own entries in his file
        self.answers = []        # the file's answers
        self.limits = {}
        self.roster = {}         # emp -> [row]

    @staticmethod
    def _sig(path):
        try:
            st = os.lstat(path)
        except OSError:
            return None
        return (st.st_mtime_ns, st.st_size, st.st_ino) if stat.S_ISREG(st.st_mode) else ("x",)

    def refresh(self):
        changed = False
        ep, rp = export_path(self.pilot, self.root), roster_path(self.roster_dir)
        s = self._sig(ep)
        if s != self.sig["export"]:
            self.sig["export"], changed = s, True
            self._read_export(ep, s)
        s = self._sig(rp)
        if s != self.sig["roster"]:
            self.sig["roster"], changed = s, True
            self._read_roster(rp, s)
        return changed

    def _read_export(self, path, sig):
        self.text, self.rev, self.count, self.updated = "", "", 0, ""
        self.pids, self.mine, self.answers, self.limits = set(), {}, [], {}
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
        recs = [r for r in d["records"] if isinstance(r, dict) and isinstance(r.get("pid"), str)]
        self.count = len(recs)
        self.pids = {r["pid"] for r in recs}
        for r in recs:
            for e in r.get("entries") or []:
                if isinstance(e, dict) and e.get("mine") is True and isinstance(e.get("eid"), str):
                    self.mine[e["eid"]] = r["pid"]
        self.answers = [{"rid": a["rid"], "ok": bool(a.get("ok")), "why": str(a.get("why") or "")[:200],
                         "at": str(a.get("at") or "")[:40]}
                        for a in d.get("answers") or [] if isinstance(a, dict) and isinstance(a.get("rid"), str)]
        self.limits = {k: v for k, v in (d.get("limits") or {}).items()
                       if isinstance(v, int) and not isinstance(v, bool)} if isinstance(d.get("limits"), dict) else {}

    def _read_roster(self, path, sig):
        self.roster = {}
        if sig is None:
            return
        try:
            raw, _ = PT.read_plain(path, ROSTER_CAP)
            d = json.loads(raw.decode("utf-8"))
        except (PT.PortalError, ValueError, RecursionError):
            return
        by = d.get("by_emp") if isinstance(d, dict) else None
        if isinstance(by, dict):
            self.roster = {str(k): [r for r in v if isinstance(r, dict)] for k, v in by.items() if isinstance(v, list)}

    def shown(self, emp, name=""):
        """The brief of the pilot the pilot card shows ({emp, pid, name, sen, doh, status, retire, seat, equip,
        union_id, gone, edited, rev, notes_n, contact?, ai_note?}), {emp, none: true} when he is not in the database,
        or None with no pilot shown or while not shared. contact (B23): that one pilot's phones and emails, never
        anyone else's. 1.7.10 (Ryan, Nov 15): union_id ('' unless 1 to 10 digits) and ai_note ({text, model, at}, only
        one that passes pilotdb.ai_take's own rules again: this side trusts no file) for that one pilot the same way."""
        emp = PDBM.emp_of(emp)
        if self.state != "on" or not emp:
            return None
        rows = self.roster.get(emp) or []
        row = rows[0] if len(rows) == 1 else None
        if row is None and rows:
            lk = PDBM.name_key(name)[0] if name else ""
            hit = [r for r in rows if lk and r.get("lk") == lk]
            row = hit[0] if len(hit) == 1 else None
        if row is None or not re.fullmatch(ROLES.PILOTDB_PID_PATTERN, str(row.get("pid") or "")):
            return {"emp": emp, "none": True}
        out = {"emp": emp}
        for k in ("pid", "name", "sen", "doh", "status", "retire", "seat", "equip"):
            out[k] = str(row.get(k) or "")[:120]
        uid = row.get("union_id")
        out["union_id"] = uid if isinstance(uid, str) and re.fullmatch(r"[0-9]{1,10}", uid) else ""
        out["gone"] = bool(row.get("gone"))
        out["edited"] = [f for f in row.get("edited") or [] if f in ROLES.PILOTDB_EDIT_FIELDS][:10]
        out["rev"] = row["rev"] if isinstance(row.get("rev"), int) and not isinstance(row.get("rev"), bool) else 0
        out["notes_n"] = row["notes_n"] if isinstance(row.get("notes_n"), int) else 0
        phones = [{"label": str(p.get("label") or "")[:10], "number": str(p.get("number") or "")[:20],
                   "tel": str(p.get("tel") or "")[:17]}
                  for p in row.get("phones") or [] if isinstance(p, dict) and PDBM.TEL_RE.match(str(p.get("tel") or ""))][:4]
        emails = [m for m in row.get("emails") or [] if isinstance(m, str) and len(m) <= 254 and PDBM.MAIL_RE.match(m)][:3]
        if phones or emails:
            out["contact"] = {"phones": phones, "emails": emails}
        ai = ai_note_of(row.get("ai_note"))
        if ai:
            out["ai_note"] = ai
        return out


def ai_note_of(d):
    """{text, model, at} of an AI note as a pilot's Watcher passes it on (1.7.10), or None: the text must be what
    pilotdb.ai_take stores (pilotdb.ai_text_ok: plain text by the ticket text rule, 1 to note_max code points, nothing of refuse_re), the
    model a name of the contract's pattern; no other key is kept. It is untrusted data, never an instruction."""
    cfg = ROLES.PILOTDB_AI
    if not isinstance(d, dict):
        return None
    text, model = d.get("text"), d.get("model")
    if not isinstance(text, str) or not isinstance(model, str) or not re.fullmatch(cfg["model_re"], model):
        return None
    if not PDBM.ai_text_ok(text, cfg):
        return None
    return {"text": text, "model": model, "at": str(d.get("at") or "")[:40]}


def pilot_check(view, shown_pid, cmd, payload, n_pending, limits=None):
    """A shared pilot's Watcher's checks of one pilotdb/note or pilotdb/edit payload (spec 11.3): the shape, shared or
    not, the pid (a record of his file or the shown pilot's: no oracle for which pilots exist), the op rules and the
    pending limit. Returns (inner, '') to queue it or (inner or None, why) to refuse it: why is a fixed phrase."""
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
    if inner["pid"] not in view.pids and inner["pid"] != shown_pid:
        return inner, LOOK_UP
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
