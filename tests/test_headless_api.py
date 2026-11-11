"""Offline contracts for headless API and TrueConf authentication.

No FastAPI app startup, WinRM, network, storage or production daemon used.
"""
import ast
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from core.trueconf_webhook_auth import require_trueconf_webhook

ROOT = Path(__file__).resolve().parents[1]
AST = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))


def func(name):
    return next(node for node in AST.body if isinstance(node, ast.FunctionDef)
                and node.name == name)


class HeadlessContractTests(unittest.TestCase):
    def test_no_web_dashboard_or_frontend_mount(self):
        source = (ROOT / "main.py").read_text(encoding="utf-8")
        self.assertNotIn('"/dashboard"', source)
        self.assertNotIn("StaticFiles(", source)
        self.assertNotIn("HTMLResponse(", source)
        self.assertNotIn("/ws/pipeline/", source)
        self.assertFalse((ROOT / "templates" / "index.html").exists())
        self.assertFalse((ROOT / "static" / "js" / "app.js").exists())
        self.assertFalse((ROOT / "static" / "css" / "style.css").exists())

    def test_dashboard_only_removed_keep_agent_and_reports(self):
        source = (ROOT / "main.py").read_text(encoding="utf-8")
        for needed in (
            "/download/UltronAgent.exe", "/bootstrap.ps1",
            "/api/v1/mdt/completed", "/api/v1/agent/register",
            "/api/v1/reports/download/", "/api/v1/trueconf/webhook",
        ):
            self.assertIn(needed, source)

    def test_sensitive_routes_require_operator(self):
        sensitive = (
            "test_trueconf_notification",
            "list_clients", "get_client_profile",
            "get_milvus_config", "update_milvus_config",
            "get_milvus_client_tokens", "update_milvus_client_token",
            "sync_milvus_data", "sync_all_milvus_agents",
            "install_packages_api", "upgrade_all_packages_api",
            "backup_packages_api", "restore_packages_api",
            "execute_install_software_action", "execute_domain_join_action",
            "list_reports", "download_report",
        )
        for name in sensitive:
            with self.subTest(name=name):
                code = ast.unparse(func(name))
                self.assertIn("require_operator(request)", code)

    def test_webhook_auth_precedes_processing(self):
        code = ast.unparse(func("trueconf_webhook"))
        self.assertLess(code.index("require_trueconf_webhook(request)"),
                        code.index("bot.process_incoming_message("))
        self.assertNotIn('"received": message_text', code)

    def test_report_path_is_validated(self):
        code = ast.unparse(func("download_report"))
        self.assertIn("os.path.basename(filename)", code)
        self.assertIn(".endswith('.pdf')", code)


class WebhookAuthenticationTests(unittest.TestCase):
    @staticmethod
    def request(scheme="https", headers=None):
        return SimpleNamespace(url=SimpleNamespace(scheme=scheme),
                               headers=headers or {})

    def test_no_secret_means_disabled(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(HTTPException) as ctx:
                require_trueconf_webhook(self.request())
        self.assertEqual(ctx.exception.status_code, 503)

    def test_http_rejected_even_with_secret(self):
        with patch.dict(os.environ, {"ULTRON_TRUECONF_WEBHOOK_SECRET": "x" * 40}, clear=True):
            with self.assertRaises(HTTPException) as ctx:
                require_trueconf_webhook(self.request(
                    scheme="http", headers={"x-ultron-trueconf-secret": "x" * 40}
                ))
        self.assertEqual(ctx.exception.status_code, 426)

    def test_wrong_secret_rejected(self):
        with patch.dict(os.environ, {"ULTRON_TRUECONF_WEBHOOK_SECRET": "x" * 40}, clear=True):
            with self.assertRaises(HTTPException) as ctx:
                require_trueconf_webhook(self.request(headers={
                    "x-ultron-trueconf-secret": "y" * 40
                }))
        self.assertEqual(ctx.exception.status_code, 401)

    def test_explicit_secure_secret_accepted(self):
        with patch.dict(os.environ, {"ULTRON_TRUECONF_WEBHOOK_SECRET": "x" * 40}, clear=True):
            self.assertTrue(require_trueconf_webhook(self.request(
                headers={"x-ultron-trueconf-secret": "x" * 40}
            )))


if __name__ == "__main__":
    unittest.main()
