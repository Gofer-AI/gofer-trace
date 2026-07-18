"""
blob_store.py — where large objects (videos, frames, exported artifacts) live.

`LocalBlobStore` writes under the filesystem blob root (current behavior). `S3BlobStore`
targets S3 / Cloudflare R2 for the cloud profile and returns public or presigned URLs.
Both implement the same interface, chosen by `GOFER_BLOB_STORE`.

Videos/frames are still written to local files today because OpenCV needs a path; artifacts
already flow through this interface. Migrating video/frame storage is the remaining step
(see docs/ROADMAP.md Phase 4.2).
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class BlobStore(Protocol):
    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str: ...
    def url(self, key: str) -> str: ...


class LocalBlobStore:
    """Filesystem-backed store. Objects are served by the /media static mounts."""

    def __init__(self, root: Path | str, url_prefix: str = "/media"):
        self.root = Path(root)
        self.url_prefix = url_prefix.rstrip("/")

    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return self.url(key)

    def url(self, key: str) -> str:
        return f"{self.url_prefix}/{key.lstrip('/')}"


class S3BlobStore:
    """S3 / R2-backed store. boto3 is imported lazily."""

    def __init__(self, bucket: str, endpoint_url: str = "", region: str = "",
                 public_base: str = "", presign_ttl: int = 3600):
        import boto3

        self.bucket = bucket
        self.public_base = public_base.rstrip("/")
        self.presign_ttl = presign_ttl
        self._s3 = boto3.client(
            "s3",
            endpoint_url=endpoint_url or None,
            region_name=region or None,
        )

    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        self._s3.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)
        return self.url(key)

    def url(self, key: str) -> str:
        if self.public_base:
            return f"{self.public_base}/{key.lstrip('/')}"
        return self._s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=self.presign_ttl,
        )


def create_blob_store(settings) -> BlobStore:
    if getattr(settings, "blob_store", "local") == "s3":
        import os
        return S3BlobStore(
            bucket=os.getenv("GOFER_S3_BUCKET", ""),
            endpoint_url=os.getenv("GOFER_S3_ENDPOINT", ""),
            region=os.getenv("GOFER_S3_REGION", ""),
            public_base=os.getenv("GOFER_S3_PUBLIC_BASE", ""),
        )
    return LocalBlobStore(settings.blob_root)
