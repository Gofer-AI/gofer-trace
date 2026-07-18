#!/usr/bin/env python3
"""
migrate_traces.py — lift legacy (v0) traces in data/traces/ to schema v1.0.

Idempotent: v1.0 files are skipped. No VLM re-run — new fields default to empty.
Writes in place unless --dry-run.

Usage:
    python scripts/migrate_traces.py [--traces-dir DIR] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from trace_schema import ensure_v1, is_v1, validate_trace  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate v0 traces to schema v1.0.")
    parser.add_argument("--traces-dir", default=None, help="Defaults to the configured blob root.")
    parser.add_argument("--dry-run", action="store_true", help="Report only; do not write.")
    args = parser.parse_args()

    if args.traces_dir:
        traces_dir = Path(args.traces_dir)
    else:
        from settings import get_settings
        traces_dir = get_settings().traces_dir

    if not traces_dir.exists():
        print(f"No traces directory at {traces_dir}; nothing to do.")
        return 0

    migrated = skipped = failed = 0
    for path in sorted(traces_dir.glob("*.json")):
        try:
            trace = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            print(f"  SKIP (unreadable) {path.name}: {exc}")
            failed += 1
            continue

        if is_v1(trace):
            skipped += 1
            continue

        upgraded = ensure_v1(trace)
        try:
            validate_trace(upgraded)
        except Exception as exc:
            print(f"  FAIL (invalid after migration) {path.name}: {exc}")
            failed += 1
            continue

        if args.dry_run:
            print(f"  WOULD migrate {path.name}")
        else:
            path.write_text(json.dumps(upgraded, indent=2))
            print(f"  migrated {path.name}")
        migrated += 1

    verb = "would migrate" if args.dry_run else "migrated"
    print(f"\nDone: {verb} {migrated}, already-v1 {skipped}, failed {failed}.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
