"""1.6.2 (Release A): the host-wide FLICA gate and the read-path circuit breakers.

Every Watcher process in the container (the admin's and each pilot's) loads FLICA through one Gate on one file both
reach (/data/flica_gate.lock: the admin's data folder, the parent of every pilot's). Before each FLICA page load the
Gate takes an exclusive fcntl lock on that file, reads the rolling-hour log of loads it holds (time and instance of
each), and lets the load go only when:
  - this Watcher's previous load was at least uniform(1.5, 3.5) s ago (the house pacing rule),
  - the host's previous load, whichever Watcher made it, was at least HOST_GAP_S (1.5 s) ago,
  - the host made fewer than HOST_CAP_H (480) loads in the last hour (all Watchers),
  - a pilot instance made fewer than its own budget (PILOT_BUDGET_H, 100) in the last hour: a token comes back one
    hour after the load that used it (a token bucket of 100 that refills by the rolling hour).
Otherwise it waits (in chunks of at most WAIT_CHUNK_S, reading the file again each time); a load is never skipped.
A wait for a budget (not plain pacing) is told through on_wait, so the Watcher's state note says why the loop slowed.

Never a deadlock: the lock is held only for the read and write of the small file (never during a wait or a load); it
is taken with LOCK_NB in a bounded loop (LOCK_TRIES x LOCK_POLL_S, about 10 s), and when it cannot be had (or the file
cannot be opened) the load goes by this Watcher's own pacing and budget only, logged at most every BUSY_LOG_S. flock
locks belong to the open file: a Watcher that dies releases its lock at once. An unreadable file is read as empty, and
a log time in the future (the clock went back) is dropped, so a stale file can never hold a load back for good.

Breakers: each FLICA read path (the mobile schedule, Schedule Lookup, pairing pages, the Tradeboard...) has one.
A CAPTCHA or interstitial page stops the path for 6 h; a page its parser does not know stops it for 30 min; 3 failed
reads in a row stop it for 30 min. Each stop after the first with no good read between doubles, up to 6 h. A stopped
path loads nothing (Flica raises BreakerOpen before the load); one log line and the state note say so. The open time
pot itself has no breaker here: it keeps its own stop rules (watcher.check)."""
import fcntl
import json
import os
import random
import time

PACE_MIN_S, PACE_MAX_S = 1.5, 3.5
HOST_GAP_S = 1.5
HOST_CAP_H = 480
PILOT_BUDGET_H = 100
WINDOW_S = 3600
FUTURE_SLACK_S = 5.0
LOCK_POLL_S = 0.05
LOCK_TRIES = 200
WAIT_CHUNK_S = 5.0
NOTE_AFTER_S = 5.0
BUSY_LOG_S = 600
MAX_ROUNDS = 200000  # a guard only: 5 s chunks are about 11 days


class Gate:
    def __init__(self, path, who, budget=None, cap=HOST_CAP_H, clock=None, sleep=None, rand=None, log=None,
                 on_wait=None):
        self.path, self.who, self.budget, self.cap = path, who or "admin", budget, cap
        self.clock = clock or (lambda: time.time())
        self.sleep = sleep or (lambda s: time.sleep(s))
        self.rand = rand or (lambda: random.uniform(PACE_MIN_S, PACE_MAX_S))
        self.log = log
        self.on_wait = on_wait
        self.local = []  # this Watcher's own loads in the last hour (used when the file cannot be locked)
        self.last_own = 0.0
        self.busy_at = 0.0
        self.waited = {"pace": 0.0, "host": 0.0, "budget": 0.0}

    # ---- the file
    def _say(self, msg, *a):
        if self.log:
            self.log.info(msg, *a)

    def _busy(self, why):
        now = self.clock()
        if now - self.busy_at >= BUSY_LOG_S:
            self.busy_at = now
            self._say("FLICA gate: %s; this load is paced by this Watcher only", why)

    def _locked(self, fn):
        """fn(data) -> (result, new data or None) under the exclusive lock; None when the lock cannot be had."""
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        except OSError as e:
            self._busy(f"file not opened ({type(e).__name__})")
            return None
        try:
            for _ in range(LOCK_TRIES):
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    time.sleep(LOCK_POLL_S)
                except OSError as e:
                    self._busy(f"lock failed ({type(e).__name__})")
                    return None
            else:
                self._busy(f"lock held elsewhere for over {LOCK_TRIES * LOCK_POLL_S:.0f} s")
                return None
            try:
                raw = b""
                while True:
                    chunk = os.pread(fd, 65536, len(raw))
                    if not chunk:
                        break
                    raw += chunk
                try:
                    data = json.loads(raw.decode() or "{}")
                    if not isinstance(data, dict):
                        data = {}
                except ValueError:
                    data = {}
                res, new = fn(data)
                if new is not None:
                    body = json.dumps(new, separators=(",", ":")).encode()
                    os.ftruncate(fd, 0)
                    os.pwrite(fd, body, 0)
                return res
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError as e:
            self._busy(f"file error ({type(e).__name__})")
            return None
        finally:
            os.close(fd)

    @staticmethod
    def _entries(data, now):
        out = []
        for e in data.get("log") or []:
            try:
                t, w = float(e[0]), str(e[1])
            except (TypeError, ValueError, IndexError):
                continue
            if now - WINDOW_S < t <= now + FUTURE_SLACK_S:
                out.append((t, w))
        out.sort()
        return out

    def _need(self, log, own, now, pace):
        """(seconds to wait, why) for a load now: why is 'pace', 'host' or 'budget'; 0 when it may go."""
        waits = [(max(own[-1:] + [self.last_own]) + pace - now, "pace")]
        if log:
            waits.append((log[-1][0] + HOST_GAP_S - now, "pace"))
        if self.cap and len(log) >= self.cap:
            waits.append((log[len(log) - self.cap][0] + WINDOW_S - now, "host"))
        if self.budget and len(own) >= self.budget:
            waits.append((own[len(own) - self.budget] + WINDOW_S - now, "budget"))
        w, why = max(waits)
        return (w, why) if w > 0 else (0.0, "")

    def _try(self, data, now, pace, take=True):
        log = self._entries(data, now)
        own = [t for t, w in log if w == self.who]
        w, why = self._need(log, own, now, pace)
        if w > 0 or not take:
            return (w, why, len(log), len(own)), None
        log.append((now, self.who))
        return (0.0, "", len(log), len(own) + 1), {"v": 1, "last": now, "log": [[round(t, 3), x] for t, x in log]}

    def _try_local(self, now, pace, take=True):
        self.local = [t for t in self.local if now - WINDOW_S < t <= now + FUTURE_SLACK_S]
        w, why = self._need([], sorted(self.local), now, pace)
        if w > 0 or not take:
            return w, why, len(self.local), len(self.local)
        return 0.0, "", len(self.local) + 1, len(self.local) + 1

    # ---- the API
    def acquire(self):
        """Wait until one FLICA load may go, record it and return the seconds waited."""
        pace = self.rand()
        start = self.clock()
        noted = False
        for _ in range(MAX_ROUNDS):
            now = self.clock()
            res = self._locked(lambda d: self._try(d, now, pace))
            if res is None:
                res = self._try_local(now, pace)
            w, why = res[0], res[1]
            if w <= 0:
                self.last_own = now
                self.local = [t for t in self.local if now - t < WINDOW_S] + [now]
                break
            if why in ("host", "budget") and w > NOTE_AFTER_S and self.on_wait and not noted:
                noted = True
                self.on_wait(why, now + w)
            step = min(w, WAIT_CHUNK_S)
            self.waited[why] = self.waited.get(why, 0.0) + step
            self.sleep(step)
        if noted and self.on_wait:
            self.on_wait("", None)
        return self.clock() - start

    def free_in(self, want=1):
        """Seconds until `want` loads would fit this Watcher's budget and the host cap (pacing left out), 0 when they
        fit now. Nothing is recorded. The main loop waits this out (WAKE-able) before a check, with the state note."""
        now = self.clock()

        def look(data):
            log = self._entries(data, now)
            own = [t for t, w in log if w == self.who]
            return (log, own), None
        res = self._locked(look)
        log, own = res if res is not None else ([], sorted(self.local))
        waits = [(0.0, "")]
        for lim, times, why in ((self.cap, [t for t, _ in log], "host"), (self.budget, own, "budget")):
            n = min(want, lim or 0)
            if lim and times and len(times) + n > lim:  # the (len + n - lim)th oldest must leave the hour first
                waits.append((times[len(times) + n - lim - 1] + WINDOW_S - now, why))
        w, why = max(waits)
        return (w, why) if w > 0 else (0.0, "")

    def counts(self):
        """{host, own, budget, cap}: loads in the last hour from the host and from this Watcher."""
        now = self.clock()
        res = self._locked(lambda d: ((len(self._entries(d, now)),
                                       sum(1 for _, w in self._entries(d, now) if w == self.who)), None))
        host, own = res if res is not None else (len(self.local), len(self.local))
        return {"host": host, "own": own, "budget": self.budget, "cap": self.cap}


# ---------------------------------------------------------------- breakers
BRK_FIRST_S = 30 * 60
BRK_MAX_S = 6 * 3600
BRK_CAPTCHA_S = 6 * 3600
BRK_FAILS = 3


class BreakerOpen(Exception):
    """A FLICA load refused because its read path is stopped (never reaches FLICA)."""

    def __init__(self, path, until):
        super().__init__(f"FLICA {path} read stopped until {until}")
        self.path = path


class Breakers:
    """Per read path: {open_until, trips, fails, why, kind}. state() returns the dict kept in the Watcher's state (so a
    stop outlives a restart), save() stores it. fmt(ts) gives the HST clock time for the log and the note."""

    def __init__(self, state, save=None, clock=None, log=None, fmt=None, on_change=None):
        self.state, self.save = state, save or (lambda: None)
        self.clock = clock or (lambda: time.time())
        self.log, self.fmt, self.on_change = log, fmt or (lambda ts: str(int(ts))), on_change

    def _rec(self, path):
        return self.state().setdefault(path, {"open_until": 0, "trips": 0, "fails": 0})

    def allow(self, path):
        r = self.state().get(path)
        return not r or self.clock() >= float(r.get("open_until") or 0)

    def until(self, path):
        r = self.state().get(path) or {}
        return float(r.get("open_until") or 0)

    def ok(self, path):
        r = self.state().get(path)
        if not r or not (r.get("trips") or r.get("fails")):
            return
        was = r.get("trips")
        self.state()[path] = {"open_until": 0, "trips": 0, "fails": 0}
        if was and self.log:
            self.log.info("FLICA %s read works again: breaker closed", path)
        self.save()
        if was and self.on_change:
            self.on_change()

    def fail(self, path, why, kind="error"):
        """Record a failed read of path. kind 'captcha' (6 h), 'unknown' (a page the parser does not know: stops now)
        or 'error' (stops on the BRK_FAILS-th in a row, or at once after an earlier stop with no good read between).
        Returns True when this failure stopped the path."""
        r = self._rec(path)
        now = self.clock()
        r["fails"] = int(r.get("fails") or 0) + 1
        trip = kind in ("captcha", "unknown") or r["fails"] >= BRK_FAILS or int(r.get("trips") or 0) > 0
        if not trip:
            self.save()
            return False
        r["trips"] = int(r.get("trips") or 0) + 1
        dur = BRK_CAPTCHA_S if kind == "captcha" else min(BRK_MAX_S, BRK_FIRST_S * 2 ** (r["trips"] - 1))
        r.update(open_until=now + dur, fails=0, why=str(why)[:160], kind=kind)
        if self.log:
            self.log.info("FLICA %s read stopped for %s (until %s): %s", path, _dur(dur), self.fmt(now + dur), r["why"])
        self.save()
        if self.on_change:
            self.on_change()
        return True

    def open_paths(self):
        now = self.clock()
        return {p: r for p, r in self.state().items() if float(r.get("open_until") or 0) > now}

    def note(self):
        """The state note for every stopped path ('' when none)."""
        parts = []
        for p, r in sorted(self.open_paths().items()):
            what = "a CAPTCHA page (never answered)" if r.get("kind") == "captcha" else r.get("why") or "failed reads"
            parts.append(f"FLICA {p} read paused until {self.fmt(r['open_until'])} HST: {what}")
        return "; ".join(parts)


def _dur(s):
    s = int(round(s))
    return f"{s // 3600} h" if s % 3600 == 0 else f"{s // 60} min"


# FLICA URL -> read path (the breaker's key). 'pot' (the open time pages, the close-in folder too) has no breaker.
PATHS = (("mobileopentimepot.cgi", "pot"), ("mobileschedule.cgi", "schedule"), ("scheduledetail.cgi", "schedule_detail"),
         ("cmschedules.cgi", "lookup"), ("mobilepairing.cgi", "pairing"), ("mobileotrequest.cgi", "requests"),
         ("tb_", "tradeboard"), ("leftmenu.cgi", "menu"), ("mainmenu.cgi", "menu"), ("reservegrid", "grid"),
         ("bidclosereservegrid", "grid"))


def read_path(url):
    u = (url or "").lower().split("#")[0]
    for frag, path in PATHS:
        if frag in u:
            return path
    return "other"
