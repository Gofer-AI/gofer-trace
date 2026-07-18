from fastapi import FastAPI, UploadFile, File
from pathlib import Path
import shutil
import uuid
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "agent"))

from settings import get_settings
from knowledge_base import create_knowledge_base
from semantic_index import create_semantic_index
from redaction import redact_trace
from video_processing import extract_frames
from model_client import analyze_frame_with_qwen as analyze_frame_stub
from trace_builder import build_trace

app = FastAPI(title="Gofer Trace API")

from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

settings = get_settings()
settings.ensure_dirs()

# Storage seam — FileKnowledgeBase or GraphKnowledgeBase (Memgraph/Neo4j), chosen by
# GOFER_KB. Endpoints below are identical regardless of backend.
KB = create_knowledge_base(settings)
# Semantic retrieval layer (embeddings + vector index), independent of the KB backend.
SEM = create_semantic_index(settings)

app.mount("/media/videos", StaticFiles(directory=str(settings.videos_dir)), name="videos")
app.mount("/media/frames", StaticFiles(directory=str(settings.frames_dir)), name="frames")
app.mount("/media/artifacts", StaticFiles(directory=str(settings.artifacts_dir)), name="artifacts")

VIDEO_DIR = settings.videos_dir


@app.get("/")
def root():
    return {
        "app": "Gofer Trace",
        "status": "running",
        "profile": settings.profile,
        "message": "Upload a workflow recording, analyze it, and generate agent memory."
    }


@app.get("/workflows")
def list_workflows():
    """List all analyzed workflows in the knowledge base."""
    return {"workflows": KB.list_workflows()}


@app.get("/search")
def search_workflows(q: str, k: int = 5):
    """Semantic workflow search over embeddings; falls back to keyword when unindexed."""
    hits = SEM.search_workflows(q, k)
    results = []
    for h in hits:
        trace = KB.get_workflow(h["workflow_id"])
        if trace:
            from knowledge_base import summarize_trace
            results.append({**summarize_trace(trace), "score": h["score"]})
    if not results:
        results = KB.search(q, k)  # keyword fallback (empty index / no vector hits)
    return {"query": q, "results": results}


@app.post("/upload")
async def upload_video(file: UploadFile = File(...)):
    video_id = str(uuid.uuid4())
    suffix = Path(file.filename).suffix or ".mp4"
    video_path = VIDEO_DIR / f"{video_id}{suffix}"

    with video_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    return {
        "video_id": video_id,
        "filename": file.filename,
        "video_path": str(video_path),
        "video_url": f"/media/videos/{video_id}{suffix}"
    }

@app.post("/analyze/{video_id}")
async def analyze_video(video_id: str):
    matches = list(VIDEO_DIR.glob(f"{video_id}.*"))
    if not matches:
        return {"error": "video not found", "video_id": video_id}

    video_path = str(matches[0])
    frame_sampling_sec = 8.0
    frames = extract_frames(video_path, video_id, every_seconds=frame_sampling_sec)

    frame_analyses = [
        analyze_frame_stub(frame["path"], frame["timestamp_sec"])
        for frame in frames
    ]

    source = {
        "kind": "screen_recording",
        "media_uri": f"/media/videos/{matches[0].name}",
        "frame_sampling_sec": frame_sampling_sec,
    }
    model = {"vlm": settings.vlm, "profile": settings.profile}

    trace = build_trace(video_id, frame_analyses, source=source, model=model)
    trace = redact_trace(trace)     # strip obvious secrets before persistence
    SEM.index_trace(trace)          # embed workflow + steps; sets steps[].embedding_ref
    KB.put_trace(trace)             # validates against the schema before persisting

    return {
        "video_id": video_id,
        "frames_extracted": len(frames),
        "trace_path": str(settings.traces_dir / f"{video_id}.json"),
        "trace": trace
    }

from pydantic import BaseModel
import json


class AskRequest(BaseModel):
    question: str


def _load_trace_or_error(video_id: str):
    """Return (trace, None) or (None, error_dict) via the knowledge base."""
    trace = KB.get_workflow(video_id)
    if trace is None:
        return None, {
            "error": "trace not found",
            "video_id": video_id,
            "hint": "Run /analyze/{video_id} first.",
        }
    return trace, None


@app.get("/trace/{video_id}")
async def get_trace(video_id: str):
    trace, error = _load_trace_or_error(video_id)
    return error or trace


@app.post("/ask/{video_id}")
async def ask_trace(video_id: str, request: AskRequest):
    from model_client import answer_question_over_trace

    trace, error = _load_trace_or_error(video_id)
    if error:
        return error

    answer = answer_question_over_trace(request.question, trace)

    return {
        "video_id": video_id,
        "question": request.question,
        "answer": answer
    }


@app.post("/sop/{video_id}")
async def generate_sop(video_id: str):
    from model_client import answer_question_over_trace

    trace, error = _load_trace_or_error(video_id)
    if error:
        return error

    question = """
Convert this workflow trace into a reusable SOP for an AI agent.
Include:
1. Goal
2. Required context
3. Step-by-step process
4. Failure checks
5. Reusable agent memory
"""

    sop = answer_question_over_trace(question, trace)

    return {
        "video_id": video_id,
        "sop": sop
    }


# ---------------------------------------------------------------------------
# Semantic retrieval + agent-memory export (Phase 2)
# ---------------------------------------------------------------------------

def _find_step(trace: dict, step_id: int) -> dict | None:
    return next((s for s in trace.get("steps", []) if s.get("step_id") == step_id), None)


def _step_brief(trace: dict, step_id: int) -> dict:
    s = _find_step(trace, step_id) or {}
    return {
        "workflow_id": trace.get("workflow_id"),
        "step_id": step_id,
        "window_or_context": s.get("window_or_context", ""),
        "user_action": s.get("user_action", ""),
        "inferred_intent": s.get("inferred_intent", ""),
    }


@app.get("/similar-steps/{video_id}/{step_id}")
def similar_steps(video_id: str, step_id: int, k: int = 5):
    """Find steps across all recordings semantically similar to this one."""
    hits = SEM.similar_steps(video_id, step_id, k)
    enriched = []
    for h in hits:
        trace = KB.get_workflow(h["workflow_id"])
        if trace:
            enriched.append({**_step_brief(trace, h["step_id"]), "score": h["score"]})
    return {"video_id": video_id, "step_id": step_id, "similar": enriched}


@app.get("/step-context/{video_id}/{step_id}")
def step_context(video_id: str, step_id: int):
    """Return a step's neighborhood: entities touched, prev/next step, and similar steps."""
    trace, error = _load_trace_or_error(video_id)
    if error:
        return error
    step = _find_step(trace, step_id)
    if step is None:
        return {"error": "step not found", "video_id": video_id, "step_id": step_id}

    refs = set(step.get("entity_refs", []))
    entities = [e for e in trace.get("entities", []) if e.get("entity_id") in refs]
    step_ids = [s.get("step_id") for s in trace.get("steps", [])]
    idx = step_ids.index(step_id) if step_id in step_ids else -1

    return {
        "video_id": video_id,
        "step": step,
        "entities": entities,
        "previous_step_id": step_ids[idx - 1] if idx > 0 else None,
        "next_step_id": step_ids[idx + 1] if 0 <= idx < len(step_ids) - 1 else None,
        "similar_steps": SEM.similar_steps(video_id, step_id, 5),
    }


@app.post("/export/{video_id}")
def export_artifacts(video_id: str):
    """Generate deterministic SOP markdown + agent-memory JSON and attach them as
    first-class artifacts (linked via :EXPORTS in the graph)."""
    from datetime import datetime, timezone
    from exporters import build_sop_markdown, agent_memory_json

    trace, error = _load_trace_or_error(video_id)
    if error:
        return error

    out_dir = settings.artifacts_dir / video_id
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "sop.md").write_text(build_sop_markdown(trace))
    (out_dir / "memory.json").write_text(agent_memory_json(trace))

    now = datetime.now(timezone.utc).isoformat()
    generated = [
        {"kind": "sop_markdown", "uri": f"/media/artifacts/{video_id}/sop.md", "created_at": now},
        {"kind": "agent_memory_json", "uri": f"/media/artifacts/{video_id}/memory.json", "created_at": now},
    ]
    kept = [a for a in trace.get("artifacts", [])
            if a.get("kind") not in {"sop_markdown", "agent_memory_json"}]
    trace["artifacts"] = kept + generated
    KB.put_trace(trace)  # re-persist so :Artifact/:EXPORTS are materialized

    return {"video_id": video_id, "artifacts": trace["artifacts"]}


# ---------------------------------------------------------------------------
# Execution plan + verification endpoints
# ---------------------------------------------------------------------------

# In-memory execution state store (video_id → state dict)
_EXECUTION_STATE: dict = {}


class VerifyStepRequest(BaseModel):
    video_id: str
    step_id: int
    screenshot_b64: str
    expected_state: str


class ExecutionStateRequest(BaseModel):
    approved: bool
    approved_steps: list[int] = []
    completed_steps: list[int] = []


@app.get("/plan/{video_id}")
async def get_execution_plan(video_id: str):
    """Return the structured browser execution plan derived from the trace."""
    from planner import build_execution_plan

    trace, error = _load_trace_or_error(video_id)
    if error:
        return error

    actions = build_execution_plan(trace)
    state = _EXECUTION_STATE.get(video_id, {})

    return {
        "video_id": video_id,
        "total_steps": len(actions),
        "approved": state.get("approved", False),
        "steps": [a.to_dict() for a in actions],
    }


@app.post("/verify-step")
async def verify_step(request: VerifyStepRequest):
    """Send a screenshot to Qwen on AMD for visual verification of a step."""
    from model_client import verify_screenshot_with_qwen

    result = verify_screenshot_with_qwen(request.screenshot_b64, request.expected_state)
    return {
        "video_id": request.video_id,
        "step_id": request.step_id,
        **result,
    }


@app.get("/execution-state/{video_id}")
async def get_execution_state(video_id: str):
    """Retrieve the current execution state for a workflow."""
    return _EXECUTION_STATE.get(video_id, {
        "video_id": video_id,
        "approved": False,
        "approved_steps": [],
        "completed_steps": [],
    })


@app.post("/execution-state/{video_id}")
async def update_execution_state(video_id: str, request: ExecutionStateRequest):
    """Store execution state (approval, step completion) for a workflow."""
    _EXECUTION_STATE[video_id] = {
        "video_id": video_id,
        "approved": request.approved,
        "approved_steps": request.approved_steps,
        "completed_steps": request.completed_steps,
    }
    return _EXECUTION_STATE[video_id]
