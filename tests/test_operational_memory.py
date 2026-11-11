"""Offline SQLite operational memory tests. No production database is used."""
import sqlite3
from pathlib import Path
import tempfile
import unittest

from core.operational_memory import OperationalMemory, OperationalMemoryError


class OperationalMemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = str(Path(self.tmp.name) / "context.sqlite3")
        self.mem = OperationalMemory(self.db_path)

    def test_targets_are_scoped_per_technician(self):
        self.mem.remember_target("tecnico.a", "192.168.57.50")
        self.mem.remember_target("tecnico.b", "192.168.57.51")
        self.assertEqual(self.mem.target("tecnico.a"), "192.168.57.50")
        self.assertEqual(self.mem.target("tecnico.b"), "192.168.57.51")
        self.assertIsNone(self.mem.target("tecnico.c"))

    def test_no_raw_messages_or_credentials_are_stored(self):
        self.mem.remember_target("tecnico.a", "192.168.57.50")
        self.mem.start_job("tecnico.a", "192.168.57.50", "files_123456",
                           "file_backup", client="TIMENOW", ticket="12282")
        with sqlite3.connect(self.db_path) as db:
            columns = [row[1] for row in db.execute("PRAGMA table_info(technician_context)")]
            self.assertEqual(columns, ["user_id", "target_ip", "updated_at"])
            columns = [row[1] for row in db.execute("PRAGMA table_info(operational_jobs)")]
            self.assertNotIn("message", columns)
            self.assertNotIn("password", columns)
            self.assertNotIn("output", columns)
            self.assertNotIn("token", columns)

    def test_task_status_is_persisted_without_authorizing_actions(self):
        self.mem.start_job("tecnico.a", "192.168.57.50", "files_123456",
                           "file_backup", client="TIMENOW", ticket="12282")
        self.assertEqual(self.mem.latest_job("tecnico.a")["status"], "QUEUED")
        self.assertTrue(self.mem.update_job("tecnico.a", "files_123456", "SUCCESS"))
        self.assertFalse(self.mem.update_job("tecnico.a", "files_123456", "ERROR"))
        new_process = OperationalMemory(self.db_path)
        self.assertEqual(new_process.latest_job("tecnico.a")["status"], "SUCCESS")
        self.assertIsNone(new_process.latest_job("tecnico.b"))

    def test_restart_marks_unfinished_as_unknown_no_auto_retry(self):
        self.mem.start_job("tecnico.a", "192.168.57.50", "files_123456", "file_backup")
        other_process = OperationalMemory(self.db_path)
        self.assertEqual(other_process.latest_job("tecnico.a")["status"], "UNKNOWN")
        self.assertFalse(other_process.update_job("tecnico.a", "files_123456", "SUCCESS"))

    def test_invalid_user_ip_or_task_is_denied(self):
        for username, ip in [
            ("", "192.168.57.50"), ("alice;DROP", "192.168.57.50"),
            ("alice", "300.300.300.300"),
        ]:
            with self.subTest(user=username, ip=ip), self.assertRaises(OperationalMemoryError):
                self.mem.remember_target(username, ip)
        with self.assertRaises(OperationalMemoryError):
            self.mem.start_job("alice", "192.168.57.50", "job_11111",
                               "format", client="CLIENT", ticket="12282")

    def test_no_cross_user_job_updates(self):
        self.mem.start_job("tecnico.a", "192.168.57.50", "files_123456", "file_backup")
        self.assertFalse(self.mem.update_job("tecnico.b", "files_123456", "SUCCESS"))
        self.assertEqual(self.mem.latest_job("tecnico.a")["status"], "QUEUED")


if __name__ == "__main__":
    unittest.main()
