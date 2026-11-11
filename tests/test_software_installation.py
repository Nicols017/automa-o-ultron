"""Offline assessment tests: fake installation/query responses, no native commands."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
from core.software_installation import (
    INSTALL_MARKER, VERIFY_MARKER, assess_installation, install_and_verify,
    format_installation, validated_summary,
)
from core.task_registry import TaskRegistry

PACKAGES = ["Google.Chrome", "Microsoft.Office"]
RUN = "a" * 32


def reports(packages=PACKAGES, present=None, failed=None, run_id=RUN):
    present = set(packages if present is None else present)
    failed = set(failed or [])
    attempts = [{"requested": p, "manager": "winget", "exit_code": 5 if p in failed else 0,
                 "reported_success": p not in failed} for p in packages]
    found = [{"requested": p, "status": "CONFIRMED_PRESENT" if p in present else "UNCONFIRMED",
              "version": "123.0" if p in present else None} for p in packages]
    return (
        dict(success=not failed, status_code=1 if failed else 0,
             stdout=INSTALL_MARKER + json.dumps(dict(schema_version=1, run_id=run_id, packages=attempts))),
        dict(success=True, status_code=0,
             stdout=VERIFY_MARKER + json.dumps(dict(schema_version=1, run_id=run_id, packages=found))),
    )


class AssessmentTests(unittest.TestCase):
    def test_all_confirmed_contains_versions(self):
        installed, verified = reports()
        result = assess_installation(installed, verified, PACKAGES, RUN)
        self.assertTrue(result["success"])
        self.assertEqual(validated_summary(result)[0], "SUCCESS")
        self.assertEqual([p["version"] for p in result["package_results"]], ["123.0", "123.0"])

    def test_exit_zero_without_presence_never_claims_success(self):
        installed, verified = reports(present=[])
        result = assess_installation(installed, verified, PACKAGES, RUN)
        self.assertFalse(result["success"])
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertNotIn("SOFTWARES INSTALADOS", format_installation(result))

    def test_partial_success_lists_each_package(self):
        installed, verified = reports(present=["Google.Chrome"], failed=["Microsoft.Office"])
        result = assess_installation(installed, verified, PACKAGES, RUN)
        self.assertEqual(result["status"], "PARTIAL")
        text = format_installation(result)
        self.assertIn("Google.Chrome: encontrado, versao 123.0", text)
        self.assertIn("Microsoft.Office: presenca/versao nao confirmadas", text)

    def test_program_present_despite_installer_error_is_not_total_success(self):
        installed, verified = reports(failed=["Google.Chrome"])
        result = assess_installation(installed, verified, PACKAGES, RUN)
        self.assertFalse(result["success"])
        self.assertEqual(result["package_results"][0]["status"], "PRESENT_WITH_UNCONFIRMED_INSTALL")

    def test_known_installer_failure_is_not_proof_of_absence(self):
        installed, verified = reports(present=[], failed=PACKAGES)
        result = assess_installation(installed, verified, PACKAGES, RUN)
        self.assertEqual(result["status"], "ERROR")
        self.assertIn("nao confirmadas", format_installation(result))

    def test_legacy_no_report_never_promotes_success(self):
        _, verified = reports()
        result = assess_installation({"success": True, "status_code": 0, "stdout": "installed"}, verified, PACKAGES, RUN)
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertFalse(result["success"])

    def test_malformed_duplicate_or_wrong_run_report_rejected(self):
        installed, verified = reports()
        for text in ("bad", verified["stdout"] + "\n" + verified["stdout"],
                     verified["stdout"].replace(RUN, "b" * 32),
                     VERIFY_MARKER + '{"schema_version":1,"schema_version":1}'):
            with self.subTest(text=text[:35]):
                result = assess_installation(installed, dict(verified, stdout=text), PACKAGES, RUN)
                self.assertFalse(result["success"])

    def test_missing_duplicate_or_extra_package_rejected(self):
        installed, verified = reports()
        obj = json.loads(verified["stdout"][len(VERIFY_MARKER):])
        for rows in (obj["packages"][:1], [obj["packages"][0]] * 2,
                     obj["packages"] + [dict(obj["packages"][0], requested="Other.App")]):
            payload = dict(obj, packages=rows)
            result = assess_installation(installed, dict(verified, stdout=VERIFY_MARKER + json.dumps(payload)), PACKAGES, RUN)
            self.assertFalse(result["success"])

    def test_unknown_missing_or_injected_version_rejected(self):
        installed, verified = reports()
        obj = json.loads(verified["stdout"][len(VERIFY_MARKER):])
        for version in (None, "Unknown", "latest", "1.0\nprivate-secret", "<script>"):
            payload = copy.deepcopy(obj)
            payload["packages"][0]["version"] = version
            result = assess_installation(installed, dict(verified, stdout=VERIFY_MARKER + json.dumps(payload)), PACKAGES, RUN)
            self.assertFalse(result["success"])
            self.assertNotIn("private-secret", str(result))

    def test_failed_export_or_boolean_exit_is_not_confirmation(self):
        installed, verified = reports()
        for code in (1, -1, False):
            self.assertFalse(assess_installation(installed, dict(verified, status_code=code), PACKAGES, RUN)["success"])

    def test_nonzero_root_exit_cannot_be_total_success(self):
        installed, verified = reports()
        self.assertFalse(assess_installation(dict(installed, status_code=2, success=False), verified, PACKAGES, RUN)["success"])

    def test_timeout_does_not_trigger_install_retry_or_query(self):
        executor = Mock()
        executor.run_script_file.return_value = {"success": False, "outcome": "UNKNOWN", "status_code": -1}
        result = install_and_verify(executor, "192.0.2.50", PACKAGES)
        self.assertEqual(result["status"], "UNKNOWN")
        executor.run_script_file.assert_called_once()
        self.assertEqual(executor.run_script_file.call_args.args[1], "Install-UnifiedPackages.ps1")

    def test_install_exception_is_sanitized_and_not_retried(self):
        executor = Mock()
        executor.run_script_file.side_effect = RuntimeError("private-password")
        result = install_and_verify(executor, "192.0.2.50", PACKAGES)
        self.assertNotIn("private-password", str(result))
        executor.run_script_file.assert_called_once()

    def test_only_one_install_and_one_query_with_same_nonce(self):
        calls = []
        def execute(ip, script, params):
            calls.append((script, params))
            installed, verified = reports(run_id=params["RunId"])
            return installed if script == "Install-UnifiedPackages.ps1" else verified
        executor = Mock()
        executor.run_script_file.side_effect = execute
        result = install_and_verify(executor, "192.0.2.50", PACKAGES)
        self.assertTrue(result["success"])
        self.assertEqual([call[0] for call in calls], ["Install-UnifiedPackages.ps1", "Verify-InstalledPackages.ps1"])
        self.assertEqual(calls[0][1]["RunId"], calls[1][1]["RunId"])

    def test_invalid_requests_do_not_execute(self):
        for packages in ([], ["--override"], ["x;whoami"], ["$(secret)"], ["a"] * 51):
            executor = Mock()
            with self.assertRaises(ValueError):
                install_and_verify(executor, "192.0.2.50", packages)
            executor.run_script_file.assert_not_called()

    def test_package_details_persist_and_are_owner_filtered(self):
        installed, verified = reports(present=["Google.Chrome"], failed=["Microsoft.Office"])
        result = assess_installation(installed, verified, PACKAGES, RUN)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "tasks.sqlite3"
            registry = TaskRegistry(path)
            job = registry.create("tech", "192.0.2.50", "software_install")
            registry.execute("tech", job["job_id"], lambda: result)
            saved = TaskRegistry(path).get("tech", job["job_id"])
            self.assertEqual(saved["status"], "PARTIAL")
            self.assertEqual(saved["package_results"][0]["version"], "123.0")
            self.assertIsNone(registry.get("other", job["job_id"]))

    def test_verified_success_has_specific_persistent_evidence(self):
        installed, verified = reports()
        result = assess_installation(installed, verified, PACKAGES, RUN)
        with tempfile.TemporaryDirectory() as temp:
            registry = TaskRegistry(Path(temp) / "tasks.sqlite3")
            job = registry.create("tech", "192.0.2.50", "software_install")
            registry.execute("tech", job["job_id"], lambda: result)
            saved = registry.get("tech", job["job_id"])
            self.assertEqual(saved["status"], "SUCCESS")
            self.assertEqual(saved["evidence"], "SOFTWARE_PRESENCE_VERIFIED")
            self.assertEqual(saved["package_results"][0]["version"], "123.0")

    def test_generic_executor_success_cannot_mark_software_verified(self):
        with tempfile.TemporaryDirectory() as temp:
            registry = TaskRegistry(Path(temp) / "tasks.sqlite3")
            job = registry.create("tech", "192.0.2.50", "software_install")
            registry.execute("tech", job["job_id"], lambda: {"success": True})
            self.assertEqual(registry.get("tech", job["job_id"])["status"], "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
