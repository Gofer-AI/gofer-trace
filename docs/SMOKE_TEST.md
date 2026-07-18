# Smoke test — verifying a real deployment

The offline suite (`tests/test_gofer.py`, run in CI) covers all the pure logic. This
checklist covers the things that need real infrastructure — a running backend, a graph
engine, an agent, a display — which CI can't exercise. Work top to bottom; each section is
independent.

## 0. Prerequisites
```bash
pip install -r backend/requirements.txt   # torch/opencv are heavy; first install is slow
```

## 1. Local file profile (no Docker, no graph)
The fastest confidence check. Uses JSON storage + the offline hashing embedder.
```bash
GOFER_PROFILE=local ./start_backend.sh
python scripts/smoke_test.py --api-base http://localhost:8001 --video path/to/demo.mp4
```
**Expect:** all checks PASS — health, upload, analyze (N steps), list_workflows, search,
trace/plan/export/step_context/similar_steps, metrics.

## 2. Graph profile (Memgraph via Docker)  ← closes Phase 1.3
```bash
docker compose up            # backend + Memgraph + Memgraph Lab
python scripts/smoke_test.py --video path/to/demo.mp4
```
Then open **Memgraph Lab → http://localhost:3000** and run:
```cypher
MATCH (w:Workflow)-[:HAS_STEP]->(s:Step)-[:ACTS_ON]->(e:Entity)
RETURN w.id, s.step_id, e.type, e.name LIMIT 25;
```
**Expect:** the analyzed workflow appears as `:Workflow`/`:Step`/`:Entity` nodes with
`HAS_STEP`/`NEXT`/`ACTS_ON`/`IN_CONTEXT` edges. Re-running `/analyze` is idempotent (no
duplicate steps).

## 3. Cloud graph target (Neo4j / AuraDB)  ← closes Phase 1.4
```bash
GOFER_PROFILE=cloud GOFER_KB=graph \
GOFER_GRAPH_URL="neo4j+s://<id>.databases.neo4j.io" \
GOFER_GRAPH_USER=neo4j GOFER_GRAPH_PASSWORD=... \
GOFER_REQUIRE_AUTH=true GOFER_API_KEYS="sk_demo:demo" \
uvicorn main:app --host 0.0.0.0 --port 8001   # from backend/
python scripts/smoke_test.py --api-key sk_demo --video path/to/demo.mp4
```
**Expect:** the *same* adapter populates AuraDB; smoke checks pass with the key.

## 4. Auth + per-user scoping (cloud)  ← Phase 4.1
```bash
# without a key → 401
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8001/workflows      # 401
# alice and bob only see their own workflows
curl -s -H "X-API-Key: sk_alice" http://localhost:8001/workflows
curl -s -H "X-API-Key: sk_bob"   http://localhost:8001/workflows
```
**Expect:** 401 without a key; each principal sees only workflows they analyzed.

## 5. Async ingestion  ← Phase 4.3
```bash
# returns a job_id immediately
curl -s -X POST "http://localhost:8001/analyze/<video_id>?background=true"
curl -s http://localhost:8001/jobs/<job_id>     # queued → running → done
```

## 6. Semantic embeddings upgrade  ← Phase 2.1
```bash
GOFER_EMBEDDINGS=sentence-transformers ./start_backend.sh
# re-analyze, then confirm search ranks by meaning (synonyms), not just token overlap
```

## 7. MCP from an agent
Point Claude Code at [`.mcp.json`](../.mcp.json) (already in the repo), or copy a config
from [`examples/mcp/`](../examples/mcp/) for Cursor/Codex. Then ask the agent to call
`list_workflows`, `search_workflows("deploy to staging")`, and `load_workflow(<id>)`.
See [AGENTS.md](./AGENTS.md).

## 8. Screen capture client  ← Phase 3.3
```bash
pip install -r capture/requirements.txt
python capture/gofer_capture.py --duration 20 --fps 2 --api-base http://localhost:8001
```
**Expect:** an MP4 is recorded and analyzed; the returned `video_id` shows up in
`list_workflows`. (Requires a display.)
