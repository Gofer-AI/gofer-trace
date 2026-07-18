# Using Gofer Trace from your agent

Gofer Trace exposes workflow memory as an **MCP server** (`agent/mcp_server.py`). Any
MCP-compatible agent — Claude Code, Cursor, Codex, Hermes, or your own — can call the same
tools. The server is a thin client of the backend HTTP API, so point it at your backend
with `API_BASE` (local: `http://localhost:8001`; cloud: your deployed URL).

Ready-to-copy configs live in [`examples/mcp/`](../examples/mcp/).

## Tools exposed

| Tool | What it does |
|---|---|
| `list_workflows` | List every analyzed workflow (id, title/goal, step count) |
| `search_workflows(query)` | **Semantic** search — find a workflow by intent, no id needed |
| `load_workflow(id)` | Full trace as a markdown context block |
| `get_step_context(id, step)` | A step's entities, prev/next, and similar steps elsewhere |
| `find_similar_steps(id, step)` | Steps like this one across all recordings |
| `ask_workflow(id, q)` | Natural-language Q&A over one workflow |
| `export_agent_memory(id)` | Persist a deterministic SOP + agent-memory JSON as artifacts |
| `review_plan` / `approve_plan` | Human-in-the-loop execution gate |
| `get_execution_plan(id)` | Deterministic browser plan (from the schema's `action{}`) |
| `verify_step` / `mark_step_complete` | Qwen visual verification + progress tracking |

## Transports

- **stdio (default)** — the agent launches the server as a subprocess. This is how Claude
  Code, Cursor, and Codex work. Configs below.
- **HTTP** — run `GOFER_MCP_TRANSPORT=http python agent/mcp_server.py` and point an
  HTTP-capable client at the server URL. Use this for the cloud profile or when the agent
  runs on a different machine than the backend. See
  [`examples/mcp/http-remote.json`](../examples/mcp/http-remote.json).

## Per-agent setup

### Claude Code
Copy [`examples/mcp/claude-code.mcp.json`](../examples/mcp/claude-code.mcp.json) to
`.mcp.json` in your project (already present in this repo), or run:
```bash
claude mcp add gofer-trace -- python agent/mcp_server.py
```

### Cursor
Copy [`examples/mcp/cursor.mcp.json`](../examples/mcp/cursor.mcp.json) to `.cursor/mcp.json`
(already present in this repo), then enable the server in Cursor Settings → MCP.

### Codex (OpenAI Codex CLI)
Add the block from [`examples/mcp/codex-config.toml`](../examples/mcp/codex-config.toml) to
`~/.codex/config.toml`. Codex launches MCP servers over stdio.

### Hermes and other MCP clients
Any client that speaks MCP can use the stdio launch command
`python agent/mcp_server.py` (with `API_BASE` in the environment), or the HTTP transport
above. Map those onto your client's MCP configuration format.

## Pointing at local vs cloud

The only thing that changes between profiles is `API_BASE`:

| | `API_BASE` |
|---|---|
| Local backend | `http://localhost:8001` |
| Cloud backend | `https://your-deployment.example.com` |

Set it in the server's `env` block (stdio) or the backend's environment (HTTP).
