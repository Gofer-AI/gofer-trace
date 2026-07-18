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
  notes. *Done in this change.*
- ☐ **0.2 Validate-on-write.** `trace_builder.save_trace` validates against the schema
  and refuses to persist an invalid trace.
  *Accept:* a malformed trace raises before hitting disk; `example.trace.json` passes.
- ☐ **0.3 `settings.py` + kill the hardcoded IP.** One env-driven config
  (`GOFER_PROFILE`, `api_base`, `graph_url`, `vlm`, `blob_root`). Replace
  `http://134.199.204.12:8001` in `.mcp.json`, `.cursor/mcp.json`, `space/app.py`,
  `agent/mcp_server.py`.
  *Accept:* `grep -r 134.199.204.12` returns nothing; app runs with `GOFER_PROFILE=local`
  against localhost.
- ☐ **0.4 `KnowledgeBase` interface + `FileKnowledgeBase`.** Define the Protocol from
  ARCHITECTURE §4; implement it over today's `data/traces/*.json` (no behavior change,
  just the seam). Route backend + MCP reads/writes through it.
  *Accept:* `list_workflows()` returns real workflow ids from disk — the first user-visible
  win, and it makes the MCP tool honest.
- ☐ **0.5 `v0 → v1` migration helper.** Lift existing flat traces to schema v1.0 (new
  fields default empty), no VLM re-run.

**Milestone:** one config switch, one storage interface, one validated schema. No graph yet.

---

## Phase 1 — Knowledge graph (the core gap)

> Goal: workflows live in a graph and link through shared entities. Local = Memgraph,
> cloud = Neo4j, **one Cypher adapter** for both.

- ☐ **1.1 Graph adapter.** `GraphKnowledgeBase(KnowledgeBase)` on the `neo4j` Python
  driver (Bolt). Constraints + upsert from a schema-valid trace (ARCHITECTURE §3 Cypher).
  *Accept:* `put_trace` upserts `:Workflow/:Step/:Entity/:Artifact` + edges; re-ingesting
  the same trace is idempotent.
- ☐ **1.2 Entity extraction.** Extend `trace_builder.py` to emit `entities[]` +
  per-step `entity_refs` + structured `action{}` from the VLM output.
  *Accept:* two workflows that run the same command share one `:Entity {command}` node.
- ☐ **1.3 `docker-compose.yml` (local).** Backend + Memgraph, one command.
  *Accept:* `docker compose up` → analyze a video → workflow visible via Cypher.
- ☐ **1.4 Cloud target.** Point `GraphKnowledgeBase` at Neo4j AuraDB via
  `GOFER_PROFILE=cloud`; document env vars.
  *Accept:* the *identical* adapter code populates AuraDB; a graph query returns the workflow.
- ☐ **1.5 Redaction pass.** Strip obvious secrets (tokens, passwords) before persistence.

**Milestone:** recordings become connected memory; cross-workflow Cypher queries work on
both engines.

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
