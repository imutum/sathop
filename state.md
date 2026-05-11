# SatHop cleanup loop state

## Current status
- Working tree contains a focused frontend onboarding token-boundary cleanup.
- `src/sathop/orchestrator/pubsub.py` owns event publishing, event logging, and `commit_and_publish` transaction/scope publication helper.
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
- `frontend/src/features/batch/types.ts` owns create-batch pure form transforms: credential payload/validity, env parsing, and dirty-draft checks.

## Completed this round
- Re-read `state.md`, confirmed the orchestrator commit/publish helper cleanup was committed, and started from a clean working tree.
- Ran a final high-level scan for real duplication and stale boundaries across orchestrator routes, frontend API/token access, state-count helpers, confirm flows, and legacy/compat references.
- Found one small frontend boundary drift: onboarding modals still read `localStorage` directly for the current token after token access moved into `apiClient.ts`.
- Updated `OnboardWorkerModal.vue` and `OnboardReceiverModal.vue` to use `getToken()` from `apiClient.ts`.
- Confirmed remaining direct token storage access is limited to `apiClient.ts` and `Login.vue`, where login rollback/removal owns the boundary.

## Validation
- Frontend build/type-check: `npm --prefix frontend run build` passed.
- Ruff: `.venv/Scripts/ruff.exe check .` passed.
- Format: `.venv/Scripts/ruff.exe format . --check` passed.

## Key decisions
- `apiClient.ts` is the browser token boundary; components that only need the current token should call `getToken()` instead of reaching into storage.
- `Login.vue` may still read/remove `localStorage` directly because it owns rollback and clearing behavior during login probing.
- No further concrete structural cleanup surfaced in the final scan.

## Next suggested priorities
1. Stop structural refactoring unless a new concrete duplication, stale boundary, or bug appears.
2. If continuing work, shift from cleanup to feature/bug/test priorities rather than more churn.
3. Future structural work should be driven by concrete duplication or stale boundary, not file size alone.
