"""
test_api.py — Phase 1 API verification.

Tests every endpoint and behavioral rule described in the Phase 1 spec.
Run ONLY after:
  1. py -3 -m src.ingestion --reset   (seeds 10 records)
  2. py -3 -m uvicorn api:app --port 8000

Usage:
    py -3 test_api.py

All assertions are self-describing.  The script exits 0 on full pass, 1 on
any failure, and prints a clear summary at the end.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from typing import Any

BASE = "http://localhost:8000"
ERRORS: list[str] = []


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _get(path: str) -> Any:
    res = urllib.request.urlopen(f"{BASE}{path}")
    return json.loads(res.read())


def _post(path: str, body: dict) -> Any:
    payload = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{BASE}{path}", data=payload,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    res = urllib.request.urlopen(req)
    return json.loads(res.read())


def _post_expect_error(path: str, body: dict) -> tuple[int, dict]:
    """Return (status_code, body) for an expected HTTP error response."""
    payload = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{BASE}{path}", data=payload,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        urllib.request.urlopen(req)
        return 200, {}  # unexpected success
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def _section(title: str) -> None:
    print(f"\n{'='*65}")
    print(f"  {title}")
    print(f"{'='*65}")


def _ok(msg: str) -> None:
    print(f"  PASS  {msg}")


def _fail(msg: str) -> None:
    print(f"  FAIL  {msg}")
    ERRORS.append(msg)


def _check(condition: bool, msg_pass: str, msg_fail: str) -> None:
    if condition:
        _ok(msg_pass)
    else:
        _fail(msg_fail)


# ---------------------------------------------------------------------------
# T01 — GET /health
# ---------------------------------------------------------------------------

def test_health() -> None:
    _section("T01 — GET /health")
    h = _get("/health")
    print(f"  response: {h}")

    _check(h.get("status") == "ok",
           "status == 'ok'",
           f"status != 'ok' (got {h.get('status')!r})")

    _check(h.get("service") == "deployment-memory",
           "service == 'deployment-memory'",
           f"service != 'deployment-memory' (got {h.get('service')!r})")

    records = h.get("records")
    _check(isinstance(records, int) and records >= 0,
           f"records is an integer ({records})",
           f"records is not an integer (got {records!r})")

    _check(records > 0,
           f"records > 0 ({records}) — ledger has seed data",
           "records == 0 — run ingestion --reset first")


# ---------------------------------------------------------------------------
# T02 — POST /analyze: baseline independence
# ---------------------------------------------------------------------------

def test_analyze_baseline_independence() -> None:
    _section("T02 — POST /analyze: baseline is independent of historical data")

    resp = _post("/analyze", {
        "deployment_id": "997",
        "service":        "test-service",
        "migration_type": "config-only",
        "connection_pool_change": False,
        "change_type":    "config",
        "dependencies_changed": False,
    })

    b = resp.get("baseline", {})
    _check("risk_assessment" in b,
           "baseline has risk_assessment",
           "baseline missing risk_assessment")
    _check("summary" in b,
           "baseline has summary",
           "baseline missing summary")
    _check("recommendation" in b,
           "baseline has recommendation",
           "baseline missing recommendation")

    # Baseline must never cite historical deployments
    _check(b.get("historical_deployments") == [],
           "baseline.historical_deployments == []",
           f"baseline.historical_deployments not empty: {b.get('historical_deployments')}")
    _check(b.get("pattern_summary") is None,
           "baseline.pattern_summary is None",
           f"baseline.pattern_summary is not None: {b.get('pattern_summary')}")

    # Baseline summary/recommendation must not fabricate historical references
    summary_lower = (b.get("summary") or "").lower()
    rec_lower = (b.get("recommendation") or "").lower()
    no_hist_refs = all(
        phrase not in summary_lower and phrase not in rec_lower
        for phrase in ["deployment #1", "deployment #2", "similar deployment"]
    )
    _check(no_hist_refs,
           "baseline text contains no historical deployment references",
           "baseline text references historical deployments — baseline must be independent")


# ---------------------------------------------------------------------------
# T03 — POST /analyze: #297 memory-informed with real historical candidates
# ---------------------------------------------------------------------------

def test_analyze_297() -> None:
    _section("T03 — POST /analyze: #297 gets real historical candidates")

    resp = _post("/analyze", {
        "deployment_id": "297",
        "service":        "payment-service",
        "migration_type": "schema",
        "connection_pool_change": True,
        "change_type":    "infra",
        "dependencies_changed": True,
    })

    print(f"  deployment_id   : {resp.get('deployment_id')}")
    print(f"  hindsight_status: {resp.get('hindsight_status')}")
    print(f"  latency_ms      : {resp.get('latency_ms')}")
    print(f"  memory_records  : {resp.get('memory_records')}")

    _check(resp.get("deployment_id") == "297",
           "deployment_id == '297'",
           f"deployment_id wrong: {resp.get('deployment_id')!r}")

    _check(resp.get("hindsight_status") in ("ok", "unavailable"),
           f"hindsight_status is valid ('{resp.get('hindsight_status')}')",
           f"hindsight_status invalid: {resp.get('hindsight_status')!r}")

    _check(isinstance(resp.get("latency_ms"), int),
           f"latency_ms is int ({resp.get('latency_ms')}ms)",
           "latency_ms missing or not int")

    # Signal legend
    legend = resp.get("signal_legend", [])
    legend_signals = {s["signal"] for s in legend}
    expected_signals = {"service", "migration_type", "connection_pool_change",
                        "change_type", "dependencies_changed"}
    _check(legend_signals == expected_signals,
           f"signal_legend has exactly 5 correct signals",
           f"signal_legend wrong: {legend_signals}")

    # Memory-informed must cite real candidates
    m = resp.get("memory_informed", {})
    ps = m.get("pattern_summary", {})

    _check(ps is not None,
           "memory_informed has pattern_summary",
           "memory_informed missing pattern_summary")

    if ps:
        total = ps.get("total_similar", 0)
        incidents = ps.get("total_incidents", 0)
        headline = ps.get("headline", "")

        _check(isinstance(total, int) and total >= 0,
               f"total_similar is int ({total})",
               "total_similar missing or not int")

        # Headline must be dynamically computed from real counts
        _check(isinstance(headline, str) and len(headline) > 0,
               f"headline present: {headline!r}",
               "headline empty")

        if total > 0:
            _check(str(total) in headline,
                   f"headline contains real total_similar count ({total}): {headline!r}",
                   f"headline does not reflect real total_similar ({total}): {headline!r}")
        if incidents > 0:
            _check(str(incidents) in headline,
                   f"headline contains real incidents count ({incidents}): {headline!r}",
                   f"headline does not reflect real incidents count ({incidents}): {headline!r}")

    # historical_deployments must be real
    hist = m.get("historical_deployments", [])
    _check(isinstance(hist, list),
           "historical_deployments is a list",
           "historical_deployments is not a list")

    if hist:
        h0 = hist[0]
        required_fields = {"deployment_id", "service", "migration_type", "change_type",
                           "connection_pool_change", "dependencies_changed", "timestamp",
                           "outcome", "similarity_score", "matched_signals", "signals",
                           "root_cause", "resolution", "key_note",
                           "hindsight_status", "hindsight_evidence"}
        missing = required_fields - set(h0.keys())
        _check(len(missing) == 0,
               f"historical_deployments[0] has all required fields",
               f"historical_deployments[0] missing fields: {missing}")

        _check(h0.get("hindsight_status") in ("recalled", "empty", "unavailable", "not_recalled"),
               f"candidate hindsight_status is valid ('{h0.get('hindsight_status')}')",
               f"candidate hindsight_status invalid: {h0.get('hindsight_status')!r}")

        for cand in hist:
            bad_signals = set(cand.get("matched_signals", [])) - expected_signals
            _check(len(bad_signals) == 0,
                   f"#{cand['deployment_id']} matched_signals contains only real signals",
                   f"#{cand['deployment_id']} matched_signals has invented signals: {bad_signals}")

    # Evidence must not contain fabricated hardcoded phrases
    FABRICATED_PHRASES = [
        "80% within 10 minutes",
        "Outcome reported via UI",
        "connection pool exhaustion / staged rollout",
    ]
    evidence = m.get("evidence", "")
    for phrase in FABRICATED_PHRASES:
        _check(phrase not in evidence,
               f"evidence does not contain fabricated phrase: {phrase!r}",
               f"evidence contains fabricated phrase: {phrase!r}")

    recommendation = m.get("recommendation", "")
    for phrase in FABRICATED_PHRASES:
        _check(phrase not in recommendation,
               f"recommendation does not contain fabricated phrase: {phrase!r}",
               f"recommendation contains fabricated phrase: {phrase!r}")


# ---------------------------------------------------------------------------
# T04 — POST /analyze: pending deployment upserted to ledger
# ---------------------------------------------------------------------------

def test_analyze_pending_upsert() -> None:
    _section("T04 — POST /analyze: proposed deployment upserted as 'pending'")

    dep_id = "899"

    # The ledger upsert (outcome="pending") happens before the Gemini call in
    # api.py, so even if the call raises later the record will be in the ledger.
    # Accept 422 only if the record already exists from a previous test run.
    try:
        _post("/analyze", {
            "deployment_id": dep_id,
            "service":        "test-service",
            "migration_type": "schema",
            "connection_pool_change": True,
            "change_type":    "infra",
            "dependencies_changed": True,
        })
    except urllib.error.HTTPError as e:
        code = e.code
        body = json.loads(e.read())
        if code == 422:
            # Already has a known outcome from a previous test run — acceptable
            pass
        else:
            _fail(f"POST /analyze returned unexpected HTTP {code}: {body.get('detail', '')[:80]}")
            return

    # Either path: the record must be in the ledger
    deployments = _get("/deployments")
    ids = [d["deployment_id"] for d in deployments]
    _check(dep_id in ids,
           f"deployment #{dep_id} appears in /deployments after analyze",
           f"deployment #{dep_id} NOT in /deployments after analyze (ids={ids[:5]}…)")

    pending_rec = next((d for d in deployments if d["deployment_id"] == dep_id), None)
    if pending_rec:
        _check(pending_rec.get("outcome") in ("pending", "incident", "success"),
               f"#{dep_id} has a valid outcome in /deployments ('{pending_rec.get('outcome')}')",
               f"#{dep_id} outcome is unrecognised: {pending_rec.get('outcome')!r}")
        _check(pending_rec.get("source") in ("analysis", "feedback"),
               f"#{dep_id} source is 'analysis' or 'feedback'",
               f"#{dep_id} source unexpected: {pending_rec.get('source')!r}")


# ---------------------------------------------------------------------------
# T05 — POST /analyze: known-outcome blocks re-analysis without rerun
# ---------------------------------------------------------------------------

def test_analyze_known_outcome_protection() -> None:
    _section("T05 — POST /analyze: known-outcome deployment returns 422 without rerun=true")

    # #184 is a seed record with outcome='incident'
    code, body = _post_expect_error("/analyze", {
        "deployment_id": "184",
        "service":        "payment-service",
        "migration_type": "schema",
        "connection_pool_change": True,
        "change_type":    "infra",
        "dependencies_changed": True,
    })
    _check(code == 422,
           f"known-outcome deployment returns 422 (got {code})",
           f"expected 422, got {code}: {body.get('detail', '')[:80]}")


# ---------------------------------------------------------------------------
# T06 — POST /analyze: rerun=true bypasses the 422 guard
# ---------------------------------------------------------------------------

def test_analyze_rerun() -> None:
    _section("T06 — POST /analyze: rerun=true succeeds and uses skip_same_id=False")

    # #201 is a seed success record — would normally be blocked by the 422 guard
    resp = _post("/analyze", {
        "deployment_id": "201",
        "service":        "payment-service",
        "migration_type": "schema",
        "connection_pool_change": False,
        "change_type":    "infra",
        "dependencies_changed": True,
        "rerun":          True,
    })

    _check(resp.get("rerun") is True,
           "response.rerun == True",
           f"response.rerun != True: {resp.get('rerun')!r}")

    _check(resp.get("deployment_id") == "201",
           "rerun response contains correct deployment_id",
           f"rerun response deployment_id wrong: {resp.get('deployment_id')!r}")

    m = resp.get("memory_informed", {})
    hist_ids = [h["deployment_id"] for h in m.get("historical_deployments", [])]
    print(f"  hist ids in rerun: {hist_ids}")
    # skip_same_id=False is in effect; #201 may appear as its own candidate
    # depending on ledger/Hindsight state — we confirm the call succeeded.


# ---------------------------------------------------------------------------
# T07 — POST /feedback: records outcome and returns memory counts
# ---------------------------------------------------------------------------

def test_feedback() -> None:
    _section("T07 — POST /feedback: records outcome, returns memory counts")

    dep_id = "899"

    try:
        fb = _post("/feedback", {
            "deployment_id":        dep_id,
            "outcome":              "incident",
            "notes":                "pool exhaustion during test",
            "service":              "test-service",
            "migration_type":       "schema",
            "change_type":          "infra",
            "connection_pool_change": True,
            "dependencies_changed": True,
        })

        print(f"  status                : {fb.get('status')}")
        print(f"  memory_records_before : {fb.get('memory_records_before')}")
        print(f"  memory_records_after  : {fb.get('memory_records_after')}")
        print(f"  hindsight_indexed     : {fb.get('hindsight_indexed')}")

        _check(fb.get("status") == "ok",
               "feedback status == 'ok'",
               f"feedback status != 'ok': {fb.get('status')!r}")

        before = fb.get("memory_records_before")
        after = fb.get("memory_records_after")
        _check(isinstance(before, int) and isinstance(after, int),
               f"memory_records_before ({before}) and after ({after}) are ints",
               "memory_records_before/after not ints")

        _check(after >= before,
               f"memory_records_after ({after}) >= before ({before})",
               f"memory_records_after ({after}) < before ({before})")

        sm = fb.get("stored_memory", {})
        _check(sm.get("deployment_id") == dep_id,
               f"stored_memory.deployment_id == {dep_id!r}",
               f"stored_memory.deployment_id wrong: {sm.get('deployment_id')!r}")
        _check(sm.get("outcome") == "incident",
               "stored_memory.outcome == 'incident'",
               f"stored_memory.outcome wrong: {sm.get('outcome')!r}")

        lesson = sm.get("lesson")
        _check(lesson == "pool exhaustion during test" or lesson is None,
               f"stored_memory.lesson derived from real notes ('{lesson}')",
               f"stored_memory.lesson fabricated: {lesson!r}")

        _check("Outcome reported via UI" not in (lesson or ""),
               "stored_memory.lesson does not contain hardcoded fabricated text",
               "stored_memory.lesson contains 'Outcome reported via UI' — fabricated!")

    except urllib.error.HTTPError as e:
        code = e.code
        body = json.loads(e.read())
        if code == 503:
            print(f"  INFO: 503 — Hindsight not configured: {body.get('detail', '')[:80]}")
            print("  Skipping feedback assertions (Hindsight unavailable)")
        else:
            _fail(f"feedback returned unexpected {code}: {body.get('detail', '')[:80]}")


# ---------------------------------------------------------------------------
# T08 — POST /feedback: duplicate known-outcome returns 409
# ---------------------------------------------------------------------------

def test_feedback_duplicate_protection() -> None:
    _section("T08 — POST /feedback: duplicate known-outcome returns 409")

    # #184 already has outcome='incident' from the seed
    code, body = _post_expect_error("/feedback", {
        "deployment_id":        "184",
        "outcome":              "success",
        "notes":                "",
        "service":              "payment-service",
        "migration_type":       "schema",
        "change_type":          "infra",
        "connection_pool_change": True,
    })

    _check(code == 409,
           f"duplicate feedback returns 409 (got {code})",
           f"expected 409, got {code}: {body.get('detail', '')[:80]}")

    detail = body.get("detail", "")
    _check("184" in detail or "outcome" in detail.lower(),
           f"409 detail references the deployment or outcome: {detail[:80]!r}",
           f"409 detail unclear: {detail[:80]!r}")


# ---------------------------------------------------------------------------
# T09 — GET /deployments
# ---------------------------------------------------------------------------

def test_deployments() -> None:
    _section("T09 — GET /deployments")

    recs = _get("/deployments")
    print(f"  total records: {len(recs)}")

    _check(isinstance(recs, list),
           "response is a list",
           "response is not a list")

    _check(len(recs) > 0,
           f"{len(recs)} records returned (seed data present)",
           "0 records — run ingestion --reset first")

    required_fields = {"deployment_id", "service", "migration_type", "change_type",
                       "outcome", "timestamp", "root_cause", "resolution",
                       "notes", "source"}
    if recs:
        missing = required_fields - set(recs[0].keys())
        _check(len(missing) == 0,
               "first record has all required fields",
               f"first record missing: {missing}")

    if len(recs) > 1:
        ids = [recs[i]["deployment_id"] for i in range(min(5, len(recs)))]
        try:
            int_ids = [int(i) for i in ids]
            _check(int_ids == sorted(int_ids, reverse=True),
                   f"records sorted by numeric ID descending: {int_ids}",
                   f"records not sorted descending: {int_ids}")
        except ValueError:
            _ok("deployment IDs contain non-numeric values; sort check skipped")

    _check(all(r.get("deployment_id") for r in recs),
           "all records have non-empty deployment_id",
           "some records have empty deployment_id")


# ---------------------------------------------------------------------------
# T10 — GET /memory/overview
# ---------------------------------------------------------------------------

def test_memory_overview() -> None:
    _section("T10 — GET /memory/overview")

    ov = _get("/memory/overview")
    print(f"  memory_records: {ov.get('memory_records')}")
    print(f"  patterns count: {len(ov.get('patterns', []))}")
    print(f"  lessons count : {len(ov.get('lessons', []))}")
    print(f"  by_service cnt: {len(ov.get('by_service', []))}")

    _check(isinstance(ov.get("memory_records"), int),
           f"memory_records is int ({ov.get('memory_records')})",
           "memory_records missing or not int")

    _check(isinstance(ov.get("patterns"), list),
           "patterns is a list",
           "patterns is not a list")
    _check(isinstance(ov.get("lessons"), list),
           "lessons is a list",
           "lessons is not a list")
    _check(isinstance(ov.get("by_service"), list),
           "by_service is a list",
           "by_service is not a list")

    patterns = ov.get("patterns", [])
    if patterns:
        p0 = patterns[0]
        required_p = {"key", "name", "total", "incidents", "successes",
                      "risk_label", "source_deployments",
                      "typical_trigger", "impact", "mitigation",
                      "last_updated", "learned_from_feedback"}
        missing_p = required_p - set(p0.keys())
        _check(len(missing_p) == 0,
               "pattern[0] has all required fields",
               f"pattern[0] missing: {missing_p}")

        _check(p0.get("risk_label") in ("high", "moderate", "low"),
               f"pattern risk_label valid ('{p0.get('risk_label')}')",
               f"pattern risk_label invalid: {p0.get('risk_label')!r}")

        _check(p0.get("total", 0) >= 2,
               f"pattern total >= 2 ({p0.get('total')})",
               f"pattern with total < 2 returned ({p0.get('total')})")

    lessons = ov.get("lessons", [])
    if lessons:
        l0 = lessons[0]
        required_l = {"deployment_id", "service", "outcome", "lesson", "recorded_at"}
        missing_l = required_l - set(l0.keys())
        _check(len(missing_l) == 0,
               "lessons[0] has all required fields",
               f"lessons[0] missing: {missing_l}")

        lesson_text = l0.get("lesson", "")
        _check(bool(lesson_text),
               f"lesson[0] has non-empty text: {lesson_text[:60]!r}",
               "lesson[0] has empty text")

    by_service = ov.get("by_service", [])
    if by_service:
        s0 = by_service[0]
        required_s = {"service", "total", "incidents", "successes", "deployment_ids"}
        missing_s = required_s - set(s0.keys())
        _check(len(missing_s) == 0,
               "by_service[0] has all required fields",
               f"by_service[0] missing: {missing_s}")

        _check(s0["total"] == s0["incidents"] + s0["successes"],
               f"by_service[0] total == incidents + successes ({s0['total']} == {s0['incidents']} + {s0['successes']})",
               f"by_service[0] counts inconsistent: total={s0['total']}, inc={s0['incidents']}, suc={s0['successes']}")

    ov2 = _get("/memory/overview")
    _check(ov2.get("memory_records") == ov.get("memory_records"),
           "memory_overview is deterministic (same result on second call)",
           "memory_overview returned different memory_records on second call")


# ---------------------------------------------------------------------------
# T11 — No fabricated memory text anywhere
# ---------------------------------------------------------------------------

def test_no_fabricated_content() -> None:
    _section("T11 — No fabricated content in API responses")

    FABRICATED_PHRASES = [
        "80% within 10 minutes",
        "Outcome reported via UI",
        "connection pool exhaustion / staged rollout",
        "hardcoded",
    ]

    resp = _post("/analyze", {
        "deployment_id": "297",
        "service":        "payment-service",
        "migration_type": "schema",
        "connection_pool_change": True,
        "change_type":    "infra",
        "dependencies_changed": True,
        "rerun":          True,
    })

    full_text = json.dumps(resp).lower()
    for phrase in FABRICATED_PHRASES:
        _check(phrase.lower() not in full_text,
               f"response does not contain fabricated phrase: {phrase!r}",
               f"response contains fabricated phrase: {phrase!r}")

    ov = _get("/memory/overview")
    ov_text = json.dumps(ov).lower()
    for phrase in FABRICATED_PHRASES:
        _check(phrase.lower() not in ov_text,
               f"/memory/overview does not contain fabricated phrase: {phrase!r}",
               f"/memory/overview contains fabricated phrase: {phrase!r}")


# ---------------------------------------------------------------------------
# T12 — POST /analyze: pending records excluded from historical matching
# ---------------------------------------------------------------------------

def test_pending_excluded_from_matching() -> None:
    _section("T12 — Pending records excluded from historical matching candidates")

    dep_id = "888"
    try:
        _post("/analyze", {
            "deployment_id": dep_id,
            "service":        "payment-service",
            "migration_type": "schema",
            "connection_pool_change": True,
            "change_type":    "infra",
            "dependencies_changed": True,
        })
    except urllib.error.HTTPError as e:
        # 422 = this ID already has a known outcome from a prior test run — acceptable
        if e.code != 422:
            _fail(f"T12 first analyze returned unexpected HTTP {e.code}")
            return

    resp = _post("/analyze", {
        "deployment_id": "297",
        "service":        "payment-service",
        "migration_type": "schema",
        "connection_pool_change": True,
        "change_type":    "infra",
        "dependencies_changed": True,
        "rerun":          True,
    })

    m = resp.get("memory_informed", {})
    hist_ids = [h["deployment_id"] for h in m.get("historical_deployments", [])]
    _check(dep_id not in hist_ids,
           f"pending #{dep_id} does NOT appear as a historical candidate",
           f"pending #{dep_id} appeared as a candidate — pending records must be excluded")


# ---------------------------------------------------------------------------
# T13 — POST /analyze: dynamic pattern_summary headline uses real numbers
# ---------------------------------------------------------------------------

def test_dynamic_headline() -> None:
    _section("T13 — Dynamic headline computed from real match counts")

    resp = _post("/analyze", {
        "deployment_id": "297",
        "service":        "payment-service",
        "migration_type": "schema",
        "connection_pool_change": True,
        "change_type":    "infra",
        "dependencies_changed": True,
        "rerun":          True,
    })

    m = resp.get("memory_informed", {})
    ps = m.get("pattern_summary", {})

    if not ps:
        _fail("pattern_summary missing — cannot check headline")
        return

    total = ps.get("total_similar", 0)
    incidents = ps.get("total_incidents", 0)
    headline = ps.get("headline", "")

    print(f"  total_similar={total}, total_incidents={incidents}")
    print(f"  headline: {headline!r}")

    _check(isinstance(headline, str) and headline,
           "headline is a non-empty string",
           "headline is empty or not a string")

    if total > 0:
        _check(str(total) in headline,
               f"headline contains real total ({total}): {headline!r}",
               f"headline does not contain real total {total}: {headline!r}")

    if incidents > 0:
        _check(str(incidents) in headline,
               f"headline contains real incident count ({incidents}): {headline!r}",
               f"headline does not reflect real incident count {incidents}: {headline!r}")

    # Headline must not be a hardcoded static string (only flag when real counts differ)
    HARDCODED_HEADLINES = ["3 of 6 similar deployments caused an incident"]
    for hh in HARDCODED_HEADLINES:
        if total != 6 or incidents != 3:
            _check(headline != hh,
                   "headline is not a hardcoded static string",
                   f"headline appears to be hardcoded: {headline!r}")


# ---------------------------------------------------------------------------
# T14 — Five matching signals only
# ---------------------------------------------------------------------------

def test_five_matching_signals() -> None:
    _section("T14 — Five matching signals only")

    resp = _post("/analyze", {
        "deployment_id": "297",
        "service":        "payment-service",
        "migration_type": "schema",
        "connection_pool_change": True,
        "change_type":    "infra",
        "dependencies_changed": True,
        "rerun":          True,
    })

    legend = resp.get("signal_legend", [])
    legend_signals = {s["signal"] for s in legend}
    expected = {"service", "migration_type", "connection_pool_change",
                "change_type", "dependencies_changed"}

    _check(legend_signals == expected,
           f"signal_legend has exactly 5 real signals: {legend_signals}",
           f"signal_legend wrong: got {legend_signals}, expected {expected}")

    m = resp.get("memory_informed", {})
    for cand in m.get("historical_deployments", []):
        cand_id = cand["deployment_id"]
        signals_dict = cand.get("signals", {})
        signal_keys = set(signals_dict.keys())
        _check(signal_keys == expected,
               f"#{cand_id} signals dict has exactly 5 real signals",
               f"#{cand_id} signals dict wrong: {signal_keys}")

        bad_matched = set(cand.get("matched_signals", [])) - expected
        _check(len(bad_matched) == 0,
               f"#{cand_id} matched_signals only contains real signals",
               f"#{cand_id} matched_signals has invented signals: {bad_matched}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("\nDeployment Memory — Phase 1 API Verification")
    print("=" * 65)

    test_health()
    test_analyze_baseline_independence()
    test_analyze_297()
    test_analyze_pending_upsert()
    test_analyze_known_outcome_protection()
    test_analyze_rerun()
    test_feedback()
    test_feedback_duplicate_protection()
    test_deployments()
    test_memory_overview()
    test_no_fabricated_content()
    test_pending_excluded_from_matching()
    test_dynamic_headline()
    test_five_matching_signals()

    print(f"\n{'='*65}")
    if ERRORS:
        print(f"  RESULT: {len(ERRORS)} FAILURE(S)\n")
        for e in ERRORS:
            print(f"    x  {e}")
        print()
        sys.exit(1)
    else:
        print("  RESULT: ALL TESTS PASSED")
        print()
        sys.exit(0)


if __name__ == "__main__":
    main()
