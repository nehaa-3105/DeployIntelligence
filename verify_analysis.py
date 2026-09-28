"""
verify_analysis.py — Phase 4 throwaway verification script.

Runs BASELINE and MEMORY-INFORMED analysis against the #184 / #297 demo
scenario and asserts the success conditions defined in the Phase 4 spec.

Demo dataset
------------
  #184  payment-service, schema, pool=True, infra, deps=True → incident
        root cause : connection pool exhaustion
        resolution : staged rollout + pool monitoring

  #201  payment-service, schema, pool=False, infra, deps=True → success
        (partial match used in Phase 3; included in historical_records so
        matching exercises the full pipeline)

  #237  inventory-service, config-only, pool=False, config, deps=False → success
        (structurally unrelated; must NOT appear as relevant evidence)

  #297  payment-service, schema, pool=True, infra, deps=True → pending
        (the proposed deployment being analysed)

Success conditions asserted
---------------------------
  BASELINE:
    B1. mode == "baseline"
    B2. relevant_deployments is empty
    B3. cited_deployment_ids is empty
    B4. evidence is empty
    B5. risk_assessment is one of {"low", "medium", "high"}
    B6. summary is non-empty
    B7. recommendation is non-empty

  MEMORY-INFORMED:
    M1. mode == "memory"
    M2. "#184" appears in cited_deployment_ids
    M3. "#184" appears in relevant_deployments (by deployment_id)
    M4. "#237" does NOT appear in cited_deployment_ids
    M5. "#237" does NOT appear in relevant_deployments
    M6. summary or evidence mentions "184" (explicit citation)
    M7. summary or evidence mentions root cause or resolution keyword
        ("pool" / "exhaustion" / "staged" / "monitoring")
    M8. evidence is non-empty
    M9. risk_assessment is one of {"low", "medium", "high"}

  CONTRAST:
    C1. The two outputs differ (BASELINE ≠ MEMORY-INFORMED)

Usage
-----
    py -3 verify_analysis.py

Requirements
------------
    .env with GEMINI_API_KEY (and HINDSIGHT_API_KEY for MEMORY mode).
    Run verify_matching.py first (or any script that seeds #184 in
    Hindsight) so the memory bank has entries for #184 before this script
    runs its MEMORY-INFORMED analysis.
"""

import sys
import time

# ── Bootstrap ────────────────────────────────────────────────────────────────
print("=" * 70)
print("  Phase 4 — Deployment Analysis Verification")
print("  BASELINE vs MEMORY-INFORMED: #297 proposed against #184/#201/#237")
print("=" * 70)

from src.models import AnalysisMode, Deployment
from src.analysis import analyze_deployment
from src.memory import ensure_bank_exists, store_deployment

# ── Demo dataset ──────────────────────────────────────────────────────────────

HISTORICAL = [
    Deployment(
        deployment_id="184",
        service="payment-service",
        migration_type="schema",
        connection_pool_change=True,
        change_type="infra",
        timestamp="2024-01-15T14:00:00Z",
        outcome="incident",
        dependencies_changed=True,
        notes="Pool exhaustion under post-migration traffic spike. 18-min incident.",
    ),
    Deployment(
        deployment_id="201",
        service="payment-service",
        migration_type="schema",
        connection_pool_change=False,
        change_type="infra",
        timestamp="2024-02-10T10:00:00Z",
        outcome="success",
        dependencies_changed=True,
        notes="Same service and migration type as #184 but no pool change. Clean deploy.",
    ),
    Deployment(
        deployment_id="237",
        service="inventory-service",
        migration_type="config-only",
        connection_pool_change=False,
        change_type="config",
        timestamp="2024-03-05T09:00:00Z",
        outcome="success",
        dependencies_changed=False,
        notes="Config-only change on a completely different service.",
    ),
]

PROPOSED = Deployment(
    deployment_id="297",
    service="payment-service",
    migration_type="schema",
    connection_pool_change=True,
    change_type="infra",
    timestamp="2024-09-27T16:00:00Z",
    outcome="pending",
    dependencies_changed=True,
    notes="New payment-service schema migration with pool change.",
)

# ── Seed Hindsight so MEMORY mode has evidence to retrieve ────────────────────
print("\n[PRE-FLIGHT] Seeding Hindsight bank with #184 and #201...")
try:
    ensure_bank_exists()
    store_deployment(
        deployment_id="184",
        service="payment-service",
        migration_type="schema",
        connection_pool_change=True,
        outcome="incident",
        root_cause="connection pool exhaustion under post-migration traffic spike",
        resolution="staged rollout with connection pool size monitoring",
        recovery_time_minutes=18,
        extra_notes="Pool limit hit at peak checkout traffic 4 minutes post-deploy.",
    )
    store_deployment(
        deployment_id="201",
        service="payment-service",
        migration_type="schema",
        connection_pool_change=False,
        outcome="success",
        extra_notes="Same service and migration type as #184 but no pool change.",
    )
    WAIT = 15
    print(f"  Waiting {WAIT}s for Hindsight async processing...")
    time.sleep(WAIT)
    print("  Seed complete.")
except Exception as exc:
    print(f"  WARNING: Hindsight seed failed ({exc})")
    print("  MEMORY mode will run but may return empty hindsight_memories.")

# ── Run BASELINE ──────────────────────────────────────────────────────────────
print("\n" + "─" * 70)
print("  RUN 1 of 2 — BASELINE mode")
print("─" * 70)

baseline = analyze_deployment(
    deployment=PROPOSED,
    mode=AnalysisMode.BASELINE,
)

print(f"\n  mode              : {baseline.mode}")
print(f"  risk_assessment   : {baseline.risk_assessment}")
print(f"\n  summary:\n    {baseline.summary}")
print(f"\n  recommendation:\n    {baseline.recommendation}")
print(f"\n  relevant_deployments : {baseline.relevant_deployments}")
print(f"  cited_deployment_ids : {baseline.cited_deployment_ids}")
print(f"  evidence             : {repr(baseline.evidence)}")

# ── Run MEMORY-INFORMED ───────────────────────────────────────────────────────
print("\n" + "─" * 70)
print("  RUN 2 of 2 — MEMORY-INFORMED mode")
print("─" * 70)

memory = analyze_deployment(
    deployment=PROPOSED,
    mode=AnalysisMode.MEMORY,
    historical_records=HISTORICAL,
)

print(f"\n  mode              : {memory.mode}")
print(f"  risk_assessment   : {memory.risk_assessment}")
print(f"\n  summary:\n    {memory.summary}")
print(f"\n  recommendation:\n    {memory.recommendation}")
print(f"\n  evidence:\n    {memory.evidence}")

print(f"\n  relevant_deployments:")
for rd in memory.relevant_deployments:
    print(f"    #{rd.deployment_id}  score={rd.similarity_score}/5  "
          f"outcome={rd.outcome}  service={rd.service}")

print(f"\n  cited_deployment_ids : {memory.cited_deployment_ids}")

if memory.match_summary:
    ms = memory.match_summary
    print(f"\n  match_summary:")
    print(f"    total_similar    : {ms.total_similar}")
    print(f"    total_incidents  : {ms.total_incidents}")
    print(f"    total_successes  : {ms.total_successes}")
    print(f"    confidence_label : {ms.confidence_label}")
    for c in ms.candidates:
        matched = [s.signal for s in c.signal_matches if s.matched]
        print(f"    candidate #{c.deployment.deployment_id}  "
              f"score={c.similarity_score}/5  "
              f"outcome={c.deployment.outcome}  "
              f"memories={len(c.hindsight_memories)}")
        print(f"      matched signals: {matched}")

# ── Assertions ────────────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("  ASSERTIONS")
print("=" * 70)

errors: list[str] = []
VALID_RISK = {"low", "medium", "high"}

# Helper
def _text_contains_any(text: str, keywords: list[str]) -> bool:
    t = text.lower()
    return any(kw.lower() in t for kw in keywords)

# ── BASELINE assertions ───────────────────────────────────────────────────────
print("\n  [BASELINE]")

# B1
if baseline.mode == AnalysisMode.BASELINE:
    print("  PASS B1: mode == 'baseline'")
else:
    errors.append(f"FAIL B1: expected mode='baseline', got {baseline.mode!r}")

# B2
if not baseline.relevant_deployments:
    print("  PASS B2: relevant_deployments is empty (no history retrieved)")
else:
    ids = [r.deployment_id for r in baseline.relevant_deployments]
    errors.append(f"FAIL B2: relevant_deployments should be empty, got {ids}")

# B3
if not baseline.cited_deployment_ids:
    print("  PASS B3: cited_deployment_ids is empty")
else:
    errors.append(
        f"FAIL B3: cited_deployment_ids should be empty, got {baseline.cited_deployment_ids}"
    )

# B4
if not baseline.evidence:
    print("  PASS B4: evidence is empty in BASELINE mode")
else:
    errors.append(
        f"FAIL B4: evidence should be empty in BASELINE mode, got: {baseline.evidence!r}"
    )

# B5
if baseline.risk_assessment in VALID_RISK:
    print(f"  PASS B5: risk_assessment is valid ({baseline.risk_assessment!r})")
else:
    errors.append(
        f"FAIL B5: risk_assessment must be low/medium/high, got {baseline.risk_assessment!r}"
    )

# B6
if baseline.summary.strip():
    print("  PASS B6: summary is non-empty")
else:
    errors.append("FAIL B6: summary is empty")

# B7
if baseline.recommendation.strip():
    print("  PASS B7: recommendation is non-empty")
else:
    errors.append("FAIL B7: recommendation is empty")

# ── MEMORY assertions ─────────────────────────────────────────────────────────
print("\n  [MEMORY-INFORMED]")

# M1
if memory.mode == AnalysisMode.MEMORY:
    print("  PASS M1: mode == 'memory'")
else:
    errors.append(f"FAIL M1: expected mode='memory', got {memory.mode!r}")

# M2
if "184" in memory.cited_deployment_ids:
    print("  PASS M2: #184 appears in cited_deployment_ids")
else:
    errors.append(
        f"FAIL M2: #184 must be in cited_deployment_ids, got {memory.cited_deployment_ids}"
    )

# M3
rel_ids = [r.deployment_id for r in memory.relevant_deployments]
if "184" in rel_ids:
    print("  PASS M3: #184 appears in relevant_deployments")
else:
    errors.append(
        f"FAIL M3: #184 must appear in relevant_deployments, got {rel_ids}"
    )

# M4
if "237" not in memory.cited_deployment_ids:
    print("  PASS M4: #237 NOT in cited_deployment_ids")
else:
    errors.append("FAIL M4: #237 must NOT be in cited_deployment_ids")

# M5
if "237" not in rel_ids:
    print("  PASS M5: #237 NOT in relevant_deployments")
else:
    errors.append("FAIL M5: #237 must NOT appear in relevant_deployments")

# M6 — summary or evidence explicitly mentions "184"
combined_text = memory.summary + " " + memory.evidence
if "184" in combined_text:
    print("  PASS M6: summary/evidence explicitly cites deployment #184")
else:
    errors.append("FAIL M6: summary/evidence must explicitly cite '#184'")

# M7 — summary or evidence mentions root-cause / resolution keyword
ROOT_CAUSE_KEYWORDS = [
    "pool", "exhaustion", "connection pool", "staged", "monitoring",
    "pool exhaustion", "staged rollout",
]
if _text_contains_any(combined_text, ROOT_CAUSE_KEYWORDS):
    hit = next(k for k in ROOT_CAUSE_KEYWORDS if k.lower() in combined_text.lower())
    print(f"  PASS M7: root-cause/resolution keyword found ({hit!r})")
else:
    errors.append(
        "FAIL M7: summary/evidence must mention root cause or resolution "
        f"(checked: {ROOT_CAUSE_KEYWORDS})"
    )

# M8
if memory.evidence.strip():
    print("  PASS M8: evidence is non-empty in MEMORY mode")
else:
    errors.append("FAIL M8: evidence must be non-empty in MEMORY mode")

# M9
if memory.risk_assessment in VALID_RISK:
    print(f"  PASS M9: risk_assessment is valid ({memory.risk_assessment!r})")
else:
    errors.append(
        f"FAIL M9: risk_assessment must be low/medium/high, got {memory.risk_assessment!r}"
    )

# ── CONTRAST assertion ────────────────────────────────────────────────────────
print("\n  [CONTRAST]")

# C1 — outputs must differ
baseline_fingerprint = (
    baseline.risk_assessment,
    baseline.summary,
    str(sorted(baseline.cited_deployment_ids)),
)
memory_fingerprint = (
    memory.risk_assessment,
    memory.summary,
    str(sorted(memory.cited_deployment_ids)),
)

if baseline_fingerprint != memory_fingerprint:
    print("  PASS C1: BASELINE and MEMORY outputs are visibly different")
else:
    errors.append(
        "FAIL C1: BASELINE and MEMORY outputs are identical — "
        "they should differ because MEMORY cites historical evidence"
    )

# ── Final result ──────────────────────────────────────────────────────────────
print("\n" + "=" * 70)
if errors:
    print(f"  RESULT: {len(errors)} assertion(s) FAILED\n")
    for e in errors:
        print(f"    ✗ {e}")
    print()
    sys.exit(1)
else:
    total = 7 + 9 + 1  # B-assertions + M-assertions + C-assertion
    print(f"  RESULT: ALL {total} assertions PASSED")
    print()
    sys.exit(0)
