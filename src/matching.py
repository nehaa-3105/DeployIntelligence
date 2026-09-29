"""
Structured signal matching and Hindsight recall for Deployment Memory.

This module implements the two-stage similarity mechanism described in the
architecture:

Stage 1 — Deterministic structured signal matching (no LLM, no embeddings)
---------------------------------------------------------------------------
Compare a proposed deployment against a list of historical deployment records
using exactly five explicit signals:

    signal                  type      match rule
    ──────────────────────────────────────────────
    service                 str       exact string equality
    migration_type          str       exact string equality
    connection_pool_change  bool      exact boolean equality
    change_type             str       exact string equality
    dependencies_changed    bool|None exact equality; None on either side = 0

Similarity score = count of matched signals (0–5, integer).
Only candidates with score >= 2 are returned as structurally similar.
The threshold is not configurable below 2 — 1-signal matches are noise.

Stage 2 — Hindsight recall for matched candidates
-------------------------------------------------
For each candidate that clears the >= 2 threshold, query Hindsight memory
using a natural-language query built from the candidate's deployment_id and
service. Attach the returned raw memory dicts to the candidate.

Hindsight metadata does NOT round-trip through recall (confirmed in Phase 2).
All structured information (service, migration_type, outcome, etc.) comes from
the local historical records passed in — NOT from Hindsight recall text.
Hindsight recall provides the experiential evidence: root cause, resolution,
recovery notes as extracted facts.

Public API
----------
score_signals(proposed, historical) -> list[SignalMatch]
    Compare all five signals. Returns all five results (matched or not).
    Used internally and exposed for testing.

find_similar(proposed, historical_records, recall_fn, threshold=2)
    -> MatchSummary
    Full pipeline: score all historical records, filter by threshold,
    attach Hindsight evidence, rank by score, build MatchSummary with
    deterministic frequency counts.
"""

from __future__ import annotations

from typing import Any, Callable

from src.models import (
    Deployment,
    MatchCandidate,
    MatchSummary,
    SignalMatch,
)

# ---------------------------------------------------------------------------
# Signal scoring
# ---------------------------------------------------------------------------

def score_signals(proposed: Deployment, historical: Deployment) -> list[SignalMatch]:
    """
    Compare a proposed deployment against one historical deployment across
    all five structural signals.

    Returns a list of five SignalMatch objects in the stable order defined
    by models.SIGNAL_NAMES. All five are always returned regardless of
    whether they matched — callers filter by `matched` themselves.

    Matching rules:
        service, migration_type, change_type — case-insensitive exact match.
        connection_pool_change               — boolean exact match.
        dependencies_changed                 — boolean exact match;
                                               None on either side scores 0
                                               (absence of information ≠ match).

    Parameters
    ----------
    proposed : Deployment
        The new deployment being analysed.
    historical : Deployment
        One past deployment record from the local dataset.

    Returns
    -------
    list[SignalMatch]
        Five entries, one per signal, in SIGNAL_NAMES order.
    """
    results: list[SignalMatch] = []

    # 1. service — exact, case-insensitive
    p_service = proposed.service.strip().lower()
    h_service = historical.service.strip().lower()
    results.append(SignalMatch(
        signal="service",
        matched=(p_service == h_service),
        proposed_value=proposed.service,
        historical_value=historical.service,
    ))

    # 2. migration_type — exact, case-insensitive
    p_mig = proposed.migration_type.strip().lower()
    h_mig = historical.migration_type.strip().lower()
    results.append(SignalMatch(
        signal="migration_type",
        matched=(p_mig == h_mig),
        proposed_value=proposed.migration_type,
        historical_value=historical.migration_type,
    ))

    # 3. connection_pool_change — boolean exact
    results.append(SignalMatch(
        signal="connection_pool_change",
        matched=(proposed.connection_pool_change == historical.connection_pool_change),
        proposed_value=proposed.connection_pool_change,
        historical_value=historical.connection_pool_change,
    ))

    # 4. change_type — exact, case-insensitive
    p_ct = proposed.change_type.strip().lower()
    h_ct = historical.change_type.strip().lower()
    results.append(SignalMatch(
        signal="change_type",
        matched=(p_ct == h_ct),
        proposed_value=proposed.change_type,
        historical_value=historical.change_type,
    ))

    # 5. dependencies_changed — boolean exact; None on either side = no match
    p_dep = proposed.dependencies_changed
    h_dep = historical.dependencies_changed
    if p_dep is None or h_dep is None:
        dep_matched = False
    else:
        dep_matched = (p_dep == h_dep)
    results.append(SignalMatch(
        signal="dependencies_changed",
        matched=dep_matched,
        proposed_value=p_dep,
        historical_value=h_dep,
    ))

    return results


def _similarity_score(signal_matches: list[SignalMatch]) -> int:
    """Count the number of matched signals. Pure function, no I/O."""
    return sum(1 for s in signal_matches if s.matched)


# ---------------------------------------------------------------------------
# Frequency counting and confidence label
# ---------------------------------------------------------------------------

def _confidence_label(total_similar: int, total_incidents: int) -> str:
    """
    Derive a confidence label deterministically from the incident ratio.

    Thresholds:
        total_similar == 0          → "none"
        incidents / similar >= 0.67 → "high"
        incidents / similar >= 0.33 → "medium"
        else                        → "low"

    This is computed in code from the retrieved candidate set and is
    never asserted by the LLM.
    """
    if total_similar == 0:
        return "none"
    ratio = total_incidents / total_similar
    if ratio >= 0.67:
        return "high"
    if ratio >= 0.33:
        return "medium"
    return "low"


# ---------------------------------------------------------------------------
# Hindsight recall query builder
# ---------------------------------------------------------------------------

def _recall_query_for(deployment: Deployment) -> str:
    """
    Build a natural-language recall query for a historical deployment.

    The query is designed to surface memory entries retained for this
    specific deployment. Because metadata does not round-trip through
    Hindsight recall, we embed the deployment_id and service directly
    in the query text.
    """
    pool_phrase = (
        "connection pool change" if deployment.connection_pool_change
        else "no connection pool change"
    )
    return (
        f"deployment {deployment.deployment_id} {deployment.service} "
        f"{deployment.migration_type} migration {pool_phrase} {deployment.outcome}"
    )


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def find_similar(
    proposed: Deployment,
    historical_records: list[Deployment],
    recall_fn: Callable[[str, str], list[dict[str, Any]]],
    threshold: int = 2,
    skip_same_id: bool = True,
) -> MatchSummary:
    """
    Full similarity pipeline: structured matching → Hindsight recall → ranking.

    Parameters
    ----------
    proposed : Deployment
        The new deployment being analysed.
    historical_records : list[Deployment]
        All known historical deployments from the local dataset.
        Matching is performed against every record in this list.
    recall_fn : Callable[[str, str], list[dict]]
        A callable with signature (query: str, deployment_id: str) -> list[dict].
        Called once per candidate that clears the threshold.
        Must return Hindsight memory dicts scoped to the given deployment_id.
        The expected production implementation is memory.retrieve_for_deployment.
        Injected so this module has no direct import of memory.py and the
        matching stage can be exercised without a live Hindsight connection.
    threshold : int
        Minimum similarity score to be considered a candidate. Default 2.
        Must not be set below 2 in production — 1-signal matches are noise.
    skip_same_id : bool
        When True (default), the proposed deployment's own record is excluded
        from historical_records before scoring (matched by deployment_id).
        When False, the proposed deployment may appear as its own candidate —
        used for rerun after feedback so the deployment's own outcome is
        factored into the analysis.

    Returns
    -------
    MatchSummary
        Contains all candidates with score >= threshold, ranked by
        similarity_score descending. Frequency counts and confidence label
        are computed deterministically from the candidate list.

    Notes
    -----
    - recall_fn is called with (query, deployment_id) so the memory layer
      can scope Hindsight recall to the specific candidate using tag filtering.
      This prevents one candidate's memories from appearing in another's
      evidence — the root cause of the Phase 3 cross-contamination bug.
    - If recall_fn raises, that candidate gets an empty hindsight_memories
      list and matching continues. A Hindsight outage does not break
      structured matching.
    """
    candidates: list[MatchCandidate] = []

    for historical in historical_records:
        # Skip if this IS the proposed deployment (same ID), unless caller
        # explicitly requests self-inclusion via skip_same_id=False.
        if skip_same_id and historical.deployment_id == proposed.deployment_id:
            continue

        signal_matches = score_signals(proposed, historical)
        score = _similarity_score(signal_matches)

        if score < threshold:
            continue

        # Stage 2: recall Hindsight evidence scoped to this candidate.
        # recall_fn receives both the query string (for semantic ranking)
        # and the deployment_id (for tag-based hard filtering in Hindsight).
        query = _recall_query_for(historical)
        try:
            memories = recall_fn(historical.deployment_id, query)
        except Exception:
            # Hindsight unavailable — degrade gracefully, don't abort matching
            memories = []

        candidates.append(MatchCandidate(
            deployment=historical,
            similarity_score=score,
            signal_matches=signal_matches,
            hindsight_memories=memories,
        ))

    # Rank by similarity score, highest first. Stable sort: equal scores
    # preserve original list order (i.e. chronological if records are ordered).
    candidates.sort(key=lambda c: c.similarity_score, reverse=True)

    # Deterministic frequency counts — never asserted by LLM
    total_similar = len(candidates)
    total_incidents = sum(
        1 for c in candidates if c.deployment.outcome == "incident"
    )
    total_successes = sum(
        1 for c in candidates if c.deployment.outcome == "success"
    )

    return MatchSummary(
        proposed=proposed,
        candidates=candidates,
        total_similar=total_similar,
        total_incidents=total_incidents,
        total_successes=total_successes,
        confidence_label=_confidence_label(total_similar, total_incidents),
    )
