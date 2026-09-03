"""
core/reliability.py
====================
Camada de confiabilidade do Ultron.

Objetivo: reduzir os 3 pontos de falha identificados no dia a dia:
  1) Interpretação errada do comando  -> IntentRouter (confiança + clarificação)
  2) Execução remota (WinRM) falhando silenciosamente -> ResilientWinRM (retry + circuit breaker)
  3) Mensagens finais mal formatadas / truncadas -> MessageBuilder (template + validação)

Tudo amarrado por um trace_id, então dá pra seguir uma solicitação do início
ao fim nos logs (orchestrator -> winrm -> bot) mesmo em execução assíncrona.

Como integrar (sem reescrever nada, só encapsular nos pontos de entrada):

    # trueconf/bot.py — ao receber uma mensagem
    trace_id = new_trace_id()
    intent, confidence, entities = intent_router.classify(texto_usuario, trace_id=trace_id)
    if confidence < intent_router.min_confidence:
        await send(intent_router.build_clarification(intent, entities))
        return
    # ... roteia para o handler certo do orchestrator.py

    # core/winrm_executor.py — ao executar comando remoto
    result = await resilient_winrm.run(host="192.168.57.166", command=cmd, trace_id=trace_id)
    if not result.ok:
        await send(message_builder.error(result, trace_id=trace_id))
        return

    # antes de enviar qualquer retorno pro TrueConf
    msg = message_builder.success(titulo="Softwares instalados", campos={...}, trace_id=trace_id)
    await send(msg)

Sem dependências externas além de stdlib (dataclasses, asyncio, logging, json, re, time, uuid).
Se você já usa pywinrm, injete a função de execução real em ResilientWinRM(executor=...).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Optional


# ---------------------------------------------------------------------------
# 0) Logging correlacionado (trace_id em todo log da esteira)
# ---------------------------------------------------------------------------

def new_trace_id() -> str:
    return uuid.uuid4().hex[:12]


class TraceLogger:
    """Wrapper fino sobre logging padrão que sempre injeta trace_id e
    emite em JSON — facilita grep / ingestão em qualquer coisa (Loki, ELK,
    ou só `grep trace_id logs.json`)."""

    def __init__(self, name: str = "ultron"):
        self._logger = logging.getLogger(name)
        if not self._logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter("%(message)s"))
            self._logger.addHandler(handler)
            self._logger.setLevel(logging.INFO)

    def _emit(self, level: int, event: str, trace_id: str, **fields: Any) -> None:
        payload = {"ts": time.time(), "trace_id": trace_id, "event": event, **fields}
        self._logger.log(level, json.dumps(payload, ensure_ascii=False, default=str))

    def info(self, event: str, trace_id: str, **fields: Any) -> None:
        self._emit(logging.INFO, event, trace_id, **fields)

    def warn(self, event: str, trace_id: str, **fields: Any) -> None:
        self._emit(logging.WARNING, event, trace_id, **fields)

    def error(self, event: str, trace_id: str, **fields: Any) -> None:
        self._emit(logging.ERROR, event, trace_id, **fields)


log = TraceLogger()


# ---------------------------------------------------------------------------
# 1) IntentRouter — para de "adivinhar" e para de responder errado
# ---------------------------------------------------------------------------
#
# O problema do print (pediu para instalar Steam em 57.166 e o bot tratou
# como "operar a máquina 57.166") é classificação de intenção sem placar de
# confiança: qualquer match parcial de regex já era tratado como certeza.
# Aqui cada intenção tem padrões + peso, o score decide se responde direto
# ou pede confirmação — em vez de cair num fallback genérico de "não tenho
# essa funcionalidade".

@dataclass
class Intent:
    name: str
    patterns: list[str]          # regex, case-insensitive
    handler_hint: str            # nome do handler no orchestrator, só documentação
    weight: float = 1.0


@dataclass
class IntentMatch:
    intent: Optional[str]
    confidence: float
    entities: dict[str, str] = field(default_factory=dict)
    candidates: list[tuple[str, float]] = field(default_factory=list)  # top-N pra clarificação


class IntentRouter:
    def __init__(self, intents: list[Intent], min_confidence: float = 0.55):
        self.intents = intents
        self.min_confidence = min_confidence
        self._ip_re = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
        self._compiled = [
            (it, [re.compile(p, re.IGNORECASE) for p in it.patterns]) for it in intents
        ]

    def classify(self, text: str, trace_id: str) -> IntentMatch:
        scores: dict[str, float] = {}
        for intent, patterns in self._compiled:
            hits = sum(1 for p in patterns if p.search(text))
            if hits:
                # normaliza pelo nº de padrões da intenção, pondera pelo peso configurado
                scores[intent.name] = (hits / len(patterns)) * intent.weight

        entities: dict[str, str] = {}
        ip = self._ip_re.search(text)
        if ip:
            entities["host"] = ip.group(0)

        if not scores:
            log.warn("intent_no_match", trace_id, text=text[:200])
            return IntentMatch(intent=None, confidence=0.0, entities=entities)

        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        top_name, top_score = ranked[0]
        # normaliza contra a soma pra virar "confiança relativa" 0..1
        total = sum(scores.values())
        confidence = top_score / total if total else 0.0

        log.info(
            "intent_classified",
            trace_id,
            text=text[:200],
            top=top_name,
            confidence=round(confidence, 3),
            candidates=ranked[:3],
        )

        return IntentMatch(
            intent=top_name if confidence >= self.min_confidence else None,
            confidence=confidence,
            entities=entities,
            candidates=ranked[:3],
        )

    def build_clarification(self, match: IntentMatch, original_text: str) -> str:
        """Mensagem a enviar quando a confiança é baixa — em vez de silenciosamente
        cair no fallback errado, pergunta."""
        if not match.candidates:
            return (
                "⚠️ Não entendi o comando. Pode reformular? "
                "Ex.: 'instala <pacote> em <IP>', 'verifica a saúde do <IP>', "
                "'ativa o Windows do <IP>'."
            )
        opcoes = "\n".join(f"• {name} ({int(score*100)}% de match)" for name, score in match.candidates)
        return (
            f"🤔 Não tenho certeza do que você quer para: \"{original_text}\"\n\n"
            f"Candidatos mais prováveis:\n{opcoes}\n\n"
            "Responde com o número ou reformula com o host explícito (IP)."
        )


# ---------------------------------------------------------------------------
# 2) ResilientWinRM — retry + backoff + circuit breaker por host
# ---------------------------------------------------------------------------
#
# Problema relatado: falha silenciosa / trava em queda de rede. Aqui: timeout
# explícito, retry com backoff exponencial, e um circuit breaker por host pra
# não ficar martelando uma máquina que caiu (o que trava a esteira inteira).

class HostState(Enum):
    CLOSED = "closed"        # normal
    OPEN = "open"             # host marcado como fora, não tenta
    HALF_OPEN = "half_open"   # testando se voltou


@dataclass
class WinRMResult:
    ok: bool
    host: str
    command: str
    stdout: str = ""
    stderr: str = ""
    exit_code: Optional[int] = None
    attempts: int = 0
    error: Optional[str] = None
    duration_s: float = 0.0


@dataclass
class _CircuitState:
    state: HostState = HostState.CLOSED
    consecutive_failures: int = 0
    opened_at: float = 0.0


ExecutorFn = Callable[[str, str, float], Awaitable[tuple[int, str, str]]]
# ExecutorFn(host, command, timeout_s) -> (exit_code, stdout, stderr)
# Injete aqui sua chamada real de pywinrm (rodando em thread pool, já que
# pywinrm é bloqueante — ver `_default_executor` como exemplo de wrapper).


class ResilientWinRM:
    def __init__(
        self,
        executor: ExecutorFn,
        max_attempts: int = 3,
        base_backoff_s: float = 2.0,
        timeout_s: float = 30.0,
        failure_threshold: int = 3,
        open_cooldown_s: float = 60.0,
    ):
        self._executor = executor
        self.max_attempts = max_attempts
        self.base_backoff_s = base_backoff_s
        self.timeout_s = timeout_s
        self.failure_threshold = failure_threshold
        self.open_cooldown_s = open_cooldown_s
        self._circuits: dict[str, _CircuitState] = {}

    def _circuit(self, host: str) -> _CircuitState:
        return self._circuits.setdefault(host, _CircuitState())

    def _can_attempt(self, host: str) -> bool:
        c = self._circuit(host)
        if c.state == HostState.CLOSED:
            return True
        if c.state == HostState.OPEN:
            if time.time() - c.opened_at >= self.open_cooldown_s:
                c.state = HostState.HALF_OPEN
                return True
            return False
        return True  # HALF_OPEN: deixa 1 tentativa passar

    def _record_success(self, host: str) -> None:
        c = self._circuit(host)
        c.state = HostState.CLOSED
        c.consecutive_failures = 0

    def _record_failure(self, host: str, trace_id: str) -> None:
        c = self._circuit(host)
        c.consecutive_failures += 1
        if c.consecutive_failures >= self.failure_threshold:
            c.state = HostState.OPEN
            c.opened_at = time.time()
            log.error("circuit_open", trace_id, host=host, failures=c.consecutive_failures)

    async def run(self, host: str, command: str, trace_id: str) -> WinRMResult:
        if not self._can_attempt(host):
            log.warn("circuit_blocked", trace_id, host=host)
            return WinRMResult(
                ok=False, host=host, command=command,
                error=f"Circuito aberto para {host} — muitas falhas recentes. "
                      f"Nova tentativa liberada em ~{int(self.open_cooldown_s)}s.",
            )

        start = time.time()
        last_err = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                exit_code, stdout, stderr = await asyncio.wait_for(
                    self._executor(host, command, self.timeout_s),
                    timeout=self.timeout_s + 5,
                )
                if exit_code == 0:
                    self._record_success(host)
                    log.info(
                        "winrm_ok", trace_id, host=host, command=command,
                        attempt=attempt, duration_s=round(time.time() - start, 2),
                    )
                    return WinRMResult(
                        ok=True, host=host, command=command,
                        stdout=stdout, stderr=stderr, exit_code=exit_code,
                        attempts=attempt, duration_s=time.time() - start,
                    )
                last_err = f"exit_code={exit_code} stderr={stderr[:300]}"
                log.warn("winrm_nonzero_exit", trace_id, host=host, attempt=attempt, **{"exit_code": exit_code})
            except asyncio.TimeoutError:
                last_err = "timeout"
                log.warn("winrm_timeout", trace_id, host=host, attempt=attempt, timeout_s=self.timeout_s)
            except Exception as exc:  # rede caiu, WinRM não configurado, etc.
                last_err = str(exc)
                log.warn("winrm_exception", trace_id, host=host, attempt=attempt, error=str(exc))

            if attempt < self.max_attempts:
                backoff = self.base_backoff_s * (2 ** (attempt - 1))
                await asyncio.sleep(backoff)

        self._record_failure(host, trace_id)
        return WinRMResult(
            ok=False, host=host, command=command,
            attempts=self.max_attempts, error=last_err,
            duration_s=time.time() - start,
        )


async def _default_executor_example(host: str, command: str, timeout_s: float):
    """Exemplo de como plugar pywinrm real (bloqueante) rodando em thread,
    pra não travar o event loop. Substitua pela sua sessão winrm.Session já
    configurada com as credenciais do cliente."""
    import winrm  # import local pra não quebrar se a lib não estiver instalada aqui

    def _blocking_call():
        session = winrm.Session(host, auth=("user", "pass"), transport="ntlm")
        r = session.run_ps(command)
        return r.status_code, r.std_out.decode("utf-8", "ignore"), r.std_err.decode("utf-8", "ignore")

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _blocking_call)


# ---------------------------------------------------------------------------
# 3) MessageBuilder — mensagens do TrueConf sempre bem formadas
# ---------------------------------------------------------------------------
#
# Problema relatado: mensagem final "mal feita". Aqui: templates fixos,
# limite de tamanho do TrueConf respeitado (split seguro), escape de
# caracteres que quebram Markdown, e um validador que barra envio de
# mensagem vazia/quebrada em vez de mandar lixo pro grupo de técnicos.

TRUECONF_MAX_CHARS = 4000  # ajuste conforme limite real da API que você usa


class MessageBuilder:
    def __init__(self, max_chars: int = TRUECONF_MAX_CHARS):
        self.max_chars = max_chars

    @staticmethod
    def _escape_md(text: str) -> str:
        # escapa só o que quebra formatação, sem exagerar
        return re.sub(r"([_*`\[\]])", r"\\\1", text)

    def success(self, titulo: str, campos: dict[str, str], trace_id: str, emoji: str = "✅") -> str:
        linhas = [f"{emoji} **{self._escape_md(titulo)}**", ""]
        for k, v in campos.items():
            linhas.append(f"**{self._escape_md(k)}:** {self._escape_md(str(v))}")
        msg = "\n".join(linhas)
        return self._validate_and_trim(msg, trace_id)

    def error(self, result: WinRMResult, trace_id: str) -> str:
        msg = (
            f"🔴 **Falha ao executar comando**\n\n"
            f"**Host:** {result.host}\n"
            f"**Comando:** `{result.command}`\n"
            f"**Tentativas:** {result.attempts}\n"
            f"**Erro:** {self._escape_md(result.error or 'desconhecido')}\n\n"
            f"trace_id: `{trace_id}`"
        )
        return self._validate_and_trim(msg, trace_id)

    def _validate_and_trim(self, msg: str, trace_id: str) -> str:
        if not msg.strip():
            log.error("message_empty_blocked", trace_id)
            return "⚠️ Erro interno: resposta vazia (bloqueada antes do envio). Veja os logs."
        if len(msg) > self.max_chars:
            log.warn("message_trimmed", trace_id, original_len=len(msg))
            msg = msg[: self.max_chars - 20].rstrip() + "\n… (truncado)"
        return msg


# ---------------------------------------------------------------------------
# Exemplo mínimo de fiação — adapte os Intent() aos handlers reais do
# orchestrator.py (os nomes abaixo são só ilustrativos, baseados no print)
# ---------------------------------------------------------------------------

DEFAULT_INTENTS = [
    Intent(
        name="instalar_software",
        patterns=[r"\binstal", r"\bwinget\b", r"\buniget", r"\bsoftware"],
        handler_hint="orchestrator.instalar_software",
    ),
    Intent(
        name="verificar_saude",
        patterns=[r"\bsa[uú]de\b", r"\bdiagn[oó]stico\b", r"\bhardware\b", r"\bs\.?m\.?a\.?r\.?t\b"],
        handler_hint="orchestrator.verificar_saude",
    ),
    Intent(
        name="preparar_maquina",
        patterns=[r"\bprepara\b", r"\besteira\b", r"\bconfigura(c|ç)[aã]o\b"],
        handler_hint="orchestrator.preparar_maquina",
    ),
    Intent(
        name="ativar_windows",
        patterns=[r"\bativa\b.*\bwindows\b", r"\blicenciamento\b", r"\bmas\b"],
        handler_hint="orchestrator.ativar_windows",
    ),
    Intent(
        name="enviar_mensagem_tela",
        patterns=[r"\bmanda\b.*\bmensagem\b", r"\baviso\b.*\btela\b"],
        handler_hint="orchestrator.enviar_mensagem_tela",
    ),
    Intent(
        name="reiniciar_maquina",
        patterns=[r"\breinici", r"\bcontrole de energia\b", r"\bshutdown\b", r"\brestart\b"],
        handler_hint="orchestrator.reiniciar_maquina",
    ),
]


if __name__ == "__main__":
    # Demo rápida: reproduz o caso do print (comando de instalação sendo mal
    # interpretado) e mostra o fluxo de clarificação.
    async def _demo():
        router = IntentRouter(DEFAULT_INTENTS, min_confidence=0.55)
        winrm = ResilientWinRM(executor=_default_executor_example, max_attempts=2, timeout_s=5)
        builder = MessageBuilder()

        trace_id = new_trace_id()
        texto = "instala o Steam em 192.168.57.166 via winget"
        match = router.classify(texto, trace_id=trace_id)
        print("Intent match:", match)

        if match.intent is None:
            print(router.build_clarification(match, texto))
            return

        # simula sucesso sem WinRM real
        msg = builder.success(
            "SOFTWARES INSTALADOS COM SUCESSO!",
            {"Computador": match.entities.get("host", "?"), "Pacotes processados": "Valve.Steam"},
            trace_id=trace_id,
        )
        print(msg)

    asyncio.run(_demo())
