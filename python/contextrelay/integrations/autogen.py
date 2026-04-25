"""
AutoGen integration for ContextRelay.

Optional dependency - install with: pip install context-relay[autogen]
"""

from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

from contextrelay import ContextRelay

if TYPE_CHECKING:
    from autogen_agentchat import AssistantAgent, FunctionTool


def contextrelay_push(
    data: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Push large context to ContextRelay edge and return a pointer URL.

    Use this tool when you need to share large payloads between agents
    or persist context for later retrieval. The URL returned can be
    passed to other agents or to contextrelay_pull to retrieve the
    original data.

    The data is stored at the Cloudflare edge with sub-millisecond
    access times from anywhere in the world. This avoids burning
    tokens on passing large context between agents.

    Args:
        data: The payload to store. Can be any text, JSON, or Markdown
             content up to 25 MB in size.
        metadata: Optional lightweight metadata dict. This is stored
                   unencrypted on the server even when using encrypted
                   mode, so do not put secrets in metadata.

    Returns:
        A ContextRelay pointer URL that can be used with contextrelay_pull
        to retrieve the original data.
    """
    # Get hub_url from global state or environment
    hub_url = _get_hub_url()
    hub = ContextRelay(hub_url)
    return hub.push(data=data, metadata=metadata)


def contextrelay_pull(url: str) -> str:
    """
    Pull context payload from a ContextRelay pointer URL.

    Use this tool to retrieve data that was previously stored with
    contextrelay_push. Provide the URL returned by contextrelay_push.

    If the URL was encrypted (contains a #key= fragment), the
    encryption is handled automatically and the decrypted
    payload is returned.

    Args:
        url: The ContextRelay pointer URL returned by contextrelay_push.

    Returns:
        The original payload that was stored.
    """
    hub_url = _get_hub_url_from_pointer(url)
    hub = ContextRelay(hub_url)
    return hub.pull(url)


def _get_hub_url() -> str:
    """Get the hub URL from global state."""
    # This will be set by get_autogen_tools
    return getattr(_get_hub_url, "_hub_url", "https://contextrelay.workers.dev")


def _get_hub_url_from_pointer(url: str) -> str:
    """Extract the hub URL from a pointer URL."""
    # The pointer URL is like: https://contextrelay.workers.dev/pull/uuid
    # Extract the base URL
    if "/pull/" in url:
        idx = url.index("/pull/")
        return url[:idx]
    return url


def get_autogen_tools(
    hub_url: str,
    encrypted: bool = False,
) -> List["FunctionTool"]:
    """
    Get AutoGen-compatible FunctionTool instances for ContextRelay.

    Returns a list of FunctionTool objects that can be passed to
    an AutoGen AssistantAgent's tools parameter.

    Args:
        hub_url: The base URL of the ContextRelay edge worker.
        encrypted: Whether to encrypt pushed context by default (default: False).

    Returns:
        A list containing FunctionTool instances for contextrelay_push and
        contextrelay_pull, ready to use with AutoGen AssistantAgent.

    Example:
        from autogen_agentchat import AssistantAgent
        from contextrelay.integrations.autogen import get_autogen_tools

        tools = get_autogen_tools("https://my-hub.workers.dev")
        agent = AssistantAgent(name="researcher", tools=tools)
    """
    # Import here to avoid hard dependency
    from autogen_agentchat import FunctionTool

    # Set the global hub URL for the function tools
    _get_hub_url._hub_url = hub_url.rstrip("/")

    # Create FunctionTools with proper descriptions (AutoGen uses docstrings)
    push_tool = FunctionTool(
        name="contextrelay_push",
        description=contextrelay_push.__doc__,
        func=contextrelay_push,
    )

    pull_tool = FunctionTool(
        name="contextrelay_pull",
        description=contextrelay_pull.__doc__,
        func=contextrelay_pull,
    )

    return [push_tool, pull_tool]
