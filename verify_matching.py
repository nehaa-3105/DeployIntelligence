"""
verify_matching.py — Phase 3 throwaway verification script.

Tests the deterministic signal matching, ranking, and Hindsight recall
integration implemented in src/matching.py and src/models.py.

Dataset (hardcoded, no seed file needed):
    #184  payment-service, schema, pool=True,  infra, deps=True  → incident  (CLEAR MATCH)
    #201  payment-service, schema, pool=False, infra, deps=True  → success   (PARTIAL MATCH, 4/5)
    #237  inventory-service, config-only, pool=False, config, deps=False → success (UNRELATED)

Proposed deployment #297:
    payment-service, schema, pool=True, infra, deps=True → pending

Expected results:
    #184 scores 5/5  → candidate, recall attempted
    #201 scores 4/5  → candidate, recall attempted
    #237 scores 0/5  → filtered out (below threshold)
    confidence_label → "high" (1 incident out of 2 similar = 50% → "medium")
                       NOTE: 1/2 = 0.5, which is >= 0.33 but < 0.67 → "medium"

Usage:
    py -3 verify_matching.py

Requires .env with HINDSIGHT_API_KEY set (for the recall step).
The matching step itself works without Hindsight — recall failures degrade
gracefully to empty hindsight_memories lists.
"""

import sys

# ── Bootstrap ───────────────────────────────────────────────────────────────
print("=" * 65)
print("  Phase 3 — Structured Matching + Hindsight Recall Verification")
print("=" * 65)

from src.models import Deployment
from src.matching import score_signals, find_similar

# ── Hardcoded historical records ─────────────────────────────────────────────

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
        connection_pool_change=False,       # pool NOT changed — key difference
        change_type="infra",
        timestamp="2024-02-10T10:00:00Z",
        outcome="success",
        dependencies_changed=True,
        notes="Same service and migration type, but no pool change. Clean deploy.",
    ),
    Deployment(
        deployment_id="237",
        service="inventory-service",        # different service
        migration_type="config-only",       # different migration type
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

# ── Step 1: raw signal scoring (no Hindsight) ────────────────────────────────
print("\n[1/4] Raw signal scoring (no Hindsight, no threshold filtering)\n")

for hist in HISTORICAL:
    sigs = score_signals(PROPOSED, hist)
    score = sum(1 for s in sigs if s.matched)
    matched_names = [s.signal for s in sigs if s.matched]
    unmatched_names = [s.signal for s in sigs if not s.matched]
    print(f"  vs #{hist.deployment_id} ({hist.service}, {hist.outcome})")
    print(f"     score        : {score}/5")
    print(f"     matched      : {matched_names}")
    print(f"     not matched  : {unmatched_names}")

# ── Step 2: full pipeline with Hindsight recall ──────────────────────────────
print("\n[2/4] Full pipeline: find_similar() with live Hindsight recall\n")

# Wire in the real recall function from memory.py
try:
    from src.memory import ensure_bank_exists, store_deployment, retrieve_for_deployment, retrieve_candidates
    import time
    ensure_bank_exists()

    # Re-retain the two test records with deployment tags so tag-scoped
    # recall works. Tags are applied at retain time — memories stored before
    # this fix (without tags) would be invisible to tags_match="any_strict".
    print("      Retaining #184 and #201 with deployment tags...")
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
    # Wait for Hindsight server-side async fact extraction and tag indexing.
    # 6s was insufficient — extracted memory records (observations/facts) may
    # not yet carry the deployment tag when the recall runs. Using 15s here.
    # If tag-scoped recall still returns 0, run the diagnostic below first
    # to confirm whether tags propagate to extracted facts.
    WAIT = 15
    print(f"      Waiting {WAIT}s for Hindsight async processing and tag indexing...")
    time.sleep(WAIT)

    # -- DIAGNOSTIC: unscoped recall to verify memories exist and inspect document_id --
    # Tags are NOT returned on recalled extracted facts (tags=None / exclude_none=True
    # on RecallResult). document_id IS returned and is the reliable scoping key.
    from src.memory import retrieve_candidates
    print("\n      [DIAGNOSTIC] Unscoped recall for #184 (confirms memories exist + document_id):")
    diag_184 = retrieve_candidates(
        "deployment 184 payment-service schema migration connection pool incident"
    )
    for m in diag_184[:3]:
        print(f"        id={m['id']}  type={m['type']}")
        print(f"        document_id={m.get('document_id', 'NOT IN DICT')}")
        print(f"        tags={m.get('tags', 'NOT IN DICT')}")
        print(f"        text={m['text'][:80]}")
    if not diag_184:
        print("        (no memories returned — retain may still be processing)")

    print("\n      [DIAGNOSTIC] Unscoped recall for #201:")
    diag_201 = retrieve_candidates(
        "deployment 201 payment-service schema migration no connection pool change success"
    )
    for m in diag_201[:3]:
        print(f"        id={m['id']}  type={m['type']}")
        print(f"        document_id={m.get('document_id', 'NOT IN DICT')}")
        print(f"        tags={m.get('tags', 'NOT IN DICT')}")
        print(f"        text={m['text'][:80]}")
    if not diag_201:
        print("        (no memories returned)")
    # -- END DIAGNOSTIC --

    recall_fn = retrieve_for_deployment
    print("      Hindsight connected — tag-scoped recall will be used.")
except Exception as e:
    # Fall back to a no-op so matching still runs
    print(f"      WARNING: Hindsight unavailable ({e})")
    print("      Matching will run but hindsight_memories will be empty.")
    recall_fn = lambda q, did: []

summary = find_similar(
    proposed=PROPOSED,
    historical_records=HISTORICAL,
    recall_fn=recall_fn,
    threshold=2,
)

# ── Step 3: print MatchSummary ───────────────────────────────────────────────
print("\n[3/4] MatchSummary\n")
print(f"  proposed deployment : #{summary.proposed.deployment_id}")
print(f"  total_similar       : {summary.total_similar}")
print(f"  total_incidents     : {summary.total_incidents}")
print(f"  total_successes     : {summary.total_successes}")
print(f"  confidence_label    : {summary.confidence_label}")
print(f"  candidates          : {len(summary.candidates)}")

for i, cand in enumerate(summary.candidates):
    print(f"\n  candidate [{i}] ── #{cand.deployment.deployment_id} "
          f"({cand.deployment.service}, {cand.deployment.outcome})")
    print(f"    similarity_score  : {cand.similarity_score}/5")
    matched = [s.signal for s in cand.signal_matches if s.matched]
    unmatched = [s.signal for s in cand.signal_matches if not s.matched]
    print(f"    matched signals   : {matched}")
    print(f"    unmatched signals : {unmatched}")
    print(f"    hindsight_memories: {len(cand.hindsight_memories)} result(s)")
    for j, mem in enumerate(cand.hindsight_memories):
        print(f"      [{j}] id={mem.get('id','?')}")
        print(f"           doc_id={mem.get('document_id','?')}")
        print(f"           tags={mem.get('tags','?')}")
        print(f"           text={mem.get('text','')[:100]}")

# ── Step 4: assertions ───────────────────────────────────────────────────────
print("\n[4/4] Assertions\n")
errors: list[str] = []

ids = [c.deployment.deployment_id for c in summary.candidates]

# --- structural matching ---

if "237" in ids:
    errors.append("FAIL: #237 (unrelated) should be filtered out but was returned")
else:
    print("  PASS: #237 (unrelated, 0 signals) correctly filtered out")

if "184" not in ids:
    errors.append("FAIL: #184 (clear match) not found in candidates")
else:
    c184 = next(c for c in summary.candidates if c.deployment.deployment_id == "184")
    if c184.similarity_score != 5:
        errors.append(f"FAIL: #184 should score 5/5 but scored {c184.similarity_score}")
    else:
        print(f"  PASS: #184 scored 5/5 — clear match")

if "201" not in ids:
    errors.append("FAIL: #201 (partial match) not found in candidates")
else:
    c201 = next(c for c in summary.candidates if c.deployment.deployment_id == "201")
    if c201.similarity_score != 4:
        errors.append(f"FAIL: #201 should score 4/5 but scored {c201.similarity_score}")
    else:
        print(f"  PASS: #201 scored 4/5 — partial match (pool change differs)")

if "184" in ids and "201" in ids:
    rank_184 = ids.index("184")
    rank_201 = ids.index("201")
    if rank_184 < rank_201:
        print(f"  PASS: #184 (score 5) ranked above #201 (score 4)")
    else:
        errors.append("FAIL: #184 should rank above #201 but did not")

if summary.total_similar != 2:
    errors.append(f"FAIL: total_similar should be 2, got {summary.total_similar}")
else:
    print(f"  PASS: total_similar = 2")

if summary.total_incidents != 1:
    errors.append(f"FAIL: total_incidents should be 1, got {summary.total_incidents}")
else:
    print(f"  PASS: total_incidents = 1")

if summary.total_successes != 1:
    errors.append(f"FAIL: total_successes should be 1, got {summary.total_successes}")
else:
    print(f"  PASS: total_successes = 1")

if summary.confidence_label != "medium":
    errors.append(
        f"FAIL: confidence_label should be 'medium' (1/2=0.50), "
        f"got '{summary.confidence_label}'"
    )
else:
    print(f"  PASS: confidence_label = 'medium' (1 incident / 2 similar = 0.50)")

# --- Hindsight retrieval: #184 must have memories > 0 ---

if "184" in ids:
    c184 = next(c for c in summary.candidates if c.deployment.deployment_id == "184")
    if len(c184.hindsight_memories) == 0:
        errors.append(
            "FAIL: #184 hindsight_memories is empty — "
            "tag-based scoping not working or memories not yet indexed"
        )
    else:
        print(f"  PASS: #184 has {len(c184.hindsight_memories)} Hindsight memory result(s)")

    # --- #184 memories must all carry the deployment:184 tag ---
    if "184" in ids and c184.hindsight_memories:
        bad = [
            m for m in c184.hindsight_memories
            if "deployment:184" not in (m.get("tags") or [])
        ]
        if bad:
            errors.append(
                f"FAIL: {len(bad)} of #184's memories lack the 'deployment:184' tag "
                f"(first bad id: {bad[0].get('id')})"
            )
        else:
            print(f"  PASS: all #184 memories carry 'deployment:184' tag")

# --- #201 memories must not bleed into #184, and vice versa ---

if "201" in ids and "184" in ids:
    c201 = next(c for c in summary.candidates if c.deployment.deployment_id == "201")
    c184 = next(c for c in summary.candidates if c.deployment.deployment_id == "184")

    # No #201 memory should carry the deployment:184 tag
    c201_contaminated_by_184 = [
        m for m in c201.hindsight_memories
        if "deployment:184" in (m.get("tags") or [])
    ]
    if c201_contaminated_by_184:
        errors.append(
            f"FAIL: #201's memories contain {len(c201_contaminated_by_184)} result(s) "
            "tagged 'deployment:184' — cross-contamination detected"
        )
    else:
        print(f"  PASS: #201 memories contain no 'deployment:184' entries")

    # No #184 memory should carry the deployment:201 tag
    c184_contaminated_by_201 = [
        m for m in c184.hindsight_memories
        if "deployment:201" in (m.get("tags") or [])
    ]
    if c184_contaminated_by_201:
        errors.append(
            f"FAIL: #184's memories contain {len(c184_contaminated_by_201)} result(s) "
            "tagged 'deployment:201' — cross-contamination detected"
        )
    else:
        print(f"  PASS: #184 memories contain no 'deployment:201' entries")

    # If #201 has memories, they must all carry deployment:201
    if c201.hindsight_memories:
        bad_201 = [
            m for m in c201.hindsight_memories
            if "deployment:201" not in (m.get("tags") or [])
        ]
        if bad_201:
            errors.append(
                f"FAIL: {len(bad_201)} of #201's memories lack the 'deployment:201' tag"
            )
        else:
            print(f"  PASS: all #201 memories carry 'deployment:201' tag")
    else:
        print(f"  INFO: #201 has 0 Hindsight memories (may not yet be indexed)")

# ── Result ───────────────────────────────────────────────────────────────────
print("\n" + "=" * 65)
if errors:
    print(f"  RESULT: {len(errors)} FAILURE(S)")
    for e in errors:
        print(f"    • {e}")
else:
    print("  RESULT: ALL ASSERTIONS PASSED")
print("=" * 65)

# Clean up — close the Hindsight client on the correct event loop.
# Import close() only if memory was successfully imported earlier.
try:
    from src.memory import close
    close()
except Exception:
    pass

sys.exit(1 if errors else 0)
