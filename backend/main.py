from fastapi import FastAPI, UploadFile, File
from pathlib import Path
import shutil
import uuid

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
