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

- ☑ **2.1 Embeddings + vector index.** `embeddings.py` (offline `HashingEmbedder` default,
  deterministic across processes; opt-in `sentence-transformers`) + `vector_index.py`
  (`FileVectorIndex`, brute-force cosine) + `semantic_index.py` tying them together.
  Per-workflow and per-step vectors; `steps[].embedding_ref` persisted. *Verified:*
  search survives a fresh process load. ◐ *sqlite-vec/FAISS + graph-native cloud index
  still to come* (interface is ready).
- ☑ **2.2 Semantic search + `find_similar_steps`.** `/search` is now semantic (keyword
  fallback when unindexed); new `/similar-steps` endpoint + `find_similar_steps` MCP tool.
  *Verified:* "deploy the app to staging" ranks the deploy workflow first with no id;
  "change my account password" ranks the password workflow first.
- ☑ **2.3 Markdown agent-memory export as first-class `:Artifact`.** `exporters.py`
  (deterministic SOP markdown + agent-memory JSON) + `/export` endpoint +
  `export_agent_memory` MCP tool; artifacts attached to the trace and linked via
  `:EXPORTS`. *Verified:* export appends artifacts, re-validates, and round-trips.
- ☑ **2.4 `get_step_context`.** New `/step-context` endpoint + MCP tool: entities touched,
  prev/next step, and similar steps elsewhere.

**Milestone (reached, offline):** an agent with no prior context can discover and reuse
the right workflow. Semantic ranking upgrades further with `sentence-transformers`.

---

## Phase 3 — Multi-agent reach & richer capture

> Goal: the MCP surface is a drop-in for every target agent, and capture goes beyond upload.

- ☑ **3.1 Agent configs + HTTP transport.** `docs/AGENTS.md` + ready-to-copy configs in
  `examples/mcp/` (Claude Code, Cursor, Codex, generic/Hermes, HTTP-remote). MCP server
  gains `GOFER_MCP_TRANSPORT=stdio|http|sse`. *Verified:* all configs parse; server starts
  in each transport mode.
- ☑ **3.2 Planner reads structured `action{}`.** `planner.build_execution_plan` uses the
  schema's `action{type,target,value,expected_state}` when present, keyword-guessing only
  for legacy traces. *Verified:* plan is deterministic from the schema; legacy fallback
  still classifies.
- ☑ **3.3 Live capture client.** `capture/gofer_capture.py` records the screen (mss +
  opencv), writes an MP4 + events sidecar, and submits to `/upload`→`/analyze`. Optional
  deps are lazy so `--help`/`--dry-run` run anywhere. ◐ *Live capture needs a display*
  (not runnable headlessly here); folding the events sidecar into the trace
  (`source.kind: "live_capture"`) is the remaining ingestion enhancement.
- ☑ **3.4 Knowledge Base tab in the Space.** Semantic search + workflow listing in the
  Gradio UI (the same `/search` agents use). The full node-link graph explorer is
  Memgraph Lab at `:3000` (shipped in `docker-compose.yml`).

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
