# Gofer Trace

**Multimodal workflow memory for AI agents.**

AI agents are powerful but blind to how real human work happens across screens, tools, windows, and decisions. Gofer Trace records a workflow video, converts it into structured trace memory, and lets an AI agent search, explain, reuse, and export that context.

Built for the AMD Developer Hackathon — runs Qwen2.5-VL-7B-Instruct on AMD MI300X.

---

## Architecture

```
HuggingFace Space UI (Gradio 5.x)
  └── POST /upload          → AMD MI300X FastAPI backend
  └── POST /analyze/{id}    → Qwen2.5-VL-7B frame analysis
  └── GET  /trace/{id}      → structured trace JSON
  └── POST /ask/{id}        → Qwen Q&A over trace
  └── POST /sop/{id}        → reusable SOP / agent memory export
```

## Documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — target architecture, graph model, local vs cloud profiles
- [docs/ROADMAP.md](docs/ROADMAP.md) — phased plan and status
- [docs/AGENTS.md](docs/AGENTS.md) — use the MCP server from Claude Code, Cursor, Codex, Hermes
- [schema/](schema/) — the canonical trace schema (the contract every layer shares)

## Repo layout

```
backend/          FastAPI server + knowledge base
  main.py         API routes (upload/analyze/search/similar/export/plan…)
  settings.py     profile-driven config (GOFER_PROFILE=local|cloud)
  trace_schema.py schema validation + v0→v1 migration
  knowledge_base.py   KnowledgeBase interface + FileKnowledgeBase + factory
  graph_knowledge_base.py  Bolt/Cypher adapter (Memgraph local / Neo4j cloud)
  entity_extraction.py  entities + structured actions from model text
  embeddings.py / vector_index.py / semantic_index.py  semantic retrieval
  redaction.py    strips secrets before persistence
  exporters.py    deterministic SOP markdown + agent-memory JSON
  model_client.py Qwen2.5-VL-7B inference (+ heuristic stub fallback)
  video_processing.py  OpenCV frame extraction

agent/            MCP server (mcp_server.py) + execution planner (planner.py)
capture/          local screen-recording client (gofer_capture.py)
space/            Hugging Face Space UI (Gradio 5.x)
schema/           trace.schema.json — the shared contract
scripts/          migrate_traces.py (v0→v1)
examples/mcp/     ready-to-copy MCP configs per agent
docker-compose.yml  local backend + Memgraph (+ Lab explorer) in one command
start_backend.sh  convenience script to (re)start the backend
```

## Running locally

### Backend (AMD MI300X or any GPU)

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8001
```

Backend serves at `http://localhost:8001`.  
API docs at `http://localhost:8001/docs`.

### Space UI

The Space is deployed at: https://huggingface.co/spaces/jasonokorie/gofer-trace

To run locally:

```bash
cd frontend/hf-space
pip install -r requirements.txt
API_BASE=http://localhost:8001 python app.py
```

## Environment variables

Configuration is profile-driven — see `.env.example` and `backend/settings.py`. Every
value has a safe local default, so `GOFER_PROFILE=local` runs offline against localhost.

| Variable | Default | Description |
|---|---|---|
| `GOFER_PROFILE` | `local` | Deployment profile: `local` or `cloud` |
| `GOFER_API_BASE` / `API_BASE` | `http://localhost:8001` | Backend URL (MCP server + Space); set to your deployed URL in cloud |
| `GOFER_GRAPH_URL` | `bolt://localhost:7687` | Knowledge-base graph (Phase 1): Memgraph local / Neo4j cloud |
| `GOFER_VLM` | `Qwen/Qwen2.5-VL-7B-Instruct` | Understanding model id/label |
| `GOFER_BLOB_ROOT` | `./data` | Filesystem root (local) or object-store prefix (cloud) |

## Demo flow

1. Upload a 10–20 second screen-recording MP4
2. Click **Analyze Workflow** — Qwen reads each frame on AMD MI300X
3. **Segmented Video Launcher** tab — buttons jump the video to each step
4. **Workflow Timeline** tab — step-by-step breakdown
5. **Agent Chat** — ask questions over the trace (Qwen answers in ~3s warm)
6. **Generate SOP** — exports a reusable standard operating procedure
7. Download **Agent Memory JSON** + **Segment Launcher HTML**
