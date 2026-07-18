"""
metrics.py — tiny in-process request/latency counters.

Enough to answer "how many analyses, how many errors, how slow" without pulling in a
metrics stack. Exposed at GET /metrics. A real deployment would export these to
Prometheus/OTel (docs/ROADMAP.md Phase 4.4).
"""
from __future__ import annotations

import threading


class Metrics:
    def __init__(self):
        self._lock = threading.Lock()
        self._requests: dict[str, int] = {}
        self._errors: dict[str, int] = {}
        self._latency_sum: dict[str, float] = {}

    def record(self, path: str, status_code: int, duration_sec: float) -> None:
        with self._lock:
            self._requests[path] = self._requests.get(path, 0) + 1
            self._latency_sum[path] = self._latency_sum.get(path, 0.0) + duration_sec
            if status_code >= 500:
                self._errors[path] = self._errors.get(path, 0) + 1

    def snapshot(self) -> dict:
        with self._lock:
            paths = sorted(self._requests)
            return {
                "total_requests": sum(self._requests.values()),
                "total_errors": sum(self._errors.values()),
                "by_path": {
                    p: {
                        "requests": self._requests[p],
                        "errors": self._errors.get(p, 0),
                        "avg_latency_ms": round(1000 * self._latency_sum[p] / self._requests[p], 2),
                    }
                    for p in paths
                },
            }
