# ContextRelay — Shared Memory and Channels for Multi-Agent AI

[![PyPI version](https://img.shields.io/pypi/v/contextrelay?color=blue&label=PyPI)](https://pypi.org/project/contextrelay/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue)](https://www.python.org/downloads/)

ContextRelay stores large payloads at the Cloudflare edge and returns a short URL pointer, so agents on different LLM providers can hand off context without pasting it through prompts. Pub/sub channels coordinate them in ~20 ms. End-to-end encryption is opt-in per push, with the key kept in the URL fragment so it never reaches the server.

**Two ways to run it:**

| | Self-host (open source) | Managed cloud |
|---|---|---|
| **License** | MIT | MIT (same code) |
| **Where it runs** | Your Cloudflare account | Our managed Worker |
| **Setup** | `wrangler deploy` | `pip install contextrelay` + API key |
| **Auth / quota** | None — open mode | API keys, monthly quotas |
| **Cost** | Cloudflare's free tier covers ~100K req/day | Free / $29 / $99 plans |
| **Best for** | You want full ownership and zero vendor lock-in | You want zero ops, a dashboard, and metered billing |

Same SDK either way — point it at your Worker URL or at the managed cloud. Everything in this README works on both.

---

## The Problem

Multi-agent pipelines burn most of their token budget passing data around, not thinking.

When Agent A (Claude) finishes a 50,000-token architecture document and needs to hand it to Agent B (Mistral), you have two bad options:

| Option | Cost |
|--------|------|
| Paste the full text into the next prompt | 50 K tokens × $0.003/1K = **$0.15 per handoff** |
| Truncate it | Agent B works blind |

At 1,000 handoffs/day that is $150/day in pure overhead — no thinking, just moving bytes around.

---

## The Solution

ContextRelay replaces the blob with an 80-character URL pointer, and adds a channel layer for async coordination.

```
Without ContextRelay          With ContextRelay
─────────────────────         ──────────────────────────────────
Agent A → [50 KB JSON]        Agent A → push() → "https://.../pull/uuid"
           ↓                                             ↓
        Agent B               Agent B → pull(url) → [50 KB JSON]
        (50 K tokens burned)            (73 ms, ~0 tokens)
```

For coordination across more than two agents, push to a named channel and have other agents `subscribe()` — they receive the pointer URL over WebSocket within ~20 ms.

---

## What ContextRelay is *not*

Honest scope, so you can decide if it fits your problem:

- **Not a vector store.** No embeddings, no semantic search. If you need persistent recall over user history, use [Mem0](https://mem0.ai) or [Letta](https://letta.com).
- **Not a long-term memory layer.** Default TTL is 24 hours. If you need durable agent memory, use Letta/MemGPT.
- **Not a general message broker.** No durable queues, no exactly-once delivery. If you need that, use Redis or SQS.
- **Not a workflow engine.** No DAGs, no retries, no orchestration. If you need that, use Temporal or Inngest.

ContextRelay's sweet spot is the moment you have two agents on different providers, a 50 KB payload, and want it to cost ~20 tokens — with optional encryption and channel coordination on top.

---

## Quickstart

```bash
pip install contextrelay
```

Get an API key at **[contextrelay-cloud.vercel.app](https://contextrelay-cloud.vercel.app)** → Dashboard → API Keys.

```python
import os
from contextrelay import ContextRelay

relay = ContextRelay(api_key=os.environ["CONTEXTRELAY_API_KEY"])

# Agent A — store a large payload, hand off the URL
url = relay.push(large_text)

# Agent B — retrieve the payload from the URL
data = relay.pull(url)
```

The `base_url` defaults to the managed cloud worker. No infrastructure to run.

---

## Real Use Cases

### 1 — Cross-provider code review (Claude → Mistral)

Agent A (Claude) does a deep code review of a pull request. The full review is too large to fit in Mistral's context alongside the follow-up instructions. ContextRelay bridges them at near-zero cost.

```python
import os
import anthropic
from mistralai import Mistral
from contextrelay import ContextRelay

relay = ContextRelay(api_key=os.environ["CONTEXTRELAY_API_KEY"])

# ── Agent A: Claude reviews the PR ──────────────────────────────────────────
claude = anthropic.Anthropic()

diff = open("pr_diff.txt").read()  # ~20 KB of git diff

review = claude.messages.create(
    model="claude-opus-4-5",
    max_tokens=4096,
    messages=[{
        "role": "user",
        "content": f"Do a thorough code review of this PR diff:\n\n{diff}"
    }],
).content[0].text

# Push the full review to ContextRelay — get back a short URL
review_url = relay.push(review, metadata={"type": "code_review", "pr": "PR-441"})
print(f"Review stored: {review_url}")

# ── Agent B: Mistral turns the review into Jira tickets ─────────────────────
mistral = Mistral(api_key=os.environ["MISTRAL_API_KEY"])

# Pull the review by URL — no token cost in the orchestrator
full_review = relay.pull(review_url)

tickets = mistral.chat.complete(
    model="mistral-large-latest",
    messages=[{
        "role": "user",
        "content": (
            f"Convert this code review into Jira tickets, one per issue found:\n\n"
            f"{full_review}"
        )
    }],
).choices[0].message.content

print(tickets)
```

**Token cost of the handoff:** the URL is ~80 chars ≈ 20 tokens. The review itself (~3,000 tokens) is fetched directly by Mistral — it never appears in Claude's conversation again.

---

### 2 — Research synthesis pipeline (parallel agents, one channel)

Three specialist agents research different sections of a topic simultaneously. A synthesis agent subscribes to a channel and reassembles the full report the moment all three push their findings.

```python
import os, threading
from contextrelay import ContextRelay

relay = ContextRelay(api_key=os.environ["CONTEXTRELAY_API_KEY"])

collected = {}

def on_section_ready(url):
    section = relay.pull(url)
    meta = relay.peek(url)
    collected[meta["section"]] = section
    if len(collected) == 3:
        full_report = "\n\n".join(
            collected[k] for k in ["intro", "analysis", "conclusion"]
        )
        print("Full report assembled:", len(full_report), "chars")

# Synthesis agent subscribes before any pushes arrive
threading.Thread(
    target=relay.subscribe,
    args=("report-channel", on_section_ready),
    daemon=True,
).start()

# Three researcher agents run in parallel and push to the same channel
def researcher(section_name, prompt):
    # ... call your LLM here ...
    result = f"[{section_name} findings]"
    relay.push(result, channel="report-channel", metadata={"section": section_name})

threads = [
    threading.Thread(target=researcher, args=(name, prompt))
    for name, prompt in [
        ("intro",       "Write an introduction to quantum computing"),
        ("analysis",    "Analyse the current state of quantum hardware"),
        ("conclusion",  "Summarise the 5-year outlook for quantum computing"),
    ]
]
for t in threads:
    t.start()
for t in threads:
    t.join()
```

Each agent push triggers the subscriber's callback within ~20ms. The synthesis agent never polls.

---

### 3 — Long-running task offload to Claude Code (AgentBridge)

An orchestrator script delegates a coding task to a Claude Code instance running in a tmux window. `push_and_wait` blocks until Claude finishes and the result is relayed back — no polling, no SSH, no manual copy-paste.

```python
import os
from contextrelay import ContextRelay, AgentBridge

relay = ContextRelay(api_key=os.environ["CONTEXTRELAY_API_KEY"])

# Start the coordinator in your tmux session first:
#   python3 vibe_coordinator.py --session vibe --window 0

bridge = AgentBridge(
    relay,
    task_channel="vibe-tasks",
    done_channel="vibe-done",
)

result = bridge.push_and_wait(
    "Refactor the auth module to replace Clerk with Firebase. "
    "Update all imports, run the type checker, and return a summary of changes."
)

print(result)
```

The bridge pushes the task via ContextRelay, the coordinator pastes it into the Claude Code terminal, waits for it to finish, and pushes the output back. The orchestrator gets the full response as a string.

---

### 4 — Oversized context handoff within a single chain

Sometimes a single chain produces output too large for the next step's context window. Use ContextRelay as a "context checkpoint" — checkpoint large intermediate results and reload only when needed.

```python
import os, json
from contextrelay import ContextRelay

relay = ContextRelay(api_key=os.environ["CONTEXTRELAY_API_KEY"])

# Step 1 — generate a large data extraction result
raw_data = run_sql_query()          # 80 KB JSON, too large for the next prompt
checkpoint_url = relay.push(
    json.dumps(raw_data),
    metadata={"step": "sql_extraction", "rows": len(raw_data)},
)

# Step 2 — peek first to decide whether to proceed
meta = relay.peek(checkpoint_url)
print(f"Checkpoint has {meta['rows']} rows — proceeding to analysis")

# Step 3 — load only when you need it, in the agent that needs it
data = json.loads(relay.pull(checkpoint_url))
analysis = run_analysis_agent(data)
```

Peeks cost almost nothing (~89ms, no payload download). Pull only when the agent actually needs the data.

---

### 5 — Claude plans, Mistral builds (fully autonomous)

Use Claude Opus as your architect (high reasoning, worth the cost) and Mistral as your engineer (fast, accurate, cheaper per token). They never share a conversation — ContextRelay channels connect them without any human handoff.

Start the Mistral engineer in one terminal. It subscribes to `task-assigned` and waits:

```python
# mistral_engineer.py — start this first
import os
from mistralai import Mistral
from contextrelay import ContextRelay

relay   = ContextRelay(api_key=os.environ["CONTEXTRELAY_API_KEY"])
mistral = Mistral(api_key=os.environ["MISTRAL_API_KEY"])

def on_task(url: str):
    architecture = relay.pull(url)
    code = mistral.chat.complete(
        model="mistral-large-latest",
        messages=[{
            "role": "user",
            "content": (
                "You are a senior engineer. Implement this architecture as "
                "complete, runnable code. Every file. No placeholders.\n\n"
                + architecture
            ),
        }],
    ).choices[0].message.content
    relay.push(code, channel="task-done", metadata={"role": "implementation"})
    print("Implementation published → task-done")

relay.subscribe("task-assigned", on_task)  # blocks, waits for Claude
```

Then run the Python automation that drives the full loop:

```python
import os, anthropic
from mistralai import Mistral
from contextrelay import ContextRelay

relay   = ContextRelay(api_key=os.environ["CONTEXTRELAY_API_KEY"])
claude  = anthropic.Anthropic()

# ── Claude Opus: architect ───────────────────────────────────────────
arch = claude.messages.create(
    model="claude-opus-4-5",
    max_tokens=8192,
    messages=[{
        "role": "user",
        "content": (
            "Design a production FastAPI task management API. Include data models, "
            "all endpoints, JWT auth, SQLAlchemy setup, and file structure. "
            "Be complete — an engineer will implement directly from this document."
        )
    }],
).content[0].text

# Push to task-assigned — Mistral's subscriber fires in ~20 ms
arch_url = relay.push(arch, channel="task-assigned", metadata={"role": "architecture"})
print(f"Architecture pushed: {arch_url}")

# Subscribe to task-done to receive the implementation
def on_done(url):
    impl = relay.pull(url)
    print(f"Implementation received: {len(impl):,} chars")

relay.subscribe("task-done", on_done)
```

**What just happened:** Claude never saw Mistral's output. Mistral never saw Claude's conversation. They exchanged one URL (~20 tokens). The subscriber fires within ~20 ms of the push — no polling, no human handoff, no copy-paste.

---

## More Features

### End-to-end encryption

```python
# Key is generated client-side and embedded in the URL fragment.
# The server stores only ciphertext — never sees the key.
url = relay.push(secret_payload, encrypted=True)
# → https://.../pull/<uuid>#key=<fernet_key>

plaintext = relay.pull(url)  # decrypted locally
```

### MCP (Claude Desktop / Claude Code)

```json
{
  "mcpServers": {
    "contextrelay": {
      "command": "contextrelay-mcp",
      "env": {
        "CONTEXTRELAY_URL": "https://contextrelay.hashim-cmd.workers.dev",
        "CONTEXTRELAY_API_KEY": "cr_live_..."
      }
    }
  }
}
```

Claude gains three tools: `push_context`, `peek_context`, `pull_context`.

### SDK reference

| Method | What it does |
|--------|-------------|
| `push(data, channel=None, encrypted=False, metadata=None)` | Upload payload (str, up to 25 MB), returns URL |
| `pull(url)` | Download payload. Auto-decrypts if URL contains `#key=` |
| `peek(url)` | Fetch metadata only — no payload download (~89 ms) |
| `subscribe(channel, fn)` | Subscribe to a channel. Calls `fn(url)` on each push. Blocking — run in a thread |
| `publish(channel, msg)` | Publish a signal message to a channel without storing a payload |

`publish()` is useful for coordinating agents without sending data — for example, broadcasting a "pipeline complete" signal to all subscribers on a channel.

### Framework integrations

```bash
pip install contextrelay[langchain]   # ContextRelayRetriever, ContextRelayCallbackHandler
pip install contextrelay[crewai]      # ContextRelayPushTool, ContextRelayPullTool
pip install contextrelay[autogen]     # get_autogen_tools()
```

---

## Managed Cloud vs Self-Hosting

| | Managed Cloud | Self-Hosted |
|---|---|---|
| Setup | Sign up, get API key, done | `wrangler deploy` on your CF account |
| API key required | Yes | Optional |
| Data ownership | Cloudflare edge (shared worker) | Your own CF account |
| Cost | Free / Pro / Team tiers | Free CF Workers tier |
| URL | `contextrelay.hashim-cmd.workers.dev` | Your `*.workers.dev` subdomain |

### Pricing

| Plan | Price | Pushes / mo | Pulls / mo | API keys | Max payload | TTL |
|------|-------|-------------|------------|----------|-------------|-----|
| Free | $0 | 1,000 | 10,000 | 2 | 25 MB | 24 hr |
| Pro | $29/mo | 100,000 | 1,000,000 | 10 | 25 MB | 24 hr |
| Team | $99/mo | 1,000,000 | 10,000,000 | 100 | 25 MB | 24 hr |

WebSocket pub/sub and client-side E2EE are included on all plans. Pushes over the monthly limit return a 402 — pulls are never blocked.

**Managed cloud:** [contextrelay-cloud.vercel.app](https://contextrelay-cloud.vercel.app)

<a id="self-hosting"></a>

### Self-hosting

ContextRelay runs entirely on Cloudflare Workers. The free Cloudflare tier (100K Worker requests/day, 1 GB of KV storage) is enough for most personal and small-team workloads.

**1. Clone and install**

```bash
git clone https://github.com/cmhashim/ContextRelay
cd ContextRelay/api
npm install
```

**2. Create the KV namespace and a Durable Object binding**

```bash
wrangler kv namespace create CONTEXT_KV
# copy the id printed → paste into wrangler.toml as `kv_namespaces`
```

The `wrangler.toml` already declares the `ChannelBroker` Durable Object — Cloudflare provisions it on first deploy.

**3. Deploy**

```bash
wrangler deploy
```

You'll get a URL like `https://contextrelay.<your-account>.workers.dev`. Point the SDK at it:

```python
relay = ContextRelay(base_url="https://contextrelay.<your-account>.workers.dev")
```

**No API key needed in self-host mode.** The Worker only enforces auth when the optional `API_KEYS_KV` binding is present (used by the managed cloud).

**Operating notes:**

- All four routes (`POST /push`, `GET /pull/:id`, `GET /peek/:id`, `GET /ws/:channel`) work the same as the managed cloud.
- Payloads are stored in KV with a 24-hour TTL, capped at 25 MB.
- WebSocket pub/sub uses Hibernatable Durable Objects, so idle channels cost nothing.
- The MCP server (`pip install contextrelay && contextrelay-mcp`) accepts `CONTEXTRELAY_URL=https://your-worker-url` to talk to your self-hosted instance.

---

## Benchmarks

| Operation | Payload | Latency |
|-----------|---------|---------|
| push | 125 KB | ~250 ms |
| pull | 125 KB | **~75 ms** |
| peek | any | ~89 ms |
| WebSocket fan-out | — | ~21 ms |

All measured against the live Cloudflare deployment from a UK machine.

---

## License

MIT — see [LICENSE](LICENSE).
