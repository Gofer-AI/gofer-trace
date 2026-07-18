"""
semantic_index.py — retrieval over embeddings, independent of the KnowledgeBase backend.

Indexes one vector per workflow and one per step. Powers:
  - search_workflows(query)  — find a workflow by intent, no id needed;
  - similar_steps(id, step)  — "where else did I do something like this?" across recordings.

Runs alongside either KnowledgeBase (file or graph). Step embedding_refs it assigns are
written back onto the trace before persistence (schema field `steps[].embedding_ref`).
"""
from __future__ import annotations

from embeddings import EmbeddingModel, get_embedding_model
from vector_index import FileVectorIndex, VectorIndex


def workflow_text(trace: dict) -> str:
    parts = [trace.get("title", ""), trace.get("goal", ""), trace.get("summary", ""),
             " ".join(trace.get("labels", []))]
    for s in trace.get("steps", []):
        parts += [s.get("window_or_context", ""), s.get("inferred_intent", ""),
                  s.get("user_action", ""), s.get("agent_hint", "")]
    for e in trace.get("entities", []):
        parts += [e.get("name", ""), e.get("value", "")]
    return " ".join(p for p in parts if p)


def step_text(step: dict) -> str:
    parts = [step.get("window_or_context", ""), step.get("observation", ""),
             step.get("user_action", ""), step.get("inferred_intent", ""),
             step.get("agent_hint", "")]
    action = step.get("action") or {}
    parts += [action.get("type", ""), action.get("target", "")]
    return " ".join(p for p in parts if p)


class SemanticIndex:
    def __init__(self, model: EmbeddingModel, index: VectorIndex):
        self.model = model
        self.index = index

    def _wf_key(self, workflow_id: str) -> str:
        return f"wf:{workflow_id}"

    def index_trace(self, trace: dict) -> None:
        """Embed workflow + steps, upsert vectors, and set embedding_ref on each step."""
        workflow_id = trace["workflow_id"]
        # Rebuild this workflow's vectors from scratch (idempotent re-index).
        self.index.delete(self._wf_key(workflow_id))
        self.index.delete_prefix(f"{workflow_id}#")

        texts = [workflow_text(trace)] + [step_text(s) for s in trace.get("steps", [])]
        vectors = self.model.embed(texts)

        self.index.upsert(self._wf_key(workflow_id), vectors[0],
                          {"kind": "workflow", "workflow_id": workflow_id})
        for step, vec in zip(trace.get("steps", []), vectors[1:]):
            ref = f"{workflow_id}#{step['step_id']}"
            self.index.upsert(ref, vec,
                              {"kind": "step", "workflow_id": workflow_id, "step_id": step["step_id"]})
            step["embedding_ref"] = ref
        self.index.save()

    def search_workflows(self, query: str, k: int = 5) -> list[dict]:
        if not query.strip():
            return []
        qv = self.model.embed([query])[0]
        hits = self.index.query(qv, k, where=lambda m: m.get("kind") == "workflow")
        return [{"workflow_id": m["workflow_id"], "score": round(score, 4)}
                for _, score, m in hits]

    def similar_steps(self, workflow_id: str, step_id: int, k: int = 5) -> list[dict]:
        ref = f"{workflow_id}#{step_id}"
        base = self.index.get(ref)
        if base is None:
            return []
        hits = self.index.query(
            base, k + 1, where=lambda m: m.get("kind") == "step")
        out = []
        for id, score, m in hits:
            if id == ref:
                continue
            out.append({"workflow_id": m["workflow_id"], "step_id": m["step_id"],
                        "score": round(score, 4)})
        return out[:k]


def create_semantic_index(settings) -> SemanticIndex:
    model = get_embedding_model(settings)
    index = FileVectorIndex(settings.vectors_dir / "index.json")
    return SemanticIndex(model, index)
