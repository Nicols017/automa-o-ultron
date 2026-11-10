"""Testes offline: diagnósticos não devem executar correções remotas.

A classe de teste extrai somente os métodos do orquestrador usando AST para
não inicializar FastAPI, TrueConf, WinRM ou dependências de produção.
Execute: python -m unittest discover -s tests -p 'test_readonly_diagnostics.py'
"""
import ast
import json
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional


def load_orchestrator_methods():
    source = Path(__file__).resolve().parents[1] / "core" / "orchestrator.py"
    module = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    original = next(node for node in module.body if isinstance(node, ast.ClassDef) and node.name == "LabOrchestrator")
    methods = [node for node in original.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
               and node.name in {"run_diagnostics_only", "run_pipeline"}]
    harness = ast.ClassDef(name="OrchestratorUnderTest", bases=[], keywords=[], body=methods, decorator_list=[])
    isolated = ast.fix_missing_locations(ast.Module(body=[harness], type_ignores=[]))
    namespace = {"json": json, "Any": Any, "Dict": Dict, "List": List, "Optional": Optional}
    exec(compile(isolated, str(source), "exec"), namespace)
    return namespace["OrchestratorUnderTest"]


class FakeWinRM:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def run_script_file(self, ip, script, **kwargs):
        self.calls.append((ip, script))
        return self.result

    def test_connection(self, ip):
        return True


class FakeAnalyzer:
    def __init__(self):
        self.seen = []

    def analyze_logs(self, telemetry):
        self.seen.append(telemetry)
        return "Diagnóstico baseado em telemetria; nenhum reparo executado."


class ReadOnlyDiagnosticsTest(unittest.TestCase):
    def setUp(self):
        self.orchestrator = load_orchestrator_methods()()
        self.orchestrator.switch_id = type("Switch", (), {
            "identify_bench": lambda self, ip: {"bench_name": "Bancada teste", "mac": "Desconhecido"}
        })()
        self.orchestrator.analyzer = FakeAnalyzer()

    def test_success_never_executes_autoheal_or_agent_powershell(self):
        telemetry = {"computer_name": "TEST-PC", "disks": [{"health": "Healthy"}]}
        self.orchestrator.winrm = FakeWinRM({
            "success": True, "stdout": json.dumps(telemetry), "stderr": ""
        })
        result = self.orchestrator.run_diagnostics_only("192.0.2.20")
        self.assertTrue(result["success"])
        self.assertEqual(result["telemetry"], telemetry)
        self.assertEqual(self.orchestrator.winrm.calls, [
            ("192.0.2.20", "Inspect-SystemLogs.ps1")
        ])
        self.assertEqual(self.orchestrator.analyzer.seen, [telemetry])

    def test_winrm_failure_returns_error_without_invoking_analyzer(self):
        self.orchestrator.winrm = FakeWinRM({
            "success": False, "stdout": "", "stderr": "Host inacessível"
        })
        result = self.orchestrator.run_diagnostics_only("192.0.2.21")
        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "Host inacessível")
        self.assertEqual(self.orchestrator.analyzer.seen, [])
        self.assertEqual(len(self.orchestrator.winrm.calls), 1)

    def test_invalid_json_is_not_reported_as_success(self):
        self.orchestrator.winrm = FakeWinRM({
            "success": True, "stdout": "{invalid JSON}", "stderr": ""
        })
        result = self.orchestrator.run_diagnostics_only("192.0.2.22")
        self.assertFalse(result["success"])
        self.assertFalse(result["ai_diagnosis"])

    def test_pipeline_aborts_before_installations_on_failed_diagnostics(self):
        self.orchestrator.winrm = FakeWinRM({
            "success": True, "stdout": "", "stderr": ""
        })
        self.orchestrator.profile_mgr = type("Profiles", (), {
            "get_client_profile": lambda self, client_id: {"nome_exibicao": "Cliente teste"}
        })()
        self.orchestrator.settings = {"network": {"mdt_server_ip": "192.0.2.87"}}
        self.orchestrator.run_diagnostics_only = lambda ip, log_callback=None: {
            "success": False, "error": "Telemetria incompleta", "telemetry": {}, "ai_diagnosis": ""
        }
        result = self.orchestrator.run_pipeline(
            "192.0.2.23", tech_user_id=None, skip_burnin=True
        )
        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "Telemetria incompleta")
        self.assertEqual(self.orchestrator.winrm.calls, [])


if __name__ == "__main__":
    unittest.main()
