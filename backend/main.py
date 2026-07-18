from fastapi import FastAPI, UploadFile, File
from pathlib import Path
import shutil
import uuid
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "agent"))

from settings import get_settings
from knowledge_base import create_knowledge_base
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

app.mount("/media/videos", StaticFiles(directory=str(settings.videos_dir)), name="videos")
app.mount("/media/frames", StaticFiles(directory=str(settings.frames_dir)), name="frames")

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
    """Search workflows by keyword (Phase 2 upgrades this to semantic search)."""
    return {"query": q, "results": KB.search(q, k)}


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
    trace = redact_trace(trace)  # strip obvious secrets before persistence
    KB.put_trace(trace)  # validates against the schema before persisting

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
