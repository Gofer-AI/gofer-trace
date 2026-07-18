#!/usr/bin/env python3
"""
smoke_test.py — exercise a RUNNING Gofer Trace backend end-to-end over HTTP.

Unlike tests/test_gofer.py (pure offline logic), this hits a live server: health, upload +
analyze (if you pass a video), the knowledge-base and retrieval endpoints, export, and
metrics. Use it after `docker compose up` or `./start_backend.sh` to confirm the deployment
actually works. See docs/SMOKE_TEST.md for the full host checklist.

    python scripts/smoke_test.py --api-base http://localhost:8001 [--video demo.mp4] [--api-key KEY]
"""
from __future__ import annotations

import argparse
import sys

import requests

PASS, FAIL = "PASS", "FAIL"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Smoke-test a running Gofer Trace backend.")
    ap.add_argument("--api-base", default="http://localhost:8001")
    ap.add_argument("--video", default=None, help="Optional MP4 to upload + analyze.")
    ap.add_argument("--api-key", default=None, help="API key (cloud profile).")
    args = ap.parse_args(argv)

    base = args.api_base.rstrip("/")
    headers = {"X-API-Key": args.api_key} if args.api_key else {}
    results: list[tuple[str, bool, str]] = []

    def check(name, ok, detail=""):
        results.append((name, ok, detail))
        print(f"{PASS if ok else FAIL} {name}" + (f" — {detail}" if detail else ""))

    # 1) health
    try:
        r = requests.get(f"{base}/", timeout=15)
        check("health", r.status_code == 200, f"profile={r.json().get('profile')}")
    except Exception as e:
        check("health", False, str(e))
        print("\nBackend unreachable — is it running?")
        return 1

    # 2) upload + analyze (only if a video is provided)
    video_id = None
    if args.video:
        try:
            with open(args.video, "rb") as f:
                up = requests.post(f"{base}/upload", files={"file": (args.video, f, "video/mp4")},
                                   headers=headers, timeout=300)
            video_id = up.json().get("video_id")
            check("upload", up.status_code == 200 and bool(video_id), f"video_id={video_id}")
            an = requests.post(f"{base}/analyze/{video_id}", headers=headers, timeout=1800)
            steps = len(an.json().get("trace", {}).get("steps", []))
            check("analyze", an.status_code == 200 and steps > 0, f"{steps} steps")
        except Exception as e:
            check("upload+analyze", False, str(e))

    # 3) list workflows
    try:
        r = requests.get(f"{base}/workflows", headers=headers, timeout=30)
        workflows = r.json().get("workflows", [])
        check("list_workflows", r.status_code == 200, f"{len(workflows)} workflow(s)")
        if workflows and not video_id:
            video_id = workflows[0]["workflow_id"]
    except Exception as e:
        check("list_workflows", False, str(e))

    # 4) semantic search
    try:
        r = requests.get(f"{base}/search", params={"q": "workflow"}, headers=headers, timeout=30)
        check("search", r.status_code == 200, f"{len(r.json().get('results', []))} result(s)")
    except Exception as e:
        check("search", False, str(e))

    # 5) per-workflow endpoints (only if we have one)
    if video_id:
        for name, method, path in [
            ("trace", "get", f"/trace/{video_id}"),
            ("plan", "get", f"/plan/{video_id}"),
            ("export", "post", f"/export/{video_id}"),
            ("step_context", "get", f"/step-context/{video_id}/1"),
            ("similar_steps", "get", f"/similar-steps/{video_id}/1"),
        ]:
            try:
                r = requests.request(method, f"{base}{path}", headers=headers, timeout=120)
                body = r.json()
                ok = r.status_code == 200 and "error" not in body
                check(name, ok, "" if ok else str(body.get("error", r.status_code)))
            except Exception as e:
                check(name, False, str(e))
    else:
        print("… skipped per-workflow checks (no workflow available; pass --video to create one)")

    # 6) metrics
    try:
        r = requests.get(f"{base}/metrics", headers=headers, timeout=15)
        check("metrics", r.status_code == 200, f"{r.json().get('total_requests')} requests seen")
    except Exception as e:
        check("metrics", False, str(e))

    failed = [n for n, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
