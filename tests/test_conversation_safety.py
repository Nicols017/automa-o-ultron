"""Offline contracts for ChatOps LLM conversation behavior after simplification."""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


def function_source(path, class_name, method_name):
    code = (ROOT / path).read_text(encoding="utf-8")
    module = ast.parse(code)
    cls = next(x for x in module.body if isinstance(x, ast.ClassDef) and x.name == class_name)
    fun = next(x for x in cls.body if isinstance(x, ast.FunctionDef) and x.name == method_name)
    return ast.unparse(fun)


class ConversationSafetyContracts(unittest.TestCase):
    def test_conversational_ai_is_not_an_executor(self):
        code = function_source("chatops/chatops.py", "TrueConfChatOps",
                               "_handle_ai_conversation")
        self.assertIn("Nunca afirme sucesso", code)
        self.assertIn("ULTRON_CHAT_LIVE_CONTEXT_ENABLED", code)
        self.assertIn("ULTRON_OBSIDIAN_RAG_ENABLED", code)
        for dangerous in (
            "run_script_file(", "run_powershell_code(", "Restart-Computer",
            "file_backup_jobs.start(", "macrium_jobs.start(",
        ):
            with self.subTest(dangerous=dangerous):
                self.assertNotIn(dangerous, code)

    def test_prompt_no_longer_claims_autohealing(self):
        text = (ROOT / "core" / "diagnostic_analyzer.py").read_text(encoding="utf-8")
        self.assertNotIn("Sempre elogie a si mesmo", text)
        self.assertIn("Diagnósticos são somente leitura", text)

    def test_classification_logs_do_not_echo_user_text(self):
        code = function_source("core/reliability.py", "IntentRouter", "classify")
        self.assertIn("message_length=len(text)", code)
        self.assertNotIn("text=text[:200]", code)


if __name__ == "__main__":
    unittest.main()
