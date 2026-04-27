"""Central bundle registry: upload, list, detail, download, delete.

Bundle zips are content-addressed on disk. Multiple (name, version) rows can
point at the same sha256 blob if identical — deletion only unlinks the blob
when no other row references it."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile

import yaml
from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sathop.shared.protocol import BundleDetail, BundleSummary

from ..config import require_token
from ..bundle_schema import InputsSchema, parse_shared_files
from ..config import settings
from ..db import Batch, Bundle, SharedFile, session, utcnow
from ..pubsub import log_event as log
from ..pubsub import publish

router = APIRouter(prefix="/bundles", tags=["bundles"], dependencies=[Depends(require_token)])


REQUIRED_MANIFEST_KEYS = {"name", "version", "execution", "outputs"}


def _parse_zip(data: bytes) -> dict:
    """Return the parsed manifest. Raises HTTPException on any shape problem."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise HTTPException(400, "not a valid zip archive")

    try:
        names = zf.namelist()
        # Accept both flat (manifest.yaml at root) and single-wrapper layouts.
        manifest_path = next(
            (n for n in names if n.rstrip("/").endswith("manifest.yaml")),
            None,
        )
        if manifest_path is None or manifest_path.count("/") > 1:
            raise HTTPException(422, "zip must contain manifest.yaml at root or one level deep")
        try:
            raw = zf.read(manifest_path)
        except KeyError:
            raise HTTPException(422, "cannot read manifest.yaml from zip")
    finally:
        zf.close()

    try:
        manifest = yaml.safe_load(raw)
    except yaml.YAMLError as e:
        raise HTTPException(422, f"manifest.yaml is not valid YAML: {e}")
    if not isinstance(manifest, dict):
        raise HTTPException(422, "manifest.yaml must be a mapping at the top level")
    missing = REQUIRED_MANIFEST_KEYS - manifest.keys()
    if missing:
        raise HTTPException(422, f"manifest missing required keys: {sorted(missing)}")
    if "entrypoint" not in manifest.get("execution", {}):
        raise HTTPException(422, "manifest.execution.entrypoint is required")
    if "inputs" not in manifest:
        raise HTTPException(422, "manifest.inputs is required")
    try:
        InputsSchema.parse(manifest)
    except ValueError as e:
        raise HTTPException(422, f"manifest.inputs invalid: {e}")
    try:
        parse_shared_files(manifest)
    except ValueError as e:
        raise HTTPException(422, f"manifest.shared_files invalid: {e}")
    return manifest


def _detail(b: Bundle) -> BundleDetail:
    return BundleDetail(
        name=b.name,
        version=b.version,
        sha256=b.sha256,
        size=b.size,
        description=b.description,
        uploaded_at=b.uploaded_at,
        manifest=json.loads(b.manifest_json),
    )


def _summary(b: Bundle) -> BundleSummary:
    return BundleSummary(
        name=b.name,
        version=b.version,
        sha256=b.sha256,
        size=b.size,
        description=b.description,
        uploaded_at=b.uploaded_at,
    )


@router.post("", response_model=BundleDetail)
async def upload(
    file: UploadFile,
    description: str | None = None,
    s: AsyncSession = Depends(session),
) -> BundleDetail:
    data = await file.read()
    if not data:
        raise HTTPException(400, "empty upload")
    manifest = _parse_zip(data)
    name = str(manifest["name"])
    version = str(manifest["version"])

    if await s.get(Bundle, (name, version)) is not None:
        raise HTTPException(409, f"bundle {name}@{version} already registered; bump version")

    # Every shared_files name must exist in the registry at upload time —
    # fail fast so operators see broken references before any batch runs.
    shared_names = parse_shared_files(manifest)
    missing = [n for n in shared_names if await s.get(SharedFile, n) is None]
    if missing:
        raise HTTPException(
            422,
            f"manifest.shared_files references unknown name(s): {missing}. Upload them to /api/shared first.",
        )

    sha = hashlib.sha256(data).hexdigest()
    storage_dir = settings.bundle_storage
    storage_dir.mkdir(parents=True, exist_ok=True)
    blob = storage_dir / f"{sha}.zip"
    if not blob.exists():
        tmp = blob.with_suffix(".zip.part")
        tmp.write_bytes(data)
        tmp.rename(blob)

    b = Bundle(
        name=name,
        version=version,
        sha256=sha,
        size=len(data),
        manifest_json=json.dumps(manifest, ensure_ascii=False),
        description=description,
        uploaded_at=utcnow(),
    )
    s.add(b)
    await log(s, "bundles", f"uploaded {name}@{version} ({len(data)} bytes, sha={sha[:12]})")
    await s.commit()
    publish({"scope": "bundles"})
    return _detail(b)


@router.get("", response_model=list[BundleSummary])
async def list_bundles(s: AsyncSession = Depends(session)) -> list[BundleSummary]:
    rows = (await s.execute(select(Bundle).order_by(Bundle.uploaded_at.desc()))).scalars().all()
    return [_summary(b) for b in rows]


@router.get("/{name}/{version}", response_model=BundleDetail)
async def detail(name: str, version: str, s: AsyncSession = Depends(session)) -> BundleDetail:
    b = await s.get(Bundle, (name, version))
    if b is None:
        raise HTTPException(404, f"bundle {name}@{version} not found")
    return _detail(b)


# File-inspection endpoints. Let the UI see *what's actually inside* a bundle
# zip, so operators can open run.sh / foo.py / manifest.yaml from the browser
# and diagnose "why did this bundle crash" without downloading + unzipping.

_MAX_TEXT_BYTES = 512 * 1024  # cap on preview size (keep browser happy)


class BundleFileEntry(BaseModel):
    path: str
    size: int


class BundleFileContent(BaseModel):
    path: str
    size: int
    truncated: bool
    binary: bool
    content: str  # empty when `binary=True`


def _strip_wrapper(names: list[str]) -> str:
    """Mirror worker's `_flatten_wrapper_dir`: if every file in the archive
    sits under a single top-level directory that contains manifest.yaml,
    return that prefix (with trailing slash). Otherwise "". Keeps UI paths
    aligned with what the worker actually unpacks."""
    non_dir = [n for n in names if not n.endswith("/")]
    if not non_dir:
        return ""
    first_segs = {n.split("/", 1)[0] for n in non_dir if "/" in n}
    has_root_file = any("/" not in n for n in non_dir)
    if has_root_file or len(first_segs) != 1:
        return ""
    prefix = first_segs.pop() + "/"
    if any(n == prefix + "manifest.yaml" for n in non_dir):
        return prefix
    return ""


def _open_zip(b: Bundle) -> zipfile.ZipFile:
    blob = settings.bundle_storage / f"{b.sha256}.zip"
    if not blob.is_file():
        raise HTTPException(500, "bundle blob missing on orchestrator disk")
    try:
        return zipfile.ZipFile(blob)
    except zipfile.BadZipFile:
        raise HTTPException(500, "bundle blob is not a valid zip") from None


@router.get("/{name}/{version}/files", response_model=list[BundleFileEntry])
async def list_files(name: str, version: str, s: AsyncSession = Depends(session)) -> list[BundleFileEntry]:
    """Enumerate files inside the bundle zip, mirroring the worker's unpack
    layout (wrapper dir stripped)."""
    b = await s.get(Bundle, (name, version))
    if b is None:
        raise HTTPException(404, f"bundle {name}@{version} not found")
    with _open_zip(b) as zf:
        prefix = _strip_wrapper(zf.namelist())
        out: list[BundleFileEntry] = []
        for info in zf.infolist():
            if info.is_dir():
                continue
            n = info.filename
            if prefix:
                if not n.startswith(prefix):
                    continue
                rel = n[len(prefix) :]
            else:
                rel = n
            if not rel:
                continue
            out.append(BundleFileEntry(path=rel, size=info.file_size))
    out.sort(key=lambda e: e.path)
    return out


@router.get("/{name}/{version}/files/{file_path:path}", response_model=BundleFileContent)
async def read_file(
    name: str, version: str, file_path: str, s: AsyncSession = Depends(session)
) -> BundleFileContent:
    """Return one file's content as text. 404 if path is not in the zip,
    400 if content doesn't decode as utf-8, truncated at _MAX_TEXT_BYTES."""
    b = await s.get(Bundle, (name, version))
    if b is None:
        raise HTTPException(404, f"bundle {name}@{version} not found")
    with _open_zip(b) as zf:
        prefix = _strip_wrapper(zf.namelist())
        internal = f"{prefix}{file_path}"
        try:
            info = zf.getinfo(internal)
        except KeyError:
            raise HTTPException(404, f"file not in bundle: {file_path}") from None
        if info.is_dir():
            raise HTTPException(400, f"path is a directory: {file_path}")
        size = info.file_size
        with zf.open(info) as fh:
            raw = fh.read(_MAX_TEXT_BYTES + 1)
        truncated = len(raw) > _MAX_TEXT_BYTES
        if truncated:
            raw = raw[:_MAX_TEXT_BYTES]
        try:
            text = raw.decode("utf-8")
            return BundleFileContent(
                path=file_path, size=size, truncated=truncated, binary=False, content=text
            )
        except UnicodeDecodeError:
            return BundleFileContent(path=file_path, size=size, truncated=truncated, binary=True, content="")


@router.get("/{name}/{version}/download")
async def download(name: str, version: str, s: AsyncSession = Depends(session)) -> Response:
    b = await s.get(Bundle, (name, version))
    if b is None:
        raise HTTPException(404, f"bundle {name}@{version} not found")
    blob = settings.bundle_storage / f"{b.sha256}.zip"
    if not blob.is_file():
        # Index has drifted from disk — treat as unrecoverable.
        raise HTTPException(500, "bundle blob missing on orchestrator disk")
    return FileResponse(
        blob,
        media_type="application/zip",
        filename=f"{name}-{version}.zip",
        headers={"X-Bundle-SHA256": b.sha256},
    )


@router.delete("/{name}/{version}")
async def delete(name: str, version: str, s: AsyncSession = Depends(session)) -> dict:
    b = await s.get(Bundle, (name, version))
    if b is None:
        raise HTTPException(404, f"bundle {name}@{version} not found")

    ref = f"orch:{name}@{version}"
    in_use = await s.scalar(select(func.count(Batch.batch_id)).where(Batch.bundle_ref == ref))
    if in_use:
        raise HTTPException(409, f"bundle is referenced by {in_use} batch(es); remove them first")

    sha = b.sha256
    await s.delete(b)
    # Only unlink the blob if no other (name, version) still points at it.
    others = await s.scalar(select(func.count()).select_from(Bundle).where(Bundle.sha256 == sha))
    if not others:
        blob = settings.bundle_storage / f"{sha}.zip"
        blob.unlink(missing_ok=True)
    await log(s, "bundles", f"deleted {name}@{version}")
    await s.commit()
    publish({"scope": "bundles"})
    return {"ok": True}
