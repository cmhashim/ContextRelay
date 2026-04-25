"""
ContextRelay Phase 3 demo — WebSocket pub/sub signaling.

Agent B subscribes to a channel; Agent A pushes context with that channel
as a tag; Agent B gets the pointer URL over a WebSocket in milliseconds.
No polling, no handoff wiring.

Run as two separate processes:

    # Terminal 1 — Agent B, the subscriber (blocks forever):
    python3 examples/pubsub_demo.py subscribe my-channel

    # Terminal 2 — Agent A, the producer:
    python3 examples/pubsub_demo.py push my-channel "Hello from Agent A"

Or run the end-to-end self-test in a single process:

    python3 examples/pubsub_demo.py selftest
"""

import sys
import threading
import time
import queue

from contextrelay import ContextRelay

WORKER_URL = "https://contextrelay.your-account.workers.dev"


def cmd_subscribe(channel: str) -> None:
    hub = ContextRelay(WORKER_URL)
    print(f"[subscriber] listening on channel={channel!r}  (Ctrl-C to stop)")

    def on_url(url: str):
        payload = hub.pull(url)
        print(f"[subscriber] got pointer → {url}")
        print(f"[subscriber] pulled {len(payload)} chars: {payload[:80]}...")

    hub.subscribe(channel, on_url)


def cmd_push(channel: str, text: str) -> None:
    hub = ContextRelay(WORKER_URL)
    url = hub.push(text, channel=channel)
    print(f"[producer] pushed to channel={channel!r} → {url}")


def cmd_selftest() -> None:
    hub = ContextRelay(WORKER_URL)
    channel = f"selftest-{int(time.time())}"
    inbox: "queue.Queue[str]" = queue.Queue()

    t = threading.Thread(
        target=hub.subscribe, args=(channel, inbox.put), daemon=True
    )
    t.start()
    time.sleep(2)  # let the WebSocket handshake complete

    payload = "the quick brown fox " * 20
    sent_url = hub.push(payload, channel=channel)
    print(f"[selftest] produced → {sent_url}")

    try:
        got_url = inbox.get(timeout=10)
    except queue.Empty:
        print("[selftest] FAIL — callback did not fire within 10s")
        sys.exit(1)

    print(f"[selftest] subscriber received → {got_url}")
    assert got_url == sent_url, "URL mismatch"
    assert hub.pull(got_url) == payload, "payload integrity failed"
    print("[selftest] OK — URL match + payload integrity verified")


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    cmd = sys.argv[1]
    if cmd == "subscribe" and len(sys.argv) == 3:
        cmd_subscribe(sys.argv[2])
    elif cmd == "push" and len(sys.argv) == 4:
        cmd_push(sys.argv[2], sys.argv[3])
    elif cmd == "selftest":
        cmd_selftest()
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
