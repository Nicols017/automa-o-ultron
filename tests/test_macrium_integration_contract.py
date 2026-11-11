"""Offline contract tests: Ultron Macrium integration is limited to verification."""
import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def class_functions(filename, class_name):
    module = ast.parse((ROOT / filename).read_text(encoding="utf-8"))
    cls = next(x for x in module.body if isinstance(x, ast.ClassDef)
               and x.name == class_name)
    return {fn.name: ast.unparse(fn) for fn in cls.body
            if isinstance(fn, ast.FunctionDef)}


def module_functions(filename):
    module = ast.parse((ROOT / filename).read_text(encoding="utf-8"))
    return {fn.name: ast.unparse(fn) for fn in module.body
            if isinstance(fn, ast.FunctionDef)}


class MacriumIntegrationContractTest(unittest.TestCase):
    def test_api_uses_operator_authentication_and_job_manager(self):
        funcs = module_functions("main.py")
        for name in ("start_macrium_verification", "get_macrium_verification"):
            with self.subTest(name=name):
                self.assertIn("require_operator(request)", funcs[name])
                self.assertIn("macrium_jobs.", funcs[name])

    def test_trueconf_has_explicit_allowlist(self):
        funcs = class_functions("chatops/chatops.py", "TrueConfChatOps")
        code = funcs["_cmd_verify_macrium"]
        self.assertIn("ULTRON_MACRIUM_ALLOWED_TRUECONF_USERS", code)
        self.assertIn("actor not in allowed", code)
        self.assertIn("macrium_jobs.start(", code)
        self.assertIn("on_done=notify", code)

    def test_winrm_scripts_only_verify_and_write_local_logs(self):
        ps = (ROOT / "scripts/powershell/Verify-MacriumImage.ps1").read_text(encoding="utf-8")
        self.assertIn("& $macrium $fullImage --set --logfile $logPath", ps)
        self.assertIn("ULTRON_MACRIUM_JSON:", ps)
        self.assertIn("Join-Path $env:ProgramData 'Ultron", ps)
        for forbidden in ("reagentc ", "Restart-Computer ", "Stop-Computer ",
                          "Invoke-WmiMethod ", "Copy-Item ", "Remove-Item "):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, ps)

    def test_no_mdt_or_agent_redispatch(self):
        funcs = module_functions("core/macrium_remote.py")
        code = funcs["verify_on_windows"]
        self.assertIn("Verify-MacriumImage.ps1", code)
        self.assertNotIn("enqueue_task(", code)
        self.assertNotIn("run_powershell_code(", code)


if __name__ == "__main__":
    unittest.main()
