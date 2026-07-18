# Gofer Trace Schema

`trace.schema.json` is the **canonical contract** for a captured workflow. It is the
one artifact every layer agrees on: the understanding layer writes it, the knowledge
base ingests it, and every MCP-connected agent (Claude Code, Cursor, Codex, Hermes)
reads it. Get this right and the local/cloud split and the graph layer both become
mechanical.

- **`trace.schema.json`** — JSON Schema (draft 2020-12). Validate every trace against it.
- **`example.trace.json`** — a minimal valid `1.0` trace.

## Why a formal schema (vs. today's flat JSON)

Today `trace_builder.build_trace` emits an ad-hoc dict: `{workflow_id, summary, steps[]}`
with loosely-typed step fields (`backend/trace_builder.py`). That was fine for the
hackathon, but it can't support the roadmap because it has:

- no `schema_version` → no safe evolution across agents;
- no `entities` → nothing to dedupe into shared graph nodes, so workflows that touch the
  same tool/file can't be linked;
- no structured `action` → `planner.py` has to keyword-guess execution steps every time;
- no provenance (`source`, `model`) → can't tell a real-VLM trace from a stub trace;
- no `artifacts` → SOP/markdown exports float around untracked.

## Migration from the current format

The `1.0` schema is a **superset** of today's step fields, so migration is additive:

| Today (`trace_builder.py`) | `1.0` schema |
|---|---|
| `workflow_id` | `workflow_id` (unchanged) |
| `summary` | `summary` (+ new `goal`, `title`) |
| `steps[].step_id` | `steps[].step_id` |
| `steps[].timestamp_sec` | `steps[].timestamp_sec` |
| `steps[].window_or_context` | `steps[].window_or_context` |
| `steps[].observation / user_action / inferred_intent / agent_hint` | same keys |
| `steps[].frame_path` | `steps[].frame_uri` (rename) |
| `steps[].raw_model_output` | `steps[].raw_model_output` |
| _(none)_ | **new:** `schema_version`, `created_at`, `source`, `model`, `entities`, `steps[].action`, `steps[].entity_refs`, `artifacts` |

A one-time `migrate_v0_to_v1(old_trace)` helper can lift existing `data/traces/*.json`
files without re-running the VLM (new fields default to empty). Entity extraction and
structured `action` get backfilled on the next analysis pass.

## Validating

```bash
pip install jsonschema
python -c "import json,jsonschema; \
  jsonschema.validate(json.load(open('schema/example.trace.json')), \
                      json.load(open('schema/trace.schema.json'))); \
  print('valid')"
```

Wire this into `trace_builder.save_trace` so an invalid trace can never be persisted.
