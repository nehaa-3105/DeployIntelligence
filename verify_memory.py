"""
verify_memory.py — throwaway end-to-end verification for the memory layer.

Proves that a retained deployment record can be recalled from Hindsight.
Not a test suite — run once, read the output, discard.

Usage:
    py -3 verify_memory.py

Requirements:
    .env must contain HINDSIGHT_API_KEY and GEMINI_API_KEY.
    Run `py -3 -m pip install -r requirements.txt` first if not installed.
"""

import time
import json

# ── 1. Bootstrap ────────────────────────────────────────────────────────────
print("=" * 60)
print("  Deployment Memory — Hindsight layer verification")
print("=" * 60)

from src.memory import ensure_bank_exists, store_deployment, retrieve_candidates, close
from src.config import settings

print(f"\n[config] bank_id  : {settings.hindsight_bank_id}")
print(f"[config] base_url : {settings.hindsight_base_url}")

# ── 2. Ensure bank ───────────────────────────────────────────────────────────
print("\n[1/4] Creating / confirming memory bank...")
ensure_bank_exists()
print("      OK — bank ready.")

# ── 3. Retain ────────────────────────────────────────────────────────────────
print("\n[2/4] Retaining sample deployment record (deployment #184)...")
store_deployment(
    deployment_id="184",
    service="payment-service",
    migration_type="schema",
    connection_pool_change=True,
    outcome="incident",
    root_cause="connection pool exhaustion under post-migration traffic spike",
    resolution="staged rollout with connection pool size monitoring",
    recovery_time_minutes=18,
    extra_notes="Incident occurred 4 minutes after deployment; pool limit hit at peak checkout traffic.",
)
print("      OK — retain call completed.")

# ── 4. Wait for async processing ────────────────────────────────────────────
WAIT_SECONDS = 6
print(f"\n[3/4] Waiting {WAIT_SECONDS}s for Hindsight to process retained content...")
for i in range(WAIT_SECONDS, 0, -1):
    print(f"      {i}...", end="\r")
    time.sleep(1)
print("      Done waiting.        ")

# ── 5. Recall ────────────────────────────────────────────────────────────────
QUERY = "payment-service schema migration connection pool incident"
print(f"\n[4/4] Recalling with query: '{QUERY}'")
memories = retrieve_candidates(query=QUERY, limit=5)

# ── 6. Report ────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print(f"  RECALL RESULTS  ({len(memories)} memory objects returned)")
print("=" * 60)

if not memories:
    print("\n  ⚠  No memories returned.")
    print("  This can mean:")
    print("    - Hindsight is still processing (try increasing WAIT_SECONDS)")
    print("    - The bank is empty (check Hindsight Cloud dashboard)")
    print("    - The query did not match extracted facts")
else:
    for i, mem in enumerate(memories):
        print(f"\n  [{i}] ──────────────────────────────────────")
        print(f"  id          : {mem['id']}")
        print(f"  type        : {mem['type']}")
        print(f"  text        : {mem['text']}")
        print(f"  entities    : {mem['entities']}")
        print(f"  context     : {mem['context']}")
        print(f"  mentioned_at: {mem['mentioned_at']}")

    # Check whether the retained content is reflected in any result
    found = any("184" in mem["text"] or "payment-service" in mem["text"] for mem in memories)
    print("\n" + "=" * 60)
    if found:
        print("  ✓  PASS — recalled at least one memory mentioning deployment")
        print("            #184 / payment-service. Retain→recall pipeline works.")
    else:
        print("  ~  Memories returned but none mention #184 or payment-service.")
        print("     Hindsight may have extracted different facts from the content.")
        print("     Review the 'text' fields above — if they describe the retained")
        print("     deployment in any form, the pipeline is working correctly.")
    print("=" * 60)

# ── 7. Inspect metadata round-trip ──────────────────────────────────────────
print("\n[Bonus] Checking whether metadata round-trips on recall results...")
has_metadata = any(
    mem.get("metadata") or mem.get("score") for mem in memories
)
if has_metadata:
    print("  metadata / score fields present on at least one result.")
    print("  Full first result:")
    print(json.dumps(memories[0], indent=4, default=str))
else:
    print("  No 'metadata' or 'score' fields found on recall results.")
    print("  → Confirmed: metadata does NOT round-trip via recall.")
    print("    Structured filtering must rely on text content, not metadata.")

close()
print("\n[done] Client closed.")
