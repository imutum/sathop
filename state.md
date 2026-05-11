# SatHop cleanup loop state

## Current status
- Working tree contains a focused frontend node-lifecycle helper split.
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
- `frontend/src/features/nodes/useNodeLifecycle.ts` owns shared worker/receiver enable, forget, restart mutations, cache updates, confirmations, and toast handling.

## Completed this round
- Re-read `state.md`, confirmed the batch-summary helper split was committed, and started from a clean working tree.
- Compared `WorkerCard.vue` and `ReceiverCard.vue` and found the duplicated concept is node lifecycle actions, not card presentation.
- Added `frontend/src/features/nodes/useNodeLifecycle.ts` to centralize enable/disable, forget, restart, optimistic cache updates, confirmation prompts, pending state, and toast messages.
- Updated `WorkerCard.vue` and `ReceiverCard.vue` to call the shared lifecycle helper while leaving worker-specific pause/revoke/cache-GC/capacity logic local to `WorkerCard.vue`.
- Kept `NodeLifecycleActions.vue` as the presentational button group; it still emits actions and does not own mutation behavior.

## Validation
- Frontend build/type-check: `npm --prefix frontend run build` passed.
- Full suite: `.venv/Scripts/python.exe -m pytest` passed (`430 passed`).
- Ruff: `.venv/Scripts/ruff.exe check .` passed.
- Format: `.venv/Scripts/ruff.exe format . --check` passed.

## Key decisions
- Shared node lifecycle behavior is a stable abstraction because workers and receivers use the same enable/forget/restart flow with only endpoint/query-key/message differences.
- Worker-only controls stay in `WorkerCard.vue`; moving pause/revoke/cache-GC/capacity into the lifecycle helper would blur the worker-vs-receiver boundary.
- The lifecycle helper exposes only the pending flag and action handlers needed by cards, not raw mutation objects.

## Next suggested priorities
1. Inspect `frontend/src/features/batch/components/CreateBatchModal.vue` and related create-batch helpers for form-state boundaries.
2. If create-batch cleanup is low-value, review dashboard/chart components for duplicated state-count presentation helpers.
3. If frontend cleanup is low-value, pause refactoring and do a high-level audit for stale docs/comments before making more structural changes.
