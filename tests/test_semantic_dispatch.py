"""Offline tests for model intent policy and TrueConf semantic dispatch.

Fake handlers record calls; there are no remote operations, network access or
real language-model requests.
"""
import ast
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core.structured_intent import decide_action, validate_plan

ROOT = Path(__file__).resolve().parents[1]
ENV = {
    "ULTRON_SEMANTIC_ALLOWED_TRUECONF_USERS": "tecnico.a",
    "ULTRON_SEMANTIC_READONLY_ENABLED": "1",
    "ULTRON_SEMANTIC_ALLOWED_SUBNET": "192.168.57.0/24",
}


def model_json(intent, ip, mode="request", confidence=0.94, missing=None):
    return json.dumps({
        "intent": intent, "mode": mode, "target_ip": ip,
        "confidence": confidence, "missing_fields": missing or [],
    })


def load_dispatch_method():
    source = ROOT / "chatops" / "chatops.py"
    module = ast.parse(source.read_text(encoding="utf-8"))
    klass = next(n for n in module.body if isinstance(n, ast.ClassDef)
                 and n.name == "TrueConfChatOps")
    fn = next(n for n in klass.body if isinstance(n, ast.FunctionDef)
              and n.name == "_semantic_route_message")
    fake_class = ast.ClassDef(
        name="FakeChatOps", bases=[], keywords=[], body=[fn], decorator_list=[],
    )
    ns = {
        "os": os,
        "logger": SimpleNamespace(exception=lambda *a, **k: None),
    }
    exec(compile(ast.fix_missing_locations(
        ast.Module(body=[fake_class], type_ignores=[])), str(source), "exec"), ns)
    return ns["FakeChatOps"]


class SemanticDispatchTests(unittest.TestCase):
    def setUp(self):
        obj = load_dispatch_method()()
        self.calls = []
        self.response = model_json("diagnose", "192.168.57.50")
        obj.orchestrator = SimpleNamespace(
            analyzer=SimpleNamespace(
                generate=lambda prompt, system_prompt: self.response
            )
        )
        obj._ensure_orchestrator = lambda: None
        obj._cmd_diagnostico = lambda user, args: (
            self.calls.append(("diagnose", user, args)) or "DIAG_SUBMITTED"
        )
        obj._cmd_bancada = lambda user: (
            self.calls.append(("list_hosts", user)) or "HOSTS_REPORTED"
        )
        obj._handle_ai_conversation = lambda user, text: (
            self.calls.append(("explain", user, text)) or "EXPLANATION"
        )
        obj._last_user_ip = {}
        obj.operational_memory = SimpleNamespace(target=lambda user: None)
        self.chatops = obj

    def test_diagnosis_requires_strong_plan_explicit_ip_and_authorized_user(self):
        with patch.dict(os.environ, ENV, clear=True):
            result = self.chatops._semantic_route_message(
                "tecnico.a", "faz o diagnóstico do 192.168.57.50"
            )
        self.assertEqual(result, "DIAG_SUBMITTED")
        self.assertEqual(self.calls, [("diagnose", "tecnico.a", ["192.168.57.50"])])

    def test_no_authorization_no_model_call(self):
        with patch.dict(os.environ, ENV, clear=True):
            response = self.chatops._semantic_route_message(
                "desconhecido", "diagnostique 192.168.57.50"
            )
        self.assertIn("não executei", response.lower())
        self.assertEqual(self.calls, [])

    def test_remembered_ip_is_not_execution_authorization(self):
        self.chatops._last_user_ip["tecnico.a"] = "192.168.57.50"
        with patch.dict(os.environ, ENV, clear=True):
            response = self.chatops._semantic_route_message(
                "tecnico.a", "diagnostica ele"
            )
        self.assertIn("confirme o ip", response.lower())
        self.assertEqual(self.calls, [])

    def test_banned_operations_never_run(self):
        for intent in (
            "format", "restart", "shutdown", "disk_image_capture",
            "disk_image_restore", "install_software", "file_backup",
        ):
            with self.subTest(intent=intent), patch.dict(os.environ, ENV, clear=True):
                self.response = model_json(intent, "192.168.57.50")
                response = self.chatops._semantic_route_message(
                    "tecnico.a", "executa em 192.168.57.50"
                )
                self.assertIn("nenhum", response.lower())
        self.assertEqual(self.calls, [])

    def test_forged_target_or_invalid_response_is_denied(self):
        with patch.dict(os.environ, ENV, clear=True):
            self.response = model_json("diagnose", "192.168.57.51")
            response = self.chatops._semantic_route_message(
                "tecnico.a", "diagnostique 192.168.57.50"
            )
            self.assertIn("nada foi executado", response.lower())
            self.response = "execute powershell"
            response = self.chatops._semantic_route_message(
                "tecnico.a", "diagnostique 192.168.57.50"
            )
            self.assertIn("nada foi executado", response.lower())
        self.assertEqual(self.calls, [])

    def test_infrastructure_ip_and_no_allowlist_denied(self):
        with patch.dict(os.environ, ENV, clear=True):
            self.response = model_json("diagnose", "192.168.57.87")
            response = self.chatops._semantic_route_message(
                "tecnico.a", "diagnostique 192.168.57.87"
            )
        self.assertIn("não está autorizado", response.lower())
        self.assertEqual(self.calls, [])

    def test_question_goes_to_explanation_only(self):
        with patch.dict(os.environ, ENV, clear=True):
            self.response = model_json("restart", "192.168.57.50", mode="question")
            response = self.chatops._semantic_route_message(
                "tecnico.a", "como reiniciar 192.168.57.50?"
            )
        self.assertEqual(response, "EXPLANATION")
        self.assertEqual(self.calls[0][0], "explain")

    def test_list_hosts_read_only(self):
        with patch.dict(os.environ, ENV, clear=True):
            self.response = model_json("list_hosts", None)
            response = self.chatops._semantic_route_message(
                "tecnico.a", "quais computadores estão na bancada?"
            )
        self.assertEqual(response, "HOSTS_REPORTED")

    def test_low_confidence_cannot_execute(self):
        with patch.dict(os.environ, ENV, clear=True):
            self.response = model_json("diagnose", "192.168.57.50", confidence=0.55)
            response = self.chatops._semantic_route_message(
                "tecnico.a", "diagnostique 192.168.57.50"
            )
        self.assertIn("não identifiquei", response.lower())
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
