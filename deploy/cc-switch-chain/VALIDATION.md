# Validation — 2026-10-16

Base: upstream main `683c9a6120c309e84e4848378dbe3891d064f82e` (after release 0.41.0).
Environment: macOS Apple Silicon, CPython 3.13.4, isolated fork `.venv`.

## Completed

- 103 regression tests passed in the combined run. Two additional lifecycle tests
  were then added and passed in an 8-test targeted run (105 distinct passing cases).
- Coverage: native subscription endpoint formulas and default behavior; HTTP and WS
  gateway endpoints; unsafe/self-referential endpoint rejection; existing OAuth header
  handling; native Responses compression with a mocked upstream; Anthropic upstream
  routing; Codex configuration preservation and external edits; watcher opt-in lifecycle;
  snapshot, rollback and emergency bypass, including preserving the original rollback target.
- Ruff check/format and git diff whitespace checks passed for changed Python files.
- The isolated installer loaded the fork Python sources and released native core.
  No Rust source differences exist in headroom-core/headroom-py versus release 0.41.0.
- Candidate service started on 8789 with independent state and both config watchers off.
  Health reported 0.41.0 ready, Rust core loaded, and CC Switch as both configured upstreams.
- Real local WebSocket opening handshake: CC Switch returned 426; candidate returned 426
  before accepting, preserving the client's HTTP/SSE fallback contract.
- Candidate pure-compression endpoint, no external model request: 10,735 → 3,707 tokens
  on synthetic repetitive JSON tool output. This is a functional smoke test, not a
  production workload savings prediction.
- Candidate stopped after validation. Existing 8788 Headroom 0.37.0 remained healthy
  with its original PID throughout; existing runtime, startup scripts and client settings
  were not switched by the agent.

One upstream Starlette/httpx TestClient deprecation warning was emitted; tests passed.

## Deliberately pending operator cutover

- No real ChatGPT or company model request was generated through the new service.
- macOS LaunchAgent stop/bootstrap and live-file restore were not executed on this host;
  file recovery behavior was tested against temporary files with mocked service management.
- The real Codex/desktop client's reaction to 426 through Headroom must be confirmed after
  the user reopens the clients. The wire signal matches the current working CC Switch route.
- Full WebSocket-generation forwarding requires a WS-capable gateway; this host's CC Switch
  is HTTP-only. Live voice and ordinary ChatGPT Chat are not included.
- Private-machine and non-macOS deployment remain a separate environment verification.

Do not state that production compression or a zero-downtime switch has been verified.
