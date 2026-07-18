"""
planner.py

Converts Gofer Trace step objects into BrowserAction objects that Claude Code
(orchestrated via MCP) can execute step-by-step with @playwright/mcp.
"""
from dataclasses import dataclass, asdict
import re

ACTION_ICONS = {
    "navigate": "🌐",
    "click": "🖱️",
    "type": "⌨️",
    "shell": "💻",
    "screenshot": "📸",
    "verify": "🔍",
}

_NAVIGATE_WORDS = {"navigate", "open", "go to", "visit", "url", "browser", "launch", "load"}
_CLICK_WORDS = {"click", "press", "select", "toggle", "tap", "button", "link", "menu"}
_TYPE_WORDS = {"type", "enter", "input", "write", "fill", "search", "query"}
_SHELL_WORDS = {"run", "execute", "command", "shell", "terminal", "script", "cmd"}


@dataclass
class BrowserAction:
    step_id: int
    action_type: str        # navigate | click | type | shell | screenshot | verify
    target: str             # URL, CSS selector, element description, or command
    value: str              # text to type (empty for other actions)
    description: str        # human-readable sentence
    expected_state: str     # what should be visible after this action (for Qwen verify)
    requires_visual_confirm: bool

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def icon(self) -> str:
        return ACTION_ICONS.get(self.action_type, "▶️")


def _classify_action(agent_hint: str, user_action: str, observation: str) -> str:
    text = f"{agent_hint} {user_action} {observation}".lower()
    if any(w in text for w in _NAVIGATE_WORDS):
        return "navigate"
    if any(w in text for w in _CLICK_WORDS):
        return "click"
    if any(w in text for w in _TYPE_WORDS):
        return "type"
    if any(w in text for w in _SHELL_WORDS):
        return "shell"
    return "verify"


def _extract_target(agent_hint: str, observation: str, action_type: str) -> str:
    # Try to pull a URL from the text
    url_match = re.search(r"https?://[^\s\"'>]+", agent_hint + " " + observation)
    if url_match and action_type == "navigate":
        return url_match.group(0)

    # Try to pull a quoted element name
    quoted = re.search(r'["\']([^"\']{3,40})["\']', agent_hint)
    if quoted:
        return quoted.group(1)

    # Fallback: use context from observation (first ~60 chars)
    return observation[:60].strip() or agent_hint[:60].strip()


def build_execution_plan(trace: dict) -> list[BrowserAction]:
    """Convert a workflow trace into an ordered list of BrowserActions.

    Prefers the structured `action{}` field carried by the schema (deterministic); falls
    back to keyword classification only for legacy traces that lack it.
    """
    steps = trace.get("steps", [])
    actions: list[BrowserAction] = []

    for s in steps:
        step_id = int(s.get("step_id", len(actions) + 1))
        agent_hint = s.get("agent_hint", "")
        user_action = s.get("user_action", "")
        observation = s.get("observation", "")
        ctx = s.get("window_or_context", "")
        intent = s.get("inferred_intent", "")

        structured = s.get("action") or {}
        structured_type = structured.get("type", "")

        if structured_type and structured_type != "unknown":
            # Schema-derived, deterministic path.
            action_type = structured_type
            target = structured.get("target") or _extract_target(agent_hint, observation, action_type)
            value = structured.get("value", "")
            expected_state = structured.get("expected_state") or f"{intent} Context: {ctx}."
        else:
            # Legacy fallback: infer from free text.
            action_type = _classify_action(agent_hint, user_action, observation)
            target = _extract_target(agent_hint, observation, action_type)
            value = ""
            expected_state = f"Browser reflects: {intent} Context: {ctx}."

        description = agent_hint or f"{user_action} in {ctx}"

        actions.append(BrowserAction(
            step_id=step_id,
            action_type=action_type,
            target=target,
            value=value,
            description=description,
            expected_state=expected_state,
            requires_visual_confirm=True,
        ))

    return actions


def format_plan_as_text(actions: list[BrowserAction]) -> str:
    """Return a human-readable numbered checklist of the execution plan."""
    if not actions:
        return "No steps in execution plan."
    lines = ["**Execution Plan:**\n"]
    for a in actions:
        lines.append(f"{a.step_id}. {a.icon} **{a.action_type.upper()}** — {a.description}")
        lines.append(f"   Target: `{a.target}`")
        lines.append(f"   Expected after: _{a.expected_state}_")
        lines.append("")
    return "\n".join(lines)
