"""
entity_extraction.py — turn per-step model text into the structured fields the graph
needs: deduplicated `entities[]`, per-step `entity_refs`, and an executable `action{}`.

Shared entities (an application, a command, a URL, a file) are what turn a pile of
recordings into connected memory: two workflows that both run `./deploy.sh` reference
the same `entity_id`, so they link through one node in the graph.

This is deterministic/heuristic extraction — good enough to populate the graph today.
A VLM-driven extraction pass can replace the internals later without changing the shape.
"""
from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

_URL_RE = re.compile(r"https?://[^\s\"'>)\]]+")
_BACKTICK_RE = re.compile(r"`([^`]+)`")
_FILE_RE = re.compile(r"\b[\w./~-]+\.[A-Za-z0-9]{1,6}\b")

_CODE_EXT = {
    "py", "js", "ts", "tsx", "jsx", "java", "go", "rs", "rb", "c", "cpp", "h",
    "json", "yaml", "yml", "md", "sh", "sql", "html", "css", "txt", "cfg", "toml", "ini",
}
_CMD_PREFIXES = (
    "run ", "./", "git ", "npm ", "pip ", "python ", "python3 ", "docker ", "make ",
    "curl ", "uvicorn ", "kubectl ", "yarn ", "node ", "cd ", "ls ", "cat ", "sudo ",
)

_APP_KEYWORDS = [
    (("terminal", "shell", "command line", "bash", "zsh", "console"), "Terminal"),
    (("chrome", "firefox", "safari", "browser", "edge"), "Browser"),
    (("vs code", "vscode", "code editor", "editor", "intellij", "pycharm", "sublime"), "Code editor"),
    (("slack", "discord", "teams", "messaging", "chat"), "Chat"),
    (("spreadsheet", "excel", "sheets"), "Spreadsheet"),
    (("file manager", "explorer", "finder"), "File manager"),
    (("database", "sql", "query interface"), "Database"),
]

# ---------------------------------------------------------------------------
# Action classification (shared vocabulary with planner.py)
# ---------------------------------------------------------------------------

_NAVIGATE_WORDS = {"navigate", "open", "go to", "visit", "url", "browser", "launch", "load"}
_CLICK_WORDS = {"click", "press", "select", "toggle", "tap", "button", "link", "menu"}
_TYPE_WORDS = {"type", "enter", "input", "write", "fill", "search", "query"}
_SHELL_WORDS = {"run", "execute", "command", "shell", "terminal", "script", "cmd"}


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _app_from_context(ctx: str) -> str:
    c = ctx.lower()
    for keywords, name in _APP_KEYWORDS:
        if any(k in c for k in keywords):
            return name
    segment = re.split(r"[—\-/:|]", ctx)[0].strip()
    return segment


def _commands(text: str) -> set[str]:
    found: set[str] = set()
    for m in _BACKTICK_RE.finditer(text):
        cmd = m.group(1).strip()
        low = cmd.lower()
        if cmd and (low.startswith(_CMD_PREFIXES) or cmd.split()[0].endswith(".sh")):
            found.add(cmd)
    return found


def _files(text: str) -> set[str]:
    found: set[str] = set()
    for m in _FILE_RE.finditer(text):
        tok = m.group(0)
        if tok.lower().startswith("http"):
            continue
        ext = tok.rsplit(".", 1)[-1].lower()
        if ext in _CODE_EXT:
            found.add(tok)
    return found


def _classify(text: str) -> str:
    if any(w in text for w in _NAVIGATE_WORDS):
        return "navigate"
    if any(w in text for w in _CLICK_WORDS):
        return "click"
    if any(w in text for w in _TYPE_WORDS):
        return "type"
    if any(w in text for w in _SHELL_WORDS):
        return "shell"
    return "verify"


def _target(hint: str, observation: str, action_type: str) -> str:
    url = _URL_RE.search(f"{hint} {observation}")
    if url and action_type == "navigate":
        return url.group(0)
    cmd = _BACKTICK_RE.search(hint)
    if cmd and action_type == "shell":
        return cmd.group(1).strip()
    quoted = re.search(r'["\']([^"\']{3,40})["\']', hint)
    if quoted:
        return quoted.group(1)
    return (observation[:60] or hint[:60]).strip()


def _extract_entities(step: dict) -> list[dict]:
    ctx = step.get("window_or_context", "")
    blob = " ".join(
        step.get(k, "") for k in
        ("observation", "user_action", "inferred_intent", "agent_hint")
    )
    entities: list[dict] = []

    app = _app_from_context(ctx)
    if app:
        entities.append({"entity_id": f"app:{_slug(app)}", "type": "application", "name": app})

    for url in dict.fromkeys(_URL_RE.findall(blob)):
        entities.append({"entity_id": f"url:{_slug(url)}", "type": "url", "name": url, "value": url})
    for cmd in sorted(_commands(blob)):
        entities.append({"entity_id": f"cmd:{_slug(cmd)}", "type": "command", "name": cmd, "value": cmd})
    for f in sorted(_files(blob)):
        entities.append({"entity_id": f"file:{_slug(f)}", "type": "file", "name": f, "value": f})

    return entities


def _build_action(step: dict) -> dict:
    hint = step.get("agent_hint", "")
    observation = step.get("observation", "")
    text = f"{hint} {step.get('user_action', '')} {observation}".lower()
    action_type = _classify(text)
    return {
        "type": action_type,
        "target": _target(hint, observation, action_type),
        "value": "",
        "expected_state": f"{step.get('inferred_intent', '')} (context: {step.get('window_or_context', '')})".strip(),
    }


def enrich(steps: list[dict]) -> list[dict]:
    """Populate each step's `action` and `entity_refs` in place; return deduped entities."""
    entities: dict[str, dict] = {}
    for step in steps:
        refs: list[str] = []
        for ent in _extract_entities(step):
            entities.setdefault(ent["entity_id"], ent)
            if ent["entity_id"] not in refs:
                refs.append(ent["entity_id"])
        step["entity_refs"] = refs
        step["action"] = _build_action(step)
    return list(entities.values())
