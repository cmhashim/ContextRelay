"""
ContextRelay integrations with popular AI frameworks.

Optional dependencies - install with:
    pip install context-relay[langchain]   # LangChain integration
    pip install context-relay[crewai]      # CrewAI integration
    pip install context-relay[autogen]     # AutoGen integration

All integrations are optional and only require their respective
frameworks to be installed when used.
"""

# Lazy imports with helpful error messages

try:
    from .langchain import ContextRelayRetriever, ContextRelayCallbackHandler
except ImportError:
    def _raise_langchain_error():
        raise ImportError(
            "The 'langchain' package is not installed. "
            "Install it with: pip install context-relay[langchain]"
        )
    ContextRelayRetriever = _raise_langchain_error
    ContextRelayCallbackHandler = _raise_langchain_error


try:
    from .crewai import ContextRelayPushTool, ContextRelayPullTool
except ImportError:
    def _raise_crewai_error():
        raise ImportError(
            "The 'crewai' package is not installed. "
            "Install it with: pip install context-relay[crewai]"
        )
    ContextRelayPushTool = _raise_crewai_error
    ContextRelayPullTool = _raise_crewai_error


try:
    from .autogen import (
        contextrelay_push,
        contextrelay_pull,
        get_autogen_tools,
    )
except ImportError:
    def _raise_autogen_error():
        raise ImportError(
            "The 'autogen-agentchat' package is not installed. "
            "Install it with: pip install context-relay[autogen]"
        )
    contextrelay_push = _raise_autogen_error
    contextrelay_pull = _raise_autogen_error
    get_autogen_tools = _raise_autogen_error


__all__ = [
    # LangChain
    "ContextRelayRetriever",
    "ContextRelayCallbackHandler",
    # CrewAI
    "ContextRelayPushTool",
    "ContextRelayPullTool",
    # AutoGen
    "contextrelay_push",
    "contextrelay_pull",
    "get_autogen_tools",
]
