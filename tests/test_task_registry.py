"""Offline task lifecycle tests: only scratch SQLite and fake executors."""
import ast
import concurrent.futures
import os
from pathlib import Path
import tempfile
import threading
import types
import typing
import unittest
from unittest.mock import Mock, patch
from core.task_registry import TaskRegistry, TaskRegistryError
from core.preformat_files_backup import FileBackupJobs
from test_preformat_files_backup import CONFIG, IP, FakeWinRM, InlineThread, make_report

ROOT = Path(__file__).resolve().parents[1]


class RegistryFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "tasks.sqlite3"
        self.registry = TaskRegistry(self.path)

    def create(self, owner="tech", ip="192.0.2.50", action="diagnose"):
        return self.registry.create(owner, ip, action)


class TaskRegistryTests(RegistryFixture):
    def test_lifecycle_is_persistent_and_owner_filtered(self):
        job = self.create()
        self.registry.execute("tech", job["job_id"], lambda: {"success": True})
        other = TaskRegistry(self.path)
        self.assertEqual(other.get("tech", job["job_id"])["status"], "SUCCESS")
        self.assertIsNone(other.get("other", job["job_id"]))
        self.assertEqual(other.recent("other"), [])

    def test_execute_at_most_once(self):
        job = self.create()
        operation = Mock(return_value={"success": True})
        self.registry.execute("tech", job["job_id"], operation)
        with self.assertRaises(TaskRegistryError):
            self.registry.execute("tech", job["job_id"], operation)
        operation.assert_called_once()

    def test_missing_confirmation_and_timeout_are_unknown(self):
        for result in ({}, {"success": True, "outcome": "UNKNOWN"}):
            job = self.create()
            self.registry.execute("tech", job["job_id"], lambda: result)
            self.assertEqual(self.registry.get("tech", job["job_id"])["status"], "UNKNOWN")

    def test_executor_exception_is_unknown_and_not_retried(self):
        job = self.create()
        operation = Mock(side_effect=TimeoutError("private-password"))
        with self.assertRaises(TimeoutError):
            self.registry.execute("tech", job["job_id"], operation)
        operation.assert_called_once()
        record = self.registry.get("tech", job["job_id"])
        self.assertEqual(record["status"], "UNKNOWN")
        self.assertNotIn("private-password", str(record))

    def test_terminal_result_cannot_be_overwritten(self):
        job = self.create()
        self.registry.execute("tech", job["job_id"], lambda: {"success": True})
        self.assertFalse(self.registry.finish("tech", job["job_id"], "ERROR"))
        self.assertFalse(self.registry.begin("tech", job["job_id"]))

    def test_other_owner_cannot_deliver_or_update(self):
        job = self.create()
        self.assertFalse(self.registry.begin("other", job["job_id"]))
        self.assertFalse(self.registry.finish("other", job["job_id"], "SUCCESS"))

    def test_observer_does_not_reset_running_task(self):
        job = self.create()
        self.registry.begin("tech", job["job_id"])
        self.assertEqual(TaskRegistry(self.path).get("tech", job["job_id"])["status"], "RUNNING")

    def test_restart_reconciles_without_executing(self):
        job = self.create()
        self.registry.begin("tech", job["job_id"])
        restarted = TaskRegistry(self.path)
        restarted.acquire_runtime()
        try:
            self.assertEqual(restarted.recover_after_restart(), 1)
            self.assertEqual(restarted.get("tech", job["job_id"])["status"], "UNKNOWN")
            operation = Mock()
            with self.assertRaises(TaskRegistryError):
                restarted.execute("tech", job["job_id"], operation)
            operation.assert_not_called()
        finally:
            restarted.release_runtime()

    def test_two_executing_servers_cannot_recover_same_database(self):
        first, second = TaskRegistry(self.path), TaskRegistry(self.path)
        first.acquire_runtime()
        try:
            with self.assertRaises(TaskRegistryError):
                second.acquire_runtime()
        finally:
            first.release_runtime()
        second.acquire_runtime()
        second.release_runtime()

    def test_recovery_requires_runtime_lock(self):
        with self.assertRaises(TaskRegistryError):
            self.registry.recover_after_restart()

    def test_concurrent_device_reservation(self):
        def attempt(_):
            try:
                return self.create()["job_id"]
            except TaskRegistryError:
                return None
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            values = list(pool.map(attempt, range(16)))
        self.assertEqual(sum(value is not None for value in values), 1)

    def test_different_devices_can_run_concurrently(self):
        self.create()
        self.create(owner="other", ip="192.0.2.51", action="software_install")

    def test_registry_has_no_output_or_command_columns(self):
        with self.registry.connect() as db:
            columns = {row[1] for row in db.execute("PRAGMA table_info(tasks)")}
        self.assertFalse(columns & {"command", "stdout", "stderr", "password", "result", "message"})

    def test_invalid_owner_target_and_action_rejected(self):
        for owner, ip, action in [("", "192.0.2.1", "diagnose"), ("x", "bad", "diagnose"),
                                   ("x", "192.0.2.1", "format")]:
            with self.assertRaises(TaskRegistryError):
                self.registry.create(owner, ip, action)

    def test_file_backup_keeps_original_id_and_validates_report(self):
        jobs = FileBackupJobs(executor_factory=lambda: FakeWinRM(), thread_factory=InlineThread,
                              registry=self.registry)
        with patch.dict(os.environ, CONFIG, clear=True):
            job = jobs.start(IP, "TIMENOW", "12282", owner="tech")
        self.assertTrue(job["job_id"].startswith("files_"))
        saved = TaskRegistry(self.path).get("tech", job["job_id"])
        self.assertEqual(saved["status"], "SUCCESS")
        self.assertEqual(saved["evidence"], "BACKUP_REPORT_VALIDATED")

    def test_backup_transport_uncertainty_is_not_success(self):
        result = {"success": False, "outcome": "UNKNOWN", "stdout": "", "status_code": -1}
        jobs = FileBackupJobs(executor_factory=lambda: FakeWinRM(result), thread_factory=InlineThread,
                              registry=self.registry)
        with patch.dict(os.environ, CONFIG, clear=True):
            job = jobs.start(IP, "TIMENOW", "12282", owner="tech")
        self.assertEqual(self.registry.get("tech", job["job_id"])["status"], "UNKNOWN")


class TrackedChatOpsTests(RegistryFixture):
    def setUp(self):
        super().setUp()
        source = ast.parse((ROOT / "chatops/chatops.py").read_text(encoding="utf-8"))
        cls = next(n for n in source.body if isinstance(n, ast.ClassDef))
        selected = {"_queue_tracked_worker", "_cmd_tarefas", "_cmd_softwares", "_cmd_diagnostico"}
        nodes = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in selected]
        self.ns = dict(vars(typing), threading=types.SimpleNamespace(Thread=InlineThread, Event=threading.Event),
                       logger=Mock(), log=Mock(), re=__import__("re"),
                       new_trace_id=lambda: "trace", _normalize_token=lambda s: s.lower(),
                       TaskRegistryError=TaskRegistryError, WinRMResult=lambda **k: k)
        exec(compile(ast.Module(body=nodes, type_ignores=[]), "<tracked-chatops>", "exec"), self.ns)
        self.client = types.SimpleNamespace(task_registry=self.registry, active_jobs={},
            _extract_target_ip=lambda value: value, _last_user_ip={}, SOFTWARE_ALIASES={},
            bot=types.SimpleNamespace(send_direct_message=Mock()), winrm=Mock(),
            msg_builder=types.SimpleNamespace(success=lambda *args, **kw: str(args),
                                             error=lambda *args: str(args)))
        for name in selected:
            setattr(self.client, name, types.MethodType(self.ns[name], self.client))

    def test_installation_recorded_before_notification(self):
        self.client.winrm.run_script_file.return_value = {"success": True}
        reply = self.client._cmd_softwares("tech", ["192.0.2.50", "Chrome"])
        record = self.registry.recent("tech")[0]
        self.assertIn(record["job_id"], reply)
        self.assertEqual(record["status"], "SUCCESS")
        self.client.winrm.run_script_file.assert_called_once()
        self.assertIn(record["job_id"], self.client.bot.send_direct_message.call_args.args[1])

    def test_diagnostic_uncertainty_is_persisted_with_id(self):
        self.client._ensure_orchestrator = lambda: None
        self.client.orchestrator = Mock()
        self.client.orchestrator.run_diagnostics_only.return_value = {
            "success": False, "outcome": "UNKNOWN", "error": "timeout"}
        reply = self.client._cmd_diagnostico("tech", ["192.0.2.50"])
        job = self.registry.recent("tech")[0]
        self.assertEqual(job["status"], "UNKNOWN")
        self.assertIn(job["job_id"], reply)
        self.client.orchestrator.run_diagnostics_only.assert_called_once()

    def test_registry_failure_prevents_worker_start(self):
        self.client.task_registry = types.SimpleNamespace(create=Mock(side_effect=OSError("fixture-secret")))
        worker = Mock()
        with self.assertRaises(TaskRegistryError) as error:
            self.client._queue_tracked_worker("tech", "192.0.2.50", "diagnose", worker)
        worker.assert_not_called()
        self.assertNotIn("fixture-secret", str(error.exception))

    def test_job_query_cannot_read_another_technician(self):
        job = self.create()
        self.assertIn("Nenhuma", self.client._cmd_tarefas("other", [job["job_id"]]))
        self.assertIn("QUEUED", self.client._cmd_tarefas("tech", [job["job_id"]]))

    def test_worker_exception_remains_queryable(self):
        def broken(job_id):
            raise RuntimeError("fixture-secret")
        job = self.client._queue_tracked_worker("tech", "192.0.2.50", "diagnose", broken)
        saved = self.registry.get("tech", job["job_id"])
        self.assertEqual(saved["status"], "ERROR")
        self.assertEqual(saved["evidence"], "NOT_STARTED")


if __name__ == "__main__":
    unittest.main()
