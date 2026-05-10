"""
mcp_server.py — Gofer Trace MCP Server

Exposes workflow memory, execution planning, and Qwen-based visual verification
as MCP tools consumable by Claude Code, Cursor, or any MCP-compatible agent.

Transport: stdio (default)

Setup:
  pip install "mcp[cli]" requests
  python mcp_server.py

Claude Code (.mcp.json):
  {"mcpServers": {"gofer-trace": {"type":"stdio","command":"python",
    "args":["agent/mcp_server.py"],"env":{"API_BASE":"http://134.199.204.12:8001"}}}}
"""
import os
import json
import requests
from mcp.server.fastmcp import FastMCP

API_BASE = os.getenv("API_BASE", "http://134.199.204.12:8001").rstrip("/")

mcp = FastMCP("Gofer Trace")

# In-process approval gate — must call approve_plan() before verify_step/execute
_APPROVED_PLANS: dict[str, bool] = {}
# In-process step completion tracking
_COMPLETED_STEPS: dict[str, list[int]] = {}


def _get(path: str) -> dict:
    try:
        r = requests.get(f"{API_BASE}{path}", timeout=30)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def _post(path: str, body: dict | None = None) -> dict:
    try:
        r = requests.post(f"{API_BASE}{path}", json=body or {}, timeout=60)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Workflow discovery
# ---------------------------------------------------------------------------

@mcp.tool()
def list_workflows() -> str:
    """
    List all analyzed workflows available for agent execution.
    Returns workflow IDs and step counts. Call this first to find a video_id.
    """
    data = _get("/")
    if "error" in data:
        return f"Backend unreachable: {data['error']}\nEnsure API_BASE={API_BASE} is correct."

    # Scan traces directory via backend status, then list known files
    # We call root just to confirm connectivity, then return guidance
    return (
        f"Gofer Trace backend is running at {API_BASE}.\n\n"
        "To find available workflows, check the Gofer Trace UI after uploading and analyzing a video. "
        "The video_id is displayed in the status box after analysis.\n\n"
        "Once you have a video_id, call load_workflow(video_id) to load its context."
    )


# ---------------------------------------------------------------------------
# Workflow context loading
# ---------------------------------------------------------------------------

@mcp.tool()
def load_workflow(video_id: str) -> str:
    """
    Load a workflow's full trace and SOP as agent context.
    Always call this before review_plan or get_execution_plan.

    Args:
        video_id: The workflow ID shown in the Gofer Trace UI after analysis.
    """
    trace = _get(f"/trace/{video_id}")
    if "error" in trace:
        return f"Could not load workflow '{video_id}': {trace['error']}"

    steps = trace.get("steps", [])
    summary = trace.get("summary", "")

    lines = [
        f"# Workflow: {video_id}",
        f"**Summary:** {summary}",
        f"**Total steps:** {len(steps)}",
        "",
        "## Steps",
    ]
    for s in steps:
        lines += [
            f"### Step {s.get('step_id')} ({s.get('timestamp_sec', 0):.1f}s)",
            f"- **Context:** {s.get('window_or_context', '')}",
            f"- **Observation:** {s.get('observation', '')}",
            f"- **Action:** {s.get('user_action', '')}",
            f"- **Intent:** {s.get('inferred_intent', '')}",
            f"- **Agent hint:** {s.get('agent_hint', '')}",
            "",
        ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Execution planning
# ---------------------------------------------------------------------------

@mcp.tool()
def get_execution_plan(video_id: str) -> str:
    """
    Get the browser execution plan derived from a workflow trace.
    Returns a numbered list of steps with action types and targets.

    Args:
        video_id: The workflow ID to get the plan for.
    """
    plan = _get(f"/plan/{video_id}")
    if "error" in plan:
        return f"Could not fetch plan for '{video_id}': {plan['error']}"

    steps = plan.get("steps", [])
    approved = plan.get("approved", False)
    icons = {"navigate": "🌐", "click": "🖱️", "type": "⌨️",
             "shell": "💻", "screenshot": "📸", "verify": "🔍"}

    lines = [
        f"# Execution Plan — {video_id}",
        f"**Steps:** {len(steps)} | **Pre-approved in UI:** {'✅ Yes' if approved else '⏳ Not yet'}",
        "",
    ]
    for s in steps:
        icon = icons.get(s.get("action_type", "verify"), "▶️")
        lines += [
            f"{s['step_id']}. {icon} **{s.get('action_type','').upper()}** — {s.get('description','')}",
            f"   Target: `{s.get('target','')}`",
            f"   Expected: _{s.get('expected_state','')}_",
            "",
        ]
    return "\n".join(lines)


@mcp.tool()
def review_plan(video_id: str) -> str:
    """
    Present the execution plan for human review.
    You MUST show this output to the user and wait for their explicit 'approve'
    before calling approve_plan(). Do not proceed without user confirmation.

    Args:
        video_id: The workflow ID to review.
    """
    plan_text = get_execution_plan(video_id)
    return (
        plan_text
        + "\n\n---\n"
        "**⚠️ REVIEW REQUIRED**\n\n"
        "Show the plan above to the user. Once they explicitly confirm (e.g. 'approve', "
        "'yes proceed', 'looks good'), call `approve_plan(video_id)` to open the execution gate.\n"
        "Do NOT call approve_plan without explicit user confirmation."
    )


@mcp.tool()
def approve_plan(video_id: str) -> str:
    """
    Open the execution gate for this workflow.
    Call this ONLY after the user has explicitly approved the plan shown by review_plan().

    Args:
        video_id: The workflow ID to approve for execution.
    """
    _APPROVED_PLANS[video_id] = True
    _COMPLETED_STEPS.setdefault(video_id, [])

    # Also update backend state
    _post(f"/execution-state/{video_id}", {
        "approved": True,
        "approved_steps": [],
        "completed_steps": [],
    })

    return (
        f"✅ Execution gate open for workflow **{video_id}**.\n\n"
        "You may now execute steps. Recommended sequence per step:\n"
        "1. Call the appropriate @playwright/mcp tool (e.g. `browser_navigate`, `browser_click`)\n"
        "2. Call `browser_screenshot` via @playwright/mcp\n"
        "3. Call `verify_step(video_id, step_id, screenshot_b64)` to confirm with Qwen\n"
        "4. Call `mark_step_complete(video_id, step_id)` when verified\n"
        "5. Proceed to next step or pause if verification fails."
    )


# ---------------------------------------------------------------------------
# Step verification (Qwen on AMD)
# ---------------------------------------------------------------------------

@mcp.tool()
def verify_step(video_id: str, step_id: int, screenshot_b64: str) -> str:
    """
    Verify that a browser action completed correctly using Qwen vision on AMD MI300X.
    Call this after every Playwright action — pass the base64 screenshot.

    Args:
        video_id: The workflow ID being executed.
        step_id: The step number just executed (from the execution plan).
        screenshot_b64: Base64-encoded PNG screenshot from browser_screenshot.
    """
    if not _APPROVED_PLANS.get(video_id):
        return (
            "❌ Execution gate is closed. You must call review_plan() → get user approval "
            "→ approve_plan() before executing and verifying steps."
        )

    # Get expected state for this step
    plan = _get(f"/plan/{video_id}")
    steps = plan.get("steps", [])
    step_data = next((s for s in steps if s.get("step_id") == step_id), {})
    expected_state = step_data.get("expected_state", f"Step {step_id} completed successfully")

    result = _post("/verify-step", {
        "video_id": video_id,
        "step_id": step_id,
        "screenshot_b64": screenshot_b64,
        "expected_state": expected_state,
    })

    if "error" in result:
        return f"Verification request failed: {result['error']}"

    verified = result.get("verified", False)
    confidence = result.get("confidence", 0.0)
    notes = result.get("notes", "")
    icon = "✅" if verified else "⚠️"

    return (
        f"{icon} Step {step_id} verification: **{'PASSED' if verified else 'FAILED'}**\n"
        f"Confidence: {confidence:.0%}\n"
        f"Qwen notes: {notes}\n\n"
        + ("Proceed to next step." if verified else
           "Step may not have completed correctly. Review the screenshot and retry or skip.")
    )


@mcp.tool()
def mark_step_complete(video_id: str, step_id: int, notes: str = "") -> str:
    """
    Record that a step was completed successfully.
    Call after verify_step confirms the step passed.

    Args:
        video_id: The workflow ID being executed.
        step_id: The step number that was completed.
        notes: Optional notes about what happened (useful for audit trail).
    """
    if not _APPROVED_PLANS.get(video_id):
        return "❌ Plan not approved. Call approve_plan() first."

    completed = _COMPLETED_STEPS.setdefault(video_id, [])
    if step_id not in completed:
        completed.append(step_id)

    _post(f"/execution-state/{video_id}", {
        "approved": True,
        "approved_steps": [],
        "completed_steps": completed,
    })

    plan = _get(f"/plan/{video_id}")
    total = plan.get("total_steps", "?")
    remaining = int(total) - len(completed) if isinstance(total, int) else "?"

    return (
        f"✅ Step {step_id} marked complete. {notes}\n"
        f"Progress: {len(completed)}/{total} steps done. "
        f"{remaining} remaining."
    )


# ---------------------------------------------------------------------------
# Natural language Q&A
# ---------------------------------------------------------------------------

@mcp.tool()
def ask_workflow(video_id: str, question: str) -> str:
    """
    Ask a natural-language question about a workflow trace.
    Qwen on AMD answers based on the captured steps and observations.

    Args:
        video_id: The workflow ID to query.
        question: Any question about the workflow (what, why, how, next steps, etc.).
    """
    result = _post(f"/ask/{video_id}", {"question": question})
    if "error" in result:
        return f"Q&A failed: {result['error']}"
    return result.get("answer", "No answer returned.")


if __name__ == "__main__":
    mcp.run()
