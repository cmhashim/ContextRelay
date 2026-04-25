import time

from contextrelay import ContextRelay

# For the MVP, assume your Cloudflare worker is running locally on port 8787
hub = ContextRelay("https://contextrelay.your-account.workers.dev")

# --- AGENT A (Claude) ---
print("Agent A: Generating massive architecture spec...")
huge_spec = "System Architecture v1.0\n" + ("This is a heavy module. \n" * 5000)

start_push = time.time()
pointer_url = hub.push(huge_spec)
push_time = (time.time() - start_push) * 1000

print(f"Agent A: Context offloaded in {push_time:.2f}ms")
print(f"Agent A: Handing off pointer to Agent B -> {pointer_url}\n")


# --- AGENT B (Mistral) ---
print("Agent B: Received pointer. Fetching context...")

start_pull = time.time()
retrieved_spec = hub.pull(pointer_url)
pull_time = (time.time() - start_pull) * 1000

print(f"Agent B: Context loaded in {pull_time:.2f}ms")
print(f"Agent B: Successfully retrieved {len(retrieved_spec)} characters.")
