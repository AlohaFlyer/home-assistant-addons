"""ntfy pushes for a pilot's portal (1.6.0, FW-0061).

Loaded only on a pilot instance whose portal is on (option pilots[].portal) and only when that pilot has saved both an
ntfy topic and an access token through the sealed Settings form (creds.json keys ntfy_topic, ntfy_token; never from a
plain message). The admin (Ryan's instance) never posts. Each push goes to the constant https://ntfy.sh/<topic>
(the host is never read from /share, an option or a message) with the pilot's token as a Bearer header. The text is
the portal event's own title and body (portal.event_record: built from whitelisted fields only, so no crew names,
employee numbers, URLs, commute reasons or pay amounts), with Click only when the option fw_portal_origin is a valid
Funnel origin. Dedupe on (kind, id), at most PER_HOUR pushes an hour, RETRIES tries with backoff. The token and the
topic are never logged: scrub() for this module's own lines, and a filter on urllib3's loggers for the request line
it writes at log_level debug (which carries the URL path, so the topic), installed by the first real sender (never on
the admin, which builds none).
"""
import collections
import logging
import queue
import re
import threading
import time
import unicodedata

import requests

HOST = "https://ntfy.sh"
TOPIC_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
TOKEN_RE = re.compile(r"^[A-Za-z0-9_.-]{8,128}$")
PER_HOUR = 30
RETRIES = 3
BACKOFF_S = (2, 4, 8)
DEDUPE_S = 86400
TIMEOUT_S = 10
KEYS = ("ntfy_topic", "ntfy_token")
# urllib3 writes each request line ('"POST /<topic> HTTP/1.1" 200') at DEBUG, and its retry notes carry the URL too
URLLIB3_LOGGERS = ("urllib3.connectionpool", "urllib3.util.retry")
_HIDDEN = set()  # every topic and token a real sender holds


class _Scrub(logging.Filter):
    """Replaces each _HIDDEN secret in a urllib3 log record with <hidden> (the line itself stays)."""

    def filter(self, rec):
        if not _HIDDEN:
            return True
        try:
            msg = rec.getMessage()
        except Exception:  # noqa: BLE001 (a record that does not format is left to logging)
            return True
        out = msg
        for secret in sorted(_HIDDEN, key=len, reverse=True):
            out = out.replace(secret, "<hidden>")
        if out != msg:
            rec.msg, rec.args = out, None
        return True


SCRUB = _Scrub()


def hide(*secrets):
    """Keep these out of urllib3's log lines from now on (SCRUB on URLLIB3_LOGGERS, added once)."""
    _HIDDEN.update(x for x in secrets if isinstance(x, str) and x)
    for name in URLLIB3_LOGGERS:
        lg = logging.getLogger(name)
        if SCRUB not in lg.filters:
            lg.addFilter(SCRUB)


def valid(topic, token):
    return bool(isinstance(topic, str) and TOPIC_RE.fullmatch(topic) and isinstance(token, str)
                and TOKEN_RE.fullmatch(token))


def _ascii(s, n):
    """Header-safe text: ASCII only (accents folded), no CR / LF, at most n characters."""
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode("ascii")
    return " ".join(s.split())[:n]


class Ntfy:
    """One pilot's ntfy sender. send(rec) posts one portal event record synchronously (tests); enqueue(rec) hands it
    to a worker thread so the Watcher's loop never waits on ntfy.sh."""

    def __init__(self, topic, token, origin="", log=None, post=None, sleep=time.sleep, now=time.time):
        if not valid(topic, token):
            raise ValueError("ntfy topic or token not usable")
        self._topic, self._token = topic, token
        self.url = f"{HOST}/{topic}"
        self.origin = origin or ""
        self.log = log or (lambda *a: None)
        if post is None:  # the real requests.post: urllib3 must not log the topic (a test's stub logs nothing)
            hide(topic, token)
        self._post = post or requests.post
        self.sleep, self.now = sleep, now
        self.sent = {}  # (kind, id) -> time
        self.times = collections.deque()
        self.q = None
        self.lock = threading.Lock()

    def scrub(self, text):
        s = str(text)
        for secret in (self._token, self._topic):
            s = s.replace(secret, "<hidden>")
        return s

    def headers(self, rec):
        h = {"Title": _ascii(rec.get("title"), 120) or "Flight Watcher",
             "Priority": str(int(rec.get("priority") or 3)),
             "Authorization": f"Bearer {self._token}"}
        if rec.get("tags"):
            h["Tags"] = _ascii(rec["tags"], 60)
        if self.origin and rec.get("view"):
            h["Click"] = f"{self.origin}/fw/#{_ascii(rec['view'], 20)}"
        return h

    def send(self, rec):
        """'sent', 'duplicate', 'capped' or 'failed'."""
        kind, eid = str(rec.get("kind") or ""), str(rec.get("id") or "")
        now = self.now()
        with self.lock:
            self.sent = {k: t for k, t in self.sent.items() if now - t < DEDUPE_S}
            if (kind, eid) in self.sent:
                return "duplicate"
            while self.times and now - self.times[0] >= 3600:
                self.times.popleft()
            if len(self.times) >= PER_HOUR:
                self.log("ntfy: %s not sent: %d pushes this hour already" % (kind, PER_HOUR))
                return "capped"
            self.sent[(kind, eid)] = now
            self.times.append(now)
        body = str(rec.get("body") or rec.get("title") or "").encode("utf-8")
        why = ""
        for i in range(RETRIES):
            try:
                r = self._post(self.url, data=body, headers=self.headers(rec), timeout=TIMEOUT_S)
                code = getattr(r, "status_code", 0)
                if 200 <= code < 300:
                    self.log("ntfy: %s sent (%d)" % (kind, code))
                    return "sent"
                why = f"HTTP {code}"
                if code < 500 and code != 429:
                    break
            except Exception as e:  # noqa: BLE001 (any network error: the type only, never its text)
                why = type(e).__name__
            if i < RETRIES - 1:
                self.sleep(BACKOFF_S[i])
        self.log(self.scrub("ntfy: %s not sent (%s)" % (kind, why)))
        return "failed"

    def enqueue(self, rec):
        with self.lock:
            if self.q is None:
                self.q = queue.Queue(maxsize=200)
                threading.Thread(target=self._worker, daemon=True, name="ntfy").start()
        try:
            self.q.put_nowait(dict(rec))
        except queue.Full:
            self.log("ntfy: queue full, %s not sent" % rec.get("kind"))

    def _worker(self):
        while True:
            rec = self.q.get()
            try:
                self.send(rec)
            except Exception as e:  # noqa: BLE001
                self.log("ntfy: send failed (%s)" % type(e).__name__)
