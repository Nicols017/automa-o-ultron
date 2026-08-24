"""
Módulo de Análise Inteligente de Diagnóstico e Logs de Erro - Ultron Lab Automation
Compatível com múltiplos provedores: Ollama, vLLM, LM Studio ou qualquer API padrão OpenAI.
"""

import json
import re
import requests
from typing import Dict, Any, Optional, List

class DiagnosticAnalyzer:
    """Motor de inferência e análise de linguagem natural para o ecossistema Ultron."""

    DEFAULT_SYSTEM_PROMPT = (
        "Você é o ULTRON, sistema inteligente de automação de bancada e suporte técnico da Pense Rede.\n"
        "Suas diretrizes obrigatórias de resposta:\n"
        "1. Responda SEMPRE em Português do Brasil (pt-BR) com gramática impecável e terminologia técnica precisa.\n"
        "2. Seja DIRETO, OBJETIVO e CONCISO. Evite saudações repetitivas, preâmbulos, enrolações ou frases vazias.\n"
        "3. Quando instruído ou ao sugerir ações operacionais, forneça o comando exato (ex: `/preparar <IP> <cliente>`, `/diagnostico <IP>`).\n"
        "4. Utilize formatação Markdown limpa (tópicos com marcadores, negrito em palavras-chave e blocos de código para comandos/IPs).\n"
        "5. NUNCA gere blocos de pensamento interno, tags <think> ou explicações sobre o seu processo de raciocínio."
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

    # ------------------------------------------------------------------
    # Sanitização e Higienização de Texto
    # ------------------------------------------------------------------

    @staticmethod
    def _clean_llm_response(raw_text: str) -> str:
        """
        Higieniza a resposta gerada pelo LLM:
        - Remove tags <think>...</think> de modelos open-source (DeepSeek, Qwen).
        - Remove preâmbulos robóticos ou saudações redundantes.
        - Normaliza quebras de linha excessivas e blocos Markdown soltos.
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

        # 4. Remove saudações robóticas redundantes na primeira linha
        filler_patterns = [
            r"^(?:Olá|Oi|Com certeza|Certamente|Com prazer|Aqui está|Como assistente|Entendido|Claro|Com base nos dados|Analisando as informações|Segue o relatório|Segue abaixo)[^\n]*\n+",
        ]
        for pattern in filler_patterns:
            text = re.sub(pattern, "", text.strip(), flags=re.IGNORECASE)

        # 5. Normaliza espaçamentos e quebras de linha
        text = re.sub(r"\r\n", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)

        return text.strip()

    # ------------------------------------------------------------------
    # Chamadas aos Provedores de LLM
    # ------------------------------------------------------------------

    def _call_ollama(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        url = f"{self.base_url}/api/generate"
        payload = {
            "model": self.model,
            "prompt": prompt,
            "system": system_prompt or self.DEFAULT_SYSTEM_PROMPT,
            "stream": False,
            "options": {
                "temperature": self.temperature
            }
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        response = requests.post(url, json=payload, headers=headers, timeout=90)
        if response.status_code == 200:
            raw = response.json().get("response", "Resposta vazia recebida do modelo.")
            return self._clean_llm_response(raw)
        else:
            try:
                err_json = response.json()
                err_msg = err_json.get("error", "")
                if "requires more system memory" in err_msg:
                    return f"⚠️ O modelo '{self.model}' requer mais memória que o disponível ({err_msg}). Recomenda-se usar um modelo otimizado como 'qwen2.5:3b' rodando 'ollama run qwen2.5:3b'."
            except Exception:
                pass
            return f"⚠️ Erro na API Ollama (Status {response.status_code}): {response.text}"

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

        response = requests.post(url, json=payload, headers=headers, timeout=90)
        if response.status_code == 200:
            data = response.json()
            raw = data["choices"][0]["message"]["content"]
            return self._clean_llm_response(raw)
        else:
            return f"⚠️ Erro na API OpenAI-compatible (Status {response.status_code}): {response.text}"

    # ------------------------------------------------------------------
    # Métodos Públicos de Geração e Análise
    # ------------------------------------------------------------------

    def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """
        Gera uma resposta textual para um prompt livre aplicando sanitização e regras do Ultron.
        """
        try:
            if self.provider in ["openai", "openai_compatible", "vllm", "lmstudio"]:
                return self._call_openai_compatible(prompt, system_prompt=system_prompt)
            else:
                return self._call_ollama(prompt, system_prompt=system_prompt)
        except requests.exceptions.ConnectionError:
            return f"⚠️ Não foi possível conectar ao servidor de IA ({self.provider} em {self.base_url}). Verifique se o serviço está em execução."
        except requests.exceptions.Timeout:
            return "⚠️ A resposta da IA expirou por timeout (90s). O modelo pode estar sobrecarregado."
        except Exception as e:
            return f"⚠️ Falha no motor de IA ({self.provider}): {e}"

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
                response = requests.post(url, json=payload, headers=headers, timeout=90)
                if response.status_code == 200:
                    raw = response.json()["choices"][0]["message"]["content"]
                    return self._clean_llm_response(raw)
                return f"⚠️ Erro na API LLM (Status {response.status_code})"
            except Exception as e:
                return f"⚠️ Falha no motor de IA: {e}"

        history_text = "\n".join(f"{m.get('role', 'user').capitalize()}: {m.get('content', '')}" for m in messages)
        return self.generate(history_text, system_prompt=system_prompt)

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
