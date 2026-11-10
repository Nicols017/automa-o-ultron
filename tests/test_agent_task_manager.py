"""Offline tests of the persistent reverse command queue.

These tests use private temporary SQLite databases and fake identifiers.
They never contact WDS, TrueConf, Windows agents or production hosts.
Run: python3 -m unittest discover -s tests -p 'test_agent_task_manager.py' -v
"""

import importlib.util
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def load_manager():
    path = Path(__file__).resolve().parents[1] / "core" / "agent_task_manager.py"
    spec = importlib.util.spec_from_file_location("offline_agent_task_manager", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.AgentTaskManager


AgentTaskManager = load_manager()


class AgentTaskManagerTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="ultron-queue-test-")
        self.db = str(Path(self.temp_dir.name) / "tasks.sqlite3")
        self.queue = AgentTaskManager(database_path=self.db)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_queue_survives_manager_recreation_without_repeating_dispatch(self):
        task_id = self.queue.enqueue_task("TEST-SERIAL", "Get-Date")
        restarted = AgentTaskManager(database_path=self.db)
        task = restarted.get_pending_task("test-serial")
        self.assertEqual(task["task_id"], task_id)
        self.assertEqual(task["command"], "Get-Date")
        self.assertEqual(restarted.get_result(task_id)["status"], "DISPATCHED")
        self.assertIsNone(AgentTaskManager(database_path=self.db).get_pending_task("TEST-SERIAL"))
        restarted.store_result(task_id, {
            "task_id": task_id, "status": "SUCCESS", "exit_code": 0,
            "stdout": "ok", "stderr": ""
        })
        result = AgentTaskManager(database_path=self.db).get_result(task_id)
        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(result["stdout"], "ok")

    def test_serial_can_poll_legacy_ip_targeted_command(self):
        task_id = self.queue.enqueue_task("192.0.2.31", "Get-Service")
        self.assertIsNone(self.queue.get_pending_task("SERIAL-31"))
        self.queue.bind_identity("SERIAL-31", "192.0.2.31")
        self.assertEqual(self.queue.get_pending_task("serial-31")["task_id"], task_id)

    def test_target_isolation(self):
        one = self.queue.enqueue_task("SERIAL-ONE", "Get-Process")
        two = self.queue.enqueue_task("SERIAL-TWO", "Get-Date")
        self.assertEqual(self.queue.get_pending_task("serial-two")["task_id"], two)
        self.assertEqual(self.queue.get_pending_task("serial-one")["task_id"], one)

    def test_only_one_worker_can_claim_a_command(self):
        task_id = self.queue.enqueue_task("SERIAL-THREAD", "Get-Culture")
        def poll(_):
            return AgentTaskManager(database_path=self.db).get_pending_task("SERIAL-THREAD")
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(poll, range(24)))
        received = [r for r in results if r]
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["task_id"], task_id)

    def test_task_id_mismatch_is_rejected(self):
        task_id = self.queue.enqueue_task("SERIAL", "Get-Date")
        self.queue.get_pending_task("SERIAL")
        with self.assertRaises(ValueError):
            self.queue.store_result(task_id, {"task_id": "OTHER", "status": "SUCCESS"})

    def test_unknown_task_id_is_rejected(self):
        with self.assertRaises(KeyError):
            self.queue.store_result("task_missing", {
                "task_id": "task_missing", "status": "SUCCESS"
            })

    def test_pending_task_cannot_be_marked_complete(self):
        task_id = self.queue.enqueue_task("SERIAL", "Get-Date")
        with self.assertRaises(ValueError):
            self.queue.store_result(task_id, {"task_id": task_id, "status": "SUCCESS"})
        self.assertEqual(self.queue.get_result(task_id)["status"], "QUEUED")

    def test_unknown_status_is_rejected(self):
        task_id = self.queue.enqueue_task("SERIAL", "Get-Date")
        self.queue.get_pending_task("SERIAL")
        with self.assertRaises(ValueError):
            self.queue.store_result(task_id, {"task_id": task_id, "status": "INVENTED"})
        self.assertEqual(self.queue.get_result(task_id)["status"], "DISPATCHED")

    def test_duplicate_result_is_idempotent_but_cannot_flip(self):
        task_id = self.queue.enqueue_task("SERIAL", "Get-Date")
        self.queue.get_pending_task("SERIAL")
        result = {
            "task_id": task_id, "status": "SUCCESS", "exit_code": 0,
            "stdout": "first", "stderr": ""
        }
        self.queue.store_result(task_id, result)
        self.queue.store_result(task_id, {**result, "stdout": "retry"})
        self.assertEqual(self.queue.get_result(task_id)["stdout"], "first")
        with self.assertRaises(ValueError):
            self.queue.store_result(task_id, {"task_id": task_id, "status": "ERROR"})

    def test_cleanup_started_does_not_claim_success(self):
        task_id = self.queue.enqueue_task("SERIAL", "CLEANUP_SYSTEM", task_type="cleanup")
        self.queue.get_pending_task("SERIAL")
        self.queue.store_result(task_id, {
            "task_id": task_id, "status": "STARTED",
            "stdout": "Removal started", "exit_code": 0
        })
        state = self.queue.get_result(task_id)
        self.assertEqual(state["status"], "RUNNING")
        self.assertIsNone(state["completed_at"])
        self.assertIsNone(self.queue.get_pending_task("SERIAL"))

    def test_explicit_duplicate_task_id_is_rejected(self):
        self.queue.enqueue_task("SERIAL", "Get-Date", task_id="same")
        with self.assertRaises(sqlite3.IntegrityError):
            self.queue.enqueue_task("SERIAL", "Get-Process", task_id="same")


if __name__ == "__main__":
    unittest.main()
