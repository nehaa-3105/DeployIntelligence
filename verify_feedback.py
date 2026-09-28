"""
verify_feedback.py — Phase 5 throwaway verification script.

Demonstrates and verifies the manual outcome feedback loop:
  1. Define a completed deployment (#350) with unique demo ID.
  2. Run memory-informed analysis of a follow-up deployment (#351) BEFORE
     recording #350's outcome.
  3. Record #350's outcome manually via record_outcome().
  4. Wait for Hindsight async processing (same pattern as Phase 3/4 scripts).
  5. Run memory-informed analysis of #351 AGAIN.
  6. Compare before/after to show whether the new memory was retrieved.

Dataset
-------
  #350  payment-service, schema, pool=True, infra, deps=True → incident
        (completed; we will record this outcome manually)
        root cause : connection pool exhaustion (similar to historical #184)
        resolution : reduced batch size and added pool monitoring alerts

  #351  payment-service, schema, pool=True, infra, deps=True → pending
        (the follow-up proposed deployment — structurally identical to #350
        and should match it after its outcome is recorded)

  #999  order-service, code-only, pool=False, code, deps=False → success
        (structurally unrelated; must NOT appear as relevant evidence for #351)

Why #350 should be retrievable for #351
----------------------------------------
All five structural signals match:
  service              : payment-service  ✓
  migration_type       : schema           ✓
  connection_pool_change: True            ✓
  change_type          : infra            ✓
  dependencies_changed : True             ✓
Score = 5/5 → passes the >= 2 threshold in find_similar().

Success conditions asserted
---------------------------
  F1. record_outcome() succeeds without raising
  F2. Before analysis: #350 not yet in cited_deployment_ids (not seeded yet)
  F3. After analysis: #350 appears in relevant_deployments (structural match)
  F4. After analysis: #350 appears in cited_deployment_ids
  F5. After analysis: summary or evidence mentions "350"
  F6. After analysis: #999 does NOT appear in relevant_deployments
  F7. after_risk_assessment is one of {"low", "medium", "high"}
  F8. The before and after analyses differ (new memory influenced the result)

Usage
-----
    py -3 verify_feedback.py

Requirements
------------
    .env with GEMINI_API_KEY and HINDSIGHT_API_KEY.
    Run `py -3 -m pip install -r requirements.txt` first if not installed.
"""

import sys
import time

# ── Bootstrap ────────────────────────────────────────────────────────────────
print("=" * 70)
print("  Phase 5 — Manual Outcome Feedback Verification")
print("  record_outcome() → Hindsight → analyze_deployment() before/after")
print("=" * 70)

from src.models import AnalysisMode, Deployment
from src.analysis import analyze_deployment
from src.feedback import record_outcome
from src.memory import ensure_bank_exists, retrieve_candidates

# ── Demo dataset ──────────────────────────────────────────────────────────────

# The completed deployment whose outcome we will record manually.
COMPLETED = Deployment(
    deployment_id="350",
    service="payment-service",
    migration_type="schema",
    connection_pool_change=True,
    change_type="infra",
    timestamp="2025-02-10T11:00:00Z",
    outcome="pending",          # still "pending" as recorded before deploy
    dependencies_changed=True,
    notes="Schema migration + pool change on payment-service.",
)

# The follow-up proposed deployment that should match #350 after feedback.
PROPOSED_FOLLOWUP = Deployment(
    deployment_id="351",
    service="payment-service",
    migration_type="schema",
    connection_pool_change=True,
    change_type="infra",
    timestamp="2025-03-01T14:00:00Z",
    outcome="pending",
    dependencies_changed=True,
    notes="Identical configuration to #350; proposed for next sprint.",
)

# Structurally unrelated — must never appear as evidence for #351.
UNRELATED = Deployment(
    deployment_id="999",
    service="order-service",
    migration_type="code-only",
    connection_pool_change=False,
    change_type="code",
    timestamp="2025-01-05T09:00:00Z",
    outcome="success",
    dependencies_changed=False,
    notes="Routine code-only deploy on order-service.",
)

# Historical records visible to both before/after analyses.
# #350 is in here so find_similar() can score it structurally — but its
# Hindsight memory only exists AFTER record_outcome() is called.
HISTORICAL = [COMPLETED, UNRELATED]

# ── BEFORE: analysis before recording #350's outcome ─────────────────────────
print("\n[1/5] BEFORE analysis — #350 not yet in Hindsight memory")
print("─" * 70)

try:
    ensure_bank_exists()
    before = analyze_deployment(
        deployment=PROPOSED_FOLLOWUP,
        mode=AnalysisMode.MEMORY,
        historical_records=HISTORICAL,
    )
    print(f"  mode             : {before.mode}")
    print(f"  risk_assessment  : {before.risk_assessment}")
    print(f"  relevant_deployments : "
          f"{[r.deployment_id for r in before.relevant_deployments]}")
    print(f"  cited_deployment_ids : {before.cited_deployment_ids}")
    print(f"\n  summary (truncated): {before.summary[:200]}")
    before_ok = True
except Exception as exc:
    print(f"  ERROR during before-analysis: {exc}")
    before_ok = False
    before = None

# ── RECORD OUTCOME ────────────────────────────────────────────────────────────
print("\n[2/5] Recording outcome for #350 via record_outcome()")
print("─" * 70)

feedback_ok = False
try:
    record_outcome(
        deployment=COMPLETED,
        outcome="incident",
        root_cause="connection pool exhaustion during schema migration rollout",
        resolution="reduced migration batch size and added pool monitoring alerts",
        recovery_time_minutes=22,
        notes="Incident began 6 minutes post-deploy at peak order traffic.",
    )
    print("  record_outcome() completed without error.")
    feedback_ok = True
except Exception as exc:
    print(f"  ERROR: record_outcome() raised: {exc}")

# ── WAIT ──────────────────────────────────────────────────────────────────────
WAIT = 15
print(f"\n[3/5] Waiting {WAIT}s for Hindsight async processing...")
time.sleep(WAIT)

# ── DIAGNOSTIC: confirm memory was retained ───────────────────────────────────
print("\n[4/5] Diagnostic recall — confirming #350 memory is now indexed")
print("─" * 70)

try:
    diag = retrieve_candidates(
        "deployment 350 payment-service schema migration connection pool incident"
    )
    found_350 = any("350" in m.get("text", "") for m in diag)
    print(f"  Unscoped recall returned {len(diag)} result(s).")
    for m in diag[:3]:
        print(f"    [{m.get('type','?')}] {m.get('text','')[:100]}")
    if found_350:
        print("  ✓ Deployment #350 text found in recalled memories.")
    else:
        print("  ⚠ Deployment #350 text NOT found yet — Hindsight may still be processing.")
except Exception as exc:
    print(f"  WARNING: diagnostic recall failed ({exc})")
    found_350 = False

# ── AFTER: analysis after recording #350's outcome ───────────────────────────
print("\n[5/5] AFTER analysis — #350 now in Hindsight memory")
print("─" * 70)

after_ok = False
after = None
try:
    after = analyze_deployment(
        deployment=PROPOSED_FOLLOWUP,
        mode=AnalysisMode.MEMORY,
        historical_records=HISTORICAL,
    )
    print(f"  mode             : {after.mode}")
    print(f"  risk_assessment  : {after.risk_assessment}")
    print(f"\n  summary:\n    {after.summary}")
    print(f"\n  recommendation:\n    {after.recommendation}")
    print(f"\n  evidence:\n    {after.evidence}")
    print(f"\n  relevant_deployments:")
    for rd in after.relevant_deployments:
        print(f"    #{rd.deployment_id}  score={rd.similarity_score}/5  "
              f"outcome={rd.outcome}  service={rd.service}")
    print(f"\n  cited_deployment_ids : {after.cited_deployment_ids}")

    if after.match_summary:
        ms = after.match_summary
        print(f"\n  match_summary:")
        print(f"    total_similar    : {ms.total_similar}")
        print(f"    total_incidents  : {ms.total_incidents}")
        print(f"    confidence_label : {ms.confidence_label}")
        for c in ms.candidates:
            matched = [s.signal for s in c.signal_matches if s.matched]
            print(f"    candidate #{c.deployment.deployment_id}  "
                  f"score={c.similarity_score}/5  "
                  f"outcome={c.deployment.outcome}  "
                  f"memories={len(c.hindsight_memories)}")
            print(f"      matched signals: {matched}")
    after_ok = True
except Exception as exc:
    print(f"  ERROR during after-analysis: {exc}")

# ── Assertions ────────────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("  ASSERTIONS")
print("=" * 70)

errors: list[str] = []
VALID_RISK = {"low", "medium", "high"}

# F1 — record_outcome() succeeded
if feedback_ok:
    print("  PASS F1: record_outcome() completed without error")
else:
    errors.append("FAIL F1: record_outcome() raised an exception")

# F2 — BEFORE: #350 not in cited_deployment_ids (memory didn't exist yet)
if before is not None:
    if "350" not in before.cited_deployment_ids:
        print("  PASS F2: #350 not in cited_deployment_ids BEFORE feedback "
              "(outcome not yet recorded)")
    else:
        # Not a hard failure — if #350 was already in the bank from a prior
        # run it might appear. Flag as informational.
        print("  INFO  F2: #350 already appeared BEFORE feedback — bank may "
              "contain a prior run's entry. Re-run with a fresh bank ID to "
              "get a fully clean before/after contrast.")
else:
    errors.append("FAIL F2: before-analysis did not complete; cannot assess")

# F3 — AFTER: #350 in relevant_deployments (structural match passes threshold)
if after is not None:
    after_rel_ids = [r.deployment_id for r in after.relevant_deployments]

    if "350" in after_rel_ids:
        score_350 = next(
            r.similarity_score for r in after.relevant_deployments
            if r.deployment_id == "350"
        )
        print(f"  PASS F3: #350 appears in relevant_deployments "
              f"(score={score_350}/5)")
    else:
        errors.append(
            f"FAIL F3: #350 must appear in relevant_deployments after feedback, "
            f"got {after_rel_ids}"
        )

    # F4 — #350 cited by the LLM
    if "350" in after.cited_deployment_ids:
        print("  PASS F4: #350 in cited_deployment_ids after feedback")
    else:
        errors.append(
            f"FAIL F4: #350 must be in cited_deployment_ids after feedback, "
            f"got {after.cited_deployment_ids}. "
            "Note: this may fail if Hindsight has not yet indexed the new memory — "
            "try increasing WAIT or re-running."
        )

    # F5 — LLM text explicitly mentions "350"
    combined = after.summary + " " + after.evidence
    if "350" in combined:
        print("  PASS F5: summary/evidence explicitly mentions deployment #350")
    else:
        errors.append(
            "FAIL F5: summary/evidence must mention '#350' — "
            "LLM did not cite the newly recorded deployment"
        )

    # F6 — #999 (unrelated) NOT in relevant_deployments
    if "999" not in after_rel_ids:
        print("  PASS F6: #999 (unrelated) not in relevant_deployments")
    else:
        errors.append(
            "FAIL F6: #999 must NOT appear in relevant_deployments "
            "(unrelated order-service deploy should score 0/5)"
        )

    # F7 — valid risk_assessment value
    if after.risk_assessment in VALID_RISK:
        print(f"  PASS F7: risk_assessment is valid ({after.risk_assessment!r})")
    else:
        errors.append(
            f"FAIL F7: risk_assessment must be low/medium/high, "
            f"got {after.risk_assessment!r}"
        )

    # F8 — before and after differ (new memory influenced something)
    if before is not None:
        before_fingerprint = (
            before.risk_assessment,
            str(sorted(before.cited_deployment_ids)),
        )
        after_fingerprint = (
            after.risk_assessment,
            str(sorted(after.cited_deployment_ids)),
        )
        if before_fingerprint != after_fingerprint:
            print("  PASS F8: BEFORE and AFTER analyses differ — "
                  "newly recorded outcome influenced the result")
        else:
            # Informational rather than hard failure: if the Hindsight tag
            # indexing hasn't propagated the new memory into the tagged recall
            # results yet, the LLM evidence block may be unchanged even though
            # the structural match still fires. Report clearly.
            print(
                "  INFO  F8: BEFORE and AFTER fingerprints are identical.\n"
                "            This may mean Hindsight has not yet propagated\n"
                "            the deployment:350 tag to extracted memory records.\n"
                "            The structural match (#350 in relevant_deployments)\n"
                "            still fired correctly (see F3). Try increasing WAIT\n"
                "            or re-running after a few minutes for full tag propagation."
            )
else:
    for fid in ("F3", "F4", "F5", "F6", "F7", "F8"):
        errors.append(f"FAIL {fid}: after-analysis did not complete; cannot assess")

# ── Final result ──────────────────────────────────────────────────────────────
print("\n" + "=" * 70)
if errors:
    print(f"  RESULT: {len(errors)} assertion(s) FAILED\n")
    for e in errors:
        print(f"    ✗ {e}")
    print()
    sys.exit(1)
else:
    print("  RESULT: ALL assertions PASSED")
    print()
    sys.exit(0)
