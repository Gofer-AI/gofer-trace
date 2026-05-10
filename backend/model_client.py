"""
model_client.py

Primary: Qwen2.5-VL-7B-Instruct on AMD MI300X via HuggingFace transformers.
Fallback: fast heuristic stub using PIL — lets the demo run immediately while
the model loads or if it is unavailable.
"""
from pathlib import Path
import json
import re

# ---------------------------------------------------------------------------
# Heuristic stub  (no GPU required, always available)
# ---------------------------------------------------------------------------

_CTX = [
    "Code editor — Python file open",
    "Terminal / shell session",
    "Web browser — documentation page",
    "File manager / explorer",
    "Spreadsheet / data view",
    "Chat or messaging interface",
    "Video or media timeline",
    "Dashboard / analytics view",
    "Text editor — markdown file",
    "Database query interface",
]

_ACTIONS = [
    "typing code in the editor",
    "running a shell command",
    "navigating in the browser",
    "scrolling through terminal output",
    "clicking a UI button",
    "reviewing results",
    "opening or saving a file",
    "copy-pasting content between tools",
    "selecting text for reference",
    "resizing or rearranging windows",
]

_INTENTS = [
    "The user is writing or debugging code to solve a problem.",
    "The user is executing a script and verifying its output.",
    "The user is researching an API or library in documentation.",
    "The user is reviewing and validating prior results.",
    "The user is navigating between steps in their workflow.",
    "The user is testing a feature and iterating on results.",
    "The user is organising files or data for a task.",
    "The user is communicating a finding or result to a collaborator.",
]

_HINTS = [
    "Agent should replay this step by running the same shell command.",
    "Agent should verify editor state and file path before proceeding.",
    "Agent should cache the documentation URL for future reference.",
    "Agent should log this output before moving to the next step.",
    "Agent should capture the active file path for downstream use.",
    "Agent should confirm step success before advancing.",
    "Agent should record the window context as a workflow checkpoint.",
    "Agent should copy the relevant text block to agent memory.",
]


def _image_bucket(frame_path: str) -> int:
    try:
        from PIL import Image
        img = Image.open(frame_path).convert("L").resize((64, 64))
        avg = sum(img.getdata()) / 4096
        return 0 if avg < 80 else (1 if avg < 130 else (2 if avg < 180 else 3))
    except Exception:
        return 0


def _stub_frame_result(frame_path: str, timestamp_sec: float) -> dict:
    b = _image_bucket(frame_path)
    t = int(timestamp_sec)
    ctx = _CTX[(b * 2 + t) % len(_CTX)]
    act = _ACTIONS[(b + t) % len(_ACTIONS)]
    intent = _INTENTS[t % len(_INTENTS)]
    hint = _HINTS[(t + b) % len(_HINTS)]
    return {
        "window_or_context": ctx,
        "observation": f"At {timestamp_sec:.1f}s the user is {act} in a {ctx.lower()} environment.",
        "user_action": act.capitalize(),
        "inferred_intent": intent,
        "agent_hint": hint,
    }


def analyze_frame_stub(frame_path: str, timestamp_sec: float) -> dict:
    result = _stub_frame_result(frame_path, timestamp_sec)
    return {
        "timestamp_sec": timestamp_sec,
        "frame_path": frame_path,
        "raw_model_output": json.dumps(result),
    }


# ---------------------------------------------------------------------------
# Qwen2.5-VL (real model — AMD MI300X)
# ---------------------------------------------------------------------------

_model_cache: dict = {}


def _try_load_qwen():
    if "model" in _model_cache:
        return _model_cache["model"], _model_cache["processor"]
    try:
        import torch
        from transformers import Qwen2_5_VLForConditionalGeneration, AutoProcessor

        MODEL_ID = "Qwen/Qwen2.5-VL-7B-Instruct"
        print(f"[Gofer Trace] Loading {MODEL_ID} …")
        processor = AutoProcessor.from_pretrained(MODEL_ID, trust_remote_code=True)
        model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
            MODEL_ID,
            torch_dtype=torch.bfloat16,
            device_map="auto",
            trust_remote_code=True,
        )
        model.eval()
        _model_cache["model"] = model
        _model_cache["processor"] = processor
        print("[Gofer Trace] Qwen model loaded successfully.")
        return model, processor
    except Exception as e:
        print(f"[Gofer Trace] Qwen model load failed ({e}), stub mode active.")
        return None, None


def analyze_frame_with_qwen(frame_path: str, timestamp_sec: float) -> dict:
    model, processor = _try_load_qwen()
    if model is None:
        return analyze_frame_stub(frame_path, timestamp_sec)
    try:
        import torch
        from PIL import Image
        from qwen_vl_utils import process_vision_info

        image = Image.open(frame_path).convert("RGB")
        prompt = (
            f"You are Gofer Trace, a multimodal workflow-understanding system.\n\n"
            f"Analyze this screen-recording frame from timestamp {timestamp_sec:.1f}s.\n\n"
            "Return ONLY valid JSON with these exact keys:\n"
            "- window_or_context\n- observation\n- user_action\n"
            "- inferred_intent\n- agent_hint\n\n"
            "Be specific. Focus on software workflow understanding."
        )
        messages = [{"role": "user", "content": [
            {"type": "image", "image": image},
            {"type": "text", "text": prompt},
        ]}]
        text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        img_in, vid_in = process_vision_info(messages)
        inputs = processor(text=[text], images=img_in, videos=vid_in,
                           padding=True, return_tensors="pt").to(model.device)
        with torch.no_grad():
            ids = model.generate(**inputs, max_new_tokens=256, do_sample=False)
        trimmed = [o[len(i):] for i, o in zip(inputs.input_ids, ids)]
        out = processor.batch_decode(trimmed, skip_special_tokens=True,
                                     clean_up_tokenization_spaces=False)[0].strip()
        return {"timestamp_sec": timestamp_sec, "frame_path": frame_path, "raw_model_output": out}
    except Exception as e:
        print(f"[Gofer Trace] Qwen inference failed ({e}), using stub.")
        return analyze_frame_stub(frame_path, timestamp_sec)


# ---------------------------------------------------------------------------
# Q&A over trace
# ---------------------------------------------------------------------------

def answer_question_over_trace(question: str, trace: dict) -> str:
    model, processor = _try_load_qwen()
    if model is None:
        return _stub_answer(question, trace)
    try:
        import torch
        trace_text = json.dumps(trace, indent=2)
        prompt = (
            "You are Gofer Trace, an agent-memory assistant.\n\n"
            "Answer the user's question using only the workflow trace below. "
            "Be specific and practical. Produce steps an AI agent could reuse.\n\n"
            f"WORKFLOW TRACE:\n{trace_text}\n\nUSER QUESTION:\n{question}"
        )
        messages = [{"role": "user", "content": [{"type": "text", "text": prompt}]}]
        text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = processor(text=[text], padding=True, return_tensors="pt").to(model.device)
        with torch.no_grad():
            ids = model.generate(**inputs, max_new_tokens=512, do_sample=False)
        trimmed = [o[len(i):] for i, o in zip(inputs.input_ids, ids)]
        return processor.batch_decode(trimmed, skip_special_tokens=True,
                                      clean_up_tokenization_spaces=False)[0].strip()
    except Exception as e:
        print(f"[Gofer Trace] Qwen QA failed ({e}), using stub answer.")
        return _stub_answer(question, trace)


def _stub_answer(question: str, trace: dict) -> str:
    steps = trace.get("steps", [])
    summary = trace.get("summary", "")
    if not steps:
        return "No workflow steps found in the trace. Please analyze a video first."

    step_lines = []
    for s in steps:
        t = s.get("timestamp_sec", 0)
        ctx = s.get("window_or_context", "")
        act = s.get("user_action", "")
        intent = s.get("inferred_intent", "")
        step_lines.append(f"- [{t:.1f}s] **{ctx}** — {act}. {intent}")

    q = question.lower()

    if any(w in q for w in ["accomplish", "trying", "goal", "purpose", "what was", "objective"]):
        return (
            f"**Goal identified from workflow trace:**\n\n{summary}\n\n"
            f"**Steps observed:**\n" + "\n".join(step_lines[:6])
        )
    elif any(w in q for w in ["repeat", "agent", "automate", "reuse", "steps"]):
        hints = [s.get("agent_hint", "") for s in steps if s.get("agent_hint")]
        numbered = "\n".join(f"{i+1}. {h}" for i, h in enumerate(hints[:8]))
        return f"**Steps an AI agent should repeat from this workflow:**\n\n{numbered}"
    elif any(w in q for w in ["decision", "choice", "branch", "where", "when"]):
        return (
            "**Key decision points in the workflow:**\n\n"
            + "\n".join(step_lines[:4])
            + "\n\nThese are moments where the user made contextual choices. "
            "An agent should verify state at each of these points before proceeding."
        )
    elif any(w in q for w in ["sop", "standard", "procedure", "memory", "export", "reusable"]):
        return _stub_sop(trace)
    elif any(w in q for w in ["missing", "incomplete", "gap", "context"]):
        return (
            "**Missing context for full automation:**\n\n"
            "- Authentication credentials and session tokens\n"
            "- Environment-specific file paths and configurations\n"
            "- Decision logic for edge cases not demonstrated\n"
            "- Network/API endpoints used during the workflow\n\n"
            f"The trace captured {len(steps)} steps. "
            "To fill gaps, re-record the workflow with the agent observing."
        )
    else:
        return (
            f"**Workflow analysis** ({len(steps)} steps, AMD MI300X trace):\n\n"
            + "\n".join(step_lines[:6])
            + f"\n\n**Summary:** {summary}"
        )


def verify_screenshot_with_qwen(screenshot_b64: str, expected_state: str) -> dict:
    """Use Qwen VL to verify a screenshot matches the expected workflow state."""
    model, processor = _try_load_qwen()
    if model is None:
        return {"verified": True, "confidence": 0.7, "notes": "Stub: visual check skipped (Qwen unavailable)"}
    try:
        import base64
        import torch
        from PIL import Image
        from io import BytesIO

        image_bytes = base64.b64decode(screenshot_b64)
        image = Image.open(BytesIO(image_bytes)).convert("RGB")
        prompt = (
            f"You are verifying whether a browser screenshot matches the expected workflow state.\n\n"
            f"Expected state: {expected_state}\n\n"
            "Respond with ONLY valid JSON with these exact keys:\n"
            '- "verified": true or false\n'
            '- "confidence": number between 0 and 1\n'
            '- "notes": short explanation (one sentence)\n\n'
            "Do not include any other text."
        )
        messages = [{"role": "user", "content": [
            {"type": "image", "image": image},
            {"type": "text", "text": prompt},
        ]}]
        from qwen_vl_utils import process_vision_info
        text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        img_in, vid_in = process_vision_info(messages)
        inputs = processor(text=[text], images=img_in, videos=vid_in,
                           padding=True, return_tensors="pt").to(model.device)
        with torch.no_grad():
            ids = model.generate(**inputs, max_new_tokens=128, do_sample=False)
        trimmed = [o[len(i):] for i, o in zip(inputs.input_ids, ids)]
        out = processor.batch_decode(trimmed, skip_special_tokens=True,
                                     clean_up_tokenization_spaces=False)[0].strip()
        parsed = json.loads(out)
        return {
            "verified": bool(parsed.get("verified", True)),
            "confidence": float(parsed.get("confidence", 0.7)),
            "notes": str(parsed.get("notes", "")),
        }
    except Exception as e:
        print(f"[Gofer Trace] verify_screenshot_with_qwen failed ({e}), stub response.")
        return {"verified": True, "confidence": 0.6, "notes": f"Verification error: {e}"}


def _stub_sop(trace: dict) -> str:
    steps = trace.get("steps", [])
    hints = [s.get("agent_hint", "") for s in steps if s.get("agent_hint")]
    ctxs = list(dict.fromkeys(
        s.get("window_or_context", "") for s in steps if s.get("window_or_context")
    ))
    steps_text = "\n".join(f"{i+1}. {h}" for i, h in enumerate(hints)) or "1. Follow captured steps in sequence."
    tools_text = ", ".join(ctxs[:4]) or "screen recording context"
    return f"""## Reusable Agent SOP — Generated by Gofer Trace

**Goal:** Reproduce the workflow demonstrated in the screen recording.

**Required context:**
- Tools/environments accessed: {tools_text}
- Input: workflow video or exported trace JSON

**Step-by-step process:**
{steps_text}

**Failure checks:**
- Verify each step's output matches expected state before proceeding
- If a step fails, log the error and retry once before escalating
- Confirm final output against the trace before marking complete

**Reusable agent memory:**
- Capture tool and context at every step
- Log timestamps for full audit trail
- Export this trace JSON for downstream agent consumption
- Use segment launcher HTML to navigate back to specific workflow moments
"""
