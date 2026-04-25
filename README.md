# ContextRelay 🔗 The Zero-Friction S3 for Agentic Memory

[![PyPI version](https://img.shields.io/pypi/v/contextrelay-mcp?color=blue&label=PyPI)](https://pypi.org/project/contextrelay-mcp/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue)](https://www.python.org/downloads/)

> **Pass a URL. Not a token wall.**
> ContextRelay stores massive AI context payloads at the Cloudflare edge and gives you back a single URL. Agents exchange the pointer — not the data.

---

## The Problem

Multi-agent AI pipelines have a dirty secret: **they burn most of their token budget passing data around, not thinking.**

When Agent A (Claude) finishes building a 50,000-token architecture spec and needs to hand it to Agent B (Mistral), your orchestrator has two options — and both are terrible:

| Option | Cost |
|--------|------|
| Pass the full text in the next prompt | 50,000 tokens × $0.003/1K = **$0.15 per handoff** |
| Truncate it | You lose context. Agent B works blind. |

At scale — hundreds of agents, thousands of handoffs per day — **you are paying a token tax on data transit, not intelligence.** This is waste, not compute.

---

## The Solution: Token Cost Arbitrage

ContextRelay replaces token-expensive data blobs with **sub-100ms URL pointers**.

```
Without ContextRelay:        With ContextRelay:
─────────────────────      ──────────────────────────────────────
Agent A → [50KB JSON]      Agent A → POST /push → [UUID url]
           ↓                                          ↓
        Agent B            Agent B → GET /pull/<id> → [50KB JSON]
        (50K tokens burned)          (73ms, ~0 tokens)
```

**The math:** A 50KB context payload costs ~12,500 tokens to pass directly. Via ContextRelay, the pointer URL is ~80 characters — effectively **zero tokens**. At 1,000 agent handoffs/day, that's ~$150/day saved.

ContextRelay runs on **Cloudflare Workers** — globally distributed V8 isolates with sub-millisecond cold starts. Your context lives at the edge, milliseconds from wherever your agents are running.

---

## Quickstart — MCP Users (Claude Desktop, Cursor)

Install the server:

```bash
pip install contextrelay-mcp
```

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "contextrelay": {
      "command": "contextrelay-mcp",
      "env": {
        "CONTEXTRELAY_URL": "https://contextrelay.your-account.workers.dev"
      }
    }
  }
}
```

Restart Claude Desktop. You now have two native tools:

- **`push_context`** — offload any large payload, get back a URL
- **`pull_context`** — retrieve any payload from a `workers.dev/pull/` URL

Claude will call these automatically when handling large context handoffs.

---

## Quickstart — Python SDK

```bash
pip install contextrelay-mcp
```

```python
from contextrelay import ContextRelay

hub = ContextRelay("https://contextrelay.your-account.workers.dev")

# Agent A: offload 50KB of context, hand off a URL
url = hub.push(large_json_string)
print(url)  # https://...workers.dev/pull/3f7a2b...

# Agent B: retrieve the full payload in one call
data = hub.pull(url)
```

Five lines. No infrastructure. No token waste.

---

## Self-Hosting the Edge API

ContextRelay is fully self-hostable. You own your data.

- **Clone & deploy in 3 commands:**
  ```bash
  git clone https://github.com/cmhashim/contextrelay
  cd contextrelay/api && npm install
  wrangler deploy
  ```

- **Create your KV namespace** (Cloudflare stores the payloads):
  ```bash
  wrangler kv namespace create CONTEXT_KV
  # Copy the returned ID into wrangler.toml
  ```

- **Set your worker URL** in the SDK or MCP server:
  ```bash
  export CONTEXTRELAY_URL="https://contextrelay.your-account.workers.dev"
  ```

Free Cloudflare tier covers 100,000 Worker requests/day and 1GB KV storage.

---

## Architecture

```
Your Agent
    │
    │  POST /push (payload)
    ▼
Cloudflare Worker  ←── globally distributed, <1ms cold start
    │
    │  KV.put(uuid, payload, ttl=86400)
    ▼
Cloudflare KV  ←── edge-replicated, 24hr TTL
    │
    │  returns { url: "https://.../pull/<uuid>" }
    ▼
Your Agent  ──→  passes URL to next agent (80 chars, ~0 tokens)
                       │
                       │  GET /pull/<uuid>
                       ▼
               Cloudflare Worker → KV.get(uuid) → payload
```

**Benchmarks (live Cloudflare deployment):**

| Operation | Payload | Latency |
|-----------|---------|---------|
| push | 125 KB | ~250ms |
| pull | 125 KB | **~75ms** |
| pull | 220 KB | ~100ms |

---

## Pub/Sub Signaling (no polling)

Multi-agent orchestration usually means Agent B polling, or your framework
wiring up a callback by hand. ContextRelay ships a WebSocket signaling layer
so Agent B can *subscribe to a channel* and get the pointer URL the
millisecond Agent A pushes it.

```python
from contextrelay import ContextRelay
import threading

hub = ContextRelay("https://contextrelay.your-account.workers.dev")

# --- Agent B, in a background thread ---
def on_context_ready(url):
    payload = hub.pull(url)
    print(f"Agent B got {len(payload)} chars: {payload[:80]}...")

threading.Thread(
    target=hub.subscribe, args=("project_x", on_context_ready), daemon=True
).start()

# --- Agent A, some time later ---
hub.push(huge_spec, channel="project_x")
# Agent B's callback fires within ~20 ms of the push returning.
```

**Under the hood:** each channel is a Cloudflare Durable Object using
Hibernatable WebSockets. Idle channels pay zero CPU/memory; fan-out is
in-memory on the same DO instance. The Python SDK auto-reconnects with
exponential backoff and 30-second ping keepalive — drops are transparent.

---

## Metadata & Peek (decide before you download)

Before pulling a 200 KB payload into a context window, an agent should
be able to *peek* at what it is. ContextRelay lets the producer attach a
small plaintext metadata header on push, and any agent can read it with
one lightweight call:

```python
url = hub.push(
    big_payload,
    metadata={"summary": "Database schema for orders service",
              "size_kb": 80, "type": "sql"},
)

# Agent B, on receiving url:
hub.peek(url)
# → {"summary": "Database schema for orders service", "size_kb": 80, "type": "sql"}

# Agent decides to pull only if it matches the task.
hub.pull(url)
```

**Route:** `GET /peek/:id` — returns only the metadata object (not the
payload). Server-side JSON parse means the heavy `data` field never
touches the wire. Works even when the payload is encrypted — metadata
stays plaintext by design, so peek needs no key.

The MCP server exposes `peek_context(url)` with guidance to LLM clients
to call it **first** on any ContextRelay URL, so agents stop burning
tokens on pulls they didn't need.

---

## End-to-End Encryption (opt-in)

Passing secrets through a third-party edge — API keys, PII, proprietary
code — means trusting that edge. ContextRelay's opt-in E2EE removes the
trust assumption. Encryption runs **entirely client-side**; Cloudflare
sees only ciphertext.

```python
hub = ContextRelay("https://contextrelay.your-account.workers.dev")

url = hub.push(secret_payload, encrypted=True)
# url → https://.../pull/<uuid>#key=<fernet_key>

plaintext = hub.pull(url)   # → decrypted locally
```

**How the key stays private:**

Per RFC 3986, URL fragments (everything after `#`) are never transmitted
to the server by HTTP clients. So when the SDK calls `GET /pull/<uuid>`,
the `#key=...` portion is stripped locally and never leaves your machine.
The Worker stores — and only ever sees — opaque Fernet ciphertext
(`gAAAAA...`).

- **Cipher:** Fernet (AES-128-CBC + HMAC-SHA256)
- **Key:** fresh 256-bit URL-safe base64 key per upload
- **Errors:** a wrong/missing key raises `ValueError("Failed to decrypt: Invalid or missing key")` — never a partial or corrupt payload

---

## Roadmap

- [x] Phase 1 — Core edge API + Python SDK + MCP server
- [x] Phase 2 — WebSocket pub/sub (agents subscribe to context-ready events)
- [x] Phase 3 — E2EE (Fernet, key in URL fragment — server never sees plaintext)
- [x] Phase 4 — Metadata & peek (decide before you pull)
- [ ] Phase 5 — LangChain / CrewAI / AutoGen native integrations

---

## License

MIT — see [LICENSE](LICENSE).
