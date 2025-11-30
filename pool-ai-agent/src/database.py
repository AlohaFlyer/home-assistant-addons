"""SQLite database for state history and decision logging."""

import sqlite3
import json
import logging
from typing import Optional
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)


class Database:
    """SQLite database for storing pool agent history."""

    def __init__(self, db_path: str = "/config/pool_ai_agent/agent.db"):
        self.db_path = db_path
        # Ensure directory exists
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        """Initialize database tables."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # State snapshots table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS state_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    active_mode TEXT,
                    water_temp REAL,
                    pump_on INTEGER
                )
            """)

            # Decisions table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    patterns_json TEXT NOT NULL,
                    decision_json TEXT NOT NULL,
                    action_required INTEGER,
                    actions_taken TEXT,
                    confidence REAL,
                    input_tokens INTEGER,
                    output_tokens INTEGER,
                    cost_usd REAL
                )
            """)

            # Actions table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    decision_id INTEGER,
                    action_json TEXT NOT NULL,
                    success INTEGER,
                    blocked_by_safety INTEGER,
                    message TEXT,
                    FOREIGN KEY (decision_id) REFERENCES decisions(id)
                )
            """)

            # Daily stats table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS daily_stats (
                    date TEXT PRIMARY KEY,
                    api_calls INTEGER DEFAULT 0,
                    input_tokens INTEGER DEFAULT 0,
                    output_tokens INTEGER DEFAULT 0,
                    cost_usd REAL DEFAULT 0,
                    actions_executed INTEGER DEFAULT 0,
                    actions_blocked INTEGER DEFAULT 0,
                    anomalies_detected INTEGER DEFAULT 0
                )
            """)

            # Create indexes
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_snapshots_timestamp
                ON state_snapshots(timestamp)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_decisions_timestamp
                ON decisions(timestamp)
            """)

            conn.commit()

    def save_state(self, state_dict: dict):
        """Save a state snapshot."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO state_snapshots
                (timestamp, state_json, active_mode, water_temp, pump_on)
                VALUES (?, ?, ?, ?, ?)
            """, (
                state_dict.get("timestamp", datetime.now().isoformat()),
                json.dumps(state_dict),
                state_dict.get("active_mode"),
                state_dict.get("temperature", {}).get("water"),
                1 if state_dict.get("pump", {}).get("on") else 0
            ))
            conn.commit()

    def save_decision(
        self,
        state_dict: dict,
        patterns_dict: dict,
        decision_dict: dict,
        input_tokens: int = 0,
        output_tokens: int = 0
    ) -> int:
        """Save a decision and return its ID."""
        # Calculate cost (Claude Sonnet 4.5 pricing)
        cost = (input_tokens / 1_000_000) * 3.0 + (output_tokens / 1_000_000) * 15.0

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO decisions
                (timestamp, state_json, patterns_json, decision_json,
                 action_required, actions_taken, confidence,
                 input_tokens, output_tokens, cost_usd)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                datetime.now().isoformat(),
                json.dumps(state_dict),
                json.dumps(patterns_dict),
                json.dumps(decision_dict),
                1 if decision_dict.get("action_required") else 0,
                json.dumps(decision_dict.get("actions", [])),
                decision_dict.get("confidence", 0),
                input_tokens,
                output_tokens,
                cost
            ))
            decision_id = cursor.lastrowid

            # Update daily stats
            today = datetime.now().strftime("%Y-%m-%d")
            cursor.execute("""
                INSERT INTO daily_stats (date, api_calls, input_tokens, output_tokens, cost_usd)
                VALUES (?, 1, ?, ?, ?)
                ON CONFLICT(date) DO UPDATE SET
                    api_calls = api_calls + 1,
                    input_tokens = input_tokens + excluded.input_tokens,
                    output_tokens = output_tokens + excluded.output_tokens,
                    cost_usd = cost_usd + excluded.cost_usd
            """, (today, input_tokens, output_tokens, cost))

            conn.commit()
            return decision_id

    def save_action(
        self,
        decision_id: int,
        action_dict: dict,
        success: bool,
        blocked_by_safety: bool,
        message: str
    ):
        """Save an action execution result."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO actions
                (timestamp, decision_id, action_json, success, blocked_by_safety, message)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                datetime.now().isoformat(),
                decision_id,
                json.dumps(action_dict),
                1 if success else 0,
                1 if blocked_by_safety else 0,
                message
            ))

            # Update daily stats
            today = datetime.now().strftime("%Y-%m-%d")
            if blocked_by_safety:
                cursor.execute("""
                    UPDATE daily_stats SET actions_blocked = actions_blocked + 1
                    WHERE date = ?
                """, (today,))
            else:
                cursor.execute("""
                    UPDATE daily_stats SET actions_executed = actions_executed + 1
                    WHERE date = ?
                """, (today,))

            conn.commit()

    def get_recent_decisions(self, hours: int = 24) -> list[dict]:
        """Get decisions from the last N hours."""
        cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT timestamp, decision_json, action_required, confidence
                FROM decisions
                WHERE timestamp > ?
                ORDER BY timestamp DESC
                LIMIT 50
            """, (cutoff,))

            decisions = []
            for row in cursor.fetchall():
                decisions.append({
                    "timestamp": row[0],
                    "decision": json.loads(row[1]),
                    "action_required": bool(row[2]),
                    "confidence": row[3]
                })
            return decisions

    def get_state_history(self, hours: int = 24) -> list[dict]:
        """Get state snapshots from the last N hours."""
        cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT timestamp, state_json
                FROM state_snapshots
                WHERE timestamp > ?
                ORDER BY timestamp ASC
            """, (cutoff,))

            return [
                {"timestamp": row[0], **json.loads(row[1])}
                for row in cursor.fetchall()
            ]

    def get_daily_stats(self, date: Optional[str] = None) -> dict:
        """Get statistics for a specific date (default: today)."""
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT api_calls, input_tokens, output_tokens, cost_usd,
                       actions_executed, actions_blocked, anomalies_detected
                FROM daily_stats
                WHERE date = ?
            """, (date,))

            row = cursor.fetchone()
            if row:
                return {
                    "date": date,
                    "api_calls": row[0],
                    "input_tokens": row[1],
                    "output_tokens": row[2],
                    "cost_usd": round(row[3], 4),
                    "actions_executed": row[4],
                    "actions_blocked": row[5],
                    "anomalies_detected": row[6]
                }
            return {
                "date": date,
                "api_calls": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "cost_usd": 0,
                "actions_executed": 0,
                "actions_blocked": 0,
                "anomalies_detected": 0
            }

    def increment_anomalies(self, count: int = 1):
        """Increment anomalies detected counter for today."""
        today = datetime.now().strftime("%Y-%m-%d")

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO daily_stats (date, anomalies_detected)
                VALUES (?, ?)
                ON CONFLICT(date) DO UPDATE SET
                    anomalies_detected = anomalies_detected + ?
            """, (today, count, count))
            conn.commit()

    def cleanup_old_data(self, days: int = 90):
        """Remove data older than N days."""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            cursor.execute("DELETE FROM state_snapshots WHERE timestamp < ?", (cutoff,))
            cursor.execute("DELETE FROM actions WHERE timestamp < ?", (cutoff,))
            cursor.execute("DELETE FROM decisions WHERE timestamp < ?", (cutoff,))

            deleted = cursor.rowcount
            conn.commit()
            logger.info(f"Cleaned up {deleted} old records")
