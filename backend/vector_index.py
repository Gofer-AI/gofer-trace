"""
vector_index.py — a minimal vector store behind a swappable interface.

`FileVectorIndex` keeps L2-normalized vectors in a single JSON file and does brute-force
cosine (= dot product on normalized vectors). Zero-dependency and fine for the local
profile's scale. The interface mirrors what a real backend (sqlite-vec / FAISS locally,
the graph engine's native vector index in cloud) exposes, so it swaps in later without
touching callers.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Protocol, runtime_checkable


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


@runtime_checkable
class VectorIndex(Protocol):
    def upsert(self, id: str, vector: list[float], metadata: dict) -> None: ...
    def get(self, id: str) -> list[float] | None: ...
    def delete(self, id: str) -> None: ...
    def delete_prefix(self, prefix: str) -> None: ...
    def query(self, vector: list[float], k: int,
              where: Callable[[dict], bool] | None = None) -> list[tuple[str, float, dict]]: ...
    def save(self) -> None: ...


class FileVectorIndex:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data: dict[str, dict] = {}
        if self.path.exists():
            try:
                self._data = json.loads(self.path.read_text())
            except (json.JSONDecodeError, OSError):
                self._data = {}

    def upsert(self, id: str, vector: list[float], metadata: dict) -> None:
        self._data[id] = {"vector": vector, "meta": metadata}

    def get(self, id: str) -> list[float] | None:
        entry = self._data.get(id)
        return entry["vector"] if entry else None

    def delete(self, id: str) -> None:
        self._data.pop(id, None)

    def delete_prefix(self, prefix: str) -> None:
        for key in [k for k in self._data if k.startswith(prefix)]:
            del self._data[key]

    def query(self, vector, k=5, where=None):
        scored: list[tuple[str, float, dict]] = []
        for id, entry in self._data.items():
            meta = entry.get("meta", {})
            if where is not None and not where(meta):
                continue
            scored.append((id, _dot(vector, entry["vector"]), meta))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:k]

    def save(self) -> None:
        self.path.write_text(json.dumps(self._data))
