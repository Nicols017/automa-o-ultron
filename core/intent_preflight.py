"""Preflight interpretation for TrueConf requests.

Distinguishes an informational question, a negated command, a multi-step
destructive request, and as-yet-unavailable FOG image operations.

IMPORTANT: This module never runs an action. It is evaluated BEFORE regex/
legacy master handlers so questions cannot trigger WinRM or other actions.
Commands explicitly prefixed with / are not modified by this classifier.
"""

from dataclasses import dataclass
import re
import unicodedata
from typing import Optional


@dataclass(frozen=True)
class PreflightDecision:
    kind: str
    reply: Optional[str] = None


def _normalize(value: str) -> str:
    lower = unicodedata.normalize("NFKD", value.lower())
    return "".join(ch for ch in lower if not unicodedata.combining(ch)).strip()


def _has(text: str, expression: str) -> bool:
    return re.search(expression, text) is not None


def preflight_request(message: str) -> PreflightDecision:
    """Safety-first language interpretation; safe outcome for ambiguous actions.

    Kinds:
    - passthrough: legacy slash command / execution route may process.
    - explanatory: language-model conversation only, never command handlers.
    - blocked: return message without dispatching any remote action.
    """
    raw = (message or "").strip()
    if not raw or raw.startswith("/"):
        return PreflightDecision("passthrough")

    text = _normalize(raw)
    # Do not match words embedded in filenames, package names or hostnames.
    backup = _has(text, r"\b(?:backup|backups|copia de seguranca|salvar dados|imagem do disco)\b")
    imaging = _has(text, r"\b(?:fog|clonezilla|macrium|imagem|clonagem|clonar|restaur[a-z]*)\b")
    formatting = _has(text, r"\b(?:format[a-z]*|reformat[a-z]*|zerar|apagar tudo|reinstal[a-z]*|wipe)\b")
    restart = _has(text, r"\b(?:reinici[a-z]*|reboot|restart|deslig[a-z]*|shutdown)\b")
    negated = _has(text, r"\b(?:nao|nunca|jamais)\s+(?:(?:quero|pode|deve|faca|faz|vai|precisa)\s+)?(?:format[a-z]*|reinici[a-z]*|deslig[a-z]*|faca backup|realiz[a-z]* backup|apaga[a-z]*|restaur[a-z]*|execute|executar)\b")

    # Questions are informational even if they contain imperative keywords.
    # Avoid interpreting "como verificar um backup" as running a diagnosis.
    query = (
        "?" in raw or
        _has(text, r"^(?:como\b|o que\b|qual\b|quais\b|porque\b|por que\b|quando\b|onde\b|"
                   r"quanto\b|pra que\b|para que\b|poderia explicar\b|me explica\b|"
                   r"me ensina\b|tem como\b|e possivel\b|gostaria de saber\b)")
    )
    if query and not _has(text, r"^(?:pode|poderia|consegue|conseguiria|da pra)\s+(?:voce\s+)?"
                                r"(?:fazer|realizar|executar|iniciar|verificar|diagnosticar|instalar|"
                                r"formatar|reiniciar|desligar|restaurar|enviar|salvar|copiar)\b"):
        return PreflightDecision("explanatory")

    if negated and (backup or imaging or formatting or restart):
        return PreflightDecision(
            "blocked",
            "Entendi a restrição. Não executei nenhuma operação. "
            "Se quiser consultar o equipamento ou planejar uma tarefa, posso ajudar sem alterá-lo.",
        )

    # A question about validation must never be misread as a fresh backup.
    if backup and _has(text, r"\b(?:verifi(?:c|qu)[a-z]*|confir[a-z]*|valid[a-z]*|chec[a-z]*|integridade|status)\b"):
        return PreflightDecision(
            "blocked",
            "Você pediu para consultar ou verificar um backup, não para criar outro. "
            "Se a tarefa foi iniciada pelo Ultron, consulte /status_backup <id>. "
            "Nenhuma cópia foi iniciada.",
        )

    # A single message must not chain a backup and destruction. Capturing a
    # user backup and formatting are TWO independently authorized operations.
    if backup and formatting:
        return PreflightDecision(
            "blocked",
            "Você mencionou backup e formatação. São operações separadas: "
            "primeiro precisamos concluir e validar o backup; a formatação "
            "continua bloqueada e exige autorização própria. Nenhuma ação foi iniciada.",
        )

    # FOG capture/deploy is NOT integrated or deployed in production yet.
    # This also blocks legacy 'backup' regex dispatch from pretending a
    # selected-folder Robocopy operation is a FOG disk image.
    wants_image_action = _has(
        text,
        r"\b(?:faz[a-z]*|cria[a-z]*|gera[a-z]*|tira|captura[a-z]*|inicia[a-z]*|"
        r"realiza[a-z]*|executa[a-z]*|restaur[a-z]*|recupera[a-z]*|"
        r"quero|preciso|solicito|salva[a-z]*)\b",
    )
    if imaging and (wants_image_action or (backup and _has(text, r"\bimagem\b"))) and (backup or formatting or _has(text, r"\b(?:fog|clonezilla|imagem|restaur[a-z]*)\b")):
        return PreflightDecision(
            "blocked",
            "O backup/restauração de imagem pelo FOG ainda não está integrado ao Ultron. "
            "Não iniciei nenhuma captura, restauração ou formatação. "
            "O backup de pastas de usuário é uma operação diferente.",
        )

    return PreflightDecision("passthrough")
