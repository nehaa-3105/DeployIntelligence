"""
Hindsight memory integration for Deployment Memory.

Owns all interaction with the Hindsight SDK. No other module calls
hindsight_client directly — all memory I/O goes through this module.

Public API
----------
ensure_bank_exists() -> None
    Idempotent. Creates the Hindsight bank on first call; safe to call
    every startup. Must be called before store_deployment or retrieve_candidates.

store_deployment(deployment_id, service, migration_type,
                 connection_pool_change, outcome,
                 root_cause, resolution, recovery_time_minutes) -> None
    Retains one deployment + outcome record as a natural-language memory
    entry. Structured fields are embedded inline in the sentence so
    Hindsight's fact-extraction picks them up for semantic recall.

retrieve_candidates(query) -> list[dict]
    Recalls raw memory objects matching the query string.
    Returns a list of dicts, each with keys:
        id, text, type, entities, context, mentioned_at
    Does NOT synthesise or count — that is matching.py's job.

What Hindsight recall actually returns (confirmed via docs):
    A ranked list of raw memory objects, not synthesised summaries.
    reflect() is the synthesising call, but we do not use it here.
"""

from __future__ import annotations

import time
from typing import Any

from hindsight_client import Hindsight

from src.config import settings

# ---------------------------------------------------------------------------
# Module-level client — initialised lazily via ensure_bank_exists()
# ---------------------------------------------------------------------------
_client: Hindsight | None = None


def _get_client() -> Hindsight:
    """Return the shared Hindsight client, initialising it on first call."""
    global _client
    if _client is None:
        _client = Hindsight(
            base_url=settings.hindsight_base_url,
            api_key=settings.hindsight_api_key,
        )
    return _client


def ensure_bank_exists() -> None:
    """
    Create the project memory bank if it does not already exist.
    Hindsight's create_bank is idempotent — safe to call on every startup.
    """
    client = _get_client()
    client.create_bank(
        bank_id=settings.hindsight_bank_id,
        name="Deployment Memory",
        background=(
            "Stores historical deployment records and their outcomes for an "
            "engineering organisation. Used to recognise patterns in new "
            "deployments that resemble past incidents."
        ),
    )


def store_deployment(
    *,
    deployment_id: str,
    service: str,
    migration_type: str,
    connection_pool_change: bool,
    outcome: str,
    root_cause: str = "",
    resolution: str = "",
    recovery_time_minutes: int = 0,
    extra_notes: str = "",
) -> None:
    """
    Retain one deployment record in Hindsight memory.

    The record is stored as a single descriptive sentence so Hindsight's
    fact-extraction picks up the structured signals for semantic recall.

    Tags
    ----
    Every retained memory is tagged with "deployment:{deployment_id}".
    This tag is used by retrieve_for_deployment() to scope recall to a
    specific deployment, preventing one candidate's memories from
    appearing in another candidate's evidence.

    Tags must be applied at retain time — they cannot be added retroactively.
    If you re-seed the bank, clear it first to avoid untagged stale memories.

    Parameters
    ----------
    deployment_id : str
        Unique identifier, e.g. "184".
    service : str
        Service name, e.g. "payment-service".
    migration_type : str
        Type of change, e.g. "schema", "read-replica", "config-only", "infra-only".
    connection_pool_change : bool
        Whether the deployment changed connection pool settings.
    outcome : str
        "incident" or "success".
    root_cause : str
        For incidents: short description of root cause.
    resolution : str
        For incidents: what fixed it.
    recovery_time_minutes : int
        For incidents: time to resolution.
    extra_notes : str
        Optional free-text for realism in the seed dataset.
    """
    client = _get_client()

    # Build the natural-language sentence that Hindsight will extract facts from.
    pool_phrase = (
        "included a connection pool change" if connection_pool_change
        else "did not change the connection pool"
    )

    if outcome == "incident":
        outcome_sentence = (
            f"The deployment resulted in an incident. "
            f"Root cause: {root_cause}. "
            f"Resolution: {resolution}. "
            f"Recovery time: {recovery_time_minutes} minutes."
        )
    else:
        outcome_sentence = "The deployment completed successfully with no incident."

    content = (
        f"Deployment {deployment_id} on {service} performed a {migration_type} migration "
        f"and {pool_phrase}. "
        f"{outcome_sentence}"
    )
    if extra_notes:
        content += f" Additional context: {extra_notes}"

    client.retain(
        bank_id=settings.hindsight_bank_id,
        content=content,
        # document_id groups all retained content for this deployment into one
        # logical document. RecallResult objects carry document_id back in the
        # recall response, so retrieve_for_deployment() can post-filter results
        # by document_id to guarantee candidate-specific retrieval.
        #
        # Tags are also set for belt-and-suspenders, but the primary scoping
        # mechanism is document_id because Hindsight's extracted fact records
        # reliably carry document_id back on recall; tags on extracted facts
        # are not reliably returned (confirmed: tags=None / excluded_none=True
        # on RecallResult objects from the server).
        document_id=f"deployment:{deployment_id}",
        tags=[f"deployment:{deployment_id}"],
        metadata={
            "deployment_id": deployment_id,
            "service": service,
            "migration_type": migration_type,
            "connection_pool_change": str(connection_pool_change),
            "outcome": outcome,
        },
    )


def retrieve_candidates(query: str, limit: int = 10) -> list[dict[str, Any]]:
    """
    Recall memory objects relevant to the given query string.

    Unscoped recall — searches the entire bank. Kept for backward
    compatibility with the Phase 2 verification script and any caller
    that does not have a specific deployment_id to scope by.

    For candidate-specific retrieval (one candidate per recall call)
    use retrieve_for_deployment() instead — it scopes by deployment tag
    and guarantees one candidate's memories cannot appear in another's.

    Returns a plain list of dicts (not Hindsight model objects) so callers
    never take a direct dependency on the hindsight_client type hierarchy.

    Each dict contains:
        id, text, type, entities, context, mentioned_at

    Confirmed SDK signature (hindsight-client==0.10.0):
        recall(bank_id, query, types=None, max_tokens=4096, budget="mid", ...)
        No `limit` parameter — token budget controls result volume.
    """
    client = _get_client()
    approx_max_tokens = min(limit * 512, 4096)

    result = client.recall(
        bank_id=settings.hindsight_bank_id,
        query=query,
        max_tokens=approx_max_tokens,
        budget="mid",
    )

    memories: list[dict[str, Any]] = []
    for mem in result.results:
        memories.append({
            "id": getattr(mem, "id", None),
            "text": getattr(mem, "text", ""),
            "type": getattr(mem, "type", ""),
            "entities": getattr(mem, "entities", []),
            "context": getattr(mem, "context", ""),
            "mentioned_at": str(getattr(mem, "mentioned_at", "")),
            "document_id": getattr(mem, "document_id", None),
            "tags": getattr(mem, "tags", None),
        })
    return memories


def retrieve_for_deployment(
    deployment_id: str,
    query: str,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """
    Recall memory objects scoped to a specific deployment.

    Mechanism: Python-side tag filter
    ----------------------------------
    store_deployment() tags every retained memory with
    "deployment:{deployment_id}". Some of Hindsight's server-side extracted
    fact/observation records carry this tag back in the RecallResult.tags
    field; others have tags=[] or tags=None (ambiguous — cannot be attributed
    to any deployment with certainty).

    This function performs an unscoped semantic recall (wider token budget for
    headroom) and then post-filters in Python:
        KEEP   if deployment_tag in (mem.tags or [])
        DISCARD if tags is None or [] — unattributable, treated as ambiguous

    Why not document_id?
    --------------------
    document_id is unreliable as a scoping key: some recalled records have
    document_id=None, some have UUID document_ids, and only some have the
    expected "deployment:{id}" value. Confirmed from diagnostic output.

    Why not server-side tags_match="any_strict"?
    --------------------------------------------
    tags_match="any_strict" returns 0 results for all candidates — the
    server excludes untagged extracted memories, but our best records have
    tags=[] (not the deployment tag), so they too get excluded.

    The Python-side filter is the most reliable approach given the actual
    data: it uses the tags that ARE present and discards ambiguous records.

    Parameters
    ----------
    deployment_id : str
        The deployment whose memories to retrieve, e.g. "184".
    query : str
        Natural-language query for semantic ranking within the result set.
    limit : int
        Upper bound on results after post-filtering (default 10).
        Recall fetches with a wider token budget so the post-filter has
        enough material even when many records are ambiguous.
    """
    client = _get_client()
    deployment_tag = f"deployment:{deployment_id}"

    # Use a wider budget so that even if many results are filtered out,
    # we still have enough deployment-tagged records to return.
    approx_max_tokens = min(limit * 4 * 512, 4096)

    result = client.recall(
        bank_id=settings.hindsight_bank_id,
        query=query,
        max_tokens=approx_max_tokens,
        budget="mid",
    )

    memories: list[dict[str, Any]] = []
    for mem in result.results:
        # tags is Optional[list[str]] — None means not set, [] means explicitly
        # empty. Neither can be attributed to this deployment.
        raw_tags: list[str] | None = getattr(mem, "tags", None)
        if not raw_tags:          # None or empty list — skip
            continue
        if deployment_tag not in raw_tags:
            continue              # tagged, but for a different deployment

        memories.append({
            "id": getattr(mem, "id", None),
            "text": getattr(mem, "text", ""),
            "type": getattr(mem, "type", ""),
            "entities": getattr(mem, "entities", []),
            "context": getattr(mem, "context", ""),
            "mentioned_at": str(getattr(mem, "mentioned_at", "")),
            "document_id": getattr(mem, "document_id", None),
            "tags": raw_tags,
        })
        if len(memories) >= limit:
            break
    return memories


def close() -> None:
    """
    Close the Hindsight client connection cleanly. Call on application shutdown.

    Uses the SDK's internal _run_async helper so the close coroutine runs on
    the same event loop that created the aiohttp ClientSession (every sync SDK
    method uses _run_async, so the session is bound to that loop).

    After awaiting aclose(), sleeps 250ms on the same loop so aiohttp's
    internally-scheduled _wait_for_close task has time to complete. A single
    sleep(0) is insufficient — _wait_for_close has multiple await points.
    250ms is the value from aiohttp's own graceful-shutdown documentation.
    """
    global _client
    if _client is None:
        return

    import asyncio
    from hindsight_client.hindsight_client import _run_async

    async def _aclose_with_drain() -> None:
        await _client.aclose()          # type: ignore[union-attr]
        await asyncio.sleep(0.250)      # let _wait_for_close finish

    try:
        _run_async(_aclose_with_drain())
    except Exception:
        pass  # best-effort; don't crash on shutdown

    _client = None
