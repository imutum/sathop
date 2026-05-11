# SatHop cleanup loop state

## Current status
- Working tree clean. All changes from prior rounds committed.
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
- New-lens audit from angles not yet covered: Dockerfile consistency across 3 components, deploy compose files, Settings/config duplication, test naming/organization, package entrypoint resolution.
  - 3 Dockerfiles follow an identical two-phase pattern (dep layer + source layer) with expected per-component differences (ca-certificates on worker/receiver, HEALTHCHECK on orchestrator). No dedup opportunity.
  - Settings classes are clean (49/112/49 lines) with no duplicated field definitions.
  - 50 test files, single conftest.py, no helpers/utils drift.
  - All 7 console_scripts in pyproject resolve correctly.
  - No stale __pycache__ tracked, no orphan files.
- No concrete cleanup target found. The project has reached a stable, clean baseline across backend code, frontend code, configuration, dependencies, tests, and deployment artifacts.

## Validation
- Multi-angle audit: Dockerfiles, config classes, test structure, entrypoint resolution, git ls-files for staleness.
- No tests needed — no source code changed.

## Key decisions
- The cleanup loop has converged. The project is in a state where further structural cleanup requires a concrete trigger (duplicated logic, failing test, confusing ownership, feature addition that reveals a pattern) rather than proactive searching.
- Will recommend transitioning out of cleanup-only mode in the next suggested priorities.

## Next suggested priorities
1. **Transition to feature or release work.** The cleanup loop has exhausted low-hanging structural improvements without a concrete trigger. Continuing to search for cleanup will increasingly return false positives and create unnecessary churn.
2. If operator action is needed: bump version for 0.5.0 (several rounds of refactoring and dedup have accumulated since 0.4.7), run the full validation suite, and cut a release.
3. If the loop continues anyway (by user preference), switch to **test gap analysis** — which scenarios are untested — rather than structural cleanup.
