"""
LangChain integration for ContextRelay.

Optional dependency - install with: pip install context-relay[langchain]
"""

from typing import TYPE_CHECKING, Any, List, Optional

from contextrelay import ContextRelay

if TYPE_CHECKING:
    from langchain_core.callbacks import BaseCallbackHandler
    from langchain_core.documents import Document
    from langchain_core.retrievers import BaseRetriever


class ContextRelayRetriever:
    """
    LangChain BaseRetriever implementation for ContextRelay.

    Puts queries as context into ContextRelay and returns documents
    containing the URLs for retrieval.

    Args:
        hub_url: Base URL of the ContextRelay edge worker.
        api_key: Optional API key for authenticated access.
        channel: Optional channel name to push queries to.
        encrypted: Whether to encrypt the pushed context (default: False).
    """

    def __init__(
        self,
        hub_url: str,
        api_key: Optional[str] = None,
        channel: Optional[str] = None,
        encrypted: bool = False,
    ):
        self.hub_url = hub_url
        self.api_key = api_key
        self.channel = channel
        self.encrypted = encrypted
        self._hub = ContextRelay(hub_url)

    def _get_relevant_documents(self, query: str) -> List["Document"]:
        """
        Push the query as context to ContextRelay and return a document
        containing the URL for retrieval.

        Args:
            query: The search query to push as context.

        Returns:
            List of Document objects with page_content as the URL and
            metadata containing the contextrelay_url.
        """
        # Import here to avoid hard dependency
        from langchain_core.documents import Document as LangchainDocument

        url = self._hub.push(
            data=query,
            channel=self.channel,
            encrypted=self.encrypted,
        )
        # Return a document with the URL as content
        return [
            LangchainDocument(
                page_content=url,
                metadata={"contextrelay_url": url},
            )
        ]


class ContextRelayCallbackHandler:
    """
    LangChain callback handler that pushes LLM output to a ContextRelay channel.

    Useful for capturing agent outputs and making them available
    to other agents via ContextRelay.

    Args:
        hub: A ContextRelay instance.
        channel: The channel name to push outputs to.
        encrypted: Whether to encrypt the pushed content (default: False).
    """

    def __init__(
        self,
        hub: ContextRelay,
        channel: str,
        encrypted: bool = False,
    ):
        self._hub = hub
        self._channel = channel
        self._encrypted = encrypted

    def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        """
        Called when an LLM call ends. Pushes the output to ContextRelay.

        Args:
            response: The LLM response object.
            **kwargs: Additional callback arguments.
        """
        # Extract the output text from the response
        # Handle different response formats
        output = ""
        if hasattr(response, "generations"):
            if response.generations and len(response.generations) > 0:
                gen = response.generations[0]
                if hasattr(gen, "text"):
                    output = gen.text
                elif hasattr(gen, "message") and hasattr(gen.message, "content"):
                    output = gen.message.content
        elif hasattr(response, "output_text"):
            output = response.output_text
        elif isinstance(response, str):
            output = response
        elif isinstance(response, dict):
            output = str(response)

        if output:
            self._hub.push(
                data=output,
                channel=self._channel,
                encrypted=self._encrypted,
            )
