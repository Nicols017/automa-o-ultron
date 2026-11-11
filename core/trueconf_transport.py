"""Small HTTPS-only REST boundary. No insecure TLS mode or automatic retries."""
import os
from urllib.parse import urlsplit


def https_origin(value):
    parsed = urlsplit(value or "")
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
        raise ValueError("TrueConf exige origem HTTPS valida.")
    # Force parsing of malformed ports before storing any credentials.
    parsed.port
    return "https://" + parsed.netloc


def trueconf_request(method, url, *, sender=None, **kwargs):
    parsed = urlsplit(url)
    https_origin("https://" + parsed.netloc if parsed.scheme == "https" else url)
    if parsed.fragment or parsed.username or parsed.password:
        raise ValueError("Endpoint TrueConf invalido.")
    if sender is None:
        import requests
        sender = requests.request
    kwargs["verify"] = os.environ.get("ULTRON_TRUECONF_CA_BUNDLE") or True
    kwargs["allow_redirects"] = False
    kwargs.setdefault("timeout", 5)
    return sender(method, url, **kwargs)


def incoming_author(message):
    """Only trust the SDK-authenticated author, never a default administrator."""
    author = getattr(message, "author", None) or getattr(message, "from_user", None)
    value = getattr(author, "id", None)
    return str(value).strip().casefold() if value is not None else ""


def is_master_user(identity):
    allowed = {item.strip().casefold() for item in
               os.environ.get("ULTRON_MASTER_TRUECONF_USERS", "").split(",") if item.strip()}
    return bool(identity) and identity.strip().casefold() in allowed


def is_allowed_user(identity):
    users = {value.strip().casefold() for value in
             os.environ.get("ULTRON_TRUECONF_ALLOWED_USERS", "").split(",") if value.strip()}
    return bool(identity) and (identity.strip().casefold() in users or is_master_user(identity))
