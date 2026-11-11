"""Safety regression cases for Portuguese TrueConf request interpretation.

Only parses text. No services, computers, users or storage are accessed.
"""
import ast
import unittest
from pathlib import Path

from core.intent_preflight import preflight_request

REPO = Path(__file__).resolve().parents[1]


class PreflightTests(unittest.TestCase):
    def test_questions_cannot_be_misrouted_to_actions(self):
        for phrase in (
            "Como verificar se o backup terminou?",
            "Qual é a diferença entre Clonezilla e FOG?",
            "Pode me explicar como formatar um computador?",
            "Por que o computador reinicia no PXE?",
            "Como instalar o Windows pela rede?",
            "Me explica como fazer backup antes de formatar",
        ):
            with self.subTest(phrase=phrase):
                self.assertEqual(preflight_request(phrase).kind, "explanatory")

    def test_clear_existing_commands_still_route(self):
        for phrase in (
            "/backup 192.168.57.50 TIMENOW 12282",
            "/verificar_backup C:\\laboratorio\\teste.mrimg",
            "instala o Chrome no 192.168.57.50",
            "diagnóstico no 192.168.57.50",
            "reinicia o PC 57.50",
            "Fazer backup dos dados do usuário do 57.50",
        ):
            with self.subTest(phrase=phrase):
                self.assertEqual(preflight_request(phrase).kind, "passthrough")

    def test_negated_actions_are_never_dispatched(self):
        for phrase in (
            "não formate esse computador",
            "não reinicie essa máquina",
            "não faça backup agora",
        ):
            with self.subTest(phrase=phrase):
                self.assertEqual(preflight_request(phrase).kind, "blocked")

    def test_backup_then_format_needs_separate_authorization(self):
        for phrase in (
            "Faz o backup e depois formata o 57.50",
            "Preciso fazer backup antes de formatar a máquina",
        ):
            with self.subTest(phrase=phrase):
                self.assertEqual(preflight_request(phrase).kind, "blocked")
                self.assertIn("formatação", preflight_request(phrase).reply)

    def test_unavailable_fog_image_commands_never_call_robocopy(self):
        for phrase in (
            "Faz um backup de imagem do 57.50",
            "backup imagem da máquina 57.50",
            "quero restaurar a imagem pelo FOG na máquina 57.50",
            "restaura esse backup no outro PC",
            "captura a imagem do computador com FOG",
        ):
            with self.subTest(phrase=phrase):
                self.assertEqual(preflight_request(phrase).kind, "blocked")

    def test_backup_verification_not_new_copy(self):
        for phrase in (
            "Verifique o backup do PC 57.50",
            "Confirma a integridade do backup de ontem",
        ):
            with self.subTest(phrase=phrase):
                self.assertEqual(preflight_request(phrase).kind, "blocked")

    def test_chatops_checks_preflight_before_legacy_master_and_router(self):
        module = ast.parse((REPO / "chatops" / "chatops.py").read_text("utf-8"))
        cls = next(n for n in module.body if isinstance(n, ast.ClassDef)
                   and n.name == "TrueConfChatOps")
        method = next(n for n in cls.body if isinstance(n, ast.FunctionDef)
                      and n.name == "handle_incoming_message")
        source = ast.unparse(method)
        self.assertLess(source.index("preflight_request(text)"),
                        source.index("self._handle_master_intent("))
        self.assertLess(source.index("preflight_request(text)"),
                        source.index("self.intent_router.classify("))


if __name__ == "__main__":
    unittest.main()
