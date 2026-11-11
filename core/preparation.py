"""Persistent milestones for one preparation request."""
from contextlib import contextmanager
from core.task_registry import task_registry


@contextmanager
def preparation(owner, ip):
    job = task_registry.create(owner, ip, "prepare")
    job_id = job["job_id"]
    def mark(step, status):
        with task_registry.connect() as db:
            db.execute("UPDATE preparation_steps SET status=? WHERE job_id=? AND step=?",
                       (status, job_id, step))
    try:
        with task_registry.connect() as db:
            db.executemany("INSERT INTO preparation_steps VALUES (?,?,'PENDING')",
                           [(job_id, step) for step in ("diagnostico", "instalacao", "laudo")])
        if not task_registry.begin(owner, job_id):
            raise RuntimeError("Preparação já encerrada.")
        yield job_id, mark
    finally:
        with task_registry.connect() as db:
            db.execute("UPDATE preparation_steps SET status='UNKNOWN' WHERE job_id=? AND status='RUNNING'", (job_id,))
            states = [row[0] for row in db.execute("SELECT status FROM preparation_steps WHERE job_id=?", (job_id,))]
        status = "SUCCESS" if states == ["SUCCESS"] * 3 else ("UNKNOWN" if "UNKNOWN" in states else "ERROR")
        task_registry.finish(owner, job_id, status)
