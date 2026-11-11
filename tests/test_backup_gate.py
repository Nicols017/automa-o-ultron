"""Signed Macrium attestation gate tests; no backup files are opened or modified."""
import hashlib
import hmac
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from core.backup_gate import BackupNotVerified, MacriumBackupGate


class BackupGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "verifier.key"
        self.key = b"M" * 64
        self.path.write_bytes(self.key)
        if os.name == "posix":
            self.path.chmod(0o600)
        self.share = r"\\192.0.2.112\Backups"
        self.gate = MacriumBackupGate(key_file=str(self.path), backup_share=self.share)
        self.now = 1800000000.0
        self.doc = {
            "kind": "macrium_reflect_8_image",
            "verify_method": "macrium_reflect_8_verify",
            "verification_status": "SUCCESS",
            "verifier_id": "trusted-macrium-verifier",
            "serial": "SN-100",
            "source_ip": "192.0.2.50",
            "verified_at": self.now - 100,
            "issued_at": self.now - 10,
            "expires_at": self.now + 3600,
            "storage_path": self.share + r"\client\disk-2026.mrimg",
            "sha256": "e" * 64,
            "size_bytes": 1073741824,
        }

    def tearDown(self):
        self.temp.cleanup()

    def signed(self, document=None):
        doc = document if document is not None else self.doc
        signature = hmac.new(
            self.key,
            json.dumps(doc, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return {"evidence": doc, "signature": signature}

    def check(self, payload, serial="SN-100", ip="192.0.2.50"):
        return self.gate.validate(payload, serial, ip, now=self.now)

    def test_fresh_signed_macrium_verify_attestation(self):
        self.assertEqual(self.check(self.signed())["serial"], "SN-100")

    def test_missing_or_forged_signature_denied(self):
        with self.assertRaises(BackupNotVerified):
            self.check({"evidence": self.doc})
        forged = self.signed()
        forged["evidence"] = {**self.doc, "verification_status": "SUCCESS", "serial": "SN-999"}
        with self.assertRaises(BackupNotVerified):
            self.check(forged)

    def test_wrong_machine_denied_even_if_validly_signed(self):
        with self.assertRaises(BackupNotVerified):
            self.check(self.signed(), serial="SN-999")
        with self.assertRaises(BackupNotVerified):
            self.check(self.signed(), ip="192.0.2.99")

    def test_macrium_not_verified_denied(self):
        doc = {**self.doc, "verification_status": "FAIL"}
        with self.assertRaises(BackupNotVerified):
            self.check(self.signed(doc))
        doc["verification_status"] = "SUCCESS"
        doc["verify_method"] = "robocopy"
        with self.assertRaises(BackupNotVerified):
            self.check(self.signed(doc))

    def test_expired_or_future_evidence_denied(self):
        with self.assertRaises(BackupNotVerified):
            self.check(self.signed({**self.doc, "expires_at": self.now - 2}))
        with self.assertRaises(BackupNotVerified):
            self.check(self.signed({**self.doc, "verified_at": self.now + 999}))

    def test_path_must_be_in_trusted_storage_and_image(self):
        for p in (
            r"\\other\Backups\client\disk.mrimg",
            self.share + r"\..\other\disk.mrimg",
            self.share + r"\client\robocopy.log",
        ):
            with self.subTest(path=p), self.assertRaises(BackupNotVerified):
                self.check(self.signed({**self.doc, "storage_path": p}))

    def test_sha_and_size_are_required(self):
        for updates in ({"sha256": ""}, {"sha256": "a" * 33},
                        {"size_bytes": 0}, {"size_bytes": True}):
            with self.subTest(updates=updates), self.assertRaises(BackupNotVerified):
                self.check(self.signed({**self.doc, **updates}))

    def test_missing_key_fails_closed(self):
        self.gate.key_file = str(self.path) + ".missing"
        with self.assertRaises(BackupNotVerified):
            self.check(self.signed())

    def test_old_macrium_verify_is_not_reusable_forever(self):
        doc = {**self.doc, "verified_at": self.now - 172800, "issued_at": self.now - 10}
        with self.assertRaises(BackupNotVerified):
            self.check(self.signed(doc))


if __name__ == "__main__":
    unittest.main()
