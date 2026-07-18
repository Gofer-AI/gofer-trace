"""
embeddings.py — text → vector, behind a swappable interface.

Default `HashingEmbedder` is offline and zero-dependency: a signed hashing (bag-of-words)
vectorizer that is deterministic *across processes* (uses hashlib, never Python's
per-process-salted hash()), so persisted vectors stay valid between runs. It captures
token overlap — a solid baseline that makes the vector-search plumbing real without any
model download.

Set `GOFER_EMBEDDINGS=sentence-transformers` for true semantic vectors (synonyms, phrasing)
via a local model; the interface is identical, so nothing downstream changes.
"""
from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol, runtime_checkable

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall((text or "").lower())


def _l2_normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0.0:
        return vec
    return [v / norm for v in vec]


@runtime_checkable
class EmbeddingModel(Protocol):
    dim: int
    name: str

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class HashingEmbedder:
    """Deterministic, offline signed-hashing bag-of-words embedder (L2-normalized)."""

    def __init__(self, dim: int = 256):
        self.dim = dim
        self.name = f"hashing-{dim}"

    @staticmethod
    def _hash(token: str) -> int:
        return int.from_bytes(hashlib.md5(token.encode("utf-8")).digest()[:8], "big")

    def _one(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for tok in _tokenize(text):
            h = self._hash(tok)
            idx = h % self.dim
            sign = 1.0 if (h >> 33) & 1 else -1.0  # signed hashing lowers collision bias
            vec[idx] += sign
        return _l2_normalize(vec)

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._one(t) for t in texts]


class SentenceTransformerEmbedder:
    """Optional true-semantic embedder. Lazy-imports sentence-transformers."""

    def __init__(self, model_id: str = "all-MiniLM-L6-v2"):
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(model_id)
        self.dim = self._model.get_sentence_embedding_dimension()
        self.name = f"st:{model_id}"

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = self._model.encode(texts, normalize_embeddings=True)
        return [list(map(float, v)) for v in vectors]


def get_embedding_model(settings) -> EmbeddingModel:
    if getattr(settings, "embeddings", "hashing") == "sentence-transformers":
        return SentenceTransformerEmbedder(settings.embedding_model)
    return HashingEmbedder(dim=getattr(settings, "embedding_dim", 256))
