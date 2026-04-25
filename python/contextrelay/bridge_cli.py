"""
contextrelay-bridge CLI
=====================
Manages the AgentBridge daemon and dispatches one-shot tasks.

Commands:
    start   — Start the bridge daemon (blocking).
    send    — Push a task and optionally wait for the result.

Examples:
    # Start the bridge next to a Vibe tmux session:
    contextrelay-bridge start --tmux vibe --task-channel agent-tasks --done-channel agent-done

    # From the orchestrator: push a task and wait for the result:
    contextrelay-bridge send "implement Firebase Auth" --wait

    # Fire-and-forget (don't wait):
    contextrelay-bridge send "run the test suite"
"""

import argparse
import os
import sys

PYTHONPATH = os.environ.get("CONTEXTRELAY_PYTHONPATH", "")
if PYTHONPATH and PYTHONPATH not in sys.path:
    sys.path.insert(0, PYTHONPATH)

from .client import ContextRelay  # noqa: E402
from .agent_bridge import AgentBridge, TmuxDispatcher  # noqa: E402

CONTEXTRELAY_URL = os.environ.get(
    "CONTEXTRELAY_URL", "https://contextrelay.your-account.workers.dev"
)


def cmd_start(args: argparse.Namespace) -> None:
    """Start the AgentBridge daemon (blocking)."""
    hub = ContextRelay(CONTEXTRELAY_URL)

    if args.tmux:
        bridge = AgentBridge.for_tmux(
            hub,
            session=args.tmux,
            window=args.window,
            task_channel=args.task_channel,
            done_channel=args.done_channel,
            timeout=args.timeout,
        )
        print(
            f"[bridge] tmux dispatcher → session='{args.tmux}' window={args.window}",
            flush=True,
        )
    else:
        # Generic dispatcher: run each task as a subprocess and capture stdout
        import subprocess as _sp

        def shell_dispatcher(task_text: str) -> str:
            result = _sp.run(
                args.exec,
                input=task_text,
                capture_output=True,
                text=True,
                timeout=args.timeout,
                shell=True,
            )
            return result.stdout + result.stderr

        bridge = AgentBridge(
            hub,
            task_channel=args.task_channel,
            done_channel=args.done_channel,
            dispatcher=shell_dispatcher,
        )

    bridge.start()


def cmd_send(args: argparse.Namespace) -> None:
    """Push a task to the bridge, optionally blocking for the result."""
    hub = ContextRelay(CONTEXTRELAY_URL)
    bridge = AgentBridge(
        hub,
        task_channel=args.task_channel,
        done_channel=args.done_channel,
    )

    task = " ".join(args.task)

    if args.wait:
        result = bridge.push_and_wait(task, timeout=args.timeout)
        # Strip Vibe box-drawing UI chars from bottom of output
        lines = result.split("\n")
        cutoff = next(
            (
                i
                for i, line in enumerate(lines)
                if "─" * 10 in line or "┌" in line
            ),
            len(lines),
        )
        print("\n".join(lines[:cutoff]).strip())
    else:
        task_url = hub.push(
            task,
            channel=args.task_channel,
            metadata={"summary": task[:80]},
        )
        print(f"[bridge] task pushed → {task_url}")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="contextrelay-bridge",
        description="ContextRelay AgentBridge — dispatch coding tasks to a local agent via pub/sub",
    )
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument(
        "--task-channel",
        default="agent-tasks",
        metavar="CHANNEL",
        help="Channel the bridge listens on (default: agent-tasks)",
    )
    shared.add_argument(
        "--done-channel",
        default="agent-done",
        metavar="CHANNEL",
        help="Channel results are published to (default: agent-done)",
    )
    shared.add_argument(
        "--timeout",
        type=int,
        default=600,
        metavar="SECONDS",
        help="Seconds to wait for agent completion (default: 600)",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    # start subcommand
    p_start = sub.add_parser(
        "start",
        parents=[shared],
        help="Start the bridge daemon (blocking)",
    )
    disp = p_start.add_mutually_exclusive_group()
    disp.add_argument(
        "--tmux",
        metavar="SESSION",
        help="tmux session name running Vibe/Claude Code (e.g. 'vibe')",
    )
    disp.add_argument(
        "--exec",
        metavar="CMD",
        help="Shell command to dispatch tasks to (receives task on stdin)",
    )
    p_start.add_argument(
        "--window",
        type=int,
        default=0,
        metavar="N",
        help="tmux window index (default: 0)",
    )

    # send subcommand
    p_send = sub.add_parser(
        "send",
        parents=[shared],
        help="Push a task to the running bridge",
    )
    p_send.add_argument(
        "task",
        nargs="+",
        help="Task description (quoted string or multiple words)",
    )
    p_send.add_argument(
        "--wait",
        action="store_true",
        help="Block until the agent finishes and print the result",
    )

    args = parser.parse_args()

    if args.command == "start":
        cmd_start(args)
    elif args.command == "send":
        cmd_send(args)


if __name__ == "__main__":
    main()
