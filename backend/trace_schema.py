"""
trace_schema.py — validate traces against schema/trace.schema.json and migrate
legacy (v0) traces to the canonical v1.0 format.

Validation is the gate: a trace is never persisted unless it validates. Migration lets
existing data/traces/*.json files (written before the schema existed) load and serve
without re-running the VLM.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from settings import SCHEMA_PATH

SCHEMA_VERSION = "1.0"


@lru_cache(maxsize=1)
def _schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


class TraceValidationError(ValueError):
    """Raised when a trace does not conform to schema/trace.schema.json."""


def validate_trace(trace: dict) -> None:
    """Validate a trace against the v1.0 schema. Raises TraceValidationError on failure."""
    import jsonschema

    try:
        jsonschema.validate(trace, _schema())
    except jsonschema.ValidationError as exc:
        location = "/".join(str(p) for p in exc.absolute_path) or "<root>"
        raise TraceValidationError(f"Invalid trace at '{location}': {exc.message}") from exc


def is_v1(trace: dict) -> bool:
    return isinstance(trace, dict) and trace.get("schema_version") == SCHEMA_VERSION


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def migrate_v0_to_v1(
    old: dict,
    *,
    source: dict | None = None,
    model: dict | None = None,
) -> dict:
    """Lift a legacy flat trace to schema v1.0. New fields default to empty; no VLM re-run.

    The v0 format is: {workflow_id, summary, steps[{step_id, timestamp_sec,
    window_or_context, observation, user_action, inferred_intent, agent_hint,
    frame_path, raw_model_output}]}.
    """
    steps: list[dict] = []
    for i, s in enumerate(old.get("steps", [])):
        step: dict[str, Any] = {
            "step_id": int(s.get("step_id", i + 1)),
            "timestamp_sec": float(s.get("timestamp_sec", 0) or 0),
            "window_or_context": s.get("window_or_context", "Unknown"),
        }
        for key in ("observation", "user_action", "inferred_intent", "agent_hint", "raw_model_output"):
            if s.get(key):
                step[key] = s[key]
        # v0 used "frame_path"; v1 uses "frame_uri".
        frame_uri = s.get("frame_uri") or s.get("frame_path")
        if frame_uri:
            step["frame_uri"] = frame_uri
        steps.append(step)

    trace = {
        "schema_version": SCHEMA_VERSION,
        "workflow_id": str(old.get("workflow_id", "")),
        "summary": old.get("summary", ""),
        "created_at": old.get("created_at", _now()),
        "source": source or {"kind": "imported"},
        "model": model or {},
        "entities": old.get("entities", []),
        "steps": steps,
    }
    for optional in ("title", "goal", "labels", "artifacts"):
        if old.get(optional):
            trace[optional] = old[optional]
    return trace


def ensure_v1(trace: dict) -> dict:
    """Return a v1.0 trace, migrating in place if the input is a legacy trace."""
    return trace if is_v1(trace) else migrate_v0_to_v1(trace)
