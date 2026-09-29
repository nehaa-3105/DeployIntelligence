"""
api.py — FastAPI adapter for Deployment Memory (Phase 1).

Endpoints
---------
GET  /health
POST /analyze
POST /feedback
GET  /deployments
GET  /memory/overview

Rules enforced here
-------------------
- Historical records come ONLY from store.known_outcome_records().
- Baseline analysis is NEVER given historical records or Hindsight data.
- Memory reasoning uses ONLY real candidate IDs, scores, outcomes,
  root_cause, resolution and Hindsight evidence — zero fabricated text.
- No hardcoded analysis strings, mitigation text, or counts.
- Pending records never appear in known_outcome_records() (enforced by store).
- CORS_ORIGINS read from .env; merged with localhost defaults.
"""

from __future__ import annotations

import datetime
import os
import time
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

load_dotenv()

# ---------------------------------------------------------------------------
# App + CORS
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Deployment Memory API",
    description="Phase 1 — backend learning loop.",
    version="1.0.0",
)

_LOCALHOST_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:3000",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:3000",
    "https://deploy-intelligence.vercel.app",
]

def _cors_origins() -> list[str]:
    """Read CORS_ORIGINS from env (comma-separated) and merge with known origins."""
    raw = os.environ.get("CORS_ORIGINS", "")
    extra = [o.strip() for o in raw.split(",") if o.strip()]
    combined = list({*_LOCALHOST_ORIGINS, *extra})
    return combined

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Startup bootstrap — reconstruct local ledger on Render's ephemeral FS
# ---------------------------------------------------------------------------
# Render wipes the filesystem on every deploy.  This call writes the 10
# canonical SEED_RECORDS into data/deployments.json when the file is missing
# or empty, so /memory/overview and /deployments are never empty on a fresh
# instance.  It is a pure ledger write — it does NOT call Hindsight retain()
# and does NOT touch the production Hindsight bank.
from src.ingestion import bootstrap_ledger_if_empty as _bootstrap
_bootstrap()

# ---------------------------------------------------------------------------
# Signal legend — the five canonical matching signals
# ---------------------------------------------------------------------------

SIGNAL_LEGEND = [
    {
        "signal": "service",
        "description": "Exact service name match",
        "type": "string",
    },
    {
        "signal": "migration_type",
        "description": "Exact migration type match (schema / read-replica / config-only / infra-only / code-only)",
        "type": "string",
    },
    {
        "signal": "connection_pool_change",
        "description": "Whether the deployment changes connection pool settings",
        "type": "boolean",
    },
    {
        "signal": "change_type",
        "description": "Structural change category (infra / config / code / schema)",
        "type": "string",
    },
    {
        "signal": "dependencies_changed",
        "description": "Whether upstream or downstream service dependencies were changed",
        "type": "boolean",
    },
]

# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class AnalyzeRequest(BaseModel):
    deployment_id: str = Field(..., description="Unique identifier for this deployment")
    service: str = Field(..., description="Service name")
    migration_type: str = Field(..., description="'schema' | 'read-replica' | 'config-only' | 'infra-only' | 'code-only'")
    connection_pool_change: bool = Field(..., description="Whether pool settings are changed")
    change_type: str = Field(default="infra", description="'infra' | 'config' | 'code' | 'schema'")
    dependencies_changed: bool | None = Field(default=None, description="Whether deps changed")
    rerun: bool = Field(default=False, description="When True, skip_same_id=False so the deployment's own record can appear as a candidate")


class HindsightEvidenceItem(BaseModel):
    text: str
    attribution: str   # "tag" | "document_id" | "metadata" | "text" | "unknown"
    memory_id: str | None = None


class HistoricalDeploymentOut(BaseModel):
    deployment_id: str
    service: str
    migration_type: str
    change_type: str
    connection_pool_change: bool
    dependencies_changed: bool | None
    timestamp: str
    outcome: str
    similarity_score: int
    matched_signals: list[str]
    signals: dict[str, Any]            # proposed vs historical per-signal breakdown
    root_cause: str
    resolution: str
    key_note: str
    hindsight_status: str              # "recalled" | "empty" | "unavailable" | "not_recalled"
    hindsight_evidence: list[HindsightEvidenceItem]


class PatternSummaryOut(BaseModel):
    total_similar: int
    total_incidents: int
    total_successes: int
    confidence_label: str
    headline: str                      # dynamically computed, never hardcoded


class AnalysisOut(BaseModel):
    risk_assessment: str
    summary: str
    recommendation: str
    evidence: str
    pattern_summary: PatternSummaryOut | None
    historical_deployments: list[HistoricalDeploymentOut]


class AnalyzeResponse(BaseModel):
    deployment_id: str
    rerun: bool
    memory_records: int
    hindsight_status: str              # "ok" | "unavailable"
    signal_legend: list[dict]
    latency_ms: int
    baseline: AnalysisOut
    memory_informed: AnalysisOut


class FeedbackRequest(BaseModel):
    deployment_id: str = Field(..., description="ID of the deployment being reported on")
    outcome: str = Field(..., description="'success' | 'incident'")
    notes: str = Field(default="", description="Free-text notes; for incidents used as root-cause input")
    service: str = Field(default="")
    migration_type: str = Field(default="")
    change_type: str = Field(default="")
    connection_pool_change: bool = Field(default=False)
    dependencies_changed: bool | None = Field(default=None)


class StoredMemoryOut(BaseModel):
    deployment_id: str
    service: str
    migration_type: str
    change_type: str
    connection_pool_change: bool
    outcome: str
    lesson: str | None
    recorded_at: str | None
    hindsight_evidence_preview: str | None


class FeedbackResponse(BaseModel):
    status: str
    message: str
    memory_records_before: int
    memory_records_after: int
    hindsight_indexed: bool
    stored_memory: StoredMemoryOut


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _records_to_deployments(records: list[dict]):
    """Convert ledger dicts to Deployment model objects."""
    from src.models import Deployment
    deps = []
    for r in records:
        deps.append(Deployment(
            deployment_id=r["deployment_id"],
            service=r["service"],
            migration_type=r["migration_type"],
            connection_pool_change=r["connection_pool_change"],
            change_type=r.get("change_type", ""),
            timestamp=r.get("timestamp", ""),
            outcome=r["outcome"],
            dependencies_changed=r.get("dependencies_changed"),
        ))
    return deps


def _headline(total_similar: int, total_incidents: int) -> str:
    """
    Dynamically generate the pattern summary headline from real counts.
    Never hardcoded.
    """
    if total_similar == 0:
        return "No similar historical deployments found"
    if total_incidents == 0:
        return f"0 of {total_similar} similar deployment(s) caused an incident"
    return f"{total_incidents} of {total_similar} similar deployment(s) caused an incident"


def _key_note(rec: dict) -> str:
    """
    Derive a key note from real field values only.
    For incidents: use root_cause.
    For successes: derive from real fields — pool change status.
    Never fabricate text.
    """
    outcome = rec.get("outcome", "")
    root_cause = (rec.get("root_cause") or "").strip()
    if outcome == "incident":
        return root_cause if root_cause else "Incident — no root cause recorded"
    # success
    pool = rec.get("connection_pool_change", False)
    if pool:
        return "Pool change — no incident"
    return "No pool change"


def _hindsight_evidence_items(memories: list[dict]) -> list[HindsightEvidenceItem]:
    items = []
    for m in memories:
        text = (m.get("text") or "").strip()
        if not text:
            continue
        items.append(HindsightEvidenceItem(
            text=text,
            attribution=m.get("_attribution", "unknown"),
            memory_id=m.get("id"),
        ))
    return items


def _candidate_hindsight_status(memories: list[dict], recall_attempted: bool) -> str:
    if not recall_attempted:
        return "not_recalled"
    if not memories:
        return "empty"
    return "recalled"


def _build_historical_out(
    candidates,
    hindsight_ok: bool,
) -> list[HistoricalDeploymentOut]:
    """
    Build HistoricalDeploymentOut list from MatchCandidate objects.
    Uses only real field values from the ledger and real Hindsight evidence.
    """
    from src.store import get as ledger_get

    out = []
    for cand in candidates:
        d = cand.deployment
        matched_signals = [s.signal for s in cand.signal_matches if s.matched]

        # Build per-signal breakdown from real values
        signals_detail: dict[str, Any] = {}
        for sm in cand.signal_matches:
            signals_detail[sm.signal] = {
                "matched": sm.matched,
                "proposed": sm.proposed_value,
                "historical": sm.historical_value,
            }

        # Prefer ledger record for root_cause/resolution (more complete than Deployment model)
        ledger_rec = ledger_get(d.deployment_id) or {}
        root_cause = (ledger_rec.get("root_cause") or "").strip()
        resolution = (ledger_rec.get("resolution") or "").strip()

        memories = cand.hindsight_memories
        status = _candidate_hindsight_status(memories, recall_attempted=hindsight_ok)

        out.append(HistoricalDeploymentOut(
            deployment_id=d.deployment_id,
            service=d.service,
            migration_type=d.migration_type,
            change_type=d.change_type,
            connection_pool_change=d.connection_pool_change,
            dependencies_changed=d.dependencies_changed,
            timestamp=d.timestamp,
            outcome=d.outcome,
            similarity_score=cand.similarity_score,
            matched_signals=matched_signals,
            signals=signals_detail,
            root_cause=root_cause,
            resolution=resolution,
            key_note=_key_note(ledger_rec if ledger_rec else {
                "outcome": d.outcome,
                "root_cause": root_cause,
                "connection_pool_change": d.connection_pool_change,
            }),
            hindsight_status=status,
            hindsight_evidence=_hindsight_evidence_items(memories),
        ))
    return out


def _build_memory_out(
    match_summary,
    hindsight_ok: bool,
    baseline_out: AnalysisOut,
) -> AnalysisOut:
    """
    Build the memory-informed AnalysisOut from a real MatchSummary.

    Recommendation is derived from the top incident candidate's real
    root_cause + resolution (from ledger).  If no resolution exists, the
    baseline recommendation is used with a note that no prior fix was recorded.

    Never fabricates evidence text.
    """
    from src.store import get as ledger_get

    ms = match_summary
    hist_out = _build_historical_out(ms.candidates, hindsight_ok)

    # Gather real Hindsight evidence texts from all candidates
    evidence_lines: list[str] = []
    for cand in ms.candidates:
        for m in cand.hindsight_memories:
            txt = (m.get("text") or "").strip()
            if txt:
                dep_id = cand.deployment.deployment_id
                evidence_lines.append(f"[#{dep_id}] {txt}")

    evidence_block = "\n".join(evidence_lines) if evidence_lines else ""

    # Recommendation: use the top incident candidate's real resolution if available
    incident_candidates = [c for c in ms.candidates if c.deployment.outcome == "incident"]
    recommendation = baseline_out.recommendation  # fallback to baseline

    cited_note = ""
    if incident_candidates:
        top_inc = incident_candidates[0]
        dep_id = top_inc.deployment.deployment_id
        ledger_rec = ledger_get(dep_id) or {}
        resolution = (ledger_rec.get("resolution") or "").strip()
        root_cause = (ledger_rec.get("root_cause") or "").strip()

        if resolution:
            recommendation = (
                f"Deployment #{dep_id} previously resolved a similar incident by: {resolution}. "
                f"Apply the same mitigation before proceeding."
            )
        else:
            recommendation = (
                f"Deployment #{dep_id} caused a similar incident"
                + (f" (root cause: {root_cause})" if root_cause else "")
                + ". No prior resolution recorded — proceed with caution and have a rollback plan ready."
            )
        cited_note = f"#{dep_id}"

    # Summary: derive from real match counts and confidence
    if ms.total_similar == 0:
        summary = (
            "No historically similar deployments found in organisational memory. "
            "Risk assessment is based on deployment structure alone."
        )
    else:
        summary = (
            f"Organisational memory contains {ms.total_similar} similar past deployment(s) "
            f"for {ms.proposed.service}, of which {ms.total_incidents} resulted in incidents "
            f"(confidence: {ms.confidence_label})."
        )
        if incident_candidates:
            top = incident_candidates[0]
            summary += (
                f" The highest-similarity incident is deployment #{top.deployment.deployment_id} "
                f"({top.similarity_score}/5 signals matched)."
            )
        if cited_note:
            summary += f" Key reference: {cited_note}."

    pattern_summary = PatternSummaryOut(
        total_similar=ms.total_similar,
        total_incidents=ms.total_incidents,
        total_successes=ms.total_successes,
        confidence_label=ms.confidence_label,
        headline=_headline(ms.total_similar, ms.total_incidents),
    )

    return AnalysisOut(
        risk_assessment=baseline_out.risk_assessment,  # structural risk unchanged
        summary=summary,
        recommendation=recommendation,
        evidence=evidence_block,
        pattern_summary=pattern_summary,
        historical_deployments=hist_out,
    )


def _recall_fn_with_status(deployment_id: str, query: str) -> tuple[list[dict], str]:
    """
    Call retrieve_for_deployment and return (memories, status).
    Status: "ok" on success, "unavailable" on any exception.
    """
    try:
        from src.memory import retrieve_for_deployment
        memories = retrieve_for_deployment(deployment_id=deployment_id, query=query)
        return memories, "ok"
    except Exception:
        return [], "unavailable"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
def health() -> dict:
    """Liveness check. records comes from retained_count(), not hardcoded."""
    from src.store import retained_count
    return {
        "status": "ok",
        "service": "deployment-memory",
        "records": retained_count(),
    }


@app.post("/analyze", response_model=AnalyzeResponse)
def analyze(req: AnalyzeRequest) -> AnalyzeResponse:
    """
    Run baseline + memory-informed analysis for a proposed deployment.

    - Historical records come from store.known_outcome_records() only.
    - Baseline receives NO historical data.
    - Memory reasoning uses only real candidate data + Hindsight evidence.
    - Pending records are excluded from historical matching.
    - If rerun=True, skip_same_id=False so the deployment's own ledger
      record (after feedback) appears as a candidate.
    """
    from src.models import Deployment, AnalysisMode
    from src.analysis import analyze_deployment
    from src.matching import find_similar
    from src.memory import ensure_bank_exists, retrieve_for_deployment
    from src.store import get as ledger_get, upsert as ledger_upsert, retained_count, known_outcome_records

    t_start = time.monotonic()

    if not req.service.strip():
        raise HTTPException(status_code=422, detail="'service' must not be empty.")
    if not req.migration_type.strip():
        raise HTTPException(status_code=422, detail="'migration_type' must not be empty.")

    # --- Guard: known-outcome deployments may not be re-analyzed without rerun flag ---
    existing = ledger_get(req.deployment_id)
    if existing and existing.get("outcome") not in ("pending", None, "") and not req.rerun:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Deployment #{req.deployment_id} already has a known outcome "
                f"('{existing['outcome']}'). Set rerun=true to re-analyze."
            ),
        )

    # --- Build the proposed Deployment model ---
    proposed = Deployment(
        deployment_id=req.deployment_id,
        service=req.service.strip(),
        migration_type=req.migration_type.strip().lower(),
        connection_pool_change=req.connection_pool_change,
        change_type=req.change_type.strip().lower(),
        timestamp=_utc_now_iso(),
        outcome="pending",
        dependencies_changed=req.dependencies_changed,
    )

    # --- Upsert as pending into the ledger (only if not already a known outcome) ---
    if not existing or existing.get("outcome") in ("pending", None, ""):
        ledger_upsert({
            "deployment_id":        req.deployment_id,
            "service":              req.service.strip(),
            "migration_type":       req.migration_type.strip().lower(),
            "connection_pool_change": req.connection_pool_change,
            "change_type":          req.change_type.strip().lower(),
            "dependencies_changed": req.dependencies_changed,
            "timestamp":            _utc_now_iso(),
            "outcome":              "pending",
            "root_cause":           "",
            "resolution":           "",
            "recovery_time_minutes": 0,
            "notes":                "",
            "source":               "analysis",
            "retained_in_hindsight": False,
        })

    # --- Baseline: historical_records=[] — NEVER gets ledger data ---
    # Pre-check: if GROQ_API_KEY is not configured, report 503 immediately
    # rather than letting the Groq SDK surface a cryptic auth error as 500.
    groq_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not groq_key:
        raise HTTPException(
            status_code=503,
            detail=(
                "Groq API key is not configured. "
                "Set GROQ_API_KEY in .env to enable analysis."
            ),
        )

    try:
        baseline_result = analyze_deployment(
            deployment=proposed,
            mode=AnalysisMode.BASELINE,
            historical_records=[],
        )
        baseline_out = AnalysisOut(
            risk_assessment=baseline_result.risk_assessment,
            summary=baseline_result.summary,
            recommendation=baseline_result.recommendation,
            evidence="",
            pattern_summary=None,
            historical_deployments=[],
        )
    except HTTPException:
        raise
    except Exception as exc:
        import groq as groq_sdk
        if isinstance(exc, groq_sdk.InternalServerError):
            # All retries exhausted — Groq is genuinely overloaded.
            raise HTTPException(
                status_code=503,
                detail=f"Groq is currently unavailable (retries exhausted): {exc}",
            )
        if isinstance(exc, (
            groq_sdk.AuthenticationError,
            groq_sdk.PermissionDeniedError,
            groq_sdk.NotFoundError,
        )):
            # 4xx from Groq — bad key, invalid model, quota exceeded.
            raise HTTPException(
                status_code=503,
                detail=f"Groq API error (check GROQ_API_KEY / GROQ_MODEL in .env): {exc}",
            )
        raise HTTPException(status_code=500, detail=f"Baseline analysis failed: {exc}")

    # --- Memory-informed: historical records from ledger (known outcomes only) ---
    hindsight_status = "ok"
    try:
        ensure_bank_exists()
    except Exception:
        hindsight_status = "unavailable"

    # Build historical Deployment list from known-outcome ledger records
    historical_records = _records_to_deployments(known_outcome_records())

    # Wrap recall_fn to track Hindsight availability per candidate
    _recall_status_flag = {"ok": True}

    def _recall_fn(deployment_id: str, query: str) -> list[dict]:
        memories, status = _recall_fn_with_status(deployment_id, query)
        if status == "unavailable":
            _recall_status_flag["ok"] = False
        return memories

    if hindsight_status == "unavailable":
        # Skip recall entirely if bank init failed
        recall_fn_to_use = lambda dep_id, query: []
    else:
        recall_fn_to_use = _recall_fn

    try:
        match_summary = find_similar(
            proposed=proposed,
            historical_records=historical_records,
            recall_fn=recall_fn_to_use,
            threshold=2,
            skip_same_id=(not req.rerun),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Memory matching failed: {exc}")

    # If any recall failed, reflect that in the response-level status
    if not _recall_status_flag["ok"]:
        hindsight_status = "unavailable"

    memory_out = _build_memory_out(
        match_summary=match_summary,
        hindsight_ok=(hindsight_status == "ok"),
        baseline_out=baseline_out,
    )

    t_ms = int((time.monotonic() - t_start) * 1000)

    return AnalyzeResponse(
        deployment_id=req.deployment_id,
        rerun=req.rerun,
        memory_records=retained_count(),
        hindsight_status=hindsight_status,
        signal_legend=SIGNAL_LEGEND,
        latency_ms=t_ms,
        baseline=baseline_out,
        memory_informed=memory_out,
    )


@app.post("/feedback", response_model=FeedbackResponse)
def feedback(req: FeedbackRequest) -> FeedbackResponse:
    """
    Record the actual outcome of a deployment (Phase 5 feedback).

    - A pending record is eligible.
    - A record with an already-known outcome returns 409.
    - Uses the existing Phase 5 record_outcome() — no reimplementation.
    - Sets retained_in_hindsight=True ONLY after successful Hindsight retain.
    - Polls retrieve_for_deployment every 2s up to 20s to confirm indexing.
    """
    from src.models import Deployment
    from src.feedback import record_outcome
    from src.memory import retrieve_for_deployment
    from src.store import (
        get as ledger_get,
        upsert as ledger_upsert,
        retained_count,
    )

    if req.outcome not in ("success", "incident"):
        raise HTTPException(
            status_code=422,
            detail="outcome must be 'success' or 'incident'."
        )

    existing = ledger_get(req.deployment_id)
    if existing and existing.get("outcome") not in ("pending", None, ""):
        raise HTTPException(
            status_code=409,
            detail=(
                f"Deployment #{req.deployment_id} already has a known outcome "
                f"('{existing['outcome']}'). "
                "If this is a new deployment, choose a different Deployment ID."
            ),
        )

    memory_records_before = retained_count()

    # Build a Deployment object for record_outcome() — outcome is ignored by it
    deployment = Deployment(
        deployment_id=req.deployment_id,
        service=req.service or (existing or {}).get("service", "unknown"),
        migration_type=req.migration_type or (existing or {}).get("migration_type", "unknown"),
        connection_pool_change=req.connection_pool_change,
        change_type=req.change_type or (existing or {}).get("change_type", ""),
        timestamp=(existing or {}).get("timestamp", _utc_now_iso()),
        outcome="pending",  # will be overridden by record_outcome's outcome param
        dependencies_changed=req.dependencies_changed
            if req.dependencies_changed is not None
            else (existing or {}).get("dependencies_changed"),
    )

    # For incidents: notes is the root-cause input.
    # For success: notes goes as notes.
    # record_outcome() handles extra_notes internally — do not replicate that logic.
    root_cause_input = req.notes if req.outcome == "incident" else ""
    notes_input      = req.notes if req.outcome == "success" else ""

    hindsight_ok = True
    try:
        record_outcome(
            deployment=deployment,
            outcome=req.outcome,
            root_cause=root_cause_input,
            notes=notes_input,
        )
    except Exception as exc:
        hindsight_ok = False
        raise HTTPException(
            status_code=503,
            detail=f"Memory backend unavailable (check HINDSIGHT_API_KEY in .env): {exc}",
        )

    # Persist to ledger — retained_in_hindsight=True only after successful retain
    recorded_at = _utc_now_iso()
    ledger_upsert({
        "deployment_id":         req.deployment_id,
        "service":               deployment.service,
        "migration_type":        deployment.migration_type,
        "connection_pool_change": req.connection_pool_change,
        "change_type":           deployment.change_type,
        "dependencies_changed":  deployment.dependencies_changed,
        "timestamp":             deployment.timestamp,
        "outcome":               req.outcome,
        "root_cause":            root_cause_input,
        "resolution":            "",
        "recovery_time_minutes": 0,
        "notes":                 req.notes,
        "source":                "feedback",
        "retained_in_hindsight": True,
        "recorded_at":           recorded_at,
    })

    # Poll Hindsight for indexing confirmation (every 2s, up to 20s)
    hindsight_indexed = False
    evidence_preview: str | None = None
    if hindsight_ok:
        query = f"deployment {req.deployment_id} {deployment.service} {deployment.migration_type} {req.outcome}"
        for _ in range(10):
            time.sleep(2)
            try:
                memories = retrieve_for_deployment(
                    deployment_id=req.deployment_id,
                    query=query,
                    limit=3,
                )
                if memories:
                    hindsight_indexed = True
                    txt = (memories[0].get("text") or "").strip()
                    evidence_preview = txt[:120] if txt else None
                    break
            except Exception:
                break

    memory_records_after = retained_count()

    # Build lesson text from real notes/root_cause — no fabrication
    lesson: str | None = None
    if req.outcome == "incident" and root_cause_input:
        lesson = root_cause_input
    elif req.outcome == "success" and notes_input:
        lesson = notes_input

    stored_memory = StoredMemoryOut(
        deployment_id=req.deployment_id,
        service=deployment.service,
        migration_type=deployment.migration_type,
        change_type=deployment.change_type,
        connection_pool_change=req.connection_pool_change,
        outcome=req.outcome,
        lesson=lesson,
        recorded_at=recorded_at,
        hindsight_evidence_preview=evidence_preview,
    )

    return FeedbackResponse(
        status="ok",
        message=(
            f"Outcome '{req.outcome}' recorded for deployment #{req.deployment_id}. "
            "Future analyses will incorporate this result."
        ),
        memory_records_before=memory_records_before,
        memory_records_after=memory_records_after,
        hindsight_indexed=hindsight_indexed,
        stored_memory=stored_memory,
    )


@app.get("/deployments")
def deployments() -> list[dict]:
    """
    Return ledger records sorted by numeric deployment ID descending.
    Fields: deployment_id, service, migration_type, change_type, outcome,
            timestamp, root_cause, resolution, notes, source.
    """
    from src.store import load_all

    records = load_all()

    def _sort_key(r: dict) -> int:
        try:
            return int(r.get("deployment_id", "0"))
        except (ValueError, TypeError):
            return 0

    records.sort(key=_sort_key, reverse=True)

    return [
        {
            "deployment_id": r.get("deployment_id", ""),
            "service":       r.get("service", ""),
            "migration_type": r.get("migration_type", ""),
            "change_type":   r.get("change_type", ""),
            "outcome":       r.get("outcome", ""),
            "timestamp":     r.get("timestamp", ""),
            "root_cause":    r.get("root_cause", ""),
            "resolution":    r.get("resolution", ""),
            "notes":         r.get("notes", ""),
            "source":        r.get("source", ""),
        }
        for r in records
    ]


@app.get("/memory/overview")
def memory_overview() -> dict:
    """
    Return deterministic pattern/lesson/service overview computed from
    known-outcome ledger records.  No Gemini, no Hindsight, no fabrication.
    """
    from src.patterns import get_overview
    return get_overview()
