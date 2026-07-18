import os
import json
import tempfile
from pathlib import Path
from html import escape

import gradio as gr
import requests


API_BASE = (os.getenv("GOFER_API_BASE") or os.getenv("API_BASE") or "http://localhost:8001").rstrip("/")

# Module-level session state — single-demo use
STATE: dict = {
    "video_id": None,
    "trace": None,
    "video_url": None,
}


def _safe(d, key, default=""):
    v = d.get(key, default)
    return "" if v is None else str(v)


# ---------------------------------------------------------------------------
# Core pipeline
# ---------------------------------------------------------------------------

def upload_and_analyze(video_path):
    if video_path is None:
        return "Upload or record a video first.", None, "", None, "", None, None

    try:
        with open(video_path, "rb") as f:
            up = requests.post(
                f"{API_BASE}/upload",
                files={"file": (Path(video_path).name, f, "video/mp4")},
                timeout=120,
            )
    except Exception as e:
        return f"Upload error: {e}", None, "", None, "", None, None

    if up.status_code != 200:
        return f"Upload failed ({up.status_code}): {up.text}", None, "", None, "", None, None

    up_data = up.json()
    video_id = up_data["video_id"]
    STATE["video_id"] = video_id

    video_url = up_data.get("video_url", "")
    if video_url.startswith("/"):
        video_url = f"{API_BASE}{video_url}"
    STATE["video_url"] = video_url

    try:
        an = requests.post(f"{API_BASE}/analyze/{video_id}", timeout=1800)
    except Exception as e:
        return f"Analyze error: {e}", video_path, "", None, "", None, None

    if an.status_code != 200:
        return f"Analyze failed ({an.status_code}): {an.text}", video_path, "", None, "", None, None

    an_data = an.json()
    trace = an_data.get("trace", {})
    STATE["trace"] = trace

    status = (
        f"Analysis complete.\n\n"
        f"**Video ID:** `{video_id}`  \n"
        f"**Frames extracted:** `{an_data.get('frames_extracted', '?')}`  \n"
        f"**Steps in trace:** `{len(trace.get('steps', []))}`"
    )

    timeline_md = _render_timeline(trace)
    launcher_btns = _render_launcher_buttons(trace)
    trace_file = _write_trace(video_id, trace)
    launcher_file = _write_launcher(video_id, _render_launcher(video_url, trace))

    return status, video_path, timeline_md, video_path, launcher_btns, trace_file, launcher_file


def _render_timeline(trace):
    steps = trace.get("steps", [])
    if not steps:
        return "No steps found in trace."
    lines = [
        "## Workflow Timeline",
        "",
        f"**Summary:** {escape(trace.get('summary', ''))}",
        "",
    ]
    for s in steps:
        lines += [
            f"### Step {s.get('step_id', '?')} — {s.get('timestamp_sec', 0)}s",
            f"**Context:** {_safe(s, 'window_or_context')}",
            f"**Observation:** {_safe(s, 'observation')}",
            f"**Action:** {_safe(s, 'user_action')}",
            f"**Intent:** {_safe(s, 'inferred_intent')}",
            f"**Agent hint:** {_safe(s, 'agent_hint')}",
            "",
        ]
    return "\n".join(lines)


def _render_launcher(video_url, trace):
    """Standalone HTML file export — keeps embedded video for the downloaded file."""
    if not video_url:
        return "<p>No video URL available.</p>"

    steps = trace.get("steps", [])
    timestamps = [float(s.get("timestamp_sec", 0) or 0) for s in steps]
    btns = ""
    for i, s in enumerate(steps):
        t_start = timestamps[i]
        t_end = timestamps[i + 1] if i + 1 < len(timestamps) else t_start + 15
        sid = s.get("step_id", "?")
        intent = escape(_safe(s, "inferred_intent", "Jump to segment"))
        obs = escape(_safe(s, "observation", ""))
        btns += f"""
        <button class="seg-btn" onclick="jumpTo({t_start},{t_end},this)">
          <span class="seg-title">Step {sid} &middot; {t_start:.1f}s</span>
          <span class="seg-intent">{intent}</span>
          <span class="seg-obs">{obs}</span>
        </button>"""

    if not btns:
        btns = "<p>No segments found.</p>"

    return f"""
<div class="gofer-shell">
  <div class="video-card">
    <video id="goferVideo" controls width="100%" src="{escape(video_url)}"></video>
  </div>
  <div class="segment-card">
    <h3>Contextual Segment Launcher</h3>
    <p>Click a segment to jump the video to that workflow moment.</p>
    <div class="segment-list">{btns}</div>
  </div>
</div>
<script>
var _clipEnd = null, _activeBtn = null;
var _vid = null;
function _getVid() {{
  if (!_vid) _vid = document.getElementById("goferVideo");
  return _vid;
}}
function jumpTo(start, end, btn) {{
  var v = _getVid();
  if (!v) return;
  _clipEnd = end;
  if (_activeBtn) _activeBtn.classList.remove("seg-active");
  _activeBtn = btn;
  btn.classList.add("seg-active");
  v.currentTime = start;
  v.play();
}}
document.addEventListener("DOMContentLoaded", function() {{
  var v = _getVid();
  if (v) v.addEventListener("timeupdate", function() {{
    if (_clipEnd !== null && v.currentTime >= _clipEnd) {{
      v.pause();
      _clipEnd = null;
    }}
  }});
}});
</script>
<style>
.gofer-shell {{display:grid;grid-template-columns:1.1fr 0.9fr;gap:16px;width:100%}}
.video-card,.segment-card {{border:1px solid #263244;background:#0b1220;border-radius:16px;padding:16px}}
.segment-card h3{{margin-top:0}}
.segment-list {{display:flex;flex-direction:column;gap:10px;max-height:520px;overflow-y:auto}}
.seg-btn {{text-align:left;border:1px solid #334155;background:#111827;color:#e5e7eb;padding:12px;border-radius:12px;cursor:pointer;width:100%}}
.seg-btn:hover {{background:#1e293b;border-color:#60a5fa}}
.seg-btn.seg-active {{background:#1e3a5f;border-color:#3b82f6;box-shadow:0 0 0 2px #3b82f640}}
.seg-title {{display:block;font-weight:700;color:#93c5fd;margin-bottom:4px}}
.seg-intent {{display:block;font-size:.92rem;margin-bottom:4px}}
.seg-obs {{display:block;font-size:.82rem;color:#cbd5e1}}
@media(max-width:900px){{.gofer-shell{{grid-template-columns:1fr}}}}
</style>"""


def _render_launcher_buttons(trace):
    """Buttons-only HTML for the in-app launcher tab. Targets the gr.Video player via DOM."""
    steps = trace.get("steps", [])
    if not steps:
        return "<p style='color:#94a3b8'>No segments found. Analyze a video first.</p>"

    timestamps = [float(s.get("timestamp_sec", 0) or 0) for s in steps]
    btns = ""
    for i, s in enumerate(steps):
        t_start = timestamps[i]
        t_end = timestamps[i + 1] if i + 1 < len(timestamps) else t_start + 15
        sid = s.get("step_id", "?")
        intent = escape(_safe(s, "inferred_intent", "Jump to segment"))
        obs = escape(_safe(s, "observation", ""))
        btns += f"""
        <button class="seg-btn" id="seg-btn-{i}" onclick="goferJump({t_start},{t_end},{i})">
          <span class="seg-title">Step {sid} &middot; {t_start:.1f}s</span>
          <span class="seg-intent">{intent}</span>
          <span class="seg-obs">{obs}</span>
        </button>"""

    return f"""
<div class="seg-panel">
  <h3 style="margin:0 0 8px;color:#93c5fd">Contextual Segment Launcher</h3>
  <p style="margin:0 0 12px;font-size:.9rem;color:#94a3b8">
    Click a segment to jump the video and play just that clip.
  </p>
  <div class="segment-list">{btns}</div>
</div>
<script>
(function() {{
  var _clipEnd = null;
  var _activeIdx = null;
  var _listenAttached = false;

  function _findVideo() {{
    var el = document.getElementById("launcher-video-player");
    return el ? el.querySelector("video") : null;
  }}

  window.goferJump = function(start, end, idx) {{
    var v = _findVideo();
    if (!v) {{
      // Video element not ready yet — retry once after a short delay
      setTimeout(function() {{ window.goferJump(start, end, idx); }}, 300);
      return;
    }}
    if (!_listenAttached) {{
      v.addEventListener("timeupdate", function() {{
        if (_clipEnd !== null && v.currentTime >= _clipEnd) {{
          v.pause();
          _clipEnd = null;
        }}
      }});
      _listenAttached = true;
    }}
    _clipEnd = end;
    if (_activeIdx !== null) {{
      var prev = document.getElementById("seg-btn-" + _activeIdx);
      if (prev) prev.classList.remove("seg-active");
    }}
    _activeIdx = idx;
    var btn = document.getElementById("seg-btn-" + idx);
    if (btn) btn.classList.add("seg-active");
    v.currentTime = start;
    v.play();
  }};
}})();
</script>
<style>
.seg-panel {{padding:8px 0}}
.segment-list {{display:flex;flex-direction:column;gap:10px;max-height:480px;overflow-y:auto}}
.seg-btn {{text-align:left;border:1px solid #334155;background:#111827;color:#e5e7eb;padding:12px;border-radius:12px;cursor:pointer;width:100%;font-family:inherit}}
.seg-btn:hover {{background:#1e293b;border-color:#60a5fa}}
.seg-btn.seg-active {{background:#1e3a5f;border-color:#3b82f6;box-shadow:0 0 0 2px #3b82f640}}
.seg-title {{display:block;font-weight:700;color:#93c5fd;margin-bottom:4px}}
.seg-intent {{display:block;font-size:.92rem;margin-bottom:4px}}
.seg-obs {{display:block;font-size:.82rem;color:#cbd5e1}}
</style>"""


def _write_trace(video_id, trace):
    p = Path(tempfile.gettempdir()) / f"gofer_agent_memory_{video_id}.json"
    p.write_text(json.dumps(trace, indent=2))
    return str(p)


def _write_launcher(video_id, launcher_html):
    full = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <title>Gofer Trace Segment Launcher</title>
  <style>body{{margin:0;padding:24px;font-family:Inter,system-ui,sans-serif;background:#020617;color:#e5e7eb}}</style>
</head>
<body>
  <h1>Gofer Trace Segment Launcher</h1>
  <p>Exported contextual video launcher generated from agent memory.</p>
  {launcher_html}
</body>
</html>"""
    p = Path(tempfile.gettempdir()) / f"gofer_segment_launcher_{video_id}.html"
    p.write_text(full)
    return str(p)


# ---------------------------------------------------------------------------
# Chat  (Gradio 5.x message format: list of {"role":..., "content":...} dicts)
# ---------------------------------------------------------------------------

def ask_agent(message: str, history: list) -> list:
    video_id = STATE.get("video_id")
    if not video_id:
        return history + [
            {"role": "user", "content": message},
            {"role": "assistant", "content": "Analyze a video first so the agent has workflow memory."},
        ]
    try:
        r = requests.post(
            f"{API_BASE}/ask/{video_id}",
            json={"question": message},
            timeout=900,
        )
    except Exception as e:
        return history + [
            {"role": "user", "content": message},
            {"role": "assistant", "content": f"Request failed: {e}"},
        ]
    if r.status_code != 200:
        return history + [
            {"role": "user", "content": message},
            {"role": "assistant", "content": f"Request failed ({r.status_code}): {r.text}"},
        ]
    answer = r.json().get("answer", "No answer returned.")
    return history + [
        {"role": "user", "content": message},
        {"role": "assistant", "content": answer},
    ]


def generate_sop():
    video_id = STATE.get("video_id")
    if not video_id:
        return "Analyze a video first."
    try:
        r = requests.post(f"{API_BASE}/sop/{video_id}", timeout=900)
    except Exception as e:
        return f"SOP request failed: {e}"
    if r.status_code != 200:
        return f"SOP failed ({r.status_code}): {r.text}"
    return r.json().get("sop", "No SOP returned.")


def _wf_label(w):
    return w.get("title") or w.get("goal") or w.get("summary") or "(untitled workflow)"


def kb_search(query):
    if not query.strip():
        return "Enter a search query."
    try:
        r = requests.get(f"{API_BASE}/search", params={"q": query, "k": 8}, timeout=60)
    except Exception as e:
        return f"Search failed: {e}"
    if r.status_code != 200:
        return f"Search failed ({r.status_code})."
    results = r.json().get("results", [])
    if not results:
        return f"No workflows matched '{query}'."
    lines = [f"### Results for '{query}'", ""]
    for w in results:
        score = w.get("score", "")
        suffix = f", score {score}" if score != "" else ""
        lines.append(f"- `{w.get('workflow_id')}` — {_wf_label(w)} "
                     f"({w.get('step_count', 0)} steps{suffix})")
    return "\n".join(lines)


def kb_list():
    try:
        r = requests.get(f"{API_BASE}/workflows", timeout=60)
    except Exception as e:
        return f"Failed: {e}"
    if r.status_code != 200:
        return f"Failed ({r.status_code})."
    wf = r.json().get("workflows", [])
    if not wf:
        return "No workflows yet. Analyze a recording first."
    lines = [f"### {len(wf)} workflow(s) in the knowledge base", ""]
    for w in wf:
        lines.append(f"- `{w.get('workflow_id')}` — {_wf_label(w)} ({w.get('step_count', 0)} steps)")
    return "\n".join(lines)


def reset_app():
    STATE.update({"video_id": None, "trace": None, "video_url": None})
    return "Reset complete.", None, "", None, "", None, None, [], ""


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

CSS = """
.gradio-container { max-width: 1400px !important; }
#hero { border-radius: 20px; padding: 22px;
        background: linear-gradient(135deg, #0b1220, #172554);
        border: 1px solid #334155; margin-bottom: 16px; }
#hero h1 { margin: 0; font-size: 2.2rem; }
#hero p  { color: #cbd5e1; font-size: 1rem; margin: 8px 0 0; }
"""

with gr.Blocks(css=CSS, title="Gofer Trace") as demo:

    gr.HTML("""
    <div id="hero">
      <h1>Gofer Trace</h1>
      <p>Multimodal workflow memory for AI agents. Upload a task video, analyze it on AMD MI300X,
         explore the segmented trace, and pilot an agent over the captured context.</p>
    </div>
    """)

    with gr.Row():
        with gr.Column(scale=1):
            video_input = gr.Video(
                label="Upload or record workflow video",
                format="mp4",
            )
            with gr.Row():
                analyze_btn = gr.Button("Analyze Workflow", variant="primary")
                reset_btn   = gr.Button("Reset")
            status_box  = gr.Markdown("Upload a workflow video to begin.")
            trace_dl    = gr.File(label="Export Agent Memory JSON")
            launcher_dl = gr.File(label="Export Segment Launcher HTML")

        with gr.Column(scale=1):
            video_preview = gr.Video(label="Analyzed Video Preview")
            sop_btn       = gr.Button("Generate SOP / Reusable Agent Memory")
            sop_out       = gr.Markdown(label="SOP Output")

    with gr.Tabs():
        with gr.Tab("Segmented Video Launcher"):
            with gr.Row():
                with gr.Column(scale=3):
                    launcher_video = gr.Video(
                        label="Workflow Video",
                        elem_id="launcher-video-player",
                        interactive=False,
                    )
                with gr.Column(scale=2):
                    launcher_btns = gr.HTML(
                        "<p style='color:#94a3b8'>Analyze a video to see segments.</p>"
                    )

        with gr.Tab("Knowledge Base"):
            gr.Markdown(
                "Search across **every** analyzed workflow (semantic). "
                "The same search powers the `search_workflows` MCP tool your agents use."
            )
            with gr.Row():
                kb_query = gr.Textbox(
                    placeholder="e.g. deploy to staging",
                    label="Search workflows", scale=5, lines=1,
                )
                kb_btn = gr.Button("Search", scale=1, variant="primary")
            kb_results = gr.Markdown()
            kb_refresh = gr.Button("List all workflows")
            kb_all = gr.Markdown()

        with gr.Tab("Workflow Timeline"):
            timeline_out = gr.Markdown()

        with gr.Tab("Agent Chat"):
            # Gradio 5.x: type="messages" uses {"role":..., "content":...} format
            chatbot = gr.Chatbot(label="Agent", height=420, type="messages")
            with gr.Row():
                chat_in   = gr.Textbox(
                    placeholder="Ask about the workflow…",
                    label="Your question",
                    scale=5,
                    lines=1,
                )
                chat_send = gr.Button("Send", scale=1, variant="primary")
            gr.Examples(
                examples=[
                    "What was the user trying to accomplish?",
                    "What steps should an AI agent repeat?",
                    "Turn this workflow into reusable agent memory.",
                    "Where did the user appear to make a decision?",
                    "What context is missing for full automation?",
                ],
                inputs=chat_in,
            )

    # ---- Events ----
    analyze_btn.click(
        fn=upload_and_analyze,
        inputs=[video_input],
        outputs=[status_box, video_preview, timeline_out, launcher_video, launcher_btns, trace_dl, launcher_dl],
    )

    sop_btn.click(fn=generate_sop, inputs=[], outputs=[sop_out])

    reset_btn.click(
        fn=reset_app,
        inputs=[],
        outputs=[status_box, video_preview, timeline_out, launcher_video, launcher_btns,
                 trace_dl, launcher_dl, chatbot, sop_out],
    )

    def _send(msg, hist):
        if not msg.strip():
            return hist, ""
        return ask_agent(msg, hist), ""

    chat_send.click(fn=_send, inputs=[chat_in, chatbot], outputs=[chatbot, chat_in])
    chat_in.submit(fn=_send, inputs=[chat_in, chatbot], outputs=[chatbot, chat_in])

    kb_btn.click(fn=kb_search, inputs=[kb_query], outputs=[kb_results])
    kb_query.submit(fn=kb_search, inputs=[kb_query], outputs=[kb_results])
    kb_refresh.click(fn=kb_list, inputs=[], outputs=[kb_all])


demo.launch()
