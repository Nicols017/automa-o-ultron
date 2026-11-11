"""Unified metadata registry. Stores metadata and typed package outcomes; never raw output/commands or retries."""
from contextlib import contextmanager
import ipaddress
import os
from pathlib import Path
import re
import sqlite3
import time
import uuid

ACTIONS = {"diagnose", "software_install", "file_backup", "prepare"}
TERMINAL = {"SUCCESS", "PARTIAL", "ERROR", "UNKNOWN"}
EVIDENCE = {"NONE", "EXECUTOR_REPORTED_SUCCESS", "BACKUP_REPORT_VALIDATED", "NOT_STARTED", "SOFTWARE_PRESENCE_VERIFIED"}


class TaskRegistryError(ValueError):
    pass


def actor(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9_.@-]{1,128}", value):
        raise TaskRegistryError("Identidade invalida.")
    return value.casefold()


class TaskRegistry:
    def __init__(self, path=None):
        self.path = Path(path or os.environ.get("ULTRON_JOB_DB") or
                         Path(__file__).resolve().parents[1] / "data/tasks.sqlite3")
        self._runtime = None

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        db = sqlite3.connect(str(self.path), timeout=10)
        db.row_factory = sqlite3.Row
        try:
            db.execute("""CREATE TABLE IF NOT EXISTS tasks (
                job_id TEXT PRIMARY KEY, owner TEXT NOT NULL, target_ip TEXT NOT NULL,
                action TEXT NOT NULL, status TEXT NOT NULL, evidence TEXT NOT NULL,
                created_at REAL NOT NULL, updated_at REAL NOT NULL)""")
            db.execute("""CREATE UNIQUE INDEX IF NOT EXISTS one_active_task_per_target
                        ON tasks(target_ip) WHERE status IN ('QUEUED','RUNNING')""")
            db.execute("""CREATE TABLE IF NOT EXISTS task_packages (
                job_id TEXT NOT NULL REFERENCES tasks(job_id),
                requested TEXT NOT NULL, manager TEXT NOT NULL, installer_exit_code INTEGER,
                installer_reported_success INTEGER, status TEXT NOT NULL, version TEXT,
                PRIMARY KEY(job_id,requested))""")
            db.execute("""CREATE TABLE IF NOT EXISTS preparation_steps (
                job_id TEXT NOT NULL, step TEXT NOT NULL, status TEXT NOT NULL,
                PRIMARY KEY(job_id,step))""")
            if os.name == "posix":
                self.path.chmod(0o600)
            with db:
                yield db
        finally:
            db.close()

    def acquire_runtime(self):
        """One executing server per DB. Readers never claim or reset active tasks."""
        if self._runtime is not None:
            return False
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        lock = open(str(self.path) + ".lock", "a+b")
        try:
            if os.name == "nt":
                import msvcrt
                if lock.seek(0, 2) == 0:
                    lock.write(b"0")
                    lock.flush()
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._runtime = lock
            return True
        except (OSError, IOError):
            lock.close()
            raise TaskRegistryError("Outro processo ja controla as tarefas deste banco.") from None

    def release_runtime(self):
        if self._runtime is not None:
            lock, self._runtime = self._runtime, None
            if os.name == "nt":
                import msvcrt
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
            lock.close()

    def recover_after_restart(self):
        if self._runtime is None:
            raise TaskRegistryError("Recuperacao exige exclusividade do processo.")
        with self.connect() as db:
            db.execute("UPDATE preparation_steps SET status='UNKNOWN' WHERE status='RUNNING'")
            return db.execute("UPDATE tasks SET status='UNKNOWN',evidence='NONE',updated_at=? "
                              "WHERE status IN ('QUEUED','RUNNING')", (time.time(),)).rowcount

    def create(self, owner, target_ip, action, job_id=None):
        owner = actor(owner)
        try:
            ip = ipaddress.ip_address(target_ip)
            if ip.version != 4 or ip.is_unspecified or ip.is_multicast:
                raise ValueError()
        except ValueError:
            raise TaskRegistryError("IPv4 invalido.") from None
        if action not in ACTIONS:
            raise TaskRegistryError("Acao nao suportada pelo registro.")
        job_id = job_id or "task_" + uuid.uuid4().hex
        if not re.fullmatch(r"[a-zA-Z0-9_-]{5,100}", job_id):
            raise TaskRegistryError("ID invalido.")
        now = time.time()
        try:
            with self.connect() as db:
                db.execute("INSERT INTO tasks VALUES (?,?,?,?,?,?,?,?)",
                           (job_id, owner, str(ip), action, "QUEUED", "NONE", now, now))
        except sqlite3.IntegrityError:
            raise TaskRegistryError("Tarefa repetida ou outra tarefa em andamento neste equipamento.") from None
        return self.get(owner, job_id)

    def begin(self, owner, job_id):
        with self.connect() as db:
            return db.execute("UPDATE tasks SET status='RUNNING',updated_at=? "
                "WHERE owner=? AND job_id=? AND status='QUEUED'",
                (time.time(), actor(owner), job_id)).rowcount == 1

    def finish(self, owner, job_id, status, evidence="NONE", package_results=None):
        if status not in TERMINAL or evidence not in EVIDENCE:
            raise TaskRegistryError("Resultado invalido.")
        with self.connect() as db:
            changed = db.execute("UPDATE tasks SET status=?,evidence=?,updated_at=? "
                "WHERE owner=? AND job_id=? AND status IN ('QUEUED','RUNNING')",
                (status, evidence, time.time(), actor(owner), job_id)).rowcount == 1
            if changed and package_results is not None:
                for row in package_results:
                    db.execute("INSERT INTO task_packages VALUES (?,?,?,?,?,?,?)",
                        (job_id, row["requested"], row["manager"], row["installer_exit_code"],
                         row["installer_reported_success"], row["status"], row["version"]))
            return changed

    def execute(self, owner, job_id, operation):
        if not self.begin(owner, job_id):
            raise TaskRegistryError("Tarefa ja entregue ou encerrada; nenhum comando reenviado.")
        try:
            result = operation()
        except Exception:
            self.finish(owner, job_id, "UNKNOWN")
            raise
        record = self.get(owner, job_id)
        if record and record["action"] == "software_install":
            from core.software_installation import validated_summary
            try:
                status, rows = validated_summary(result)
            except (ValueError, TypeError, KeyError, AttributeError):
                self.finish(owner, job_id, "UNKNOWN")
            else:
                self.finish(owner, job_id, status,
                    "SOFTWARE_PRESENCE_VERIFIED" if status == "SUCCESS" else "NONE", package_results=rows)
            return result
        if not isinstance(result, dict) or result.get("outcome") == "UNKNOWN":
            status = "UNKNOWN"
        elif result.get("success") is True and not result.get("error"):
            status = "SUCCESS"
        elif result.get("success") is False or result.get("error"):
            status = "ERROR"
        else:
            status = "UNKNOWN"
        evidence = "EXECUTOR_REPORTED_SUCCESS" if status == "SUCCESS" else "NONE"
        self.finish(owner, job_id, status, evidence)
        return result

    def get(self, owner, job_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM tasks WHERE owner=? AND job_id=?",
                             (actor(owner), job_id)).fetchone()
            if row is None:
                return None
            record = dict(row)
            if record["action"] == "prepare":
                record["steps"] = dict(db.execute(
                    "SELECT step,status FROM preparation_steps WHERE job_id=? ORDER BY rowid", (job_id,)))
            if record["action"] == "software_install":
                record["package_results"] = []
                for item in db.execute("SELECT requested,manager,installer_exit_code,installer_reported_success,status,version FROM task_packages WHERE job_id=? ORDER BY requested", (job_id,)):
                    package = dict(item)
                    if package["installer_reported_success"] is not None:
                        package["installer_reported_success"] = bool(package["installer_reported_success"])
                    record["package_results"].append(package)
            return record

    def recent(self, owner, limit=10):
        if not isinstance(limit, int) or not 1 <= limit <= 50:
            raise TaskRegistryError("Limite invalido.")
        with self.connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM tasks WHERE owner=? ORDER BY created_at DESC,job_id LIMIT ?",
                (actor(owner), limit))]


task_registry = TaskRegistry()
