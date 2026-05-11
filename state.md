# SatHop cleanup loop state

## Current status
- Working tree contains a focused frontend batch-summary helper split.
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

## Completed this round
- Re-read `state.md`, confirmed the frontend API transport split was committed, and started from a clean working tree.
- Reviewed `frontend/src/apiTypes.ts` and decided not to split it because it is a compact backend DTO mirror rather than mixed frontend view state.
- Inspected large Vue pages/components and found duplicated batch state-count rules in `Batches.vue` and `BatchDetail.vue`.
- Added `frontend/src/features/batch/summary.ts` as a pure helper for total, completed, error, in-flight, and closed-batch calculations.
- Updated `Batches.vue` and `BatchDetail.vue` to use the shared helper while leaving templates, routes, and query behavior unchanged.

## Validation
- Frontend build/type-check: `npm --prefix frontend run build` passed.
- Full suite: `.venv/Scripts/python.exe -m pytest` passed (`430 passed`).
- Ruff: `.venv/Scripts/ruff.exe check .` passed.
- Format: `.venv/Scripts/ruff.exe format . --check` passed.

## Key decisions
- `apiTypes.ts` stays whole for now: splitting by protocol object family would add lookup overhead without removing duplicated logic.
- Batch summary math is a real frontend domain boundary because it drives both list filtering/progress and detail actions.
- UI templates were not split this round because the duplication was in business rules, not presentation markup.

## Next suggested priorities
1. Inspect `frontend/src/features/nodes/components/WorkerCard.vue` and `ReceiverCard.vue` for a shared lifecycle mutation helper if duplication continues to matter.
2. If node-card cleanup is low-value, inspect `frontend/src/features/batch/components/CreateBatchModal.vue` and related create-batch helpers for form-state boundaries.
3. If frontend cleanup is low-value, review `src/sathop/cli/validate_bundle.py` only when adding new validator rules; do not split it preemptively.
