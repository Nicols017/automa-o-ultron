"""Offline tests for per-device authentication. No network or live agents."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from fastapi import HTTPException
from core.agent_auth import AgentAuthenticator, require_operator


class AgentAuthTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "agents.json"
        self.tokens = {"serial-a": "a" * 64, "serial-b": "b" * 64}
        self.path.write_text(json.dumps(self.tokens), encoding="utf-8")
        if os.name == "posix":
            self.path.chmod(0o600)
        self.auth = AgentAuthenticator(credentials_file=str(self.path))

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def request(serial="serial-a", token=None, scheme="https"):
        headers = {
            "x-ultron-agent-id": serial,
            "authorization": "Bearer " + (token or "a" * 64),
        }
        return SimpleNamespace(url=SimpleNamespace(scheme=scheme), headers=headers)

    def assert_denied(self, request, code, expected=None):
        with self.assertRaises(HTTPException) as err:
            self.auth.authenticate(request, expected_agent=expected)
        self.assertEqual(err.exception.status_code, code)

    def test_valid_enrolled_agent(self):
        self.assertEqual(self.auth.authenticate(self.request(), "serial-a"), "serial-a")

    def test_reject_missing_and_wrong_token(self):
        self.assert_denied(self.request(token="wrong"), 401)
        req = self.request()
        del req.headers["authorization"]
        self.assert_denied(req, 401)

    def test_reject_identity_impersonation_and_wrong_target(self):
        self.assert_denied(self.request(serial="serial-b"), 401)
        self.assert_denied(self.request(), 403, expected="serial-b")

    def test_refuse_cleartext_even_for_valid_token(self):
        self.assert_denied(self.request(scheme="http"), 426, expected="serial-a")

    def test_refuse_missing_enrollment_file(self):
        self.auth.credentials_file = str(self.path) + "-nonexistent"
        self.assert_denied(self.request(), 503)

    def test_refuse_weak_token_and_open_file_perms(self):
        self.path.write_text(json.dumps({"serial-a": "weak"}), encoding="utf-8")
        self.assert_denied(self.request(), 503)
        self.path.write_text(json.dumps(self.tokens), encoding="utf-8")
        if os.name == "posix":
            self.path.chmod(0o644)
            self.assert_denied(self.request(), 503)

    def test_operator_token_is_distinct_from_agent_token(self):
        env = os.environ.get("ULTRON_ADMIN_API_TOKEN")
        try:
            os.environ["ULTRON_ADMIN_API_TOKEN"] = "o" * 64
            with self.assertRaises(HTTPException) as err:
                require_operator(self.request())
            self.assertEqual(err.exception.status_code, 403)
            req = self.request()
            req.headers["authorization"] = "Bearer " + "o" * 64
            self.assertIsNone(require_operator(req))
        finally:
            if env is None:
                os.environ.pop("ULTRON_ADMIN_API_TOKEN", None)
            else:
                os.environ["ULTRON_ADMIN_API_TOKEN"] = env


if __name__ == "__main__":
    unittest.main()
