from fastapi import FastAPI, UploadFile, File
from pathlib import Path
import shutil
import uuid
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "agent"))

from video_processing import extract_frames
from model_client import analyze_frame_with_qwen as analyze_frame_stub
from trace_builder import build_trace, save_trace

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

app.mount("/media/videos", StaticFiles(directory="../data/videos"), name="videos")
app.mount("/media/frames", StaticFiles(directory="../data/frames"), name="frames")

VIDEO_DIR = Path("../data/videos")
VIDEO_DIR.mkdir(parents=True, exist_ok=True)


@app.get("/")
def root():
    return {
        "app": "Gofer Trace",
        "status": "running",
        "message": "Upload a workflow recording, analyze it, and generate agent memory."
    }


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
    frames = extract_frames(video_path, video_id, every_seconds=8.0)

    frame_analyses = [
        analyze_frame_stub(frame["path"], frame["timestamp_sec"])
        for frame in frames
    ]

    trace = build_trace(video_id, frame_analyses)
    trace_path = save_trace(video_id, trace)

    return {
        "video_id": video_id,
        "frames_extracted": len(frames),
        "trace_path": trace_path,
        "trace": trace
    }

from pydantic import BaseModel
import json


class AskRequest(BaseModel):
    question: str


@app.get("/trace/{video_id}")
async def get_trace(video_id: str):
    trace_path = Path("../data/traces") / f"{video_id}.json"

    if not trace_path.exists():
        return {
            "error": "trace not found",
            "video_id": video_id,
            "hint": "Run /analyze/{video_id} first."
        }

    with trace_path.open("r") as f:
        trace = json.load(f)

    return trace


@app.post("/ask/{video_id}")
async def ask_trace(video_id: str, request: AskRequest):
    from model_client import answer_question_over_trace

    trace_path = Path("../data/traces") / f"{video_id}.json"

    if not trace_path.exists():
        return {
            "error": "trace not found",
            "video_id": video_id,
            "hint": "Run /analyze/{video_id} first."
        }

    with trace_path.open("r") as f:
        trace = json.load(f)

    answer = answer_question_over_trace(request.question, trace)

    return {
        "video_id": video_id,
        "question": request.question,
        "answer": answer
    }


@app.post("/sop/{video_id}")
async def generate_sop(video_id: str):
    from model_client import answer_question_over_trace

    trace_path = Path("../data/traces") / f"{video_id}.json"

    if not trace_path.exists():
        return {
            "error": "trace not found",
            "video_id": video_id,
            "hint": "Run /analyze/{video_id} first."
        }

    with trace_path.open("r") as f:
        trace = json.load(f)

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

    trace_path = Path("../data/traces") / f"{video_id}.json"
    if not trace_path.exists():
        return {"error": "trace not found", "video_id": video_id,
                "hint": "Run /analyze/{video_id} first."}

    with trace_path.open("r") as f:
        trace = json.load(f)

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
