import argparse
import os
import subprocess
import sys
import time

from dotenv import load_dotenv
from contextrelay import ContextRelay

load_dotenv()

CONTEXTRELAY_URL = "https://contextrelay.your-account.workers.dev"
API_MODEL = "claude-3-haiku-20240307"

PROMPT = (
    "Generate a highly detailed, 100-line JSON configuration for a "
    "global e-commerce microservices architecture. Include services like "
    "auth, inventory, orders, payments, notifications, and search. "
    "For each service include: name, language, database, port, replicas, "
    "dependencies, and environment variables. Output only valid JSON."
)


def generate_via_api() -> str:
    try:
        import anthropic
    except ImportError:
        print("ERROR: anthropic package not installed. Run: pip3 install anthropic")
        sys.exit(1)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set in environment or .env file")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model=API_MODEL,
        max_tokens=4096,
        messages=[{"role": "user", "content": PROMPT}],
    )
    return message.content[0].text


def generate_via_claude_code() -> str:
    # Strip ANTHROPIC_API_KEY so the claude CLI uses subscription auth, not API credits
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
    result = subprocess.run(
        ["claude", "-p", PROMPT],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        env=env,
    )
    if result.returncode != 0:
        print(f"ERROR: claude CLI failed:\n{result.stderr.strip()}")
        sys.exit(1)
    return result.stdout.strip()


def main():
    parser = argparse.ArgumentParser(description="Agent A — Claude generates and pushes to ContextRelay")
    parser.add_argument(
        "--mode",
        choices=["api", "claude-code"],
        default="claude-code",
        help="api: use ANTHROPIC_API_KEY | claude-code: use Claude Code subscription CLI (default)",
    )
    args = parser.parse_args()

    hub = ContextRelay(base_url=CONTEXTRELAY_URL)

    print(f"Agent A (Claude) [{args.mode} mode]: Generating microservices architecture config...")
    t0 = time.time()

    if args.mode == "api":
        json_output = generate_via_api()
    else:
        json_output = generate_via_claude_code()

    generate_time = (time.time() - t0) * 1000
    print(f"Agent A (Claude): Generated {len(json_output)} characters in {generate_time:.2f}ms")

    print("Agent A (Claude): Pushing to ContextRelay edge...")
    t1 = time.time()
    pointer_url = hub.push(json_output)
    push_time = (time.time() - t1) * 1000

    print(f"Agent A (Claude): Pushed in {push_time:.2f}ms")
    print(f"\n--- CONTEXTRELAY POINTER ---")
    print(pointer_url)
    print(f"--------------------------")
    print("\nPass the above URL to Agent B:")
    print(f"  python3 agent_b_mistral.py {pointer_url}")


if __name__ == "__main__":
    main()
