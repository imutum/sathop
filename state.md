# SatHop cleanup loop state

## Current status
- Working tree carries one source change: `admin.py::gc_bundles` migrated to `commit_and_publish`.
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
- Audited the three next-round suggestions from the previous round:
  - **Worker `client.report_*` try/except**: not repetitive in practice — each report has its own semantics (404→`LeaseRevoked`, debug-swallow, bare). No abstraction available.
  - **Admin pre-flight checks**: each route's pre-check is different (`clamp_limit`, `NON_TERMINAL` membership, `age_days < 0`). No common shape to extract.
  - **Frontend loading/error scaffolding**: already abstracted via `QueryState` (6 pages); the 2 holdouts (Dashboard, BatchDetail) have legitimate non-3-state layouts.
- Found one concrete migration opportunity that the previous round missed: `admin.py::gc_bundles` was the last surviving DB-write path using raw `s.commit()` + conditional `publish(...)` instead of `commit_and_publish`. Migrated to the new ternary form.
- Removed the now-unused `publish` import from `admin.py`.

## Validation
- Net diff: 3 lines down across `admin.py` (1 line of imports churn, 2 lines of body collapse).
- `pytest tests/` → 430 passed in 77s.
- `ruff check` + `ruff format --check admin.py` → clean.
- Grep audit confirms remaining direct `publish()` callers all have a documented reason to stay raw (see Current status).

## Key decisions
- Did NOT migrate `shared.py::delete`'s split `commit → unlink → publish` — the ordering matters: subscribers shouldn't be nudged until the FS unlink completes.
- Did NOT touch `background.py` or `progress.py` raw publishes — they're not request-scoped DB writes, so `commit_and_publish` is the wrong abstraction.
- Resisted the temptation to refactor Dashboard/BatchDetail into `QueryState` — their "render with empty fallbacks + non-blocking error alert" pattern is genuinely different from QueryState's "all-or-nothing slot dispatch".

## Next suggested priorities
1. Default back to feature, bug, release, or test work. The orchestrator commit/publish pattern is now uniform; the next concrete cleanup target is not visible without a real trigger.
2. If a future round wants to keep looking, candidates I deliberately did NOT pursue this round but flagged as possibly worth a look:
   - `frontend/src/pages/Batches.vue` (494 lines) and `frontend/src/pages/BatchDetail.vue` (421 lines) are the largest frontend pages; check whether sections can move into `features/batch/components/` without bloating prop drilling.
   - `tests/test_bundle_registry.py` is 599 lines — verify it's still mapping one test class per scenario, not accumulating helpers.
3. Before any release, run the normal full validation suite rather than more structural reshuffling.
