"""Fail-closed per-device authentication for the UltronAgent API.

Enrollment is out-of-band. The credential file is NOT accepted from the agent
itself and must never be committed. No plaintext bearer token is sent over HTTP.
Reverse proxies must be configured so ASGI reliably identifies HTTPS.
"""

import hmac
import json
import os
import stat
from pathlib import Path
from typing import Mapping, Optional

from fastapi import HTTPException, Request


def _identifier(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Identificador do agente ausente.")
    return value.strip().lower()


class AgentAuthenticator:
    def __init__(self, credentials_file: Optional[str] = None):
        self.credentials_file = credentials_file or os.environ.get("ULTRON_AGENT_CREDENTIALS_FILE", "")

    @staticmethod
    def require_https(request: Request):
        # Do not trust the client-supplied X-Forwarded-Proto header here.
        # Uvicorn's configured, trusted proxy middleware may set request.url.scheme.
        if request.url.scheme != "https":
            raise HTTPException(status_code=426, detail="API do agente exige HTTPS.")

    def _load_credentials(self) -> Mapping[str, str]:
        if not self.credentials_file:
            raise HTTPException(status_code=503, detail="Credenciais dos agentes não configuradas.")
        file = Path(self.credentials_file)
        try:
            if os.name == "posix":
                mode = stat.S_IMODE(file.stat().st_mode)
                if mode & 0o077:
                    raise ValueError("Permissões inseguras no arquivo de credenciais.")
            data = json.loads(file.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or not data:
                raise ValueError("Mapa de credenciais vazio ou inválido.")
            items = {}
            for key, token in data.items():
                device = _identifier(key)
                if (device in items or not isinstance(token, str)
                        or len(token) < 32 or token.strip() != token):
                    raise ValueError("Credenciais de agente inválidas ou duplicadas.")
                items[device] = token
            return items
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            raise HTTPException(status_code=503, detail="Não foi possível carregar credenciais dos agentes.")

    def authenticate(self, request: Request, expected_agent: Optional[str] = None) -> str:
        self.require_https(request)
        identity = request.headers.get("x-ultron-agent-id", "")
        try:
            identity = _identifier(identity)
        except ValueError:
            raise HTTPException(status_code=401, detail="Identificação de agente obrigatória.")

        auth = request.headers.get("authorization", "")
        if not auth.startswith("Bearer ") or len(auth) <= len("Bearer "):
            raise HTTPException(status_code=401, detail="Token de agente obrigatório.")
        token = auth[len("Bearer "):]
        credentials = self._load_credentials()
        expected_token = credentials.get(identity)
        if not expected_token or not hmac.compare_digest(token, expected_token):
            raise HTTPException(status_code=401, detail="Credenciais de agente inválidas.")
        if expected_agent is not None:
            try:
                expected = _identifier(expected_agent)
            except ValueError:
                raise HTTPException(status_code=403, detail="Alvo do agente inválido.")
            if not hmac.compare_digest(identity, expected):
                raise HTTPException(status_code=403, detail="Agente não autorizado para o alvo.")
        return identity


def require_operator(request: Request):
    """Minimal temporary guard for cleanup; defaults disabled in API."""
    AgentAuthenticator.require_https(request)
    token = os.environ.get("ULTRON_ADMIN_API_TOKEN", "")
    header = request.headers.get("authorization", "")
    if len(token) < 32 or not header.startswith("Bearer "):
        raise HTTPException(status_code=403, detail="Autorização administrativa indisponível.")
    if not hmac.compare_digest(header[len("Bearer "):], token):
        raise HTTPException(status_code=403, detail="Autorização administrativa inválida.")
