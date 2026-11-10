"""Offline regression tests for safe TrueConf actions.

No TrueConf connection, WinRM host, OS service or formatting target is contacted.
The selected class methods are parsed from source using AST and run with fakes.
"""
import ast
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import List


def load_chatops_actions():
    source = Path(__file__).resolve().parents[1] / "chatops" / "chatops.py"
    parsed = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    original = next(
        n for n in parsed.body
        if isinstance(n, ast.ClassDef) and n.name == "TrueConfChatOps"
    )
    selected = {
        "_cmd_limpar", "_cmd_formatar", "_execute_formatar",
        "_cmd_power", "_cmd_message"
    }
    methods = [
        n for n in original.body
        if isinstance(n, ast.FunctionDef) and n.name in selected
    ]
    assert len(methods) == len(selected), "Método de ChatOps não encontrado"
    fake_class = ast.ClassDef(
        name="OfflineChatOps", bases=[], keywords=[],
        body=methods, decorator_list=[]
    )
    ns = {
        "List": List,
        "threading": SimpleNamespace(Thread=ImmediateThread),
        "new_trace_id": lambda: "trace-test",
        "WinRMResult": FakeWinRMResult,
        "log": SimpleNamespace(info=lambda *a, **k: None),
    }
    exec(
        compile(ast.fix_missing_locations(ast.Module(body=[fake_class], type_ignores=[])),
                str(source), "exec"),
        ns,
    )
    return ns["OfflineChatOps"]


class ImmediateThread:
    def __init__(self, target, daemon=False):
        self.target = target

    def start(self):
        self.target()


class FakeWinRMResult:
    def __init__(self, **kwargs):
        self.details = kwargs


class FakeBuilder:
    def success(self, title, data, trace_id, emoji=None):
        return ("SUCCESS", title, data, trace_id)

    def error(self, result, trace_id):
        return ("ERROR", result.details, trace_id)


class FakeWinRM:
    def __init__(self, success=True):
        self.success = success
        self.calls = []

    def run_powershell_code(self, ip, code):
        self.calls.append(("powershell", ip, code))
        return {"success": self.success, "stderr": "" if self.success else "Sem resposta"}

    def run_script_file(self, ip, name, params=None):
        self.calls.append(("script", ip, name, params))
        return {"success": self.success, "stderr": "" if self.success else "Sem resposta"}


class FakeBot:
    def __init__(self):
        self.messages = []

    def send_direct_message(self, user_id, message):
        self.messages.append((user_id, message))


class ChatOpsSafetyTests(unittest.TestCase):
    def setUp(self):
        self.chatops = load_chatops_actions()()
        self.chatops.winrm = FakeWinRM()
        self.chatops.msg_builder = FakeBuilder()
        self.chatops.bot = FakeBot()
        self.chatops._last_user_ip = {}

    def test_cleanup_does_not_uninstall_or_queue(self):
        result = self.chatops._cmd_limpar("operator", ["192.0.2.55"], trace_id="test")
        self.assertIn("BLOQUEADA", result)
        self.assertEqual(self.chatops.winrm.calls, [])

    def test_mdt_format_request_and_legacy_confirmation_are_blocked(self):
        a = self.chatops._cmd_formatar("operator", ["192.0.2.56"])
        b = self.chatops._execute_formatar("operator", "192.0.2.56")
        self.assertIn("BLOQUEADA", a)
        self.assertIn("BLOQUEADA", b)
        self.assertEqual(self.chatops.winrm.calls, [])

    def test_power_uses_winrm_only_once(self):
        result = self.chatops._cmd_power("operator", ["192.0.2.57"], "restart")
        self.assertEqual(result[0], "SUCCESS")
        self.assertEqual(self.chatops.winrm.calls, [
            ("powershell", "192.0.2.57", "Restart-Computer -Force")
        ])

    def test_power_fail_never_falls_back_to_agent(self):
        self.chatops.winrm.success = False
        result = self.chatops._cmd_power("operator", ["192.0.2.57"], "shutdown")
        self.assertEqual(result[0], "ERROR")
        self.assertIn("Não houve reenvio", result[1]["error"])
        self.assertEqual(len(self.chatops.winrm.calls), 1)

    def test_unknown_power_action_has_no_side_effects(self):
        result = self.chatops._cmd_power("operator", ["192.0.2.57"], "invalid")
        self.assertEqual(result[0], "ERROR")
        self.assertEqual(self.chatops.winrm.calls, [])

    def test_message_goes_by_winrm_only_and_reports_success(self):
        self.chatops._cmd_message("operator", ["192.0.2.59", "Olá", "usuário"])
        self.assertEqual(len(self.chatops.winrm.calls), 1)
        self.assertEqual(self.chatops.winrm.calls[0][0:3],
                         ("script", "192.0.2.59", "Show-UserMessage.ps1"))
        self.assertEqual(len(self.chatops.bot.messages), 1)
        self.assertIn("PROCESSADA", self.chatops.bot.messages[0][1])

    def test_failed_message_does_not_claim_it_will_arrive_later(self):
        self.chatops.winrm.success = False
        self.chatops._cmd_message("operator", ["192.0.2.59", "Teste"])
        self.assertEqual(len(self.chatops.winrm.calls), 1)
        self.assertIn("NÃO FOI POSSÍVEL CONFIRMAR", self.chatops.bot.messages[0][1])


if __name__ == "__main__":
    unittest.main()
