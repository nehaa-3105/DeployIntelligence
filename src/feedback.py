"""
Manual deployment outcome feedback for Deployment Memory.

Phase 5: allows engineers to record the actual outcome of a completed
deployment into the persistent Hindsight memory bank.  The recorded
outcome then becomes available to future memory-informed analyses of
structurally similar proposed deployments.

Public API
----------
record_outcome(deployment, outcome, root_cause, resolution,
               recovery_time_minutes, notes) -> None

    Persist the manually supplied outcome for a completed deployment.
    Delegates directly to memory.store_deployment() — no second
    Hindsight client or bank is created.

Design notes
------------
- Manual input only.  There is no automatic outcome detection and no
  integration with a deployment pipeline.
- The caller is responsible for supplying accurate outcome information.
  This module performs no validation beyond what Pydantic enforces on
  the Deployment model passed in.
- Idempotency: calling record_outcome() more than once for the same
  deployment_id appends an additional Hindsight memory entry.  Hindsight
  handles duplicates at recall time via semantic ranking; the extra entry
  does not break retrieval but callers should avoid unnecessary repeats.
- The bank is created idempotently on every call (ensure_bank_exists()
  is safe to call at any time).
"""

from __future__ import annotations

from src.memory import ensure_bank_exists, store_deployment
from src.models import Deployment


def record_outcome(
    deployment: Deployment,
    outcome: str,
    *,
    root_cause: str = "",
    resolution: str = "",
    recovery_time_minutes: int = 0,
    notes: str = "",
) -> None:
    """
    Persist a manually supplied deployment outcome to Hindsight memory.

    The retained memory sentence embeds all structured fields from the
    Deployment object (service, migration_type, connection_pool_change,
    change_type) alongside the manually provided outcome details, so that
    a later retrieve_for_deployment() or retrieve_candidates() call can
    surface the entry when a structurally similar deployment is analysed.

    Parameters
    ----------
    deployment : Deployment
        The completed deployment whose outcome is being recorded.
        deployment.deployment_id is used as the unique memory key.
        deployment.outcome is IGNORED — the caller-supplied ``outcome``
        parameter is the authoritative source of truth here, because
        the Deployment object may still carry outcome="pending" from
        the pre-deployment analysis phase.
    outcome : str
        The actual outcome as observed after the deployment completed.
        Must be "incident" or "success".
    root_cause : str
        For incidents: a brief description of what caused the incident.
        Leave empty for successful deployments.
    resolution : str
        For incidents: what action resolved the incident.
        Leave empty for successful deployments.
    recovery_time_minutes : int
        For incidents: how many minutes elapsed between incident start
        and resolution.  Defaults to 0.
    notes : str
        Optional free-text context, e.g. traffic conditions at the time,
        observations during rollback, post-mortem summary link, etc.

    Raises
    ------
    ValueError
        Propagated from config.Settings if GEMINI_API_KEY or
        HINDSIGHT_API_KEY are absent (settings is imported at module
        level via memory.py).
    """
    if outcome not in ("incident", "success"):
        raise ValueError(
            f"outcome must be 'incident' or 'success', got {outcome!r}. "
            "Only completed deployments with a known outcome should be recorded."
        )

    # Ensure the Hindsight bank exists before writing.
    # memory.ensure_bank_exists() is idempotent — safe to call every time.
    ensure_bank_exists()

    # Build the change_type + pool phrase note so full deployment context
    # is embedded in the memory text for richer semantic retrieval.
    change_ctx = (
        f"change_type={deployment.change_type}"
        + (
            f", dependencies_changed={deployment.dependencies_changed}"
            if deployment.dependencies_changed is not None
            else ""
        )
    )

    extra = f"[manual outcome feedback] {change_ctx}"
    if notes:
        extra += f". {notes}"

    store_deployment(
        deployment_id=deployment.deployment_id,
        service=deployment.service,
        migration_type=deployment.migration_type,
        connection_pool_change=deployment.connection_pool_change,
        outcome=outcome,
        root_cause=root_cause,
        resolution=resolution,
        recovery_time_minutes=recovery_time_minutes,
        extra_notes=extra,
    )
