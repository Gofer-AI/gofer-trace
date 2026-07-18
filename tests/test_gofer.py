#!/usr/bin/env python3
"""
Offline test suite for Gofer Trace — no GPU, no Docker, no network.

Covers the pure logic across all phases: schema validation + migration, entity
extraction, redaction, the file and graph knowledge bases (graph via an injected fake
Bolt driver), semantic search/similarity, deterministic planning, exporters, and Phase 4
auth + owner scoping + jobs + metrics.

Run:  python tests/test_gofer.py   (or: pytest tests/)
Requires: jsonschema, neo4j (driver only — no server).
"""
import json
import os
import sys
import tempfile
from pathlib import Path

# Import backend modules and isolate storage to a temp dir.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "agent"))
os.environ.setdefault("GOFER_BLOB_ROOT", tempfile.mkdtemp(prefix="gofer-test-"))

from settings import get_settings                       # noqa: E402
from trace_builder import build_trace                    # noqa: E402
from trace_schema import validate_trace, migrate_v0_to_v1, is_v1, TraceValidationError  # noqa: E402
from knowledge_base import create_knowledge_base, FileKnowledgeBase  # noqa: E402
from semantic_index import create_semantic_index         # noqa: E402
from redaction import redact_text, redact_trace          # noqa: E402
from exporters import build_sop_markdown                 # noqa: E402
from planner import build_execution_plan                 # noqa: E402
import auth                                               # noqa: E402
from jobs import JobStore                                 # noqa: E402
from metrics import Metrics                               # noqa: E402


def _frames():
    return [
        {"timestamp_sec": 0.0, "frame_path": "/f/0.jpg", "raw_model_output": json.dumps({
            "window_or_context": "Terminal", "observation": "runs `./deploy.sh staging` on main.py",
            "user_action": "Running a shell command", "inferred_intent": "Deploy to staging",
            "agent_hint": "Run `./deploy.sh staging`"})},
        {"timestamp_sec": 8.0, "frame_path": "/f/1.jpg", "raw_model_output": json.dumps({
            "window_or_context": "Web browser", "observation": "opens https://staging.example.com/login",
            "user_action": "Navigating", "inferred_intent": "Verify deploy",
            "agent_hint": "Open https://staging.example.com/login"})},
    ]


def test_schema_build_and_migrate():
    trace = build_trace("wf1", _frames())
    validate_trace(trace)
    assert is_v1(trace) and len(trace["steps"]) == 2
    v0 = {"workflow_id": "old", "summary": "s", "steps": [
        {"step_id": 1, "timestamp_sec": 0, "window_or_context": "E", "frame_path": "/f/x.jpg"}]}
    assert not is_v1(v0)
    v1 = migrate_v0_to_v1(v0)
    validate_trace(v1)
    assert "frame_uri" in v1["steps"][0] and "frame_path" not in v1["steps"][0]
    try:
        FileKnowledgeBase(get_settings().traces_dir).put_trace({"schema_version": "1.0", "workflow_id": "x"})
        raise AssertionError("invalid trace was accepted")
    except TraceValidationError:
        pass


def test_entity_extraction_and_actions():
    trace = build_trace("wf2", _frames())
    ids = {e["entity_id"] for e in trace["entities"]}
    assert "app:terminal" in ids and "cmd:deploy-sh-staging" in ids and "file:main-py" in ids
    assert any(i.startswith("url:") for i in ids)
    assert trace["steps"][0]["action"]["type"] == "shell"
    assert trace["steps"][1]["action"]["type"] == "navigate"


def test_redaction():
    txt = ("AKIAIOSFODNN7EXAMPLE ghp_abcdefghij0123456789ABCDEFGHIJ "
           "Bearer abcdefghijklmnop0123456789 password=hunter2 https://u:s3cr3t@h/x")
    red = redact_text(txt)
    for leak in ("AKIAIOSFODNN7EXAMPLE", "ghp_abcdefghij", "hunter2", "s3cr3t"):
        assert leak not in red
    t = build_trace("wf3", _frames())
    t["steps"][0]["observation"] = "token=ghp_abcdefghij0123456789ABCDEFGHIJ"
    assert "ghp_abcdefghij" not in json.dumps(redact_trace(t))


def test_file_kb_roundtrip_and_scoping():
    s = get_settings()
    kb = FileKnowledgeBase(Path(s.traces_dir) / "scoped")
    a = build_trace("owned-a", _frames())
    b = build_trace("owned-b", _frames())
    kb.put_trace(a, owner="alice")
    kb.put_trace(b, owner="bob")
    assert [w["workflow_id"] for w in kb.list_workflows(owner="alice")] == ["owned-a"]
    assert kb.get_workflow("owned-b", owner="alice") is None
    assert kb.get_workflow("owned-b", owner="bob")["workflow_id"] == "owned-b"
    # No owner filter → everything visible (local single-user behavior).
    assert len(kb.list_workflows()) == 2


def test_semantic_search_and_similarity():
    s = get_settings()
    kb = create_knowledge_base(s)
    sem = create_semantic_index(s)
    deploy = build_trace("s-deploy", _frames())
    passwd = build_trace("s-passwd", [{"timestamp_sec": 0.0, "frame_path": "/f/c.jpg",
        "raw_model_output": json.dumps({"window_or_context": "Web browser",
        "observation": "reset password in account settings", "user_action": "Clicking reset password",
        "inferred_intent": "Reset the account password", "agent_hint": "Click reset password"})}])
    for t in (deploy, passwd):
        sem.index_trace(t)
        kb.put_trace(t)
    assert deploy["steps"][0]["embedding_ref"] == "s-deploy#1"
    r = sem.search_workflows("deploy the app to staging")
    assert r and r[0]["workflow_id"] == "s-deploy"
    r2 = sem.search_workflows("change my account password")
    assert r2 and r2[0]["workflow_id"] == "s-passwd"
    # deterministic across a fresh index instance
    assert create_semantic_index(s).search_workflows("deploy to staging")[0]["workflow_id"] == "s-deploy"


def test_graph_kb_with_fake_driver():
    from graph_knowledge_base import GraphKnowledgeBase

    class FakeResult(list):
        pass

    class FakeTx:
        def __init__(self, store):
            self.store = store
        def run(self, q, **p):
            if "w.raw_json = $raw" in q:
                self.store[p["id"]] = p["raw"]
            return FakeResult()

    class FakeSession:
        def __init__(self, store):
            self.store = store
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def run(self, q, **p):
            if "RETURN w.raw_json AS j" in q:
                if "id" in p:
                    v = self.store.get(p["id"])
                    return FakeResult([{"j": v}] if v else [])
                return FakeResult([{"j": v} for v in self.store.values()])
            return FakeResult()
        def execute_write(self, fn, *a, **k):
            return fn(FakeTx(self.store), *a, **k)

    class FakeDriver:
        def __init__(self):
            self.store = {}
        def session(self, **k):
            return FakeSession(self.store)
        def close(self):
            pass

    gkb = GraphKnowledgeBase("bolt://fake", driver=FakeDriver())
    trace = build_trace("g1", _frames())
    gkb.put_trace(trace, owner="alice")
    got = gkb.get_workflow("g1", owner="alice")
    assert got and got["workflow_id"] == "g1" and got["owner"] == "alice"
    assert gkb.get_workflow("g1", owner="bob") is None
    assert gkb.list_workflows(owner="alice")[0]["workflow_id"] == "g1"


def test_planner_uses_structured_action():
    trace = build_trace("p1", _frames())
    plan = build_execution_plan(trace)
    assert plan[0].action_type == "shell" and plan[0].target == "./deploy.sh staging"
    assert plan[1].action_type == "navigate" and "staging.example.com" in plan[1].target
    legacy = {"steps": [{"step_id": 1, "timestamp_sec": 0, "window_or_context": "Terminal",
                         "user_action": "run a command", "observation": "", "inferred_intent": "",
                         "agent_hint": "run the build"}]}
    assert build_execution_plan(legacy)[0].action_type == "shell"


def test_exporter():
    sop = build_sop_markdown(build_trace("e1", _frames()))
    assert "## Goal" in sop and "## Steps" in sop and "./deploy.sh staging" in sop


def test_auth_and_scoping_helpers():
    class S:
        def __init__(self, require_auth):
            self.require_auth = require_auth
            self.api_keys = {"sk_alice": "alice", "sk_bob": "sk_bob"}
    # local: no auth → principal 'local', no owner scoping
    local = S(require_auth=False)
    assert auth.resolve_principal(local) == "local"
    assert auth.owner_for(local, "local") is None
    # cloud: require auth
    cloud = S(require_auth=True)
    assert auth.resolve_principal(cloud, x_api_key="sk_alice") == "alice"
    assert auth.resolve_principal(cloud, authorization="Bearer sk_bob") == "sk_bob"
    assert auth.owner_for(cloud, "alice") == "alice"
    try:
        auth.resolve_principal(cloud, x_api_key="nope")
        raise AssertionError("bad key accepted")
    except Exception as e:
        assert getattr(e, "status_code", None) == 401

    # Settings.api_keys parses "key:principal" pairs correctly.
    real = get_settings()
    parsed = type(real)(**{**real.__dict__, "api_keys_raw": "k1:alice, k2 , k3:bob"}).api_keys
    assert parsed == {"k1": "alice", "k2": "k2", "k3": "bob"}


def test_jobs_and_metrics():
    js = JobStore()
    jid = js.create("v1")
    assert js.get(jid)["status"] == "queued"
    js.update(jid, "done", result={"ok": True})
    assert js.get(jid)["status"] == "done" and js.get(jid)["result"] == {"ok": True}
    m = Metrics()
    m.record("/analyze", 200, 0.1)
    m.record("/analyze", 500, 0.2)
    snap = m.snapshot()
    assert snap["total_requests"] == 2 and snap["total_errors"] == 1
    assert snap["by_path"]["/analyze"]["requests"] == 2


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception as e:
            failed += 1
            print(f"FAIL {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
