import pytest

from headroom.providers.codex.endpoints import (
    chatgpt_backend_url,
    codex_backend_url,
    codex_backend_ws_url,
)


def test_chatgpt_backend_url_appends_optional_query() -> None:
    assert chatgpt_backend_url("/backend-api/me") == "https://chatgpt.com/backend-api/me"
    assert (
        chatgpt_backend_url("/backend-api/me", "client_version=1")
        == "https://chatgpt.com/backend-api/me?client_version=1"
    )


def test_codex_backend_url_normalizes_path_prefix() -> None:
    assert codex_backend_url("models") == "https://chatgpt.com/backend-api/codex/models"
    assert (
        codex_backend_url("/responses/compact", "trace=1")
        == "https://chatgpt.com/backend-api/codex/responses/compact?trace=1"
    )


def test_codex_backend_ws_url_normalizes_path_prefix() -> None:
    assert codex_backend_ws_url() == "wss://chatgpt.com/backend-api/codex"
    assert codex_backend_ws_url("responses") == "wss://chatgpt.com/backend-api/codex/responses"
    assert codex_backend_ws_url("/responses") == "wss://chatgpt.com/backend-api/codex/responses"


def test_local_gateway_routes_responses_http_ws_and_compaction(monkeypatch):
    monkeypatch.setenv("HEADROOM_CODEX_LOCAL_GATEWAY", "http://127.0.0.1:15721/v1/")
    assert codex_backend_url("responses", "trace=1") == (
        "http://127.0.0.1:15721/v1/responses?trace=1"
    )
    assert codex_backend_url("/responses/compact") == "http://127.0.0.1:15721/v1/responses/compact"
    assert codex_backend_ws_url("responses") == "ws://127.0.0.1:15721/v1/responses"
    # Account/catalogue/voice endpoints are not Responses gateway endpoints.
    assert codex_backend_url("models") == "https://chatgpt.com/backend-api/codex/models"
    assert codex_backend_ws_url("live") == "wss://chatgpt.com/backend-api/codex/live"
    assert chatgpt_backend_url("/backend-api/me") == "https://chatgpt.com/backend-api/me"


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com:443/v1",
        "http://localhost:15721/v1",
        "http://127.0.0.1:15721/v1?token=x",
        "http://user:pw@127.0.0.1:15721/v1",
        "http://127.0.0.1:15721/wrong",
        "http://127.0.0.1:15721/v1#x",
        "ftp://127.0.0.1:15721/v1",
        "http://127.0.0.1:bad/v1",
    ],
)
def test_local_gateway_rejects_unsafe_or_ambiguous_urls(monkeypatch, url):
    monkeypatch.setenv("HEADROOM_CODEX_LOCAL_GATEWAY", url)
    with pytest.raises(ValueError):
        codex_backend_url("responses")


def test_local_gateway_rejects_self_loop(monkeypatch):
    monkeypatch.setenv("HEADROOM_PORT", "8788")
    monkeypatch.setenv("HEADROOM_CODEX_LOCAL_GATEWAY", "http://127.0.0.1:8788/v1")
    with pytest.raises(ValueError, match="listening port"):
        codex_backend_ws_url("responses")


def test_gateway_supports_ipv6_and_https(monkeypatch):
    monkeypatch.setenv("HEADROOM_CODEX_LOCAL_GATEWAY", "https://[::1]:15721/v1")
    assert codex_backend_ws_url("responses") == "wss://[::1]:15721/v1/responses"
