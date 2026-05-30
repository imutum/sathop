"""Object-storage backends for worker-side upload cache.

Two implementations:
  - LocalStorage: writes to a local directory, also runs an HTTP static server (MVP).
  - MinioStorage: real S3-API via minio-py; presigned URLs for receiver pull.

The Protocol methods are async because MinIO calls can block for seconds over
WAN — running them on the asyncio loop would stall heartbeats and leases.
LocalStorage's implementation is effectively sync (local move) but keeps the
async signature so callers don't need to branch on backend.

Selection is env-driven: `SATHOP_MINIO_ACCESS_KEY` + `SATHOP_MINIO_SECRET_KEY` set → MinIO; else local.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse

from sathop.shared.hashing import sha256_file
from sathop.shared.safe_path import safe_join
from sathop.shared.state_machine import UploadedObject

log = logging.getLogger("sathop.worker.storage")


def render_key(template: str, out: Path, meta: dict) -> str:
    """Render a bundle's `outputs.object_key_template` against one output file.

    Built-in fields `{stem}`, `{ext}`, `{name}` from the path; granule `meta`
    keys are merged on top (str-coerced). Unknown placeholders fall back to
    the bare filename so a typo in the template doesn't crash the upload."""
    fields = {
        "stem": out.stem,
        "ext": out.suffix,
        "name": out.name,
        **{k: str(v) for k, v in meta.items()},
    }
    try:
        return template.format(**fields)
    except KeyError:
        return out.name


class Storage(Protocol):
    needs_static_server: bool

    async def put(self, src: Path, object_key: str) -> UploadedObject: ...
    async def delete(self, object_key: str) -> None: ...


@dataclass
class LocalStorage:
    root: Path
    public_base_url: str
    needs_static_server: bool = True

    def __post_init__(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    async def put(self, src: Path, object_key: str) -> UploadedObject:
        dst = safe_join(self.root, object_key)
        # Off the event loop: hashing a multi-MB output (and a cross-FS move) on the
        # loop stalls every concurrent granule's coroutines and the heartbeat. A
        # same-FS move is a cheap rename; the sha256 read is the real cost.
        sha, size = await asyncio.to_thread(self._store, src, dst)
        return UploadedObject(
            object_key=object_key,
            presigned_url=f"{self.public_base_url}/{object_key}",
            sha256=sha,
            size=size,
        )

    @staticmethod
    def _store(src: Path, dst: Path) -> tuple[str, int]:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), dst)
        return sha256_file(dst), dst.stat().st_size

    async def delete(self, object_key: str) -> None:
        p = safe_join(self.root, object_key)
        p.unlink(missing_ok=True)
        for parent in p.parents:
            if parent == self.root.resolve() or not parent.exists():
                break
            try:
                parent.rmdir()
            except OSError:
                break


class MinioStorage:
    needs_static_server = False

    def __init__(self, public_base_url: str, access_key: str, secret_key: str, bucket: str) -> None:
        from minio import Minio
        from minio.error import S3Error

        p = urlparse(public_base_url)
        if not p.hostname:
            raise ValueError(f"public_base_url has no hostname: {public_base_url!r}")
        default_port = 443 if p.scheme == "https" else 80
        endpoint = f"{p.hostname}:{p.port or default_port}"
        self._bucket = bucket
        self._public = public_base_url.rstrip("/")
        self._client = Minio(
            endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=(p.scheme == "https"),
        )
        if not self._client.bucket_exists(bucket):
            try:
                self._client.make_bucket(bucket)
            except S3Error as e:
                # Concurrent worker startup against the same MinIO can race here.
                # Either error code means another worker already created it; any
                # other S3Error is a real failure (auth, network, etc.).
                if e.code not in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
                    raise

    async def put(self, src: Path, object_key: str) -> UploadedObject:
        # Hash off the loop too — sha256 of a multi-MB output on the event loop
        # stalls heartbeats and other handlers just like the upload itself would.
        sha = await asyncio.to_thread(sha256_file, src)
        size = src.stat().st_size
        # minio-py is sync; off-load to a thread so the asyncio loop keeps
        # serving heartbeats and other granule handlers during multi-second
        # WAN uploads.
        await asyncio.to_thread(self._client.fput_object, self._bucket, object_key, str(src))
        src.unlink(missing_ok=True)
        url = await asyncio.to_thread(
            self._client.presigned_get_object, self._bucket, object_key, expires=timedelta(hours=24)
        )
        return UploadedObject(object_key=object_key, presigned_url=url, sha256=sha, size=size)

    async def delete(self, object_key: str) -> None:
        try:
            await asyncio.to_thread(self._client.remove_object, self._bucket, object_key)
        except Exception as e:
            log.warning("minio remove_object(%s) failed: %s", object_key, e)


def load(
    *,
    use_minio: bool,
    public_base_url: str,
    storage_root: Path,
    minio_access_key: str,
    minio_secret_key: str,
    minio_bucket: str,
) -> Storage:
    if use_minio:
        return MinioStorage(public_base_url, minio_access_key, minio_secret_key, minio_bucket)
    return LocalStorage(root=storage_root, public_base_url=public_base_url)


async def serve_static(
    root: Path,
    port: int,
    *,
    tls_cert: Path | None = None,
    tls_key: Path | None = None,
) -> None:
    """Serve `root` as read-only static files. Used with LocalStorage only.

    When `tls_cert` and `tls_key` are both given, uvicorn serves HTTPS with
    them; otherwise plain HTTP. The caller decides based on whether
    SATHOP_PUBLIC_URL starts with `https://`."""
    import uvicorn
    from fastapi import FastAPI
    from fastapi.staticfiles import StaticFiles

    app = FastAPI()
    root.mkdir(parents=True, exist_ok=True)
    app.mount("/", StaticFiles(directory=str(root)), name="storage")

    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=port,
        log_level="warning",
        ssl_certfile=str(tls_cert) if tls_cert and tls_key else None,
        ssl_keyfile=str(tls_key) if tls_cert and tls_key else None,
    )
    await uvicorn.Server(config).serve()
