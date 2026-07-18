"""
knowledge_base.py — the storage seam every layer talks to.

`KnowledgeBase` is the interface (docs/ARCHITECTURE.md §4). Two implementations:
  - `FileKnowledgeBase` — local default: schema-valid traces as JSON under data/traces/.
  - `GraphKnowledgeBase` (graph_knowledge_base.py) — Bolt/Cypher → Memgraph or Neo4j.

`create_knowledge_base(settings)` picks one from `GOFER_KB`. Nothing that consumes a
KnowledgeBase changes when the backend is swapped.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Protocol, runtime_checkable

from trace_schema import ensure_v1, validate_trace


@runtime_checkable
class KnowledgeBase(Protocol):
    def put_trace(self, trace: dict) -> None: ...
    def get_workflow(self, workflow_id: str) -> dict | None: ...
    def list_workflows(self) -> list[dict]: ...
    def search(self, query: str, k: int = 5) -> list[dict]: ...
    def similar_steps(self, workflow_id: str, step_id: int) -> list[dict]: ...


# ---------------------------------------------------------------------------
# Shared helpers (used by both File and Graph implementations)
# ---------------------------------------------------------------------------

def summarize_trace(trace: dict) -> dict:
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


def search_blob(trace: dict) -> str:
    """Concatenated searchable text for a workflow (Phase 0/1 keyword search)."""
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
    for e in trace.get("entities", []):
        parts += [e.get("name", ""), e.get("value", "")]
    return " ".join(p for p in parts if p).lower()


def rank_workflows(traces: Iterable[dict], query: str, k: int = 5) -> list[dict]:
    """Keyword-rank workflows by token frequency. Phase 2 replaces this with embeddings."""
    tokens = [t for t in query.lower().split() if t]
    if not tokens:
        return []
    scored: list[tuple[int, dict]] = []
    for trace in traces:
        blob = search_blob(trace)
        score = sum(blob.count(tok) for tok in tokens)
        if score > 0:
            result = summarize_trace(trace)
            result["score"] = score
            scored.append((score, result))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [r for _, r in scored[:k]]


# ---------------------------------------------------------------------------
# Filesystem implementation
# ---------------------------------------------------------------------------

class FileKnowledgeBase:
    """Filesystem-backed KnowledgeBase: one validated JSON trace per workflow."""

    def __init__(self, traces_dir: Path | str):
        self.traces_dir = Path(traces_dir)
        self.traces_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, workflow_id: str) -> Path:
        return self.traces_dir / f"{workflow_id}.json"

    def put_trace(self, trace: dict) -> None:
        validate_trace(trace)
        self._path(trace["workflow_id"]).write_text(json.dumps(trace, indent=2))

    def get_workflow(self, workflow_id: str) -> dict | None:
        path = self._path(workflow_id)
        if not path.exists():
            return None
        return ensure_v1(json.loads(path.read_text()))

    def _iter_traces(self):
        for path in sorted(self.traces_dir.glob("*.json")):
            try:
                yield ensure_v1(json.loads(path.read_text()))
            except (json.JSONDecodeError, OSError):
                continue

    def list_workflows(self) -> list[dict]:
        return [summarize_trace(t) for t in self._iter_traces()]

    def search(self, query: str, k: int = 5) -> list[dict]:
        return rank_workflows(self._iter_traces(), query, k)

    def similar_steps(self, workflow_id: str, step_id: int) -> list[dict]:
        return []  # requires embeddings (Phase 2)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_knowledge_base(settings) -> KnowledgeBase:
    """Build the KnowledgeBase for the current profile (GOFER_KB=file|graph)."""
    if getattr(settings, "kb_backend", "file") == "graph":
        from graph_knowledge_base import GraphKnowledgeBase
        return GraphKnowledgeBase(
            settings.graph_url,
            user=settings.graph_user,
            password=settings.graph_password,
            database=getattr(settings, "graph_database", "") or None,
        )
    return FileKnowledgeBase(settings.traces_dir)
