from pathlib import Path
import json
import re


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


def build_trace(video_id: str, frame_analyses: list[dict]):
    steps = []

    for i, item in enumerate(frame_analyses):
        parsed = _parse_model_json(item.get("raw_model_output", ""))

        steps.append({
            "step_id": i + 1,
            "timestamp_sec": item["timestamp_sec"],
            "window_or_context": parsed.get("window_or_context", "Unknown"),
            "observation": parsed.get("observation", ""),
            "user_action": parsed.get("user_action", ""),
            "inferred_intent": parsed.get("inferred_intent", ""),
            "agent_hint": parsed.get("agent_hint", ""),
            "frame_path": item["frame_path"],
            "raw_model_output": item.get("raw_model_output", "")
        })

    return {
        "workflow_id": video_id,
        "summary": "A human software workflow was converted into structured multimodal agent memory.",
        "steps": steps
    }


def save_trace(video_id: str, trace: dict):
    trace_dir = Path("../data/traces")
    trace_dir.mkdir(parents=True, exist_ok=True)

    trace_path = trace_dir / f"{video_id}.json"
    with trace_path.open("w") as f:
        json.dump(trace, f, indent=2)

    return str(trace_path)

