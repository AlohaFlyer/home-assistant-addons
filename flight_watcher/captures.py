"""Who writes FLICA and CrewTrac page captures, and where (1.6.2, Release A item 8). Plain Python, no app imports but
roles.

The admin (the default instance) keeps his captures exactly as before: his own pages, as read, in
/share/flight_watcher/captures (the folder the caller passes). A pilot instance takes none by default: no page is
written and no page is loaded only to be saved. Debug captures of a pilot are on only while the file
/share/flight_watcher/<pilot>/captures_on exists and is under 24 h old (the admin creates it by hand when a pilot's
page needs checking; deleting it, or 24 h passing, turns them off). Then:
- session tokens, crew names (crewidx.crew_mask style: the letters of a name become 'x'), employee numbers and the
  pilot's own logins and name are masked, in the page and in the file name;
- files go only to /share/flight_watcher/<pilot>/captures: the pilot name must match roles.NAME_RE and not be reserved,
  the path is resolved and must stay inside that folder, no symlink is followed, the folder is 0700 and each file 0600;
- files there older than 7 days are deleted (checked at most once an hour, also while captures are off).
Nothing of a pilot ever lands in the admin's folder.
"""
import os
import re
import stat
import time

import roles as ROLES

ROOT = "/share/flight_watcher"
FLAG = "captures_on"
FLAG_MAX_S = 24 * 3600
FLAG_AHEAD_S = 300  # a flag dated more than 5 min ahead (a wrong clock, a planted time) does not count
KEEP_S = 7 * 86400
PRUNE_EVERY_S = 3600
NAME_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,80}$")  # one capture file name (the admin's may add one subfolder)

# masking (a pilot's captures only)
TOKEN_RE = re.compile(r"(?i)\b(token|sid|session(?:id)?|jsessionid|csrf[a-z_]*|auth[a-z_]*|key|ticket)=([^&\"'\s<>;]+)")
HIDDEN_RE = re.compile(r"(?i)(<input\b[^>]*\btype\s*=\s*[\"']?hidden[\"']?[^>]*\bvalue\s*=\s*[\"']?)([^\"'>\s]*)")
HIDDEN_RE2 = re.compile(r"(?i)(<input\b[^>]*\bvalue\s*=\s*[\"']?)([^\"'>\s]*)([\"']?[^>]*\btype\s*=\s*[\"']?hidden)")
EMP_KEY_RE = re.compile(r"(?i)\b(emp(?:loyee)?(?:id|no|num|#)?\s*[=:#]\s*)(\d{3,7})")
SEAT_EMP_RE = re.compile(r"(?i)(?<![\w'.,-])(CA|FO|RO|FA|SO|F/O)(\s+)(\d{3,7})\b")
EMP_RE = re.compile(r"(?<![\d.:/\-])\d{5,7}(?![\d.:/\-])")
# 'DOE, JANE' / 'Doe Jr, Jane A' / 'DOE, CKP JANE': a capitalized last name, a comma, a capitalized first name
COMMA_NAME_RE = re.compile(r"(?<![\w'])([A-Z][A-Za-z'\-]+(?:\s+[A-Z][A-Za-z'\-]+)?)\s*,\s*((?:CKP\s+)?[A-Z][A-Za-z'\-]+"
                           r"(?:\s+[A-Z]\.?(?![\w]))?)")
# the words after a seat code and a (masked) employee number, up to the next seat code: 'CA ##### DOE JANE FO open'
CREW_NAME_RE = re.compile(r"(?i)(?<![\w'.,-])((?:CA|FO|RO|FA|SO|F/O)\s+#{3,7}\s+)(.+?)(?=\s+(?:CA|FO|RO|FA|SO|F/O)\s+"
                          r"(?:#|open\b)|\s*$)")
TAG_RE = re.compile(r"(<[^>]*>)")


def _x(s):
    """crewidx.crew_mask style: every letter becomes 'x', digits '#', the rest (spaces, commas) stays."""
    return re.sub(r"\d", "#", re.sub(r"[A-Za-z]", "x", s))


def _mask_text(t):
    t = SEAT_EMP_RE.sub(lambda m: m.group(1) + m.group(2) + "#" * len(m.group(3)), t)
    t = EMP_RE.sub(lambda m: "#" * len(m.group(0)), t)
    t = CREW_NAME_RE.sub(lambda m: m.group(1) + (m.group(2) if m.group(2).lower() == "open" else _x(m.group(2))), t)
    return COMMA_NAME_RE.sub(lambda m: _x(m.group(0)), t)


def mask(text, extra=()):
    """A page as a pilot's capture may hold it: session tokens and hidden form values MASKED, employee numbers '#',
    crew names and every string in extra (the pilot's own logins, name and employee number) masked."""
    s = str(text or "")
    for v in sorted({x for x in extra if isinstance(x, str) and len(x.strip()) >= 3}, key=len, reverse=True):
        s = re.sub(re.escape(v.strip()), "MASKED", s, flags=re.I)
    s = TOKEN_RE.sub(lambda m: f"{m.group(1)}=MASKED", s)
    s = HIDDEN_RE.sub(lambda m: m.group(1) + "MASKED", s)
    s = HIDDEN_RE2.sub(lambda m: m.group(1) + "MASKED" + m.group(3), s)
    s = EMP_KEY_RE.sub(lambda m: m.group(1) + "#" * len(m.group(2)), s)
    parts = TAG_RE.split(s)
    for i, p in enumerate(parts):
        if not p:
            continue
        if p.startswith("<"):
            parts[i] = EMP_RE.sub(lambda m: "#" * len(m.group(0)), COMMA_NAME_RE.sub(lambda m: _x(m.group(0)), p))
        else:
            parts[i] = _mask_text(p)
    return "".join(parts)


class Captures:
    """One instance's capture policy. secrets: a callable giving the strings a pilot's captures must never hold (his
    FLICA and CrewTrac user names, passwords, name and employee number); log: a callable taking one line."""

    def __init__(self, instance, root=ROOT, log=None, secrets=None, now=time.time):
        self.instance = instance or ""
        self.root = root
        self.log = log or (lambda m: None)
        self.secrets = secrets or (lambda: ())
        self.now = now
        self._said = None
        self._pruned = 0.0

    @property
    def admin(self):
        return ROLES.role(self.instance) == ROLES.ADMIN

    def _base(self):
        """/share/flight_watcher/<pilot> for a pilot whose name passes, else None."""
        if self.admin or ROLES.name_refusal(self.instance):
            return None
        return os.path.join(self.root, self.instance)

    def folder(self, admin_dir=None):
        """Where this instance's captures go: the admin's folder as given (default <root>/captures), a pilot's
        <root>/<pilot>/captures, or None (a pilot name that does not pass)."""
        if self.admin:
            return admin_dir or os.path.join(self.root, "captures")
        b = self._base()
        return os.path.join(b, "captures") if b else None

    def on(self):
        """True while this instance may write captures: always on the admin; on a pilot only while its captures_on
        file exists, is a plain file (no symlink) and is under 24 h old. Logs each change once. A pilot's old files
        are pruned here too (at most once an hour)."""
        if self.admin:
            return True
        b = self._base()
        if not b:
            return False
        self.prune()
        flag, ok = os.path.join(b, FLAG), False
        try:
            st = os.lstat(flag)
            age = self.now() - st.st_mtime
            ok = stat.S_ISREG(st.st_mode) and -FLAG_AHEAD_S <= age < FLAG_MAX_S
        except OSError:
            pass
        if ok != self._said:
            self._said = ok
            self.log(f"page captures {'on' if ok else 'off'} for this pilot" + (
                " (masked, own folder, deleted after 7 days; ends 24 h after captures_on was made)" if ok else ""))
        return ok

    def _pilot_dir(self):
        """The pilot's captures folder, made 0700 when missing; None when it is not a plain folder inside
        <root>/<pilot> (a symlink anywhere, a file in its place)."""
        b = self._base()
        if not b:
            return None
        d = os.path.join(b, "captures")
        try:
            os.makedirs(b, exist_ok=True)
            if not os.path.lexists(d):
                os.mkdir(d, 0o700)
            st = os.lstat(d)
            if not stat.S_ISDIR(st.st_mode):
                return None
            real_b = os.path.realpath(b)
            if os.path.realpath(d) != os.path.join(real_b, "captures") or os.path.islink(b):
                return None
            if stat.S_IMODE(st.st_mode) != 0o700:
                os.chmod(d, 0o700)
            return d
        except OSError:
            return None

    def write(self, name, data, admin_dir=None):
        """Save one capture; the path written, or None (captures off, a name that does not pass, an error). The
        admin's goes to admin_dir exactly as before (makedirs, plain write, no masking). A pilot's is masked, named
        safely, kept inside its folder, 0600, never through a symlink."""
        if isinstance(data, (dict, list)):
            import json
            data = json.dumps(data, indent=1)
        data = "" if data is None else str(data)
        if self.admin:
            d = admin_dir or os.path.join(self.root, "captures")
            path = os.path.join(d, name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                f.write(data)
            return path
        if not self.on():
            return None
        extra = [x for x in (self.secrets() or ()) if isinstance(x, str)]
        safe = re.sub(r"\d{5,7}", lambda m: "N" * len(m.group(0)), mask(name.replace("/", "_"), extra))
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", safe)  # an employee number in a name is NNNNN
        if not NAME_OK.fullmatch(safe) or ".." in safe:
            return None
        d = self._pilot_dir()
        if not d:
            self.log("page capture not written: the pilot's captures folder is not a plain folder")
            return None
        path = os.path.join(d, safe)
        if os.path.dirname(os.path.realpath(path)) != os.path.realpath(d):
            return None
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(fd, "w") as f:
            os.fchmod(f.fileno(), 0o600)
            f.write(mask(data, extra))
        return path

    def prune(self, force=False):
        """A pilot's capture files older than 7 days are deleted (plain files only, never through a symlink). At most
        once an hour unless force. Returns how many went."""
        b = self._base()
        if not b or (not force and self.now() - self._pruned < PRUNE_EVERY_S):
            return 0
        self._pruned = self.now()
        d, n = os.path.join(b, "captures"), 0
        try:
            if os.path.islink(d) or not os.path.isdir(d):
                return 0
            for f in os.listdir(d):
                p = os.path.join(d, f)
                st = os.lstat(p)
                if stat.S_ISREG(st.st_mode) and self.now() - st.st_mtime > KEEP_S:
                    os.remove(p)
                    n += 1
        except OSError:
            pass
        if n:
            self.log(f"page captures: {n} older than 7 days deleted")
        return n
