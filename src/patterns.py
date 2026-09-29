"""
src/patterns.py — Deterministic pattern/lesson extraction over the ledger.

PURE functions only.  No Gemini calls, no Hindsight calls, no network I/O.
All results are deterministic functions of known-outcome ledger records.

Used by GET /memory/overview.

Public API
----------
get_overview() -> dict
    Returns the full /memory/overview response payload.

    Keys:
        memory_records  int             retained_count() from the ledger
        patterns        list[dict]      grouped by (migration_type, connection_pool_change)
        lessons         list[dict]      newest known-outcome records first
        by_service      list[dict]      per-service incident/success counts

Pattern schema
--------------
    key                 str     e.g. "schema|pool_change"
    name                str     human-readable label, e.g. "Schema + Pool Change"
    total               int
    incidents           int
    successes           int
    risk_label          str     "high" | "moderate" | "low"
    source_deployments  list[str]   deployment IDs in this group
    typical_trigger     str | null  first non-empty root_cause in group, or null
    impact              str | null  computed from incident recovery_time_minutes, or null
    mitigation          str | null  first non-empty resolution in group, or null
    last_updated        str | null  latest recorded_at in group, or null
    learned_from_feedback bool      True if any record in group has source=="feedback"

Lesson schema
-------------
    deployment_id       str
    service             str
    outcome             str
    lesson              str     "<root_cause> — fixed by <resolution>" or notes
    recorded_at         str | null

By-service schema
-----------------
    service             str
    total               int
    incidents           int
    successes           int
    deployment_ids      list[str]

Rules
-----
- Only known-outcome records (outcome != "pending") contribute to any output.
- Groups with fewer than 2 deployments are not included in patterns.
- Risk labels: incidents/total >= 0.67 → "high", >= 0.33 → "moderate", else "low".
- Lessons skip records with no real lesson text (no root_cause/resolution/notes).
- Do not invent any text; use null/empty rather than fabricate.
"""

from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _risk_label(total: int, incidents: int) -> str:
    if total == 0:
        return "low"
    ratio = incidents / total
    if ratio >= 0.67:
        return "high"
    if ratio >= 0.33:
        return "moderate"
    return "low"


def _pattern_key(rec: dict) -> str:
    """Stable group key: migration_type + whether pool changed."""
    mt = rec.get("migration_type", "unknown")
    pool = rec.get("connection_pool_change", False)
    pool_part = "pool_change" if pool else "no_pool_change"
    return f"{mt}|{pool_part}"


def _pattern_name(migration_type: str, connection_pool_change: bool) -> str:
    """Human-readable pattern label derived from real field values."""
    pool_part = "Pool Change" if connection_pool_change else "No Pool Change"
    mt_display = migration_type.replace("-", " ").replace("_", " ").title()
    return f"{mt_display} + {pool_part}"


def _latest_recorded_at(records: list[dict]) -> str | None:
    dates = [r.get("recorded_at") for r in records if r.get("recorded_at")]
    return max(dates) if dates else None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_overview() -> dict[str, Any]:
    """
    Compute the full /memory/overview payload from the current ledger state.

    All data comes from store.known_outcome_records() and store.retained_count().
    No fabrication.
    """
    from src.store import known_outcome_records, retained_count

    records = known_outcome_records()   # excludes "pending"
    memory_records = retained_count()

    return {
        "memory_records": memory_records,
        "patterns":  _build_patterns(records),
        "lessons":   _build_lessons(records),
        "by_service": _build_by_service(records),
    }


def _build_patterns(records: list[dict]) -> list[dict[str, Any]]:
    """
    Group records by (migration_type, connection_pool_change).
    Return only groups with >= 2 deployments.
    Patterns are sorted by total descending, then by key for stability.
    """
    groups: dict[str, list[dict]] = {}
    for rec in records:
        key = _pattern_key(rec)
        groups.setdefault(key, []).append(rec)

    patterns: list[dict[str, Any]] = []
    for key, group_recs in sorted(groups.items()):
        if len(group_recs) < 2:
            continue

        incidents  = sum(1 for r in group_recs if r.get("outcome") == "incident")
        successes  = sum(1 for r in group_recs if r.get("outcome") == "success")
        total      = len(group_recs)

        # Real data only — first non-empty root_cause, resolution
        typical_trigger: str | None = next(
            (r["root_cause"] for r in group_recs
             if r.get("root_cause") and r.get("outcome") == "incident"),
            None,
        )
        mitigation: str | None = next(
            (r["resolution"] for r in group_recs
             if r.get("resolution") and r.get("outcome") == "incident"),
            None,
        )

        # Impact: derived from recovery_time_minutes of incident records
        incident_recs = [r for r in group_recs if r.get("outcome") == "incident"]
        impact: str | None = None
        if incident_recs:
            times = [r.get("recovery_time_minutes", 0) for r in incident_recs
                     if r.get("recovery_time_minutes")]
            if times:
                avg_min = round(sum(times) / len(times))
                impact = f"Average recovery time: {avg_min} minutes across {len(times)} incident(s)"

        # Use the first record's fields for name (all in same group share migration_type+pool)
        rep = group_recs[0]
        mt   = rep.get("migration_type", "unknown")
        pool = rep.get("connection_pool_change", False)

        patterns.append({
            "key":                    key,
            "name":                   _pattern_name(mt, pool),
            "total":                  total,
            "incidents":              incidents,
            "successes":              successes,
            "risk_label":             _risk_label(total, incidents),
            "source_deployments":     [r["deployment_id"] for r in group_recs],
            "typical_trigger":        typical_trigger,
            "impact":                 impact,
            "mitigation":             mitigation,
            "last_updated":           _latest_recorded_at(group_recs),
            "learned_from_feedback":  any(r.get("source") == "feedback" for r in group_recs),
        })

    # Sort: most deployments first, then alphabetically by key for stability
    patterns.sort(key=lambda p: (-p["total"], p["key"]))
    return patterns


def _build_lessons(records: list[dict]) -> list[dict[str, Any]]:
    """
    Build lesson entries from known-outcome records, newest first.
    Skip any record that has no real lesson text.
    """
    lessons: list[dict[str, Any]] = []
    # Sort newest recorded_at first; records with no recorded_at go last
    sorted_recs = sorted(
        records,
        key=lambda r: r.get("recorded_at") or "",
        reverse=True,
    )
    for rec in sorted_recs:
        outcome = rec.get("outcome", "")
        root_cause = (rec.get("root_cause") or "").strip()
        resolution = (rec.get("resolution") or "").strip()
        notes      = (rec.get("notes") or "").strip()

        if outcome == "incident":
            if root_cause and resolution:
                lesson_text = f"{root_cause} — fixed by {resolution}"
            elif root_cause:
                lesson_text = root_cause
            else:
                continue  # no real text — skip
        else:
            # success
            if notes:
                lesson_text = notes
            else:
                continue  # no notes — skip

        lessons.append({
            "deployment_id": rec["deployment_id"],
            "service":       rec.get("service", ""),
            "outcome":       outcome,
            "lesson":        lesson_text,
            "recorded_at":   rec.get("recorded_at"),
        })

    return lessons


def _build_by_service(records: list[dict]) -> list[dict[str, Any]]:
    """
    Aggregate incident/success counts per service from known-outcome records.
    Sorted by total deployments descending, then service name for stability.
    """
    services: dict[str, dict[str, Any]] = {}
    for rec in records:
        svc = rec.get("service", "unknown")
        if svc not in services:
            services[svc] = {
                "service":        svc,
                "total":          0,
                "incidents":      0,
                "successes":      0,
                "deployment_ids": [],
            }
        services[svc]["total"] += 1
        if rec.get("outcome") == "incident":
            services[svc]["incidents"] += 1
        elif rec.get("outcome") == "success":
            services[svc]["successes"] += 1
        services[svc]["deployment_ids"].append(rec["deployment_id"])

    result = sorted(
        services.values(),
        key=lambda s: (-s["total"], s["service"]),
    )
    return result
