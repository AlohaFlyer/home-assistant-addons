"""Flight Watcher pilot portal, the Watcher's half (1.6.0, FW-0061). The interface is PORTAL_CONTRACT.md (contract 1)
and its fixture tests/fixtures/portal_contract_v1.json, which contract_text() below generates.

Dark until a pilot entry in the option `pilots` has `portal: true`. Then run.py makes /share/fw_portal/<name>/ (out/
for that pilot's Watcher, in/ for the HOM portal, which runs as uid/gid 2061) and the Ed25519 signing key
/data/portal_ed25519.pem (never under /share: a /share writer could swap it), and that pilot's watcher.py writes its
states, events, results, list files and card bundle to out/ as signed envelopes and reads the portal's commands from
in/. The admin (the default instance, Ryan's) never has a portal: nothing here runs for it.

Everything here is file and crypto logic only: no MQTT, no Home Assistant, no FLICA (FLICA stays read only; the portal
adds no FLICA page loads). watcher.py does the wiring, ntfy.py the pushes.
"""
import base64
import collections
import hashlib
import json
import math
import os
import re
import secrets
import stat
import tempfile
import threading
import time
import unicodedata

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

import roles

FWP = 1  # the envelope and command format; equals roles.CONTRACT in contract 1
PORTAL_UID = PORTAL_GID = 2061  # reserved for the HOM portal process; the Watcher never runs as it
ROOT = "/share/fw_portal"
KEY_FILE = "/data/portal_ed25519.pem"
KB = 1024
CAPS = {"manifest": 256 * KB, "state": 2048 * KB, "events": 256 * KB, "results": 64 * KB, "file": 8192 * KB,
        "blob": 1024 * KB, "cmd": 64 * KB}
CMD_NAME_RE = re.compile(r"^\d{13}-[0-9a-f]{16}\.json$")
HEX16_RE = re.compile(r"^[0-9a-f]{16}$")
PUB_RE = re.compile(r"^ed25519:[A-Za-z0-9_-]{43}$")
ORIGIN_RE = re.compile(r"^https://[a-z0-9-]+\.[a-z0-9-]+\.ts\.net$")
CMD_MAX_AGE_S = 300
CMD_MAX_AHEAD_S = 60  # a command stamped this far in the future (clock skew) is refused too
CMD_PER_MIN = 30
SEEN_KEEP_S = 600
DOT_STALE_S = 300  # an in/ dotfile this old is a write the portal abandoned (a live one lasts milliseconds)
EVENTS_KEEP = 100
RESULTS_KEEP = 50
BLOB_KEEP_S = 3600  # a blob is deleted this long after the manifest stopped naming it (a reader may still hold it)
MASK_ZERO = ("file_key", "versions_file_key")  # the www file keys: the portal serves the files itself
MASK_DROP = ("contact",)  # FW-0066 phones and emails of looked-up pilots (plan Q6: masked in contract 1)
OUT_DIRS = ("out", "out/blobs", "out/files")
TEST_SEED_LABEL = "Flight Watcher portal contract v1 TEST SEED: not a real key, never used outside tests"


class PortalError(ValueError):
    """A refused envelope, key, folder or command; str() says why (never a secret)."""

    def __init__(self, why, cid=None):
        super().__init__(why)
        self.cid = cid


def b64u(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def b64u_dec(s):
    if not isinstance(s, str) or not re.fullmatch(r"[A-Za-z0-9_-]*", s) or len(s) % 4 == 1:
        raise PortalError("not base64url")
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def dumps(obj):
    """Compact JSON text, the form every payload and out/ file uses."""
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


def origin_ok(s):
    """The option fw_portal_origin when it is a Tailscale Funnel origin (https://<host>.<tailnet>.ts.net), else ''."""
    s = str(s or "").strip()
    return s if ORIGIN_RE.fullmatch(s) else ""


def read_plain(path, cap, expect_uid=None):
    """(bytes, os.stat_result) of path, read only when it is a plain file: never through a symlink (O_NOFOLLOW), never
    blocking on a FIFO (O_NONBLOCK), owned by expect_uid when given, and at most cap bytes (the read itself stops at
    cap + 1, so a device behind the name cannot fill memory). PortalError for anything else; the fd is always
    closed."""
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    except OSError as e:
        raise PortalError(f"not readable as a plain file ({e.strerror})") from None
    chunks, n = [], 0
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise PortalError("not a plain file")
        if expect_uid is not None and st.st_uid != expect_uid:
            raise PortalError("wrong owner")
        if st.st_size > cap:
            raise PortalError(f"over {cap // KB} KB")
        while n <= cap:
            b = os.read(fd, min(1024 * KB, cap + 1 - n))
            if not b:
                break
            chunks.append(b)
            n += len(b)
    except OSError as e:
        raise PortalError(f"not readable as a plain file ({e.strerror})") from None
    finally:
        os.close(fd)
    if n > cap:
        raise PortalError(f"over {cap // KB} KB")
    return b"".join(chunks), st


# ---------------------------------------------------------------- the signing key
def _under_share(path):
    p = os.path.abspath(path)
    return p == "/share" or p.startswith("/share/") or os.path.realpath(p).startswith("/share/")


def load_key(path=KEY_FILE, create=True, log=None):
    """The add-on's Ed25519 key (PKCS8 PEM, mode 0600, root), made when missing (create: run.py, before any child).
    With create, a file that does not parse as one moves to <path>.bad and a new key is made (logged; the portal
    answers 503 until HOM's pinned key is updated); without it (a pilot's watcher.py) that is a PortalError and
    nothing moves. Refuses any path under /share."""
    if _under_share(path):
        raise PortalError("the portal signing key never goes under /share")
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except FileNotFoundError:
        fd = None
    if fd is not None:
        with os.fdopen(fd, "rb") as f:
            raw = f.read(64 * KB)
        try:
            key = serialization.load_pem_private_key(raw, password=None)
            if not isinstance(key, Ed25519PrivateKey):
                raise ValueError("not an Ed25519 key")
            if stat.S_IMODE(os.stat(path).st_mode) != 0o600:
                os.chmod(path, 0o600)
            return key
        except ValueError:
            if not create:
                raise PortalError("the portal signing key does not parse") from None
            os.replace(path, path + ".bad")
            if log:
                log(f"portal signing key did not parse: moved to {os.path.basename(path)}.bad, a new one is made "
                    "(update fw_signing_key in HOM)")
    if not create:
        raise PortalError("no portal signing key")
    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption())
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".portal_ed25519.", dir=d)  # mode 0600
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(pem)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return key


def raw_public(key):
    return key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def public_id(key):
    """'ed25519:<base64url of the raw 32-byte public key>' (51 characters): what HOM pins in fw_signing_key."""
    return "ed25519:" + b64u(raw_public(key))


def public_from_id(s):
    if not isinstance(s, str) or not PUB_RE.fullmatch(s):
        raise PortalError("not an ed25519:<43 base64url> public key")
    return Ed25519PublicKey.from_public_bytes(b64u_dec(s.split(":", 1)[1]))


def test_key():
    """The labeled test key of the contract fixture (Ed25519 signatures are deterministic, so the fixture is too)."""
    return Ed25519PrivateKey.from_private_bytes(hashlib.sha256(TEST_SEED_LABEL.encode()).digest())


# ---------------------------------------------------------------- envelopes
def signed_bytes(kind, pilot, seq, payload):
    """The bytes an envelope's sig covers: "fwp1\\n" + kind + "\\n" + pilot + "\\n" + str(seq) + "\\n" + payload."""
    return ("fwp%d\n%s\n%s\n%d\n" % (FWP, kind, pilot, seq) + payload).encode("utf-8")


def cap_for(kind):
    if kind.startswith("file:"):
        return CAPS["file"]
    return CAPS.get(kind, 0)


def envelope(key, kind, pilot, seq, payload):
    """{fwp, kind, pilot, seq, payload, sig}; payload is the JSON text of the body (a string, so no canonical JSON)."""
    if not isinstance(payload, str):
        raise PortalError("payload must be text")
    if not valid_kind(kind):
        raise PortalError(f"unknown kind {kind[:60]!r}")
    if not roles.NAME_RE.fullmatch(pilot or ""):
        raise PortalError("bad pilot name")
    if isinstance(seq, bool) or not isinstance(seq, int) or seq < 0:
        raise PortalError("bad seq")
    if len(payload.encode("utf-8")) > cap_for(kind):
        raise PortalError(f"{kind} over {cap_for(kind) // KB} KB")
    return {"fwp": FWP, "kind": kind, "pilot": pilot, "seq": seq, "payload": payload,
            "sig": b64u(key.sign(signed_bytes(kind, pilot, seq, payload)))}


def verify(pub, env, kind=None, pilot=None, after=None):
    """The payload text of env when it is a valid envelope signed by pub (a public key or its 'ed25519:' id), of the
    expected kind and pilot, with seq above after; else PortalError. What the HOM portal does before serving bytes."""
    if isinstance(pub, str):
        pub = public_from_id(pub)
    if not isinstance(env, dict) or set(env) != {"fwp", "kind", "pilot", "seq", "payload", "sig"}:
        raise PortalError("not an envelope")
    if env["fwp"] != FWP or isinstance(env["fwp"], bool):
        raise PortalError("unknown fwp")
    k, p, seq, payload = env["kind"], env["pilot"], env["seq"], env["payload"]
    if not isinstance(k, str) or not valid_kind(k) or (kind is not None and k != kind):
        raise PortalError("wrong kind")
    if not isinstance(p, str) or (pilot is not None and p != pilot):
        raise PortalError("wrong pilot")
    if isinstance(seq, bool) or not isinstance(seq, int) or seq < 0 or (after is not None and seq <= after):
        raise PortalError("seq not above the last one served")
    if not isinstance(payload, str) or len(payload.encode("utf-8")) > cap_for(k):
        raise PortalError("payload missing or over its cap")
    try:
        sig = b64u_dec(env["sig"])
    except PortalError:
        sig = b""
    if len(sig) != 64:
        raise PortalError("bad signature length")
    try:
        pub.verify(sig, signed_bytes(k, p, seq, payload))
    except InvalidSignature:
        raise PortalError("bad signature") from None
    return payload


def valid_kind(kind):
    if kind in ("manifest", "state", "events", "results"):
        return True
    parts = kind.split(":") if isinstance(kind, str) else []
    if len(parts) not in (2, 3) or parts[0] != "file" or parts[1] not in roles.FILE_KINDS:
        return False
    pat = roles.FILE_KINDS[parts[1]]
    return (len(parts) == 2 and not pat) or (len(parts) == 3 and bool(pat) and bool(re.fullmatch(pat, parts[2])))


def out_name(kind):
    """The file under out/ an envelope of kind lives in: manifest.json, state.json, events.json, results.json,
    files/<kind>.json or files/<kind>_<arg>.json."""
    if not valid_kind(kind):
        raise PortalError("unknown kind")
    if not kind.startswith("file:"):
        return f"{kind}.json"
    parts = kind.split(":")
    return "files/" + "_".join(parts[1:]) + ".json"


def kind_of(name):
    """The kind a file under out/ must carry (the inverse of out_name), or None for a name that is not one."""
    if name in ("manifest.json", "state.json", "events.json", "results.json"):
        return name[:-5]
    m = re.fullmatch(r"files/([a-z]+)(?:_([0-9-]+))?\.json", name or "")
    if not m:
        return None
    kind = "file:" + m.group(1) + (":" + m.group(2) if m.group(2) else "")
    return kind if valid_kind(kind) else None


class SeqStore:
    """seq per kind, strictly increasing and persisted (<data>/portal_seq.json), so a clock step back never reorders:
    each next() is max(now in ms, last + 1)."""

    def __init__(self, path, now=time.time):
        self.path, self.now, self.lock = path, now, threading.Lock()
        try:
            d = json.load(open(path, encoding="utf-8"))
            self.last = {k: v for k, v in d.items() if isinstance(k, str) and isinstance(v, int)} \
                if isinstance(d, dict) else {}
        except (OSError, ValueError):
            self.last = {}

    def next(self, kind):
        with self.lock:
            n = max(int(self.now() * 1000), self.last.get(kind, 0) + 1)
            self.last[kind] = n
            write_private(self.path, dumps(self.last))
            return n


def write_private(path, text):
    """text to path atomically, mode 0600 (the Watcher's own state under /data)."""
    d = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(prefix="." + os.path.basename(path) + ".", suffix=".tmp", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_out(path, data, mode=0o640, gid=PORTAL_GID):
    """data (bytes or text) to path atomically: a '.<file>.<rand>.tmp' in the same folder, mode 0640, owner root and
    group 2061 when the Watcher runs as root (the portal reads it; nobody else does), then a rename."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    d, base = os.path.split(path)
    tmp = os.path.join(d, f".{base}.{secrets.token_hex(8)}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), mode)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fchmod(f.fileno(), mode)
            if gid is not None and os.geteuid() == 0:
                os.fchown(f.fileno(), 0, gid)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class Writer:
    """Signs and writes one pilot's out/ files. write() returns the envelope; blob() a card's sha256."""

    def __init__(self, out_dir, pilot, key, seq):
        self.out, self.pilot, self.key, self.seq = out_dir, pilot, key, seq
        self.unlisted = {}  # sha256 -> when a sweep first found its blob named by no manifest

    def write(self, kind, body):
        payload = body if isinstance(body, str) else dumps(body)
        env = envelope(self.key, kind, self.pilot, self.seq.next(kind), payload)
        write_out(os.path.join(self.out, out_name(kind)), dumps(env))
        return env

    def blob(self, text):
        raw = text.encode("utf-8") if isinstance(text, str) else text
        if len(raw) > CAPS["blob"]:
            raise PortalError(f"blob over {CAPS['blob'] // KB} KB")
        sha = hashlib.sha256(raw).hexdigest()
        path = os.path.join(self.out, "blobs", f"{sha}.js")
        if not os.path.exists(path):
            write_out(path, raw)
        return sha

    def sweep_blobs(self, keep, now=None):
        """Delete each blob no manifest names (keep: the current manifest's sha256s) BLOB_KEEP_S after a sweep first
        found it unlisted, never by its file time: a portal may still hold the manifest that named it. The clock is
        in memory, so a restart only starts it again (a blob is kept up to an hour longer, never deleted early).
        Returns how many went."""
        now = time.time() if now is None else now
        n, d = 0, os.path.join(self.out, "blobs")
        try:
            names = os.listdir(d)
        except OSError:
            return 0
        still = {}
        for name in names:
            m = re.fullmatch(r"([0-9a-f]{64})\.js", name)
            if not m or m.group(1) in keep:
                continue
            sha = m.group(1)
            since = self.unlisted.get(sha, now)
            if now - since < BLOB_KEEP_S:
                still[sha] = since
                continue
            try:
                os.unlink(os.path.join(d, name))
                n += 1
            except FileNotFoundError:
                pass
        self.unlisted = still  # a blob back in keep, or gone, leaves the map
        return n


# ---------------------------------------------------------------- folders (run.py, as root, before any child)
def prepare(root, names, share_fw=None, euid=None, chown=None, log=print):
    """Make /share/fw_portal (root:root 0755), <root>/<name> and its out/, out/blobs, out/files (root:2061 0750) and
    in/ (2061:2061 0700) for each pilot in names, re-applying the modes on every start; owners are set when running as
    root. A folder that is a symlink or not a folder is refused: that pilot gets no portal (logged). With share_fw,
    /share/flight_watcher becomes 0700 (root only). Returns the names whose folders are ready."""
    euid = os.geteuid() if euid is None else euid
    chown = chown or os.chown

    def own(p, uid, gid):
        if euid == 0:
            chown(p, uid, gid)

    def folder(p, mode, uid, gid):
        try:
            st = os.lstat(p)
        except FileNotFoundError:
            os.mkdir(p, mode)
            st = os.lstat(p)
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
            raise PortalError(f"{p} is a symlink or not a folder")
        os.chmod(p, mode)
        own(p, uid, gid)

    ready = []
    try:
        folder(root, 0o755, 0, 0)
    except (OSError, PortalError) as e:
        log(f"portal folders refused ({e}): no pilot portal this start")
        return ready
    for name in names:
        if not roles.NAME_RE.fullmatch(name or ""):
            continue
        d = os.path.join(root, name)
        try:
            folder(d, 0o750, 0, PORTAL_GID)
            for sub in OUT_DIRS:
                folder(os.path.join(d, sub), 0o750, 0, PORTAL_GID)
            folder(os.path.join(d, "in"), 0o700, PORTAL_UID, PORTAL_GID)
            ready.append(name)
        except (OSError, PortalError) as e:
            log(f"portal for pilot {name!r} refused: {e}")
    if share_fw and ready:
        try:
            st = os.lstat(share_fw)
            if stat.S_ISDIR(st.st_mode) and not stat.S_ISLNK(st.st_mode):
                os.chmod(share_fw, 0o700)
                own(share_fw, 0, 0)
        except FileNotFoundError:
            pass
        except OSError as e:
            log(f"{share_fw} mode not set: {e}")
    return ready


_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


def _empty(name, dir_fd, keep_dirs=()):
    """Empties the folder name (relative to dir_fd) without ever following a link: every file, link or FIFO in it is
    unlinked; a sub-folder named in keep_dirs is emptied the same way (one level) and kept, any other one is removed
    only when it is empty. When name itself is a symlink or not a folder, that entry goes. Returns how many entries
    went. Never raises."""
    try:
        fd = os.open(name, _DIR_FLAGS, dir_fd=dir_fd)
    except FileNotFoundError:
        return 0
    except OSError:
        try:
            if stat.S_ISDIR(os.stat(name, dir_fd=dir_fd, follow_symlinks=False).st_mode):
                return 0  # a real folder this process cannot open: left alone
            os.unlink(name, dir_fd=dir_fd)  # a symlink (never its target) or a file in place of the folder
            return 1
        except OSError:
            return 0
    n = 0
    try:
        for entry in os.listdir(fd):
            try:
                is_dir = stat.S_ISDIR(os.stat(entry, dir_fd=fd, follow_symlinks=False).st_mode)
                if is_dir and entry in keep_dirs:
                    n += _empty(entry, fd)
                elif is_dir:
                    os.rmdir(entry, dir_fd=fd)
                    n += 1
                else:
                    os.unlink(entry, dir_fd=fd)
                    n += 1
            except OSError:
                pass
    except OSError:
        pass
    finally:
        os.close(fd)
    return n


def retire(root, keep, log=print):
    """run.py, as root, on every start: a pilot folder under root (a real folder named by roles.NAME_RE) whose pilot
    is not in keep (its entry no longer has portal: true, or its portal was refused this start) gets its out/ (with
    out/blobs and out/files) and in/ emptied, never following a link, so the portal stops serving that pilot's last
    state and files (it answers 503 without state.json and manifest.json) and no command waits in in/. The folders
    stay (prepare re-applies their modes when the portal comes back); <data>/portal_seq.json is never touched, so a
    later re-enable still writes higher seqs. One log line per pilot that had anything removed. With no root (an
    install that never had a portal), or a root that is a symlink or not a folder: nothing at all, not even a line.
    Returns the names cleared."""
    try:
        rfd = os.open(root, _DIR_FLAGS)
    except OSError:
        return []
    done = []
    try:
        for name in sorted(os.listdir(rfd)):
            if name in keep or not roles.NAME_RE.fullmatch(name):
                continue
            try:
                pfd = os.open(name, _DIR_FLAGS, dir_fd=rfd)
            except OSError:  # a symlink or a file: not a pilot folder this made
                continue
            try:
                n = _empty("out", pfd, keep_dirs=("blobs", "files")) + _empty("in", pfd)
            finally:
                os.close(pfd)
            if n:
                done.append(name)
                log(f"portal for pilot {name!r} off: out/ and in/ cleared ({n} entries)")
    except OSError:
        pass
    finally:
        os.close(rfd)
    return done


# ---------------------------------------------------------------- the in/ spool (the portal's commands)
class Spool:
    """Reads and checks the portal's command files in one pilot's in/ folder (contract 3.5). take(path) deletes the
    file and returns (id, sub, payload) for an accepted command, or raises PortalError (its cid set when the file named
    one) for a refused one; a dotfile (the portal's write in progress) is left alone (None). names() never lists a
    dotfile and removes one older than DOT_STALE_S (counted in reaped)."""

    def __init__(self, pilot, state_path=None, now=time.time, expect_uid=None):
        self.pilot, self.state_path, self.now, self.expect_uid = pilot, state_path, now, expect_uid
        self.seen, self.accepted, self.reaped = {}, collections.deque(), 0
        self.stuck = set()  # names of in/ folders that could not be removed (not empty): refused once, then skipped
        try:
            d = json.load(open(state_path, encoding="utf-8")) if state_path else {}
            self.seen = {k: v for k, v in (d.get("seen") or {}).items() if HEX16_RE.fullmatch(k) and isinstance(v, int)}
        except (OSError, ValueError, AttributeError):
            self.seen = {}

    def _save(self):
        if self.state_path:
            try:
                write_private(self.state_path, dumps({"seen": self.seen}))
            except OSError:
                pass

    def names(self, d):
        """The entries of in/ (d) to take, oldest name first. A folder already refused and left in place (stuck: not
        empty) is skipped quietly, so it is neither logged every poll nor in the way of the commands after it; it is
        removed quietly once it is empty, and forgotten once it is gone or no longer a folder. A dotfile (the portal's
        write in progress, never taken) is never listed, so leftovers can never fill a poll's cap ahead of the
        commands ('.' sorts before every command name); one not changed for DOT_STALE_S is a write the portal
        abandoned (a crash between write and rename) and is removed (_reap)."""
        listing = []
        for name in sorted(os.listdir(d)):
            if name.startswith("."):
                self._reap(d, name)
            else:
                listing.append(name)
        self.stuck &= set(listing)
        out = []
        for name in listing:
            if name in self.stuck:
                p = os.path.join(d, name)
                try:
                    if stat.S_ISDIR(os.lstat(p).st_mode):
                        try:
                            os.rmdir(p)
                            self.stuck.discard(name)
                        except OSError:
                            pass
                        continue
                except OSError:
                    pass
                self.stuck.discard(name)
            out.append(name)
        return out

    def _reap(self, d, name):
        """Removes the dotfile d/name (never followed: a link goes, not its target) when its mtime is DOT_STALE_S or
        more behind now; a dot folder, a fresh one or one dated ahead is left alone. Never raises."""
        p = os.path.join(d, name)
        try:
            st = os.lstat(p)
            if stat.S_ISDIR(st.st_mode) or self.now() - st.st_mtime < DOT_STALE_S:
                return
            os.unlink(p)
            self.reaped += 1
        except OSError:
            pass

    def take(self, path):
        name = os.path.basename(path)
        if name.startswith("."):
            return None
        try:
            return self._take(path, name)
        finally:
            self._remove(path, name)

    def _remove(self, path, name):
        """Every entry goes after it is read: a file or link with unlink, a folder with rmdir; a folder that is not
        empty (or anything else that cannot go) joins stuck. Never raises."""
        try:
            os.unlink(path)
            return
        except FileNotFoundError:
            return
        except OSError:
            pass
        try:
            os.rmdir(path)
            return
        except FileNotFoundError:
            return
        except OSError:
            self.stuck.add(name)

    def _read(self, path, name):
        if not CMD_NAME_RE.fullmatch(name):
            raise PortalError("bad file name")
        raw, _ = read_plain(path, CAPS["cmd"], self.expect_uid)  # a folder, FIFO or link: PortalError, fd closed
        try:
            d = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, RecursionError):
            raise PortalError("not JSON") from None
        if not isinstance(d, dict):
            raise PortalError("not a JSON object")
        return d

    def _take(self, path, name):
        d = self._read(path, name)
        cid = d.get("id") if isinstance(d.get("id"), str) and HEX16_RE.fullmatch(d.get("id")) else None
        if cid is None or name[14:30] != cid:
            raise PortalError("id missing or not the file's")
        now_ms = int(self.now() * 1000)
        self.seen = {k: v for k, v in self.seen.items() if now_ms - v < SEEN_KEEP_S * 1000}
        if cid in self.seen:
            raise PortalError("duplicate id", cid)
        self.seen[cid] = now_ms
        self._save()
        if d.get("fwp") != FWP or isinstance(d.get("fwp"), bool):
            raise PortalError("unknown fwp", cid)
        if d.get("pilot") != self.pilot:
            raise PortalError("wrong pilot", cid)
        ts = d.get("ts")
        if isinstance(ts, bool) or not isinstance(ts, int):
            raise PortalError("bad ts", cid)
        if now_ms - ts > CMD_MAX_AGE_S * 1000 or ts - now_ms > CMD_MAX_AHEAD_S * 1000:
            raise PortalError("too old or clock off", cid)
        if not isinstance(d.get("session"), str) or not HEX16_RE.fullmatch(d["session"]):
            raise PortalError("bad session", cid)
        sub, payload = d.get("sub"), d.get("payload")
        if not isinstance(payload, str):
            raise PortalError("payload is not text", cid)
        key = roles.portal_sub(sub)
        if key is None:
            raise PortalError("sub not allowed: " + (re.sub(r"[^a-z0-9_/+-]", "?", sub[:40]) if isinstance(sub, str)
                                                       else "none"), cid)
        while self.accepted and now_ms - self.accepted[0] >= 60000:
            self.accepted.popleft()
        if len(self.accepted) >= CMD_PER_MIN:
            raise PortalError(f"over {CMD_PER_MIN} commands a minute", cid)
        if key == "settings/set":
            check_sealed(payload, cid)
        elif key == "pref/set":
            check_pref(payload, cid)
        elif key in ("freq/normal_min/set", "freq/hunt_s/set"):
            check_freq(key.split("/")[1], payload, cid)
        self.accepted.append(now_ms)
        return cid, sub, payload


def check_sealed(payload, cid=None):
    """settings/set from the portal must be exactly {"enc": {...}}: sealed in the browser, never plain."""
    try:
        d = json.loads(payload)
    except (ValueError, RecursionError):
        d = None
    if not isinstance(d, dict) or set(d) != {"enc"} or not isinstance(d["enc"], dict):
        raise PortalError("settings must be sealed ({\"enc\": ...} only)", cid)


def check_pref(payload, cid=None):
    """pref/set: {"key": one of roles.PREF_KEYS, "value": within its bounds}; returns (key, normalized value)."""
    try:
        d = json.loads(payload)
    except (ValueError, TypeError, RecursionError):
        d = None
    if not isinstance(d, dict) or set(d) != {"key", "value"}:
        raise PortalError("pref/set is {\"key\", \"value\"}", cid)
    try:
        return d["key"], roles.pref_value(d["key"], d["value"])
    except (ValueError, OverflowError, TypeError) as e:  # a refusal is always a PortalError, never another error
        raise PortalError(str(e), cid) from None


def check_freq(key, payload, cid=None):
    """freq/<key>/set (key normal_min or hunt_s): a finite number within roles.FREQ_LIMITS[key], the slider's range
    (the handler rounds it); 'inf', 'nan', '1e999' or text are refused. Returns the number."""
    lo, hi = roles.FREQ_LIMITS[key]
    try:
        v = float(payload)
    except (ValueError, TypeError, OverflowError):
        v = None
    if v is None or not math.isfinite(v) or not lo <= v <= hi:
        raise PortalError(f"freq {key}: not a number from {lo} to {hi}", cid)
    return v


# ---------------------------------------------------------------- events (events.json and ntfy share them)
_TAGS = {"new_pairing": "airplane", "rule_match": "dart", "recall_miss": "warning", "request_decided": "envelope",
         "schedule_changed": "calendar", "charter": "airplane", "hidden": "eyes", "needs_settings": "key",
         "stopped_*": "rotating_light"}


def _clean(v, n=120):
    """A whitelisted value as it may leave the Watcher: short text without control characters, a URL or an e-mail
    address; numbers and booleans as they are; a list of such texts; anything else dropped (None)."""
    if isinstance(v, bool) or isinstance(v, (int, float)):
        return v
    if isinstance(v, str):
        s = "".join(ch for ch in v if unicodedata.category(ch)[0] != "C").strip()[:n]
        return None if (not s or "://" in s or "@" in s) else s
    if isinstance(v, (list, tuple)):
        out = [x for x in (_clean(x, 40) for x in list(v)[:20]) if isinstance(x, str)]
        return out or None
    return None


def event_data(kind, payload):
    """The EVENT_FIELDS of an event payload (blk read as block), cleaned (_clean); nothing else ever."""
    p = dict(payload) if isinstance(payload, dict) else {}
    if "block" not in p and "blk" in p:
        p["block"] = p.get("blk")
    if isinstance(p.get("row"), dict):  # rule_match: the matched row
        p = {**{k: v for k, v in p["row"].items() if k not in p}, **p}
    out = {}
    for k in roles.EVENT_FIELDS:
        if k in p:
            v = _clean(p[k])
            if v is not None:
                out[k] = v
    return out


def _j(*parts):
    return " ".join(str(x) for x in parts if x not in (None, "", [], False)).strip()


def event_text(kind, d):
    """(title, body) of an event from its data alone (event_data), so neither can carry a field data does not."""
    when = d.get("dates") or d.get("start") or d.get("date") or ""
    facts = []
    if d.get("days"):
        facts.append(f"{d['days']} days" + (f", layover {d['layover']}" if d.get("layover") else ""))
    for k, label in (("report", "Report"), ("release", "Release"), ("credit", "Credit"), ("block", "Block"),
                     ("fit", "Fit"), ("far", "FAR 117"), ("comm", "Commute"), ("month_rule", "Month")):
        if d.get(k) not in (None, ""):
            facts.append(f"{label} {d[k]}")
    if d.get("vac"):
        facts.append("touches VAC")
    if kind == "new_pairing":
        return _j("New pairing", d.get("pairing"), when), ". ".join(facts)
    if kind == "rule_match":
        return _j("Rule", d.get("rule_id"), "matched", d.get("pairing"), when), ". ".join(facts)
    if kind == "recall_miss":
        return (_j("Recall/O75", d.get("verdict"), d.get("date"), d.get("pairing")),
                "Check it on the Recall tab (PWA 22.G.2).")
    if kind == "request_decided":
        return _j("Request", d.get("status"), d.get("type")), _j(d.get("pairing"), when) or "See the Schedule tab."
    if kind == "schedule_changed":
        body = ". ".join(x for x in (_j("Added", ", ".join(d.get("added") or [])) if d.get("added") else "",
                                     _j("Removed", ", ".join(d.get("removed") or [])) if d.get("removed") else "") if x)
        return _j("Schedule changed", d.get("month")), body or "See the Schedule tab."
    if kind == "charter":
        return _j("Charter", d.get("flight"), d.get("date")), _j(d.get("route"))
    if kind == "hidden":
        return (_j("Hidden trip?", d.get("pairing"), when),
                ". ".join(["Seat still open on the pairing page, gone from the pot"] + facts))
    if kind == "needs_settings":
        return "Flight Watcher needs your FLICA login", "Enter your FLICA username and password on the Settings tab."
    if kind == "stopped_*":
        why = ("One FLICA login attempt failed: check your password on the Settings tab, then press Re-arm."
               if d.get("state") == "stopped_login_failed" else
               "Check FLICA yourself, then press Re-arm on the Watcher tab (a CAPTCHA or MFA is never worked around).")
        return "Flight Watcher stopped", why
    return _j(kind, d.get("pairing")), ""


def event_priority(kind, d):
    """ntfy priority: 5 for a new pairing that fits the schedule and is FAR 117 legal, 4 for a rule match, a recall
    miss or a stop, else 3."""
    if kind == "new_pairing":
        fits = str(d.get("fit") or "").startswith("Fits")
        legal = str(d.get("far") or "").startswith("OK")
        return 5 if fits and legal else 3
    return 4 if kind in ("rule_match", "recall_miss", "stopped_*") else 3


EVENT_TIME_FIELDS = ("since", "seen", "at", "updated")  # machine events, new_pairing, rule_match, schedule_changed


def event_id(kind, payload, d):
    """A short, name-free id for dedupe ((kind, id) pushes once): the event's own key or id when it has one, else a
    hash of its data and its own time (EVENT_TIME_FIELDS: the first one set), so one occurrence is one id: a replay of
    the same publish dedupes, while a pairing that leaves the pot and comes back (a new 'seen') is a new event."""
    p = payload if isinstance(payload, dict) else {}
    for k in ("key", "id"):
        if isinstance(p.get(k), str) and p[k]:
            return hashlib.sha256(f"{kind}|{p[k]}".encode()).hexdigest()[:16]
    when = next((p[k] for k in EVENT_TIME_FIELDS if p.get(k)), "")
    basis = dumps({k: d.get(k) for k in sorted(d)}) + "|" + str(when)
    return hashlib.sha256(f"{kind}|{basis}".encode()).hexdigest()[:16]


def event_record(kind, payload, seq, ts):
    """One events.json entry {seq, ts, kind, id, view, priority, title, body, data, tags}."""
    d = event_data(kind, payload)
    title, body = event_text(kind, d)
    return {"seq": seq, "ts": ts, "kind": kind, "id": event_id(kind, payload, d),
            "view": roles.EVENT_VIEWS.get(kind, "watcher"), "priority": event_priority(kind, d),
            "title": title[:120], "body": body[:600], "data": d, "tags": _TAGS.get(kind, "")}


# ---------------------------------------------------------------- state.json
def mask(v):
    """A state's attributes as the portal may serve them: file_key / versions_file_key become 32 zeros, contact goes
    (at any depth)."""
    if isinstance(v, dict):
        out = {}
        for k, x in v.items():
            if k in MASK_DROP:
                continue
            out[k] = ("0" * 32) if (k in MASK_ZERO and isinstance(x, str) and x) else mask(x)
        return out
    if isinstance(v, list):
        return [mask(x) for x in v]
    return v


def state_entry(d):
    """{state, attributes, last_changed, last_updated} of an HA /api/states answer; never its context."""
    return {"state": d.get("state"), "attributes": mask(d.get("attributes") or {}),
            "last_changed": d.get("last_changed"), "last_updated": d.get("last_updated")}


# ---------------------------------------------------------------- the card bundle
PORTAL_CARD_FLAG = ("const FW_PORTAL = false;", "const FW_PORTAL = true;")


def portal_card(text):
    """A card as the portal serves it: its cards.build text with FW_PORTAL turned on, so the settings card never
    sends a login unsealed there (no WebCrypto, or no pubkey yet: it sends nothing). A card without the flag, and every
    card deployed under /local/, is unchanged."""
    return text.replace(*PORTAL_CARD_FLAG, 1)


def card_subs(text, prefix):
    """The subs a card publishes to with mqtt.publish under prefix (literal topics, the recall card's _send(...))."""
    subs = set(re.findall(r'"%s/([a-z_]+(?:/[a-z_]+)*)"' % re.escape(prefix), text))
    subs |= set(re.findall(r'_send\("([a-z_]+(?:/[a-z_]+)*)"', text))
    return subs


# ---------------------------------------------------------------- the contract fixture
def contract():
    """Contract 1 as data: what tests/fixtures/portal_contract_v1.json holds (contract_text() is its exact text), so the
    HOM portal's tests and the Watcher's read the same allowlists, caps, masks and signed samples. The samples are
    signed with the labeled test key (test_key()), never the add-on's."""
    key = test_key()
    pilot, prefix, seq0 = "demo", "flight_watcher_demo", 1763600000000
    zeros = "0" * 32
    state = {"states": {
        f"sensor.{prefix}_state": {"state": "idle", "attributes": {"role": "pilot", "version": "1.6.0"},
                                   "last_changed": "2026-11-09T20:00:00+00:00",
                                   "last_updated": "2026-11-09T20:00:00+00:00"},
        f"sensor.{prefix}_finds": {"state": "1", "attributes": {"count": 1, "file_key": zeros, "rev": "abc123abc123",
                                                                "finds": [{"pairing": "H9001"}]},
                                   "last_changed": "2026-11-09T20:00:00+00:00",
                                   "last_updated": "2026-11-09T20:00:00+00:00"},
        roles.pref_entity("federal_tax_pct", prefix): {"state": "22.0",
                                                       "attributes": {"min": 0, "max": 45, "step": 0.5},
                                                       "last_changed": None, "last_updated": None}}, "ha_ok": True}
    ev = event_record("new_pairing", {"pairing": "H9001", "dates": "20NOV-22NOV", "days": 3, "layover": "SYD",
                                      "report": "0800", "credit": "15:20", "fit": "Fits", "far": "OK", "comm": "Yes",
                                      "month_rule": "", "captain": "Doe, Jane (10001)", "value": 1234.5,
                                      "comm_why": "home by 1800", "detail_url": "https://example.invalid/x"},
                      seq0 + 10, "2026-11-09T20:00:10+00:00")
    manifest = {"contract": 1, "app_version": "1.6.0", "pilot": pilot, "prefix": prefix, "role": "pilot",
                "cards": {f"flight-watcher-clock-card-{pilot}.js": hashlib.sha256(b"// sample card\n").hexdigest()},
                "layout": {"tabs": [{"id": "watcher", "title": "Watcher", "cards": [
                    {"type": f"custom:flight-watcher-clock-card-{pilot}"}, {"type": "heading", "heading": "Finds"}]}]},
                "services": {f"switch.{prefix}_pause": {"toggle": {"sub": "pause/set", "on": "ON", "off": "OFF"},
                                                        "turn_on": {"sub": "pause/set", "payload": "ON"},
                                                        "turn_off": {"sub": "pause/set", "payload": "OFF"}},
                             f"button.{prefix}_check_now": {"press": {"sub": "check_now/press", "payload": "PRESS"}},
                             f"number.{prefix}_hunt_check_every": {"set_value": {"sub": "freq/hunt_s/set"}},
                             roles.pref_entity("federal_tax_pct", prefix): {"set_value": {"sub": "pref/set",
                                                                                          "key": "federal_tax_pct"}},
                             f"input_number.{prefix}_month_offset": {"set_value": {"local": True},
                                                                      "increment": {"local": True},
                                                                      "decrement": {"local": True}}},
                "mqtt_subs": ["blocked/set", "improved/set", "pilot/set", "recall/act", "recall/set", "settings/set",
                              "trade/set"],
                "files": ["finds:2026-11", "pairings:2026-11", "pickers", "pilotver", "recall", "school:2026-27",
                          "versions"], "ntfy": False}
    bodies = [("manifest", manifest), ("state", state), ("events", {"events": [ev]}),
              ("results", {"results": [{"id": "0123456789abcdef", "ok": True, "why": ""},
                                       {"id": "fedcba9876543210", "ok": False, "why": "sub not allowed: drop/set"}]}),
              ("file:finds:2026-11", {"month": "2026-11", "count": 0, "finds": []}),
              ("file:pickers", {"count": 0, "pickers": []})]
    envs = []
    for i, (kind, body) in enumerate(bodies):
        envs.append({"file": out_name(kind), "envelope": envelope(key, kind, pilot, seq0 + i, dumps(body))})
    good = envs[1]["envelope"]
    bad = [
        {"why": "tampered payload", "envelope": {**good, "payload": good["payload"].replace("idle", "hunting")}},
        {"why": "wrong pilot", "envelope": {**good, "pilot": "james"}},
        {"why": "wrong kind (state.json holding a manifest)", "file": "state.json", "envelope": envs[0]["envelope"]},
        {"why": "rollback (seq not above the last served)", "after": good["seq"], "envelope": good},
        {"why": "fwp 2", "envelope": {**good, "fwp": 2}},
        {"why": "signed by another key", "envelope": envelope(Ed25519PrivateKey.from_private_bytes(
            hashlib.sha256(b"another test key").digest()), "state", pilot, good["seq"], good["payload"])},
    ]

    def cmd(sub, payload, n, ts=None, who=pilot):
        cid = "%016x" % (0xc0de0000 + n)
        t = seq0 + n if ts is None else ts
        return {"name": f"{t:013d}-{cid}.json",
                "cmd": {"fwp": 1, "id": cid, "pilot": who, "ts": t, "sub": sub, "payload": payload,
                        "session": "5e55105e55105e55"}}

    sealed = dumps({"enc": {"v": 1, "kid": "0011223344556677", "key": "AAAA", "iv": "AAAA", "data": "AAAA"}})
    accepted = [cmd("hunt/set", "ON", 1), cmd("pause/set", "OFF", 2), cmd("rearm/press", "PRESS", 3),
                cmd("check_now/press", "PRESS", 4), cmd("charter_scan/press", "PRESS", 5),
                cmd("freq/normal_min/set", "6", 6), cmd("freq/hunt_s/set", "40", 7),
                cmd("rule/sin_alert/live/set", "ON", 8), cmd("blocked/set", dumps({"date": "2026-11-20"}), 9),
                cmd("trade/set", dumps({"key": "H9001|2026-11-20"}), 10),
                cmd("pilot/set", dumps({"q": "10001"}), 11),
                cmd("improved/set", dumps({"month": "2026-11", "awarded": 1, "current": 2}), 12),
                cmd("recall/set", dumps({"date": "2026-11-03", "rows": []}), 13),
                cmd("recall/act", dumps({"refresh": True}), 14), cmd("settings/set", sealed, 15),
                cmd("pref/set", dumps({"key": "federal_tax_pct", "value": 22.5}), 16),
                cmd("pref/set", dumps({"key": "longevity_year", "value": 7}), 17),
                cmd("pref/set", dumps({"key": "er_trips", "value": "+H9001|2026-11-20,-H9002|2026-11-24"}), 18)]
    refused = [{"why": "sub not allowed", **cmd(s, "x", 100 + i)} for i, s in enumerate(roles.PORTAL_REFUSED)]
    refused += [
        {"why": "sub not allowed", **cmd("anything/else", "x", 200)},
        {"why": "sub not allowed (rule id)", **cmd("rule/Bad-Id/live/set", "ON", 201)},
        {"why": "settings must be sealed", **cmd("settings/set", dumps({"username": "doej", "password": "x"}), 202)},
        {"why": "settings must be sealed", **cmd("settings/set", dumps({"enc": {}, "username": "doej"}), 203)},
        {"why": "pref out of bounds", **cmd("pref/set", dumps({"key": "federal_tax_pct", "value": 46}), 204)},
        {"why": "pref off its step", **cmd("pref/set", dumps({"key": "state_tax_pct", "value": 1.1}), 205)},
        {"why": "pref out of bounds", **cmd("pref/set", dumps({"key": "longevity_year", "value": 13}), 206)},
        {"why": "pref unknown key", **cmd("pref/set", dumps({"key": "month_offset", "value": 1}), 207)},
        {"why": "pref bad list", **cmd("pref/set", dumps({"key": "er_trips", "value": "H9001"}), 208)},
        {"why": "freq not a finite number in range", **cmd("freq/hunt_s/set", "inf", 211)},
        {"why": "freq not a finite number in range", **cmd("freq/normal_min/set", "0", 212)},
        {"why": "wrong pilot", **cmd("hunt/set", "ON", 209, who="james")},
        {"why": "too old or clock off", **cmd("hunt/set", "ON", 210, ts=seq0 - (CMD_MAX_AGE_S + 1) * 1000)},
    ]
    file_urls = [
        {"url": f"/local/flight-watcher/{pilot}/finds_2026-11_{'ab' * 16}.json?t=1", "kind": "finds", "arg": "2026-11",
         "api": "/fw/api/file/finds/2026-11"},
        {"url": "/local/flight-watcher/pairings_2026-11.json?v=1", "kind": "pairings", "arg": "2026-11",
         "api": "/fw/api/file/pairings/2026-11"},
        {"url": f"/local/flight-watcher/{pilot}/school_2026-27.json?v=1", "kind": "school", "arg": "2026-27",
         "api": "/fw/api/file/school/2026-27"},
    ] + [{"url": f"/local/flight-watcher/{pilot}/{k}_{zeros}.json?r=abc", "kind": k, "arg": "",
          "api": f"/fw/api/file/{k}"} for k in ("versions", "pickers", "recall", "pilotver")]
    return {
        "contract": roles.CONTRACT, "fwp": FWP,
        "generated_by": "flight_watcher/portal.py contract(); docs: flight_watcher/PORTAL_CONTRACT.md",
        "names": {"pilot_re": roles.NAME_RE.pattern, "cmd_file_re": CMD_NAME_RE.pattern, "id_re": HEX16_RE.pattern,
                  "session_re": HEX16_RE.pattern, "rule_id_re": roles.PORTAL_RULE_ID_RE.pattern,
                  "public_key_re": PUB_RE.pattern, "origin_re": ORIGIN_RE.pattern},
        "uid": PORTAL_UID, "gid": PORTAL_GID,
        "paths": {"root": ROOT, "pilot": ROOT + "/<name>", "out": ROOT + "/<name>/out", "in": ROOT + "/<name>/in",
                  "key": KEY_FILE, "modes": {"root": "root:root 0755", "pilot": "root:2061 0750",
                                             "out": "root:2061 0750", "out_files": "root:2061 0640",
                                             "in": "2061:2061 0700", "in_files": "2061:2061 0600"},
                  "out_tmp": ".<file>.<16 hex>.tmp", "in_tmp": ".<file>.tmp"},
        "envelope": {"keys": ["fwp", "kind", "pilot", "seq", "payload", "sig"],
                     "signed_bytes": "fwp1\\n<kind>\\n<pilot>\\n<seq>\\n<payload>",
                     "sig": "base64url, no padding, 64-byte Ed25519 signature",
                     "kinds": ["manifest", "state", "events", "results", "file:<kind>", "file:<kind>:<arg>"],
                     "files": {"manifest": "manifest.json", "state": "state.json", "events": "events.json",
                               "results": "results.json", "file:<kind>": "files/<kind>.json",
                               "file:<kind>:<arg>": "files/<kind>_<arg>.json", "blob": "blobs/<sha256>.js"}},
        "caps": CAPS,
        "commands": {"max_bytes": CAPS["cmd"], "max_age_s": CMD_MAX_AGE_S, "max_ahead_s": CMD_MAX_AHEAD_S,
                     "per_minute": CMD_PER_MIN, "seen_keep_s": SEEN_KEEP_S,
                     "keys": ["fwp", "id", "pilot", "ts", "sub", "payload", "session"],
                     "allowed": list(roles.PORTAL_CMDS), "refused": list(roles.PORTAL_REFUSED),
                     "settings_set": "payload is exactly {\"enc\": {...}}",
                     "pref_set": "payload is {\"key\", \"value\"}",
                     "freq_set": "payload is a finite number within freq_limits[<normal_min|hunt_s>]",
                     "freq_limits": roles.FREQ_LIMITS},
        "prefs": roles.PREF_KEYS, "local_helpers": roles.LOCAL_HELPERS,
        "events": {"kinds": list(roles.PORTAL_EVENTS) + list(roles.MACHINE_EVENTS), "views": roles.EVENT_VIEWS,
                   "fields": list(roles.EVENT_FIELDS),
                   "entry": ["seq", "ts", "kind", "id", "view", "priority", "title", "body", "data", "tags"],
                   "keep": EVENTS_KEEP},
        "results": {"entry": ["id", "ok", "why"], "keep": RESULTS_KEEP},
        "tabs": list(roles.PORTAL_TABS),
        "file_kinds": roles.FILE_KINDS,
        "masks": {"zero": list(MASK_ZERO), "drop": list(MASK_DROP), "never_copied": ["context"]},
        "blob_keep_s": BLOB_KEEP_S,
        "test_key": {"label": TEST_SEED_LABEL, "seed": "sha256(label)", "public_key": public_id(key)},
        "samples": {"envelopes": envs, "bad_envelopes": bad,
                    "commands": {"accepted": accepted, "refused": refused}, "file_urls": file_urls},
    }


def contract_text():
    """The exact bytes of tests/fixtures/portal_contract_v1.json (also fwportal/contract/v1.json in HOM)."""
    return json.dumps(contract(), indent=1, ensure_ascii=True) + "\n"
