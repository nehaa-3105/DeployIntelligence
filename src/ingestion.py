"""
Seed data ingestion for Deployment Memory.

Contains the synthetic historical deployment dataset inline and retains
each record into Hindsight memory via the existing Phase 2 store_deployment()
function in memory.py.

Run once before demo to populate the memory bank:
    python -m src.ingestion

Dataset: 10 records across 3 services
    Incidents  (3): #184, #249, #271
    Safe       (7): #201, #215, #237, #258, #263, #278, #285

Ingestion is idempotent in intent — re-running adds duplicate entries,
so the bank should be cleared before re-seeding during development.
"""

from __future__ import annotations

import time

# ---------------------------------------------------------------------------
# Synthetic historical dataset — embedded inline (no external file needed)
# ---------------------------------------------------------------------------

SEED_RECORDS: list[dict] = [
    # ── payment-service ──────────────────────────────────────────────────────
    {
        "deployment_id": "184",
        "service": "payment-service",
        "migration_type": "schema",
        "connection_pool_change": True,
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
# Ingestion runner
# ---------------------------------------------------------------------------

def run_ingestion(wait_seconds: int = 3) -> None:
    """
    Retain all seed deployment records into Hindsight via the existing
    Phase 2 store_deployment() function.

    Parameters
    ----------
    wait_seconds : int
        Seconds to wait between retains to avoid rate-limiting.
        Default 3 keeps the total wall-clock time reasonable for 10 records.
    """
    from src.memory import ensure_bank_exists, store_deployment

    total = len(SEED_RECORDS)

    print(f"\n{'='*60}")
    print(f"  Deployment Memory — Seed Data Ingestion")
    print(f"{'='*60}")
    print(f"\n  Records to ingest : {total}")
    print(f"  Wait between calls: {wait_seconds}s")
    print()

    ensure_bank_exists()
    print("  [bank] Memory bank ready.\n")

    succeeded = 0
    failed: list[tuple[str, str]] = []

    for i, rec in enumerate(SEED_RECORDS, start=1):
        dep_id = rec["deployment_id"]
        service = rec["service"]
        outcome = rec["outcome"]
        label = "INCIDENT" if outcome == "incident" else "success"

        try:
            store_deployment(
                deployment_id=dep_id,
                service=service,
                migration_type=rec["migration_type"],
                connection_pool_change=rec["connection_pool_change"],
                outcome=outcome,
                root_cause=rec.get("root_cause", ""),
                resolution=rec.get("resolution", ""),
                recovery_time_minutes=rec.get("recovery_time_minutes", 0),
                extra_notes=rec.get("extra_notes", ""),
            )
            print(f"  [{i:02d}/{total}] #{dep_id:>4}  {service:<22}  {label}")
            succeeded += 1
        except Exception as exc:
            print(f"  [{i:02d}/{total}] #{dep_id:>4}  FAILED: {exc}")
            failed.append((dep_id, str(exc)))

        # Brief pause — Hindsight retain is async server-side; the pause
        # prevents hammering the API and gives the server processing headroom.
        if i < total:
            time.sleep(wait_seconds)

    print()
    print(f"{'='*60}")
    print(f"  RESULT: {succeeded}/{total} records retained successfully")
    if failed:
        print(f"  FAILURES ({len(failed)}):")
        for dep_id, err in failed:
            print(f"    #{dep_id}: {err}")
    else:
        print("  All records retained. No failures.")
    print(f"{'='*60}\n")

    if failed:
        raise RuntimeError(
            f"Ingestion completed with {len(failed)} failure(s). "
            "See output above for details."
        )


if __name__ == "__main__":
    run_ingestion()
