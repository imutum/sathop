# SatHop cleanup loop state

## Current status
- Working tree contains a focused frontend create-batch helper extraction.
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
- `frontend/src/features/batch/types.ts` now also owns create-batch pure form transforms: credential payload/validity, env parsing, and dirty-draft checks.

## Completed this round
- Re-read `state.md`, confirmed the node-lifecycle helper split was committed, and started from a clean working tree.
- Inspected `CreateBatchModal.vue`, `CreateBatchCsvModal.vue`, `CreateBatchGranuleTable.vue`, `CreateBatchCredentials.vue`, `types.ts`, and `schemas.ts`.
- Chose not to split CSV or table components further because those boundaries already exist and are cohesive.
- Moved create-batch pure form calculations from `CreateBatchModal.vue` into `frontend/src/features/batch/types.ts`: `parseExecutionEnv`, credential payload/validity, row dirty detection, and credential dirty detection.
- Kept the modal responsible for query wiring, mutation, credential persistence side effects, and template composition.

## Validation
- Frontend build/type-check: `npm --prefix frontend run build` passed.
- Full suite: `.venv/Scripts/python.exe -m pytest` passed (`430 passed`).
- Ruff: `.venv/Scripts/ruff.exe check .` passed.
- Format: `.venv/Scripts/ruff.exe format . --check` passed.

## Key decisions
- `CreateBatchModal.vue` should keep orchestration and side effects, but not own pure data transforms that are part of create-batch form semantics.
- `types.ts` remains the correct home for these helpers because it already owns create-batch row and credential transformations.
- CSV/table/credential components are already appropriately split; moving their internals would add indirection without reducing concepts.

## Next suggested priorities
1. Review dashboard/chart components for duplicated state-count presentation helpers.
2. If dashboard cleanup is low-value, do a high-level docs/comment audit for stale architecture references after the recent helper splits.
3. If no clear cleanup remains, stop structural refactoring and report that the project is currently in a clean enough state.
