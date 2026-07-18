# Gofer Trace — screen capture client

Records your screen and submits it to the Gofer Trace backend, so a live recording flows
through the same understanding → knowledge-base pipeline as an uploaded video. This is the
"screen recorder captures context" half of the product, without going through the web UI.

```bash
pip install -r capture/requirements.txt

# record 20s at 2fps and analyze against a local backend
python capture/gofer_capture.py --duration 20 --fps 2 --api-base http://localhost:8001

# just print what it would do
python capture/gofer_capture.py --dry-run

# record only, don't upload
python capture/gofer_capture.py --no-submit --out demo.mp4
```

Output: an MP4 plus a `.events.json` sidecar (active-window title per frame, best-effort).
The backend returns a `video_id`; from there use the MCP tools (`search_workflows`,
`load_workflow`, …) or the Space UI.

**Notes**
- Requires a display/session to capture. `mss` handles Windows/macOS/Linux(X11).
- Active-window titles depend on the OS; capture still works without them.
- Folding the events sidecar into the trace (`source.kind: "live_capture"`, per-step
  window metadata) is a planned ingestion enhancement — see docs/ROADMAP.md Phase 3.
