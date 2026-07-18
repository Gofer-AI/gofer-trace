"""
graph_knowledge_base.py — KnowledgeBase backed by a Bolt/Cypher graph.

One adapter, two engines: Memgraph (local profile) and Neo4j / AuraDB (cloud profile)
both speak the Bolt protocol and Cypher, so only the connection URL differs. See
docs/ARCHITECTURE.md §3 for the node/edge model.

Design notes:
  - The full trace JSON is stored on the :Workflow node (`raw_json`) for exact round-trip
    fidelity in get_workflow, while :Step / :Entity / :Artifact nodes are materialized for
    graph queries (cross-workflow linking through shared entities).
  - Entity kind is kept as a `type` property (not a dynamic sub-label) so the same Cypher
    runs unchanged on both engines. Application entities become :IN_CONTEXT edges; every
    other entity kind becomes an :ACTS_ON edge.
  - The `neo4j` driver is imported lazily so importing this module never requires it.
"""
from __future__ import annotations

import json

from knowledge_base import rank_workflows, summarize_trace
from trace_schema import ensure_v1, validate_trace

# Best-effort uniqueness constraints. Syntax differs across engines, so each is tried in
# both Neo4j-5 and Memgraph form and failures are ignored (MERGE on {id} keeps correctness).
_CONSTRAINTS = [
    ("CREATE CONSTRAINT workflow_id IF NOT EXISTS FOR (w:Workflow) REQUIRE w.id IS UNIQUE",
     "CREATE CONSTRAINT ON (w:Workflow) ASSERT w.id IS UNIQUE"),
    ("CREATE CONSTRAINT entity_id IF NOT EXISTS FOR (e:Entity) REQUIRE e.id IS UNIQUE",
     "CREATE CONSTRAINT ON (e:Entity) ASSERT e.id IS UNIQUE"),
    ("CREATE CONSTRAINT step_id IF NOT EXISTS FOR (s:Step) REQUIRE s.id IS UNIQUE",
     "CREATE CONSTRAINT ON (s:Step) ASSERT s.id IS UNIQUE"),
]


class GraphKnowledgeBase:
    def __init__(self, url, user="", password="", database=None, driver=None):
        self._database = database
        if driver is not None:
            self._driver = driver
        else:
            from neo4j import GraphDatabase
            auth = (user, password) if user else None
            self._driver = GraphDatabase.driver(url, auth=auth)
        self._ensure_constraints()

    # -- connection helpers -------------------------------------------------

    def _session(self):
        if self._database:
            return self._driver.session(database=self._database)
        return self._driver.session()

    def _run(self, query, **params):
        with self._session() as session:
            return [dict(r) for r in session.run(query, **params)]

    def _ensure_constraints(self):
        for neo4j_form, memgraph_form in _CONSTRAINTS:
            for stmt in (neo4j_form, memgraph_form):
                try:
                    self._run(stmt)
                    break
                except Exception:
                    continue

    def close(self):
        self._driver.close()

    # -- writes -------------------------------------------------------------

    def put_trace(self, trace: dict, owner: str | None = None) -> None:
        if owner is not None:
            trace["owner"] = owner
        validate_trace(trace)
        with self._session() as session:
            session.execute_write(self._write_trace_tx, trace, json.dumps(trace))

    @staticmethod
    def _write_trace_tx(tx, trace, raw_json):
        wid = trace["workflow_id"]
        steps = trace.get("steps", [])
        entities = trace.get("entities", [])
        artifacts = trace.get("artifacts", [])

        tx.run(
            """
            MERGE (w:Workflow {id: $id})
            SET w.title = $title, w.goal = $goal, w.summary = $summary,
                w.created_at = $created_at, w.labels = $labels, w.owner = $owner,
                w.raw_json = $raw
            """,
            id=wid, title=trace.get("title", ""), goal=trace.get("goal", ""),
            summary=trace.get("summary", ""), created_at=trace.get("created_at", ""),
            labels=trace.get("labels", []), owner=trace.get("owner", ""), raw=raw_json,
        )

        # Idempotency: rebuild this workflow's steps from scratch on every write.
        tx.run("MATCH (w:Workflow {id: $id})-[:HAS_STEP]->(s:Step) DETACH DELETE s", id=wid)

        tx.run(
            """
            UNWIND $entities AS e
            MERGE (n:Entity {id: e.entity_id})
            SET n.type = e.type, n.name = e.name, n.value = coalesce(e.value, '')
            """,
            entities=entities,
        )

        tx.run(
            """
            MATCH (w:Workflow {id: $id})
            UNWIND $steps AS st
            CREATE (s:Step {id: $id + '#' + toString(st.step_id)})
            SET s.step_id = st.step_id, s.timestamp_sec = st.timestamp_sec,
                s.window_or_context = st.window_or_context,
                s.observation = coalesce(st.observation, ''),
                s.user_action = coalesce(st.user_action, ''),
                s.inferred_intent = coalesce(st.inferred_intent, ''),
                s.agent_hint = coalesce(st.agent_hint, ''),
                s.action_type = coalesce(st.action.type, ''),
                s.action_target = coalesce(st.action.target, '')
            MERGE (w)-[:HAS_STEP]->(s)
            """,
            id=wid, steps=steps,
        )

        # Sequential NEXT edges.
        tx.run(
            """
            MATCH (w:Workflow {id: $id})-[:HAS_STEP]->(s:Step)
            WITH s ORDER BY s.step_id
            WITH collect(s) AS ss
            UNWIND range(0, size(ss) - 2) AS i
            MERGE (ss[i])-[:NEXT]->(ss[i + 1])
            """,
            id=wid,
        )

        # Application entities become IN_CONTEXT; everything else ACTS_ON.
        tx.run(
            """
            UNWIND $steps AS st
            UNWIND coalesce(st.entity_refs, []) AS ref
            MATCH (s:Step {id: $id + '#' + toString(st.step_id)})
            MATCH (e:Entity {id: ref})
            WHERE e.type = 'application'
            MERGE (s)-[:IN_CONTEXT]->(e)
            """,
            id=wid, steps=steps,
        )
        tx.run(
            """
            UNWIND $steps AS st
            UNWIND coalesce(st.entity_refs, []) AS ref
            MATCH (s:Step {id: $id + '#' + toString(st.step_id)})
            MATCH (e:Entity {id: ref})
            WHERE e.type <> 'application'
            MERGE (s)-[:ACTS_ON]->(e)
            """,
            id=wid, steps=steps,
        )

        tx.run(
            """
            MATCH (w:Workflow {id: $id})
            UNWIND $artifacts AS a
            MERGE (art:Artifact {id: $id + '#' + a.kind})
            SET art.kind = a.kind, art.uri = a.uri
            MERGE (w)-[:EXPORTS]->(art)
            """,
            id=wid, artifacts=artifacts,
        )

    # -- reads --------------------------------------------------------------

    def get_workflow(self, workflow_id: str, owner: str | None = None) -> dict | None:
        rows = self._run(
            "MATCH (w:Workflow {id: $id}) RETURN w.raw_json AS j", id=workflow_id
        )
        if not rows or not rows[0].get("j"):
            return None
        trace = ensure_v1(json.loads(rows[0]["j"]))
        if owner is not None and trace.get("owner") != owner:
            return None
        return trace

    def _all_traces(self, owner: str | None = None):
        rows = self._run(
            "MATCH (w:Workflow) WHERE w.raw_json IS NOT NULL "
            "RETURN w.raw_json AS j ORDER BY w.created_at"
        )
        traces = (ensure_v1(json.loads(r["j"])) for r in rows if r.get("j"))
        if owner is not None:
            return [t for t in traces if t.get("owner") == owner]
        return list(traces)

    def list_workflows(self, owner: str | None = None) -> list[dict]:
        return [summarize_trace(t) for t in self._all_traces(owner)]

    def search(self, query: str, k: int = 5, owner: str | None = None) -> list[dict]:
        return rank_workflows(self._all_traces(owner), query, k)

    def similar_steps(self, workflow_id: str, step_id: int) -> list[dict]:
        return []  # requires embeddings (Phase 2)
