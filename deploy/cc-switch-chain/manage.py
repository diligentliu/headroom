#!/usr/bin/env python3
"""Prepare, manually switch, or recover the macOS CC Switch chain.

prepare/status never stop services or edit client configuration. switch is an
explicit operator action; the coding agent must not run it for the user.
Recovery uses only the standard library and the old installation.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import plistlib
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / ".runtime/cc-switch-chain"
SETTINGS = RUNTIME / "deployment.json"
UI_SETTINGS = RUNTIME / "workspace/config/settings.json"
LABEL = "com.headroom.default"
SERVICE = f"gui/{os.getuid()}/{LABEL}" if hasattr(os, "getuid") else ""
PLIST = Path.home() / "Library/LaunchAgents" / f"{LABEL}.plist"


def write_private(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(text)
    os.replace(tmp, path)


def load() -> dict:
    if not SETTINGS.exists():
        raise RuntimeError("Run prepare first")
    return json.loads(SETTINGS.read_text())


def health(port: int) -> dict:
    # Local probes must not inherit a shell's HTTPS/ALL_PROXY settings.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(f"http://127.0.0.1:{port}/health", timeout=3) as response:
        return json.load(response)


def probe_ws(gateway: str) -> int:
    """Harmless opening handshake; no OAuth credential or model input is sent."""
    u = urlsplit(gateway)
    if u.scheme != "http":
        raise RuntimeError("Automatic gateway preflight currently requires loopback HTTP")
    with socket.create_connection((u.hostname, u.port), timeout=3) as connection:
        connection.sendall(
            (
                f"GET {u.path.rstrip('/')}/responses HTTP/1.1\r\nHost: {u.netloc}\r\n"
                "Connection: Upgrade\r\nUpgrade: websocket\r\nSec-WebSocket-Version: 13\r\n"
                "Sec-WebSocket-Key: SGVsbG9IZWFkcm9vbTEyMw==\r\n\r\n"
            ).encode()
        )
        line = connection.recv(1024).split(b"\r\n", 1)[0]
    return int(line.split()[1])


def prepare(args) -> None:
    gateway = args.gateway.rstrip("/")
    env = os.environ.copy()
    env["HEADROOM_CODEX_LOCAL_GATEWAY"] = gateway
    env["HEADROOM_PORT"] = str(args.port)
    py = ROOT / ".venv/bin/python"
    subprocess.run(
        [
            str(py),
            "-c",
            "from headroom.providers.codex.endpoints import local_codex_gateway;print(local_codex_gateway())",
        ],
        env=env,
        cwd=Path(__file__).parent,
        check=True,
    )
    code = probe_ws(gateway)
    if code not in (101, 426):
        raise RuntimeError(f"Gateway WebSocket preflight returned {code}; inspect before switching")
    data = {
        "gateway": gateway,
        "port": args.port,
        "websockets": code == 101,
        "python": str(py),
        "codex_home": str(Path(args.codex_home).expanduser().resolve()),
        "claude_dir": str(Path(args.claude_dir).expanduser().resolve()),
        "mode": args.mode,
    }
    write_private(SETTINGS, json.dumps(data, indent=2) + "\n")
    print(json.dumps(data, indent=2))
    print("Prepared only. No live settings, service or LaunchAgent changed.")


def runtime_env(data: dict, *, watching: bool = True, port: int | None = None) -> dict:
    env = os.environ.copy()
    # These knobs are owned by the dashboard settings file, even when the
    # operator's shell exports old values during a later deployment.
    for key in (
        "HEADROOM_MODE",
        "HEADROOM_BACKEND",
        "OPENAI_TARGET_API_URL",
        "ANTHROPIC_TARGET_API_URL",
        "HEADROOM_CODEX_LOCAL_GATEWAY",
    ):
        env.pop(key, None)
    # Use independent Headroom state; keep the old ledger and settings intact.
    env.update(
        {
            "HEADROOM_WORKSPACE_DIR": str(RUNTIME / "workspace"),
            "HEADROOM_SETTINGS_PATH": str(UI_SETTINGS),
            "HEADROOM_UI_MANAGED_ENV_KEYS": (
                "HEADROOM_MODE,HEADROOM_BACKEND,OPENAI_TARGET_API_URL,"
                "ANTHROPIC_TARGET_API_URL,HEADROOM_CODEX_LOCAL_GATEWAY"
            ),
            "HEADROOM_PORT": str(port or data["port"]),
            "HEADROOM_HOST": "127.0.0.1",
            "HEADROOM_BEACON": "off",
            "DO_NOT_TRACK": "1",
            "HEADROOM_TELEMETRY": "on",
            "HEADROOM_KOMPRESS_WARMUP": "0",
            # HTTP/SSE remains compatible when a new UI-selected gateway has
            # no WebSocket support; it also avoids stale transport detection.
            "HEADROOM_CODEX_GATEWAY_WEBSOCKETS": "0",
            "HEADROOM_CC_SWITCH_RECONCILE": "1" if watching else "0",
            "HEADROOM_CC_SWITCH_RECONCILE_CODEX": "1" if watching else "0",
            "CODEX_HOME": data["codex_home"],
            "CLAUDE_CONFIG_DIR": data["claude_dir"],
        }
    )
    return env


def seed_ui_settings(data: dict) -> None:
    """Preserve existing UI choices and seed the five former env-owned knobs."""
    stored = json.loads(UI_SETTINGS.read_text()) if UI_SETTINGS.exists() else {}
    if not isinstance(stored, dict):
        raise RuntimeError(f"Invalid dashboard settings: {UI_SETTINGS}")
    gateway = data["gateway"]
    defaults = {
        "mode": data["mode"],
        "backend": "anthropic",
        "openai_base_url": gateway.removesuffix("/v1"),
        "anthropic_base_url": gateway.removesuffix("/v1"),
        "codex_local_gateway": gateway,
    }
    for key, value in defaults.items():
        stored.setdefault(key, value)
    write_private(UI_SETTINGS, json.dumps(stored, indent=2) + "\n")


def command(data: dict, *, port: int | None = None) -> list[str]:
    return [
        data["python"],
        "-m",
        "headroom.cli",
        "proxy",
        "--host",
        "127.0.0.1",
        "--port",
        str(port or data["port"]),
    ]


def stop_headroom(port: int) -> None:
    try:
        h = health(port)
    except Exception:
        # Health may be broken. Find only a Headroom proxy bound to this port.
        result = subprocess.run(
            ["lsof", "-tiTCP:" + str(port), "-sTCP:LISTEN"], capture_output=True, text=True
        )
        if not result.stdout.strip():
            return
        pid = int(result.stdout.strip().splitlines()[0])
    else:
        if h.get("service") != "headroom-proxy":
            raise RuntimeError("Refusing to stop a non-Headroom service")
        pid = int(h["config"]["pid"])
    cmd = subprocess.check_output(["ps", "-p", str(pid), "-o", "args="], text=True)
    if "headroom" not in cmd or "proxy" not in cmd:
        raise RuntimeError("Refusing to stop an unrecognized process")
    parent = int(subprocess.check_output(["ps", "-p", str(pid), "-o", "ppid="], text=True))
    parent_cmd = subprocess.run(
        ["ps", "-p", str(parent), "-o", "args="], capture_output=True, text=True
    ).stdout
    if "headroom" in parent_cmd and "install agent run" in parent_cmd:
        os.kill(parent, signal.SIGTERM)
    else:
        os.kill(pid, signal.SIGTERM)
    for _ in range(100):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.2)
    raise RuntimeError("Headroom did not stop within 20 seconds; inspect it manually")


def bootout() -> None:
    subprocess.run(["launchctl", "bootout", SERVICE], capture_output=True)


def bootin() -> None:
    subprocess.run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(PLIST)], check=True)


def snapshot(data: dict, *, remember: bool = True) -> Path:
    directory = RUNTIME / "backups" / dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    directory.mkdir(parents=True, mode=0o700)
    files = [
        Path(data["codex_home"]) / "config.toml",
        Path(data["claude_dir"]) / "settings.json",
        PLIST,
        UI_SETTINGS,
    ]
    records = []
    for i, path in enumerate(files):
        record = {"path": str(path), "exists": path.exists(), "backup": str(i)}
        if path.exists():
            shutil.copy2(path, directory / str(i))
            (directory / str(i)).chmod(0o600)
            record["mode"] = path.stat().st_mode & 0o777
        records.append(record)
    write_private(
        directory / "manifest.json", json.dumps({"files": records, "deployment": data}, indent=2)
    )
    if remember or not (RUNTIME / "last-backup").exists():
        write_private(RUNTIME / "last-backup", str(directory))
    return directory


def restore(directory: Path, *, restart: bool = True) -> None:
    manifest = json.loads((directory / "manifest.json").read_text())
    data = manifest["deployment"]
    bootout()
    stop_headroom(data["port"])
    for item in manifest["files"]:
        path = Path(item["path"])
        if item["exists"]:
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(directory / item["backup"], path)
            path.chmod(item["mode"])
        else:
            path.unlink(missing_ok=True)
    if restart and PLIST.exists():
        bootin()
    print("Restored pre-switch configuration from", directory)


def switch(data: dict) -> None:
    if sys.platform != "darwin":
        raise RuntimeError(
            "Automatic service switch supports macOS only; use foreground on other OSes"
        )
    # Require a tested fork before making the first live change.
    subprocess.run(
        [
            data["python"],
            "-c",
            "import headroom._core;from headroom.proxy.server import create_app",
        ],
        cwd=RUNTIME,
        check=True,
    )
    handshake = probe_ws(data["gateway"])
    if handshake not in (101, 426) or (handshake == 101) != data["websockets"]:
        raise RuntimeError("Gateway transport changed; run prepare again before switching")
    directory = snapshot(data)
    print("Recovery snapshot:", directory, flush=True)
    try:
        seed_ui_settings(data)
        bootout()
        stop_headroom(data["port"])
        env = runtime_env(data)
        spec = {
            "Label": LABEL,
            "ProgramArguments": command(data),
            "WorkingDirectory": str(RUNTIME),
            "EnvironmentVariables": {
                k: v
                for k, v in env.items()
                if k.startswith("HEADROOM_")
                or k
                in {
                    "OPENAI_TARGET_API_URL",
                    "ANTHROPIC_TARGET_API_URL",
                    "CODEX_HOME",
                    "CLAUDE_CONFIG_DIR",
                    "PATH",
                    "DO_NOT_TRACK",
                }
            },
            "RunAtLoad": True,
            "KeepAlive": True,
            "StandardOutPath": str(RUNTIME / "proxy.log"),
            "StandardErrorPath": str(RUNTIME / "proxy.log"),
        }
        PLIST.parent.mkdir(parents=True, exist_ok=True)
        PLIST.write_bytes(plistlib.dumps(spec))
        bootin()
        for _ in range(60):
            try:
                h = health(data["port"])
                pid = h.get("config", {}).get("pid")
                running = (
                    subprocess.check_output(["ps", "-p", str(pid), "-o", "args="], text=True)
                    if pid
                    else ""
                )
                if h.get("ready") and data["python"] in running:
                    print("Fork healthy. Reopen Codex CLI and desktop coding sessions.")
                    return
            except Exception:
                pass
            time.sleep(1)
        raise RuntimeError("Fork did not become ready; see " + str(RUNTIME / "proxy.log"))
    except Exception:
        print("Switch failed; restoring the snapshot.", flush=True)
        restore(directory)
        raise


def emergency_direct(data: dict) -> None:
    """Independent escape hatch: both clients go straight to CC Switch."""
    snapshot(data, remember=False)
    bootout()
    stop_headroom(data["port"])
    if PLIST.exists():
        # Retain the plist for later inspection but prevent restart at login.
        shutil.move(str(PLIST), str(RUNTIME / "disabled-launchagent.plist"))
    codex = Path(data["codex_home"]) / "config.toml"
    proxy = f"http://127.0.0.1:{data['port']}/v1"
    if codex.exists():
        # Exact endpoint replacement preserves TOML layout and selected model.
        write_private(codex, codex.read_text().replace(proxy, data["gateway"]))
    claude = Path(data["claude_dir"]) / "settings.json"
    if claude.exists():
        doc = json.loads(claude.read_text())
        doc.setdefault("env", {})["ANTHROPIC_BASE_URL"] = data["gateway"].removesuffix("/v1")
        write_private(claude, json.dumps(doc, indent=2) + "\n")
    print("Headroom stopped. Reopen clients: requests now go directly to CC Switch.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--gateway", default="http://127.0.0.1:15721/v1")
    prep.add_argument("--port", type=int, default=8788)
    prep.add_argument("--mode", choices=["cache", "token"], default="cache")
    prep.add_argument(
        "--codex-home", default=os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))
    )
    prep.add_argument(
        "--claude-dir", default=os.environ.get("CLAUDE_CONFIG_DIR", str(Path.home() / ".claude"))
    )
    for name in ["status", "switch", "rollback", "emergency-direct", "foreground"]:
        sub.add_parser(name)
    args = parser.parse_args()
    if args.action == "prepare":
        prepare(args)
        return
    data = load()
    if args.action == "status":
        print(json.dumps(data, indent=2))
        try:
            h = health(data["port"])
            print("Running:", h.get("version"), "PID", h.get("config", {}).get("pid"))
        except Exception as exc:
            print("Health unavailable:", type(exc).__name__)
    elif args.action == "switch":
        switch(data)
    elif args.action == "rollback":
        restore(Path((RUNTIME / "last-backup").read_text().strip()))
    elif args.action == "emergency-direct":
        emergency_direct(data)
    elif args.action == "foreground":
        # Isolated candidate: no config watcher or active-session credential reads.
        seed_ui_settings(data)
        env = runtime_env(data, watching=False, port=data["port"] + 1)
        env["CODEX_HOME"] = str(RUNTIME / "candidate-codex")
        env["CLAUDE_CONFIG_DIR"] = str(RUNTIME / "candidate-claude")
        env["HEADROOM_DISABLE_KOMPRESS"] = "1"
        subprocess.run(command(data, port=data["port"] + 1), cwd=RUNTIME, env=env, check=True)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit(str(exc)) from exc
