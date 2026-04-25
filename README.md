# ContextRelay 🔗 Zero-Friction Shared Memory for Multi-Agent AI

[![PyPI version](https://img.shields.io/pypi/v/contextrelay?color=blue&label=PyPI)](https://pypi.org/project/contextrelay/)
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

## The Solution

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

## Install

```bash
pip install contextrelay
```

With optional framework integrations:

```bash
pip install contextrelay[langchain]   # LangChain retriever + callback handler
pip install contextrelay[crewai]      # CrewAI push/pull tools
pip install contextrelay[autogen]     # AutoGen function tools
```

---

## Quickstart — Python SDK

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

## Quickstart — MCP (Claude Desktop, Cursor)

```bash
pip install contextrelay
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

Restart Claude Desktop. You now have three native tools:

- **`push_context`** — offload any large payload, get back a URL
- **`peek_context`** — read only the metadata header before deciding to pull
- **`pull_context`** — retrieve any payload from a `workers.dev/pull/` URL

---

## Self-Hosting the Edge API

ContextRelay is fully self-hostable. You own your data.

```bash
git clone https://github.com/cmhashim/ContextRelay
cd ContextRelay/api && npm install
```

Create your KV namespace (Cloudflare stores the payloads):

```bash
wrangler kv namespace create CONTEXT_KV
# Copy the returned ID into wrangler.toml
```

Deploy:

```bash
wrangler deploy
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
| peek (metadata only) | any | ~89ms |

---

## Pub/Sub Signaling

Multi-agent orchestration usually means polling or manual callbacks. ContextRelay ships a WebSocket signaling layer so Agent B can subscribe to a channel and get the pointer URL the millisecond Agent A pushes it.

```python
from contextrelay import ContextRelay
import threading

hub = ContextRelay("https://contextrelay.your-account.workers.dev")

# Agent B — subscribe in a background thread
def on_context_ready(url):
    payload = hub.pull(url)
    print(f"Agent B got {len(payload)} chars")

threading.Thread(
    target=hub.subscribe, args=("project_x", on_context_ready), daemon=True
).start()

# Agent A — push triggers Agent B's callback within ~20ms
hub.push(huge_spec, channel="project_x")
```

Each channel is a Cloudflare Durable Object using Hibernatable WebSockets — idle channels pay zero CPU/memory. The SDK auto-reconnects with exponential backoff and 30-second keepalive.

---

## Metadata & Peek

Decide before you download. Attach a metadata header on push; any agent can read it with a single lightweight call — no payload download needed.

```python
url = hub.push(
    big_payload,
    metadata={"summary": "Database schema for orders service", "size_kb": 80},
)

# Agent B peeks before committing tokens to a full pull
meta = hub.peek(url)
# → {"summary": "Database schema for orders service", "size_kb": 80}

data = hub.pull(url)  # only if relevant
```

Metadata is always plaintext — `peek` works even when the payload is encrypted.

---

## End-to-End Encryption (opt-in)

Encryption runs **entirely client-side**. Cloudflare sees only ciphertext.

```python
url = hub.push(secret_payload, encrypted=True)
# url → https://.../pull/<uuid>#key=<fernet_key>

plaintext = hub.pull(url)  # decrypted locally — key never leaves your machine
```

Per RFC 3986, URL fragments (`#key=...`) are never transmitted to the server. The Worker stores — and only ever sees — opaque Fernet ciphertext.

- **Cipher:** Fernet (AES-128-CBC + HMAC-SHA256)
- **Key:** fresh 256-bit key per upload, embedded in the URL fragment

---

## Framework Integrations

### LangChain

```python
from contextrelay.integrations import ContextRelayRetriever, ContextRelayCallbackHandler

retriever = ContextRelayRetriever(hub_url="https://...", channel="agent-results")
handler = ContextRelayCallbackHandler(hub=hub, channel="llm-outputs")
```

### CrewAI

```python
from contextrelay.integrations import ContextRelayPushTool, ContextRelayPullTool

tools = [ContextRelayPushTool(hub_url="https://..."), ContextRelayPullTool(hub_url="https://...")]
```

### AutoGen

```python
from contextrelay.integrations import get_autogen_tools

tools = get_autogen_tools(hub_url="https://...")
# Returns FunctionTool instances ready for AssistantAgent
```

---

## Roadmap

- [x] Phase 1 — Core edge API (POST /push, GET /pull) + Python SDK
- [x] Phase 2 — Cross-provider handoff (Claude → Mistral, ~0 tokens)
- [x] Phase 3 — MCP native tools (push_context, peek_context, pull_context)
- [x] Phase 4 — WebSocket pub/sub via Durable Objects (21ms fan-out)
- [x] Phase 5 — E2EE vault (Fernet, key in URL fragment)
- [x] Phase 6 — Metadata envelope + peek() lazy loading
- [x] Phase 7 — LangChain, CrewAI, AutoGen integrations
- [ ] Phase 8 — Safety scanners (Llama-Guard 3 for public deployments)

---

## License

MIT — see [LICENSE](LICENSE).
