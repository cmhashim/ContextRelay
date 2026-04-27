"""
ContextRelay AgentBridge
======================
Bridges ContextRelay pub/sub channels to a local coding agent (Vibe, Claude Code,
Aider, or any CLI tool running in a tmux pane).

Two sides — same class, same channel config:

  Bridge side (runs next to the agent):
      bridge = AgentBridge.for_tmux(hub, session="vibe")
      bridge.start()          # blocks; dispatches tasks from 'agent-tasks' channel

  Client side (used by the orchestrator / Claude):
      bridge = AgentBridge(hub)
      result = bridge.push_and_wait("implement the EOD pipeline")

Channels:
  task_channel  — orchestrator pushes task URLs here
  done_channel  — bridge pushes result URLs here

Example (full round-trip):
    from contextrelay import ContextRelay, AgentBridge

    hub = ContextRelay("https://your-worker.workers.dev")

    # On the machine running Vibe:
    bridge = AgentBridge.for_tmux(hub, session="vibe")
    bridge.start()  # blocking daemon

    # On the orchestrator / Claude:
    bridge = AgentBridge(hub)
    result = bridge.push_and_wait("refactor auth to use Firebase")
    print(result)
"""

import subprocess
import threading
import time
from typing import Callable, Optional

from .client import ContextRelay

DEFAULT_TASK_CHANNEL = "agent-tasks"
DEFAULT_DONE_CHANNEL = "agent-done"

# Markers the agent is instructed to wrap its outcome summary in.
# The coordinator extracts only this block before pushing to done_channel,
# keeping Claude's returned context lean instead of sending the full terminal.
OUTCOME_START = "=== CC_OUTCOME_START ==="
OUTCOME_END = "=== CC_OUTCOME_END ==="

OUTCOME_INSTRUCTION = f"""

---
After completing the task above, end your response with this exact block:

{OUTCOME_START}
COMPLETED: <bullet list of what was done>
NOT_DONE: <anything skipped, blocked, or errored — or "none">
NOTES: <anything the orchestrating agent should know>
{OUTCOME_END}
"""


def _extract_outcome(raw: str) -> str:
    """Return text between CC_OUTCOME markers, or full raw output as fallback.

    Uses rfind() for the start marker so we always grab Vibe's response,
    not the echoed instruction text (which also contains the markers).
    """
    start = raw.rfind(OUTCOME_START)  # last occurrence = model output, not input echo
    if start == -1:
        return raw
    end = raw.find(OUTCOME_END, start)
    if end == -1:
        return raw
    return raw[start: end + len(OUTCOME_END)].strip()


# ---------------------------------------------------------------------------
# TmuxDispatcher — sends a task to a tmux pane and waits for the agent to idle
# ---------------------------------------------------------------------------

class TmuxDispatcher:
    """
    Sends tasks to a tmux pane (e.g. running Vibe) and blocks until idle.

    Args:
        session:  tmux session name (default: "vibe").
        window:   tmux window index (default: 0).
        timeout:  seconds to wait for the agent to finish (default: 600).

    Making it callable lets it satisfy the ``AgentBridge`` dispatcher protocol:

        dispatcher = TmuxDispatcher(session="vibe")
        bridge = AgentBridge(hub, dispatcher=dispatcher)
    """

    BUSY_MARKERS = [
        "Generating…", "Writing file…", "Reading file…",
        "esc to interrupt", "Synthèse…", "⡆", "⠘", "⠁", "⠋",
    ]
    IDLE_MARKERS = ["│ >", "vibe>", "$ "]

    def __init__(self, session: str = "vibe", window: int = 0, timeout: int = 600):
        self.session = session
        self.window = window
        self.timeout = timeout

    # Public interface -------------------------------------------------------

    def dispatch(self, task_text: str) -> str:
        """Send *task_text* to the tmux pane and return captured output when done."""
        snapshot = self._capture()
        self._send(task_text)
        self._wait_changed(snapshot, startup_timeout=30)
        # Wait for a busy marker before watching for idle — avoids the race
        # where _wait_idle() sees a brief idle state between the task being
        # pasted into the input box and the agent actually starting to process.
        self._wait_busy(startup_timeout=15)
        return self._wait_idle()

    def __call__(self, task_text: str) -> str:
        return self.dispatch(task_text)

    # Internals --------------------------------------------------------------

    def _target(self) -> str:
        return f"{self.session}:{self.window}"

    def _send(self, text: str) -> None:
        subprocess.run(
            ["tmux", "send-keys", "-t", self._target(), text, "Enter"],
            capture_output=True,
            timeout=5,
        )

    def _capture(self) -> str:
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", self._target(), "-p"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout

    def _wait_changed(self, snapshot: str, startup_timeout: int = 30) -> None:
        """Block until the pane content changes from *snapshot* (agent started)."""
        deadline = time.time() + startup_timeout
        while time.time() < deadline:
            time.sleep(2)
            if self._capture() != snapshot:
                return

    def _wait_busy(self, startup_timeout: int = 15) -> None:
        """Block until at least one busy marker appears (agent started processing).
        Times out silently — if the agent is very fast it may already be done."""
        deadline = time.time() + startup_timeout
        while time.time() < deadline:
            output = self._capture()
            if any(m in output for m in self.BUSY_MARKERS):
                return
            time.sleep(1)

    def _wait_idle(self) -> str:
        """Block until no busy marker is present and an idle marker is visible."""
        deadline = time.time() + self.timeout
        last_output = ""
        while time.time() < deadline:
            output = self._capture()
            has_idle = any(m in output for m in self.IDLE_MARKERS)
            is_busy = any(m in output for m in self.BUSY_MARKERS)
            if has_idle and not is_busy:
                return output
            last_output = output
            time.sleep(3)
        return last_output + "\n[AgentBridge] Timed out waiting for agent idle"


# ---------------------------------------------------------------------------
# AgentBridge — the pub/sub bridge between ContextRelay channels and the agent
# ---------------------------------------------------------------------------

class AgentBridge:
    """
    Connects ContextRelay pub/sub channels to a local agent via a dispatcher.

    Args:
        hub:           A :class:`ContextRelay` client instance.
        task_channel:  Channel name the bridge listens on for incoming tasks.
        done_channel:  Channel name the bridge publishes results to.
        dispatcher:    Callable ``(task_text: str) -> result_text: str``.
                       Defaults to :class:`TmuxDispatcher` with session="vibe".
    """

    def __init__(
        self,
        hub: ContextRelay,
        task_channel: str = DEFAULT_TASK_CHANNEL,
        done_channel: str = DEFAULT_DONE_CHANNEL,
        dispatcher: Optional[Callable[[str], str]] = None,
    ):
        self.hub = hub
        self.task_channel = task_channel
        self.done_channel = done_channel
        self._dispatcher = dispatcher or TmuxDispatcher()

    # Factory ----------------------------------------------------------------

    @classmethod
    def for_tmux(
        cls,
        hub: ContextRelay,
        session: str = "vibe",
        window: int = 0,
        task_channel: str = DEFAULT_TASK_CHANNEL,
        done_channel: str = DEFAULT_DONE_CHANNEL,
        timeout: int = 600,
    ) -> "AgentBridge":
        """
        Convenience factory: returns an ``AgentBridge`` pre-wired to a tmux
        session running Vibe (or any interactive coding agent).

        Example::

            bridge = AgentBridge.for_tmux(hub, session="vibe")
            bridge.start()
        """
        return cls(
            hub=hub,
            task_channel=task_channel,
            done_channel=done_channel,
            dispatcher=TmuxDispatcher(session=session, window=window, timeout=timeout),
        )

    # Bridge side (daemon) ---------------------------------------------------

    def start(self) -> None:
        """
        Subscribe to ``task_channel`` and process tasks forever.

        Each task runs in its own daemon thread so the WebSocket loop stays
        alive even if the dispatcher takes a long time.

        Blocks until KeyboardInterrupt. Intended to be the last call in a
        ``__main__`` block or a systemd/tmux-managed daemon.
        """
        print(
            f"[AgentBridge] listening on '{self.task_channel}' "
            f"→ results to '{self.done_channel}'",
            flush=True,
        )
        self.hub.subscribe(self.task_channel, callback=self._handle_task_url)

    def _handle_task_url(self, task_url: str) -> None:
        t = threading.Thread(
            target=self._process_task, args=(task_url,), daemon=True
        )
        t.start()

    def _process_task(self, task_url: str) -> None:
        print(f"[AgentBridge] task received: {task_url}", flush=True)
        try:
            task_text = self.hub.pull(task_url)
        except Exception as e:
            print(f"[AgentBridge] failed to pull task: {e}", flush=True)
            return

        task_with_instruction = task_text + OUTCOME_INSTRUCTION
        print(
            f"[AgentBridge] dispatching ({len(task_with_instruction)} chars) to agent",
            flush=True,
        )
        try:
            raw = self._dispatcher(task_with_instruction)
            result = _extract_outcome(raw)
            print(
                f"[AgentBridge] outcome extracted ({len(result)} chars, "
                f"{'marker found' if OUTCOME_START in raw else 'fallback: full output'})",
                flush=True,
            )
        except Exception as e:
            result = f"[AgentBridge] dispatcher error: {e}"

        try:
            result_url = self.hub.push(
                result,
                channel=self.done_channel,
                metadata={"summary": result[:120]},
            )
            print(f"[AgentBridge] result pushed: {result_url}", flush=True)
        except Exception as e:
            print(f"[AgentBridge] failed to push result: {e}", flush=True)

    # Client side (orchestrator) ---------------------------------------------

    def push_and_wait(self, task: str, timeout: int = 600) -> str:
        """
        Push a task to ``task_channel`` and block until the result arrives
        on ``done_channel``.

        Subscribes to ``done_channel`` *before* pushing to avoid the race
        condition where the result arrives before the subscriber connects.

        Args:
            task:    The full task text to dispatch.
            timeout: Seconds to wait before giving up (default: 600).

        Returns:
            The result text captured from the agent, or a timeout message.

        Example::

            bridge = AgentBridge(hub)
            result = bridge.push_and_wait("add Firebase Auth to the login page")
            print(result)
        """
        result_holder: list = []
        ready = threading.Event()

        def on_done(url: str) -> None:
            try:
                data = self.hub.pull(url)
                result_holder.append(data)
            except Exception as e:
                result_holder.append(f"[AgentBridge] error pulling result: {e}")
            ready.set()

        sub_thread = threading.Thread(
            target=self.hub.subscribe,
            args=(self.done_channel, on_done),
            daemon=True,
        )
        sub_thread.start()
        time.sleep(1)  # let the WebSocket handshake complete before pushing

        task_url = self.hub.push(
            task,
            channel=self.task_channel,
            metadata={"summary": task[:80]},
        )
        print(f"[AgentBridge] task pushed → {task_url}", flush=True)
        print(
            f"[AgentBridge] waiting for result on '{self.done_channel}'…",
            flush=True,
        )

        if not ready.wait(timeout=timeout):
            return f"[AgentBridge] timeout after {timeout}s — no result received"

        return result_holder[0] if result_holder else "[AgentBridge] empty result"
