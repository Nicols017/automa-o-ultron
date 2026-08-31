"""
Testes Unitários da IA do Ultron, TrueConf ChatOps e Autenticação Dinâmica
Valida a sanitização de texto, remoção de tags <think>, respostas instantâneas via Knowledge Engine, restrições de escopo e credenciais dinâmicas.
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

    def test_clean_llm_response_unclosed_think(self):
        """Valida que uma tag <think> não fechada é truncada sem vazar raciocínio."""
        raw = "<think>Raciocínio inacabado do modelo..."
        cleaned = DiagnosticAnalyzer._clean_llm_response(raw)
        self.assertEqual(cleaned, "")

    def test_fallback_knowledge_when_offline(self):
        """Valida que o Knowledge Engine responde imediatamente sobre chamados Milvus mesmo sem conexão LLM."""
        analyzer = DiagnosticAnalyzer(base_url="http://127.0.0.1:9999", provider="ollama")
        res = analyzer.generate("A listas de chamados é apenas no meu nome que puxa?")
        self.assertIn("Milvus", res)
        self.assertIn("chamados", res.lower())

    def test_fallback_scope_restriction(self):
        """Valida que perguntas fora de escopo (culinária, futebol, etc.) são educadamente redirecionadas."""
        analyzer = DiagnosticAnalyzer(base_url="http://127.0.0.1:9999", provider="ollama")
        res = analyzer.generate("Me passa uma receita de bolo de chocolate?")
        self.assertIn("foco é restrito ao suporte técnico", res)
        self.assertIn("bancada", res.lower())

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
        self.assertTrue("Bancada" in reply or "Máquina" in reply or "computador" in reply.lower())

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

    def test_interactive_credentials_flow(self):
        """Testa o fluxo de solicitação interativa de credenciais pelo TrueConf."""
        # Configura sessão simulando que a máquina 192.168.57.99 pediu usuário/senha
        prompt = self.chatops._prompt_for_credentials(
            user_id="nicolas",
            ip="192.168.57.99",
            action_name="Diagnóstico",
            callback_fn=lambda: "Ação executada com sucesso após autenticação!"
        )
        self.assertIn("ACESSO NECESSÁRIO", prompt)
        self.assertIn("192.168.57.99", prompt)

        # Usuário envia as credenciais: 'Administrador MinhaSenha123'
        reply = self.chatops.handle_incoming_message("nicolas", "Administrador MinhaSenha123")
        self.assertEqual(reply, "Ação executada com sucesso após autenticação!")

        # Valida que as credenciais foram salvas no WinRMExecutor para o IP
        cached = self.chatops.winrm.get_host_credentials("192.168.57.99")
        self.assertEqual(cached, ("Administrador", "MinhaSenha123"))

    def test_natural_language_diag_variations(self):
        """Testa gatilhos naturais de diagnóstico em texto livre."""
        # Variação 1: 'Diag' abre wizard ou identifica máquina
        r1 = self.chatops.handle_incoming_message("nicolas", "Diag")
        self.assertTrue("diagnóstico" in r1.lower() or "hardware" in r1.lower())

        # Variação 2: 'faz um diagnostico no pc 57.25'
        r2 = self.chatops.handle_incoming_message("nicolas", "faz um diagnostico no pc 57.25")
        self.assertIn("192.168.57.25", r2)

    def test_natural_language_prep_variations(self):
        """Testa gatilhos naturais de preparação de máquina."""
        reply = self.chatops.handle_incoming_message("nicolas", "prepara a maquina 57.48 pro white group")
        self.assertIn("192.168.57.48", reply)
        self.assertTrue("white" in reply.lower() or "esteira" in reply.lower())

    def test_natural_language_activation(self):
        """Testa pedido natural de ativação Windows."""
        reply = self.chatops.handle_incoming_message("nicolas", "ativa o windows do pc 57.48")
        self.assertIn("192.168.57.48", reply)
        self.assertTrue("ativação" in reply.lower() or "mas" in reply.lower())

    def test_natural_language_agent_download(self):
        """Testa solicitação natural de download do executável."""
        reply = self.chatops.handle_incoming_message("nicolas", "onde baixo o executavel do agente?")
        self.assertIn("UltronAgent.exe", reply)
        self.assertIn("192.168.57.48:7000", reply)

        # Testa frase do usuário pedindo o arquivo diretamente
        reply2 = self.chatops.handle_incoming_message("nicolas", "me manda o executavel do agent por aqui")
        self.assertIn("UltronAgent.exe", reply2)

        # Testa comando /download
        reply3 = self.chatops.handle_incoming_message("nicolas", "/download")
        self.assertIn("UltronAgent.exe", reply3)

    def test_conversational_ai_natural_question(self):
        """Testa resposta natural para pergunta de chamados sem timeout."""
        reply = self.chatops.handle_incoming_message("nicolas", "A listas de chamados é apenas no meu nome que puxa?")
        self.assertIn("🤖 Ultron:", reply)
        self.assertIn("chamados", reply.lower())

    def test_user_exact_bench_phrases(self):
        """Testa as frases exatas enviadas pelo técnico pelo TrueConf."""
        # 1. 'me fala as máquinas que você está detectando os IPs'
        r1 = self.chatops.handle_incoming_message("nicolas", "me fala as máquinas que você está detectando os IPs")
        self.assertNotIn("Ingresso no Domínio", r1)
        self.assertTrue("Bancada" in r1 or "computador" in r1.lower() or "máquina" in r1.lower())

        # 2. 'Procure máquinas na bancda' (com erro de digitação bancda)
        r2 = self.chatops.handle_incoming_message("nicolas", "Procure máquinas na bancda")
        self.assertNotIn("Ingresso no Domínio", r2)
        self.assertTrue("Bancada" in r2 or "computador" in r2.lower() or "máquina" in r2.lower())

    def test_natural_language_error_lookup(self):
        """Testa reconhecimento de intenção de código de erro hexadecimal."""
        reply = self.chatops.handle_incoming_message("nicolas", "qual o significado do erro 0x80070005 no windows?")
        self.assertIn("0x80070005", reply.lower())
        self.assertIn("ERROR_ACCESS_DENIED", reply)

if __name__ == "__main__":
    unittest.main()
