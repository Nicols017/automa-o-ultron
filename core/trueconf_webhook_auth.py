"""Authentication guard for optional TrueConf incoming HTTP webhook.

The TrueConf bot's authenticated WebSocket transport remains separate.
This webhook is DISABLED unless a 32+ character secret is configured.
The payload's user_id is NOT, by itself, proof of identity.
"""

import hmac
import os

from fastapi import HTTPException, Request


def require_trueconf_webhook(request: Request):
    # The ASGI scheme must have been established by a trusted TLS endpoint.
    # Do not trust a client-controlled X-Forwarded-Proto header.
    if request.url.scheme != "https":
        raise HTTPException(status_code=426, detail="Webhook TrueConf exige HTTPS.")
    expected = os.getenv("ULTRON_TRUECONF_WEBHOOK_SECRET", "")
    if len(expected) < 32 or expected.strip() != expected:
        raise HTTPException(status_code=503, detail="Webhook HTTP TrueConf não habilitado.")
    candidate = request.headers.get("x-ultron-trueconf-secret", "")
    if not candidate or not hmac.compare_digest(candidate, expected):
        raise HTTPException(status_code=401, detail="Origem do webhook não autenticada.")
    return True
