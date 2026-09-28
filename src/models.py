"""
Data models for Deployment Memory.

Defines the core Pydantic schemas shared across matching, memory, agent,
and analysis modules. All modules import types from here — no type
definitions live elsewhere.

Models
------
Deployment
    A proposed or historical deployment record. Core fields drive matching
    logic; optional fields exist for realism in the seed dataset only.

Incident
    An incident record linked to a past deployment by deployment_id.

SignalMatch
    The result of comparing one signal between two deployments.
    matched: bool, signal name, proposed value, historical value.

MatchCandidate
    A historical deployment that passed the >= 2 signal threshold.
    Carries its similarity score, the list of matching signals, and
    the recalled Hindsight evidence for that deployment.

MatchSummary
    The full output of the matching pipeline for one proposed deployment.
    Contains all candidates (ranked by score), plus aggregate counts
    computed deterministically in code — never by an LLM.

AnalysisMode
    Enum: "baseline" | "memory". Controls which path analyze_deployment()
    takes. Baseline ignores memory entirely; memory uses full retrieval.

RelevantDeployment
    Compact reference to a historically similar deployment cited in an
    AnalysisResult. Populated only in MEMORY mode.

AnalysisResult
    The output of analyze_deployment(). Same schema for both modes so the
    UI can render them side-by-side without branching.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Core deployment record
# ---------------------------------------------------------------------------

class Deployment(BaseModel):
    """
    A proposed or historical deployment record.

    Core fields (drive matching logic):
        deployment_id         — unique identifier, e.g. "184"
        service               — service name, e.g. "payment-service"
        migration_type        — "schema" | "read-replica" | "config-only" |
                                "infra-only" | "code-only"
        connection_pool_change — whether the deployment changed pool settings
        change_type           — "infra" | "config" | "code" | "schema"
        timestamp             — ISO 8601 string; used for ordering only
        outcome               — "incident" | "success" | "pending"
                                "pending" = not yet known (proposed deployments)

    Optional fields (realism only, do not drive logic):
        dependencies_changed  — whether upstream/downstream deps changed
        config_changes        — free-text description of config changes
        ci_result             — "pass" | "fail" | "skip"
        notes                 — free-text for seed dataset realism
    """

    deployment_id: str
    service: str
    migration_type: str
    connection_pool_change: bool
    change_type: str
    timestamp: str
    outcome: str = "pending"

    # Optional fields — do not drive matching or risk logic
    dependencies_changed: bool | None = None
    config_changes: str | None = None
    ci_result: str | None = None
    notes: str | None = None


# ---------------------------------------------------------------------------
# Incident record
# ---------------------------------------------------------------------------

class Incident(BaseModel):
    """
    An incident record linked to a past deployment.

    Stored separately from Deployment so a deployment can exist without
    an incident (outcome == "success"), and the incident details are only
    populated for outcome == "incident" records.
    """

    incident_id: str
    deployment_id: str
    severity: str                   # "sev1" | "sev2" | "sev3"
    root_cause: str
    resolution: str
    recovery_time_minutes: int


# ---------------------------------------------------------------------------
# Matching models
# ---------------------------------------------------------------------------

SIGNAL_NAMES = ("service", "migration_type", "connection_pool_change",
                "change_type", "dependencies_changed")
"""
The five structural signals used for deterministic matching.
Order is stable — used for display and scoring.
"""


class SignalMatch(BaseModel):
    """Result of comparing one signal between proposed and historical deployments."""

    signal: str
    matched: bool
    proposed_value: Any
    historical_value: Any


class MatchCandidate(BaseModel):
    """
    A historical deployment that passed the >= 2 signal threshold.

    Fields
    ------
    deployment      — the full historical Deployment record
    similarity_score — number of matched signals out of 5 (int, 0–5)
    signal_matches  — per-signal breakdown (all 5, matched or not)
    hindsight_memories — raw memory dicts recalled from Hindsight for this
                         deployment. Each dict: {id, text, type, entities,
                         context, mentioned_at}. Empty list if recall returned
                         nothing (network issue, not yet processed, etc.)
    """

    deployment: Deployment
    similarity_score: int = Field(ge=0, le=5)
    signal_matches: list[SignalMatch]
    hindsight_memories: list[dict[str, Any]] = Field(default_factory=list)


class MatchSummary(BaseModel):
    """
    Full output of the matching pipeline for one proposed deployment.

    All counts are computed deterministically from the candidate list.
    They are never asserted by an LLM.

    Fields
    ------
    proposed            — the deployment being analysed
    candidates          — MatchCandidates with score >= 2, ranked by
                          similarity_score descending
    total_similar       — len(candidates)
    total_incidents     — candidates whose outcome == "incident"
    total_successes     — candidates whose outcome == "success"
    confidence_label    — deterministic string derived from the ratio:
                          "high" if total_incidents / total_similar >= 0.67
                          "medium" if ratio >= 0.33
                          "low" otherwise (or if total_similar == 0 → "none")
    """

    proposed: Deployment
    candidates: list[MatchCandidate]
    total_similar: int
    total_incidents: int
    total_successes: int
    confidence_label: str           # "none" | "low" | "medium" | "high"


# ---------------------------------------------------------------------------
# Analysis models
# ---------------------------------------------------------------------------

class AnalysisMode(str, Enum):
    """Controls which analysis path analyze_deployment() takes."""

    BASELINE = "baseline"
    MEMORY = "memory"


class RelevantDeployment(BaseModel):
    """
    Compact reference to a historically similar deployment included in an
    AnalysisResult. Populated only in MEMORY mode; empty list in BASELINE.

    Fields
    ------
    deployment_id   — unique identifier of the historical deployment
    similarity_score — number of matched signals out of 5 (from matching)
    outcome         — "incident" | "success"
    service         — service name
    migration_type  — migration type string
    """

    deployment_id: str
    similarity_score: int
    outcome: str
    service: str
    migration_type: str


class AnalysisResult(BaseModel):
    """
    Output of analyze_deployment(). Same schema for both modes so the UI
    can render baseline and memory results side-by-side without branching.

    Fields populated in both modes:
        mode, risk_assessment, summary, recommendation,
        risk_level, reasoning

    Fields populated only in memory mode (empty/None in baseline):
        match_summary, cited_deployment_ids, relevant_deployments, evidence
    """

    mode: AnalysisMode

    # Phase 4 canonical output fields (spec-required)
    risk_assessment: str                # "low" | "medium" | "high"
    summary: str                        # one-paragraph LLM narrative
    recommendation: str                 # LLM mitigation advice
    relevant_deployments: list[RelevantDeployment] = Field(default_factory=list)
    evidence: str                       # LLM-produced evidence summary; empty str in baseline

    # Legacy aliases kept so nothing that already reads these breaks
    risk_level: str                     # mirrors risk_assessment
    reasoning: str                      # mirrors summary

    # Memory-mode extras
    match_summary: MatchSummary | None = None
    cited_deployment_ids: list[str] = Field(default_factory=list)
