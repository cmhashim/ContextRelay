"""
ContextRelay — Zero-friction shared memory for multi-agent AI systems.

Quickstart:
    from contextrelay import ContextRelay

    hub = ContextRelay("https://your-worker.workers.dev")
    url = hub.push(large_payload)   # → "https://.../pull/<uuid>"
    data = hub.pull(url)            # → original payload

AgentBridge — dispatch coding tasks to a local agent (Vibe, Claude Code, etc.):

    # Bridge side (runs next to the agent):
    from contextrelay import ContextRelay, AgentBridge
    bridge = AgentBridge.for_tmux(hub, session="vibe")
    bridge.start()   # blocking daemon

    # Client side (orchestrator / Claude):
    result = AgentBridge(hub).push_and_wait("implement Firebase Auth")

Integrations:
    LangChain:  from contextrelay.integrations import ContextRelayRetriever, ContextRelayCallbackHandler
    CrewAI:    from contextrelay.integrations import ContextRelayPushTool, ContextRelayPullTool
    AutoGen:   from contextrelay.integrations import contextrelay_push, contextrelay_pull, get_autogen_tools

    Install optional dependencies:
        pip install context-relay[langchain]
        pip install context-relay[crewai]
        pip install context-relay[autogen]
"""

from .client import ContextRelay
from .agent_bridge import AgentBridge, TmuxDispatcher

__all__ = ["ContextRelay", "AgentBridge", "TmuxDispatcher"]
__version__ = "0.2.0"
