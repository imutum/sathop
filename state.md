# SatHop cleanup loop state

## Current status
- Working tree contains a focused frontend dashboard pipeline-summary helper extraction.
- `src/sathop/orchestrator/api/batch_readmodels.py` owns BatchSummary/GranuleRow assembly, state counts, ETA, and exhausted-object read queries.
- `src/sathop/orchestrator/api/batch_transitions.py` owns cancel/retry granule state rules.
- `src/sathop/orchestrator/api/worker_heartbeat.py` owns worker heartbeat version logging, queue/disk field application, revoke calculation, and one-shot signal consumption.
- `src/sathop/orchestrator/api/worker_leases.py` owns lease duration, worker in-flight counts, lease-size clamping, lease item assembly, pending-granule claiming, lease renewal, held-granule sampling, and force revoke mutation.
- `src/sathop/orchestrator/api/worker_transitions.py` owns worker-reported state progression, stage timing records, upload completion, and failure retry/blacklist mutation.
- `src/sathop/orchestrator/api/workers.py` now keeps worker routes, endpoint validation, commit/publish/log orchestration, delete-confirm, and operator actions.
- `src/sathop/orchestrator/api/admin_readmodels.py` owns admin overview, in-flight rows, stuck-granule rows, limit clamping, and stuck-age constants.
- `src/sathop/orchestrator/api/admin.py` now keeps admin routes, bundle GC mutation, settings info, commit/log/publish behavior, and route-level validation.
- `frontend/src/apiClient.ts` owns browser token storage, auth headers, 401 recovery, HTTP error parsing, and JSON fetch helpers.
- `frontend/src/api.ts` remains the public typed endpoint catalog and API facade used by pages/components.
- `frontend/src/features/batch/summary.ts` owns frontend batch count totals, completed/error/in-flight totals, and closed-batch detection.
- `frontend/src/features/batch/pipelineSummary.ts` owns dashboard/pipeline-health state-count rollups, pipeline totals, and ordered non-zero segments.
- `frontend/src/features/nodes/useNodeLifecycle.ts` owns shared worker/receiver enable, forget, restart mutations, cache updates, confirmations, and toast handling.
- `frontend/src/features/batch/types.ts` now also owns create-batch pure form transforms: credential payload/validity, env parsing, and dirty-draft checks.

## Completed this round
- Re-read `state.md`, confirmed the create-batch helper split was committed, and started from a clean working tree.
- Reviewed `Dashboard.vue`, `PipelineHealth.vue`, `StateBarChart.vue`, and `summary.ts` for repeated state-count presentation logic.
- Chose not to reuse `frontend/src/features/batch/summary.ts` for dashboard health because batch in-flight totals and dashboard pipeline-active totals have different semantics.
- Added `frontend/src/features/batch/pipelineSummary.ts` for dashboard/pipeline-health totals and ordered non-zero segment assembly.
- Updated `Dashboard.vue` and `PipelineHealth.vue` to share the new helper, removing duplicated bucket constants and local count reducers.
- Removed stale explanatory template comments while keeping the local stage color map in `PipelineHealth.vue` because it is presentation-only.

## Validation
- Frontend build/type-check: `npm --prefix frontend run build` passed.
- Ruff: `.venv/Scripts/ruff.exe check .` passed.
- Format: `.venv/Scripts/ruff.exe format . --check` passed.
- Full pytest was not rerun this round because changes were frontend-only state-count helper extraction.

## Key decisions
- Dashboard/pipeline-health rollups are a separate concept from batch-list in-flight math: pipeline active excludes pending/deleted/failed/blacklisted, while batch summary helpers follow batch completion semantics.
- `pipelineSummary.ts` owns semantic state buckets and ordered segment data; `PipelineHealth.vue` keeps only visual color mapping and layout.
- This helper also prevents Dashboard's top "进行中" stat from accidentally counting failed/blacklisted states.

## Next suggested priorities
1. Do a high-level docs/comment audit for stale architecture references after the recent helper splits.
2. Check whether `StateBarChart.vue` still earns its separate representation or can remain as-is because it is per-state chart presentation rather than rollup semantics.
3. If no clear cleanup remains, stop structural refactoring and report that the project is currently in a clean enough state.
