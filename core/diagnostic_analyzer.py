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
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        api_key: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        timeout_seconds: Optional[float] = None,
        chat_url: Optional[str] = None
    ):
        import os
        env_base = os.getenv("LLM_BASE_URL") or os.getenv("LLAMA_BASE_URL") or "http://192.168.57.31:8080/v1"
        self.base_url = (base_url or env_base).rstrip("/")
        self.chat_url = chat_url or os.getenv("LLAMA_CHAT_URL")
        self.model = model or os.getenv("LLM_MODEL") or os.getenv("LLAMA_MODEL") or "local"
        self.provider = (provider or os.getenv("LLM_PROVIDER") or "llama.cpp").lower()
        self.api_key = api_key or os.getenv("LLM_API_KEY") or "local-dev"

        try:
            self.temperature = float(temperature if temperature is not None else os.getenv("LLM_TEMPERATURE", "0.0"))
        except (ValueError, TypeError):
            self.temperature = 0.0

        try:
            self.max_tokens = int(max_tokens if max_tokens is not None else os.getenv("LLM_MAX_TOKENS", "1800"))
        except (ValueError, TypeError):
            self.max_tokens = 1800

        try:
            self.timeout_seconds = float(timeout_seconds if timeout_seconds is not None else os.getenv("LLM_TIMEOUT_SECONDS", "1200"))
        except (ValueError, TypeError):
            self.timeout_seconds = 1200.0

        # Timeout de conexão de 5s e leitura configurada
        self.request_timeout = (5.0, min(self.timeout_seconds, 1200.0))
        self.session = requests.Session()

    def _is_openai_compatible(self) -> bool:
        """Determina se o provedor utiliza o protocolo padrão OpenAI / llama.cpp / vLLM"""
        p = self.provider.strip().lower()
        if "ollama" in p:
            return False
        return any(x in p for x in ["openai", "llama", "vllm", "lmstudio", "local", "chat"])

    def _get_chat_url(self) -> str:
        """Resolve a URL final do endpoint de chat completions"""
        if self.chat_url:
            return self.chat_url
        base = self.base_url.rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        if base.endswith("/v1"):
            return f"{base}/chat/completions"
        return f"{base}/v1/chat/completions"

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

        # 3. Consulta de Bancada / IPs / Dispositivos Conectados / Máquinas Disponíveis
        ip_bench_words = ["ip", "ips", "maquina", "maquinas", "máquina", "máquinas", "pc", "pcs", "computador", "computadores", "dispositivo", "dispositivos", "rede", "bancada", "bancda"]
        query_words = ["quais", "qual", "quem", "tem", "disponivel", "disponiveis", "disponível", "disponíveis", "presente", "presentes", "ativo", "ativos", "online", "conectado", "conectados", "lista", "listar", "ver", "mostra", "mostrar", "status"]

        has_target = any(w in p_lower for w in ip_bench_words)
        has_query = any(w in p_lower for w in query_words)
        if (has_target and has_query) or any(w in p_lower for w in ["bancada", "bancda", "status bancada", "varredura", "scanner"]):
            if bench_info and "Nenhum" not in bench_info:
                return f"🖥️ **Status Atual da Bancada**\n\n📍 {bench_info}\n\n💬 Você pode me pedir diagnósticos, esteiras de preparação ou ativações indicando o IP desejado."
            else:
                return "🔍 **Bancada Ultron**\n\nNão detectei máquinas com WinRM ativo na bancada no momento. Verifique se os computadores estão ligados e com o cabo de rede conectado."

        # 4. Diagnóstico de Hardware, SMART, Saúde
        if any(w in p_lower for w in ["diag", "diagnostico", "diagnóstico", "smart", "saude", "saúde", "integridade", "disco", "hd", "ssd", "memoria", "memória", "estresse", "burnin", "burn-in"]):
            return (
                "🩺 **Diagnóstico de Hardware & Integridade**\n\n"
                "Consigo inspecionar a saúde dos discos (S.M.A.R.T), memória RAM, CPU e histórico de telas azuis (BSOD).\n\n"
                "Para iniciar, basta me enviar: *'verifica a saúde do <IP>'* ou *'diagnóstico no <IP>'*."
            )

        # 5. Perguntas sobre Chamados / Milvus
        if any(w in p_lower for w in ["chamado", "chamados", "milvus", "ticket", "tickets", "ordem de serviço", "ordens de serviço", "minhas os"]):
            return (
                "📋 **Chamados e Fila do Milvus**\n\n"
                "Consulto a fila de chamados pendentes do laboratório na Dashboard do Milvus.\n\n"
                "Para ver os chamados abertos agora, basta me pedir: *'quais os chamados abertos?'* ou digitar `/chamados`."
            )

        # 6. Procedimentos de Preparação / Formatação
        if any(w in p_lower for w in ["como preparar", "como formatar", "preparacao", "preparação", "procedimento", "esteira", "passo a passo"]):
            return (
                "🚀 **Procedimento de Esteira do Ultron**\n\n"
                "1. Conecte o PC na rede e aplique a imagem Windows via MDT/PXE (ou use o One-Liner / Bootstrap).\n"
                "2. O UltronAgent libera o WinRM e registra o IP no servidor automaticamente.\n"
                "3. No chat, me peça: *'prepara a máquina <IP> para o <Cliente>'*.\n"
                "4. Instalo os softwares do perfil, Agente Milvus, ativo Windows/Office, executo testes e te entrego o laudo PDF e ID do AnyDesk aqui."
            )

        # 7. Ativação Windows / Office (MAS)
        if any(w in p_lower for w in ["ativar", "ativacao", "ativação", "licenca", "licença", "office", "windows"]) or re.search(r"\b(mas|massgrave)\b", p_lower):
            return (
                "🔑 **Ativação Windows & Office (MAS)**\n\n"
                "Aplico a ativação permanente digital via MAS remotamente em qualquer máquina liberada da bancada.\n\n"
                "Basta me pedir: *'ativa o Windows do <IP>'*."
            )

        # 8. Mensagens na Tela / Pop-up
        if any(w in p_lower for w in ["mensagem", "msg", "popup", "pop-up", "aviso na tela", "notificar"]):
            return (
                "📢 **Envio de Mensagens na Tela**\n\n"
                "Posso exibir avisos e pop-ups na tela do usuário remotamente.\n\n"
                "Basta me enviar: *'manda uma mensagem para o IP <IP> <seu texto>'*."
            )

        # 9. Download do Executável do Agente
        if any(w in p_lower for w in ["baixar", "download", "agente", "agent", "exe", "executavel"]):
            return (
                "📥 **Ultron Agent (.EXE)**\n\n"
                "Você pode baixar o executável diretamente aqui no chat ou pelo link:\n"
                "👉 http://192.168.57.43:7000/download/UltronAgent.exe\n\n"
                "Execute como Administrador na máquina alvo para liberar o acesso com Zero-Prompt."
            )

        # 9.1 AnyDesk e Acesso Remoto
        if any(w in p_lower for w in ["anydesk", "any desk", "anidisk", "anidesk", "acesso remoto", "qual o id", "passa o id"]):
            m_ip = re.search(r"\b((?:192\.168\.\d{1,3}\.\d{1,3}|57\.\d{1,3}|\d{1,3}\.\d{1,3}))\b", user_msg)
            ip_str = m_ip.group(1) if m_ip else "da bancada"
            return (
                f"🔑 **AnyDesk / Acesso Remoto — {ip_str}**\n\n"
                f"O Ultron captura e disponibiliza o ID do AnyDesk automaticamente em tempo real.\n\n"
                f"💬 Digite: *'qual o anydesk do {ip_str}'* ou `/anydesk` para ver os links diretos de acesso."
            )

        # 10. Resposta inteligente contextualizada
        m_ip = re.search(r"\b((?:192\.168\.\d{1,3}\.\d{1,3}|57\.\d{1,3}|\d{1,3}\.\d{1,3}))\b", user_msg)
        if m_ip:
            ip_str = m_ip.group(1)
            return (
                f"Encontrei a máquina **{ip_str}**, mas não entendi exatamente o que fazer com ela.\n\n"
                f"Se quiser, posso rodar as seguintes automações rápidas nela:\n"
                f"▶️ `/diagnostico {ip_str}` para checar a saúde geral (Discos, RAM, BSOD).\n"
                f"▶️ `/preparar {ip_str} <cliente>` para iniciar a esteira de formatação.\n"
                f"▶️ `/ativar {ip_str}` para aplicar o licenciamento Windows.\n"
                f"▶️ `/reiniciar {ip_str}` para forçar o reboot.\n\n"
                f"Ou acesse ela via `/anydesk` se for algo manual."
            )

        return (
            "Como posso te ajudar com os computadores da bancada agora?\n\n"
            "• **Ver computadores na bancada:** *'quem tá na bancada?'* ou `/bancada`\n"
            "• **Diagnóstico de hardware:** *'diagnóstico no <IP>'*\n"
            "• **Preparação de esteira:** *'preparar <IP> para <Cliente>'*\n"
            "• **Chamados abertos:** `/chamados`\n"
            "• **Menu completo de opções:** `/ajuda`"
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

        response = self.session.post(url, json=payload, headers=headers, timeout=self.request_timeout)
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
        url = self._get_chat_url()
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
            "temperature": self.temperature,
            "max_tokens": self.max_tokens
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        response = self.session.post(url, json=payload, headers=headers, timeout=self.request_timeout)
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
            if self._is_openai_compatible():
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
        if self._is_openai_compatible():
            url = self._get_chat_url()
            all_messages = [{"role": "system", "content": system_prompt or self.DEFAULT_SYSTEM_PROMPT}] + messages
            payload = {
                "model": self.model,
                "messages": all_messages,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens
            }
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            try:
                response = self.session.post(url, json=payload, headers=headers, timeout=self.request_timeout)
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

    def _generate_rule_based_diagnosis(self, telemetry: Dict[str, Any]) -> str:
        """Gera parecer executivo de 4 pontos estruturado diretamente dos dados de telemetria da máquina."""
        disks = telemetry.get("disks", [])
        bsods = telemetry.get("bsod_dumps", [])
        dev_errs = telemetry.get("device_errors", [])
        ram_gb = telemetry.get("ram_gb", 0)
        cpu = telemetry.get("cpu", "Processador")

        unhealthy_disks = [d for d in disks if d.get("health") not in ["Healthy", "OK", "0", 0]]
        has_bsod = len(bsods) > 0
        has_driver_errs = len(dev_errs) > 0

        issues = []
        if unhealthy_disks:
            issues.append(f"Alerta S.M.A.R.T em disco: {', '.join(d.get('model', 'Disco') for d in unhealthy_disks)}")
        if has_bsod:
            issues.append(f"{len(bsods)} registro(s) recente(s) de Tela Azul (BSOD)")
        if has_driver_errs:
            issues.append(f"{len(dev_errs)} dispositivo(s) com driver genérico ou ausente")

        issues_str = "; ".join(issues) if issues else "Nenhuma falha crítica detectada."

        if unhealthy_disks:
            root_cause = "Degradação física ou setores defeituosos detectados na unidade de armazenamento."
            actions = "Substituir unidade de armazenamento danificada antes de iniciar a instalação de softwares."
            verdict = "REQUER MANUTENÇÃO DE HARDWARE ANTES DO DEPLOY"
        elif has_bsod:
            root_cause = "Histórico de travamento por falha de driver, superaquecimento ou instabilidade de memória."
            actions = "Executar esteira de atualização de drivers e rodar teste de estresse térmico."
            verdict = "APROVADA COM RESSALVAS (MONITORAR ESTRESSE)"
        elif has_driver_errs:
            root_cause = f"Sistema operacional recém-instalado com {len(dev_errs)} drivers pendentes de instalação."
            actions = "Prosseguir para esteira de preparação e aplicar o perfil do cliente com atualização de drivers."
            verdict = "APROVADA PARA PREPARAÇÃO"
        else:
            root_cause = "Hardware 100% íntegro com processador, memória e barramentos operando dentro dos parâmetros ideais."
            actions = "Prosseguir para esteira de automação e instalação do perfil do cliente."
            verdict = "APROVADA PARA PREPARAÇÃO"

        return (
            f"1. 🚨 **Problemas Identificados:** {issues_str}\n"
            f"2. 🔬 **Causa Raiz:** {root_cause}\n"
            f"3. 🛠️ **Ações de Reparo Recomendadas:** {actions}\n"
            f"4. 🩺 **Veredito da Máquina:** **{verdict}**"
        )

    def analyze_logs(self, telemetry_data: Dict[str, Any]) -> str:
        """
        Envia os dados de telemetria e S.M.A.R.T para o LLM configurado e retorna
        um parecer técnico executivo de alto padrão para o laudo e chat.
        Se o LLM estiver indisponível, gera o parecer técnico estruturado diretamente dos dados.
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

        try:
            res = self.generate(prompt, system_prompt=system_prompt)
            if res and "1. 🚨" in res and not res.startswith("🩺 **Diagnóstico"):
                return res
        except Exception:
            pass

        return self._generate_rule_based_diagnosis(telemetry_data)
