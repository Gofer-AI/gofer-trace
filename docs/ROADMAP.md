# Gofer Trace — Roadmap

The ordered plan to grow the hackathon MVP into the architecture in
[ARCHITECTURE.md](./ARCHITECTURE.md): a graph knowledge base of workflow memory, served
over MCP, running in both a **local** (offline-capable) and a **cloud** profile.

Each phase leaves the app working and shippable. Phases are ordered so that the earliest,
cheapest, most vendor-neutral work de-risks everything after it.

Legend: ☐ todo · ◐ started · ☑ done

---

## Phase 0 — Foundations (vendor-neutral, unblocks everything)

> Goal: a stable contract and a config seam, so the graph and the local/cloud split
> become mechanical instead of risky.

- ☑ **0.1 Formal trace schema.** `schema/trace.schema.json` (v1.0) + example + migration
  notes.
- ☑ **0.2 Validate-on-write.** `trace_schema.validate_trace` gates every write;
  `FileKnowledgeBase.put_trace` (and `trace_builder.save_trace`) refuse to persist an
  invalid trace. `build_trace` now emits v1.0. *Verified:* a malformed trace raises
  before hitting disk; `example.trace.json` validates.
- ☑ **0.3 `settings.py` + killed the hardcoded IP.** Env-driven `Settings`
  (`GOFER_PROFILE`, `api_base`, `graph_url`, `vlm`, `blob_root`). Removed
  `http://134.199.204.12:8001` from `.mcp.json`, `.cursor/mcp.json`, `space/app.py`,
  `agent/mcp_server.py` (defaults to localhost). *Verified:* `grep -r 134.199.204.12`
  over runtime files is empty.
- ☑ **0.4 `KnowledgeBase` interface + `FileKnowledgeBase`.** Protocol from ARCHITECTURE
  §4, implemented over `data/traces/*.json`. Backend reads/writes and MCP go through it;
  new `GET /workflows` + `GET /search` endpoints. *Verified:* `list_workflows()` returns
  real workflow ids, and the MCP tool is now honest (plus a new `search_workflows`).
- ☑ **0.5 `v0 → v1` migration.** `migrate_v0_to_v1` + `scripts/migrate_traces.py`
  (idempotent, `--dry-run`); legacy files also auto-migrate on read. No VLM re-run.

**Milestone (reached):** one config switch, one storage interface, one validated schema.
No graph yet.

---

## Phase 1 — Knowledge graph (the core gap)

> Goal: workflows live in a graph and link through shared entities. Local = Memgraph,
> cloud = Neo4j, **one Cypher adapter** for both.

- ☑ **1.1 Graph adapter.** `graph_knowledge_base.GraphKnowledgeBase` on the `neo4j`
  driver (Bolt). Best-effort constraints (Neo4j + Memgraph syntax), idempotent upsert of
  `:Workflow/:Step/:Entity/:Artifact` + `HAS_STEP/NEXT/ACTS_ON/IN_CONTEXT/EXPORTS` edges;
  full trace stored as `raw_json` for exact get_workflow round-trip. Selected via
  `GOFER_KB=graph`; `create_knowledge_base()` factory. *Verified* against a fake Bolt
  driver (Cypher issued + round-trip). ◐ *Live Memgraph/Neo4j run still pending* (needs
  Docker, see 1.3).
- ☑ **1.2 Entity extraction.** `entity_extraction.enrich` (wired into `build_trace`)
  emits deduped `entities[]` (application/url/command/file), per-step `entity_refs`, and
  structured `action{}`. *Verified:* two steps sharing `./deploy.sh` produce one
  `cmd:` entity id, so workflows link through it.
- ☑ **1.3 `docker-compose.yml` (local).** Backend (`backend/Dockerfile`) + Memgraph +
  Memgraph Lab, one command. YAML validated. ◐ *`docker compose up` not run here* (no
  Docker daemon in this environment) — needs a run on a Docker host to confirm live.
- ◐ **1.4 Cloud target.** Same adapter targets Neo4j/AuraDB via `GOFER_GRAPH_URL`
  (`neo4j+s://…`) + `GOFER_GRAPH_DATABASE`; env vars documented in `.env.example`.
  *Pending:* a live AuraDB smoke test.
- ☑ **1.5 Redaction pass.** `redaction.redact_trace` strips AWS/GitHub/JWT/bearer keys,
  `key=value` secrets, and URL credentials; runs before `put_trace`. *Verified:* no
  seeded secret survives.

**Milestone (code complete, live-DB run pending):** recordings become connected memory;
cross-workflow queries work through one Cypher adapter on both engines.

---

## Phase 2 — Retrieval & agent memory

> Goal: agents can *find* the right workflow/step, not just fetch one by id.

- ☐ **2.1 Embeddings + vector index.** Per-step/-workflow vectors; `sqlite-vec`/FAISS
  local, graph-native vector index cloud. Store `embedding_ref` on steps.
- ☐ **2.2 `search_workflows` + `find_similar_steps` MCP tools.** Semantic + graph.
  *Accept:* "find a workflow that deploys to staging" returns the right workflow with no id.
- ☐ **2.3 Markdown agent-memory export as first-class `:Artifact`.** SOP/markdown +
  agent-memory JSON persisted and linked via `EXPORTS`.
- ☐ **2.4 `get_step_context` MCP tool.** Step neighborhood (entities, prev/next, similar).

**Milestone:** an agent with no prior context can discover and reuse the right workflow.

---

## Phase 3 — Multi-agent reach & richer capture

> Goal: the MCP surface is a drop-in for every target agent, and capture goes beyond upload.

- ☐ **3.1 Agent configs.** Verified MCP config snippets for Claude Code, Cursor, Codex,
  Hermes; document transport (stdio vs. HTTP) per agent.
- ☐ **3.2 Planner reads structured `action{}`** instead of keyword-guessing in
  `planner.py`. *Accept:* execution plan is deterministic from the schema.
- ☐ **3.3 Live capture client.** Local screen-capture with active-window/URL/input
  metadata; feed the same Understanding pipeline.
- ☐ **3.4 Graph explorer UI.** Read-only view of the workflow graph in the Space.

---

## Phase 4 — Cloud hardening (only for the hosted version)

- ☐ **4.1 AuthN/Z + per-user workflow scoping** on every graph query.
- ☐ **4.2 Object storage (S3/R2)** for videos/frames/artifacts + signed URLs.
- ☐ **4.3 Async ingestion** (queue/worker) so long VLM analysis doesn't block requests.
- ☐ **4.4 Observability** — request/inference metrics, trace-count dashboards.

---

## Suggested first PR after this one

Phase 0.2–0.4 together: **validate-on-write + `settings.py` + `KnowledgeBase`/
`FileKnowledgeBase`.** Small, no new infrastructure, removes the hardcoded IP, and makes
`list_workflows()` actually work — immediate, demoable value and the seam every later
phase plugs into.
