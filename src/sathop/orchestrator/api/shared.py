"""Shared-file store: upload + list + meta + download + delete.

Bundles declare which shared files they need in `manifest.shared_files: [name]`;
workers lazily pull them on first use and cache locally keyed by sha256.

Files are stored by user-facing name at `$SATHOP_SHARED/<name>` — a single
canonical "what's behind this name right now" model. Re-uploading a name
overwrites the bytes and updates the sha256 in the DB; workers see the new
sha256 via `/meta` and refetch on next lease."""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import require_token, require_token_or_query
from ..bundle_schema import parse_shared_files
from ..config import settings
from ..db import Bundle, SharedFile, session, utcnow
from ..pubsub import log_event as log
from ..pubsub import publish

router = APIRouter(prefix="/shared", tags=["shared"])

# Filesystem-safe names: no separators, no leading dot, cap below common FS limits.
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$")


def _validate_name(name: str) -> None:
    if not _NAME_RE.match(name):
        raise HTTPException(
            400,
            "invalid name: must match [A-Za-z0-9][A-Za-z0-9._-]{0,254} (no path separators, no leading dot)",
        )


class SharedFileInfo(BaseModel):
    name: str
    sha256: str
    size: int
    description: str | None
    uploaded_at: datetime


class SharedFileMeta(BaseModel):
    """Byte-less check used by workers to compare against local cache."""

    name: str
    sha256: str
    size: int


def _info(f: SharedFile) -> SharedFileInfo:
    return SharedFileInfo(
        name=f.name,
        sha256=f.sha256,
        size=f.size,
        description=f.description,
        uploaded_at=f.uploaded_at,
    )


@router.get(
    "",
    response_model=list[SharedFileInfo],
    dependencies=[Depends(require_token)],
)
async def list_shared(s: AsyncSession = Depends(session)) -> list[SharedFileInfo]:
    rows = (await s.execute(select(SharedFile).order_by(SharedFile.name))).scalars().all()
    return [_info(f) for f in rows]


@router.put(
    "/{name}",
    response_model=SharedFileInfo,
    dependencies=[Depends(require_token)],
)
async def upload(
    name: str,
    file: UploadFile,
    description: str | None = None,
    s: AsyncSession = Depends(session),
) -> SharedFileInfo:
    _validate_name(name)

    storage: Path = settings.shared_storage
    storage.mkdir(parents=True, exist_ok=True)

    # Stream to a sibling tmp file so the final rename stays same-filesystem atomic.
    sha = hashlib.sha256()
    size = 0
    tmp = tempfile.NamedTemporaryFile(dir=storage, prefix=f".{name}.", suffix=".part", delete=False)
    tmp_path = Path(tmp.name)
    try:
        with tmp:
            while True:
                chunk = await file.read(1 << 20)
                if not chunk:
                    break
                tmp.write(chunk)
                sha.update(chunk)
                size += len(chunk)
        if size == 0:
            raise HTTPException(400, "empty upload")

        digest = sha.hexdigest()
        dest = storage / name
        tmp_path.replace(dest)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise

    existing = await s.get(SharedFile, name)
    if existing is None:
        row = SharedFile(
            name=name,
            sha256=digest,
            size=size,
            description=description,
            uploaded_at=utcnow(),
        )
        s.add(row)
        verb = "uploaded"
    else:
        existing.sha256 = digest
        existing.size = size
        if description is not None:
            existing.description = description
        existing.uploaded_at = utcnow()
        row = existing
        verb = "replaced"

    await log(s, "shared", f"{verb} {name} ({size} bytes, sha={digest[:12]})")
    await s.commit()
    publish({"scope": "shared"})
    return _info(row)


@router.get(
    "/{name}",
    response_model=SharedFileMeta,
    dependencies=[Depends(require_token)],
)
async def meta(name: str, s: AsyncSession = Depends(session)) -> SharedFileMeta:
    _validate_name(name)
    f = await s.get(SharedFile, name)
    if f is None:
        raise HTTPException(404, f"shared file {name!r} not found")
    return SharedFileMeta(name=f.name, sha256=f.sha256, size=f.size)


@router.get(
    "/{name}/download",
    dependencies=[Depends(require_token_or_query)],
)
async def download(name: str, s: AsyncSession = Depends(session)) -> FileResponse:
    """Accepts `?token=` for clients that can't set the Authorization header."""
    _validate_name(name)
    f = await s.get(SharedFile, name)
    if f is None:
        raise HTTPException(404, f"shared file {name!r} not found")
    blob = settings.shared_storage / f.name
    if not blob.is_file():
        raise HTTPException(500, "shared-file bytes missing on orchestrator disk")
    return FileResponse(
        blob,
        media_type="application/octet-stream",
        filename=f.name,
        headers={"X-SHA256": f.sha256},
    )


@router.delete("/{name}", dependencies=[Depends(require_token)])
async def delete(name: str, s: AsyncSession = Depends(session)) -> dict:
    _validate_name(name)
    f = await s.get(SharedFile, name)
    if f is None:
        raise HTTPException(404, f"shared file {name!r} not found")

    # Refuse if any registered bundle still references this name — fail fast
    # rather than let a lease crash on a silently-missing shared file.
    bundles = (await s.execute(select(Bundle))).scalars().all()
    referrers = [
        f"{b.name}@{b.version}" for b in bundles if name in parse_shared_files(json.loads(b.manifest_json))
    ]
    if referrers:
        raise HTTPException(
            409,
            f"shared file {name!r} is referenced by {len(referrers)} bundle(s): "
            f"{referrers[:5]}{'...' if len(referrers) > 5 else ''}",
        )

    blob = settings.shared_storage / f.name
    await s.delete(f)
    await log(s, "shared", f"deleted {name}")
    await s.commit()
    blob.unlink(missing_ok=True)
    publish({"scope": "shared"})
    return {"ok": True}
