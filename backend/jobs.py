"""
jobs.py — a minimal in-process job store for asynchronous ingestion.

VLM analysis can take a while; the cloud profile shouldn't block a request on it. This
provides a tiny queued→running→done/error state machine driven by FastAPI BackgroundTasks.
It is in-memory (jobs are lost on restart); a durable queue/worker is the production step
(docs/ROADMAP.md Phase 4.3).
"""
from __future__ import annotations

import threading
import time
import uuid


class JobStore:
    def __init__(self):
        self._jobs: dict[str, dict] = {}
        self._lock = threading.Lock()

    def create(self, video_id: str) -> str:
        job_id = str(uuid.uuid4())
        with self._lock:
            self._jobs[job_id] = {
                "job_id": job_id,
                "video_id": video_id,
                "status": "queued",
                "created_at": time.time(),
                "result": None,
                "error": None,
            }
        return job_id

    def update(self, job_id: str, status: str, result=None, error=None) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job["status"] = status
            job["updated_at"] = time.time()
            if result is not None:
                job["result"] = result
            if error is not None:
                job["error"] = error

    def get(self, job_id: str) -> dict | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None
