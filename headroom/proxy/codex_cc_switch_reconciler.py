"""Keep CC Switch's Codex HTTP/SSE entry points behind Headroom.

Only addresses equal to the operator-configured local gateway are replaced.
Credentials, provider identities, models, comments and other endpoints stay put.
This watcher is separate from the existing Claude reconciler and opt-in.
"""

from __future__ import annotations

import logging
import os
import stat
import tempfile
from collections.abc import Mapping
from pathlib import Path

import tomlkit

from headroom.proxy.cc_switch_reconciler import CCSwitchReconciler

logger = logging.getLogger(__name__)


def rewrite_codex_gateway(text: str, *, proxy_url: str, gateway_url: str) -> str:
    """Loss-minimizing rewrite, including inactive gateway providers/profiles."""
    if proxy_url.rstrip("/") == gateway_url.rstrip("/"):
        raise ValueError("Headroom and CC Switch must use different endpoints")
    doc = tomlkit.parse(text)

    def rewrite(table, key: str) -> None:
        value = table.get(key)
        if isinstance(value, str) and value.rstrip("/") == gateway_url.rstrip("/"):
            table[key] = proxy_url.rstrip("/")

    rewrite(doc, "openai_base_url")
    providers = doc.get("model_providers", {})
    profiles = doc.get("profiles", {})
    if not isinstance(providers, Mapping) or not isinstance(profiles, Mapping):
        raise ValueError("Codex provider/profile configuration must be a TOML table")
    for provider in providers.values():
        if hasattr(provider, "get"):
            rewrite(provider, "base_url")
    for profile in profiles.values():
        if hasattr(profile, "get"):
            rewrite(profile, "openai_base_url")
    return tomlkit.dumps(doc)


class CodexCCSwitchReconciler(CCSwitchReconciler):
    """Reuse the existing watcher's lifecycle with a Codex-specific file writer."""

    def __init__(self, *, proxy_url: str, gateway_url: str, path: Path | None = None) -> None:
        if path is None:
            home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser()
            path = home / "config.toml"
        super().__init__(
            proxy_url=proxy_url,
            default_upstream=gateway_url,
            set_upstream=lambda _: None,
            path=path,
        )
        self.gateway_url = gateway_url.rstrip("/")
        self.current_upstream = self.gateway_url

    def tick(self) -> bool:
        try:
            before = self.path.stat()
            if before.st_mtime_ns == self._last_mtime_ns:
                return False
            original = self.path.read_text(encoding="utf-8")
            rewritten = rewrite_codex_gateway(
                original, proxy_url=self.proxy_url, gateway_url=self.gateway_url
            )
        except (OSError, ValueError, TypeError, tomlkit.exceptions.ParseError):
            # Retry incomplete/invalid concurrent writes, even at the same mtime.
            return False
        if rewritten == original:
            self._last_mtime_ns = before.st_mtime_ns
            return False
        # Stage privately, preserve permissions, and re-read before replacing.
        # CC Switch is an external writer and does not share our process lock.
        fd, name = tempfile.mkstemp(prefix=".headroom-codex-", dir=self.path.parent)
        tmp = Path(name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                os.fchmod(stream.fileno(), stat.S_IMODE(before.st_mode))
                stream.write(rewritten)
                stream.flush()
                os.fsync(stream.fileno())
            current = self.path.stat()
            if (current.st_ino, current.st_mtime_ns, current.st_size) != (
                before.st_ino,
                before.st_mtime_ns,
                before.st_size,
            ) or self.path.read_text(encoding="utf-8") != original:
                return False
            os.replace(tmp, self.path)
            self._last_mtime_ns = self.path.stat().st_mtime_ns
            logger.info("Codex CC Switch entry restored to Headroom")
            return True
        finally:
            tmp.unlink(missing_ok=True)
