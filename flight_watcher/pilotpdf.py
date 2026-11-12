"""A pilot's upload of the monthly pairings package or award from his portal (1.7.2, contract 1 revision 3, FW-0066).

Ryan, Nov 11: "either I or James can upload them; the pairings and awards are the same doc for each of us". Until
1.7.2 only the admin uploaded them in Home Assistant, and every instance reads the same files in the shared uploads
folder (/share/flight_watcher/uploads/<YYYY-MM>_<pairings|award>.pdf and its pdftotext -layout copy .txt).

The portal's uploads card cuts the PDF's base64 into upload/pdf commands (roles.SHAPE_CMDS, each under the 64 KB command
cap; the spool checks the shape only). On the pilot's own Watcher:
- Assembler puts one upload together at a time (in_flight 1): chunks in order, the same chunk again counts once, the
  next one within stale_s or the upload is dropped; every chunk carries the same fields; parts must be what the size
  needs; the whole base64 decodes strictly to size bytes whose sha256 is sha (at most file_bytes, 4 MB).
- check(): %PDF- at the start and %%EOF in the last 1024 bytes, then extract(): pdftotext -layout (the extractor the
  admin's uploads use) in a child process with a 30 s timeout and memory, CPU, file size and core limits (setrlimit in
  the child, a fresh interpreter that sets them and execs the extractor: LIMIT_SHIM), then the existing parsers must read the text as that month's pairing package (its title names the month,
  at least min_pairings pairings over every base and fleet, at least one A332 HNL one) or that month's award (its head
  names the month and it holds the pilot's own line). Anything else is refused with a plain reason, nothing stored.
- Review.store(): when nothing is on file for that month and kind the upload is used at once (both instances read it as
  today); when a file is on file, the pilot's copy goes to the quarantine folder (/share/flight_watcher/upload_review/
  quarantine/, mode 0700, files 0600), which no instance reads and nothing serves (not the uploads list, not the portal
  export, not the Web UI), until the admin approves it. Every file's provenance (who, when, sha256) is kept in
  upload_review/provenance.json.
- Review.decide() is the admin's (upload/decide, from his push or his Settings uploads card): approve swaps a pending
  copy in and keeps the file it replaces in upload_review/rollback/; remove takes a pilot's file in use off (the file it
  replaced comes back when there was one, else nothing is on file) and both instances re-read; reject deletes a
  pending copy. Each change bumps that file's generation (gens()), which every instance's uploads_check follows.

A pilot's PDF is untrusted data: it is only ever parsed as text by the same parsers as the admin's, never run, followed
or treated as an instruction.
"""
import base64
import binascii
import contextlib
import fcntl
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone

import pdfs as PDF
import roles

LIM = roles.PILOT_UPLOAD_LIMITS
KINDS = tuple(LIM["kinds"])
HST = timezone(timedelta(hours=-10))
UPLOADS = "/share/flight_watcher/uploads"  # web.UPLOAD_DIR: what every instance reads
REVIEW = "/share/flight_watcher/upload_review"  # provenance.json, quarantine/, rollback/: nothing reads or serves these
B64_RE = re.compile(r"[A-Za-z0-9+/]*={0,2}")
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December")
WHAT = {"pairings": "pairings package", "award": "award"}
TEXT_MAX = 64 * 1024 * 1024  # the most text a 4 MB PDF may give (RLIMIT_FSIZE in the child too)
KEEP = 60  # records kept in provenance.json (a live or pending one is never dropped)
ADMIN = "ryan"  # the admin's name in provenance (tickets' reporter): a pilot's card shows "the admin"
STATES = ("live", "pending", "approved", "rejected", "removed", "replaced", "superseded")


class Refused(ValueError):
    """An upload or a chunk refused; str() is plain text for the pilot's card (never any file content)."""


def parts_for(size):
    """The chunks a file of size bytes needs: its base64 length over chunk_chars."""
    return max(1, math.ceil(4 * math.ceil(size / 3) / LIM["chunk_chars"]))


def month_name(month):
    return f"{MONTHS[int(month[5:7]) - 1]} {month[:4]}"


def months_allowed(now=None):
    """This HST month and the next months_ahead, as YYYY-MM."""
    t = (now or datetime.now(HST)).astimezone(HST)
    out = []
    for k in range(LIM["months_ahead"] + 1):
        y, m = divmod(t.year * 12 + t.month - 1 + k, 12)
        out.append(f"{y:04d}-{m + 1:02d}")
    return out


def month_refusal(month, now=None):
    ok = months_allowed(now)
    if month not in ok:
        return f"pick {month_name(ok[0])}, {month_name(ok[1])} or {month_name(ok[2])}"
    return ""


# ---------------------------------------------------------------- chunks
class Assembler:
    """One upload being put together at a time for one pilot instance. add(d) takes one shape-checked chunk
    (portal.check_shape) and returns None while the upload is still coming, or (meta, file bytes) once its last chunk
    is in and the whole decodes to its size and sha256. Refused says why a chunk was not taken (the upload it belonged
    to is dropped, except for a first chunk of another upload while one is coming)."""

    META = ("uid", "kind", "month", "size", "sha", "parts")

    def __init__(self, now=time.time):
        self.now, self.lock = now, threading.Lock()
        self.cur = None  # {meta, got, data: [str], last: sha of the last chunk, at}
        self.done = None  # (uid, last chunk's sha): a resend of a finished upload's last chunk is ignored

    def _expire(self):
        if self.cur and self.now() - self.cur["at"] > LIM["stale_s"]:
            self.cur = None

    def busy(self):
        with self.lock:
            self._expire()
            return self.cur is not None

    def progress(self):
        """(uid, got, parts) of the upload coming, or None."""
        with self.lock:
            self._expire()
            c = self.cur
            return (c["meta"]["uid"], c["got"], c["meta"]["parts"]) if c else None

    def drop(self):
        with self.lock:
            self.cur = None

    def add(self, d):
        meta = {k: d[k] for k in self.META}
        part, data = int(d["part"]), d["data"]
        meta["size"], meta["parts"] = int(meta["size"]), int(meta["parts"])
        sha = hashlib.sha256(data.encode("ascii", "replace")).hexdigest()
        with self.lock:
            self._expire()
            c = self.cur
            if c and c["meta"] == meta and part == c["got"] and sha == c["last"]:
                c["at"] = self.now()
                return None  # the chunk just taken, sent again
            if not c and self.done == (meta["uid"], sha) and part == meta["parts"]:
                return None  # a finished upload's last chunk, sent again: already handed on
            if part == 1:
                if c and c["meta"]["uid"] != meta["uid"]:
                    raise Refused("another upload is still coming: one at a time (try again in 2 minutes)")
                if meta["kind"] not in KINDS:
                    raise Refused("only the pairings package or the award may be uploaded here")
                if meta["size"] > LIM["file_bytes"]:
                    raise Refused(f"the file is over {LIM['file_bytes'] // (1024 * 1024)} MB")
                if meta["parts"] != parts_for(meta["size"]):
                    raise Refused("the parts do not fit the file's size; nothing was stored")
                c = self.cur = {"meta": meta, "got": 0, "data": [], "last": "", "at": self.now()}
            elif not c or c["meta"] != meta or part != c["got"] + 1:
                if c and c["meta"]["uid"] == meta["uid"]:
                    self.cur = None
                raise Refused(f"part {part} of {meta['parts']} came out of order; the upload was dropped (send it "
                              "again)")
            c["data"].append(data)
            c["got"], c["last"], c["at"] = part, sha, self.now()
            if c["got"] < meta["parts"]:
                return None
            self.cur, self.done = None, (meta["uid"], sha)
            b64 = "".join(c["data"])
        return meta, decode(b64, meta)


def decode(b64, meta):
    """The file's bytes from its whole base64, strictly: the alphabet, padding only at the end, exactly meta size
    bytes, sha256 meta sha."""
    if not b64 or len(b64) % 4 or not B64_RE.fullmatch(b64):
        raise Refused("the file did not come through whole (not valid base64); nothing was stored")
    try:
        raw = base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError):
        raise Refused("the file did not come through whole (not valid base64); nothing was stored") from None
    if len(raw) != meta["size"]:
        raise Refused("the file's size does not match; nothing was stored")
    if len(raw) > LIM["file_bytes"]:
        raise Refused(f"the file is over {LIM['file_bytes'] // (1024 * 1024)} MB")
    if hashlib.sha256(raw).hexdigest() != meta["sha"]:
        raise Refused("the file changed on the way (its checksum does not match); nothing was stored")
    return raw


# ---------------------------------------------------------------- the checks
def pdf_shape(raw):
    """%PDF- at the start and %%EOF in the last 1024 bytes (a PDF's trailer), within file_bytes."""
    if not isinstance(raw, (bytes, bytearray)) or not raw.startswith(b"%PDF-"):
        raise Refused("that file is not a PDF")
    if b"%%EOF" not in raw[-1024:]:
        raise Refused("that PDF is not complete (no end of file mark); nothing was stored")
    if len(raw) > LIM["file_bytes"]:
        raise Refused(f"the file is over {LIM['file_bytes'] // (1024 * 1024)} MB")


def child_limits(mem_mb=None, cpu_s=None, fsize=TEXT_MAX):
    """The limits the extractor runs under: address space mem_mb, CPU cpu_s seconds, files it writes at most fsize
    bytes, no core file (extract_mem_mb, extract_cpu_s)."""
    return {"as": int(mem_mb or LIM["extract_mem_mb"]) * 1024 * 1024, "cpu": int(cpu_s or LIM["extract_cpu_s"]),
            "fsize": int(fsize)}


# The child the extractor runs in: a fresh interpreter with no threads (the Watcher has many, so a preexec_fn could
# deadlock between fork and exec) sets its own limits (setrlimit), puts SIGXFSZ and SIGPIPE back to their defaults
# (Python ignores them, and an exec keeps an ignored signal ignored) and execs the extractor, which keeps the limits.
LIMIT_SHIM = (
    "import os,resource,signal,sys\n"
    "a,c,f=(int(x) for x in sys.argv[1:4])\n"
    "resource.setrlimit(resource.RLIMIT_AS,(a,a))\n"
    "resource.setrlimit(resource.RLIMIT_CPU,(c,c+1))\n"
    "resource.setrlimit(resource.RLIMIT_FSIZE,(f,f))\n"
    "resource.setrlimit(resource.RLIMIT_CORE,(0,0))\n"
    "signal.signal(signal.SIGXFSZ,signal.SIG_DFL)\n"
    "signal.signal(signal.SIGPIPE,signal.SIG_DFL)\n"
    "os.execvp(sys.argv[5],sys.argv[5:])\n")
EXTRACTOR = ("pdftotext", "-layout")  # web._save_monthly's own


def extract(raw, workdir, timeout=None, cmd=EXTRACTOR, limits=None):
    """The PDF's text from pdftotext -layout run in a child process: the PDF written to a private folder under workdir
    (0700, the file 0600), no shell, stdin closed, its output discarded, a timeout (extract_timeout_s) and the limits of
    child_limits() set in the child (LIMIT_SHIM). Returns (text, the folder holding in.pdf and out.txt); Refused with a
    plain reason when it fails, times out or gives no text. The caller removes the folder."""
    import sys
    lim = limits or child_limits()
    os.makedirs(workdir, mode=0o700, exist_ok=True)
    d = tempfile.mkdtemp(prefix="up.", dir=workdir)  # mode 0700
    src, out = os.path.join(d, "in.pdf"), os.path.join(d, "out.txt")
    try:
        fd = os.open(src, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(raw)
        argv = [sys.executable, "-I", "-c", LIMIT_SHIM, str(lim["as"]), str(lim["cpu"]), str(lim["fsize"]), "--"]
        try:
            subprocess.run(argv + list(cmd) + [src, out], check=True, timeout=timeout or LIM["extract_timeout_s"],
                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           close_fds=True, env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "C.UTF-8"})
        except subprocess.TimeoutExpired:
            raise Refused(f"reading the PDF took over {timeout or LIM['extract_timeout_s']} s; nothing was "
                          "stored") from None
        except subprocess.CalledProcessError as e:
            raise Refused(f"the PDF could not be read (damaged or password protected? exit {e.returncode}); "
                          "nothing was stored") from None
        except OSError as e:
            raise Refused(f"the PDF reader could not run ({type(e).__name__}); nothing was stored") from None
        try:
            if os.path.getsize(out) >= min(TEXT_MAX, lim["fsize"]):
                raise Refused("the PDF gave too much text; nothing was stored")
            with open(out, encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            raise Refused("the PDF gave no text, so the Watcher cannot read it; nothing was stored") from None
        if not text.strip():
            raise Refused("the PDF gave no text (a scan?), so the Watcher cannot read it; nothing was stored")
        return text, d
    except BaseException:
        shutil.rmtree(d, ignore_errors=True)
        raise


def pairing_count(text):
    """Pairings in the package: distinct pairing headers over every base and fleet."""
    return len({m.group(1) for m in (PDF.PAIR_HDR.match(ln) for ln in text.splitlines()) if m})


def check_pairings(text, month):
    """That month's A332 pairing package (pdfs.py): its title names the month, at least min_pairings pairings, at least
    one A332 HNL pairing. {pairings, a332}; Refused otherwise."""
    pm = PDF.package_month(text)
    if not pm:
        raise Refused("this does not read as a pairing package (no 'Month YYYY Pairing Package' title)")
    if pm != month:
        raise Refused(f"this is the {month_name(pm)} pairing package, not {month_name(month)}'s")
    n = pairing_count(text)
    if n < LIM["min_pairings"]:
        raise Refused(f"only {n} pairings in it: a whole pairing package has at least {LIM['min_pairings']}")
    rows = PDF.parse_package(text)
    if not rows:
        raise Refused("no A332 HNL pairing in it")
    return {"pairings": n, "a332": len(rows)}


AWARD_MONTH_RE = re.compile(r"\b(" + "|".join(MONTHS) + r")\s+(\d{4})\b", re.I)


def award_month(text):
    """YYYY-MM of the first 'Month YYYY' in an award's first 15 lines ('November 2026 ALV', 'DECEMBER 2026 BID PERIOD';
    a 'Posted October 12, 2026' line has the day between, so it is not one), else ''."""
    for ln in (text or "").splitlines()[:15]:
        m = AWARD_MONTH_RE.search(ln)
        if m:
            return f"{m.group(2)}-{[x.lower() for x in MONTHS].index(m.group(1).lower()) + 1:02d}"
    return ""


def check_award(text, month, emp, details=None):
    """That month's PBS award (pdfs.parse_award) holding the pilot's own line: 'AWARD' in its head, its head names the
    month, his employee number's line is found. {items}; Refused otherwise."""
    head = "\n".join((text or "").splitlines()[:15])
    if "award" not in head.lower():
        raise Refused("this does not read as a PBS award (no AWARD in its title)")
    am = award_month(text)
    if not am:
        raise Refused("this award does not name its month")
    if am != month:
        raise Refused(f"this is the {month_name(am)} award, not {month_name(month)}'s")
    if not (isinstance(emp, str) and re.fullmatch(r"[0-9]{3,7}", emp)):
        raise Refused("the Watcher does not know your employee number yet (it learns it from your FLICA schedule): "
                      "try again after a schedule read")
    try:
        aw = PDF.parse_award(text, emp, details or {}, month)
    except ValueError:
        raise Refused("your line was found but its dates could not be read") from None
    if not aw:
        raise Refused("your line is not in this award")
    return {"items": len(aw["items"])}


def sha_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


# ---------------------------------------------------------------- provenance, quarantine, decisions
def _write_private(path, data, mode=0o600):
    d = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(prefix=".", suffix=".tmp", dir=d)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data if isinstance(data, bytes) else data.encode("utf-8"))
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


class Review:
    """The shared uploads folder's provenance and a pilot's quarantined copies (one store for every instance; they
    run in one container: an flock on <root>/.lock)."""

    def __init__(self, uploads=UPLOADS, root=REVIEW, now=time.time):
        self.uploads, self.root, self.now = uploads, root, now
        self.qdir, self.rdir = os.path.join(root, "quarantine"), os.path.join(root, "rollback")
        self.path = os.path.join(root, "provenance.json")
        self._tl = threading.Lock()

    # -- the store
    def _dirs(self):
        for d in (self.root, self.qdir, self.rdir):
            os.makedirs(d, mode=0o700, exist_ok=True)
            st = os.lstat(d)
            if os.path.islink(d) or not os.path.isdir(d):
                raise OSError(f"{d} is not a folder")
            if st.st_mode & 0o777 != 0o700:
                os.chmod(d, 0o700)

    @contextlib.contextmanager
    def lock(self):
        with self._tl:
            self._dirs()
            fd = os.open(os.path.join(self.root, ".lock"), os.O_RDWR | os.O_CREAT, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
                yield
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)

    def load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            d = {}
        if not isinstance(d, dict):
            d = {}
        d.setdefault("v", 1)
        d["uploads"] = [r for r in d.get("uploads") or [] if isinstance(r, dict)]
        d["files"] = d.get("files") if isinstance(d.get("files"), dict) else {}
        d["gen"] = d.get("gen") if isinstance(d.get("gen"), dict) else {}
        return d

    def _save(self, d):
        keep = [r for r in d["uploads"] if r.get("state") in ("live", "pending", "approved")]
        rest = [r for r in d["uploads"] if r not in keep][-max(0, KEEP - len(keep)):] if len(keep) < KEEP else []
        d["uploads"] = sorted(keep + rest, key=lambda r: r.get("at") or "")
        _write_private(self.path, json.dumps(d, separators=(",", ":"), sort_keys=True))

    def _iso(self):
        return datetime.fromtimestamp(self.now(), HST).isoformat(timespec="seconds")

    def _bump(self, d, name):
        d["gen"][name] = int(d["gen"].get(name) or 0) + 1

    def gens(self):
        """{<month>_<kind>: generation}: bumped by every change a pilot's upload or a decision makes to that file."""
        return {k: v for k, v in self.load()["gen"].items() if isinstance(v, int)}

    def live(self, name):
        return os.path.join(self.uploads, f"{name}.pdf"), os.path.join(self.uploads, f"{name}.txt")

    def q(self, uid):
        return os.path.join(self.qdir, f"{uid}.pdf"), os.path.join(self.qdir, f"{uid}.txt")

    # -- a pilot's upload
    def store(self, who, kind, month, raw, text_path, uid, info=None):
        """A checked upload of pilot who: used at once when nothing is on file for month and kind, else quarantined
        (an earlier pending copy of his for the same file is superseded). text_path is the extractor's output (moved,
        never read again here). Returns its record (state live, pending, or same: the file on file already)."""
        name = f"{month}_{kind}"
        sha = hashlib.sha256(raw).hexdigest()
        with self.lock():
            d = self.load()
            pdf, txt = self.live(name)
            rec = {"id": uid, "who": who, "kind": kind, "month": month, "at": self._iso(), "sha256": sha,
                   "size": len(raw), **(info or {})}
            if os.path.exists(pdf):
                if sha_file(pdf) == sha:
                    return {**rec, "state": "same"}
                for r in d["uploads"]:
                    if r.get("state") == "pending" and r.get("who") == who and (r.get("month"), r.get("kind")) == (
                            month, kind):
                        r.update(state="superseded", decided_at=rec["at"], decided_by="")
                        for p in self.q(r["id"]):
                            with contextlib.suppress(OSError):
                                os.unlink(p)
                qp, qt = self.q(uid)
                _write_private(qp, raw)
                shutil.move(text_path, qt)
                os.chmod(qt, 0o600)
                rec["state"] = "pending"
            else:
                os.makedirs(self.uploads, exist_ok=True)
                tmp_pdf, tmp_txt = pdf[:-4] + ".pilot.new.pdf", pdf[:-4] + ".pilot.new.txt"
                try:
                    with open(tmp_pdf, "wb") as f:
                        f.write(raw)
                    shutil.move(text_path, tmp_txt)
                    os.chmod(tmp_txt, 0o644)
                    os.replace(tmp_pdf, pdf)
                    os.replace(tmp_txt, txt)
                finally:
                    for p in (tmp_pdf, tmp_txt):
                        with contextlib.suppress(OSError):
                            os.unlink(p)
                rec.update(state="live", how="first")
                d["files"][name] = {"id": uid, "who": who, "at": rec["at"], "sha256": sha, "size": len(raw),
                                    "how": "first"}
                self._bump(d, name)
            d["uploads"].append(rec)
            self._save(d)
            return rec

    # -- the admin's own uploads (web._save_monthly)
    def record_admin(self, kind, month, sha, size, who=ADMIN):
        """The admin saved <month>_<kind> himself: its provenance is his; a pilot's file it replaced is 'replaced'."""
        name = f"{month}_{kind}"
        with self.lock():
            d = self.load()
            at = self._iso()
            for r in d["uploads"]:
                if r.get("state") in ("live", "approved") and (r.get("month"), r.get("kind")) == (month, kind):
                    r.update(state="replaced", decided_at=at, decided_by=who)
            d["files"][name] = {"id": "", "who": who, "at": at, "sha256": sha, "size": size, "how": "admin"}
            self._bump(d, name)
            self._save(d)

    # -- the admin's decisions
    def decide(self, uid, action, by=ADMIN, after=None):
        """approve (a pending copy is swapped in, the file it replaces kept in rollback/), remove (a pilot's file in
        use goes; the file it replaced comes back when there is one, else nothing is on file) or reject (a pending
        copy is deleted). (ok, message, record or None). after(record) runs under the lock when something changed."""
        if action not in ("approve", "remove", "reject"):
            return False, "unknown action", None
        with self.lock():
            d = self.load()
            rec = next((r for r in d["uploads"] if r.get("id") == uid), None)
            if rec is None:
                return False, "no such upload", None
            name, at, what = f"{rec['month']}_{rec['kind']}", self._iso(), self.what(rec)
            pdf, txt = self.live(name)
            if action in ("approve", "reject"):
                if rec.get("state") != "pending":
                    return False, f"{what} is not waiting (it is {rec.get('state')})", rec
                qp, qt = self.q(uid)
                if action == "reject":
                    for p in (qp, qt):
                        with contextlib.suppress(OSError):
                            os.unlink(p)
                    rec.update(state="rejected", decided_at=at, decided_by=by)
                    self._save(d)
                    return True, f"rejected {what}: deleted, the file on file stays", rec
                if not (os.path.isfile(qp) and os.path.isfile(qt)):
                    rec.update(state="rejected", decided_at=at, decided_by=by)
                    self._save(d)
                    return False, f"{what}: its copy is gone; nothing changed", rec
                prev, kept = d["files"].get(name), ""
                if os.path.exists(pdf):
                    kept = f"{name}.{int(self.now())}.{uid[:8]}"
                    shutil.move(pdf, os.path.join(self.rdir, kept + ".pdf"))
                    if os.path.exists(txt):
                        shutil.move(txt, os.path.join(self.rdir, kept + ".txt"))
                os.chmod(qp, 0o644)
                os.chmod(qt, 0o644)
                shutil.move(qp, pdf)
                shutil.move(qt, txt)
                os.utime(pdf)
                os.utime(txt)
                for r in d["uploads"]:
                    if r is not rec and r.get("state") in ("live", "approved") and (r.get("month"), r.get("kind")) == (
                            rec["month"], rec["kind"]):
                        r.update(state="replaced", decided_at=at, decided_by=by)
                rec.update(state="approved", decided_at=at, decided_by=by, prev=kept, prev_file=prev or None)
                d["files"][name] = {"id": uid, "who": rec["who"], "at": at, "sha256": rec["sha256"],
                                    "size": rec["size"], "how": "approved"}
                self._bump(d, name)
                if after:
                    after(rec)
                self._save(d)
                return True, f"approved {what}: in use now; the file it replaced is kept", rec
            # remove
            cur = d["files"].get(name) or {}
            if rec.get("state") not in ("live", "approved") or cur.get("id") != uid:
                return False, f"{what} is not the file in use", rec
            for p in (pdf, txt):
                with contextlib.suppress(OSError):
                    os.unlink(p)
            back = rec.get("prev") or ""
            bp, bt = os.path.join(self.rdir, back + ".pdf"), os.path.join(self.rdir, back + ".txt")
            if back and os.path.isfile(bp) and os.path.isfile(bt):
                shutil.move(bp, pdf)
                shutil.move(bt, txt)
                os.utime(pdf)
                os.utime(txt)
                d["files"][name] = rec.get("prev_file") or {"id": "", "who": "", "at": at, "sha256": sha_file(pdf),
                                                            "size": os.path.getsize(pdf), "how": "restored"}
                msg = f"removed {what}: the file it replaced is back"
            else:
                d["files"].pop(name, None)
                msg = f"removed {what}: nothing is on file for it now"
            rec.update(state="removed", decided_at=at, decided_by=by)
            self._bump(d, name)
            if after:
                after(rec)
            self._save(d)
            return True, msg, rec

    @staticmethod
    def what(rec):
        return f"the {month_name(rec['month'])} {WHAT.get(rec['kind'], rec['kind'])} from {rec.get('who') or '?'}"

    # -- listings (no file content, ever)
    def records(self):
        return list(self.load()["uploads"])

    def on_file(self, month, kind):
        """(on file, its provenance or {})."""
        name = f"{month}_{kind}"
        return os.path.exists(self.live(name)[0]), self.load()["files"].get(name) or {}
