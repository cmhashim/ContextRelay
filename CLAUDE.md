# ContextRelay Edge — AI Assistant Instructions

## Project Context

**Goal:** Zero-friction shared memory for multi-agent AI systems. Agent A pushes a large payload to the edge, gets back a ~80-char URL, passes it to Agent B. Agent B pulls the full payload. Token cost of the handoff: ~0.
**Tech Stack:** Cloudflare Workers + KV (TypeScript) for the edge API; Python 3.9+ for the SDK and MCP server.
**Audience:** AI engineers building multi-agent orchestrations across LLM providers.

## Repository Layout

```
contextrelay/
├── api/                      ← Cloudflare Worker
│   ├── src/index.ts          ← routes + ChannelBroker Durable Object
│   ├── wrangler.toml         ← CF config (KV + DO bindings)
│   └── package.json          ← wrangler + vitest
├── python/                   ← Python package (published as contextrelay-mcp)
│   ├── contextrelay/
│   │   ├── __init__.py       ← re-exports ContextRelay
│   │   ├── client.py         ← SDK: push() / pull() / subscribe()
│   │   └── mcp.py            ← FastMCP server (stdio transport)
│   ├── pyproject.toml        ← hatchling build, entry point contextrelay-mcp
│   └── requirements.txt
├── examples/                 ← runnable demos (not part of the package)
│   ├── agent_a_claude.py     ← Claude generates → pushes
│   ├── agent_b_mistral.py    ← Mistral pulls → summarises
│   ├── pubsub_demo.py        ← WebSocket channel subscribe/push selftest
│   ├── test.py               ← raw push/pull latency smoke test
│   └── requirements.txt      ← example-only deps (anthropic, mistralai)
├── README.md                 ← public-facing pitch + quickstart
├── LICENSE                   ← MIT
├── AGENTS.md                 ← current state, phase tracker
└── CLAUDE.md                 ← this file
```

## Working in This Repo

**Worker changes** (`api/`):
```bash
cd api
npm install
wrangler dev              # local preview
wrangler deploy           # requires CLOUDFLARE_API_TOKEN in env
```

**Python SDK / MCP changes** (`python/`):
```bash
cd python
pip install -e .          # installs `contextrelay-mcp` command
python -m contextrelay.mcp  # run MCP server against live worker
```

**Running examples**:
```bash
pip install -e ./python
pip install -r examples/requirements.txt
python examples/test.py                          # 125KB latency check
python examples/agent_a_claude.py --mode claude-code
python examples/agent_b_mistral.py <pointer_url>
```

## Architectural Invariants

1. **Worker is four routes.** `POST /push` stores (and optionally broadcasts), `GET /pull/:id` returns the stored KV value verbatim, `GET /peek/:id` returns only the metadata object, `GET /ws/:channel` attaches a WebSocket subscriber. No auth, no middleware.
2. **KV value cap is 25 MB.** Enforce at the worker if this ever matters.
3. **TTL is 24 hours** (`expirationTtl: 86400`). Context IDs are UUIDs and are treated as bearer tokens.
4. **No Phase-1 auth.** If adding auth, version the URL (`/v1/...`) — right now routes are unversioned intentionally for MVP simplicity.
5. **SDK surface is four methods.** `push(data, channel=None, encrypted=False, metadata=None) -> url`, `pull(url) -> str`, `peek(url) -> dict`, `subscribe(channel, callback)`. Resist adding `.store()`, `.retrieve()`, `.delete()`, `.unsubscribe()`, `.encrypt()`, `.decrypt()`, `.list()`.
6. **MCP tool docstrings are user-visible.** LLM clients read them verbatim — keep them crisp and action-oriented.
7. **Channel pub/sub uses Hibernatable WebSockets.** The `ChannelBroker` DO uses `state.acceptWebSocket()` — do not switch to `ws.accept()` without a reason; idle channels should cost nothing.
8. **Broadcast is fire-and-forget via `ctx.waitUntil`.** Producer latency must not be coupled to subscriber fan-out. Never `await` the DO broadcast from inside the `/push` response path.
9. **E2EE key lives only in the URL fragment.** When `encrypted=True`, the Fernet key is appended as `#key=...`. RFC 3986 guarantees the fragment is never transmitted to the server by HTTP clients. Never log, persist, or send the full URL to the Worker — the string after `#` is the whole secret.
10. **Fernet only; never roll our own crypto.** Stick with `cryptography.fernet.Fernet` (AES-128-CBC + HMAC-SHA256). Do not switch to raw AES-GCM, do not add a key-rotation scheme, do not add password-based key derivation without a real requirement — every such step widens the attack surface.
11. **Metadata is always plaintext, even when `encrypted=True`.** The KV value is `{data, metadata}`; `data` may be Fernet ciphertext but `metadata` is stored as-is. Peek works without a key *because* of this invariant. Never encrypt metadata, never put secrets in metadata, never merge metadata into the encrypted envelope.
12. **Pull unwraps client-side; peek unwraps server-side.** The Worker's `/pull/:id` returns the KV value verbatim (SDK calls `json.loads` and extracts `data`). The Worker's `/peek/:id` does its own `JSON.parse` to send only metadata over the wire. Do not move unwrap logic between sides without good reason — the bandwidth argument for peek depends on the server doing the parse.
13. **Legacy raw KV entries stay readable.** Any pre-Phase-5 value stored as raw text (not wrapped in `{data, metadata}`) must continue to work: peek returns `{}`, pull returns the raw string. The try/catch on JSON parsing (both in the Worker's peek route and the SDK's pull) is load-bearing — don't remove it.

## Critical Rules

1. **Read before editing.** Read the file first.
2. **No secrets in code.** `.env` is gitignored. Use `wrangler secret put` for Worker secrets when Phase 2 needs them.
3. **Don't reintroduce dead paths.** The repo was restructured; `src/worker/`, `src/sdk/`, `configs/`, `ContextRelayClient`, and `/v1/context` routes are all deliberately removed. Don't resurrect them.
4. **Entry point lives in `python/contextrelay/mcp.py::main`**. The `[project.scripts]` table in `pyproject.toml` wires this to the `contextrelay-mcp` CLI command.

## Pre-Ship Checklist

Before `/ship` or manual commit:
- [ ] Root stays clean (no `package.json`, `wrangler.toml`, `node_modules/`, `__pycache__/` at repo root — these live in `api/` or are gitignored)
- [ ] `api/src/index.ts` still has only the two routes
- [ ] `python/contextrelay/` still imports cleanly (`python -c "from contextrelay import ContextRelay"`)
- [ ] `README.md` reflects any new feature surface
- [ ] `AGENTS.md` updated with current phase state
