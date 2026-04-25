"""
ContextRelay MCP Server
=====================
Exposes the ContextRelay edge network as native MCP tools so that any
MCP-compatible AI client (Claude Desktop, Cursor, etc.) can offload,
peek at, and retrieve large context payloads without consuming token
budget.

Run directly:
    contextrelay-mcp

Or via Python:
    python -m contextrelay.mcp
"""

import json
import os
from typing import Optional

import requests
from mcp.server.fastmcp import FastMCP

from .client import ContextRelay
from .agent_bridge import AgentBridge

CONTEXTRELAY_URL = os.environ.get(
    "CONTEXTRELAY_URL", "https://contextrelay.your-account.workers.dev"
)

hub = ContextRelay(base_url=CONTEXTRELAY_URL)
mcp = FastMCP("ContextRelay")


@mcp.tool()
def push_context(
    data: str,
    channel: Optional[str] = None,
    encrypted: bool = False,
    summary: Optional[str] = None,
) -> str:
    """
    Uploads a large text or JSON payload to the ContextRelay edge network
    and returns a short URL pointer.

    Use this tool whenever you need to:
    - Pass a large block of text, code, or JSON to another agent without
      filling up the conversation window.
    - Save context for later retrieval in the same or a future session.
    - Hand off data between two different LLMs or AI pipelines.

    The returned URL is valid for 24 hours. Treat it as a bearer token —
    anyone with the URL can read the payload.

    Args:
        data:      The text or JSON string to upload. Can be arbitrarily
                   large (up to 25 MB). Plain text, JSON, Markdown, and
                   code all work.
        channel:   Optional channel name. If set, any subscriber listening
                   on this channel (via the Python SDK's `subscribe()`
                   method) receives the pointer URL immediately over
                   WebSocket.
        encrypted: Set encrypted=True if the payload contains API keys,
                   PII, proprietary code, or sensitive data. This
                   encrypts the data locally before upload. The
                   decryption key will be embedded in the returned URL
                   hash so the receiving agent can decrypt it.
        summary:   Optional one-line description of what this payload
                   contains (e.g. "Database schema for the orders
                   service"). When set, the receiving agent can call
                   peek_context(url) to read this summary without
                   downloading the full payload. Strongly recommended
                   whenever you expect another agent to decide whether
                   to pull.

    Returns:
        A full HTTPS URL pointing to the stored payload, e.g.:
        https://contextrelay.workers.dev/pull/<uuid>

        When encrypted=True, the URL carries a `#key=...` fragment that
        the receiving agent must keep intact when calling pull_context.
    """
    metadata = {"summary": summary} if summary else None
    try:
        return hub.push(
            data,
            channel=channel,
            encrypted=encrypted,
            metadata=metadata,
        )
    except requests.HTTPError as e:
        return f"Error pushing context: {e}"


@mcp.tool()
def peek_context(url: str) -> str:
    """
    Use this tool FIRST when you receive a ContextRelay URL. It returns a
    lightweight summary of what the URL contains without downloading
    the full file, saving tokens and context window space. You can use
    this to decide if you actually need to use pull_context.

    Args:
        url: The full ContextRelay pointer URL, with or without a `#key=`
             fragment.

    Returns:
        A formatted string of the metadata headers attached by the
        producer (for example: "summary: Database schema for orders").
        Returns "(no metadata available)" if the producer attached none
        or if the entry predates metadata support.
    """
    try:
        metadata = hub.peek(url)
    except (requests.HTTPError, ValueError) as e:
        return f"Error peeking context: {e}"
    if not metadata:
        return "(no metadata available)"
    return json.dumps(metadata, indent=2, ensure_ascii=False)


@mcp.tool()
def pull_context(url: str) -> str:
    """
    Downloads a context payload from a ContextRelay URL pointer and
    returns the full text or JSON content.

    Use this tool whenever:
    - A user or another agent gives you a URL containing
      'workers.dev/pull/'.
    - You need to load previously offloaded context back into the
      conversation for analysis, summarisation, or continuation.

    Args:
        url: The full ContextRelay pointer URL to retrieve, e.g.:
             https://contextrelay.workers.dev/pull/<uuid>

    Returns:
        The raw text or JSON content that was originally uploaded.
        Returns an error message if the URL has expired (TTL: 24 hours)
        or is not found.
    """
    try:
        return hub.pull(url)
    except requests.HTTPError as e:
        return f"Error pulling context: {e}"
    except ValueError as e:
        return f"Error pulling context: {e}"


@mcp.tool()
def bridge_task(
    task: str,
    task_channel: str = "agent-tasks",
    done_channel: str = "agent-done",
    timeout: int = 600,
) -> str:
    """
    Dispatch a coding task to a local agent (e.g. Vibe running in tmux) via
    ContextRelay pub/sub and block until the result is returned.

    Requires the ContextRelay AgentBridge daemon to be running on the target
    machine:
        contextrelay-bridge start --task-channel agent-tasks --done-channel agent-done --tmux vibe

    Use this tool when you want to delegate implementation work to Vibe (or
    another coding agent) and receive the output back in this conversation
    without manual copy-paste. The task is pushed to ContextRelay, the bridge
    dispatches it to the agent's tmux pane, waits for the agent to finish,
    and returns the captured terminal output.

    Args:
        task:          Full task description. Include file paths, context,
                       and success criteria. Longer is better — the bridge
                       uses ContextRelay so token length here does not matter.
        task_channel:  The channel the bridge daemon is listening on.
                       Default: "agent-tasks".
        done_channel:  The channel the bridge publishes results to.
                       Default: "agent-done".
        timeout:       Seconds to wait for the agent to finish (default: 600).

    Returns:
        The terminal output captured from the agent after it finishes,
        or a timeout/error message if the bridge did not respond in time.
    """
    bridge = AgentBridge(hub, task_channel=task_channel, done_channel=done_channel)
    return bridge.push_and_wait(task, timeout=timeout)


def main():
    """Entry point for the contextrelay-mcp CLI command."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
