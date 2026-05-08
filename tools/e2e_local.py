"""Local end-to-end harness: orch + worker + receiver in one box, real HTTPS.

Spawns the three components as subprocesses, uploads a trivial copy bundle,
submits a multi-granule batch with multiple inputs each, and polls until every
object is acked + deleted (full pipeline) or the deadline elapses.

Run:
    .venv/Scripts/python.exe tools/e2e_local.py

Exit code is non-zero on any failure. Logs for each subprocess land in the
workdir and are tailed at the end so a CI run leaves something readable.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = (
    ROOT
    / ".venv"
    / ("Scripts" if sys.platform == "win32" else "bin")
    / ("python.exe" if sys.platform == "win32" else "python")
)


def _free_port() -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_http(url: str, *, headers: dict[str, str] | None = None, timeout: float = 30.0) -> None:
    """Poll the URL until it responds 2xx, raises on timeout."""
    deadline = time.time() + timeout
    last_err: Exception | None = None
    while time.time() < deadline:
        try:
            req = urllib.request.Request(url, headers=headers or {})
            with urllib.request.urlopen(req, timeout=2.0) as r:
                if 200 <= r.status < 300:
                    return
        except Exception as e:
            last_err = e
        time.sleep(0.3)
    raise TimeoutError(f"{url} not ready in {timeout}s; last_err={last_err}")


def _http_json(method: str, url: str, token: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Authorization": f"Bearer {token}"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=15.0) as r:
        return json.loads(r.read().decode())


def _build_test_bundle(tmp: Path) -> Path:
    """Trivial bundle: copies every file in $SATHOP_INPUT_DIR to $SATHOP_OUTPUT_DIR."""
    bdir = tmp / "bundle"
    bdir.mkdir(parents=True)
    (bdir / "manifest.yaml").write_text(
        "\n".join(
            [
                "name: e2e-copy",
                "version: 1.0.0",
                "inputs:",
                "  slots:",
                "    - name: a",
                "      product: prodA",
                "    - name: b",
                "      product: prodB",
                "execution:",
                "  entrypoint: 'python copy.py'",
                "  timeout_sec: 60",
                "outputs:",
                "  watch_dir: out",
                "  extensions: ['.bin']",
            ]
        ),
        encoding="utf-8",
    )
    (bdir / "copy.py").write_text(
        "\n".join(
            [
                "import os, shutil, pathlib",
                "src = pathlib.Path(os.environ['SATHOP_INPUT_DIR'])",
                "dst = pathlib.Path(os.environ['SATHOP_OUTPUT_DIR'])",
                "dst.mkdir(parents=True, exist_ok=True)",
                "for f in src.iterdir():",
                "    out = dst / (f.stem + '.bin')",
                "    shutil.copyfile(f, out)",
                "    print('copied', f.name, '->', out.name)",
            ]
        ),
        encoding="utf-8",
    )
    zpath = tmp / "bundle.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in bdir.rglob("*"):
            zf.write(f, f.relative_to(bdir))
    return zpath


def _upload_bundle(orch_url: str, token: str, zip_path: Path) -> None:
    """Multipart upload via httpx — hand-rolled urllib boundaries here would need
    careful CRLF accounting; httpx already does it and we ship httpx anyway."""
    import httpx

    with httpx.Client(timeout=30) as c:
        r = c.post(
            f"{orch_url}/api/bundles",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("bundle.zip", zip_path.read_bytes(), "application/zip")},
        )
    if r.status_code >= 400:
        raise RuntimeError(f"bundle upload HTTP {r.status_code}: {r.text[:400]}")
    body = r.json()
    print(f"[harness] bundle uploaded {body['name']}@{body['version']} sha={body['sha256'][:12]}")


def _spawn(name: str, env: dict, cmd: list[str], log_path: Path) -> subprocess.Popen:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    fh = log_path.open("w", encoding="utf-8")
    p = subprocess.Popen(
        cmd,
        env={**os.environ, **env},
        stdin=subprocess.DEVNULL,
        stdout=fh,
        stderr=subprocess.STDOUT,
        cwd=str(ROOT),
    )
    print(f"[harness] spawned {name} pid={p.pid} log={log_path}")
    return p


def _tail(path: Path, n: int = 60) -> str:
    if not path.exists():
        return f"(no log at {path})"
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(lines[-n:])


def main() -> int:
    keep_workdir = bool(os.getenv("E2E_KEEP_WORKDIR"))
    work = Path(tempfile.mkdtemp(prefix="sathop-e2e-"))
    print(f"[harness] workdir: {work} (keep={keep_workdir})")
    log_dir = work / "logs"

    token = secrets.token_hex(16)
    orch_port = _free_port()
    worker_port = _free_port()
    progress_port = _free_port()
    inputs_port = _free_port()

    orch_url = f"http://127.0.0.1:{orch_port}"
    worker_public = f"https://127.0.0.1:{worker_port}"

    # Inputs HTTP server: serves bytes from work/inputs/ that the worker downloads
    # into its $SATHOP_INPUT_DIR before running the bundle. Plain HTTP — this is
    # the *upstream* (e.g. NASA), unrelated to the worker→receiver SSL we test.
    inputs_dir = work / "inputs"
    inputs_dir.mkdir()
    payloads: dict[str, bytes] = {}
    for i in range(4):
        name = f"input-{i}.dat"
        # Vary size: small, ~100KB, ~1MB, ~3MB. Exercises chunked streaming.
        data = bytes(
            [(i + 1) * 7] * (256 if i == 0 else 100_000 if i == 1 else 1_000_000 if i == 2 else 3_000_000)
        )
        (inputs_dir / name).write_bytes(data)
        payloads[name] = data

    inputs_proc = subprocess.Popen(
        [str(PYTHON), "-m", "http.server", str(inputs_port), "--bind", "127.0.0.1"],
        cwd=str(inputs_dir),
        stdin=subprocess.DEVNULL,
        stdout=(log_dir / "inputs.log").open("w")
        if log_dir.mkdir(parents=True, exist_ok=True) or True
        else None,
        stderr=subprocess.STDOUT,
    )
    print(f"[harness] inputs server pid={inputs_proc.pid} :{inputs_port}")

    procs: list[tuple[str, subprocess.Popen]] = [("inputs", inputs_proc)]

    try:
        # ── Orchestrator ──
        orch_env = {
            "SATHOP_HOST": "127.0.0.1",
            "SATHOP_PORT": str(orch_port),
            "SATHOP_TOKEN": token,
            "SATHOP_DB": str(work / "orch" / "orchestrator.db"),
            "SATHOP_BUNDLES": str(work / "orch" / "bundles"),
            "SATHOP_SHARED": str(work / "orch" / "shared"),
            # No web UI (frontend/dist/ may or may not exist; we don't care here).
        }
        orch_proc = _spawn(
            "orch",
            orch_env,
            [str(PYTHON), "-m", "sathop.orchestrator.main"],
            log_dir / "orch.log",
        )
        procs.append(("orch", orch_proc))

        _wait_http(
            f"{orch_url}/api/admin/settings/info", headers={"Authorization": f"Bearer {token}"}, timeout=20
        )
        print("[harness] orchestrator ready")

        # ── Bundle upload ──
        zip_path = _build_test_bundle(work)
        _upload_bundle(orch_url, token, zip_path)

        # ── Worker ──
        worker_env = {
            "SATHOP_WORKER_ID": "wkr-e2e",
            "SATHOP_PUBLIC_URL": worker_public,
            "SATHOP_ORCH_URL": orch_url,
            "SATHOP_TOKEN": token,
            "SATHOP_WORK_ROOT": str(work / "worker" / "work"),
            "SATHOP_BUNDLE_CACHE": str(work / "worker" / "bundles"),
            "SATHOP_VENV_CACHE": str(work / "worker" / "venvs"),
            "SATHOP_SHARED_CACHE": str(work / "worker" / "shared"),
            "SATHOP_STORAGE_ROOT": str(work / "worker" / "storage"),
            "SATHOP_STORAGE_PORT": str(worker_port),
            "SATHOP_PROGRESS_PORT": str(progress_port),
            "SATHOP_TLS_CERT": str(work / "worker" / "tls" / "cert.pem"),
            "SATHOP_TLS_KEY": str(work / "worker" / "tls" / "key.pem"),
            "SATHOP_HEARTBEAT": "3",
            "SATHOP_LEASE_POLL": "2",
            "SATHOP_DOWNLOAD_CONCURRENCY": "2",
            "SATHOP_PROCESS_CONCURRENCY": "2",
        }
        worker_proc = _spawn(
            "worker",
            worker_env,
            [str(PYTHON), "-m", "sathop.worker.main"],
            log_dir / "worker.log",
        )
        procs.append(("worker", worker_proc))

        # Wait for worker to register (visible at /api/workers).
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                workers = _http_json("GET", f"{orch_url}/api/workers", token)
                w = next((x for x in workers if x.get("worker_id") == "wkr-e2e"), None)
                if w is not None:
                    print(f"[harness] worker registered (reported version: {w.get('version')!r})")
                    break
            except Exception:
                pass
            time.sleep(0.5)
        else:
            raise TimeoutError("worker did not register")

        # ── Receiver ──
        recv_env = {
            "SATHOP_RECEIVER_ID": "rcv-e2e",
            "SATHOP_STORAGE_DIR": str(work / "receiver" / "archive"),
            "SATHOP_ORCH_URL": orch_url,
            "SATHOP_TOKEN": token,
            "SATHOP_POLL_INTERVAL": "2",
            "SATHOP_CONCURRENT_PULLS": "4",
            # Defaults already True in 0.3.3+, but explicit for clarity.
            "SATHOP_TLS_VERIFY": "true",
            "SATHOP_TLS_TRUST_ORCH": "true",
        }
        recv_proc = _spawn(
            "receiver",
            recv_env,
            [str(PYTHON), "-m", "sathop.receiver.main"],
            log_dir / "receiver.log",
        )
        procs.append(("receiver", recv_proc))

        deadline = time.time() + 15
        while time.time() < deadline:
            try:
                receivers = _http_json("GET", f"{orch_url}/api/receivers", token)
                rcv = next((r for r in receivers if r.get("receiver_id") == "rcv-e2e"), None)
                if rcv is not None:
                    print(f"[harness] receiver registered (reported version: {rcv.get('version')!r})")
                    break
            except Exception:
                pass
            time.sleep(0.5)
        else:
            raise TimeoutError("receiver did not register")

        # ── Submit batch ──
        # 3 granules × 2 inputs each. Chosen to exercise:
        #   - concurrent downloads (download_sem=2)
        #   - concurrent processing (process_sem=2)
        #   - concurrent receiver pulls of multiple granules' outputs
        n_granules = int(os.getenv("E2E_GRANULES", "3"))
        granules = []
        for gi in range(n_granules):
            # Two slots, two inputs — first input fills slot a (small), second
            # fills slot b (larger). Together they exercise concurrent download
            # + chunked streaming on the receiver pull side.
            granules.append(
                {
                    "granule_id": f"g{gi}",
                    "inputs": [
                        {
                            "url": f"http://127.0.0.1:{inputs_port}/input-0.dat",
                            "filename": f"g{gi}-a.dat",
                            "product": "prodA",
                        },
                        {
                            "url": f"http://127.0.0.1:{inputs_port}/input-{(gi % 3) + 1}.dat",
                            "filename": f"g{gi}-b.dat",
                            "product": "prodB",
                        },
                    ],
                }
            )
        batch = _http_json(
            "POST",
            f"{orch_url}/api/batches",
            token,
            {
                "name": "e2e-copy-test",
                "bundle_ref": "orch:e2e-copy@1.0.0",
                "granules": granules,
            },
        )
        batch_id = batch["batch_id"]
        print(f"[harness] batch submitted: {batch_id}")

        # Sanity: confirm the granules made it past validation and are visible.
        gr = _http_json("GET", f"{orch_url}/api/batches/{batch_id}/granules?limit=10", token)
        print(f"[harness] granules registered: {len(gr)}")
        for g in gr:
            print(f"           - {g['granule_id']} state={g['state']}")

        # ── Poll until acked + deleted, or timeout ──
        target_total = len(granules)
        deadline = time.time() + max(240, 60 * target_total)  # scale with batch size
        last_summary: dict | None = None
        while time.time() < deadline:
            time.sleep(2)
            try:
                detail = _http_json("GET", f"{orch_url}/api/batches/{batch_id}", token)
                summary = detail.get("counts", {})
                if summary != last_summary:
                    print(f"[harness] counts={summary} exh={detail.get('objects_exhausted', 0)}")
                    last_summary = summary
                acked = summary.get("acked", 0)
                deleted = summary.get("deleted", 0)
                if acked + deleted == target_total and deleted == target_total:
                    print(f"[harness] ✅ all granules acked+deleted: {summary}")
                    return 0
                if detail.get("objects_exhausted", 0) > 0:
                    print(f"[harness] ❌ pull exhaustion: {detail['objects_exhausted']} objects gave up")
                    return 2
            except Exception as e:
                print(f"[harness] poll err: {e}")

        print("[harness] ❌ timeout — final state below")
        try:
            print(json.dumps(_http_json("GET", f"{orch_url}/api/batches/{batch_id}", token), indent=2))
        except Exception:
            pass
        return 1

    finally:
        for name, p in reversed(procs):
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    p.kill()
            print(f"--- {name} log tail ---")
            print(_tail(log_dir / f"{name}.log", 40))
        if not keep_workdir:
            try:
                shutil.rmtree(work, ignore_errors=True)
            except Exception:
                pass
        else:
            print(f"[harness] workdir kept: {work}")


if __name__ == "__main__":
    raise SystemExit(main())
