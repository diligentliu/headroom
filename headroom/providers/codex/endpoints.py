"""ChatGPT Codex backend endpoint formulas."""

from __future__ import annotations

import ipaddress
import os
from urllib.parse import urlsplit

CHATGPT_BACKEND_API_URL = "https://chatgpt.com"
CHATGPT_BACKEND_WS_URL = "wss://chatgpt.com"
CODEX_BACKEND_PREFIX = "/backend-api/codex"


def local_codex_gateway() -> str | None:
    """Explicit operator-only Responses gateway; never read from client headers.

    Restrict credential-bearing subscription traffic to a loopback IP literal.
    Other ChatGPT endpoints (account, catalogue and Live) keep their native route.
    """
    value = os.environ.get("HEADROOM_CODEX_LOCAL_GATEWAY", "").strip().rstrip("/")
    if not value:
        return None
    parsed = urlsplit(value)
    try:
        loopback = ipaddress.ip_address(parsed.hostname or "").is_loopback
        port = parsed.port
    except ValueError:
        loopback, port = False, None
    if (
        not loopback
        or parsed.scheme not in {"http", "https"}
        or not port
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path != "/v1"
    ):
        raise ValueError("HEADROOM_CODEX_LOCAL_GATEWAY requires http(s)://loopback-ip:port/v1")
    if str(port) == os.environ.get("HEADROOM_PORT", "").strip():
        raise ValueError("Codex gateway must not point back to Headroom's listening port")
    return value


def local_codex_gateway_http_only() -> bool:
    """Let an HTTP-only gateway preserve Codex's native HTTP fallback handshake."""
    return local_codex_gateway() is not None and os.environ.get(
        "HEADROOM_CODEX_GATEWAY_WEBSOCKETS", "1"
    ).strip().lower() in {"0", "false", "off", "no"}


def _gateway_response_url(path: str) -> str | None:
    suffix = "/" + path.lstrip("/")
    if suffix == "/responses" or suffix.startswith("/responses/"):
        gateway = local_codex_gateway()
        if gateway:
            return gateway + suffix
    return None


def chatgpt_backend_url(path: str, query: str = "") -> str:
    """Return a ChatGPT HTTPS backend URL for an absolute backend path."""
    url = f"{CHATGPT_BACKEND_API_URL}{path}"
    if query:
        return f"{url}?{query}"
    return url


def codex_backend_url(path: str, query: str = "") -> str:
    """Return a ChatGPT HTTPS backend URL under `/backend-api/codex`."""
    path_suffix = path if path.startswith("/") else f"/{path}"
    gateway_url = _gateway_response_url(path_suffix)
    if gateway_url:
        return gateway_url + (f"?{query}" if query else "")
    return chatgpt_backend_url(f"{CODEX_BACKEND_PREFIX}{path_suffix}", query)


def codex_backend_ws_url(path: str = "") -> str:
    """Return a ChatGPT WebSocket backend URL under `/backend-api/codex`."""
    path_suffix = path if not path or path.startswith("/") else f"/{path}"
    gateway_url = _gateway_response_url(path_suffix)
    if gateway_url:
        return gateway_url.replace("https://", "wss://", 1).replace("http://", "ws://", 1)
    return f"{CHATGPT_BACKEND_WS_URL}{CODEX_BACKEND_PREFIX}{path_suffix}"
