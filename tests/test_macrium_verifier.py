"""Offline Macrium verifier tests. Fake MRVerify.exe; NO Windows or real images."""
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from core.backup_gate import MacriumBackupGate
from verifier.macrium_verify import (
    VerificationError,
    secure_windows_share_path,
    verify_and_attest,
)


class MacriumVerifierTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="macrium-verifier-mock-")
        self.root = Path(self.temp.name)
        self.image = self.root / "test.mrimg"
        self.image.write_bytes(b"FAKE-DATA-NOT-A-REAL-MACRIUM-IMAGE")
        self.exe = self.root / "MRVerify.exe"
        self.exe.write_bytes(b"MOCK-NOT-EXECUTED")
        self.key = self.root / "verifier.key"
        self.key.write_bytes(b"z" * 64)
        if os.name == "posix":
            self.key.chmod(0o600)
        self.share = r"\\192.0.2.112\Backups"
        self.unc = self.share + r"\client\test.mrimg"
        self.inventory = self.root / "devices.json"
        self.inventory.write_text(json.dumps({"devices": {"SN-100": {
            "source_ip": "192.0.2.50",
            "image_path": self.unc,
        }}}), encoding="utf-8")
        self.output = self.root / "out"
        self.calls = []
        self.mode = "success"
        self.now = 1800000000

    def tearDown(self):
        self.temp.cleanup()

    def fake_runner(self, args, **kwargs):
        self.calls.append((list(args), kwargs))
        log = Path(args[args.index("--logfile") + 1])
        if self.mode == "success":
            log.write_text("test.mrimg - Verify Success\n", encoding="utf-8")
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if self.mode == "failure":
            log.write_text("test.mrimg - Verify Failure\n", encoding="utf-8")
            return SimpleNamespace(returncode=1, stdout="", stderr="")
        if self.mode == "incomplete":
            log.write_text(
                "test.mrimg Verify Success\nBackup set is not complete\n",
                encoding="utf-8",
            )
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if self.mode == "tampered":
            log.write_text("test.mrimg - Verify Success\n", encoding="utf-8")
            self.image.write_bytes(self.image.read_bytes() + b"TAMPER")
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if self.mode == "no-log":
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        raise AssertionError("Unknown fake-runner mode")

    def verify(self):
        return verify_and_attest(
            serial="SN-100", inventory_file=self.inventory,
            allowed_share=self.share,
            signing_key_file=self.key,
            output_directory=self.output,
            verifier_id="verification-lab",
            mrverify_executable=self.exe,
            runner=self.fake_runner,
            now=lambda: self.now,
            image_resolver=lambda path: self.image,
        )

    def test_successful_fake_run_creates_gate_compatible_signed_evidence(self):
        path = self.verify()
        body = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(body["evidence"]["sha256"],
                         hashlib.sha256(self.image.read_bytes()).hexdigest())
        self.assertEqual(body["evidence"]["serial"], "SN-100")
        self.assertEqual(body["evidence"]["mrverify_exit_code"], 0)
        self.assertEqual(body["evidence"]["source_ip"], "192.0.2.50")
        gate = MacriumBackupGate(key_file=str(self.key), backup_share=self.share)
        self.assertEqual(gate.validate(body, "SN-100", "192.0.2.50",
                                       now=self.now)["verification_status"], "SUCCESS")
        cmd, kwargs = self.calls[0]
        self.assertEqual(cmd[0], str(self.exe))
        self.assertIn("--set", cmd)
        self.assertIn("--logfile", cmd)
        self.assertNotIn("--fix", cmd)
        self.assertFalse(kwargs["check"])

    def test_failed_verification_does_not_produce_evidence(self):
        self.mode = "failure"
        with self.assertRaises(VerificationError):
            self.verify()
        self.assertEqual(list(self.output.glob("*evidence*")), [])

    def test_success_exit_with_incomplete_set_is_rejected(self):
        self.mode = "incomplete"
        with self.assertRaises(VerificationError):
            self.verify()
        self.assertEqual(list(self.output.glob("*evidence*")), [])

    def test_missing_log_denied(self):
        self.mode = "no-log"
        with self.assertRaises(VerificationError):
            self.verify()

    def test_image_changed_during_verification_denied(self):
        self.mode = "tampered"
        with self.assertRaises(VerificationError):
            self.verify()

    def test_no_binary_no_verification(self):
        self.exe.unlink()
        with self.assertRaises(VerificationError):
            self.verify()
        self.assertEqual(self.calls, [])

    def test_empty_image_denied(self):
        self.image.write_bytes(b"")
        with self.assertRaises(VerificationError):
            self.verify()
        self.assertEqual(self.calls, [])

    def test_unknown_serial_denied(self):
        self.inventory.write_text(json.dumps({"devices": {}}), encoding="utf-8")
        with self.assertRaises(VerificationError):
            self.verify()
        self.assertEqual(self.calls, [])

    def test_windows_share_restrictions(self):
        for bad in (
            r"\\192.0.2.112\Backups-evil\test.mrimg",
            r"\\192.0.2.112\Backups\..\test.mrimg",
            r"C:\Backups\test.mrimg",
            r"\\other\Backups\test.mrimg",
            r"\\192.0.2.112\Backups\file.mrimg:bad",
            r"\\192.0.2.112\Backups\test.vhdx",
        ):
            with self.subTest(path=bad), self.assertRaises(VerificationError):
                secure_windows_share_path(bad, self.share)

    def test_signed_evidence_is_rejected_for_wrong_device(self):
        path = self.verify()
        proof = json.loads(path.read_text(encoding="utf-8"))
        gate = MacriumBackupGate(key_file=str(self.key), backup_share=self.share)
        with self.assertRaises(Exception):
            gate.validate(proof, "SN-999", "192.0.2.50", now=self.now)

    def test_linux_cli_refuses_real_mrverify(self):
        # A CLI can only run on a designated Windows workstation.
        if os.name == "nt":
            self.skipTest("Windows-only CLI is enabled on Windows")
        from verifier.macrium_verify import main
        self.assertEqual(main([
            "--serial", "SN-100", "--inventory", str(self.inventory),
            "--share", self.share, "--signing-key", str(self.key),
            "--output", str(self.output), "--verifier-id", "verification-lab",
        ]), 2)


if __name__ == "__main__":
    unittest.main()
