"""SQLite store: watcher state, finds history, rule matches, per-rule live flags.

Replaces state.json (v0.1.x). Every write is one transaction, so a crash mid-write
leaves the previous state intact. The old state.json is imported once and renamed.
"""
import json
import os
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
"""
KEEP_DAYS = 90


def is_prem(row):
    """Premium pairing: FLICA marks the Prem column with an X (mobile cell x1)."""
    return any(str(row.get(k) or "").strip().upper() == "X" for k in ("x1", "prem"))


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
        self.default_state = default_state or {}
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

    def recent_finds(self, n=50):
        with self.lock:
            rows = self.db.execute("SELECT key,row,month,first_seen,gone_at,pickup FROM finds "
                                   "ORDER BY first_seen DESC LIMIT ?", (n,)).fetchall()
        out = []
        for key, row, month, first, gone, pickup in rows:
            r = json.loads(row)
            pk = json.loads(pickup) if pickup else {}
            out.append({"pairing": r.get("pairing"), "dates": r.get("dates"), "days": r.get("days"),
                        "layover": r.get("layover"), "report": r.get("report"), "credit": r.get("credit"),
                        "turn": r.get("turn"), "captain": pk.get("ca") or r.get("captain") or "",
                        "prem": is_prem(r), "picked_by": pk.get("by", ""), "source": r.get("source", "pot"), "pickup_status": pk.get("status", ""), "pickup_known": bool(pk.get("known")),
                        "month": month, "seen": first, "gone": gone})
        return out

    def has_find(self, key):
        with self.lock:
            return self.db.execute("SELECT 1 FROM finds WHERE key=?", (key,)).fetchone() is not None

    def add_find(self, key, month, row, seen, gone=None):
        """A find the pot watch missed (0.4.1: from a FLICA alert email). No-op if already known."""
        with self.lock:
            self.db.execute("INSERT OR IGNORE INTO finds(key,pairing,month,row,first_seen,last_seen,gone_at) "
                            "VALUES(?,?,?,?,?,?,?)", (key, row.get("pairing"), month, json.dumps(row),
                                                      seen, seen, gone))

    def find_row(self, key):
        with self.lock:
            r = self.db.execute("SELECT row FROM finds WHERE key=?", (key,)).fetchone()
        return json.loads(r[0]) if r else None

    def set_pickup(self, key, pickup):
        with self.lock:
            self.db.execute("UPDATE finds SET pickup=? WHERE key=?", (json.dumps(pickup), key))

    def gone_without_pickup(self, n=50):
        with self.lock:
            return [k for (k,) in self.db.execute(
                "SELECT key FROM finds WHERE gone_at IS NOT NULL AND pickup IS NULL "
                "ORDER BY first_seen DESC LIMIT ?", (n,)).fetchall()]

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

    # ---- housekeeping
    def prune(self, days=KEEP_DAYS):
        cut = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        with self.lock:
            self.db.execute("DELETE FROM matches WHERE at<?", (cut,))
            self.db.execute("DELETE FROM finds WHERE gone_at IS NOT NULL AND gone_at<?", (cut,))
            self.db.execute("DELETE FROM submissions WHERE at<?", (cut,))
