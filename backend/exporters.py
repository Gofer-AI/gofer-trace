"""
exporters.py — deterministic agent-memory exports derived from a structured trace.

Unlike the model-generated SOP (/sop), these are built directly from the schema fields, so
they work offline and are reproducible. Emitted as first-class artifacts (schema
`artifacts[]`) and, in the graph, linked to the workflow via :EXPORTS.
"""
from __future__ import annotations

import json

_ACTION_ICON = {
    "navigate": "🌐", "click": "🖱️", "type": "⌨️",
    "shell": "💻", "screenshot": "📸", "verify": "🔍", "wait": "⏳",
}


def build_sop_markdown(trace: dict) -> str:
    goal = trace.get("goal") or trace.get("title") or trace.get("summary") or "Reproduce the recorded workflow."
    steps = trace.get("steps", [])
    entities = trace.get("entities", [])

    lines = [
        f"# SOP — {trace.get('title') or trace.get('workflow_id', 'Workflow')}",
        "",
        "## Goal",
        goal,
        "",
        "## Required context",
    ]

    by_type: dict[str, list[str]] = {}
    for e in entities:
        by_type.setdefault(e.get("type", "other"), []).append(e.get("name", ""))
    if by_type:
        for etype, names in by_type.items():
            uniq = ", ".join(dict.fromkeys(n for n in names if n))
            lines.append(f"- **{etype}**: {uniq}")
    else:
        lines.append("- (no entities extracted)")

    lines += ["", "## Steps"]
    for s in steps:
        action = s.get("action") or {}
        icon = _ACTION_ICON.get(action.get("type", ""), "▶️")
        desc = s.get("agent_hint") or s.get("user_action") or s.get("observation") or ""
        lines.append(f"{s.get('step_id')}. {icon} {desc}")
        if action.get("target"):
            lines.append(f"   - target: `{action['target']}`")
        if action.get("expected_state"):
            lines.append(f"   - expected: _{action['expected_state']}_")

    lines += [
        "",
        "## Failure checks",
        "- Verify each step's expected state before proceeding.",
        "- If a step fails, re-observe the screen and retry once before escalating.",
        "- Confirm the final state matches the goal before marking complete.",
        "",
        "## Reusable agent memory",
        f"- Workflow id: `{trace.get('workflow_id', '')}`",
        f"- Steps: {len(steps)} · Entities: {len(entities)}",
        "- Load the full trace JSON for structured actions and entity references.",
    ]
    return "\n".join(lines)


def agent_memory_json(trace: dict) -> str:
    """The canonical machine-readable agent memory is the validated trace itself."""
    return json.dumps(trace, indent=2)
