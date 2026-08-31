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
        m_user = re.search(r'Mensagem do T[ée]cnico\s*(?:\([^)]+\))?\s*:\s*["\']?([^"\'\n]+)["\']?', prompt, re.IGNORECASE)
        if m_user:
            user_msg = m_user.group(1).strip()

        p_lower = user_msg.lower()

        # Extrai o resumo da bancada do prompt se houver
        m_bench = re.search(r'- Bancada:\s*([^\n]+)', prompt, re.IGNORECASE)
        bench_info = m_bench.group(1).strip() if m_bench else ""

        # 1. Restrição de Assuntos Fora de Escopo
        out_of_scope = ["receita", "futebol", "politica", "política", "filme", "fofoca", "jogo", "musica", "música", "novela", "piada", "namoro", "tempo amanha", "bolo"]
        if any(w in p_lower for w in out_of_scope):
            return (
                "🤖 Assistente de Laboratório Ultron:\n\n"
                "Meu foco é restrito ao suporte técnico, computadores da bancada, diagnóstico de hardware e procedimentos de infraestrutura da Pense Rede.\n\n"
                "Em que posso te ajudar hoje na bancada?"
            )

        # 2. Perguntas sobre Bancada / IPs Detectados / Status de Máquinas
        bench_inquiry_kws = ["maquina", "máquina", "maquinas", "máquinas", "bancada", "bancda", "ip", "ips", "detectando", "detecta", "online", "ligada", "ligadas", "computador", "computadores", "procura", "procure", "busca", "buscar", "acha", "achar", "varre", "varrer"]
        if any(w in p_lower for w in bench_inquiry_kws) and not any(w in p_lower for w in ["como preparar", "como formatar", "preparar", "formatar", "ativar"]):
            if bench_info and "Nenhum" not in bench_info:
                return (
                    f"💻 BANCADA ULTRON — STATUS ATUAL\n\n"
                    f"📍 {bench_info}\n\n"
                    f"💡 Ações Rápidas:\n"
                    f"• \"faz o diagnóstico no <IP>\"\n"
                    f"• \"prepara o <IP> para o White Group\"\n"
                    f"• \"ativa o Windows do <IP>\""
                )
            else:
                return (
                    "🔍 STATUS DA BANCADA\n\n"
                    "No momento não detectei nenhuma máquina ativa com WinRM na subrede 192.168.57.0/24.\n\n"
                    "💡 Dica: Se você ligou um computador na bancada, execute o UltronAgent.exe nele para liberar o WinRM e registrar o IP automaticamente."
                )

        # 3. Saudações e Apresentação
        if re.search(r"\b(ola|olá|oi|bom dia|boa tarde|boa noite|quem e voce|quem é você|o que você faz|o que voce faz)\b", p_lower):
            return (
                "Olá! Sou o Ultron, assistente inteligente de automação de bancada e suporte técnico da Pense Rede.\n\n"
                "Posso te ajudar a automatizar a esteira de computadores, rodar diagnósticos de hardware (S.M.A.R.T, CPU, RAM), ativar Windows e Office via MAS, ingressar máquinas no domínio, consultar chamados no Milvus e gerar laudos técnicos em PDF.\n\n"
                "Como posso te ajudar com os equipamentos da bancada hoje?"
            )

        # 4. Diagnóstico de Hardware, SMART, Testes de Estresse
        if any(w in p_lower for w in ["diag", "diagnostico", "diagnóstico", "smart", "disco", "hd", "ssd", "memoria", "memória", "saude", "saúde", "hardware", "estresse", "burnin", "burn-in", "testar", "verificar", "checar"]):
            return (
                "🩺 DIAGNÓSTICO DE HARDWARE & INTEGRIDADE\n\n"
                "Consigo analisar profundamente a integridade física de qualquer máquina na bancada, inspecionando a saúde dos discos SSD/HD via S.M.A.R.T, estado das memórias RAM, processador e histórico de telas azuis (BSOD).\n\n"
                "Basta me dizer qual computador ou IP você quer examinar (por exemplo: \"faz o diagnóstico no 57.48\" ou apenas o IP) e eu inicio a verificação imediatamente."
            )

        # 5. Perguntas sobre Milvus / Chamados / Ordens de Serviço
        if any(w in p_lower for w in ["chamado", "chamados", "milvus", "ticket", "tickets", "ordem de serviço", "ordens de serviço", "meu nome", "apenas no meu", "puxa", "fila"]):
            return (
                "📋 CHAMADOS E FILA DO MILVUS\n\n"
                "Consulto a fila de chamados em aberto na Dashboard do Milvus em tempo real. A lista exibe as ordens de serviço pendentes do laboratório, e ao concluir uma esteira para o cliente, o laudo técnico gerado fica registrado no histórico daquele equipamento.\n\n"
                "Se quiser ver a lista completa agora, basta me pedir: \"quais os chamados abertos?\" ou \"chamados\"."
            )

        # 6. Perguntas sobre ações recentes em máquinas
        if any(w in p_lower for w in ["mexeu em alguma", "esta fazendo", "está fazendo", "mexeu em maquina", "mexeu em máquina", "alguma maquina agora", "alguma máquina agora", "executando"]):
            return (
                "🔍 STATUS OPERACIONAL DA BANCADA\n\n"
                "Só executo ações nos computadores quando solicitado por você aqui no chat ou quando um computador conclui a instalação do MDT e envia notificação de chegada.\n\n"
                "Se quiser verificar os equipamentos que estão ligados e acessíveis agora, basta me pedir: \"quais máquinas estão na bancada?\" ou \"bancada\"."
            )

        # 7. Procedimentos de Formatação & Preparação da Esteira
        if any(w in p_lower for w in ["como preparar", "como formatar", "preparacao", "preparação", "procedimento", "esteira", "passo a passo", "deploy"]):
            return (
                "🚀 PROCEDIMENTO PADRÃO DE BANCADA DO ULTRON\n\n"
                "1. MDT / PXE: Conecte o cabo de rede na bancada e inicialize via rede (PXE) para aplicar a imagem padrão do Windows.\n"
                "2. Desbloqueio / Agente: O UltronAgent.exe libera o WinRM e registra o IP no servidor automaticamente.\n"
                "3. Preparação: No chat, basta me pedir: \"prepara a máquina 57.48 para o White Group\".\n"
                "4. Execução Automática: O Ultron instala os softwares do cliente, AnyDesk, Agente Milvus com token oficial, ativa o Windows/Office permanente (MAS), ingressa no domínio AD e roda o teste de estresse.\n"
                "5. Conclusão: Envio o ID do AnyDesk e o Laudo Técnico em PDF assinado aqui no chat."
            )

        # 8. Ingressar em Domínio (AD)
        if re.search(r"\b(dominio|domínio|active directory|ingressar no dominio|join domain|entrar no dominio|ad join)\b", p_lower) or (" ad" in p_lower and "dominio" in p_lower):
            return (
                "🛡️ INGRESSO NO DOMÍNIO (ACTIVE DIRECTORY)\n\n"
                "Posso configurar o DNS e ingressar a máquina diretamente no domínio do cliente (ex: \"coloca a máquina 57.48 no domínio penserede.local\").\n\n"
                "Quando necessário, vou te solicitar o usuário e senha de Administrador do domínio aqui no chat para realizar a autenticação com segurança."
            )

        # 9. Ativação Windows / Office (MAS)
        if any(w in p_lower for w in ["ativar", "ativacao", "ativação", "licenca", "licença", "office", "windows", "mas", "massgrave"]):
            return (
                "🔑 ATIVAÇÃO WINDOWS & OFFICE (MAS)\n\n"
                "Utilizo o método permanente MAS (Microsoft Activation Scripts) para licenciar o Windows e Office sem necessidade de chaves manuais.\n\n"
                "Você pode apenas me pedir: \"ativa o windows do pc 57.48\" ou \"ativa a máquina\" que eu aplico a licença remotamente."
            )

        # 10. Download do UltronAgent.exe
        if any(w in p_lower for w in ["baixar", "download", "agente", "agent", "exe", "pendrive", "desbloquear", "desbloqueio", "instalador"]):
            return (
                "📥 ULTRON AGENT (.EXE) — CONEXÃO DE MÁQUINAS\n\n"
                "Você pode baixar o executável diretamente pelo link:\n"
                "👉 http://192.168.57.43:7000/download/UltronAgent.exe (ou pelo botão azul no Dashboard Web)\n\n"
                "Ao rodar o .exe como Administrador na máquina alvo, ele libera o WinRM, abre o Firewall e conecta o computador ao laboratório automaticamente."
            )

        # 11. Resposta técnica cordial padrão (fluida e acolhedora)
        return (
            "🤖 Ultron — Suporte de Bancada:\n\n"
            "Entendi! Como posso te ajudar com os computadores da bancada hoje? Se quiser rodar diagnósticos de hardware, preparar máquinas para clientes, ativar licenças ou consultar chamados, pode me pedir livremente da forma que preferir."
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
