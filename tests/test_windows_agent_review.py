"""Offline behavior tests: fake session never opens a socket."""
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch
from core.winrm_diagnostics import classify_winrm_error

ROOT = Path(__file__).resolve().parents[1]
# Load executor in isolation without installing network clients or importing the app.
spec = importlib.util.spec_from_file_location("review_executor", ROOT / "core/winrm_executor.py")
executor = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, {"winrm": types.SimpleNamespace(Session=object),
                              "yaml": types.SimpleNamespace(safe_load=lambda _: {})}):
    spec.loader.exec_module(executor)


class WinRMReviewTests(unittest.TestCase):
    def setUp(self):
        self.client = executor.WinRMExecutor(str(ROOT / "does-not-exist.yaml"))

    def test_no_guessed_credentials(self):
        self.assertEqual(self.client._get_credential_candidates("example.invalid"), [])

    def test_explicit_identity_overrides_cache(self):
        self.client.set_host_credentials("host", "old", "old")
        self.assertEqual(self.client._get_credential_candidates("host", "new", "secret"),
                         [("new", "secret")])

    def test_missing_credentials_never_connects(self):
        with patch.object(self.client, "get_session") as session:
            self.assertEqual(self.client.run_powershell_code("host", "x")["error_code"],
                             "CREDENTIALS_MISSING")
            session.assert_not_called()

    def test_timeout_runs_once_and_does_not_leak_secret(self):
        session = unittest.mock.Mock()
        session.run_ps.side_effect = TimeoutError("timeout secret-password")
        with patch.object(self.client, "get_session", return_value=session):
            result = self.client.run_powershell_code("host", "script", "user", "pass")
        session.run_ps.assert_called_once_with("script")
        self.assertEqual(result["outcome"], "UNKNOWN")
        self.assertFalse(result["retry_safe"])
        self.assertNotIn("secret-password", str(result))

    def test_script_nonzero_is_not_auth_failure_and_preserves_text(self):
        session = unittest.mock.Mock()
        session.run_ps.return_value = types.SimpleNamespace(status_code=1, std_out=b"",
                                                           std_err=b"access is denied")
        script = "@'\n# keep this data\n'@"
        with patch.object(self.client, "get_session", return_value=session):
            result = self.client.run_powershell_code("host", script, "u", "p")
        session.run_ps.assert_called_once_with(script)
        self.assertFalse(result["auth_failed"])
        self.assertEqual(result["status_code"], 1)

    def test_tls_validation_and_encryption(self):
        with patch.object(executor.winrm, "Session", create=True) as session:
            self.client.get_session("host", "u", "p")
        self.assertEqual(session.call_args.args[0], "https://host:5986/wsman")
        self.assertEqual(session.call_args.kwargs["server_cert_validation"], "validate")
        self.assertEqual(session.call_args.kwargs["message_encryption"], "always")

    def test_http_requires_opt_in(self):
        self.client.config = {"winrm": {"scheme": "http"}}
        with self.assertRaises(ValueError):
            self.client.get_session("host")

    def test_script_parameters_are_literals(self):
        with patch.object(self.client, "run_powershell_code", return_value={}) as run:
            self.client.run_script_file("host", "Search-Packages.ps1",
                                        {"Query": "$(Get-Process)'hello"})
        self.assertIn("-Query '$(Get-Process)''hello'", run.call_args.args[1])

    def test_invalid_parameter_name_rejected(self):
        with self.assertRaises(ValueError):
            self.client.run_script_file("host", "Search-Packages.ps1", {"x;whoami": "y"})

    def test_classifications(self):
        for message, code in [("401", "AUTHENTICATION"), ("access is denied", "AUTHORIZATION"),
                              ("certificate verify", "TLS"), ("getaddrinfo", "DNS"),
                              ("10061 refused", "LISTENER"), ("SPN", "KERBEROS")]:
            with self.subTest(code=code):
                self.assertEqual(classify_winrm_error(message)["error_code"], code)

    def test_agent_has_no_automatic_network_provisioning(self):
        source = (ROOT / "agent/UltronAgent.cs").read_text(encoding="utf-8")
        for forbidden in ("winrm quickconfig", "TrustedHosts=", "net user", "Set-NetConnectionProfile"):
            self.assertNotIn(forbidden, source)
        self.assertIn("req.AllowAutoRedirect = false", source)


if __name__ == "__main__":
    unittest.main()
