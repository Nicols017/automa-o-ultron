"""Minimal SQLite operational memory for Ultron TrueConf.

Only stable operational identifiers and job statuses are stored. No chat text,
tokens, passwords, diagnostic logs, execution outputs or customer file content.

The memory is informational and must NEVER authorize a remote action.
Unfinished jobs become UNKNOWN after process restart; they are never requeued.
"""
import ipaddress
import os
from pathlib import Path
import re
import sqlite3
import threading
import time
from typing import Optional

USER_RE = re.compile(r"^[a-zA-Z0-9_.@-]{1,128}$")
TICKET_RE = re.compile(r"^[0-9]{2,12}$")
CLIENT_RE = re.compile(r"^[a-zA-Z0-9 _-]{1,60}$")
JOB_RE = re.compile(r"^[a-zA-Z0-9_-]{5,100}$")
ACTIONS = frozenset({
    "file_backup", "macrium_verify", "diagnose", "prepare", "inspect",
})
STATUSES = frozenset({"QUEUED", "RUNNING", "SUCCESS", "ERROR", "UNKNOWN"})


class OperationalMemoryError(ValueError):
    pass


def _user(value: str) -> str:
    if not isinstance(value, str) or not USER_RE.fullmatch(value):
        raise OperationalMemoryError("Identidade de técnico inválida.")
    return value.lower()


def _ip(value: str) -> str:
    try:
        addr = ipaddress.ip_address(value)
        if addr.version != 4 or addr.is_unspecified or addr.is_multicast:
            raise ValueError("invalid")
    except (ValueError, TypeError) as exc:
        raise OperationalMemoryError("Endereço IPv4 inválido.") from exc
    return str(addr)


def _optional_client(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    if not CLIENT_RE.fullmatch(value):
        raise OperationalMemoryError("Nome do cliente não permitido.")
    return value


def _optional_ticket(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    if not TICKET_RE.fullmatch(value):
        raise OperationalMemoryError("Chamado inválido.")
    return value


class OperationalMemory:
    def __init__(self, db_path: Optional[str] = None, ttl_seconds: int = 7 * 24 * 3600):
        self.path = Path(db_path or os.getenv(
            "ULTRON_OPERATIONAL_DB", "data/operational_context.sqlite3"
        ))
        if ttl_seconds < 60:
            raise OperationalMemoryError("TTL da memória inválido.")
        self.ttl_seconds = ttl_seconds
        self._lock = threading.RLock()
        self._ready = False

    def _connection(self):
        db = sqlite3.connect(str(self.path), timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def _initialize(self):
        if self._ready:
            return
        with self._lock:
            if self._ready:
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.chmod(self.path.parent, 0o700)
            except OSError:
                pass
            with self._connection() as db:
                db.execute("PRAGMA journal_mode=WAL")
                db.execute("""
                    CREATE TABLE IF NOT EXISTS technician_context (
                        user_id TEXT PRIMARY KEY,
                        target_ip TEXT NOT NULL,
                        updated_at REAL NOT NULL
                    )
                """)
                db.execute("""
                    CREATE TABLE IF NOT EXISTS operational_jobs (
                        job_id TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL,
                        target_ip TEXT NOT NULL,
                        action TEXT NOT NULL,
                        client TEXT,
                        ticket TEXT,
                        status TEXT NOT NULL,
                        started_at REAL NOT NULL,
                        updated_at REAL NOT NULL
                    )
                """)
                # A restart cannot prove how a subprocess ended. Never replay.
                db.execute(
                    "UPDATE operational_jobs SET status='UNKNOWN', updated_at=? "
                    "WHERE status IN ('QUEUED','RUNNING')",
                    (time.time(),),
                )
                cutoff = time.time() - self.ttl_seconds
                db.execute("DELETE FROM operational_jobs WHERE updated_at < ?", (cutoff,))
                db.execute("DELETE FROM technician_context WHERE updated_at < ?", (cutoff,))
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass
            self._ready = True

    def remember_target(self, user_id: str, target_ip: str):
        """Record an EXPLICITLY given target; not evidence of authorization."""
        user_id, target_ip = _user(user_id), _ip(target_ip)
        self._initialize()
        with self._lock, self._connection() as db:
            db.execute(
                "INSERT INTO technician_context(user_id,target_ip,updated_at) "
                "VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET "
                "target_ip=excluded.target_ip, updated_at=excluded.updated_at",
                (user_id, target_ip, time.time()),
            )

    def target(self, user_id: str) -> Optional[str]:
        user_id = _user(user_id)
        self._initialize()
        with self._lock, self._connection() as db:
            row = db.execute(
                "SELECT target_ip FROM technician_context "
                "WHERE user_id=? AND updated_at>=?",
                (user_id, time.time() - self.ttl_seconds),
            ).fetchone()
            return str(row["target_ip"]) if row else None

    def start_job(
        self, user_id: str, target_ip: str, job_id: str, action: str,
        client: Optional[str] = None, ticket: Optional[str] = None
    ):
        user_id, target_ip = _user(user_id), _ip(target_ip)
        client, ticket = _optional_client(client), _optional_ticket(ticket)
        if not isinstance(job_id, str) or not JOB_RE.fullmatch(job_id):
            raise OperationalMemoryError("Identificador da tarefa inválido.")
        if action not in ACTIONS:
            raise OperationalMemoryError("Tipo de tarefa não reconhecido.")
        self._initialize()
        now = time.time()
        with self._lock, self._connection() as db:
            db.execute(
                "INSERT INTO operational_jobs"
                "(job_id,user_id,target_ip,action,client,ticket,status,started_at,updated_at)"
                " VALUES(?,?,?,?,?,?,?,?,?)",
                (job_id, user_id, target_ip, action, client, ticket, "QUEUED", now, now),
            )

    def update_job(self, user_id: str, job_id: str, status: str) -> bool:
        user_id = _user(user_id)
        if not isinstance(job_id, str) or not JOB_RE.fullmatch(job_id):
            raise OperationalMemoryError("Identificador inválido.")
        if status not in STATUSES:
            raise OperationalMemoryError("Estado de tarefa inválido.")
        self._initialize()
        with self._lock, self._connection() as db:
            changed = db.execute(
                "UPDATE operational_jobs SET status=?,updated_at=? "
                "WHERE user_id=? AND job_id=? AND status IN ('QUEUED','RUNNING')",
                (status, time.time(), user_id, job_id),
            ).rowcount
            return changed == 1

    def latest_job(self, user_id: str) -> Optional[dict]:
        user_id = _user(user_id)
        self._initialize()
        with self._lock, self._connection() as db:
            row = db.execute(
                "SELECT job_id,target_ip,action,client,ticket,status,started_at,updated_at "
                "FROM operational_jobs WHERE user_id=? AND updated_at>=? "
                "ORDER BY started_at DESC LIMIT 1",
                (user_id, time.time() - self.ttl_seconds),
            ).fetchone()
            return dict(row) if row else None
