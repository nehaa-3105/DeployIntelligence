"""
api.py — Minimal FastAPI adapter for Deployment Memory Phase 6.

Exposes exactly two functional endpoints:
    POST /analyze   — runs baseline + memory-informed analysis pipelines
    POST /feedback  — records actual deployment outcome (Phase 5)

Plus:
    GET  /health    — liveness check

The analysis pipeline calls the existing src/matching.py and src/memory.py
functions directly. It does NOT duplicate their logic.

Phase 4 (agent.py) and Phase 5 (analysis.py) are stubs that have not been
implemented yet; this adapter performs the same pipeline those modules would
own, keeping all logic in the existing src/ layer.

Start with:
    uvicorn api:app --reload --port 8000
"""

from __future__ import annotations

import datetime
import os
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

load_dotenv()

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Deployment Memory API",
    description="Minimal API adapter for the Deployment Memory project.",
    version="1.0.0",
)

# Allow the React dev server (Vite default: 5173) and any localhost origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class AnalyzeRequest(BaseModel):
    """Input signals for a proposed deployment."""
    deployment_id: str = Field(default="297", description="Unique identifier for this deployment")
    service: str = Field(..., description="Service name, e.g. 'payment-service'")
    migration_type: str = Field(..., description="'schema' | 'read-replica' | 'config-only' | 'infra-only' | 'code-only'")
    connection_pool_change: bool = Field(..., description="Whether the deployment changes connection pool settings")
    change_type: str = Field(default="infra", description="'infra' | 'config' | 'code' | 'schema'")
    dependencies_changed: bool | None = Field(default=None, description="Whether upstream/downstream deps changed")


class SignalMatchOut(BaseModel):
    signal: str
    matched: bool
    proposed_value: Any
    historical_value: Any


class HistoricalDeploymentOut(BaseModel):
    deployment_id: str
    service: str
    migration_type: str
    connection_pool_change: bool
    outcome: str
    similarity_score: int
    matched_signals: list[str]
    hindsight_evidence: list[str]   # raw text snippets from Hindsight


class AnalysisOut(BaseModel):
    mode: str                        # "baseline" | "memory"
    risk_level: str                  # "low" | "medium" | "high"
    reasoning: str
    recommendation: str
    cited_deployment_ids: list[str]
    historical_deployments: list[HistoricalDeploymentOut]


class AnalyzeResponse(BaseModel):
    deployment_id: str
    baseline: AnalysisOut
    memory_informed: AnalysisOut


class FeedbackRequest(BaseModel):
    deployment_id: str = Field(..., description="ID of the deployment being reported on")
    outcome: str = Field(..., description="'success' | 'incident'")
    root_cause: str = Field(default="", description="For incidents: short root cause description")
    resolution: str = Field(default="", description="For incidents: what fixed it")
    recovery_time_minutes: int = Field(default=0, description="For incidents: recovery time in minutes")
    service: str = Field(default="", description="Service name (used when recording the outcome)")
    migration_type: str = Field(default="", description="Migration type (used when recording the outcome)")
    connection_pool_change: bool = Field(default=False)


class FeedbackResponse(BaseModel):
    status: str
    message: str


# ---------------------------------------------------------------------------
# Hardcoded historical dataset (mirrors verify_matching.py)
# This is the same dataset used in the Phase 3 verification.
# ---------------------------------------------------------------------------

def _historical_records():
    """Return the hardcoded historical deployment records for the demo."""
    from src.models import Deployment
    return [
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
            notes="Same service and migration type, but no pool change. Clean deploy.",
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


# ---------------------------------------------------------------------------
# Analysis helpers — baseline (no memory)
# ---------------------------------------------------------------------------

_RISK_RULES = {
    # (migration_type, connection_pool_change) → risk
    ("schema", True): "high",
    ("schema", False): "medium",
    ("read-replica", True): "medium",
    ("read-replica", False): "low",
    ("infra-only", True): "medium",
    ("infra-only", False): "low",
    ("config-only", True): "low",
    ("config-only", False): "low",
    ("code-only", True): "low",
    ("code-only", False): "low",
}

_REASONING_TEMPLATES = {
    "high": (
        "This deployment combines a {migration_type} migration with a connection pool "
        "change on {service}. Schema migrations alter the database structure while "
        "simultaneous pool changes affect connection availability. Together these "
        "represent a high-risk combination that can trigger cascading failures under "
        "traffic load."
    ),
    "medium": (
        "This deployment involves a {migration_type} migration on {service}. "
        "Without a concurrent pool change the blast radius is reduced, but schema "
        "migrations still carry inherent rollback complexity and potential downtime "
        "if applied without proper safeguards."
    ),
    "low": (
        "This deployment on {service} is a {migration_type} change. "
        "The risk profile is low based on the change type and absence of "
        "connection pool modifications. Standard deployment practices apply."
    ),
}

_RECOMMENDATION_TEMPLATES = {
    "high": (
        "Implement staged rollout across canary instances before full promotion. "
        "Pre-scale connection pool headroom by at least 30% before migration begins. "
        "Set up real-time pool utilisation monitoring with automated rollback triggers. "
        "Schedule during lowest-traffic window and have DBA on call."
    ),
    "medium": (
        "Test the migration on a staging environment that mirrors production traffic. "
        "Have a rollback script validated and ready. "
        "Monitor error rates and latency for 15 minutes post-deployment before "
        "declaring success."
    ),
    "low": (
        "Follow standard deployment checklist. "
        "Monitor application health metrics for 5 minutes post-deployment."
    ),
}


def _baseline_analysis(deployment) -> AnalysisOut:
    """
    Rule-based baseline analysis. No memory retrieval.
    Mimics what the LLM agent (agent.py) would produce in baseline mode.
    """
    key = (deployment.migration_type.lower(), deployment.connection_pool_change)
    risk = _RISK_RULES.get(key, "medium")

    reasoning = _REASONING_TEMPLATES[risk].format(
        migration_type=deployment.migration_type,
        service=deployment.service,
    )
    recommendation = _RECOMMENDATION_TEMPLATES[risk]

    return AnalysisOut(
        mode="baseline",
        risk_level=risk,
        reasoning=reasoning,
        recommendation=recommendation,
        cited_deployment_ids=[],
        historical_deployments=[],
    )


# ---------------------------------------------------------------------------
# Analysis helpers — memory-informed
# ---------------------------------------------------------------------------

def _memory_informed_analysis(deployment, historical_records) -> AnalysisOut:
    """
    Memory-informed analysis using src/matching.py + src/memory.py.
    Calls find_similar() with the real retrieve_for_deployment recall function.

    If Hindsight / config is unavailable (e.g. API keys not yet set), degrades
    gracefully: structural matching still runs, hindsight_evidence will be empty,
    but candidate deployments and risk assessment are still returned.
    """
    from src.matching import find_similar

    # Attempt to wire in real Hindsight recall. Degrade gracefully on any failure
    # so a missing .env doesn't crash the entire analysis pipeline.
    recall_fn = lambda deployment_id, query: []   # default: no-op
    try:
        from src.memory import ensure_bank_exists, retrieve_for_deployment
        ensure_bank_exists()
        recall_fn = retrieve_for_deployment
    except Exception:
        # Hindsight unavailable or keys not configured — structural matching continues
        pass

    match_summary = find_similar(
        proposed=deployment,
        historical_records=historical_records,
        recall_fn=recall_fn,
        threshold=2,
    )

    # Build historical deployment output objects
    hist_out: list[HistoricalDeploymentOut] = []
    cited_ids: list[str] = []

    for candidate in match_summary.candidates:
        d = candidate.deployment
        matched_signals = [s.signal for s in candidate.signal_matches if s.matched]
        # Extract readable text snippets from Hindsight evidence
        evidence_texts = [
            mem["text"] for mem in candidate.hindsight_memories
            if mem.get("text")
        ]
        hist_out.append(HistoricalDeploymentOut(
            deployment_id=d.deployment_id,
            service=d.service,
            migration_type=d.migration_type,
            connection_pool_change=d.connection_pool_change,
            outcome=d.outcome,
            similarity_score=candidate.similarity_score,
            matched_signals=matched_signals,
            hindsight_evidence=evidence_texts,
        ))
        cited_ids.append(d.deployment_id)

    # Elevate risk based on memory evidence
    incident_candidates = [
        c for c in match_summary.candidates if c.deployment.outcome == "incident"
    ]

    if match_summary.confidence_label == "high":
        risk = "high"
    elif match_summary.confidence_label == "medium" and incident_candidates:
        risk = "high"   # memory upgrades medium baseline to high when incidents found
    elif match_summary.confidence_label in ("medium", "low") and incident_candidates:
        risk = "medium"
    else:
        # Fall back to baseline rule
        key = (deployment.migration_type.lower(), deployment.connection_pool_change)
        risk = _RISK_RULES.get(key, "medium")

    # Build reasoning that explicitly cites the matched historical deployments
    if incident_candidates:
        incident_ids = [c.deployment.deployment_id for c in incident_candidates]
        id_list = ", ".join(f"#{i}" for i in incident_ids)
        reasoning = (
            f"Organisational memory contains {match_summary.total_similar} similar "
            f"past deployment(s) for {deployment.service}, of which "
            f"{match_summary.total_incidents} resulted in incidents "
            f"(confidence: {match_summary.confidence_label}). "
            f"The most relevant is deployment #{incident_candidates[0].deployment.deployment_id}, "
            f"which shares {incident_candidates[0].similarity_score}/5 signals with this "
            f"proposed deployment and resulted in an incident. "
        )
        # Append Hindsight evidence text if available
        top_evidence = incident_candidates[0].hindsight_memories
        if top_evidence:
            reasoning += f"Memory evidence: {top_evidence[0]['text']}"
        else:
            reasoning += (
                f"That deployment ({incident_candidates[0].deployment.notes or 'see historical record'}) "
                f"is a strong signal that this deployment carries elevated risk."
            )
    elif match_summary.total_similar > 0:
        reasoning = (
            f"Organisational memory contains {match_summary.total_similar} similar "
            f"past deployment(s) for {deployment.service}, none of which resulted "
            f"in incidents (confidence: {match_summary.confidence_label}). "
            f"Historical evidence suggests this change type is generally safe on this service."
        )
    else:
        reasoning = (
            f"No sufficiently similar historical deployments found in organisational memory "
            f"for {deployment.service} with these signals. "
            f"Falling back to rule-based risk assessment."
        )

    # Recommendation incorporates the specific mitigation from incident history
    if incident_candidates:
        top = incident_candidates[0]
        d184_notes = top.deployment.notes or ""
        # Try to get resolution from Hindsight evidence text
        resolution_hint = ""
        for mem in top.hindsight_memories:
            txt = mem.get("text", "")
            if "resolution" in txt.lower() or "staged" in txt.lower() or "pool" in txt.lower():
                resolution_hint = txt
                break

        if resolution_hint:
            recommendation = (
                f"Based on deployment #{top.deployment.deployment_id}'s incident history: "
                f"{resolution_hint} "
                f"Additionally: {_RECOMMENDATION_TEMPLATES.get(risk, _RECOMMENDATION_TEMPLATES['high'])}"
            )
        else:
            recommendation = (
                f"Deployment #{top.deployment.deployment_id} previously caused a connection "
                f"pool exhaustion incident on {top.deployment.service}. "
                f"Apply staged rollout with connection pool size monitoring. "
                f"Pre-scale pool headroom before migration and automate rollback if pool "
                f"utilisation exceeds 80% within 10 minutes of deployment."
            )
    else:
        recommendation = _RECOMMENDATION_TEMPLATES.get(risk, _RECOMMENDATION_TEMPLATES["low"])

    return AnalysisOut(
        mode="memory",
        risk_level=risk,
        reasoning=reasoning,
        recommendation=recommendation,
        cited_deployment_ids=cited_ids,
        historical_deployments=hist_out,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
def health() -> dict:
    """Liveness check."""
    return {"status": "ok", "service": "deployment-memory-api"}


@app.post("/analyze", response_model=AnalyzeResponse)
def analyze(req: AnalyzeRequest) -> AnalyzeResponse:
    """
    Run both baseline and memory-informed analysis for a proposed deployment.

    Returns both AnalysisOut objects so the React UI can display them
    side-by-side without making two separate requests.
    """
    from src.models import Deployment

    if not req.service.strip():
        raise HTTPException(status_code=422, detail="'service' must not be empty.")
    if not req.migration_type.strip():
        raise HTTPException(status_code=422, detail="'migration_type' must not be empty.")

    deployment = Deployment(
        deployment_id=req.deployment_id,
        service=req.service.strip(),
        migration_type=req.migration_type.strip().lower(),
        connection_pool_change=req.connection_pool_change,
        change_type=req.change_type.strip().lower(),
        timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        outcome="pending",
        dependencies_changed=req.dependencies_changed,
    )

    historical = _historical_records()

    try:
        baseline = _baseline_analysis(deployment)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Baseline analysis failed: {exc}")

    try:
        memory_informed = _memory_informed_analysis(deployment, historical)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Memory-informed analysis failed: {exc}")

    return AnalyzeResponse(
        deployment_id=req.deployment_id,
        baseline=baseline,
        memory_informed=memory_informed,
    )


@app.post("/feedback", response_model=FeedbackResponse)
def feedback(req: FeedbackRequest) -> FeedbackResponse:
    """
    Record the actual outcome of a deployment (Phase 5 feedback).

    Calls src/memory.store_deployment() with the outcome so the next
    analysis will incorporate this deployment's result.
    """
    if req.outcome not in ("success", "incident"):
        raise HTTPException(
            status_code=422,
            detail="outcome must be 'success' or 'incident'."
        )

    try:
        from src.memory import ensure_bank_exists, store_deployment
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                f"Memory backend unavailable (check HINDSIGHT_API_KEY in .env): {exc}"
            ),
        )

    try:
        ensure_bank_exists()
        store_deployment(
            deployment_id=req.deployment_id,
            service=req.service or "unknown-service",
            migration_type=req.migration_type or "unknown",
            connection_pool_change=req.connection_pool_change,
            outcome=req.outcome,
            root_cause=req.root_cause,
            resolution=req.resolution,
            recovery_time_minutes=req.recovery_time_minutes,
        )
        return FeedbackResponse(
            status="ok",
            message=(
                f"Outcome '{req.outcome}' recorded for deployment #{req.deployment_id}. "
                "Future analyses will incorporate this result."
            ),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to record outcome: {exc}"
        )
