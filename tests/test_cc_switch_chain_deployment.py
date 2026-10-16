"""Offline tests of recovery artifacts; never use the real home or processes."""

import importlib.util
import json
import os
from pathlib import Path


def module(tmp_path, monkeypatch):
    source = Path(__file__).resolve().parents[1] / "deploy/cc-switch-chain/manage.py"
    spec = importlib.util.spec_from_file_location("chain_deployment", source)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    monkeypatch.setattr(mod, "RUNTIME", runtime)
    monkeypatch.setattr(mod, "UI_SETTINGS", runtime / "workspace/config/settings.json")
    monkeypatch.setattr(mod, "PLIST", tmp_path / "old.plist")
    monkeypatch.setattr(mod, "bootout", lambda: None)
    monkeypatch.setattr(mod, "bootin", lambda: None)
    monkeypatch.setattr(mod, "stop_headroom", lambda _: None)
    return mod


def data(tmp_path):
    return {
        "gateway": "http://127.0.0.1:15721/v1",
        "port": 8788,
        "python": "/test/fork/.venv/bin/python",
        "websockets": False,
        "mode": "cache",
        "codex_home": str(tmp_path / "codex"),
        "claude_dir": str(tmp_path / "claude"),
    }


def test_snapshot_and_rollback_restore_missing_files_modes_and_original_content(
    tmp_path, monkeypatch
):
    mod = module(tmp_path, monkeypatch)
    cfg = data(tmp_path)
    codex = Path(cfg["codex_home"]) / "config.toml"
    codex.parent.mkdir()
    codex.write_text('model = "original"\n')
    codex.chmod(0o640)
    mod.PLIST.write_bytes(b"old launchagent")
    backup = mod.snapshot(cfg)
    assert backup.stat().st_mode & 0o777 == 0o700
    assert (backup / "0").stat().st_mode & 0o777 == 0o600
    codex.write_text('model = "changed"\n')
    claude = Path(cfg["claude_dir"]) / "settings.json"
    claude.parent.mkdir()
    claude.write_text("{}")
    mod.PLIST.write_bytes(b"fork launchagent")
    mod.restore(backup, restart=False)
    assert codex.read_text() == 'model = "original"\n'
    assert codex.stat().st_mode & 0o777 == 0o640
    assert not claude.exists()
    assert mod.PLIST.read_bytes() == b"old launchagent"


def test_emergency_bypass_keeps_models_and_credentials(tmp_path, monkeypatch):
    mod = module(tmp_path, monkeypatch)
    cfg = data(tmp_path)
    codex = Path(cfg["codex_home"]) / "config.toml"
    codex.parent.mkdir()
    codex.write_text('model = "selected"\nopenai_base_url = "http://127.0.0.1:8788/v1"\n')
    claude = Path(cfg["claude_dir"]) / "settings.json"
    claude.parent.mkdir()
    claude.write_text(
        json.dumps({"env": {"ANTHROPIC_AUTH_TOKEN": "preserved", "ANTHROPIC_MODEL": "selected"}})
    )
    mod.PLIST.write_text("old service")
    mod.emergency_direct(cfg)
    assert cfg["gateway"] in codex.read_text()
    assert 'model = "selected"' in codex.read_text()
    env = json.loads(claude.read_text())["env"]
    assert env["ANTHROPIC_AUTH_TOKEN"] == "preserved"
    assert env["ANTHROPIC_MODEL"] == "selected"
    assert env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:15721"
    assert not mod.PLIST.exists()
    assert (mod.RUNTIME / "last-backup").exists()


def test_emergency_snapshot_does_not_replace_original_rollback_target(tmp_path, monkeypatch):
    mod = module(tmp_path, monkeypatch)
    cfg = data(tmp_path)
    original = mod.snapshot(cfg)
    mod.emergency_direct(cfg)
    assert (mod.RUNTIME / "last-backup").read_text() == str(original)


def test_candidate_disables_watchers_and_isolates_state(tmp_path, monkeypatch):
    mod = module(tmp_path, monkeypatch)
    env = mod.runtime_env(data(tmp_path), watching=False, port=8789)
    assert env["HEADROOM_PORT"] == "8789"
    assert env["HEADROOM_CC_SWITCH_RECONCILE"] == "0"
    assert env["HEADROOM_CC_SWITCH_RECONCILE_CODEX"] == "0"
    assert env["HEADROOM_CODEX_GATEWAY_WEBSOCKETS"] == "0"
    assert env["HEADROOM_BEACON"] == "off"
    assert str(mod.RUNTIME) in env["HEADROOM_WORKSPACE_DIR"]
    assert env.get("HOME") == os.environ.get("HOME")


def test_dashboard_owns_chain_upstreams_and_mode(tmp_path, monkeypatch):
    mod = module(tmp_path, monkeypatch)
    cfg = data(tmp_path)
    for key in (
        "HEADROOM_MODE",
        "HEADROOM_BACKEND",
        "OPENAI_TARGET_API_URL",
        "ANTHROPIC_TARGET_API_URL",
        "HEADROOM_CODEX_LOCAL_GATEWAY",
    ):
        monkeypatch.setenv(key, "old-export")
    env = mod.runtime_env(cfg)
    assert all(key not in env for key in (
        "HEADROOM_MODE", "HEADROOM_BACKEND", "OPENAI_TARGET_API_URL",
        "ANTHROPIC_TARGET_API_URL", "HEADROOM_CODEX_LOCAL_GATEWAY",
    ))
    assert "--mode" not in mod.command(cfg)
    mod.seed_ui_settings(cfg)
    saved = json.loads(mod.UI_SETTINGS.read_text())
    assert saved == {
        "mode": cfg["mode"],
        "backend": "anthropic",
        "openai_base_url": "http://127.0.0.1:15721",
        "anthropic_base_url": "http://127.0.0.1:15721",
        "codex_local_gateway": "http://127.0.0.1:15721/v1",
    }
    saved["mode"] = "token"
    mod.UI_SETTINGS.write_text(json.dumps(saved))
    backup = mod.snapshot(cfg)
    mod.seed_ui_settings(cfg)
    assert json.loads(mod.UI_SETTINGS.read_text())["mode"] == "token"
    mod.UI_SETTINGS.write_text("{}")
    mod.restore(backup, restart=False)
    assert json.loads(mod.UI_SETTINGS.read_text())["mode"] == "token"
