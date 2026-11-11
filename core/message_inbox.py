"""Persistent at-most-once inbound event claims. Stores no message text or tokens."""
from contextlib import contextmanager
import hashlib
import os
import sqlite3
import time
from pathlib import Path


class MessageInbox:
    def __init__(self, path=None):
        self.path = Path(path or os.environ.get("ULTRON_INBOX_DB") or
                         Path(__file__).resolve().parents[1] / "data/trueconf_inbox.sqlite3")
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self._connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS inbound_claims (event_key TEXT PRIMARY KEY, claimed_at REAL NOT NULL)")
        if os.name == "posix":
            self.path.chmod(0o600)

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(str(self.path), timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def claim(self, namespace, author, event_id):
        if not namespace or not author or event_id is None or not str(event_id).strip():
            return False
        # Length-prefixed identity avoids delimiter collisions.
        values = [str(namespace), str(author), str(event_id)]
        key = hashlib.sha256("".join(str(len(v)) + ":" + v for v in values).encode("utf-8")).hexdigest()
        with self._connect() as db:
            return db.execute("INSERT OR IGNORE INTO inbound_claims VALUES (?, ?)",
                              (key, time.time())).rowcount == 1
