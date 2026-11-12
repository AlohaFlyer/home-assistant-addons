"""ntfy pushes for a pilot's portal (1.6.0, FW-0061; 1.6.2 topic-only, Ryan 2026-11-10).

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

1.6.2 (Release A item 9, Ryan's decision): the access token is optional. With a topic only, anyone who learns the topic
can read the pilot's alerts on ntfy.sh (it keeps them about 12 h), so: the topic must be hard to guess (topic_refusal:
at least 24 characters with both letters and digits; the Settings card generates a 32-character random one), and a
topic-only push carries only the pairing number, the date and the fit (plain_text): no crew name, employee number,
URL (no Click header either), ticket text, report times or rule ids. With a token the 1.6.0 push is unchanged.

1.7.0 (Release C): the ticket_fixed alert (the pilot's own ticket moved to fixed) carries only the ticket id(s) and the
version, with a token or without (plain_text); never a ticket's title or text. Priority 2 (quiet).

1.7.2 (contract 1 revision 3): the bid calendar alert carries the admin's push words (only dates and what to do,
bidcal.alert_text from its own fields, each in its own shape), and a schedule not read says for how long (a whole number
of hours); with a token or without. Never a ticket's or a crew member's text.
"""
import collections
import logging
import queue
import re
import threading
import time
import unicodedata

import requests

import bidcal

HOST = "https://ntfy.sh"
TOPIC_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
TOKEN_RE = re.compile(r"^[A-Za-z0-9_.-]{8,128}$")
TOPIC_MIN = 24  # 1.6.2: a topic anyone could read if they guess it: long and mixed (the card makes 32 random)
GEN_LEN = 32
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


def topic_refusal(topic):
    """Why a topic may not be used ('' when it may): ntfy's characters (A-Z a-z 0-9 _ -, at most 64, so it can never
    change the host or the path), and 1.6.2: at least TOPIC_MIN characters with both letters and digits."""
    if not isinstance(topic, str) or not TOPIC_RE.fullmatch(topic):
        return "use only letters, digits, - and _ (at most 64)"
    if len(topic) < TOPIC_MIN or not re.search(r"[A-Za-z]", topic) or not re.search(r"\d", topic):
        return f"use at least {TOPIC_MIN} characters with both letters and digits (or Generate one)"
    return ""


def token_ok(token):
    """1.6.2: the token is optional: none ('' or None) or one of TOKEN_RE."""
    return token in (None, "") or bool(isinstance(token, str) and TOKEN_RE.fullmatch(token))


def valid(topic, token=None):
    return not topic_refusal(topic) and token_ok(token)


# 1.6.2: what a topic-only push may say: the kind in words, the pairing number, the date and the fit, nothing else
KIND_WORDS = {"new_pairing": "New pairing", "rule_match": "Rule match", "recall_miss": "Recall/O75 to check",
              "request_decided": "Request decided", "schedule_changed": "Schedule changed", "charter": "Charter",
              "hidden": "Hidden trip?", "needs_settings": "Flight Watcher needs your FLICA login",
              "stopped_*": "Flight Watcher stopped", "ticket_fixed": "Ticket fixed", "bid_calendar": "Bid calendar",
              "schedule_unread": "Schedule not read"}
TICKET_RE = re.compile(r"^FW-\d{4,6}$")
VERSION_RE = re.compile(r"^\d{1,3}(?:\.\d{1,4}){1,3}$")
PAIRING_RE = re.compile(r"^[A-Z]\d{4}[A-Z]?$")
WHEN_RE = re.compile(r"^(?:\d{4}-\d{2}(?:-\d{2})?|\d{1,2}[A-Z]{3}(?:-\d{1,2}[A-Z]{3})?|[A-Z][a-z]{2} \d{1,2})$")
FIT_RE = re.compile(r"^(?:Fits|Conflict|Check rest|Days off)(?: [A-Za-z0-9()+/.,:-]{1,24}){0,3}$")  # pot.fit_tag


def plain_text(rec):
    """(title, body) of a topic-only push from the event record's data: the kind in words, the pairing number (H1234),
    the date and the fit, each only when it has its own shape (a name, a number or a URL never matches)."""
    d = rec.get("data") if isinstance(rec.get("data"), dict) else {}
    kind = str(rec.get("kind") or "")
    if kind == "ticket_fixed":  # 1.7.0: the ticket ids (FW-nnnn) and the version, each only in its own shape
        t = d.get("ticket")
        ids = [x for x in (t if isinstance(t, list) else [t]) if isinstance(x, str) and TICKET_RE.fullmatch(x)][:5]
        ver = str(d.get("version") or "")
        title = " ".join(x for x in ("Ticket", ", ".join(ids), "fixed", f"in {ver}" if VERSION_RE.fullmatch(ver)
                                      else "") if x)
        return title, "Open the Tickets tab of your Flight Watcher portal to check it."
    if kind == "bid_calendar":  # 1.7.2: the admin's push words, rebuilt from the alert's own fields (dates only)
        return bidcal.alert_text(d) or ("Bid calendar", "Open your Flight Watcher portal for the bid calendar.")
    if kind == "schedule_unread":  # 1.7.2: a whole number of hours, nothing else
        h = d.get("hours")
        ok = isinstance(h, int) and not isinstance(h, bool) and 0 < h < 10000
        return (f"Schedule not read for {h} h" if ok else "Schedule not read",
                "Open the Schedule tab of your Flight Watcher portal to see why.")
    pid = str(d.get("pairing") or "")
    when = next((str(d[k]) for k in ("dates", "start", "date", "month") if WHEN_RE.fullmatch(str(d.get(k) or ""))), "")
    fit = str(d.get("fit") or "")
    title = " ".join(x for x in (KIND_WORDS.get(kind, "Flight Watcher"), pid if PAIRING_RE.fullmatch(pid) else "",
                                 when) if x)
    body = f"Fit: {fit}" if FIT_RE.fullmatch(fit) else "Open your Flight Watcher portal for the details."
    return title, body


def _ascii(s, n):
    """Header-safe text: ASCII only (accents folded), no CR / LF, at most n characters."""
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode("ascii")
    return " ".join(s.split())[:n]


class Ntfy:
    """One pilot's ntfy sender. send(rec) posts one portal event record synchronously (tests); enqueue(rec) hands it
    to a worker thread so the Watcher's loop never waits on ntfy.sh."""

    def __init__(self, topic, token="", origin="", log=None, post=None, sleep=time.sleep, now=time.time):
        if not valid(topic, token):
            raise ValueError("ntfy topic or token not usable")
        self._topic, self._token = topic, token or ""
        self.url = f"{HOST}/{topic}"
        self.origin = (origin or "") if self._token else ""  # 1.6.2: a topic-only push carries no URL (no Click)
        self.log = log or (lambda *a: None)
        if post is None:  # the real requests.post: urllib3 must not log the topic (a test's stub logs nothing)
            hide(topic, self._token)
        self._post = post or requests.post
        self.sleep, self.now = sleep, now
        self.sent = {}  # (kind, id) -> time
        self.times = collections.deque()
        self.q = None
        self.lock = threading.Lock()

    def scrub(self, text):
        s = str(text)
        for secret in (self._token, self._topic):
            if secret:
                s = s.replace(secret, "<hidden>")
        return s

    def text(self, rec):
        """(title, body) as pushed: the event's own with a token (1.6.0), plain_text with a topic only (1.6.2)."""
        if self._token:
            return rec.get("title"), rec.get("body") or rec.get("title")
        return plain_text(rec)

    def headers(self, rec):
        h = {"Title": _ascii(self.text(rec)[0], 120) or "Flight Watcher",
             "Priority": str(int(rec.get("priority") or 3))}
        if self._token:
            h["Authorization"] = f"Bearer {self._token}"
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
        body = str(self.text(rec)[1] or "").encode("utf-8")
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
