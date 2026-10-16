"""CC Switch overwrites, native OAuth routing and HTTP-only WS fallback."""

import json
import os
from unittest.mock import AsyncMock

import pytest
import tomlkit

from headroom.proxy.codex_cc_switch_reconciler import (
    CodexCCSwitchReconciler,
    rewrite_codex_gateway,
)

PROXY = "http://127.0.0.1:8788/v1"
GATEWAY = "http://127.0.0.1:15721/v1"


def test_roundtrip_preserves_provider_models_comments_and_credentials(tmp_path):
    original = f'''# Keep my model selection
model = "test-model"
openai_base_url = "{GATEWAY}" # owned by CC Switch
model_provider = "custom"
[model_providers.custom]
base_url = "{GATEWAY}"
wire_api = "responses"
requires_openai_auth = true
env_key = "UNCHANGED_KEY_NAME"
[model_providers.other]
base_url = "https://other.example/v1"
[profiles.work]
model = "ccs-test-model"
openai_base_url = "{GATEWAY}"
'''
    path = tmp_path / "config.toml"
    path.write_text(original)
    path.chmod(0o600)
    auth = tmp_path / "auth.json"
    auth.write_text(json.dumps({"tokens": {"access_token": "do-not-touch"}}))
    r = CodexCCSwitchReconciler(proxy_url=PROXY, gateway_url=GATEWAY, path=path)
    assert r.tick()
    doc = tomlkit.parse(path.read_text())
    assert doc["openai_base_url"] == PROXY
    assert doc["model_providers"]["custom"]["base_url"] == PROXY
    assert doc["profiles"]["work"]["openai_base_url"] == PROXY
    assert doc["model_providers"]["other"]["base_url"] == "https://other.example/v1"
    assert doc["model_providers"]["custom"]["requires_openai_auth"] is True
    assert doc["model_providers"]["custom"]["env_key"] == "UNCHANGED_KEY_NAME"
    assert doc["model_provider"] == "custom"
    assert "# owned by CC Switch" in path.read_text()
    assert path.stat().st_mode & 0o777 == 0o600
    assert json.loads(auth.read_text())["tokens"]["access_token"] == "do-not-touch"
    assert not r.tick()
    # The external writer atomically replaces config on each mode change.
    replacement = tmp_path / "cc-switch-new.toml"
    replacement.write_text(original.replace("test-model", "new-model"))
    os.replace(replacement, path)
    assert r.tick()
    assert tomlkit.parse(path.read_text())["model"] == "new-model"


def test_invalid_toml_retries_and_unrelated_endpoint_stays_direct(tmp_path):
    path = tmp_path / "config.toml"
    r = CodexCCSwitchReconciler(proxy_url=PROXY, gateway_url=GATEWAY, path=path)
    assert not r.tick()
    path.write_text('model = "unfinished')
    assert not r.tick()
    assert r._last_mtime_ns is None
    path.write_text('openai_base_url = "https://other.example/v1"\n')
    assert not r.tick()
    assert "https://other.example/v1" in path.read_text()


def test_concurrent_external_edit_is_not_overwritten(tmp_path, monkeypatch):
    import headroom.proxy.codex_cc_switch_reconciler as module

    path = tmp_path / "config.toml"
    path.write_text(f'openai_base_url = "{GATEWAY}"\n')
    original_fsync = module.os.fsync

    def external_write(fd):
        path.write_text('model = "concurrent-selection"\n')
        original_fsync(fd)

    monkeypatch.setattr(module.os, "fsync", external_write)
    r = CodexCCSwitchReconciler(proxy_url=PROXY, gateway_url=GATEWAY, path=path)
    assert not r.tick()
    assert path.read_text() == 'model = "concurrent-selection"\n'
    assert not list(tmp_path.glob(".headroom-codex-*"))


def test_rewriter_refuses_identical_gateway_and_proxy():
    with pytest.raises(ValueError):
        rewrite_codex_gateway("", proxy_url=PROXY, gateway_url=PROXY)


@pytest.mark.asyncio
async def test_http_only_gateway_denies_before_accept_or_upstream_connect(monkeypatch):
    from headroom.proxy.handlers.openai import OpenAIHandlerMixin

    monkeypatch.setenv("HEADROOM_CODEX_LOCAL_GATEWAY", GATEWAY)
    monkeypatch.setenv("HEADROOM_CODEX_GATEWAY_WEBSOCKETS", "0")
    socket = AsyncMock()
    # No initialized handler needed: HTTP fallback must precede auth/WS work.
    await OpenAIHandlerMixin.handle_openai_responses_ws(object(), socket)
    socket.accept.assert_not_called()
    response = socket.send_denial_response.call_args.args[0]
    assert response.status_code == 426


def test_native_oauth_http_reaches_gateway_after_compression(monkeypatch):
    import httpx
    from fastapi.testclient import TestClient

    from headroom.proxy.loopback_guard import require_loopback
    from headroom.proxy.server import ProxyConfig, create_app

    monkeypatch.setenv("HEADROOM_CODEX_LOCAL_GATEWAY", GATEWAY)
    app = create_app(
        ProxyConfig(
            optimize=True,
            mode="token",
            disable_kompress=True,
            cache_enabled=False,
            rate_limit_enabled=False,
            cost_tracking_enabled=False,
        )
    )
    app.dependency_overrides[require_loopback] = lambda: None
    captured = {}
    original = json.dumps(
        [
            {"id": i, "status": "ok", "service": "test-service", "message": "request completed"}
            for i in range(400)
        ]
    )
    with TestClient(app) as client:
        proxy = client.app.state.proxy

        async def forward(method, url, headers, body, **kwargs):
            captured.update(url=url, headers=headers, body=body)
            return httpx.Response(
                200,
                json={
                    "id": "resp_local_test",
                    "output": [],
                    "usage": {"input_tokens": 10, "output_tokens": 1},
                },
            )

        proxy._retry_request = forward
        result = client.post(
            "/v1/responses",
            headers={
                "Authorization": "Bearer fake-local-test",
                "chatgpt-account-id": "fake-local-account",
            },
            json={
                "model": "test-model",
                "store": False,
                "stream": False,
                "input": [
                    {"role": "user", "content": "Summarize these service logs."},
                    {"type": "function_call_output", "call_id": "call_1", "output": original},
                ],
            },
        )
    assert result.status_code == 200
    assert captured["url"] == GATEWAY + "/responses"
    assert captured["headers"]["authorization"] == "Bearer fake-local-test"
    assert captured["headers"]["chatgpt-account-id"] == "fake-local-account"
    assert captured["body"]["store"] is False
    assert len(captured["body"]["input"][1]["output"]) < len(original)


@pytest.mark.parametrize("enabled", [False, True])
def test_app_lifecycle_starts_only_opted_in_codex_watcher(tmp_path, monkeypatch, enabled):
    import time

    from fastapi.testclient import TestClient

    from headroom.proxy.server import ProxyConfig, create_app

    monkeypatch.setenv("HEADROOM_CODEX_LOCAL_GATEWAY", GATEWAY)
    monkeypatch.setenv("HEADROOM_CC_SWITCH_RECONCILE_CODEX", "1" if enabled else "0")
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    path = tmp_path / "config.toml"
    path.write_text(f'openai_base_url = "{GATEWAY}"\n')
    app = create_app(
        ProxyConfig(
            port=18789,
            optimize=False,
            cache_enabled=False,
            rate_limit_enabled=False,
        )
    )
    with TestClient(app):
        deadline = time.monotonic() + 2
        while enabled and GATEWAY in path.read_text() and time.monotonic() < deadline:
            time.sleep(0.01)
        expected = "http://127.0.0.1:18789/v1" if enabled else GATEWAY
        assert tomlkit.parse(path.read_text())["openai_base_url"] == expected
