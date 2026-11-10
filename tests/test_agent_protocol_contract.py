"""Static API contract tests without importing FastAPI's application or agents.

These checks supplement behavior tests; they do NOT compile the Windows C#
agent or prove that Macrium Verify was executed on a real backup.
"""
import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def function_sources(path):
    module = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    functions = {}
    for node in module.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions[node.name] = ast.unparse(node)
    return functions


class EndpointSecurityContractTests(unittest.TestCase):
    def setUp(self):
        self.functions = function_sources("main.py")

    def test_agent_operations_require_authentication(self):
        for name in (
            "get_agent_pending_tasks", "submit_agent_task_result",
            "receive_agent_alert", "agent_register", "agent_heartbeat",
            "mdt_completed",
        ):
            with self.subTest(name=name):
                self.assertIn(
                    "AgentAuthenticator().authenticate(request",
                    self.functions[name],
                )

    def test_remote_bench_operations_require_operator(self):
        for name in (
            "diagnose_machine", "execute_backup_action",
            "execute_power_action", "execute_rename_action",
            "execute_activation_action", "run_bench_pipeline",
        ):
            with self.subTest(name=name):
                self.assertIn("require_operator(request)", self.functions[name])

    def test_cleanup_endpoint_cannot_dispatch_command(self):
        body = self.functions["enqueue_agent_cleanup"]
        self.assertIn("require_operator(request)", body)
        self.assertIn("status_code=423", body)
        self.assertNotIn("enqueue_task(", body)

    def test_windows_agent_uses_auth_for_sensitive_routes(self):
        source = (ROOT / "agent" / "UltronAgent.cs").read_text(encoding="utf-8")
        self.assertIn("private static string AgentRequest(", source)
        self.assertIn("Uri.UriSchemeHttps", source)
        self.assertIn('req.Headers["X-Ultron-Agent-ID"]', source)
        self.assertIn("Authorization] = ", source)
        self.assertIn("string responseJson = AgentGet(endpoint", source)
        self.assertIn("string cleanupAck = AgentPost(", source)
        self.assertIn("AgentPost(ServerUrl + \"/api/v1/agent/heartbeat\"", source)
        self.assertIn("AgentPost(ServerUrl + \"/api/v1/agent/alert\"", source)
        self.assertNotIn('HttpPost(ServerUrl + "/api/v1/agent/register"', source)
        self.assertNotIn('HttpPost(ServerUrl + "/api/v1/agent/heartbeat"', source)

    def test_robocopy_backup_is_not_macrium_verification(self):
        source = (ROOT / "scripts" / "powershell" / "Backup-UserData.ps1").read_text(
            encoding="utf-8"
        ).lower()
        self.assertIn("robocopy", source)
        gate = (ROOT / "core" / "backup_gate.py").read_text(encoding="utf-8")
        self.assertNotIn("subprocess.run(", gate)


if __name__ == "__main__":
    unittest.main()
