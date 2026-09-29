"""
Seed data ingestion for Deployment Memory.

Contains the synthetic historical deployment dataset inline and retains
each record into Hindsight memory via the existing Phase 2 store_deployment()
function in memory.py. Also writes every successfully retained record to the
JSON ledger (src/store.py) with retained_in_hindsight=True.

Run once before demo to populate the memory bank:
    python -m src.ingestion

Reset the bank and ledger, then re-seed from scratch:
    python -m src.ingestion --reset

--reset:
    1. Deletes the Hindsight bank (all memories erased server-side).
    2. Clears the local JSON ledger.
    3. Recreates the Hindsight bank (idempotent).
    4. Seeds all 10 records.

Normal run (no --reset):
    Skips any deployment_id already present in the local ledger.
    Only retains and records genuinely new entries.

Dataset: 10 records across 3 services
    Incidents  (3): #184, #249, #271
    Safe       (7): #201, #215, #237, #258, #263, #278, #285
"""

from __future__ import annotations

import sys
import time

# ---------------------------------------------------------------------------
# Canonical 10-record seed dataset
# Fields: deployment_id, service, migration_type, connection_pool_change,
#         change_type, dependencies_changed, timestamp,
#         outcome, root_cause, resolution, recovery_time_minutes, extra_notes
# Do NOT change root_cause, resolution, or extra_notes.
# ---------------------------------------------------------------------------

SEED_RECORDS: list[dict] = [
    # ── payment-service ──────────────────────────────────────────────────────
    {
        "deployment_id": "184",
        "service": "payment-service",
        "migration_type": "schema",
        "connection_pool_change": True,
        "change_type": "infra",
        "dependencies_changed": True,
        "timestamp": "2026-03-11T14:00:00Z",
        "outcome": "incident",
        "root_cause": "connection pool exhaustion under post-migration traffic spike",
        "resolution": "staged rollout with connection pool size monitoring and pre-scaled headroom",
        "recovery_time_minutes": 18,
        "extra_notes": (
            "Pool limit hit at peak checkout traffic 4 minutes post-deploy. "
            "Sev-2 incident."
        ),
    },
    {
        "deployment_id": "201",
        "service": "payment-service",
        "migration_type": "schema",
        "connection_pool_change": False,
        "change_type": "infra",
        "dependencies_changed": True,
        "timestamp": "2026-03-24T10:00:00Z",
        "outcome": "success",
        "root_cause": "",
        "resolution": "",
        "recovery_time_minutes": 0,
        "extra_notes": (
            "Same service and migration type as #184 but no pool change. "
            "Clean deploy with zero incidents."
        ),
    },
    {
        "deployment_id": "215",
        "service": "payment-service",
        "migration_type": "read-replica",
        "connection_pool_change": False,
        "change_type": "config",
        "dependencies_changed": False,
        "timestamp": "2026-04-08T09:00:00Z",
        "outcome": "success",
        "root_cause": "",
        "resolution": "",
        "recovery_time_minutes": 0,
        "extra_notes": (
            "Read-replica promotion for reporting queries. "
            "No pool change required. Completed in maintenance window."
        ),
    },
    # ── inventory-service ────────────────────────────────────────────────────
    {
        "deployment_id": "237",
        "service": "inventory-service",
        "migration_type": "config-only",
        "connection_pool_change": False,
        "change_type": "config",
        "dependencies_changed": False,
        "timestamp": "2026-04-22T09:00:00Z",
        "outcome": "success",
        "root_cause": "",
        "resolution": "",
        "recovery_time_minutes": 0,
        "extra_notes": (
            "Feature flag rollout for new warehouse routing logic. "
            "No infrastructure change."
        ),
    },
    {
        "deployment_id": "249",
        "service": "inventory-service",
        "migration_type": "schema",
        "connection_pool_change": True,
        "change_type": "schema",
        "dependencies_changed": True,
        "timestamp": "2026-05-13T11:00:00Z",
        "outcome": "incident",
        "root_cause": "deadlock on inventory_items table during concurrent write migration",
        "resolution": (
            "rolled back migration, re-applied with row-level locking "
            "and off-peak scheduling"
        ),
        "recovery_time_minutes": 34,
        "extra_notes": (
            "Concurrent writes from order-fulfillment service caused table-level locks. "
            "Sev-2 incident."
        ),
    },
    {
        "deployment_id": "258",
        "service": "inventory-service",
        "migration_type": "schema",
        "connection_pool_change": False,
        "change_type": "schema",
        "dependencies_changed": True,
        "timestamp": "2026-05-27T11:00:00Z",
        "outcome": "success",
        "root_cause": "",
        "resolution": "",
        "recovery_time_minutes": 0,
        "extra_notes": (
            "Same schema migration as #249 re-applied with row-level locking fix "
            "and maintenance window. Clean."
        ),
    },
    # ── auth-service ─────────────────────────────────────────────────────────
    {
        "deployment_id": "263",
        "service": "auth-service",
        "migration_type": "code-only",
        "connection_pool_change": False,
        "change_type": "code",
        "dependencies_changed": False,
        "timestamp": "2026-06-10T13:00:00Z",
        "outcome": "success",
        "root_cause": "",
        "resolution": "",
        "recovery_time_minutes": 0,
        "extra_notes": (
            "JWT expiry policy update. Canary deployed to 10% traffic first, "
            "then full rollout. No issues."
        ),
    },
    {
        "deployment_id": "271",
        "service": "auth-service",
        "migration_type": "schema",
        "connection_pool_change": True,
        "change_type": "schema",
        "dependencies_changed": False,
        "timestamp": "2026-06-24T15:00:00Z",
        "outcome": "incident",
        "root_cause": (
            "connection pool starvation during token-refresh storm "
            "after schema migration"
        ),
        "resolution": (
            "increased pool size from 20 to 50 connections, "
            "added circuit breaker on token endpoint"
        ),
        "recovery_time_minutes": 22,
        "extra_notes": (
            "High-frequency token refresh requests from mobile clients "
            "overwhelmed the post-migration pool. Sev-2."
        ),
    },
    {
        "deployment_id": "278",
        "service": "auth-service",
        "migration_type": "schema",
        "connection_pool_change": False,
        "change_type": "schema",
        "dependencies_changed": False,
        "timestamp": "2026-07-15T10:00:00Z",
        "outcome": "success",
        "root_cause": "",
        "resolution": "",
        "recovery_time_minutes": 0,
        "extra_notes": (
            "Follow-up schema migration without pool change. "
            "Pre-scaled pool from #271 fix already in place. Clean."
        ),
    },
    # ── payment-service (continued) ──────────────────────────────────────────
    {
        "deployment_id": "285",
        "service": "payment-service",
        "migration_type": "infra-only",
        "connection_pool_change": True,
        "change_type": "infra",
        "dependencies_changed": False,
        "timestamp": "2026-08-05T09:00:00Z",
        "outcome": "success",
        "root_cause": "",
        "resolution": "",
        "recovery_time_minutes": 0,
        "extra_notes": (
            "Deliberate pool resize to new RDS instance class. "
            "Staged rollout, monitored for 30 minutes. Clean."
        ),
    },
]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _ledger_record(rec: dict, retained: bool) -> dict:
    """Build a canonical ledger record from a seed dict."""
    from datetime import datetime, timezone
    return {
        "deployment_id": rec["deployment_id"],
        "service": rec["service"],
        "migration_type": rec["migration_type"],
        "connection_pool_change": rec["connection_pool_change"],
        "change_type": rec.get("change_type", ""),
        "dependencies_changed": rec.get("dependencies_changed"),
        "timestamp": rec.get("timestamp", ""),
        "outcome": rec["outcome"],
        "root_cause": rec.get("root_cause", ""),
        "resolution": rec.get("resolution", ""),
        "recovery_time_minutes": rec.get("recovery_time_minutes", 0),
        "notes": rec.get("extra_notes", ""),
        "source": "seed",
        "retained_in_hindsight": retained,
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def _reset_bank_and_ledger() -> None:
    """
    Delete the Hindsight bank, clear the local ledger, recreate the bank.
    Called only when --reset flag is passed.
    """
    from src.memory import _get_client, ensure_bank_exists
    from src.store import clear as ledger_clear
    from src.config import settings

    print("  [reset] Deleting Hindsight bank...")
    client = _get_client()
    try:
        client.delete_bank(bank_id=settings.hindsight_bank_id)
        print("  [reset] Bank deleted.")
    except Exception as exc:
        print(f"  [reset] Bank deletion failed (may not exist): {exc}")

    print("  [reset] Clearing local ledger...")
    ledger_clear()
    print("  [reset] Ledger cleared.")

    # Reset the module-level cache so ensure_bank_exists() creates a fresh bank
    import src.memory as _mem
    _mem._bank_initialised = False

    print("  [reset] Recreating Hindsight bank...")
    ensure_bank_exists()
    print("  [reset] Bank recreated.\n")


# ---------------------------------------------------------------------------
# Ingestion runner
# ---------------------------------------------------------------------------

def run_ingestion(wait_seconds: int = 3, reset: bool = False) -> None:
    """
    Retain seed deployment records into Hindsight and record them in the
    local JSON ledger.

    Normal run (reset=False):
        Skips deployment IDs already present in the ledger.
        Only retains and records genuinely new entries.
        retained_in_hindsight is set to True ONLY after a successful
        Hindsight retain — never before.

    Reset run (reset=True):
        1. Deletes the Hindsight bank.
        2. Clears the local ledger.
        3. Recreates the bank.
        4. Seeds all 10 records.

    Parameters
    ----------
    wait_seconds : int
        Seconds to wait between retain calls to avoid rate-limiting.
    reset : bool
        When True, wipe and re-seed. When False, skip known IDs.
    """
    from src.memory import ensure_bank_exists, store_deployment
    from src.store import get as ledger_get, upsert as ledger_upsert

    print(f"\n{'='*60}")
    print(f"  Deployment Memory — Seed Data Ingestion")
    print(f"{'='*60}")

    if reset:
        _reset_bank_and_ledger()
    else:
        ensure_bank_exists()
        print("  [bank] Memory bank ready.\n")

    total = len(SEED_RECORDS)
    print(f"  Records to process: {total}")
    print(f"  Wait between calls: {wait_seconds}s")
    print()

    succeeded = 0
    skipped = 0
    failed: list[tuple[str, str]] = []

    for i, rec in enumerate(SEED_RECORDS, start=1):
        dep_id = rec["deployment_id"]
        service = rec["service"]
        outcome = rec["outcome"]
        label = "INCIDENT" if outcome == "incident" else "success"

        # Skip if already present in ledger (normal run only)
        if not reset and ledger_get(dep_id) is not None:
            print(f"  [{i:02d}/{total}] #{dep_id:>4}  {service:<22}  SKIP (already in ledger)")
            skipped += 1
            continue

        # Write a NOT-yet-retained placeholder to the ledger first
        # so a crash mid-run doesn't leave the ledger empty for this ID.
        # retained_in_hindsight will be updated to True on success below.
        ledger_upsert(_ledger_record(rec, retained=False))

        try:
            store_deployment(
                deployment_id=dep_id,
                service=service,
                migration_type=rec["migration_type"],
                connection_pool_change=rec["connection_pool_change"],
                outcome=outcome,
                change_type=rec.get("change_type", ""),
                dependencies_changed=rec.get("dependencies_changed"),
                root_cause=rec.get("root_cause", ""),
                resolution=rec.get("resolution", ""),
                recovery_time_minutes=rec.get("recovery_time_minutes", 0),
                extra_notes=rec.get("extra_notes", ""),
            )
            # Hindsight retain succeeded — mark retained in ledger
            ledger_upsert(_ledger_record(rec, retained=True))
            print(f"  [{i:02d}/{total}] #{dep_id:>4}  {service:<22}  {label}  [retained]")
            succeeded += 1
        except Exception as exc:
            # Leave retained_in_hindsight=False in the ledger (already written above)
            print(f"  [{i:02d}/{total}] #{dep_id:>4}  FAILED: {exc}")
            failed.append((dep_id, str(exc)))

        if i < total:
            time.sleep(wait_seconds)

    print()
    print(f"{'='*60}")
    print(f"  RESULT: {succeeded} retained, {skipped} skipped, {len(failed)} failed  (of {total})")
    if failed:
        print(f"  FAILURES:")
        for dep_id, err in failed:
            print(f"    #{dep_id}: {err}")
    else:
        if succeeded > 0:
            print("  All processed records retained successfully.")
        else:
            print("  No new records to ingest.")
    print(f"{'='*60}\n")

    if failed:
        raise RuntimeError(
            f"Ingestion completed with {len(failed)} failure(s). "
            "See output above for details."
        )


def bootstrap_ledger_if_empty() -> None:
    """
    Reconstruct the local ledger from SEED_RECORDS when it is missing or empty.

    Called at API server startup so that Render's ephemeral filesystem is
    always populated with the 10 canonical historical records, even after a
    fresh deploy wipes the disk.

    Rules
    -----
    - Does NOT call Hindsight retain() — the production bank is assumed to
      already contain these memories from the one-time seed run.
    - Does NOT reset or delete the Hindsight bank.
    - Does NOT create duplicate memories in Hindsight.
    - Sets retained_in_hindsight=True on every bootstrapped record, because
      the corresponding memories are already in the production bank.
    - Uses store.seed_from_records() which skips IDs already present, so
      any records written by /feedback after a prior deploy are preserved.
    - Idempotent: if the ledger is non-empty the function returns immediately.
    """
    from src.store import load_all, seed_from_records

    if load_all():
        # Ledger already has records — nothing to do.
        return

    records = [_ledger_record(rec, retained=True) for rec in SEED_RECORDS]
    seed_from_records(records)


if __name__ == "__main__":
    reset_flag = "--reset" in sys.argv
    run_ingestion(reset=reset_flag)
