"""Object-storage backends for worker-side upload cache.

Two implementations:
  - LocalStorage: writes to a local directory, also runs an HTTP static server (MVP).
  - MinioStorage: real S3-API via minio-py; presigned URLs for receiver pull.

Selection is env-driven: `SATHOP_MINIO_ACCESS_KEY` + `SATHOP_MINIO_SECRET_KEY` set → MinIO; else local.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse

from sathop.shared.hashing import sha256_file
from sathop.shared.protocol import UploadedObject
from sathop.shared.safe_path import safe_join


class Storage(Protocol):
    needs_static_server: bool

    def put(self, src: Path, object_key: str) -> UploadedObject: ...
    def delete(self, object_key: str) -> None: ...


@dataclass
class LocalStorage:
    root: Path
    public_base_url: str
    needs_static_server: bool = True

    def __post_init__(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, src: Path, object_key: str) -> UploadedObject:
        dst = safe_join(self.root, object_key)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), dst)
        return UploadedObject(
            object_key=object_key,
            presigned_url=f"{self.public_base_url}/{object_key}",
            sha256=sha256_file(dst),
            size=dst.stat().st_size,
        )

    def delete(self, object_key: str) -> None:
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
            self._client.make_bucket(bucket)

    def put(self, src: Path, object_key: str) -> UploadedObject:
        sha = sha256_file(src)
        size = src.stat().st_size
        self._client.fput_object(self._bucket, object_key, str(src))
        src.unlink(missing_ok=True)
        url = self._client.presigned_get_object(self._bucket, object_key, expires=timedelta(hours=24))
        return UploadedObject(object_key=object_key, presigned_url=url, sha256=sha, size=size)

    def delete(self, object_key: str) -> None:
        try:
            self._client.remove_object(self._bucket, object_key)
        except Exception:
            pass


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

    kwargs: dict[str, object] = {
        "host": "0.0.0.0",
        "port": port,
        "log_level": "warning",
    }
    if tls_cert and tls_key:
        kwargs["ssl_certfile"] = str(tls_cert)
        kwargs["ssl_keyfile"] = str(tls_key)
    config = uvicorn.Config(app, **kwargs)
    await uvicorn.Server(config).serve()
