"""
Testes Unitários da IA do Ultron e TrueConf ChatOps
Valida a sanitização de texto, remoção de tags <think>, geração e roteamento de comandos.
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Forçar UTF-8
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Adiciona raiz do projeto ao sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.diagnostic_analyzer import DiagnosticAnalyzer
from chatops.chatops import TrueConfChatOps

class TestDiagnosticAnalyzer(unittest.TestCase):

    def test_clean_llm_response_think_tags(self):
        """Valida se tags <think>...</think> são completamente removidas."""
        raw = (
            "<think>\n"
            "O técnico está perguntando sobre o erro de disco 0x80070005.\n"
            "Preciso responder de forma técnica e direta.\n"
            "</think>\n"
            "1. 🚨 **Problemas Identificados:** Falha de permissão de acesso ao disco.\n"
            "2. 🔬 **Causa Raiz:** ACL corrompida na pasta de sistema.\n"
            "3. 🛠️ **Ações de Reparo:** Executar `icacls C:\\Windows /reset /t /c /l`.\n"
            "4. 🩺 **Veredito:** APROVADA APÓS REPARO."
        )
        cleaned = DiagnosticAnalyzer._clean_llm_response(raw)
        self.assertNotIn("<think>", cleaned)
        self.assertNotIn("</think>", cleaned)
        self.assertNotIn("O técnico está perguntando", cleaned)
        self.assertTrue(cleaned.startswith("1. 🚨 **Problemas Identificados:**"))

    def test_clean_llm_response_fillers(self):
        """Valida se saudações robóticas e preâmbulos são removidos."""
        raw = (
            "Olá! Como assistente de IA da Pense Rede, aqui está o laudo:\n\n"
            "Status: Operacional\n"
            "Ação: Nenhuma."
        )
        cleaned = DiagnosticAnalyzer._clean_llm_response(raw)
        self.assertNotIn("Olá! Como assistente", cleaned)
        self.assertIn("Status: Operacional", cleaned)

    def test_clean_llm_response_unclosed_think(self):
        """Valida que uma tag <think> não fechada é truncada sem vazar raciocínio."""
        raw = "<think>Raciocínio inacabado do modelo..."
        cleaned = DiagnosticAnalyzer._clean_llm_response(raw)
        self.assertEqual(cleaned, "")

    @patch("requests.post")
    def test_generate_and_analyze_alias(self, mock_post):
        """Valida se generate() e analyze() executam e retornam texto limpo."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "response": "<think>pensando...</think>O computador PC-01 está ativo com WinRM pronto."
        }
        mock_post.return_value = mock_response

        analyzer = DiagnosticAnalyzer(base_url="http://localhost:11434", provider="ollama")
        res1 = analyzer.generate("Status do PC?")
        res2 = analyzer.analyze("Status do PC?")

        self.assertEqual(res1, "O computador PC-01 está ativo com WinRM pronto.")
        self.assertEqual(res2, res1)

    @patch("requests.post")
    def test_analyze_logs_format(self, mock_post):
        """Valida o prompt de diagnóstico de hardware."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "response": (
                "1. 🚨 **Problemas Identificados:** Nenhuma falha crítica detectada.\n\n"
                "2. 🔬 **Causa Raiz:** Discos S.M.A.R.T 100% saudáveis.\n\n"
                "3. 🛠️ **Ações de Reparo:** Prosseguir com a esteira de software.\n\n"
                "4. 🩺 **Veredito da Máquina:** **APROVADA PARA PREPARAÇÃO**"
            )
        }
        mock_post.return_value = mock_response

        analyzer = DiagnosticAnalyzer()
        telemetry = {
            "computer_name": "PC-TEST",
            "serial_number": "12345",
            "cpu": "Core i5",
            "ram_gb": 16,
            "disks": [{"model": "Kingston 480GB", "health": "Healthy"}]
        }
        verdict = analyzer.analyze_logs(telemetry)
        self.assertIn("1. 🚨 **Problemas Identificados:**", verdict)
        self.assertIn("APROVADA PARA PREPARAÇÃO", verdict)


class TestTrueConfChatOps(unittest.TestCase):

    def setUp(self):
        self.chatops = TrueConfChatOps()

    def test_slash_help(self):
        """Testa o comando /ajuda e menu interativo."""
        reply = self.chatops.handle_incoming_message("nicolas", "/ajuda")
        self.assertIn("CENTRAL DE AUTOMAÇÃO ULTRON", reply)
        self.assertIn("[ 1 ]", reply)
        self.assertIn("[ 3 ]", reply)

    def test_numbered_menu_choice(self):
        """Testa seleção digitando apenas o número '1' para bancada."""
        reply = self.chatops.handle_incoming_message("nicolas", "1")
        self.assertIn("Varrendo computadores", reply)

    def test_wizard_message_flow(self):
        """Testa fluxo passo a passo para envio de mensagem."""
        # Passo 1: Digita '3'
        r1 = self.chatops.handle_incoming_message("nicolas", "3")
        self.assertIn("ENVIAR MENSAGEM", r1)
        self.assertIn("Digite o IP", r1)

        # Passo 2: Digita o IP
        r2 = self.chatops.handle_incoming_message("nicolas", "192.168.57.59")
        self.assertIn("Destino: 192.168.57.59", r2)
        self.assertIn("Digite o texto", r2)

        # Passo 3: Digita o texto da mensagem
        r3 = self.chatops.handle_incoming_message("nicolas", "Olá máquina de teste")
        self.assertIn("Enviando mensagem", r3)
        self.assertIn("192.168.57.59", r3)

    def test_slash_bancada(self):
        """Testa o comando /bancada."""
        reply = self.chatops.handle_incoming_message("nicolas", "/bancada")
        self.assertIn("Varrendo computadores", reply)

    def test_natural_language_error_lookup(self):
        """Testa reconhecimento de intenção de código de erro hexadecimal."""
        reply = self.chatops.handle_incoming_message("nicolas", "qual o significado do erro 0x80070005 no windows?")
        self.assertIn("0x80070005", reply.lower())
        self.assertIn("ERROR_ACCESS_DENIED", reply)

    def test_natural_language_bench_query(self):
        """Testa intenção em linguagem natural para consultar bancada."""
        reply = self.chatops.handle_incoming_message("nicolas", "quais máquinas estão ligadas agora?")
        self.assertIn("Varrendo computadores", reply)

    def test_slash_message(self):
        """Testa o comando /msg para envio de alerta na tela."""
        reply = self.chatops.handle_incoming_message("nicolas", "/msg 192.168.57.59 Teste de aviso na tela")
        self.assertIn("192.168.57.59", reply)
        self.assertIn("Enviando mensagem", reply)

    def test_natural_language_message(self):
        """Testa envio de mensagem por linguagem natural."""
        reply = self.chatops.handle_incoming_message("nicolas", 'manda uma mensagem para o IP 192.168.57.59 "Ultron está rodando"')
        self.assertIn("192.168.57.59", reply)
        self.assertIn("Enviando mensagem", reply)

    def test_conversational_ai_fallback(self):
        """Testa conversa livre com LLM mockado."""
        mock_analyzer = MagicMock()
        mock_analyzer.generate.return_value = "Para ingressar no domínio, utilize o comando `/dominio 192.168.57.25 penserede.local`."
        
        mock_orch = MagicMock()
        mock_orch.analyzer = mock_analyzer
        self.chatops.orchestrator = mock_orch

        reply = self.chatops.handle_incoming_message("nicolas", "como coloco o pc no dominio?")
        self.assertIn("🤖 Ultron:", reply)
        self.assertIn("/dominio", reply)

if __name__ == "__main__":
    unittest.main()
