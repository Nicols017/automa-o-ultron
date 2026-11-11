"""Offline tests for Ultron -> Windows MRVerify, without network/storage access."""
import json
import os
import unittest
from unittest.mock import patch

from core.macrium_remote import (
    MacriumBridgeError, MacriumVerificationJobs,
    read_configuration, validate_image_path, verify_on_windows,
)

ROOT = r"\\192.168.57.112\backups3"
IMAGE = ROOT + r"\12282 - TIMENOW NÃO APAGAR\BADE766865EE753C-00-00.mrimg"
LOCAL = r"C:\Users\nicolas.silva\Desktop\12282 - TIMENOW NÃO APAGAR\BADE766865EE753C-00-00.mrimg"
LOCAL_ROOT = r"C:\Users\nicolas.silva\Desktop"


class FakeWinRM:
    def __init__(self, state="success"):
        self.state = state
        self.calls = []

    def run_script_file(self, ip, script, params):
        self.calls.append((ip, script, dict(params)))
        report = {
            "verified": self.state == "success",
            "reason": "MRVerify retornou sucesso." if self.state == "success" else "Arquivo corrompido",
            "exit_code": 0 if self.state == "success" else 1,
            "image_path": params["ImagePath"],
            "log_path": r"C:\ProgramData\Ultron\MacriumVerifyLogs\verify.txt",
            "size_bytes": 52562075967,
            "verified_at": "2026-11-11T08:00:00Z",
        }
        if self.state == "wrong-image":
            report["image_path"] = ROOT + r"\outro.mrimg"
        if self.state == "corrupt":
            return {"success": True, "status_code": 0,
                    "stdout": "ULTRON_MACRIUM_JSON:{invalid json"}
        if self.state == "missing":
            return {"success": True, "status_code": 0, "stdout": ""}
        return {
            "success": self.state in ("success", "wrong-image"),
            "status_code": 0 if self.state in ("success", "wrong-image") else 1,
            "stdout": "MRVerify output\nULTRON_MACRIUM_JSON:" + json.dumps(report),
        }


class InlineThread:
    def __init__(self, target, daemon=False):
        self.target = target

    def start(self):
        self.target()


class WaitingThread:
    def __init__(self, target, daemon=False):
        self.target = target

    def start(self):
        return  # Keep job QUEUED: simulate ongoing worker.


class MacriumRemoteTests(unittest.TestCase):
    def test_unc_allowed(self):
        self.assertEqual(validate_image_path(IMAGE, [ROOT]), ROOT)

    def test_local_copy_allowed_only_if_explicitly_configured(self):
        with self.assertRaises(MacriumBridgeError):
            validate_image_path(LOCAL, [ROOT])
        self.assertEqual(validate_image_path(LOCAL, [LOCAL_ROOT]), LOCAL_ROOT)

    def test_wrong_share_or_traversal_rejected(self):
        for bad in (
            r"\\192.168.57.112\backups3-evil\a.mrimg",
            ROOT + r"\..\other\a.mrimg",
            r"C:\Windows\a.mrimg",
            ROOT + r"\file.txt",
            ROOT + r"\file.mrimg:other",
            ROOT + r"\$(whoami).mrimg",
            ROOT + r"\file.mrimg"";del C:\Windows",
        ):
            with self.subTest(path=bad), self.assertRaises(MacriumBridgeError):
                validate_image_path(bad, [ROOT, LOCAL_ROOT])

    def test_success_single_windows_call_no_agent_or_cleanup(self):
        fake = FakeWinRM()
        result = verify_on_windows(IMAGE, host="192.168.57.77",
                                   roots=[ROOT], executor=fake)
        self.assertTrue(result["verified"])
        self.assertFalse(result["restored"])
        self.assertFalse(result["mdt_authorized"])
        self.assertEqual(fake.calls, [(
            "192.168.57.77", "Verify-MacriumImage.ps1",
            {"ImagePath": IMAGE, "AllowedRoot": ROOT},
        )])

    def test_failed_verify_does_not_claim_success(self):
        fake = FakeWinRM("failure")
        with self.assertRaises(MacriumBridgeError):
            verify_on_windows(IMAGE, host="192.168.57.77",
                              roots=[ROOT], executor=fake)
        self.assertEqual(len(fake.calls), 1)

    def test_missing_invalid_or_wrong_result_denied(self):
        for state in ("corrupt", "missing", "wrong-image"):
            with self.subTest(state=state), self.assertRaises(MacriumBridgeError):
                verify_on_windows(IMAGE, host="192.168.57.77",
                                  roots=[ROOT], executor=FakeWinRM(state))

    def test_disabled_without_configuration(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(MacriumBridgeError):
                read_configuration()

    def test_enabled_requires_fixed_host_and_allowed_root(self):
        with patch.dict(os.environ, {
            "ULTRON_MACRIUM_VERIFY_ENABLED": "1",
            "ULTRON_MACRIUM_ALLOWED_ROOTS": ROOT,
        }, clear=True):
            with self.assertRaises(MacriumBridgeError):
                read_configuration()
            os.environ["ULTRON_MACRIUM_VERIFIER_HOST"] = "192.168.57.77"
            self.assertEqual(read_configuration()["host"], "192.168.57.77")

    def test_completed_job_and_callback(self):
        fake = FakeWinRM()
        out = []
        env = {
            "ULTRON_MACRIUM_VERIFY_ENABLED": "1",
            "ULTRON_MACRIUM_VERIFIER_HOST": "192.168.57.77",
            "ULTRON_MACRIUM_ALLOWED_ROOTS": ROOT,
        }
        with patch.dict(os.environ, env, clear=True):
            mgr = MacriumVerificationJobs(
                executor_factory=lambda: fake,
                thread_factory=InlineThread,
            )
            job = mgr.start(IMAGE, on_done=lambda value: out.append(value))
        self.assertEqual(job["status"], "SUCCESS")
        self.assertEqual(out[0]["result"]["mdt_authorized"], False)
        self.assertEqual(len(fake.calls), 1)

    def test_only_one_active_job(self):
        env = {
            "ULTRON_MACRIUM_VERIFY_ENABLED": "1",
            "ULTRON_MACRIUM_VERIFIER_HOST": "192.168.57.77",
            "ULTRON_MACRIUM_ALLOWED_ROOTS": ROOT,
        }
        with patch.dict(os.environ, env, clear=True):
            mgr = MacriumVerificationJobs(thread_factory=WaitingThread)
            first = mgr.start(IMAGE)
            self.assertEqual(first["status"], "QUEUED")
            with self.assertRaises(MacriumBridgeError):
                mgr.start(IMAGE)

    def test_path_rejected_before_windows_access(self):
        fake = FakeWinRM()
        with self.assertRaises(MacriumBridgeError):
            verify_on_windows(r"C:\Windows\temp\payload.mrimg",
                              host="192.168.57.77", roots=[ROOT], executor=fake)
        self.assertEqual(fake.calls, [])


if __name__ == "__main__":
    unittest.main()
