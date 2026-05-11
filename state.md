# SatHop cleanup loop state

## Current status
- Working tree contains a focused worker heartbeat helper split.
- `src/sathop/orchestrator/api/batch_readmodels.py` owns BatchSummary/GranuleRow assembly, state counts, ETA, and exhausted-object read queries.
- `src/sathop/orchestrator/api/batch_transitions.py` owns cancel/retry granule state rules.
- `src/sathop/orchestrator/api/worker_heartbeat.py` owns worker heartbeat version logging, queue/disk field application, lease renewal, revoke calculation, and one-shot signal consumption.
- `src/sathop/orchestrator/api/workers.py` now keeps worker routes, lease claiming, upload/failure mutation, delete-confirm, and operator actions.

## Completed this round
- Re-read `state.md`, confirmed the previous batch transition split was committed and the working tree was clean.
- Re-assessed batch creation and deliberately skipped splitting it: validation, bundle lookup, shared-file checks, DB creation, logs, and response are tightly coupled to the create endpoint.
- Split worker heartbeat helpers out of `workers.py` into `worker_heartbeat.py`.
- Updated `tests/test_worker_state.py` to import `renew_worker_leases` from the new helper module instead of the route file.

## Validation
- Focused worker API tests: `.venv/Scripts/python.exe -m pytest tests/test_worker_state.py tests/test_version_flap.py tests/test_restart_signal.py tests/test_lease_renewal.py tests/test_worker_endpoints.py` passed (`46 passed`).
- Full suite: `.venv/Scripts/python.exe -m pytest` passed (`430 passed`).
- Ruff: `.venv/Scripts/ruff.exe check .` passed.
- Format: `.venv/Scripts/ruff.exe format . --check` passed.

## Key decisions
- Batch creation stays in `batches.py` for now because splitting it would mostly move HTTP/session-specific orchestration into another file without reducing concepts.
- Worker heartbeat is a stable boundary: it has its own DTO, repeated helper responsibilities, and separate tests around renewal, version flaps, restart, GC, and revoke behavior.
- Keep lease claiming in `workers.py` for now. It depends on the route-level lock, worker enablement, queue backpressure, DB mutation, event logging, and publish behavior.

## Next suggested priorities
1. Inspect `src/sathop/orchestrator/api/workers.py` for another stable boundary around lease item assembly and batch credential/env decoding.
2. If lease item assembly is too small, inspect upload/failure state mutation helpers for a clean transition module.
3. Keep each loop iteration small and commit only cohesive refactors with full tests passing.
