"""
Append-only audit logging.

Every patient-record access, policy lookup, and safety escalation is
recorded with who/what/when so the hospital can meet HIPAA's "access
logging" requirement (see data/policies/hipaa_privacy.md) and so incidents
can be investigated after the fact. Log rows are never updated or deleted
by the application; only inserted.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


class AuditLogger:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self._lock = threading.Lock()
        self._ensure_table()

    def _connect(self):
        return sqlite3.connect(self.db_path)

    def _ensure_table(self):
        with self._lock, self._connect() as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_log (
                    id TEXT PRIMARY KEY,
                    ts TEXT NOT NULL,
                    user_id TEXT,
                    role TEXT,
                    agent TEXT NOT NULL,
                    query TEXT NOT NULL,
                    sql TEXT,
                    row_count INTEGER,
                    confidence REAL,
                    safety_flags TEXT,
                    escalated INTEGER DEFAULT 0,
                    status TEXT NOT NULL,
                    detail TEXT
                )
                """
            )
            con.execute("CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(ts)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_log(user_id)")

    def log(
        self,
        *,
        agent: str,
        query: str,
        user_id: Optional[str] = None,
        role: Optional[str] = None,
        sql: Optional[str] = None,
        row_count: Optional[int] = None,
        confidence: Optional[float] = None,
        safety_flags: Optional[List[str]] = None,
        escalated: bool = False,
        status: str = "ok",
        detail: Optional[str] = None,
    ) -> str:
        entry_id = uuid.uuid4().hex
        ts = datetime.now(timezone.utc).isoformat()
        with self._lock, self._connect() as con:
            con.execute(
                """INSERT INTO audit_log
                   (id, ts, user_id, role, agent, query, sql, row_count,
                    confidence, safety_flags, escalated, status, detail)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    entry_id, ts, user_id, role, agent, query, sql, row_count,
                    confidence, json.dumps(safety_flags or []), int(escalated),
                    status, detail,
                ),
            )
        return entry_id

    def recent(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self._lock, self._connect() as con:
            con.row_factory = sqlite3.Row
            rows = con.execute(
                "SELECT * FROM audit_log ORDER BY ts DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]

    def stats(self) -> Dict[str, Any]:
        with self._lock, self._connect() as con:
            total = con.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
            escalations = con.execute(
                "SELECT COUNT(*) FROM audit_log WHERE escalated=1"
            ).fetchone()[0]
            blocked = con.execute(
                "SELECT COUNT(*) FROM audit_log WHERE status='blocked'"
            ).fetchone()[0]
            return {"total_events": total, "escalations": escalations, "blocked": blocked}
