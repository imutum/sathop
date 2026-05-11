# SatHop cleanup loop state

## Current status
- Working tree contains a focused worker lease helper split.
- `src/sathop/orchestrator/api/batch_readmodels.py` owns BatchSummary/GranuleRow assembly, state counts, ETA, and exhausted-object read queries.
- `src/sathop/orchestrator/api/batch_transitions.py` owns cancel/retry granule state rules.
- `src/sathop/orchestrator/api/worker_heartbeat.py` owns worker heartbeat version logging, queue/disk field application, revoke calculation, and one-shot signal consumption.
- `src/sathop/orchestrator/api/worker_leases.py` owns lease duration, worker in-flight counts, lease-size clamping, lease item assembly, pending-granule claiming, lease renewal, held-granule sampling, and force revoke mutation.
- `src/sathop/orchestrator/api/worker_transitions.py` owns worker-reported state progression, stage timing records, upload completion, and failure retry/blacklist mutation.
- `src/sathop/orchestrator/api/workers.py` now keeps worker routes, endpoint validation, commit/publish/log orchestration, delete-confirm, and operator actions.

## Completed this round
- Re-read `state.md`, confirmed the previous worker transition split was committed and the working tree was clean.
- Re-opened `workers.py` and found a stable remaining boundary around leases and worker-held granule accounting.
- Added `worker_leases.py` and moved lease duration, in-flight counting, lease limit calculation, lease item assembly, pending-claim mutation, lease renewal, held sample, and force revoke mutation out of `workers.py`.
- Moved `renew_worker_leases` from `worker_heartbeat.py` to `worker_leases.py` because it is lease-domain behavior, not heartbeat-domain behavior.
- Updated tests to import lease helpers from the new module.

## Validation
- Focused worker lease tests: `.venv/Scripts/python.exe -m pytest tests/test_lease_backpressure.py tests/test_lease_renewal.py tests/test_node_lifecycle.py tests/test_batch_env.py tests/test_batch_credentials.py tests/test_worker_state.py` passed (`64 passed`).
- Full suite: `.venv/Scripts/python.exe -m pytest` passed (`430 passed`).
- Ruff: `.venv/Scripts/ruff.exe check .` passed.
- Format: `.venv/Scripts/ruff.exe format . --check` passed.

## Key decisions
- Lease behavior is cohesive enough to deserve its own helper module because it spans capacity clamps, storage-held accounting, lease DTO assembly, renewal, and revocation.
- `workers.py` still owns the process-wide `_LEASE_LOCK` and commit/log behavior; moving those would hide route-level concurrency and transaction semantics.
- `worker_heartbeat.py` no longer owns lease renewal; heartbeat merely calls the lease-domain helper.

## Next suggested priorities
1. Re-open `src/sathop/orchestrator/api/workers.py` and check whether the remaining operator actions should stay in one route file or move to an explicit ops module.
2. If no clear backend boundary remains, inspect `src/sathop/orchestrator/api/admin.py` for dashboard-vs-GC split opportunities.
3. If backend cleanup is low-value, inspect frontend `frontend/src/api.ts` for a domain split.
