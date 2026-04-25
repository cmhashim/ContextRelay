# ContextRelay Edge — Agent State File

> Single source of truth for current project state. Update after every significant action.

## Current State

- **Phase:** Phase 6 — Ecosystem Integrations (complete)
- **Status:** Live with DO + pub/sub + E2EE + metadata/peek + PyPI prep + LangChain/CrewAI/AutoGen integrations
- **Last Updated:** 2026-04-25
- **Live Worker:** https://contextrelay.your-account.workers.dev
- **Worker Version:** `18a14af7-7f96-4e68-a99d-231d7198f371`
- **GitHub (private):** cmhashim/contextrelay

## Shipped

### Phase 1 — MVP Smoke Test ✓
- Cloudflare Worker with KV: `POST /push` / `GET /pull/:id`
- Python SDK: `ContextRelay(base_url).push(str) -> url`, `.pull(url) -> str`
- 125 KB pull latency: **113 ms** (target was <150 ms)

### Phase 1.5 — Cross-Provider Handoff ✓
- `examples/agent_a_claude.py`: Claude generates 18 KB JSON → `hub.push()` → URL pointer
- `examples/agent_b_mistral.py`: Mistral receives URL → `hub.pull()` → summarises
- Validated: full context flows through ContextRelay at ~0 tokens of prompt cost
- Dual-mode: `--mode api` (ANTHROPIC_API_KEY) or `--mode claude-code` (subscription via CLI)

### Phase 2 (MCP) — Native Client Tool ✓
- `python/contextrelay/mcp.py`: FastMCP server exposing `push_context` and `pull_context`
- Registered in `/home/hash/My-AI-Twin/.mcp.json` as `contextrelay`
- Live-tested inside Claude Code (round-trip push → pull)

### Phase 3 (OSS launch prep) ✓
- Repo restructured into `api/` + `python/` + `examples/`
- `pyproject.toml` with hatchling, `contextrelay-mcp` CLI entry point
- Marketing `README.md` (hero, problem/solution, benchmarks, self-host guide)
- MIT `LICENSE`
- Pushed to private GitHub

### Phase 3 (WebSocket Signaling) ✓
- `ChannelBroker` Durable Object using Hibernatable WebSockets API
  (`state.acceptWebSocket` — zero idle cost)
- New route: `GET /ws/:channel` — upgrades and routes to the per-channel DO
- `POST /push` now accepts JSON `{data, channel?}`; raw-text body still works (back-compat)
- Python SDK `push(data, channel=None)` + new `subscribe(channel, callback)` with
  ping-keepalive (30s/10s) and exponential-backoff reconnect
- MCP `push_context` tool exposes the `channel` parameter
- **Fan-out latency measured:** 21 ms from producer ACK to subscriber callback

### Phase 4 (E2EE Vault) ✓
- Worker unchanged — all crypto is client-side
- SDK `push(data, channel=None, encrypted=False)`:
  - Generates a fresh `Fernet.generate_key()` per upload
  - Encrypts with AES-128-CBC + HMAC-SHA256 before POST
  - Appends key as `#key=...` fragment on the returned URL
- SDK `pull(url)` auto-detects `#key=`, strips the fragment before GET, decrypts locally
- `cryptography.fernet.InvalidToken` → `ValueError("Failed to decrypt: Invalid or missing key")`
- MCP `push_context` exposes `encrypted: bool = False`
- **Verified live:** server-side payload starts with `gAAAAA...` (Fernet header) — no plaintext reaches Cloudflare; encrypted round-trip 258ms push / 88ms pull+decrypt

### Phase 5 (Metadata & Lazy Loading) ✓
- KV storage format is now `{data: <payload_str>, metadata: <object>}`
- Worker route `GET /peek/:id` — server-side parse; returns only metadata
- Worker `POST /push` accepts optional `metadata` in the JSON body
- SDK `push(data, channel=None, encrypted=False, metadata=None)`
- SDK `pull(url)` unwraps the `{data, metadata}` envelope; falls back to raw for legacy entries
- SDK `peek(url) -> dict` hits `/peek/:id`, returns the metadata object
- MCP `push_context` adds `summary: str | None` (flattened into `metadata={"summary": summary}`)
- MCP new tool `peek_context(url)` for agent-side triage
- **Invariant verified live:** for `encrypted=True` + `metadata`, the server's stored `data` field is Fernet ciphertext while `metadata` remains plaintext JSON — peek works without a key
- **Bandwidth measurement (180 KB encrypted payload):** peek 89ms vs pull+decrypt 137ms

---

### Phase 6 — Ecosystem Integrations ✓
- PyPI package `context-relay` (not `contextrelay-mcp`): `pyproject.toml` updated with name="contextrelay", MIT license, Python>=3.9, homepage URL
- `python/contextrelay/__all__` exports all public API (ContextRelay, AgentBridge, TmuxDispatcher)
- `python/contextrelay/py.typed` marker file for PEP 561 type checking
- `[tool.hatch.build.targets.wheel]` configured: only `context-relay` package included (excludes tests/examples)
- `python/PUBLISHING.md` with exact steps: `pip install build twine`, `python -m build`, `twine upload dist/*`, notes about TWINE_USERNAME=TWINE_PASSWORD env vars
- **LangChain integration:** `python/contextrelay/integrations/langchain.py`
  - `ContextRelayRetriever(BaseRetriever)`: `__init__(hub_url, api_key, channel, encrypted)`, `_get_relevant_documents()` pushes query, returns `[Document(page_content=url, metadata={"contextrelay_url": url})]`
  - `ContextRelayCallbackHandler(BaseCallbackHandler)`: `on_llm_end()` pushes output to channel
  - TYPE_CHECKING guards for langchain imports (optional dependency)
  - pyproject.toml: `langchain = {version=">=0.1", optional=true}` in `[project.optional-dependencies]`
  - extras group "langchain"
- **CrewAI integration:** `python/contextrelay/integrations/crewai.py`
  - `ContextRelayPushTool(BaseTool)`: name="contextrelay_push", description, args_schema with `data: str`, `metadata: dict`
  - `ContextRelayPullTool(BaseTool)`: name="contextrelay_pull", description, args_schema with `url: str`
  - TYPE_CHECKING guards (optional dependency)
  - pyproject.toml: `crewai = {version=">=0.1", optional=true}` in extras group "crewai"
- **AutoGen integration:** `python/contextrelay/integrations/autogen.py`
  - `contextrelay_push(data: str, metadata: dict = None) -> str`: docstring as AutoGen tool description
  - `contextrelay_pull(url: str) -> str`: docstring as AutoGen tool description
  - `get_autogen_tools(hub_url, encrypted=False) -> list`: returns `[FunctionTool(contextrelay_push), FunctionTool(contextrelay_pull)]`
  - TYPE_CHECKING guards (optional dependency)
  - pyproject.toml: `autogen-agentchat = {version=">=0.2", optional=true}` in extras group "autogen"
- **Integrations module:** `python/contextrelay/integrations/__init__.py`
  - Lazy imports with helpful error messages pointing to `pip install context-relay[langchain/crewai/autogen]`
  - `__all__` exports all integration classes/functions
- Updated `python/contextrelay/__init__.py` with integrations docstring and updated `__all__`

---

## Next Up — Phase 7: Safety Scanners

---

## Pending (Future Phases)

### Phase 7 — Safety Scanners
- Optional Llama-Guard 3 scanner for public deployments (prompt-injection, malware)
- Only useful for non-E2EE mode — encrypted payloads are opaque to any server-side scanner by design

---

## Architectural Decisions

**2026-04-22 — Stripped Hono; raw Fetch API**
Two-route MVP doesn't justify Hono's middleware weight. Will reconsider if auth/CORS/rate-limit middleware lands.

**2026-04-22 — No versioned URL prefix in Phase 1**
Routes are `/push` and `/pull/:id` (unversioned). Rationale: MVP simplicity. Auth/E2EE in Phase 5 will force a `/v1/` cutover.

**2026-04-22 — SDK is two methods only**
`push(str)` / `pull(url)`. No `.store()` / `.retrieve()` / `.delete()` / `.health()`. Surface area stays minimal until a real user asks.

**2026-04-22 — Claude Code subscription mode in examples**
`examples/agent_a_claude.py` defaults to `--mode claude-code` (shells out to `claude -p`) so the demo works without an API key. Subprocess strips `ANTHROPIC_API_KEY` from env so the CLI uses the user's subscription auth, not API credits.

**2026-04-22 — MCP uses `FastMCP.run(transport="stdio")`**
Wrapped in `def main()` so `pyproject.toml`'s `[project.scripts]` can bind `contextrelay-mcp` to it.

**2026-04-22 — Hibernatable WebSockets over classic `ws.accept()`**
`ChannelBroker` uses `state.acceptWebSocket()` + `webSocketMessage` handlers so the DO instance evicts from memory when idle. A channel with 1 subscriber waiting 1 hour for a single event pays near-zero CPU/memory during that hour.

**2026-04-22 — Fan-out via `ctx.waitUntil`**
`POST /push` returns the pointer URL immediately; the DO broadcast runs async in `waitUntil`. Producer latency is not coupled to subscriber count or DO wake-up time.

**2026-04-22 — `subscribe()` is blocking with reconnect inside the call**
Users who need non-blocking run it in a `threading.Thread(daemon=True)`. Avoids baking a threading model into the SDK — callers stay in control.

**2026-04-22 — Fernet, not raw AES-GCM**
Fernet (AES-128-CBC + HMAC-SHA256) bundles IV, ciphertext, MAC, timestamp, and version byte into a single URL-safe base64 string. No IV management, no MAC-then-encrypt mistakes, no custom framing. AES-128 is still firmly sufficient; the SDK-local keygen means per-upload rotation is free.

**2026-04-22 — E2EE key in URL fragment, not query param or header**
RFC 3986: fragments are never transmitted by HTTP clients. `requests.get("https://h/p#key=X")` transmits `GET /p` only. That property is what makes "edge never sees the key" actually true — no server trust assumption. Query params and headers do not have this guarantee.

**2026-04-22 — `encrypted=True` + `channel` combo: key NOT broadcast**
The DO broadcast carries only the server-side URL (no fragment, because the Worker never sees it). Subscribers get a keyless pointer and must receive the key out-of-band. This preserves the E2EE invariant at the cost of requiring manual key delivery for pub/sub E2EE flows. If this becomes a real UX problem, the right answer is a second WebSocket message carrying the key *from the producer* through the DO — never from the server.

**2026-04-22 — KV storage became `{data, metadata}` on every write**
Pre-Phase-5 values were raw strings. Post-Phase-5 every value is a JSON envelope. The split-brain is contained by: (a) Worker's `/peek` try/catches `JSON.parse` and returns `{}` on failure, (b) SDK's `pull()` try/catches `json.loads` and falls back to returning the raw body. Legacy entries expire in ≤24h; after that the two paths are dead code — but keep them anyway, they're cheap insurance for future format migrations.

**2026-04-22 — Pull unwraps client-side, peek unwraps server-side**
Asymmetric on purpose. Pull returning the raw KV value keeps the Worker dumb and minimizes server-side allocation on the hot path. Peek *must* unwrap server-side — if it returned the full envelope, there'd be no bandwidth advantage over pull and the feature would be pointless.

**2026-04-22 — Metadata is never encrypted**
Covered by invariant #11 in CLAUDE.md. Consequence: producers must not put secrets (API keys, PII) in metadata. The MCP `summary` field is free-form text intended for human/agent triage — treat it as public even for encrypted payloads.
