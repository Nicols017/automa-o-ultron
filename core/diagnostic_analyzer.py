"""
Módulo de Análise Inteligente de Diagnóstico e Logs de Erro - Ultron Lab Automation
Compatível com múltiplos provedores (Ollama, vLLM, LM Studio, OpenAI, Gemini) com Knowledge Engine integrado para alta disponibilidade e conversação fluida.
"""

import json
import re
import requests
from typing import Dict, Any, Optional, List

class DiagnosticAnalyzer:
    """Motor de inferência e análise de linguagem natural para o ecossistema Ultron."""

    DEFAULT_SYSTEM_PROMPT = (
        "Você é o ULTRON, Inteligência Artificial de Automação de Bancada e Suporte Técnico da Pense Rede.\n"
        "Você atua como assistente sênior de infraestrutura, hardware, formatação e suporte aos técnicos de TI do laboratório.\n\n"
        "DIRETRIZES FUNDAMENTAIS:\n"
        "1. Responda em Português do Brasil (pt-BR) com perfeição técnica, clareza e cordialidade profissional.\n"
        "2. Converse naturalmente com o técnico, tirando dúvidas de bancada, procedimentos de formatação, scripts, softwares, domínio Active Directory, chamados Milvus e diagnósticos de hardware.\n"
        "3. RESTRIÇÃO DE ESCOPO: Mantenha as conversas estritamente focadas em suporte de TI, manutenção de computadores, bancada de laboratório, infraestrutura e procedimentos operacionais. Se for perguntado sobre temas completamente alheios (receitas, fofocas, assuntos não-TI), responda educadamente redirecionando o técnico para as tarefas de bancada.\n"
        "4. Quando relevante, sugira comandos de atalho práticos como `/bancada`, `/diagnostico <IP>`, `/preparar <IP> <cliente>`, `/chamados`, `/ativar <IP>` ou `/ajuda`.\n"
        "5. NUNCA gere tags <think> ou blocos de raciocínio interno expostos."
    )

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "custom_model",
        provider: str = "ollama",
        api_key: Optional[str] = None,
        temperature: float = 0.2
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.provider = provider.lower()
        self.api_key = api_key
        self.temperature = temperature
        # Timeout de conexão curto (3.5s) e de leitura razoável (25s) para nunca travar a experiência do técnico
        self.request_timeout = (3.5, 25.0)

    # ------------------------------------------------------------------
    # Sanitização e Higienização de Texto
    # ------------------------------------------------------------------

    @staticmethod
    def _clean_llm_response(raw_text: str) -> str:
        """
        Higieniza a resposta gerada pelo LLM:
        - Remove tags <think>...</think> de modelos open-source (DeepSeek, Qwen).
        - Remove preâmbulos robóticos ou saudações redundantes excessivas.
        - Normaliza quebras de linha.
        """
        if not raw_text:
            return ""

        text = raw_text

        # 1. Remove blocos <think>...</think> (completos ou não finalizados)
        text = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.IGNORECASE)
        text = re.sub(r"<think>[\s\S]*$", "", text, flags=re.IGNORECASE)
        text = re.sub(r"</think>", "", text, flags=re.IGNORECASE)

        # 2. Remove tags de prompt chatml ou raw tokens remanescentes
        text = re.sub(r"<\|im_start\|>[\s\S]*?<\|im_end\|>", "", text)
        text = re.sub(r"<\|[a-zA-Z0-9_-]+\|>", "", text)

        # 3. Remove blocos markdown externos redundantes como ```markdown ... ```
        fence_match = re.match(r"^```(?:markdown|text)?\s*\n([\s\S]*?)\n```\s*$", text.strip(), flags=re.IGNORECASE)
        if fence_match:
            text = fence_match.group(1)

        # 4. Normaliza espaçamentos e quebras de linha
        text = re.sub(r"\r\n", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)

        return text.strip()

    # ------------------------------------------------------------------
    # Motor Especialista Fallback (Base de Conhecimento Ultron)
    # ------------------------------------------------------------------

    def _fallback_knowledge_response(self, prompt: str) -> str:
        """
        Responde perguntas técnicas e conversacionais de bancada com alta precisão
        quando o modelo LLM externo não está acessível imediatamente.
        Aplica regras de restrição de escopo e domínio técnico em linguagem natural fluida.
        """
        # Extrai a mensagem real do usuário se o prompt contiver cabeçalhos de contexto
        user_msg = prompt
        m_user = re.search(r'(?:Mensagem do T[ée]cnico\s*(?:\([^)]+\))?|Mensagem recebida)\s*:\s*["\']?([^"\'\n]+)["\']?', prompt, re.IGNORECASE)
        if m_user:
            user_msg = m_user.group(1).strip()

        p_lower = user_msg.lower()

        # Extrai o resumo da bancada do prompt se houver
        m_bench = re.search(r'- Bancada:\s*([^\n]+)', prompt, re.IGNORECASE)
        bench_info = m_bench.group(1).strip() if m_bench else ""

        # 1. Restrição de Assuntos Fora de Escopo (Conversa não relacionada a TI)
        out_of_scope = ["receita", "futebol", "politica", "política", "filme", "fofoca", "jogo", "musica", "música", "novela", "piada", "namoro", "tempo amanha", "bolo"]
        if any(w in p_lower for w in out_of_scope):
            return (
                "🤖 Ultron — Suporte de Bancada:\n\n"
                "Meu foco é restrito ao suporte técnico, computadores da bancada, diagnóstico de hardware e procedimentos de automação da Pense Rede.\n\n"
                "Em que posso te ajudar com os equipamentos do laboratório?"
            )

        # 2. Saudações e Conversa Inicial
        if re.search(r"^(ola|olá|oi|bom dia|boa tarde|boa noite|e ai|e aí|opa|fala ultron|tudo bem|como vai|quem e voce|quem é você|o que você faz|o que voce faz)\b", p_lower):
            return (
                "Olá! Sou o Ultron, assistente de automação de bancada e suporte técnico da Pense Rede.\n\n"
                "Posso te ajudar a automatizar a preparação de computadores para clientes, rodar diagnósticos de hardware (S.M.A.R.T, CPU, RAM), ativar Windows e Office (MAS), fazer backup de usuários, enviar mensagens na tela e emitir laudos em PDF.\n\n"
                "Como posso te ajudar hoje?"
            )

        # 3. Consulta Explícita de Bancada / Dispositivos Conectados
        explicit_bench = [
            "quem esta na bancada", "quem está na bancada", "quais maquinas estao ligadas", "quais máquinas estão ligadas",
            "quais pcs estao ligados", "quais pcs estão ligados", "ver bancada", "status da bancada", "lista de maquinas",
            "lista de máquinas", "quem ta online", "quem tá online", "quem ta ligado", "quem tá ligado"
        ]
        if any(kw in p_lower for kw in explicit_bench) or p_lower in ["bancada", "bancda", "status bancada"]:
            if bench_info and "Nenhum" not in bench_info:
                return f"💻 BANCADA ULTRON — STATUS ATUAL\n\n📍 {bench_info}\n\n💡 Você pode me pedir diagnósticos, esteiras de preparação ou ativações indicando o IP da máquina."
            else:
                return "🔍 BANCADA ULTRON\n\nNo momento não detectei máquinas com WinRM ativo na subrede da bancada. Se você ligou um computador, execute o UltronAgent.exe nele para liberar o acesso automaticamente."

        # 4. Diagnóstico de Hardware, SMART, Saúde
        if any(w in p_lower for w in ["diag", "diagnostico", "diagnóstico", "smart", "saude", "saúde", "integridade", "disco", "hd", "ssd", "memoria", "memória", "estresse", "burnin", "burn-in"]):
            return (
                "🩺 DIAGNÓSTICO DE HARDWARE & INTEGRIDADE\n\n"
                "Consigo inspecionar a saúde dos discos (S.M.A.R.T), estado de memória RAM, CPU e histórico de telas azuis (BSOD).\n\n"
                "Para iniciar, basta me enviar: \"verifica a saúde do <IP>\" ou \"diagnóstico no <IP>\"."
            )

        # 5. Perguntas sobre Chamados / Milvus
        if any(w in p_lower for w in ["chamado", "chamados", "milvus", "ticket", "tickets", "ordem de serviço", "ordens de serviço", "minhas os"]):
            return (
                "📋 CHAMADOS E FILA DO MILVUS\n\n"
                "Consulto a fila de ordens de serviço pendentes do laboratório na Dashboard do Milvus.\n\n"
                "Para ver os chamados em aberto agora, basta me pedir: \"quais os chamados abertos?\" ou digitar a opção [ 11 ]."
            )

        # 6. Procedimentos de Preparação / Formatação
        if any(w in p_lower for w in ["como preparar", "como formatar", "preparacao", "preparação", "procedimento", "esteira", "passo a passo"]):
            return (
                "🚀 PROCEDIMENTO DE ESTEIRA DO ULTRON\n\n"
                "1. Conecte o PC na rede e aplique a imagem Windows via MDT/PXE.\n"
                "2. O UltronAgent.exe libera o WinRM e registra o IP no servidor automaticamente.\n"
                "3. No chat, me peça: \"prepara a máquina <IP> para o <Cliente>\".\n"
                "4. Instalo os softwares do perfil, Agente Milvus, ativo Windows/Office, executo testes e te entrego o laudo PDF e ID do AnyDesk aqui."
            )

        # 7. Ativação Windows / Office (MAS)
        if any(w in p_lower for w in ["ativar", "ativacao", "ativação", "licenca", "licença", "office", "windows"]) or re.search(r"\b(mas|massgrave)\b", p_lower):
            return (
                "🔑 ATIVAÇÃO WINDOWS & OFFICE (MAS)\n\n"
                "Aplico a ativação permanente digital via MAS remotamente em qualquer máquina liberada da bancada.\n\n"
                "Basta me pedir: \"ativa o Windows do <IP>\"."
            )

        # 8. Mensagens na Tela / Pop-up
        if any(w in p_lower for w in ["mensagem", "msg", "popup", "pop-up", "aviso na tela", "notificar"]):
            return (
                "📢 ENVIO DE MENSAGENS NA TELA\n\n"
                "Posso exibir caixas de mensagem e avisos na tela do usuário remotamente.\n\n"
                "Basta me enviar: \"manda uma mensagem para o IP <IP> <seu texto>\"."
            )

        # 9. Download do Executável do Agente
        if any(w in p_lower for w in ["baixar", "download", "agente", "agent", "exe", "executavel"]):
            return (
                "📥 ULTRON AGENT (.EXE)\n\n"
                "Você pode baixar o executável diretamente aqui no chat ou pelo link:\n"
                "👉 http://192.168.57.43:7000/download/UltronAgent.exe\n\n"
                "Execute como Administrador na máquina alvo para liberar o acesso com Zero-Prompt."
            )

        # 10. Resposta inteligente quando o usuário pede algo não suportado ou conversa técnica
        # Extrai se o usuário citou algum IP na frase não suportada
        m_ip = re.search(r"\b((?:192\.168\.\d{1,3}\.\d{1,3}|57\.\d{1,3}|\d{1,3}\.\d{1,3}))\b", user_msg)
        if m_ip:
            ip_str = m_ip.group(1)
            return (
                f"🤖 Ultron — Suporte de Bancada:\n\n"
                f"Entendi que você se referiu à máquina {ip_str}, porém **atualmente eu não possuo essa funcionalidade automatizada** de forma integrada.\n\n"
                f"💡 Se precisar operar essa máquina, você pode acessar via AnyDesk/RDP ou executar manualmente.\n\n"
                f"As automações que posso executar nela agora são:\n"
                f"• \"verifica a saúde do {ip_str}\" (Diagnóstico S.M.A.R.T e Hardware)\n"
                f"• \"prepara o {ip_str} para <cliente>\" (Esteira de Softwares e Configuração)\n"
                f"• \"ativa o Windows do {ip_str}\" (Licenciamento MAS)\n"
                f"• \"manda uma mensagem para o {ip_str} <texto>\" (Aviso na tela)\n"
                f"• \"reinicia o {ip_str}\" (Controle de energia)\n\n"
                f"Como prefere prosseguir?"
            )

        return (
            "🤖 Ultron — Suporte de Bancada:\n\n"
            "Entendi o que você disse! Porém, **atualmente não possuo uma função automática para essa solicitação específica**.\n\n"
            "Minhas principais automações ativas no laboratório são:\n"
            "• Diagnóstico de Hardware & Saúde de Discos (S.M.A.R.T)\n"
            "• Preparação de Esteira Completa para Clientes da Pense Rede\n"
            "• Ativação Permanente de Windows & Office (MAS)\n"
            "• Backup de Perfil de Usuário para o Storage\n"
            "• Envio de Avisos/Pop-ups na Tela\n"
            "• Reiniciar ou Desligar Máquinas Remotamente\n\n"
            "Como posso te ajudar com os computadores da bancada agora?"
        )

    # ------------------------------------------------------------------
    # Chamadas aos Provedores de LLM
    # ------------------------------------------------------------------

    def _call_ollama(self, prompt: str, system_prompt: Optional[str] = None, retry_fallback: bool = True) -> str:
        url = f"{self.base_url}/api/generate"
        payload = {
            "model": self.model,
            "prompt": prompt,
            "system": system_prompt or self.DEFAULT_SYSTEM_PROMPT,
            "stream": False,
            "options": {
                "temperature": self.temperature,
                "num_ctx": 2048,
                "num_predict": 1024,
            }
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        response = requests.post(url, json=payload, headers=headers, timeout=self.request_timeout)
        if response.status_code == 200:
            raw = response.json().get("response", "Resposta vazia recebida do modelo.")
            return self._clean_llm_response(raw)
        else:
            try:
                err_json = response.json()
                err_msg = err_json.get("error", "")
                if "requires more system memory" in err_msg and retry_fallback:
                    alt_model = "llama3:latest" if self.model != "llama3:latest" else "qwen2.5:7b"
                    orig_model = self.model
                    self.model = alt_model
                    try:
                        res = self._call_ollama(prompt, system_prompt, retry_fallback=False)
                        self.model = orig_model
                        return res
                    except Exception:
                        self.model = orig_model
            except Exception:
                pass
            return self._fallback_knowledge_response(prompt)

    def _call_openai_compatible(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        url = f"{self.base_url}/v1/chat/completions"
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt or self.DEFAULT_SYSTEM_PROMPT
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "temperature": self.temperature
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        response = requests.post(url, json=payload, headers=headers, timeout=self.request_timeout)
        if response.status_code == 200:
            data = response.json()
            raw = data["choices"][0]["message"]["content"]
            return self._clean_llm_response(raw)
        else:
            return self._fallback_knowledge_response(prompt)

    # ------------------------------------------------------------------
    # Métodos Públicos de Geração e Análise
    # ------------------------------------------------------------------

    def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """
        Gera uma resposta textual com fallback gracioso para garantir resposta instantânea.
        """
        try:
            if self.provider in ["openai", "openai_compatible", "vllm", "lmstudio"]:
                return self._call_openai_compatible(prompt, system_prompt=system_prompt)
            else:
                return self._call_ollama(prompt, system_prompt=system_prompt)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            # Se o LLM local/remoto estiver indisponível ou demorar, responde imediatamente via Knowledge Engine
            return self._fallback_knowledge_response(prompt)
        except Exception:
            return self._fallback_knowledge_response(prompt)

    def analyze(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """Alias para generate() para compatibilidade direta."""
        return self.generate(prompt, system_prompt=system_prompt)

    def chat(self, messages: List[Dict[str, str]], system_prompt: Optional[str] = None) -> str:
        """
        Gera uma resposta considerando histórico de mensagens de chat.
        """
        if self.provider in ["openai", "openai_compatible", "vllm", "lmstudio"]:
            url = f"{self.base_url}/v1/chat/completions"
            all_messages = [{"role": "system", "content": system_prompt or self.DEFAULT_SYSTEM_PROMPT}] + messages
            payload = {
                "model": self.model,
                "messages": all_messages,
                "temperature": self.temperature
            }
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            try:
                response = requests.post(url, json=payload, headers=headers, timeout=self.request_timeout)
                if response.status_code == 200:
                    raw = response.json()["choices"][0]["message"]["content"]
                    return self._clean_llm_response(raw)
            except Exception:
                pass

        last_user_msg = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                last_user_msg = m.get("content", "")
                break

        return self.generate(last_user_msg or "Olá", system_prompt=system_prompt)

    def analyze_logs(self, telemetry_data: Dict[str, Any]) -> str:
        """
        Envia os dados de telemetria e S.M.A.R.T para o LLM configurado e retorna
        um parecer técnico executivo de alto padrão para o laudo e chat.
        """
        system_prompt = (
            "Você é o ULTRON, perito sênior em hardware de computadores e suporte de TI da Pense Rede.\n"
            "Sua missão é emitir um laudo técnico executivo estritamente profissional, claro e direto.\n"
            "Diretrizes:\n"
            "- Idioma: Português do Brasil (pt-BR).\n"
            "- Não inclua saudações, introduções ou conversas fiadas.\n"
            "- Responda exatamente na estrutura solicitada de 4 pontos.\n"
            "- Se não houver problemas graves, afirme com clareza e autoridade técnica.\n"
            "- Seja prático: indique comandos ou ações físicas exatas de bancada."
        )

        prompt = f"""Analise a telemetria e logs de hardware da máquina de bancada abaixo:

--- DADOS DA MÁQUINA ---
{json.dumps(telemetry_data, indent=2, ensure_ascii=False)}
------------------------

Responda estritamente no seguinte formato executivo em Markdown:

1. 🚨 **Problemas Identificados:** (Resumo claro de falhas em discos, memória, drivers ou BSOD. Se nenhum erro existir, declare explicitamente: "Nenhuma falha crítica detectada.")
2. 🔬 **Causa Raiz Provável:** (Explicação técnica objetiva do diagnóstico ou comprovação de integridade operacional).
3. 🛠️ **Ações de Reparo Recomendadas:** (Passo a passo técnico prático para o técnico de bancada. Ex: prosseguir para esteira de software, substituir unidade de disco, executar teste de memória MemTest86, etc.)
4. 🩺 **Veredito da Máquina:** (Indique claramente: **APROVADA PARA PREPARAÇÃO** ou **REQUER MANUTENÇÃO DE HARDWARE ANTES DO DEPLOY**)."""

        return self.generate(prompt, system_prompt=system_prompt)
