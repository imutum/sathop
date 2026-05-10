"""Worker bundle runner: covers input staging, entrypoint exec, output collection,
extension filter, non-zero exit, empty-output detection, env-var injection.

Uses a stub BundleHandle that points python at sys.executable — so the
test doesn't pay the ~5s cost of `python -m venv` for every case."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

from sathop.worker.bundle import BundleHandle, BundleManifest
from sathop.worker.processor import run_bundle


def _make_bundle(
    tmp_path: Path,
    entrypoint: str,
    script: str,
    *,
    watch_dir: str = "output",
    extensions: list[str] | None = None,
    timeout_sec: int = 30,
) -> BundleHandle:
    root = tmp_path / "bundle"
    root.mkdir()
    manifest_data = {
        "name": "test-bundle",
        "version": "0.0.1",
        "execution": {"entrypoint": entrypoint, "timeout_sec": timeout_sec},
        "outputs": {"watch_dir": watch_dir, **({"extensions": extensions} if extensions else {})},
    }
    (root / "manifest.yaml").write_text(yaml.safe_dump(manifest_data), encoding="utf-8")
    (root / "run.py").write_text(script, encoding="utf-8")
    manifest = BundleManifest.load(root / "manifest.yaml")
    shared = tmp_path / "shared"
    shared.mkdir(exist_ok=True)
    # Point runtime python at the test interpreter; processor PATH-prepends its parent.
    return BundleHandle(manifest=manifest, root=root, python=Path(sys.executable), shared_dir=shared)


@pytest.fixture
def work_root(tmp_path):
    d = tmp_path / "work"
    d.mkdir()
    return d


async def test_happy_path_copies_input_runs_and_collects(tmp_path, work_root):
    inp = tmp_path / "in.txt"
    inp.write_text("hello", encoding="utf-8")

    script = (
        "import os, shutil, pathlib\n"
        "i = pathlib.Path(os.environ['SATHOP_INPUT_DIR'])\n"
        "o = pathlib.Path(os.environ['SATHOP_OUTPUT_DIR'])\n"
        "for p in i.iterdir(): shutil.copy2(p, o / p.name)\n"
    )
    h = _make_bundle(tmp_path, "python run.py", script)

    r = await run_bundle(h, "g1", "b1", [inp], {}, work_root)

    assert r.ok
    assert r.exit_code == 0
    assert len(r.outputs) == 1
    assert r.outputs[0].read_text(encoding="utf-8") == "hello"
    # kept_root naming
    assert "_staged" in str(r.outputs[0])


async def test_nonzero_exit_reports_failure(tmp_path, work_root):
    h = _make_bundle(tmp_path, "python run.py", "import sys; sys.exit(7)")
    r = await run_bundle(h, "g1", "b1", [], {}, work_root)
    assert not r.ok
    assert r.exit_code == 7
    assert r.outputs == []


async def test_empty_output_dir_flagged_as_failure(tmp_path, work_root):
    """Bundle ran to success but produced nothing — worker needs this caught."""
    h = _make_bundle(tmp_path, "python run.py", "print('idle'); pass")
    r = await run_bundle(h, "g1", "b1", [], {}, work_root)
    assert not r.ok
    assert r.exit_code == 0
    assert "no outputs" in r.stderr


async def test_extension_filter_drops_non_matching(tmp_path, work_root):
    script = (
        "import os, pathlib\n"
        "o = pathlib.Path(os.environ['SATHOP_OUTPUT_DIR'])\n"
        "(o / 'keep.txt').write_text('yes')\n"
        "(o / 'skip.log').write_text('no')\n"
    )
    h = _make_bundle(tmp_path, "python run.py", script, extensions=[".txt"])
    r = await run_bundle(h, "g1", "b1", [], {}, work_root)
    assert r.ok
    names = {p.name for p in r.outputs}
    assert names == {"keep.txt"}


async def test_multiple_inputs_all_staged(tmp_path, work_root):
    a = tmp_path / "a.txt"
    a.write_text("A", encoding="utf-8")
    b = tmp_path / "b.txt"
    b.write_text("B", encoding="utf-8")
    script = (
        "import os, pathlib\n"
        "i = pathlib.Path(os.environ['SATHOP_INPUT_DIR'])\n"
        "o = pathlib.Path(os.environ['SATHOP_OUTPUT_DIR'])\n"
        "names = sorted(p.name for p in i.iterdir())\n"
        "(o / 'list.txt').write_text(','.join(names))\n"
    )
    h = _make_bundle(tmp_path, "python run.py", script)
    r = await run_bundle(h, "g1", "b1", [a, b], {}, work_root)
    assert r.ok
    assert r.outputs[0].read_text(encoding="utf-8") == "a.txt,b.txt"


async def test_env_vars_reach_entrypoint(tmp_path, work_root):
    script = (
        "import os, pathlib\n"
        "o = pathlib.Path(os.environ['SATHOP_OUTPUT_DIR'])\n"
        "(o / 'ids.txt').write_text(\n"
        "    os.environ['SATHOP_GRANULE_ID'] + '|' + os.environ['SATHOP_BATCH_ID']\n"
        ")\n"
    )
    h = _make_bundle(tmp_path, "python run.py", script)
    r = await run_bundle(h, "my-granule", "my-batch", [], {}, work_root)
    assert r.ok
    assert r.outputs[0].read_text(encoding="utf-8") == "my-granule|my-batch"


async def test_runtime_python_env_vars_reach_entrypoint(tmp_path, work_root):
    script = (
        "import os, pathlib\n"
        "o = pathlib.Path(os.environ['SATHOP_OUTPUT_DIR'])\n"
        "(o / 'python.txt').write_text(\n"
        "    os.environ['SATHOP_BUNDLE_PYTHON'] + '\\n' + os.environ['SATHOP_VENV_PYTHON']\n"
        ")\n"
    )
    h = _make_bundle(tmp_path, "python run.py", script)
    r = await run_bundle(h, "g", "b", [], {}, work_root)
    assert r.ok
    assert r.outputs[0].read_text(encoding="utf-8") == f"{sys.executable}\n{sys.executable}"


async def test_custom_env_in_manifest_merged(tmp_path, work_root):
    script = (
        "import os, pathlib\n"
        "o = pathlib.Path(os.environ['SATHOP_OUTPUT_DIR'])\n"
        "(o / 'e.txt').write_text(os.environ.get('EXTRA_KEY', 'MISSING'))\n"
    )
    root = tmp_path / "bundle"
    root.mkdir()
    (root / "manifest.yaml").write_text(
        yaml.safe_dump(
            {
                "name": "t",
                "version": "1",
                "execution": {
                    "entrypoint": "python run.py",
                    "env": {"EXTRA_KEY": "custom-val"},
                    "timeout_sec": 30,
                },
                "outputs": {"watch_dir": "output"},
            }
        ),
        encoding="utf-8",
    )
    (root / "run.py").write_text(script, encoding="utf-8")
    h = BundleHandle(
        manifest=BundleManifest.load(root / "manifest.yaml"),
        root=root,
        python=Path(sys.executable),
        shared_dir=tmp_path / "shared",
    )
    r = await run_bundle(h, "g", "b", [], {}, work_root)
    assert r.ok
    assert r.outputs[0].read_text(encoding="utf-8") == "custom-val"


async def test_batch_env_overrides_bundle_env(tmp_path, work_root):
    """Batch execution_env wins over bundle manifest env — the whole point of
    batch-level overrides (same bundle, different task knobs)."""
    script = (
        "import os, pathlib\n"
        "o = pathlib.Path(os.environ['SATHOP_OUTPUT_DIR'])\n"
        "(o / 'e.txt').write_text(os.environ.get('RESOLUTION', 'MISSING'))\n"
    )
    root = tmp_path / "bundle"
    root.mkdir()
    (root / "manifest.yaml").write_text(
        yaml.safe_dump(
            {
                "name": "t",
                "version": "1",
                "execution": {
                    "entrypoint": "python run.py",
                    "env": {"RESOLUTION": "500m"},  # bundle default
                    "timeout_sec": 30,
                },
                "outputs": {"watch_dir": "output"},
            }
        ),
        encoding="utf-8",
    )
    (root / "run.py").write_text(script, encoding="utf-8")
    h = BundleHandle(
        manifest=BundleManifest.load(root / "manifest.yaml"),
        root=root,
        python=Path(sys.executable),
        shared_dir=tmp_path / "shared",
    )
    # Batch overrides the bundle default
    r = await run_bundle(h, "g", "b", [], {}, work_root, execution_env={"RESOLUTION": "1km"})
    assert r.ok
    assert r.outputs[0].read_text(encoding="utf-8") == "1km"


async def test_internal_sathop_vars_immune_to_override(tmp_path, work_root):
    """Batch env must NOT be able to hijack SATHOP_OUTPUT_DIR or SATHOP_INPUT_DIR
    — those are worker-controlled invariants."""
    script = (
        "import os, pathlib\n"
        "o = pathlib.Path(os.environ['SATHOP_OUTPUT_DIR'])\n"
        "(o / 'sentinel.txt').write_text(o.name)\n"
    )
    h = _make_bundle(tmp_path, "python run.py", script)
    # Malicious batch env trying to redirect output
    r = await run_bundle(
        h,
        "g",
        "b",
        [],
        {},
        work_root,
        execution_env={"SATHOP_OUTPUT_DIR": "/tmp/pwned"},
    )
    assert r.ok  # internal var wasn't overridden; output went where worker said
    assert len(r.outputs) == 1


async def test_progress_url_injected_when_provided(tmp_path, work_root):
    script = (
        "import os, pathlib\n"
        "o = pathlib.Path(os.environ['SATHOP_OUTPUT_DIR'])\n"
        "(o / 'u.txt').write_text(os.environ.get('SATHOP_PROGRESS_URL', 'MISSING'))\n"
    )
    h = _make_bundle(tmp_path, "python run.py", script)
    r = await run_bundle(
        h,
        "g",
        "b",
        [],
        {},
        work_root,
        progress_url="http://127.0.0.1:9002/progress/abc123",
    )
    assert r.ok
    assert r.outputs[0].read_text(encoding="utf-8") == "http://127.0.0.1:9002/progress/abc123"


async def test_progress_url_absent_when_not_provided(tmp_path, work_root):
    """No progress_url → SATHOP_PROGRESS_URL should not appear in env. Bundles
    check for its absence to stay backward compatible with older workers."""
    script = (
        "import os, pathlib\n"
        "o = pathlib.Path(os.environ['SATHOP_OUTPUT_DIR'])\n"
        "(o / 'u.txt').write_text(os.environ.get('SATHOP_PROGRESS_URL', 'MISSING'))\n"
    )
    h = _make_bundle(tmp_path, "python run.py", script)
    r = await run_bundle(h, "g", "b", [], {}, work_root)
    assert r.ok
    assert r.outputs[0].read_text(encoding="utf-8") == "MISSING"


async def test_batch_env_cannot_hijack_progress_url(tmp_path, work_root):
    """Like SATHOP_OUTPUT_DIR, SATHOP_PROGRESS_URL is worker-controlled —
    a malicious batch env mustn't be able to redirect progress to an external host."""
    script = (
        "import os, pathlib\n"
        "o = pathlib.Path(os.environ['SATHOP_OUTPUT_DIR'])\n"
        "(o / 'u.txt').write_text(os.environ['SATHOP_PROGRESS_URL'])\n"
    )
    h = _make_bundle(tmp_path, "python run.py", script)
    r = await run_bundle(
        h,
        "g",
        "b",
        [],
        {},
        work_root,
        execution_env={"SATHOP_PROGRESS_URL": "http://attacker.example.com/x"},
        progress_url="http://127.0.0.1:9002/progress/real",
    )
    assert r.ok
    assert r.outputs[0].read_text(encoding="utf-8") == "http://127.0.0.1:9002/progress/real"


async def test_worker_secrets_not_leaked_to_bundle(tmp_path, work_root, monkeypatch):
    """Critical security guarantee: bundle subprocesses must NOT inherit the
    worker's SATHOP_TOKEN (or any other non-whitelisted env var) — otherwise a
    malicious bundle could call the orchestrator API with worker-level
    privileges. The env whitelist in processor._ENV_WHITELIST enforces this;
    SATHOP_* variables the bundle legitimately needs are injected explicitly
    by _build_env (granule id, batch id, dirs, ...) and aren't inherited as
    a class."""
    monkeypatch.setenv("SATHOP_TOKEN", "secret-token-xyz")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "leaky-aws-key")
    monkeypatch.setenv("SATHOP_INTERNAL_ARBITRARY", "should-not-leak")
    script = (
        "import os, pathlib\n"
        "o = pathlib.Path(os.environ['SATHOP_OUTPUT_DIR'])\n"
        "(o / 'env.txt').write_text(\n"
        "    f\"token={os.environ.get('SATHOP_TOKEN','MISSING')};\"\n"
        "    f\"aws={os.environ.get('AWS_SECRET_ACCESS_KEY','MISSING')};\"\n"
        "    f\"arb={os.environ.get('SATHOP_INTERNAL_ARBITRARY','MISSING')}\"\n"
        ")\n"
    )
    h = _make_bundle(tmp_path, "python run.py", script)
    r = await run_bundle(h, "g", "b", [], {}, work_root)
    assert r.ok
    out = r.outputs[0].read_text(encoding="utf-8")
    assert "token=MISSING" in out, f"SATHOP_TOKEN leaked to bundle: {out!r}"
    assert "aws=MISSING" in out, f"AWS_SECRET_ACCESS_KEY leaked: {out!r}"
    assert "arb=MISSING" in out, f"non-whitelisted SATHOP_* leaked: {out!r}"


async def test_cancel_kills_subprocess_promptly(tmp_path, work_root):
    """The whole reason run_bundle is async: when the worker's handler task
    is cancelled (operator hit "取消批次"), the child must die within a few
    seconds rather than burning CPU until manifest.timeout_sec."""
    import asyncio
    import time

    # 60s sleep gives us plenty of headroom — the test should finish in <2s.
    script = "import time; time.sleep(60)\n"
    h = _make_bundle(tmp_path, "python run.py", script, timeout_sec=120)

    async def worker_task():
        return await run_bundle(h, "g", "b", [], {}, work_root)

    task = asyncio.create_task(worker_task())
    # Let the subprocess actually start before we cancel — without this the
    # cancel would race against asyncio.create_subprocess_shell setup.
    await asyncio.sleep(0.5)
    started = time.monotonic()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    elapsed = time.monotonic() - started
    # _kill_and_wait gives a 5s SIGTERM grace period before SIGKILL; the whole
    # tear-down should comfortably finish well under 10s. Anything close to
    # the bundle's timeout_sec means we're not actually killing the child.
    assert elapsed < 10, f"cancel took {elapsed:.1f}s — subprocess wasn't killed promptly"
