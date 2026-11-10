"""Persistent reverse-task queue for UltronAgent.

Safety invariant: once a command has been delivered, it is NEVER automatically
re-delivered. Network loss after dispatch makes the outcome unknown; an operator
must reconcile it rather than risk executing a destructive command twice.
"""

import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Optional


class AgentTaskManager:
    VALID_RESULT_STATUSES = {
        "SUCCESS": "SUCCESS",
        "COMPLETED": "SUCCESS",
        "ERROR": "ERROR",
        "FAILED": "ERROR",
        "STARTED": "RUNNING",
        "RUNNING": "RUNNING",
    }
    TERMINAL = {"SUCCESS", "ERROR"}

    def __init__(self, database_path: Optional[str] = None):
        default_path = Path(__file__).resolve().parents[1] / "data" / "agent_tasks.sqlite3"
        self.database_path = str(database_path or os.environ.get("ULTRON_TASK_DB_PATH") or default_path)
        parent = os.path.dirname(os.path.abspath(self.database_path))
        os.makedirs(parent, mode=0o700, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.database_path, timeout=15, isolation_level=None)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=15000")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _initialize(self):
        with self._connect() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS agent_tasks (
                    task_id TEXT PRIMARY KEY,
                    target TEXT NOT NULL,
                    command TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    dispatched_at REAL,
                    completed_at REAL,
                    exit_code INTEGER,
                    stdout TEXT,
                    stderr TEXT
                )"""
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS agent_tasks_pending ON agent_tasks(status, target, created_at)"
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS agent_identity (
                    serial TEXT PRIMARY KEY,
                    last_ip TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )"""
            )
        # SQLite normally respects the process umask; ensure newly created DB
        # files are not world-readable on Unix. Do not require POSIX on Windows.
        if os.name == "posix":
            os.chmod(self.database_path, 0o600)

    @staticmethod
    def _normalize(value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Identificador de agente ausente.")
        return value.strip().lower()

    def bind_identity(self, serial: str, ip: str) -> None:
        """Map one agent's serial to its current IP for legacy IP-targeted tasks."""
        if not serial or not ip:
            return
        serial_key, ip_key = self._normalize(serial), self._normalize(ip)
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO agent_identity(serial, last_ip, updated_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT(serial) DO UPDATE SET
                       last_ip=excluded.last_ip, updated_at=excluded.updated_at""",
                (serial_key, ip_key, time.time()),
            )

    def enqueue_task(
        self, target_identifier: str, command: str,
        task_type: str = "powershell", task_id: Optional[str] = None
    ) -> str:
        key = self._normalize(target_identifier)
        if not isinstance(command, str) or not command.strip():
            raise ValueError("Comando da tarefa ausente.")
        task_id = task_id or ("task_" + uuid.uuid4().hex)
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO agent_tasks
                   (task_id, target, command, task_type, status, created_at)
                   VALUES (?, ?, ?, ?, 'QUEUED', ?)""",
                (task_id, key, command, task_type, time.time()),
            )
        return task_id

    def get_pending_task(self, target_identifier: str) -> Optional[Dict[str, Any]]:
        key = self._normalize(target_identifier)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            identity = conn.execute(
                "SELECT last_ip FROM agent_identity WHERE serial = ?", (key,)
            ).fetchone()
            aliases = (key, identity["last_ip"]) if identity else (key,)
            placeholders = ",".join("?" for _ in aliases)
            row = conn.execute(
                f"""SELECT task_id, target, command, task_type, created_at
                    FROM agent_tasks
                    WHERE status = 'QUEUED' AND target IN ({placeholders})
                    ORDER BY created_at, rowid LIMIT 1""",
                aliases,
            ).fetchone()
            if row is None:
                return None
            # An unknown delivery is NOT retried automatically. Network failure
            # after this point requires operator reconciliation, not re-execution.
            conn.execute(
                """UPDATE agent_tasks
                   SET status = 'DISPATCHED', dispatched_at = ?
                   WHERE task_id = ? AND status = 'QUEUED'""",
                (time.time(), row["task_id"]),
            )
            return {
                "task_id": row["task_id"],
                "target": row["target"],
                "command": row["command"],
                "type": row["task_type"],
                "created_at": row["created_at"],
            }

    def store_result(self, task_id: str, result: Dict[str, Any]) -> None:
        if not isinstance(result, dict) or result.get("task_id") != task_id:
            raise ValueError("O ID da tarefa no resultado não corresponde à URL.")
        status = self.VALID_RESULT_STATUSES.get(str(result.get("status", "")).upper())
        if status is None:
            raise ValueError("Status da tarefa inválido.")
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT status FROM agent_tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            if row is None:
                raise KeyError(task_id)
            if row["status"] in self.TERMINAL:
                if row["status"] == status:
                    return  # Resubmission after HTTP timeout; idempotent.
                raise ValueError("Não é possível sobrescrever resultado concluído.")
            if row["status"] == "QUEUED":
                raise ValueError("A tarefa ainda não foi entregue ao agente.")
            if row["status"] == "RUNNING" and status == "RUNNING":
                return
            conn.execute(
                """UPDATE agent_tasks
                   SET status = ?, completed_at = ?, exit_code = ?,
                       stdout = ?, stderr = ?
                   WHERE task_id = ?""",
                (
                    status, time.time() if status in self.TERMINAL else None,
                    result.get("exit_code"), result.get("stdout", ""),
                    result.get("stderr", ""), task_id,
                ),
            )

    def get_result(self, task_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                """SELECT task_id, target, status, created_at,
                          dispatched_at, completed_at, exit_code, stdout, stderr
                   FROM agent_tasks WHERE task_id = ?""",
                (task_id,),
            ).fetchone()
            return dict(row) if row is not None else None
