# Bundle Authoring

A **bundle** is a zip containing user code (any language) plus a `manifest.yaml`. The orchestrator stores it; workers fetch it once per `name@version`, reuse the worker's current Python when no Python deps are declared, build a venv only for declared `pip` deps, and invoke the entrypoint per granule.

This document covers everything you need to write, ship, and debug one.

---

## 60-second start

Copy `examples/bundle-hello-world/`, edit two lines, ship it:

```bash
# Validate before zipping (catches manifest typos, missing entrypoint, bad regex)
sathop-validate-bundle examples/bundle-hello-world

# Zip + upload (validates again unless --skip-validate)
sathop-upload-bundle examples/bundle-hello-world --url sathop://TOKEN@orch:8000

# Submit a batch via Web UI → "新建任务" → pick the bundle.
```

Failure shows up in the batch-detail page: error summary, full `stdout` tab, full `stderr` tab. No ssh required.

---

## manifest.yaml

```yaml
name: my-bundle               # required, [A-Za-z0-9._-]+
version: 1.0.0                # required, [A-Za-z0-9._+-]+; cannot re-upload same name@version
description: optional         # shown in UI bundle list

execution:                    # required
  entrypoint: "python run.py" # required; PATH-prefixed with selected Python
  timeout_sec: 900            # optional, default 900; SIGTERM then SIGKILL
  env:                        # optional default env vars
    GDAL_NUM_THREADS: "2"

outputs:                      # required
  watch_dir: output           # subdir under $SATHOP_WORK_DIR; bundle writes here
  extensions: [".tif", ".h5"] # optional filter; empty = collect everything
  object_key_template: "{stem}_{year}{ext}"  # optional; default "{stem}{ext}"

inputs:                       # required
  slots:                      # ≥1; one input per slot per granule
    - name: primary
      product: MOD09A1        # matches InputSpec.product
      filename_pattern: '^MOD09A1\..+\.hdf$'  # optional regex
      credential: nasa-edl    # optional default credential
  meta:                       # optional per-granule metadata fields
    - name: year
      pattern: '^\d{4}$'      # optional regex

requirements:                 # all optional
  python: ">=3.11"            # PEP 440 specifier; informational
  pip: ["numpy>=2", "rasterio"]   # installed into the per-bundle venv
  apt: ["gdal-bin"]           # documented; image must already include them
  credentials: [nasa-edl]     # names that batches must supply

shared_files: [coast.shp]     # optional; auxiliary files uploaded once to /api/shared
```

**Re-upload rule.** Same `(name, version)` returns 409. Bump `version` (any string differing from the previous works) when iterating. The orchestrator's GC sweeper (`POST /api/admin/gc/bundles`) eventually reclaims orphaned old versions — see `docs/` … (or just delete via UI/API).

---

## What the worker hands you (runtime contract)

When the worker invokes `entrypoint`, it sets these env vars:

| Var | Meaning |
|---|---|
| `SATHOP_INPUT_DIR` | directory containing the granule's downloaded input files |
| `SATHOP_OUTPUT_DIR` | directory the bundle MUST write outputs into (= `<work_dir>/<watch_dir>`) |
| `SATHOP_WORK_DIR` | scratch directory; cleaned up after the granule |
| `SATHOP_SHARED_DIR` | read-only directory of synced shared files (open `$SATHOP_SHARED_DIR/coast.shp`) |
| `SATHOP_GRANULE_ID` | per-granule unique id (composed `<batch>:<user_gid>`) |
| `SATHOP_BATCH_ID` | the batch this granule belongs to |
| `SATHOP_META_JSON` | JSON-encoded per-granule meta dict (e.g. `{"year": "2024"}`) |
| `SATHOP_BUNDLE_PYTHON` | absolute path to the Python interpreter selected for this bundle |
| `SATHOP_VENV_PYTHON` | compatibility alias for `SATHOP_BUNDLE_PYTHON` |
| `SATHOP_PROGRESS_URL` | optional; POST checkpoints here (see Progress) |

Plus a curated whitelist of OS vars (`PATH`, `HOME`/`USERPROFILE`, `TMP*`, `LANG`, etc.). **Worker secrets like `SATHOP_TOKEN` are NOT inherited** — the bundle cannot impersonate the worker against the orchestrator.

`PATH` starts with the selected Python's bin dir. For dependency-free bundles this is the worker's current environment; for bundles with `requirements.txt` or `requirements.pip`, it is the cached per-bundle venv.

---

## Inputs

The orchestrator validates each granule against `inputs.slots`/`inputs.meta` at batch creation:

- **Slots**: every declared slot must be filled exactly once. A granule whose inputs don't supply a matching `product` is rejected.
- **Meta**: every declared meta field must be present and match its `pattern`.
- **Extras**: undeclared products/meta keys are warnings, not errors.

The bundle just reads files from `$SATHOP_INPUT_DIR` (filenames preserved from `InputSpec.filename`) and `$SATHOP_META_JSON`.

---

## Outputs

The bundle writes any number of files into `$SATHOP_OUTPUT_DIR` (recursive subdirs OK). After exit code 0, the worker:

1. Filters by `extensions` (if set).
2. Renders each filename through `object_key_template`. Available fields: `{stem}`, `{ext}`, `{name}`, plus every key in `meta` (e.g. `{year}`, `{tile}`).
3. Uploads to local storage (or MinIO) under that key.

If the template references a meta key the granule doesn't have, the worker falls back to `{name}` for that file (no failure).

**Empty output is treated as failure.** Exit 0 with nothing in `$SATHOP_OUTPUT_DIR/` reports as `[no outputs produced]` in stderr.

---

## Requirements

`requirements.pip` is the only manifest dependency list the worker actually installs. `requirements.txt` at the bundle root takes precedence and the manifest list is ignored — pick one. If neither declares Python deps, the worker reuses its current Python environment and skips venv creation. `apt` is documented but the worker base image must already include those packages; the worker does NOT run apt.

`requirements.credentials` declares names the batch must populate via `BatchCreate.credentials`. The Web UI's batch-create dialog renders a form for each declared name. Schemes today: `basic` (`username`/`password`) and `bearer` (`token`).

A bundle's `InputSpec.credential` (set per slot or per granule) picks one of those names; the worker's downloader translates it to either HTTP Basic auth or `Authorization: Bearer …`.

---

## Shared files

Anything too big to ship per-batch (DEMs, masks, lookup tables): upload once to `/api/shared/<name>` (UI: 「共享文件」), declare in manifest:

```yaml
shared_files: [coast.shp, dem-30m.tif]
```

The worker downloads them lazily on first ensure() and caches by sha256 — only re-downloads on drift. Bundle reads `$SATHOP_SHARED_DIR/coast.shp` at runtime.

Names referenced by any uploaded bundle cannot be deleted from the registry (409). To rotate: re-upload the same name; the next lease picks up the new sha.

---

## Progress reporting

If `$SATHOP_PROGRESS_URL` is set (worker injects it; URL is signed with a per-granule nonce), the bundle can POST checkpoints:

```python
import os
import httpx

def progress(step: str, pct: float | None = None, detail: str | None = None) -> None:
    url = os.environ.get("SATHOP_PROGRESS_URL")
    if not url:
        return
    httpx.post(url, json={"step": step, "pct": pct, "detail": detail}, timeout=5)
```

Events surface in the granule's expanded row in the batch-detail page (timeline). Failed POSTs are silently swallowed by the worker — bundles shouldn't break because the worker is briefly unreachable.

The nonce is single-use per granule; reusing it across granules will 404.

---

## Debugging failures

When `entrypoint` exits non-zero (or zero but `$SATHOP_OUTPUT_DIR/` is empty), the worker reports:

- `error`: short summary (last 2 KB of stderr) — shown in the granule row's error cell.
- `stdout_tail` + `stderr_tail`: last 16 KB of each stream — exposed in the UI's `ErrorCell` as **stdout** / **stderr** tabs after expanding the row.

So `print(...)` and full Python tracebacks are visible in the Web UI without ssh'ing into a worker. On a granule retry (manual or automatic), the previous tails persist on the row until the granule successfully uploads, then they clear.

For pre-flight bundle issues (manifest typos, missing scripts, broken regexes), use:

```bash
sathop-validate-bundle ./my-bundle              # static checks
sathop-validate-bundle ./my-bundle --build-venv # also runs `uv venv` + pip-install (slow)
```

`sathop-upload-bundle` runs the static checks automatically; pass `--skip-validate` to bypass in emergencies.

---

## Versioning recipe

The orchestrator refuses to overwrite an existing `name@version`. Two patterns work in practice:

- **Production releases**: semver. `1.0.0` → `1.0.1` (fix) → `1.1.0` (feature) → `2.0.0` (breaking).
- **Iteration during dev**: append a build counter. `1.0.0-dev1`, `1.0.0-dev2`, …; squash to `1.0.0` once green.

Old versions don't auto-delete. The orchestrator GC endpoint sweeps them (default: unreferenced + ≥30 days old):

```bash
# dry-run first; pass dry_run=false when you trust the candidate list
curl -X POST -H "Authorization: Bearer $SATHOP_TOKEN" \
  "$ORCH/api/admin/gc/bundles?age_days=30&dry_run=true"
```

---

## Cross-references

- `examples/bundle-hello-world/` — minimal runnable bundle
- `src/sathop/orchestrator/bundle_schema.py` — authoritative parser (what the strict validator runs)
- `src/sathop/worker/processor.py` — what actually invokes your entrypoint
- `src/sathop/shared/protocol.py` — Pydantic models for ProgressEvent, Credential, InputSpec
