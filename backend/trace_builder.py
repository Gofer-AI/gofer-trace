from datetime import datetime, timezone
import json
import re

from entity_extraction import enrich
from trace_schema import SCHEMA_VERSION, validate_trace


def _parse_model_json(raw_text: str):
    if not raw_text:
        return {}

    cleaned = raw_text.strip()

    cleaned = cleaned.replace("```json", "").replace("```", "").strip()

    try:
        return json.loads(cleaned)
    except Exception:
        pass

    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except Exception:
            pass

    return {
        "window_or_context": "Unknown screen context",
        "observation": cleaned[:500],
        "user_action": "Could not confidently extract action.",
        "inferred_intent": "Could not confidently infer intent.",
        "agent_hint": "Review this frame manually or improve prompt/context."
    }


def build_trace(
    video_id: str,
    frame_analyses: list[dict],
    *,
    source: dict | None = None,
    model: dict | None = None,
):
    """Convert per-frame model analyses into a schema v1.0 trace.

    Entity extraction and structured `action{}` fields (schema §steps.action) are
    populated in Phase 1; in Phase 0 they are simply omitted (both are optional).
    """
    steps = []

    for i, item in enumerate(frame_analyses):
        parsed = _parse_model_json(item.get("raw_model_output", ""))

        step = {
            "step_id": i + 1,
            "timestamp_sec": item["timestamp_sec"],
            "window_or_context": parsed.get("window_or_context", "Unknown"),
            "observation": parsed.get("observation", ""),
            "user_action": parsed.get("user_action", ""),
            "inferred_intent": parsed.get("inferred_intent", ""),
            "agent_hint": parsed.get("agent_hint", ""),
        }
        # v0 stored "frame_path"; the schema uses "frame_uri".
        frame_uri = item.get("frame_path")
        if frame_uri:
            step["frame_uri"] = frame_uri
        if item.get("raw_model_output"):
            step["raw_model_output"] = item["raw_model_output"]

        steps.append(step)

    # Populate structured action{} + entity_refs per step, and the deduped entity list.
    entities = enrich(steps)

    return {
        "schema_version": SCHEMA_VERSION,
        "workflow_id": video_id,
        "summary": "A human software workflow was converted into structured multimodal agent memory.",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": source or {"kind": "screen_recording"},
        "model": model or {},
        "entities": entities,
        "steps": steps,
    }


def save_trace(video_id: str, trace: dict, traces_dir=None):
    """Validate against the schema, then persist. Kept for scripts/back-compat;
    the app writes through FileKnowledgeBase.put_trace, which does the same."""
    from pathlib import Path
    from settings import get_settings

    validate_trace(trace)

    trace_dir = Path(traces_dir) if traces_dir else get_settings().traces_dir
    trace_dir.mkdir(parents=True, exist_ok=True)

    trace_path = trace_dir / f"{video_id}.json"
    with trace_path.open("w") as f:
        json.dump(trace, f, indent=2)

    return str(trace_path)
