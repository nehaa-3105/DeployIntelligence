"""
Deployment analysis orchestration for Deployment Memory.

This is the only public interface consumed by the UI and verification
scripts. It owns the end-to-end pipeline and coordinates matching.py,
memory.py, and the Groq LLM.

Public API
----------
analyze_deployment(deployment, mode, historical_records) -> AnalysisResult
    mode=AnalysisMode.BASELINE
        Analyse using ONLY the proposed deployment's own structured fields.
        Does NOT call Hindsight, does NOT retrieve historical deployments.
        Exactly one LLM call.

    mode=AnalysisMode.MEMORY
        Reuses Phase 3 matching + Hindsight retrieval to find historically
        similar deployments. Passes retrieved evidence to exactly one LLM
        call. LLM must cite evidence using deployment ID, outcome, root
        cause, and prior mitigation/fix.

Both modes return the same AnalysisResult schema.

LLM
---
Uses the official Groq Python SDK:
    client.chat.completions.create(model, messages)
API key is read from settings.groq_api_key — never hardcoded.
Exactly one Groq call per mode. No chaining.

record_outcome() is a stub for Phase 5 — not implemented here.
"""

from __future__ import annotations

import json
import random
import re
import time
from typing import Any

import groq as groq_sdk

from src.config import settings
from src.matching import find_similar
from src.memory import close as hindsight_close
from src.memory import ensure_bank_exists, retrieve_for_deployment
from src.models import (
    AnalysisMode,
    AnalysisResult,
    Deployment,
    MatchSummary,
    RelevantDeployment,
)

# ---------------------------------------------------------------------------
# Groq client setup
# ---------------------------------------------------------------------------

_client = groq_sdk.Groq(api_key=settings.groq_api_key)
_MODEL  = settings.groq_model


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _deployment_fields_block(d: Deployment) -> str:
    """
    Render the structured fields of a Deployment as a compact text block
    for inclusion in an LLM prompt. Only core fields are shown — optional
    fields with None values are omitted.
    """
    lines = [
        f"  deployment_id        : {d.deployment_id}",
        f"  service              : {d.service}",
        f"  migration_type       : {d.migration_type}",
        f"  connection_pool_change: {d.connection_pool_change}",
        f"  change_type          : {d.change_type}",
        f"  timestamp            : {d.timestamp}",
    ]
    if d.dependencies_changed is not None:
        lines.append(f"  dependencies_changed : {d.dependencies_changed}")
    if d.config_changes:
        lines.append(f"  config_changes       : {d.config_changes}")
    if d.ci_result:
        lines.append(f"  ci_result            : {d.ci_result}")
    if d.notes:
        lines.append(f"  notes                : {d.notes}")
    return "\n".join(lines)


def _parse_llm_json(content: str) -> dict[str, Any]:
    """
    Extract a JSON object from the LLM's response text.

    The model sometimes wraps its output in a markdown code fence
    (```json … ```). Strip the fence if present, then parse.
    Raises ValueError if no valid JSON object is found.
    """
    # Strip markdown code fences if present
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
    if fence_match:
        return json.loads(fence_match.group(1))

    # Try the whole response as JSON
    brace_match = re.search(r"\{.*\}", content, re.DOTALL)
    if brace_match:
        return json.loads(brace_match.group(0))

    raise ValueError(f"LLM response contained no JSON object:\n{content}")


def _call_llm(system_prompt: str, user_prompt: str) -> str:
    """
    Single Groq chat-completion call.

    The system prompt is passed as the first message with role "system";
    the user prompt follows with role "user".  Returns the assistant's
    reply text as a plain string.

    Retry policy
    ------------
    groq.InternalServerError (HTTP 5xx) is retried up to 5 total attempts
    with exponential back-off plus ±25 % jitter:

        attempt 1 → 2 : base 1 s  (~0.75–1.25 s)
        attempt 2 → 3 : base 2 s  (~1.5–2.5 s)
        attempt 3 → 4 : base 4 s  (~3.0–5.0 s)
        attempt 4 → 5 : base 8 s  (~6.0–10.0 s)
        total sleep budget : ~11–19 s across 4 gaps

    groq.AuthenticationError / groq.BadRequestError / groq.PermissionDeniedError
    / groq.NotFoundError (4xx) are never retried — they propagate immediately.

    groq.RateLimitError is treated as transient and retried with the same
    schedule (rate-limit spikes are usually brief on Groq's LPU infrastructure).

    Any other exception propagates immediately.

    No fallback model is used.
    """
    _BASE_DELAYS  = (1, 2, 4, 8)   # 4 gaps → ~15 s total sleep for 5 attempts
    _MAX_ATTEMPTS = 5

    # Permanent 4xx error types — never retry these.
    _PERMANENT = (
        groq_sdk.AuthenticationError,
        groq_sdk.BadRequestError,
        groq_sdk.PermissionDeniedError,
        groq_sdk.NotFoundError,
    )
    # Transient error types — retry with back-off.
    _TRANSIENT = (
        groq_sdk.InternalServerError,
        groq_sdk.RateLimitError,
    )

    last_exc: Exception | None = None

    for attempt in range(_MAX_ATTEMPTS):
        try:
            completion = _client.chat.completions.create(
                model=_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_prompt},
                ],
                temperature=0,
            )
            return completion.choices[0].message.content

        except _PERMANENT:
            # 4xx — configuration/auth error; never retry.
            raise

        except _TRANSIENT as exc:
            # 5xx or rate-limit — retry with back-off.
            last_exc = exc
            if attempt == _MAX_ATTEMPTS - 1:
                break  # exhausted; raise below

            base   = _BASE_DELAYS[attempt]
            jitter = base * random.uniform(-0.25, 0.25)
            time.sleep(base + jitter)

        except Exception:
            # Network error, unexpected SDK error, etc. — not retryable.
            raise

    # All attempts exhausted on transient errors.
    raise last_exc  # type: ignore[misc]


# ---------------------------------------------------------------------------
# BASELINE mode
# ---------------------------------------------------------------------------

_BASELINE_SYSTEM = """\
You are a deployment risk analyst. You assess the risk of a proposed
deployment based solely on its own technical fields. You have no access
to historical deployment data and must NOT invent or imply historical
incidents.

Respond with a single JSON object — no markdown, no prose outside the
object — with exactly these keys:

{
  "risk_assessment": "<low|medium|high>",
  "summary": "<one-paragraph narrative explaining the risk level>",
  "recommendation": "<concrete mitigation steps for this deployment>"
}

Base your assessment only on the fields provided. A connection pool change
combined with a schema migration is inherently higher risk than a
config-only change. Use engineering judgement grounded in the fields shown.
"""


def _analyze_baseline(deployment: Deployment) -> AnalysisResult:
    """
    BASELINE mode: exactly one LLM call using only the proposed deployment's
    own structured fields. No Hindsight, no historical retrieval.
    """
    user_prompt = (
        "Assess the risk of this proposed deployment:\n\n"
        f"{_deployment_fields_block(deployment)}\n\n"
        "Return only the JSON object described in your instructions."
    )

    raw = _call_llm(_BASELINE_SYSTEM, user_prompt)
    parsed = _parse_llm_json(raw)

    risk           = parsed.get("risk_assessment", "medium")
    summary        = parsed.get("summary", "")
    recommendation = parsed.get("recommendation", "")

    return AnalysisResult(
        mode=AnalysisMode.BASELINE,
        risk_assessment=risk,
        risk_level=risk,            # legacy alias
        summary=summary,
        reasoning=summary,          # legacy alias
        recommendation=recommendation,
        relevant_deployments=[],    # baseline never retrieves history
        evidence="",                # baseline produces no evidence block
        match_summary=None,
        cited_deployment_ids=[],
    )


# ---------------------------------------------------------------------------
# MEMORY-INFORMED mode
# ---------------------------------------------------------------------------

_MEMORY_SYSTEM = """\
You are a deployment risk analyst with access to historical incident data.
You must reason over the evidence provided and produce a risk assessment.

Rules:
- Cite historical deployments by their deployment ID, outcome, root cause
  (when available), and prior mitigation/fix (when available).
- Do NOT invent historical incidents, root causes, fixes, or outcomes.
- If no historical evidence is available, say so explicitly.
- Your risk_assessment must be "low", "medium", or "high".
- cited_deployment_ids must only contain IDs present in the evidence block.

Respond with a single JSON object — no markdown, no prose outside the
object — with exactly these keys:

{
  "risk_assessment": "<low|medium|high>",
  "summary": "<narrative that explicitly references the relevant historical deployments, their outcomes, root causes, and prior fixes>",
  "recommendation": "<concrete mitigation steps informed by historical evidence>",
  "evidence": "<concise summary of the historical evidence used, citing deployment ID, outcome, root cause, and fix for each cited incident>",
  "cited_deployment_ids": ["<id>", ...]
}
"""


def _build_evidence_block(match_summary: MatchSummary) -> str:
    """
    Render the historical candidates from a MatchSummary as a structured
    evidence block for injection into the LLM prompt.

    Only candidates that passed the >= 2 signal threshold are included.
    For each candidate, Hindsight memory texts are included verbatim so
    the LLM has the raw experiential evidence (root cause, resolution,
    recovery notes).

    The LLM is strictly instructed not to invent facts — it can only cite
    what appears in this block.
    """
    if not match_summary.candidates:
        return "No historically similar deployments found in the memory bank."

    lines: list[str] = [
        f"Total similar historical deployments : {match_summary.total_similar}",
        f"Of which resulted in incidents        : {match_summary.total_incidents}",
        f"Of which were successful              : {match_summary.total_successes}",
        f"Historical risk confidence            : {match_summary.confidence_label}",
        "",
    ]

    for cand in match_summary.candidates:
        d = cand.deployment
        lines.append(f"--- Deployment #{d.deployment_id} ---")
        lines.append(f"  service              : {d.service}")
        lines.append(f"  migration_type       : {d.migration_type}")
        lines.append(f"  connection_pool_change: {d.connection_pool_change}")
        lines.append(f"  change_type          : {d.change_type}")
        lines.append(f"  outcome              : {d.outcome}")
        lines.append(f"  similarity_score     : {cand.similarity_score}/5")
        matched = [s.signal for s in cand.signal_matches if s.matched]
        lines.append(f"  matched_signals      : {', '.join(matched)}")

        if cand.hindsight_memories:
            lines.append("  hindsight_evidence:")
            for mem in cand.hindsight_memories:
                text = mem.get("text", "").strip()
                if text:
                    lines.append(f"    - {text}")
        else:
            lines.append("  hindsight_evidence   : (none retrieved)")
        lines.append("")

    return "\n".join(lines)


def _analyze_memory(
    deployment: Deployment,
    historical_records: list[Deployment],
) -> AnalysisResult:
    """
    MEMORY-INFORMED mode: runs Phase 3 matching + Hindsight retrieval,
    then passes the full evidence block to exactly one LLM call.

    Hindsight client lifecycle
    --------------------------
    ensure_bank_exists() initialises the shared Hindsight client lazily.
    hindsight_close() is called in a finally block so the aiohttp session
    is closed cleanly even if the LLM call or JSON parsing raises — a failed
    run cannot leave an open aiohttp connector behind.
    """
    ensure_bank_exists()

    try:
        # Phase 3 matching + Hindsight recall (reused verbatim — no modifications)
        match_summary = find_similar(
            proposed=deployment,
            historical_records=historical_records,
            recall_fn=retrieve_for_deployment,
            threshold=2,
        )
    finally:
        # Best-effort close — does not raise; see memory.close() docstring.
        hindsight_close()

    evidence_block = _build_evidence_block(match_summary)

    user_prompt = (
        "Proposed deployment to assess:\n\n"
        f"{_deployment_fields_block(deployment)}\n\n"
        "Historical evidence from memory:\n\n"
        f"{evidence_block}\n"
        "Return only the JSON object described in your instructions."
    )

    raw    = _call_llm(_MEMORY_SYSTEM, user_prompt)
    parsed = _parse_llm_json(raw)

    risk           = parsed.get("risk_assessment", "medium")
    summary        = parsed.get("summary", "")
    recommendation = parsed.get("recommendation", "")
    evidence_out   = parsed.get("evidence", "")
    cited_ids      = parsed.get("cited_deployment_ids", [])
    # Normalise: ensure all cited IDs are strings and appear in actual candidates
    candidate_ids = {c.deployment.deployment_id for c in match_summary.candidates}
    cited_ids = [str(cid) for cid in cited_ids if str(cid) in candidate_ids]

    # Build RelevantDeployment list from matched candidates
    relevant = [
        RelevantDeployment(
            deployment_id=c.deployment.deployment_id,
            similarity_score=c.similarity_score,
            outcome=c.deployment.outcome,
            service=c.deployment.service,
            migration_type=c.deployment.migration_type,
        )
        for c in match_summary.candidates
    ]

    return AnalysisResult(
        mode=AnalysisMode.MEMORY,
        risk_assessment=risk,
        risk_level=risk,            # legacy alias
        summary=summary,
        reasoning=summary,          # legacy alias
        recommendation=recommendation,
        relevant_deployments=relevant,
        evidence=evidence_out,
        match_summary=match_summary,
        cited_deployment_ids=cited_ids,
    )


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def analyze_deployment(
    deployment: Deployment,
    mode: AnalysisMode,
    historical_records: list[Deployment] | None = None,
) -> AnalysisResult:
    """
    Analyse a proposed deployment and return a structured risk assessment.

    Parameters
    ----------
    deployment : Deployment
        The proposed deployment to analyse. outcome should be "pending".
    mode : AnalysisMode
        AnalysisMode.BASELINE  — generic assessment, no memory retrieval.
        AnalysisMode.MEMORY    — memory-informed assessment using Phase 3
                                 matching and Hindsight recall.
    historical_records : list[Deployment] | None
        Required for MEMORY mode. The full list of known historical
        deployments passed to find_similar(). Ignored in BASELINE mode.
        If None in MEMORY mode, an empty list is used and the LLM will
        report that no historical evidence is available.

    Returns
    -------
    AnalysisResult
        Structured result with mode, risk_assessment, summary,
        recommendation, relevant_deployments, evidence, and — in MEMORY
        mode — match_summary and cited_deployment_ids.

    Raises
    ------
    ValueError
        If mode is not a recognised AnalysisMode value.
    groq.APIError (subclasses)
        Propagated directly if the Groq call fails after all retries.
    """
    if mode == AnalysisMode.BASELINE:
        return _analyze_baseline(deployment)
    elif mode == AnalysisMode.MEMORY:
        records = historical_records if historical_records is not None else []
        return _analyze_memory(deployment, records)
    else:
        raise ValueError(f"Unrecognised analysis mode: {mode!r}")


# ---------------------------------------------------------------------------
# Phase 5 stub — not implemented here
# ---------------------------------------------------------------------------

def record_outcome(
    deployment_id: str,
    outcome: str,
    incident: object | None = None,
) -> None:
    """
    Store a deployment outcome in Hindsight memory after it occurs.
    Implemented in Phase 5 (outcome feedback). Not part of Phase 4.
    """
    raise NotImplementedError("record_outcome() is a Phase 5 feature.")
