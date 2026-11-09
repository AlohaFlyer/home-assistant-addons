"""SQLite store: watcher state, finds history, rule matches, per-rule live flags.

Replaces state.json (v0.1.x). Every write is one transaction, so a crash mid-write
leaves the previous state intact. The old state.json is imported once and renamed.
"""
import json
import os
import re
import sqlite3
import threading
from datetime import datetime, timedelta, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS finds (
  key TEXT PRIMARY KEY, pairing TEXT, month TEXT, row TEXT NOT NULL,
  first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, gone_at TEXT);
CREATE INDEX IF NOT EXISTS finds_seen ON finds(first_seen);
CREATE TABLE IF NOT EXISTS matches (
  id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, rule_id TEXT NOT NULL, find_key TEXT,
  dry_run INTEGER, would_submit INTEGER, reason TEXT, row TEXT);
CREATE INDEX IF NOT EXISTS matches_at ON matches(at);
CREATE TABLE IF NOT EXISTS submissions (
  id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, rule_id TEXT, find_key TEXT,
  kind TEXT, result TEXT, page TEXT);
CREATE TABLE IF NOT EXISTS rule_live (rule_id TEXT PRIMARY KEY, live INTEGER NOT NULL, changed_at TEXT);
CREATE TABLE IF NOT EXISTS pickers (
  emp TEXT PRIMARY KEY, name TEXT, pos TEXT, n INTEGER NOT NULL DEFAULT 0, total_s INTEGER NOT NULL DEFAULT 0, last_at TEXT);
CREATE TABLE IF NOT EXISTS picker_log (
  key TEXT PRIMARY KEY, emp TEXT NOT NULL, at TEXT NOT NULL, secs INTEGER, approx INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS picker_log_emp ON picker_log(emp, at);
CREATE TABLE IF NOT EXISTS crew_dir (
  emp TEXT PRIMARY KEY, name TEXT NOT NULL, pos TEXT, seen_at TEXT);
CREATE TABLE IF NOT EXISTS crew_idx (
  key TEXT PRIMARY KEY, pairing TEXT NOT NULL, date TEXT NOT NULL, end_date TEXT, route TEXT, crew TEXT,
  checked_at TEXT, status TEXT, reason TEXT, tries INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS crew_idx_date ON crew_idx(date);
CREATE TABLE IF NOT EXISTS crew_emp (
  emp TEXT NOT NULL, key TEXT NOT NULL, pos TEXT, name TEXT, PRIMARY KEY(emp, key));
CREATE INDEX IF NOT EXISTS crew_emp_key ON crew_emp(key);
"""
HST = timezone(timedelta(hours=-10))
LOG_KEEP_DAYS = 731  # 0.9.4: 24 months (Ryan); 0.5.6: per-pickup log for month / year counts outlives the 90-day finds history
EMP_RE = re.compile(r"\((\d{3,7})\)\s*$")


def dwell(first, last, gone, alert=None):
    """(seconds, plus_minus) the trip sat in open time. 0.7.6 (Ryan: vet Pickup Speed): it entered the pot
    at FLICA's alert time when that is earlier than the Watcher's first sighting; it was picked up some
    time after the last check that still listed it and by the check that found it gone, so the estimate
    is the middle of that window and plus_minus is half the window. None when gone is unknown."""
    if not gone:
        return None, None
    try:
        f, g = datetime.fromisoformat(first), datetime.fromisoformat(gone)
        l = datetime.fromisoformat(last) if last else f
        entry = min(f, datetime.fromisoformat(alert)) if alert else f
    except (TypeError, ValueError):
        return None, None
    lo, hi = max(l, entry), max(g, entry)
    mid = lo + (hi - lo) / 2
    return max(0, int((mid - entry).total_seconds())), int((hi - lo).total_seconds() / 2)


def lay_of(row):
    """'LAX' from a find row: its layover, else its turn station (PPG), else ''."""
    lay = (row or {}).get("layover") or ""
    if lay.strip().lower() in ("", "-", "-none-", "none"):
        lay = (row or {}).get("turn") or ""
    return lay.strip().upper()


def picker_of(by):
    """('FO', 'Lane Jr, Chris', '10007') from 'FO Lane Jr, Chris (10007)'; None without a number."""
    m = EMP_RE.search(by or "")
    if not m:
        return None
    head = by[:m.start()].strip()
    pos, _, name = head.partition(" ")
    return pos.upper(), name.strip(), m.group(1)


def fmt_dur(sec):
    """'2m 17s', '42s', '1h 05m' for the finds table."""
    sec = int(round(sec))
    if sec >= 3600:
        return f"{sec // 3600}h {(sec % 3600) // 60:02d}m"
    if sec >= 60:
        return f"{sec // 60}m {sec % 60:02d}s"
    return f"{sec}s"
KEEP_DAYS = 731  # 0.9.4 (Ryan): finds, matches and submissions kept 24 months


def is_prem(row):
    """Premium pairing: FLICA marks the Prem column with an X (mobile cell x1)."""
    return any(str(row.get(k) or "").strip().upper() == "X" for k in ("x1", "prem"))


FIND_SMART = ("comm", "comm_why", "value", "month_rule")  # FW-0042 (watcher.SMART_FIELDS)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path, legacy_json=None, default_state=None):
        self.lock = threading.Lock()
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)
        try:  # 0.3.7: who picked up the open seat once a find leaves the pot (JSON)
            self.db.execute("ALTER TABLE finds ADD COLUMN pickup TEXT")
        except sqlite3.OperationalError:
            pass
        try:  # 0.7.6 (Ryan): the layover (or turn station) of each scored pickup, for Common Layover
            self.db.execute("ALTER TABLE picker_log ADD COLUMN lay TEXT")
        except sqlite3.OperationalError:
            pass
        try:  # 0.7.6 (Ryan): when FLICA's alert email for the find was sent (the true pot-entry time)
            self.db.execute("ALTER TABLE finds ADD COLUMN alert_at TEXT")
        except sqlite3.OperationalError:
            pass
        self.default_state = default_state or {}
        self._backfill_picker_log()
        if legacy_json and os.path.exists(legacy_json) and self.get("state") is None:
            try:
                self.put("state", json.load(open(legacy_json)))
                os.replace(legacy_json, legacy_json + ".imported")
            except Exception:
                pass

    # ---- kv
    def get(self, k, default=None):
        with self.lock:
            r = self.db.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
        return json.loads(r[0]) if r else default

    def put(self, k, v):
        with self.lock:
            self.db.execute("INSERT INTO kv(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                            (k, json.dumps(v)))

    def load_state(self):
        s = self.get("state")
        return s if isinstance(s, dict) else json.loads(json.dumps(self.default_state))

    def save_state(self, s):
        self.put("state", s)

    # ---- finds
    def record_pot(self, month, pot, new_keys):
        """Upsert every row seen; stamp gone_at on rows no longer in this month's pot."""
        t = now_iso()
        with self.lock:
            self.db.execute("BEGIN")
            for k, row in pot.items():
                if k in new_keys:
                    self.db.execute(
                        "INSERT INTO finds(key,pairing,month,row,first_seen,last_seen) VALUES(?,?,?,?,?,?) "
                        "ON CONFLICT(key) DO UPDATE SET first_seen=excluded.first_seen, "
                        "last_seen=excluded.last_seen, gone_at=NULL, "
                        "row=excluded.row", (k, row.get("pairing"), month, json.dumps(row), t, t))
                else:  # keep the stored row current (CA, details, fit) while it is still in the pot
                    self.db.execute("UPDATE finds SET last_seen=?, gone_at=NULL, row=? WHERE key=?",
                                    (t, json.dumps(row), k))
            keys = list(pot.keys())
            q = ",".join("?" * len(keys)) or "''"
            self.db.execute(f"UPDATE finds SET gone_at=? WHERE month=? AND gone_at IS NULL "
                            f"AND key NOT IN ({q})", (t, month, *keys))
            self.db.execute("COMMIT")

    def move_finds(self, keys, month):
        """FW-0034: finds that moved to another folder (a trip FLICA moves from the regular pot to the close-in one)
        belong to that folder's month key from now on, so the regular pot's next read does not stamp them gone; their
        first_seen (pickup speed) is kept."""
        keys = sorted(keys or ())
        if not keys:
            return
        with self.lock:
            q = ",".join("?" * len(keys))
            self.db.execute(f"UPDATE finds SET month=?, gone_at=NULL WHERE key IN ({q})", (month, *keys))

    def recent_finds(self, n=50):
        with self.lock:
            rows = self.db.execute("SELECT key,row,month,first_seen,gone_at,pickup,last_seen,alert_at FROM finds "
                                   "ORDER BY first_seen DESC LIMIT ?", (n,)).fetchall()
        return self._find_rows(rows)

    def finds_between(self, start_iso, end_iso):
        """0.9.4 (Ryan): every find first seen in [start, end), newest first, for the month picker."""
        with self.lock:
            rows = self.db.execute("SELECT key,row,month,first_seen,gone_at,pickup,last_seen,alert_at FROM finds "
                                   "WHERE first_seen>=? AND first_seen<? ORDER BY first_seen DESC", (start_iso, end_iso)).fetchall()
        return self._find_rows(rows)

    def _find_rows(self, rows):
        out = []
        stats = self.picker_stats()
        for key, row, month, first, gone, pickup, last, alert in rows:
            r = json.loads(row)
            pk = json.loads(pickup) if pickup else {}
            who = picker_of(pk.get("by", ""))
            st = stats.get(who[2]) if who else None
            secs, pm = dwell(first, last, gone, alert)
            out.append({"pairing": r.get("pairing"), "dates": r.get("dates"), "days": r.get("days"),
                        "dwell_s": secs, "dwell_pm_s": pm, "alert_at": alert or "",
                        "picker_emp": who[2] if who else "", "picker_n": st["n"] if st else 0,
                        "picker_avg_s": int(st["total_s"] / st["n"]) if st and st["n"] else None,
                        "layover": r.get("layover"), "report": r.get("report"), "credit": r.get("credit"),
                        "turn": r.get("turn"), "captain": pk.get("ca") or r.get("captain") or "",
                        "prem": is_prem(r), "picked_by": pk.get("by", ""), "source": r.get("source", "pot"), "pickup_status": pk.get("status", ""), "pickup_known": bool(pk.get("known")),
                        "inflt": pk.get("inflt"), "inflt_trip": pk.get("inflt_trip", ""), "picker_approx": bool(pk.get("approx")),
                        "month": month, "seen": first, "gone": gone,
                        # FW-0042: the smart push fields as the row last had them in the pot ('' before 1.4.13 or
                        # without smart.json)
                        **{k: r.get(k, "") for k in FIND_SMART}})
        return out

    # ---- pickers (0.4.18, Ryan): how fast each FO/RO grabs a trip = seconds the find sat in open time
    def _backfill_picker_log(self):
        """0.5.6: one row per scored pickup (emp, when it left the pot) so month and year counts survive
        the 90-day finds history. Idempotent; fills the log from already scored finds on every start."""
        with self.lock:
            rows = self.db.execute("SELECT key,gone_at,pickup,row FROM finds WHERE pickup IS NOT NULL AND gone_at IS NOT NULL").fetchall()
            for k, gone, pk, row in rows:
                pk = json.loads(pk)
                who = picker_of(pk.get("by", "")) if pk.get("scored") is not None else None
                if who:
                    lay = lay_of(json.loads(row) if row else {})
                    self.db.execute("INSERT OR IGNORE INTO picker_log(key,emp,at,secs,approx,lay) VALUES(?,?,?,?,?,?)",
                                    (k, who[2], gone, pk.get("scored"), int(bool(pk.get("approx"))), lay))
                    self.db.execute("UPDATE picker_log SET lay=? WHERE key=? AND (lay IS NULL OR lay='')", (lay, k))

    def picker_stats(self, now=None):
        """{emp: {name, pos, n, total_s, last_at, inflt_n, month_n, year_n, lays, last_lay}}; month and
        year are the current HST month and year, counted from picker_log. 0.7.6: lays = [[station, count]]
        most picked first (ties: most recent first); last_lay = the most recent pickup's layover."""
        now = now or datetime.now(HST)
        ym, y = now.strftime("%Y-%m"), now.strftime("%Y")
        with self.lock:
            rows = self.db.execute("SELECT emp,name,pos,n,total_s,last_at FROM pickers").fetchall()
            pks = self.db.execute("SELECT pickup FROM finds WHERE pickup IS NOT NULL").fetchall()
            logs = self.db.execute("SELECT emp,at,lay FROM picker_log ORDER BY at").fetchall()
            mins = dict(self.db.execute("SELECT emp,MIN(secs) FROM picker_log WHERE secs IS NOT NULL GROUP BY emp").fetchall())
        out = {e: {"name": nm, "pos": ps, "n": n, "total_s": t, "last_at": la, "inflt_n": 0, "month_n": 0, "year_n": 0,
                   "lays": [], "last_lay": "", "min_s": mins.get(e)}  # 0.8.2 (Ryan): fastest pickup
               for e, nm, ps, n, t, la in rows}
        counts, latest = {}, {}
        for emp, at, lay in logs:
            if emp in out and lay:
                counts.setdefault(emp, {}).setdefault(lay, 0)
                counts[emp][lay] += 1
                latest.setdefault(emp, {})[lay] = at
                out[emp]["last_lay"] = lay
        for emp, c in counts.items():
            out[emp]["lays"] = [[l, n] for l, n in sorted(c.items(), key=lambda kv: (kv[1], latest[emp][kv[0]]), reverse=True)]
        for (pk,) in pks:  # 0.5.2: in-flight pickups per picker, counted from the finds
            pk = json.loads(pk)
            who = picker_of(pk.get("by", "")) if pk.get("inflt") is True else None
            if who and who[2] in out:
                out[who[2]]["inflt_n"] += 1
        for emp, at, _ in logs:
            if emp not in out:
                continue
            try:
                loc = datetime.fromisoformat(at).astimezone(HST)
            except ValueError:
                continue
            if loc.strftime("%Y") == y:
                out[emp]["year_n"] += 1
                if loc.strftime("%Y-%m") == ym:
                    out[emp]["month_n"] += 1
        return out

    def score_pickup(self, key):
        """Add this find's time in open time to its picker, once. Only when the seat was known (the
        name is certain), the find was seen in the pot (not email-caught: its dwell is unknown) and the
        picker has an employee number. Returns the seconds scored, or None."""
        with self.lock:
            r = self.db.execute("SELECT row,first_seen,gone_at,pickup,last_seen,alert_at FROM finds WHERE key=?", (key,)).fetchone()
            if not r:
                return None
            row, first, gone, pickup, last, alert = json.loads(r[0]), r[1], r[2], json.loads(r[3]) if r[3] else {}, r[4], r[5]
            if pickup.get("scored") or pickup.get("status") != "filled" or not gone:
                return None
            # 0.5.6 (Ryan: always complete the data): an email-caught find has no pot dwell, but the FLICA alert
            # is sent when the trip enters the pot, so alert time -> pickup check is a fair (upper-bound) dwell;
            # scored as approximate when exactly one FO/RO name was found.
            approx = row.get("source") == "email" or not pickup.get("known")
            if approx and ";" in (pickup.get("by") or ""):
                return None
            who = picker_of(pickup.get("by", ""))
            if not who:
                return None
            secs, _ = dwell(first, last, gone, alert)  # 0.7.6: alert time in, middle of the gone window out
            pos, name, emp = who
            self.db.execute("BEGIN")
            self.db.execute("INSERT INTO pickers(emp,name,pos,n,total_s,last_at) VALUES(?,?,?,1,?,?) "
                            "ON CONFLICT(emp) DO UPDATE SET name=excluded.name, pos=excluded.pos, "
                            "n=n+1, total_s=total_s+excluded.total_s, last_at=excluded.last_at",
                            (emp, name, pos, secs, gone))
            pickup["scored"] = secs
            if approx:
                pickup["approx"] = True
            self.db.execute("UPDATE finds SET pickup=? WHERE key=?", (json.dumps(pickup), key))
            self.db.execute("INSERT OR IGNORE INTO picker_log(key,emp,at,secs,approx,lay) VALUES(?,?,?,?,?,?)",
                            (key, emp, gone, secs, int(approx), lay_of(row)))
            self.db.execute("COMMIT")
            return secs

    # ---- crew directory (0.8.2, Ryan: look anybody up by name)
    def remember_crew(self, text):
        """Every 'POS emp Name' on a pairing page's crew line goes into crew_dir (newest position wins), without
        the CKP tag (FW-0017)."""
        from pot import CREW_RE, clean_name
        m = re.search(r"crew\s*:\s*(.*)$", text or "", re.I | re.S)
        if not m:
            return 0
        n, t = 0, datetime.now(timezone.utc).isoformat()
        with self.lock:
            for pos, emp, name in CREW_RE.findall(m.group(1)):
                name = clean_name(name)[0]
                if not emp or name.lower() == "open":
                    continue
                self.db.execute("INSERT INTO crew_dir(emp,name,pos,seen_at) VALUES(?,?,?,?) ON CONFLICT(emp) DO UPDATE SET "
                                "name=excluded.name, pos=excluded.pos, seen_at=excluded.seen_at", (emp, name.title(), pos.upper(), t))
                n += 1
        return n

    def remember_person(self, emp, name, pos=""):
        from pot import clean_name
        name = clean_name(name)[0]
        if not emp or not name:
            return
        with self.lock:
            self.db.execute("INSERT INTO crew_dir(emp,name,pos,seen_at) VALUES(?,?,?,?) ON CONFLICT(emp) DO UPDATE SET "
                            "name=excluded.name, pos=COALESCE(NULLIF(excluded.pos,''), pos)",
                            (str(emp), name, pos or "", datetime.now(timezone.utc).isoformat()))

    def find_crew(self, q):
        """[{emp, name, pos}] whose name contains every word of q (last, first, any order) or whose employee
        number starts with q. Exact employee numbers come first."""
        q = (q or "").strip().lower()
        if not q:
            return []
        with self.lock:
            rows = self.db.execute("SELECT emp,name,pos FROM crew_dir").fetchall()
        words = [w for w in re.split(r"[\s,]+", q) if w]
        out = []
        for emp, name, pos in rows:
            nm = (name or "").lower()
            if q.isdigit():
                if emp.startswith(q):
                    out.append({"emp": emp, "name": name, "pos": pos or ""})
            elif all(w in nm for w in words):
                out.append({"emp": emp, "name": name, "pos": pos or ""})
        out.sort(key=lambda r: (r["emp"] != q, r["name"]))
        return out[:20]

    def crew_count(self):
        with self.lock:
            return self.db.execute("SELECT COUNT(*) FROM crew_dir").fetchone()[0]

    def set_alert_at(self, key, at):
        """0.7.6: remember FLICA's alert time for a known find (earliest wins); a scored pickup is rescored."""
        with self.lock:
            r = self.db.execute("SELECT alert_at,pickup FROM finds WHERE key=?", (key,)).fetchone()
            if not r or (r[0] and r[0] <= at):
                return False
            self.db.execute("UPDATE finds SET alert_at=? WHERE key=?", (at, key))
        self.rescore_all([key])
        return True

    def rescore_all(self, keys=None):
        """0.7.6 (Ryan: vet Pickup Speed): recompute every scored pickup with dwell() and rebuild the
        pickers totals and picker_log seconds from them. Idempotent."""
        with self.lock:
            rows = self.db.execute("SELECT key,first_seen,last_seen,gone_at,alert_at,pickup FROM finds "
                                   "WHERE pickup IS NOT NULL AND gone_at IS NOT NULL").fetchall()
            self.db.execute("BEGIN")
            for k, first, last, gone, alert, pk in rows:
                pk = json.loads(pk)
                if pk.get("scored") is None or (keys and k not in keys):
                    continue
                secs, _ = dwell(first, last, gone, alert)
                if secs is None or secs == pk["scored"]:
                    continue
                pk["scored"] = secs
                self.db.execute("UPDATE finds SET pickup=? WHERE key=?", (json.dumps(pk), k))
                self.db.execute("UPDATE picker_log SET secs=? WHERE key=?", (secs, k))
            self.db.execute("UPDATE pickers SET total_s=(SELECT COALESCE(SUM(secs),0) FROM picker_log WHERE picker_log.emp=pickers.emp), "
                            "n=(SELECT COUNT(*) FROM picker_log WHERE picker_log.emp=pickers.emp)")
            self.db.execute("COMMIT")

    def unscored_pickups(self):
        with self.lock:
            rows = self.db.execute("SELECT key,pickup FROM finds WHERE pickup IS NOT NULL AND gone_at IS NOT NULL").fetchall()
        return [k for k, pk in rows if pk and not json.loads(pk).get("scored")]

    def has_find(self, key):
        with self.lock:
            return self.db.execute("SELECT 1 FROM finds WHERE key=?", (key,)).fetchone() is not None

    def add_find(self, key, month, row, seen, gone=None):
        """A find the pot watch missed (0.4.1: from a FLICA alert email). No-op if already known."""
        with self.lock:
            self.db.execute("INSERT OR IGNORE INTO finds(key,pairing,month,row,first_seen,last_seen,gone_at) "
                            "VALUES(?,?,?,?,?,?,?)", (key, row.get("pairing"), month, json.dumps(row),
                                                      seen, seen, gone))

    def email_unchanged(self):
        with self.lock:
            rows = self.db.execute("SELECT key,row,pickup FROM finds WHERE pickup IS NOT NULL").fetchall()
        return [k for k, r, p in rows
                if json.loads(r).get("source") == "email" and json.loads(p).get("status") == "unchanged"]

    def email_finds(self):
        with self.lock:
            rows = self.db.execute("SELECT key,row FROM finds").fetchall()
        return [k for k, r in rows if json.loads(r).get("source") == "email"]

    def patch_row(self, key, fields):
        if not fields:
            return
        with self.lock:
            r = self.db.execute("SELECT row FROM finds WHERE key=?", (key,)).fetchone()
            if r:
                row = dict(json.loads(r[0]), **fields)
                self.db.execute("UPDATE finds SET row=? WHERE key=?", (json.dumps(row), key))

    def clear_pickup(self, key):
        with self.lock:
            self.db.execute("UPDATE finds SET pickup=NULL, row=json_remove(row, '$.crew') WHERE key=?", (key,))

    def find_row(self, key):
        with self.lock:
            r = self.db.execute("SELECT row FROM finds WHERE key=?", (key,)).fetchone()
        return json.loads(r[0]) if r else None

    def set_pickup(self, key, pickup):
        with self.lock:
            old = self.db.execute("SELECT pickup FROM finds WHERE key=?", (key,)).fetchone()
            old = json.loads(old[0]) if old and old[0] else {}
            if old.get("scored") is not None and "scored" not in pickup:
                pickup = dict(pickup, scored=old["scored"])  # 0.4.21: a re-check never scores the picker twice
            if "inflt" in old and "inflt" not in pickup:  # 0.5.2: a re-check keeps the in-flight verdict
                pickup = dict(pickup, inflt=old["inflt"], inflt_trip=old.get("inflt_trip", ""), inflt_tries=old.get("inflt_tries", 0))
            self.db.execute("UPDATE finds SET pickup=? WHERE key=?", (json.dumps(pickup), key))

    def pickups_without_inflt(self, n=50, max_tries=3):
        """0.5.2 (Ryan): filled pickups with a known picker (employee number) and no in-flight verdict yet:
        [(key, emp, gone_at, tries)], newest first. A pickup that failed max_tries lookups is skipped."""
        with self.lock:
            rows = self.db.execute("SELECT key,pickup,gone_at FROM finds WHERE pickup IS NOT NULL AND gone_at IS NOT NULL "
                                   "ORDER BY first_seen DESC LIMIT ?", (n,)).fetchall()
        out = []
        for k, pk, gone in rows:
            pk = json.loads(pk) if pk else {}
            if pk.get("status") != "filled" or "inflt" in pk or pk.get("inflt_tries", 0) >= max_tries:
                continue
            who = picker_of(pk.get("by", ""))
            if who:
                out.append((k, who[2], gone, pk.get("inflt_tries", 0)))
        return out

    def set_inflt(self, key, inflt, trip="", tries=None):
        """Record the in-flight verdict (True / False / None = unknown after max tries) on the pickup."""
        with self.lock:
            r = self.db.execute("SELECT pickup FROM finds WHERE key=?", (key,)).fetchone()
            if not r or not r[0]:
                return
            pk = json.loads(r[0])
            if tries is not None:
                pk["inflt_tries"] = tries
                if inflt is None and tries < 3:
                    self.db.execute("UPDATE finds SET pickup=? WHERE key=?", (json.dumps(pk), key))
                    return
            pk["inflt"], pk["inflt_trip"] = inflt, trip
            self.db.execute("UPDATE finds SET pickup=? WHERE key=?", (json.dumps(pk), key))

    def reset_inflt(self, only=None):
        """0.5.3: drop every in-flight verdict so it is looked up again (0.5.2 judged forwarding pages).
        only=False (FW-0013) drops just the 'not in flight' verdicts and leaves the rest."""
        with self.lock:
            rows = self.db.execute("SELECT key,pickup FROM finds WHERE pickup IS NOT NULL").fetchall()
            for k, pk in rows:
                pk = json.loads(pk)
                if only is not None and ("inflt" not in pk or pk["inflt"] is not only):
                    continue
                if "inflt" in pk or "inflt_tries" in pk:
                    for f in ("inflt", "inflt_trip", "inflt_tries"):
                        pk.pop(f, None)
                    self.db.execute("UPDATE finds SET pickup=? WHERE key=?", (json.dumps(pk), k))

    def gone_without_pickup(self, n=50):
        with self.lock:
            return [k for (k,) in self.db.execute(
                "SELECT key FROM finds WHERE gone_at IS NOT NULL AND pickup IS NULL "
                "ORDER BY first_seen DESC LIMIT ?", (n,)).fetchall()]

    def pickups_without_ids(self, n=50):
        """0.4.17: finds whose pickup name or CA has no employee number yet (recorded before 0.4.11)."""
        with self.lock:
            rows = self.db.execute("SELECT key,pickup FROM finds WHERE pickup IS NOT NULL "
                                   "ORDER BY first_seen DESC LIMIT ?", (n,)).fetchall()
        out = []
        for k, pk in rows:
            pk = json.loads(pk) if pk else {}
            if pk.get("status") not in ("filled", "open", "unchanged"):
                continue
            by, ca = pk.get("by") or "", pk.get("ca") or ""
            if (by and "(" not in by) or (ca and "(" not in ca):
                out.append(k)
        return out

    # ---- matches
    def add_match(self, m, find_key):
        with self.lock:
            self.db.execute("INSERT INTO matches(at,rule_id,find_key,dry_run,would_submit,reason,row) "
                            "VALUES(?,?,?,?,?,?,?)",
                            (m["at"], m["rule_id"], find_key, int(m["dry_run"]), int(m["would_submit"]),
                             m["reason"], json.dumps(m["row"])))

    def would_submits_since(self, since_iso):
        with self.lock:
            rows = self.db.execute("SELECT rule_id, COUNT(*) FROM matches WHERE would_submit=1 AND at>=? "
                                   "GROUP BY rule_id", (since_iso,)).fetchall()
        return dict(rows)

    def recent_matches(self, n=50):
        with self.lock:
            rows = self.db.execute("SELECT at,rule_id,dry_run,would_submit,reason,row FROM matches "
                                   "ORDER BY id DESC LIMIT ?", (n,)).fetchall()
        return [{"at": a, "rule_id": r, "dry_run": bool(d), "would_submit": bool(w), "reason": why,
                 "pairing": json.loads(row).get("pairing")} for a, r, d, w, why, row in rows]

    # ---- rule live flags
    def live_flags(self):
        with self.lock:
            return {r: bool(v) for r, v in self.db.execute("SELECT rule_id, live FROM rule_live")}

    def set_live(self, rule_id, live):
        with self.lock:
            self.db.execute("INSERT INTO rule_live(rule_id,live,changed_at) VALUES(?,?,?) "
                            "ON CONFLICT(rule_id) DO UPDATE SET live=excluded.live, changed_at=excluded.changed_at",
                            (rule_id, int(live), now_iso()))

    def drop_live(self, rule_id):
        with self.lock:
            self.db.execute("DELETE FROM rule_live WHERE rule_id=?", (rule_id,))

    # ---- crew index (0.10.1, Ryan): crew lines of every A330 trip instance, looked up by employee number
    def crew_put(self, key, pairing, date_, end_date, route, crew, checked_at, status, reason=""):
        """Store one read of a trip instance. status 'ok' (crew is the list), 'empty' (FW-0016: the page names no
        pilot yet, as before the award) or 'fail' (reason); 'empty' and 'fail' keep the last good crew. tries counts
        reads since the last good one."""
        with self.lock:
            self.db.execute("BEGIN")
            old = self.db.execute("SELECT crew, tries FROM crew_idx WHERE key=?", (key,)).fetchone()
            tries = 0 if status == "ok" else ((old[1] if old else 0) + 1)
            cj = json.dumps(crew) if status == "ok" else (old[0] if old else None)
            self.db.execute("INSERT INTO crew_idx(key,pairing,date,end_date,route,crew,checked_at,status,reason,tries) "
                            "VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET pairing=excluded.pairing, "
                            "date=excluded.date, end_date=excluded.end_date, route=excluded.route, crew=excluded.crew, "
                            "checked_at=excluded.checked_at, status=excluded.status, reason=excluded.reason, tries=excluded.tries",
                            (key, pairing, date_, end_date, route, cj, checked_at, status, reason, tries))
            if status == "ok":
                self.db.execute("DELETE FROM crew_emp WHERE key=?", (key,))
                for c in crew or []:
                    if c.get("emp") and c.get("name") != "OPEN":
                        self.db.execute("INSERT OR REPLACE INTO crew_emp(emp,key,pos,name) VALUES(?,?,?,?)",
                                        (c["emp"], key, c.get("pos") or "", c.get("name") or ""))
            self.db.execute("COMMIT")

    def crew_rows(self):
        """{key: {key, pairing, date, end_date, route, crew, checked_at, status, reason, tries}}."""
        with self.lock:
            rows = self.db.execute("SELECT key,pairing,date,end_date,route,crew,checked_at,status,reason,tries FROM crew_idx").fetchall()
        out = {}
        for k, p, d, e, r, c, at, st, why, tr in rows:
            out[k] = {"key": k, "pairing": p, "date": d, "end_date": e, "route": r, "crew": json.loads(c) if c else [],
                      "checked_at": at, "status": st, "reason": why or "", "tries": tr}
        return out

    def crew_by_emp(self, emp):
        """[{key, pairing, date, end_date, route, pos, name, checked_at}] for one employee number (status ok)."""
        with self.lock:
            rows = self.db.execute("SELECT i.key,i.pairing,i.date,i.end_date,i.route,e.pos,e.name,i.checked_at FROM crew_emp e "
                                   "JOIN crew_idx i ON i.key=e.key WHERE e.emp=? AND i.status='ok' ORDER BY i.date",
                                   (str(emp),)).fetchall()
        return [{"key": k, "pairing": p, "date": d, "end_date": e, "route": r, "pos": pos, "name": nm, "checked_at": at}
                for k, p, d, e, r, pos, nm, at in rows]

    def crew_fix(self, has_crew, periods=None, today=""):
        """One-shot repair of what was stored before FW-0016 / FW-0017. Returns (names, empties):
        * names: the CKP tag taken out of every stored name (crew_dir, crew_emp, pickers, the crew lines in
          crew_idx, which get ckp: true instead, and the finds history: a row's captain and pot roster, a pickup's
          ca / by), so 'Doe, Ckp Jane' and 'Doe, Jane' are one person and the finds card shows the clean name;
        * empties: an 'ok' read whose crew line names no pilot becomes 'empty' (not counted as read, read again
          once names appear) only when it is a page read before the award: no read of its bid period (periods
          {key: 'YYYY-MM'}, else the date's month) names a pilot, and the trip has not started (date >= today,
          ISO). An awarded period's open-time trips stay read, and a departed trip is not read again for crew
          that can no longer change. has_crew(crew list) decides what names a pilot."""
        from pot import clean_name
        periods = periods or {}
        names = empties = 0

        def clean_by(s):  # 'FO Doe, Ckp Jane (10001); RO Roe, Rick (10002)': each picker on its own
            parts = [clean_name(p) for p in str(s or "").split("; ")]
            return "; ".join(p for p, _ in parts), any(c for _, c in parts)

        with self.lock:
            self.db.execute("BEGIN")
            try:
                for table, key in (("crew_dir", "emp"), ("crew_emp", "rowid"), ("pickers", "emp")):
                    for k, nm in self.db.execute(f"SELECT {key}, name FROM {table}").fetchall():
                        new, ckp = clean_name(nm)
                        if ckp:
                            self.db.execute(f"UPDATE {table} SET name=? WHERE {key}=?", (new, k))
                            names += 1
                for k, row, pk in self.db.execute("SELECT key, row, pickup FROM finds").fetchall():
                    try:
                        r, p = json.loads(row), json.loads(pk) if pk else None
                    except ValueError:
                        continue
                    n0 = names
                    if r.get("captain"):
                        r["captain"], c = clean_name(r["captain"])
                        names += c
                    for x in r.get("crew") or []:
                        if isinstance(x, list) and len(x) > 1:
                            x[1], c = clean_name(x[1])
                            names += c
                    for f in ("ca", "by"):
                        if isinstance(p, dict) and p.get(f):
                            p[f], c = clean_by(p[f])
                            names += c
                    if names != n0:
                        self.db.execute("UPDATE finds SET row=?, pickup=? WHERE key=?",
                                        (json.dumps(r), json.dumps(p) if p is not None else pk, k))
                rows = []
                for k, d, c, st in self.db.execute("SELECT key, date, crew, status FROM crew_idx").fetchall():
                    try:
                        crew = json.loads(c) if c else []
                    except ValueError:
                        continue
                    changed = False
                    for x in crew:
                        new, ckp = clean_name(x.get("name"))
                        if ckp:
                            x["name"], x["ckp"], changed = new, True, True
                            names += 1
                    if changed:
                        self.db.execute("UPDATE crew_idx SET crew=? WHERE key=?", (json.dumps(crew), k))
                    rows.append((k, periods.get(k) or str(d or "")[:7], str(d or ""), crew, st))
                awarded = {p for _, p, _, crew, _ in rows if has_crew(crew)}
                for k, p, d, crew, st in rows:
                    if st == "ok" and not has_crew(crew) and p not in awarded and d >= (today or ""):
                        self.db.execute("UPDATE crew_idx SET status='empty', reason=? WHERE key=?",
                                        ("no crew names on the page (read before the award)", k))
                        empties += 1
            except Exception:
                self.db.execute("ROLLBACK")
                raise
            self.db.execute("COMMIT")
        return names, empties

    # ---- housekeeping
    def prune(self, days=KEEP_DAYS):
        cut = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        with self.lock:
            self.db.execute("DELETE FROM matches WHERE at<?", (cut,))
            self.db.execute("DELETE FROM finds WHERE gone_at IS NOT NULL AND gone_at<?", (cut,))
            self.db.execute("DELETE FROM submissions WHERE at<?", (cut,))
            self.db.execute("DELETE FROM picker_log WHERE at<?", ((datetime.now(timezone.utc) - timedelta(days=LOG_KEEP_DAYS)).isoformat(),))
