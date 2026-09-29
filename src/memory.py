"""
Hindsight memory integration for Deployment Memory.

Owns all interaction with the Hindsight SDK. No other module calls
hindsight_client directly — all memory I/O goes through this module.

Public API
----------
ensure_bank_exists() -> None
    Idempotent. Creates the Hindsight bank on first call; safe to call
    every startup. Must be called before store_deployment or retrieve_candidates.
    Caches the successful initialisation so repeated calls within the same
    process are instant no-ops.

store_deployment(deployment_id, service, migration_type,
                 connection_pool_change, outcome, change_type,
                 dependencies_changed, root_cause, resolution,
                 recovery_time_minutes, extra_notes) -> None
    Retains one deployment + outcome record as a natural-language memory
    entry. Structured fields are embedded inline in the sentence so
    Hindsight's fact-extraction picks them up for semantic recall.

retrieve_candidates(query) -> list[dict]
    Recalls raw memory objects matching the query string.
    Returns a list of dicts, each with keys:
        id, text, type, entities, context, mentioned_at, document_id, tags
    Does NOT synthesise or count — that is matching.py's job.

retrieve_for_deployment(deployment_id, query, limit) -> list[dict]
    Recalls memory objects scoped to a specific deployment.
    Attribution priority:
        1. tag  deployment:<id>         (canonical — checked first)
        2. document_id == deployment:<id>
        3. metadata.deployment_id == <id>
        4. text fallback — only when text contains "Deployment <id> on"
           AND does NOT contain "Deployment <other-id> on"
    Rejects a memory if it explicitly identifies a different deployment
    via tag, document_id, or metadata, even if the text would match.

count_facts() -> int | None
    Returns the total number of memory objects in the bank, using
    client.list_memories().total. Returns None on any failure.

close() -> None
    Graceful shutdown of the aiohttp session.

What Hindsight recall actually returns (confirmed via docs):
    A ranked list of raw memory objects, not synthesised summaries.
    reflect() is the synthesising call, but we do not use it here.
"""

from __future__ import annotations

import re
import time
from typing import Any

from hindsight_client import Hindsight

from src.config import settings

# ---------------------------------------------------------------------------
# Module-level client — initialised lazily via ensure_bank_exists()
# ---------------------------------------------------------------------------

_client: Hindsight | None = None
_bank_initialised: bool = False   # cached so repeated calls are instant


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

    Caches a successful initialisation in the module-level
    ``_bank_initialised`` flag so that subsequent calls within the same
    process are instant no-ops. This prevents the server from issuing a
    bank-creation round-trip on every incoming request.
    """
    global _bank_initialised
    if _bank_initialised:
        return
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
    _bank_initialised = True


def store_deployment(
    *,
    deployment_id: str,
    service: str,
    migration_type: str,
    connection_pool_change: bool,
    outcome: str,
    change_type: str = "",
    dependencies_changed: bool | None = None,
    root_cause: str = "",
    resolution: str = "",
    recovery_time_minutes: int = 0,
    extra_notes: str = "",
) -> None:
    """
    Retain one deployment record in Hindsight memory.

    The record is stored as a natural-language sentence so Hindsight's
    fact-extraction picks up the structured signals for semantic recall.
    ``change_type`` and ``dependencies_changed`` are included so the
    full 5-signal match context is embedded in the retained text.

    Tags
    ----
    Every retained memory is tagged with "deployment:{deployment_id}".
    This tag is the canonical scoping mechanism for retrieve_for_deployment().
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
    change_type : str
        Structural change category — "infra" | "config" | "code" | "schema".
    dependencies_changed : bool | None
        Whether upstream/downstream service dependencies were changed.
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

    pool_phrase = (
        "included a connection pool change" if connection_pool_change
        else "did not change the connection pool"
    )

    change_ctx = ""
    if change_type:
        change_ctx += f" change_type={change_type}"
    if dependencies_changed is not None:
        change_ctx += f", dependencies_changed={dependencies_changed}"

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
        f"and {pool_phrase}."
    )
    if change_ctx:
        content += f" Structured signals:{change_ctx}."
    content += f" {outcome_sentence}"
    if extra_notes:
        content += f" Additional context: {extra_notes}"

    client.retain(
        bank_id=settings.hindsight_bank_id,
        content=content,
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

    Returns a plain list of dicts (not Hindsight model objects) so callers
    never take a direct dependency on the hindsight_client type hierarchy.

    Each dict contains:
        id, text, type, entities, context, mentioned_at, document_id, tags
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


# Pre-compiled pattern for text fallback: matches "Deployment 184 on"
_DEP_TEXT_PATTERN = re.compile(r"\bDeployment\s+(\d+)\s+on\b", re.IGNORECASE)


def retrieve_for_deployment(
    deployment_id: str,
    query: str,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """
    Recall memory objects scoped to a specific deployment.

    Attribution priority (first matching rule wins):
    ─────────────────────────────────────────────────
    1. tag  ``deployment:<id>``  is present in mem.tags
       → ACCEPT unconditionally.

    2. document_id == ``deployment:<id>``
       → ACCEPT.

    3. metadata.deployment_id == ``<id>``
       → ACCEPT.

    Rejection rules (checked before text fallback):
    ─────────────────────────────────────────────────
    If none of the above matched, the memory is a candidate for text
    fallback ONLY IF it does not carry explicit attribution to a DIFFERENT
    deployment:
        - any tag matching ``deployment:<other-id>``  → REJECT
        - document_id matching ``deployment:<other-id>``  → REJECT
        - metadata.deployment_id != <id> (and not empty)  → REJECT

    Text fallback (only when all explicit-attribution checks pass):
    ─────────────────────────────────────────────────────────────────
    Accept if text contains ``Deployment <id> on``  AND  the text does
    NOT also contain ``Deployment <other-id> on`` for any other numeric
    ID.  A bare ``#184`` without the canonical phrase is not sufficient.

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

    # Wider budget so that even if many results are filtered, we still
    # have enough deployment-tagged records to return.
    approx_max_tokens = min(limit * 4 * 512, 4096)

    result = client.recall(
        bank_id=settings.hindsight_bank_id,
        query=query,
        max_tokens=approx_max_tokens,
        budget="mid",
    )

    memories: list[dict[str, Any]] = []

    for mem in result.results:
        raw_tags: list[str] | None = getattr(mem, "tags", None)
        tags: list[str] = raw_tags if raw_tags else []
        doc_id: str | None = getattr(mem, "document_id", None)
        metadata: dict = getattr(mem, "metadata", None) or {}
        text: str = getattr(mem, "text", "") or ""

        # ── Priority 1: explicit tag ─────────────────────────────────────
        if deployment_tag in tags:
            attribution = "tag"

        # ── Priority 2: document_id ──────────────────────────────────────
        elif doc_id == deployment_tag:
            attribution = "document_id"

        # ── Priority 3: metadata.deployment_id ──────────────────────────
        elif str(metadata.get("deployment_id", "")) == deployment_id:
            attribution = "metadata"

        else:
            # ── Rejection before text fallback ───────────────────────────
            # If any explicit field points to a DIFFERENT deployment, reject.
            other_dep_tag = any(
                t.startswith("deployment:") and t != deployment_tag
                for t in tags
            )
            if other_dep_tag:
                continue

            if doc_id and doc_id.startswith("deployment:") and doc_id != deployment_tag:
                continue

            meta_dep = str(metadata.get("deployment_id", ""))
            if meta_dep and meta_dep != deployment_id:
                continue

            # ── Text fallback ────────────────────────────────────────────
            # Accept only if text contains "Deployment <id> on"
            # AND contains no "Deployment <other-id> on" for any other id.
            ids_in_text = _DEP_TEXT_PATTERN.findall(text)
            if not ids_in_text:
                continue                  # no deployment mentioned in text
            if deployment_id not in ids_in_text:
                continue                  # this deployment not mentioned
            other_ids = [i for i in ids_in_text if i != deployment_id]
            if other_ids:
                continue                  # another deployment also mentioned
            attribution = "text"

        memories.append({
            "id": getattr(mem, "id", None),
            "text": text,
            "type": getattr(mem, "type", ""),
            "entities": getattr(mem, "entities", []),
            "context": getattr(mem, "context", ""),
            "mentioned_at": str(getattr(mem, "mentioned_at", "")),
            "document_id": doc_id,
            "tags": raw_tags,
            "_attribution": attribution,   # diagnostic — stripped by verify only
        })

        if len(memories) >= limit:
            break

    return memories


def count_facts() -> int | None:
    """
    Return the total number of memory objects stored in the bank.

    Uses ``client.list_memories(bank_id).total``.
    Returns ``None`` on any failure (network error, SDK version mismatch, etc.)
    so callers can distinguish "zero facts" from "call failed".
    """
    try:
        client = _get_client()
        result = client.list_memories(bank_id=settings.hindsight_bank_id)
        return result.total
    except Exception:
        return None


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
    global _client, _bank_initialised
    if _client is None:
        return

    import asyncio
    from hindsight_client.hindsight_client import _run_async

    async def _aclose_with_drain() -> None:
        await _client.aclose()          # type: ignore[union-attr]
        await asyncio.sleep(0.250)

    try:
        _run_async(_aclose_with_drain())
    except Exception:
        pass  # best-effort; don't crash on shutdown

    _client = None
    _bank_initialised = False  # reset so a new client can re-initialise
