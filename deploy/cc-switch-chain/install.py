#!/usr/bin/env python3
"""Install this fork into its own venv; never update the existing Headroom tool.

The release wheel supplies the native extension. Python sources are overlaid
only when their Rust sources match the release used to build that wheel.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def native_digest() -> str:
    digest = hashlib.sha256()
    for folder in (ROOT / "crates/headroom-core", ROOT / "crates/headroom-py"):
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                digest.update(str(path.relative_to(ROOT)).encode())
                digest.update(b"\0" + path.read_bytes())
    return digest.hexdigest()


def main() -> None:
    manifest = json.loads((HERE / "build.json").read_text())
    if native_digest() != manifest["native_sources_sha256"]:
        raise SystemExit(
            "Native sources changed since the validated release. Build a new fork wheel "
            "with maturin and revalidate; do not reuse the old binary."
        )
    uv = shutil.which("uv")
    if not uv:
        raise SystemExit(
            "Install uv from its official distribution first; no system Python changes made."
        )
    venv = ROOT / ".venv"
    py = venv / "bin/python"
    if sys.platform != "win32":
        processes = subprocess.check_output(["ps", "-axo", "args="], text=True)
        if any(str(py) in line and "headroom.cli proxy" in line for line in processes.splitlines()):
            raise SystemExit(
                "This fork runtime is serving traffic. Install into a new checkout instead."
            )
    if not py.exists():
        subprocess.run([uv, "venv", "--python", "3.13", str(venv)], check=True)
    subprocess.run(
        [uv, "pip", "install", "--python", str(py), "-r", str(HERE / "requirements.txt")],
        check=True,
    )
    # Ask from outside the checkout so imports find the wheel, not source.
    target = Path(
        subprocess.check_output(
            [
                str(py),
                "-c",
                "import headroom,pathlib;print(pathlib.Path(headroom.__file__).parent)",
            ],
            cwd=HERE,
            text=True,
        ).strip()
    )
    if venv.resolve() not in target.resolve().parents:
        raise SystemExit("Refusing to overlay a package outside this fork's .venv")
    shutil.copytree(
        ROOT / "headroom",
        target,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.so", "*.pyd"),
    )
    subprocess.run(
        [
            str(py),
            "-c",
            "import headroom._core; from headroom.proxy.server import create_app; print('Fork runtime OK')",
        ],
        cwd=HERE,
        check=True,
    )
    print("Installed fork Python sources + validated release native extension into", venv)
    print("No live configuration, process or LaunchAgent was changed.")


if __name__ == "__main__":
    main()
