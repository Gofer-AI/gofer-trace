"""
redaction.py — strip obvious secrets from a trace before it is persisted.

Screen recordings routinely surface tokens and credentials. A trace is memory that gets
shared with agents and (in the cloud profile) stored remotely, so redaction runs on the
final trace right before `KnowledgeBase.put_trace`. This is a safety net, not a guarantee:
it catches common, high-signal patterns.
"""
from __future__ import annotations

import copy
import re

# (pattern, replacement). Ordered; higher-signal patterns first.
_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED_AWS_KEY]"),
    (re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"), "[REDACTED_GH_TOKEN]"),
    (re.compile(r"\b(?:sk|pk|rk)_[A-Za-z0-9]{16,}\b"), "[REDACTED_KEY]"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"), "[REDACTED_JWT]"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]{16,}=*"), "Bearer [REDACTED]"),
    # credentials embedded in a URL: scheme://user:pass@host
    (re.compile(r"://([^:@/\s]+):([^@/\s]+)@"), r"://\1:[REDACTED]@"),
    # key=value / key: value style secrets
    (re.compile(r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key)\b(\s*[:=]\s*)(\S+)"),
     r"\1\2[REDACTED]"),
]

_TEXT_KEYS = (
    "summary", "goal", "title",
    "observation", "user_action", "inferred_intent", "agent_hint", "raw_model_output",
)


def redact_text(text: str) -> str:
    if not text:
        return text
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def redact_trace(trace: dict) -> dict:
    """Return a redacted deep copy of the trace. The input is not mutated."""
    t = copy.deepcopy(trace)

    for key in ("summary", "goal", "title"):
        if isinstance(t.get(key), str):
            t[key] = redact_text(t[key])

    for step in t.get("steps", []):
        for key in _TEXT_KEYS:
            if isinstance(step.get(key), str):
                step[key] = redact_text(step[key])
        action = step.get("action")
        if isinstance(action, dict):
            for key in ("target", "value", "expected_state"):
                if isinstance(action.get(key), str):
                    action[key] = redact_text(action[key])

    for ent in t.get("entities", []):
        for key in ("name", "value"):
            if isinstance(ent.get(key), str):
                ent[key] = redact_text(ent[key])

    return t
