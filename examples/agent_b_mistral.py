import os
import sys
import time

from dotenv import load_dotenv
from mistralai import Mistral
from contextrelay import ContextRelay

load_dotenv()

MODEL = "mistral-small-latest"

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 agent_b_mistral.py <contextrelay-url>")
        sys.exit(1)

    pointer_url = sys.argv[1]

    api_key = os.environ.get("MISTRAL_API_KEY")
    if not api_key:
        print("ERROR: MISTRAL_API_KEY not set in environment or .env file")
        sys.exit(1)

    hub = ContextRelay(base_url="https://contextrelay.your-account.workers.dev")

    print(f"Agent B (Mistral): Pulling context from ContextRelay...")
    t0 = time.time()
    downloaded_data = hub.pull(pointer_url)
    pull_time = (time.time() - t0) * 1000

    print(f"Agent B (Mistral): Pulled {len(downloaded_data)} characters in {pull_time:.2f}ms")

    client = Mistral(api_key=api_key)

    print("Agent B (Mistral): Analysing architecture...")
    t1 = time.time()

    response = client.chat.complete(
        model=MODEL,
        messages=[
            {
                "role": "user",
                "content": (
                    "Read this downloaded JSON architecture and give me a 3-bullet point "
                    "summary of the databases being used:\n\n"
                    f"{downloaded_data}"
                ),
            }
        ],
    )

    analyse_time = (time.time() - t1) * 1000
    summary = response.choices[0].message.content

    print(f"Agent B (Mistral): Analysis complete in {analyse_time:.2f}ms\n")
    print("--- MISTRAL SUMMARY ---")
    print(summary)
    print("-----------------------")

if __name__ == "__main__":
    main()
