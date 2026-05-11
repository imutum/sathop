# SatHop cleanup loop state

## Current status
- Working tree clean. All changes from this round committed.
- `src/sathop/orchestrator/pubsub.py` owns event publishing, event logging, and `commit_and_publish` (`str | None` scopes, filters falsy values).
- `src/sathop/orchestrator/api/admin.py` no longer imports raw `publish` — all DB-write-then-publish flows route through `commit_and_publish`.
- The only remaining direct `publish()` callers are intentional:
  - `background.py` (long-running sweepers without a request-scoped session)
  - `api/progress.py` (relay-only, no DB write)
  - `api/shared.py::delete` (commit → blob unlink → publish ordering must stay split)
  - `pubsub.commit_and_publish` and `pubsub.log_event` themselves
- `src/sathop/orchestrator/api/batch_readmodels.py` owns BatchSummary/GranuleRow assembly, state counts, ETA, and exhausted-object read queries.
- `src/sathop/orchestrator/api/batch_transitions.py` owns cancel/retry granule state rules.
- `src/sathop/orchestrator/api/worker_heartbeat.py` owns worker heartbeat version logging, queue/disk field application, revoke calculation, and one-shot signal consumption.
- `src/sathop/orchestrator/api/worker_leases.py` owns lease duration, worker in-flight counts, lease-size clamping, lease item assembly, pending-granule claiming, lease renewal, held-granule sampling, and force revoke mutation.
- `src/sathop/orchestrator/api/worker_transitions.py` owns worker-reported state progression, stage timing records, upload completion, and failure retry/blacklist mutation.
- `src/sathop/orchestrator/api/workers.py` keeps worker routes, endpoint validation, commit/publish/log orchestration, delete-confirm, and operator actions.
- `src/sathop/orchestrator/api/admin_readmodels.py` owns admin overview, in-flight rows, stuck-granule rows, limit clamping, and stuck-age constants.
- `src/sathop/orchestrator/api/admin.py` keeps admin routes, bundle GC mutation, settings info, commit/log/publish behavior, and route-level validation.
- `frontend/src/components/QueryState.vue` owns the 3-state (loading/error/empty/data) headless wrapper; 6 list pages use it. Dashboard and BatchDetail intentionally keep page-specific layouts.
- `frontend/src/apiClient.ts` owns browser token storage, auth headers, 401 recovery, HTTP error parsing, and JSON fetch helpers.
- `frontend/src/api.ts` remains the public typed endpoint catalog and API facade used by pages/components.
- `frontend/src/features/batch/summary.ts` owns frontend batch count totals, completed/error/in-flight totals, and closed-batch detection.
- `frontend/src/features/batch/pipelineSummary.ts` owns dashboard/pipeline-health state-count rollups, pipeline totals, and ordered non-zero segments.
- `frontend/src/features/nodes/useNodeLifecycle.ts` owns shared worker/receiver enable, forget, restart mutations, cache updates, confirmations, and toast handling.
- `frontend/src/features/batch/types.ts` owns create-batch pure form transforms: credential payload/validity, env parsing, and dirty-draft checks.

## Completed this round
- New-lens audit from angles not covered in prior rounds: deps (`pyproject.toml`), CLI surface (`pyproject [project.scripts]` vs. docs), unused imports/duplicates.
  - Found: `httpx` and `pyyaml` listed redundantly in both base deps AND each component's extras. Removed 5 dup lines.
  - Found: `sathop-pull` CLI script undocumented in CLAUDE.md. Added entry.
  - No sound files to delete, no dead imports, no stale config.
- Lockfile rebuilt: same 53 packages, 10 duplicate `requires-dist` entries removed.

## Validation
- `pytest tests/` → 430 passed in 78s.
- `ruff check` → clean.
- `uv lock --check` passes.
- Net diff: −13 lines across `pyproject.toml` + `uv.lock`; `CLAUDE.md` +1 line (local-only, gitignored).

## Key decisions
- Leaving `pyyaml` and `httpx` in base `[project.dependencies]` instead of removing them from base and keeping them in extras: both are runtime essentials (httpx for every component's agent, pyyaml for bundle manifest parsing), so making each component declare them separately just adds noise.
- Did NOT create a formal `shared` extra for `httpx`/`pyyaml` — base deps are the natural place for "everyone needs this", and the pattern matches what venv resolution already treats as transitive.

## Next suggested priorities
1. Feature, bug, release, or test work. The low-hanging dep/documentation cleanup is done.
2. If a future round wants to keep looking without a concrete trigger: examine whether `Dockerfile` lines that install both `--no-install-project` and then the full sync can be simplified now that base deps are known to cover cross-component needs. (Low value.)
3. Before any release, run the normal full validation suite.
