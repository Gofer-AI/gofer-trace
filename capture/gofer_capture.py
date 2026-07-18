#!/usr/bin/env python3
"""
gofer_capture.py — local screen-recording client for Gofer Trace.

Records the screen for a fixed duration, writes an MP4, and submits it to the backend
(/upload → /analyze) so it flows through the same understanding → knowledge-base pipeline
as an uploaded video. Optionally records a lightweight events sidecar (active-window title
per frame) that a future ingestion pass can fold into the trace.

Heavy/OS-specific deps (mss for capture, opencv for encoding) are imported lazily so this
module imports anywhere and `--help` / `--dry-run` work without a display.

    pip install -r capture/requirements.txt
    python capture/gofer_capture.py --duration 20 --fps 2 --api-base http://localhost:8001
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path


def _active_window_title() -> str:
    """Best-effort active-window title; empty string if unavailable on this platform."""
    try:
        import pygetwindow  # optional
        w = pygetwindow.getActiveWindow()
        return getattr(w, "title", "") or ""
    except Exception:
        return ""


def capture(duration: float, fps: float, monitor: int = 1):
    """Grab screen frames for `duration` seconds at `fps`. Returns (frames, events).

    frames: list of BGR numpy arrays (for opencv). events: list of {t, window} dicts.
    """
    import numpy as np  # via opencv/mss install
    from mss import mss

    frames, events = [], []
    interval = 1.0 / fps
    end = time.time() + duration
    with mss() as sct:
        mon = sct.monitors[monitor]
        while time.time() < end:
            t0 = time.time()
            shot = sct.grab(mon)
            frame = np.asarray(shot)[:, :, :3]  # BGRA → BGR
            frames.append(frame)
            events.append({"t": round(t0, 3), "window": _active_window_title()})
            sleep = interval - (time.time() - t0)
            if sleep > 0:
                time.sleep(sleep)
    return frames, events


def write_video(frames, path: Path, fps: float) -> Path:
    import cv2

    if not frames:
        raise RuntimeError("No frames captured.")
    h, w = frames[0].shape[:2]
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    for f in frames:
        writer.write(f)
    writer.release()
    return path


def submit(video_path: Path, api_base: str) -> dict:
    import requests

    api_base = api_base.rstrip("/")
    with open(video_path, "rb") as f:
        up = requests.post(f"{api_base}/upload",
                           files={"file": (video_path.name, f, "video/mp4")}, timeout=300)
    up.raise_for_status()
    video_id = up.json()["video_id"]
    an = requests.post(f"{api_base}/analyze/{video_id}", timeout=1800)
    an.raise_for_status()
    return {"video_id": video_id, **an.json()}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Record the screen and send it to Gofer Trace.")
    parser.add_argument("--duration", type=float, default=20.0, help="Seconds to record.")
    parser.add_argument("--fps", type=float, default=2.0, help="Frames per second.")
    parser.add_argument("--monitor", type=int, default=1, help="Monitor index (mss).")
    parser.add_argument("--api-base", default=os.getenv("GOFER_API_BASE") or os.getenv("API_BASE") or "http://localhost:8001")
    parser.add_argument("--out", default=None, help="Where to write the MP4 (default: temp).")
    parser.add_argument("--no-submit", action="store_true", help="Record only; do not upload.")
    parser.add_argument("--dry-run", action="store_true", help="Print config and exit (no capture).")
    args = parser.parse_args(argv)

    out = Path(args.out) if args.out else Path(f"gofer_capture_{int(time.time())}.mp4")

    if args.dry_run:
        print(json.dumps({
            "duration": args.duration, "fps": args.fps, "monitor": args.monitor,
            "api_base": args.api_base, "out": str(out), "submit": not args.no_submit,
        }, indent=2))
        return 0

    print(f"[capture] recording {args.duration}s @ {args.fps}fps …")
    frames, events = capture(args.duration, args.fps, args.monitor)
    write_video(frames, out, args.fps)
    out.with_suffix(".events.json").write_text(json.dumps(events, indent=2))
    print(f"[capture] wrote {out} ({len(frames)} frames) + events sidecar")

    if args.no_submit:
        return 0

    print(f"[capture] submitting to {args.api_base} …")
    result = submit(out, args.api_base)
    print(f"[capture] analyzed. video_id={result.get('video_id')} "
          f"steps={len(result.get('trace', {}).get('steps', []))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
