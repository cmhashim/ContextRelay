"""
CrewAI integration for ContextRelay.

Optional dependency - install with: pip install context-relay[crewai]
"""

from typing import TYPE_CHECKING, Any, Dict, Optional

from contextrelay import ContextRelay

if TYPE_CHECKING:
    from crewai import BaseTool


class ContextRelayPushTool:
    """
    CrewAI BaseTool for pushing large context to ContextRelay edge.

    Returns a pointer URL that can be passed between agents
    without token overhead.
    """

    name: str = "contextrelay_push"
    description: str = (
        "Push large context to ContextRelay edge, returns pointer URL. "
        "Use this when you need to share large payloads between agents "
        "or persist context for later retrieval. Returns a URL that "
        "can be passed to contextrelay_pull."
    )
    
    def __init__(self, hub_url: str, api_key: Optional[str] = None):
        self._hub = ContextRelay(hub_url)
        self._api_key = api_key

    def _run(self, data: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        """
        Push data to ContextRelay and return the pointer URL.

        Args:
            data: The payload to store (up to 25 MB).
            metadata: Optional metadata dict for the payload.

        Returns:
            The ContextRelay pointer URL for retrieval.
        """
        url = self._hub.push(
            data=data,
            metadata=metadata,
        )
        return url


class ContextRelayPullTool:
    """
    CrewAI BaseTool for pulling context from a ContextRelay pointer URL.

    Retrieves the original payload from a URL returned by contextrelay_push.
    """

    name: str = "contextrelay_pull"
    description: str = (
        "Pull context payload from a ContextRelay pointer URL. "
        "Use this to retrieve data that was previously stored with "
        "contextrelay_push. Provide the URL returned by contextrelay_push."
    )

    def __init__(self, hub_url: str, api_key: Optional[str] = None):
        self._hub = ContextRelay(hub_url)
        self._api_key = api_key

    def _run(self, url: str) -> str:
        """
        Pull data from a ContextRelay pointer URL.

        Args:
            url: The ContextRelay pointer URL (from contextrelay_push).

        Returns:
            The stored payload.
        """
        return self._hub.pull(url)
