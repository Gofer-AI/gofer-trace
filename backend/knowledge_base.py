"""
knowledge_base.py — the storage seam every layer talks to.

`KnowledgeBase` is the interface (docs/ARCHITECTURE.md §4). `FileKnowledgeBase` is the
local default: it stores schema-valid traces as JSON files under data/traces/ — the same
layout the app used before, now behind an interface and with validate-on-write.

Phase 1 adds `GraphKnowledgeBase` (Bolt/Cypher → Memgraph/Neo4j) implementing the same
interface; nothing that consumes a KnowledgeBase has to change when we swap it in.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol, runtime_checkable

from trace_schema import ensure_v1, validate_trace


@runtime_checkable
class KnowledgeBase(Protocol):
    def put_trace(self, trace: dict) -> None: ...
    def get_workflow(self, workflow_id: str) -> dict | None: ...
    def list_workflows(self) -> list[dict]: ...
    def search(self, query: str, k: int = 5) -> list[dict]: ...
    def similar_steps(self, workflow_id: str, step_id: int) -> list[dict]: ...


def _summarize(trace: dict) -> dict:
    """Compact descriptor of a workflow for listings/search results."""
    return {
        "workflow_id": trace.get("workflow_id", ""),
        "title": trace.get("title", ""),
        "goal": trace.get("goal", ""),
        "summary": trace.get("summary", ""),
        "step_count": len(trace.get("steps", [])),
        "labels": trace.get("labels", []),
        "created_at": trace.get("created_at", ""),
    }


def _search_blob(trace: dict) -> str:
    """Concatenated searchable text for a workflow (Phase 0 keyword search)."""
    parts = [
        trace.get("title", ""),
        trace.get("goal", ""),
        trace.get("summary", ""),
        " ".join(trace.get("labels", [])),
    ]
    for s in trace.get("steps", []):
        parts += [
            s.get("window_or_context", ""),
            s.get("observation", ""),
            s.get("user_action", ""),
            s.get("inferred_intent", ""),
            s.get("agent_hint", ""),
        ]
    return " ".join(p for p in parts if p).lower()


class FileKnowledgeBase:
    """Filesystem-backed KnowledgeBase: one validated JSON trace per workflow."""

    def __init__(self, traces_dir: Path | str):
        self.traces_dir = Path(traces_dir)
        self.traces_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, workflow_id: str) -> Path:
        return self.traces_dir / f"{workflow_id}.json"

    def put_trace(self, trace: dict) -> None:
        """Validate against the schema, then persist. Refuses to write an invalid trace."""
        validate_trace(trace)
        workflow_id = trace["workflow_id"]
        self._path(workflow_id).write_text(json.dumps(trace, indent=2))

    def get_workflow(self, workflow_id: str) -> dict | None:
        path = self._path(workflow_id)
        if not path.exists():
            return None
        # Legacy files on disk are auto-migrated to v1.0 on read.
        return ensure_v1(json.loads(path.read_text()))

    def _iter_traces(self):
        for path in sorted(self.traces_dir.glob("*.json")):
            try:
                yield ensure_v1(json.loads(path.read_text()))
            except (json.JSONDecodeError, OSError):
                continue

    def list_workflows(self) -> list[dict]:
        return [_summarize(t) for t in self._iter_traces()]

    def search(self, query: str, k: int = 5) -> list[dict]:
        """Keyword search over workflow text. Phase 2 replaces this with embeddings."""
        tokens = [t for t in query.lower().split() if t]
        if not tokens:
            return []
        scored: list[tuple[int, dict]] = []
        for trace in self._iter_traces():
            blob = _search_blob(trace)
            score = sum(blob.count(tok) for tok in tokens)
            if score > 0:
                result = _summarize(trace)
                result["score"] = score
                scored.append((score, result))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [r for _, r in scored[:k]]

    def similar_steps(self, workflow_id: str, step_id: int) -> list[dict]:
        # Requires embeddings (Phase 2). Interface is defined now so callers are stable.
        return []
