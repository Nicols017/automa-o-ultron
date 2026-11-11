"""Offline tests for secure TrueConf pre-format FILE backup workflow."""
import json
import os
import unittest
from unittest.mock import patch

from core.preformat_files_backup import (
    FileBackupError, FileBackupJobs, _parse_result,
    read_file_backup_configuration, validate_file_backup_request,
)

SHARE = r"\\192.168.57.112\backups3"
CONFIG = {
    "ULTRON_FILES_BACKUP_ENABLED": "1",
    "ULTRON_FILES_BACKUP_SHARE": SHARE,
    "ULTRON_FILES_BACKUP_ALLOWED_SUBNET": "192.168.57.0/24",
}
IP = "192.168.57.50"


def make_report(*, failed=False, changes=None):
    report = {
        "status": "SUCCESS",
        "type": "selected_user_files",
        "image_backup": False,
        "mdt_authorized": False,
        "reason": "ok",
        "client": "TIMENOW",
        "ticket": "12282",
        "destination": SHARE + r"\12282 - TIMENOW\ultron-files-20261111-1a2b3c4d",
        "profiles_found": 1,
        "folders_copied": 4,
        "files_at_destination": 100,
        "bytes_at_destination": 90000,
        "run_id": "abcdef0123456789abcdef0123456789",
        "robocopy_exit_codes": [0, 1, 3],
    }
    report.update(changes or {})
    return {
        "status_code": 1 if failed else 0,
        "success": not failed,
        "stdout": "ULTRON_FILES_BACKUP_JSON:" + json.dumps(report),
    }


class FakeWinRM:
    def __init__(self, result=None):
        self.result = result or make_report()
        self.calls = []

    def run_script_file(self, ip, script, params):
        self.calls.append((ip, script, params))
        return self.result


class InlineThread:
    def __init__(self, target, daemon=False):
        self.target = target

    def start(self):
        self.target()


class WaitingThread:
    def __init__(self, target, daemon=False):
        self.target = target

    def start(self):
        pass


class FileBackupUnitTests(unittest.TestCase):
    def test_disabled_by_default(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(FileBackupError):
            read_file_backup_configuration()

    def test_storage_configuration_mandatory(self):
        with patch.dict(os.environ, {"ULTRON_FILES_BACKUP_ENABLED": "1"}, clear=True):
            with self.assertRaises(FileBackupError):
                read_file_backup_configuration()

    def test_client_ticket_and_target_validation(self):
        with patch.dict(os.environ, CONFIG, clear=True):
            config = read_file_backup_configuration()
        validate_file_backup_request(IP, "TIMENOW", "12282", config)
        for addr,client,ticket in [
            ("192.168.57.43", "TIMENOW", "12282"),
            ("192.168.57.87", "TIMENOW", "12282"),
            ("192.168.57.112", "TIMENOW", "12282"),
            ("192.168.2.55", "TIMENOW", "12282"),
            (IP, "$(Get-Item C:)", "12282"),
            (IP, "CLIENT/EVIL", "12282"),
            (IP, "TIMENOW", "../12282"),
            (IP, "TIMENOW", ""),
        ]:
            with self.subTest(addr=addr,client=client,ticket=ticket), self.assertRaises(FileBackupError):
                validate_file_backup_request(addr, client, ticket, config)

    def test_success_report_requires_real_copy(self):
        report = _parse_result(make_report(), client="TIMENOW", ticket="12282")
        self.assertEqual(report["files_at_destination"], 100)
        self.assertFalse(report["mdt_authorized"])
        self.assertFalse(report["image_backup"])

    def test_error_codes_and_invalid_reports_rejected(self):
        for payload in [
            make_report(failed=True),
            make_report(changes={"robocopy_exit_codes": [8]}),
            make_report(changes={"files_at_destination": 0}),
            make_report(changes={"status": "ERROR"}),
            make_report(changes={"image_backup": True}),
            make_report(changes={"mdt_authorized": True}),
            make_report(changes={"ticket": "12345"}),
            make_report(changes={"run_id": None}),
            {"success": True, "status_code": 0, "stdout": "anything"},
        ]:
            with self.subTest(case=payload), self.assertRaises(FileBackupError):
                _parse_result(payload, client="TIMENOW", ticket="12282")

    def test_start_returns_result_and_notifies(self):
        fake = FakeWinRM()
        notifications = []
        with patch.dict(os.environ, CONFIG, clear=True):
            jobs = FileBackupJobs(
                executor_factory=lambda: fake,
                thread_factory=InlineThread,
            )
            started = jobs.start(IP, "TIMENOW", "12282", on_done=notifications.append)
        self.assertEqual(started["status"], "SUCCESS")
        self.assertFalse(notifications[0]["result"]["mdt_authorized"])
        self.assertEqual(fake.calls[0][1], "Backup-UserData.ps1")
        self.assertEqual(fake.calls[0][2]["TargetShare"], SHARE)

    def test_busy_job_blocks_duplicate_copy(self):
        with patch.dict(os.environ, CONFIG, clear=True):
            jobs = FileBackupJobs(thread_factory=WaitingThread)
            self.assertEqual(jobs.start(IP, "TIMENOW", "12282")["status"], "QUEUED")
            with self.assertRaises(FileBackupError):
                jobs.start(IP, "TIMENOW", "12282")

    def test_failed_worker_reports_error_not_success(self):
        fake = FakeWinRM(make_report(failed=True))
        with patch.dict(os.environ, CONFIG, clear=True):
            jobs = FileBackupJobs(
                executor_factory=lambda: fake, thread_factory=InlineThread,
            )
            job = jobs.start(IP, "TIMENOW", "12282")
        self.assertEqual(job["status"], "ERROR")
        self.assertFalse(job["result"]["success"])


if __name__ == "__main__":
    unittest.main()
