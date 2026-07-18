"""
settings.py — single source of truth for Gofer Trace configuration.

Profile-driven (GOFER_PROFILE=local|cloud). Every value has a safe local default and
can be overridden by an environment variable, so the same code runs offline on a laptop
or against cloud infrastructure without edits. This module replaces the backend URL that
used to be hardcoded across the codebase.

See docs/ARCHITECTURE.md §4 for the local vs cloud mapping.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "schema" / "trace.schema.json"

# Safe defaults for the local profile — no external services, no secrets.
_DEFAULT_API_BASE = "http://localhost:8001"
_DEFAULT_GRAPH_URL = "bolt://localhost:7687"
_DEFAULT_VLM = "Qwen/Qwen2.5-VL-7B-Instruct"
_DEFAULT_BLOB_ROOT = str(REPO_ROOT / "data")


def _env(*names: str, default: str = "") -> str:
    """Return the first non-empty value among the given env var names, else default."""
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return default


@dataclass(frozen=True)
class Settings:
    profile: str          # "local" | "cloud"
    api_base: str         # backend HTTP base (used by MCP server + Space)
    graph_url: str        # Bolt URL: Memgraph (local) or Neo4j/AuraDB (cloud)
    graph_user: str
    graph_password: str
    vlm: str              # understanding model id / label
    blob_root: str        # filesystem root (local) or object-store prefix (cloud)

    @property
    def is_cloud(self) -> bool:
        return self.profile == "cloud"

    @property
    def videos_dir(self) -> Path:
        return Path(self.blob_root) / "videos"

    @property
    def frames_dir(self) -> Path:
        return Path(self.blob_root) / "frames"

    @property
    def traces_dir(self) -> Path:
        return Path(self.blob_root) / "traces"

    def ensure_dirs(self) -> None:
        for d in (self.videos_dir, self.frames_dir, self.traces_dir):
            d.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    profile = _env("GOFER_PROFILE", default="local").lower()
    return Settings(
        profile=profile,
        # API_BASE kept as an accepted name for backward compatibility with existing configs.
        api_base=_env("GOFER_API_BASE", "API_BASE", default=_DEFAULT_API_BASE).rstrip("/"),
        graph_url=_env("GOFER_GRAPH_URL", default=_DEFAULT_GRAPH_URL),
        graph_user=_env("GOFER_GRAPH_USER", default=""),
        graph_password=_env("GOFER_GRAPH_PASSWORD", default=""),
        vlm=_env("GOFER_VLM", default=_DEFAULT_VLM),
        blob_root=_env("GOFER_BLOB_ROOT", default=_DEFAULT_BLOB_ROOT),
    )
