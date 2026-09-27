"""
Prompt 1 spike: verify Hindsight SDK API surface.

Run with:
    python spike_hindsight.py

Requires .env with HINDSIGHT_API_KEY and HINDSIGHT_BASE_URL set.

Purpose:
  1. Confirm retain works and returns expected fields.
  2. Confirm recall returns a list of raw memory objects (not synthesized).
  3. Inspect the exact shape of each memory object (id, text, type, etc.).
  4. Confirm reflect returns synthesized text + based_on sources.
  5. Confirm list_memories works (needed for frequency counting in matching.py).

This file is scratch/diagnostic only — delete after spike is verified.
"""

import os
import json
import time
from dotenv import load_dotenv

load_dotenv()

BANK_ID = "spike-test-001"


def pp(label: str, obj) -> None:
    """Pretty-print an object for inspection."""
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    if hasattr(obj, "__dict__"):
        print(json.dumps(obj.__dict__, default=str, indent=2))
    elif hasattr(obj, "model_dump"):
        print(json.dumps(obj.model_dump(), default=str, indent=2))
    else:
        print(repr(obj))


def main():
    from hindsight_client import Hindsight

    api_key = os.environ.get("HINDSIGHT_API_KEY")
    base_url = os.environ.get("HINDSIGHT_BASE_URL", "https://api.hindsight.vectorize.io")

    if not api_key:
        raise ValueError("HINDSIGHT_API_KEY not set. Copy .env.example to .env and fill in your key.")

    print(f"Connecting to Hindsight at: {base_url}")
    client = Hindsight(base_url=base_url, api_key=api_key)

    # -----------------------------------------------------------------
    # Step 1: Create / ensure bank exists (idempotent)
    # -----------------------------------------------------------------
    print(f"\n[1] Creating bank: {BANK_ID}")
    bank = client.create_bank(
        bank_id=BANK_ID,
        name="Spike Test Bank",
        background="Temporary bank for API surface verification. Safe to delete.",
    )
    pp("create_bank response", bank)

    # -----------------------------------------------------------------
    # Step 2: Retain — store two structured deployment memory entries
    # -----------------------------------------------------------------
    print("\n[2] Retaining two test memories...")

    retain_a = client.retain(
        bank_id=BANK_ID,
        content=(
            "Deployment #184: service=payment-service, migration_type=schema, "
            "connection_pool_change=True, outcome=incident. "
            "Incident root cause: connection pool exhaustion. "
            "Resolution: staged rollout with pool monitoring. "
            "Recovery time: 18 minutes."
        ),
        metadata={"deployment_id": "184", "service": "payment-service", "outcome": "incident"},
    )
    pp("retain response (deployment #184)", retain_a)

    retain_b = client.retain(
        bank_id=BANK_ID,
        content=(
            "Deployment #201: service=payment-service, migration_type=schema, "
            "connection_pool_change=False, outcome=success. "
            "No incident. Deployment completed cleanly."
        ),
        metadata={"deployment_id": "201", "service": "payment-service", "outcome": "success"},
    )
    pp("retain response (deployment #201)", retain_b)

    # Hindsight processes retains asynchronously — wait before recalling
    print("\n[3] Waiting 5 seconds for async processing...")
    time.sleep(5)

    # -----------------------------------------------------------------
    # Step 3: Recall — inspect exact return shape
    # -----------------------------------------------------------------
    print("\n[4] Recalling: 'payment-service schema migration connection pool incident'")
    recall_result = client.recall(
        bank_id=BANK_ID,
        query="payment-service schema migration connection pool incident",
    )
    pp("FULL recall response object", recall_result)

    print(f"\n  recall_result.results has {len(recall_result.results)} items")
    for i, mem in enumerate(recall_result.results):
        print(f"\n  --- Memory [{i}] ---")
        print(f"  id:           {getattr(mem, 'id', 'N/A')}")
        print(f"  text:         {getattr(mem, 'text', 'N/A')}")
        print(f"  type:         {getattr(mem, 'type', 'N/A')}")
        print(f"  entities:     {getattr(mem, 'entities', 'N/A')}")
        print(f"  context:      {getattr(mem, 'context', 'N/A')}")
        print(f"  mentioned_at: {getattr(mem, 'mentioned_at', 'N/A')}")
        # Check for any score or metadata fields
        for attr in ("score", "relevance_score", "metadata", "tags"):
            if hasattr(mem, attr):
                print(f"  {attr}: {getattr(mem, attr)}")

    # -----------------------------------------------------------------
    # Step 4: Reflect — inspect return shape
    # -----------------------------------------------------------------
    print("\n[5] Reflecting: 'What happened with payment-service schema migrations?'")
    reflect_result = client.reflect(
        bank_id=BANK_ID,
        query="What happened with payment-service schema migrations?",
    )
    pp("FULL reflect response object", reflect_result)
    print(f"\n  reflect_result.text: {getattr(reflect_result, 'text', 'N/A')}")
    print(f"  reflect_result.based_on: {getattr(reflect_result, 'based_on', 'N/A')}")

    # -----------------------------------------------------------------
    # Step 5: list_memories — confirm it works and inspect shape
    # -----------------------------------------------------------------
    print("\n[6] list_memories (limit=10)")
    list_result = client.list_memories(bank_id=BANK_ID, limit=10)
    pp("FULL list_memories response", list_result)
    print(f"\n  total memories in bank: {getattr(list_result, 'total', 'N/A')}")
    if hasattr(list_result, "items"):
        for i, item in enumerate(list_result.items):
            print(f"  item[{i}]: {repr(item)[:120]}")

    # -----------------------------------------------------------------
    # Done
    # -----------------------------------------------------------------
    print("\n\n[SPIKE COMPLETE]")
    print("Review the output above and check:")
    print("  - recall returns raw memory objects (not synthesized text)")
    print("  - reflect returns .text (synthesized) + .based_on (source memories)")
    print("  - memory objects have: id, text, type, entities, mentioned_at")
    print("  - list_memories returns .total + .items for iteration")
    print("\nNOTE: Bank 'spike-test-001' was created and should be deleted manually")
    print("      from the Hindsight dashboard after verification.")

    client.close()


if __name__ == "__main__":
    main()
