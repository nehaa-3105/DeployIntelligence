"""
JSON-file ledger for Deployment Memory.

Single source of truth for all deployment records — seed data, feedback
outcomes, and any record created during an analysis session.

Storage
-------
All records are persisted to a single JSON file:
    {DATA_DIR}/deployments.json          (default: ./data/deployments.json)

DATA_DIR is read from settings.data_dir (env var DATA_DIR, default ./data).

Concurrency
-----------
A threading.Lock guards every read-modify-write cycle.
Writes are atomic: content is written to a temp file in the same directory
then os.replace()-d over the target so readers never see a partial write.

Canonical record schema (steering file "CANONICAL DATA MODEL")
--------------------------------------------------------------
deployment_id         str         unique key
service               str
migration_type        str
connection_pool_change bool
change_type           str
dependencies_changed  bool | None
timestamp             str         ISO 8601
outcome               str         "success" | "incident" | "pending"
root_cause            str         "" when not applicable
resolution            str         "" when not applicable
recovery_time_minutes int         0 when not applicable
notes                 str         free text, "" allowed
source                str         "seed" | "feedback" | "analysis"
retained_in_hindsight bool
recorded_at           str         ISO 8601 of when the record was written here

Public API
----------
load_all()                  -> list[dict]
get(id)                     -> dict | None
upsert(record)              -> None
seed_from_records(records)  -> None   (skip IDs already present)
known_outcome_records()     -> list[dict]   (outcome != "pending")
retained_count()            -> int
clear()                     -> None
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.config import settings

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_lock = threading.Lock()


def _ledger_path() -> Path:
    """Return the absolute path to the JSON ledger file."""
    p = Path(settings.data_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p / "deployments.json"


def _load_raw() -> dict[str, dict]:
    """
    Load the ledger from disk. Returns a dict keyed by deployment_id.
    Returns an empty dict if the file does not exist or is malformed.
    Must be called with _lock held.
    """
    path = _ledger_path()
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            # Legacy format: list of records — migrate to dict on first read
            return {r["deployment_id"]: r for r in data if "deployment_id" in r}
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, KeyError, TypeError):
        pass
    return {}


def _save_raw(records: dict[str, dict]) -> None:
    """
    Write records to disk atomically. Must be called with _lock held.
    Writes to a sibling temp file then os.replace()-s over the target.
    """
    path = _ledger_path()
    dir_ = path.parent
    fd, tmp_path = tempfile.mkstemp(dir=dir_, suffix=".tmp", prefix="deployments_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, path)
    except Exception:
        # Clean up temp file on failure; re-raise so caller knows
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _normalise(record: dict[str, Any]) -> dict[str, Any]:
    """
    Return a copy of record with all canonical fields present.
    Missing optional fields are filled with their zero values so every
    stored record has an identical schema regardless of how it was created.
    """
    r = dict(record)
    r.setdefault("root_cause", "")
    r.setdefault("resolution", "")
    r.setdefault("recovery_time_minutes", 0)
    r.setdefault("notes", "")
    r.setdefault("source", "seed")
    r.setdefault("retained_in_hindsight", False)
    r.setdefault("recorded_at", _now_iso())
    r.setdefault("dependencies_changed", None)
    r.setdefault("change_type", "")
    r.setdefault("timestamp", "")
    return r


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_all() -> list[dict]:
    """Return all records as a list, ordered by deployment_id ascending."""
    with _lock:
        raw = _load_raw()
    return sorted(raw.values(), key=lambda r: r.get("deployment_id", ""))


def get(deployment_id: str) -> dict | None:
    """Return the record for deployment_id, or None if not present."""
    with _lock:
        raw = _load_raw()
    return raw.get(deployment_id)


def upsert(record: dict[str, Any]) -> None:
    """
    Insert or replace the record for record["deployment_id"].
    Thread-safe and atomic on disk.
    """
    dep_id = record["deployment_id"]
    with _lock:
        raw = _load_raw()
        raw[dep_id] = _normalise(record)
        _save_raw(raw)


def seed_from_records(records: list[dict[str, Any]]) -> None:
    """
    Insert records that do not yet exist in the ledger.
    Records whose deployment_id is already present are silently skipped —
    this prevents duplicate entries on repeated ingestion runs without --reset.
    """
    with _lock:
        raw = _load_raw()
        changed = False
        for rec in records:
            dep_id = rec.get("deployment_id")
            if dep_id and dep_id not in raw:
                raw[dep_id] = _normalise(rec)
                changed = True
        if changed:
            _save_raw(raw)


def known_outcome_records() -> list[dict]:
    """
    Return records whose outcome is not "pending".
    These are the only records eligible for pattern matching and memory counts.
    "pending" records are never used for matching per the data model spec.
    """
    return [r for r in load_all() if r.get("outcome") != "pending"]


def retained_count() -> int:
    """Return the number of records marked retained_in_hindsight=True."""
    return sum(1 for r in load_all() if r.get("retained_in_hindsight") is True)


def clear() -> None:
    """
    Delete all records from the ledger (atomic overwrite with empty dict).
    Called by the --reset ingestion flow before re-seeding.
    """
    with _lock:
        _save_raw({})
