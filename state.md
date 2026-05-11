# SatHop cleanup loop state

## Current status
- Working tree contains a focused worker-reported state transition split.
- `src/sathop/orchestrator/api/batch_readmodels.py` owns BatchSummary/GranuleRow assembly, state counts, ETA, and exhausted-object read queries.
- `src/sathop/orchestrator/api/batch_transitions.py` owns cancel/retry granule state rules.
- `src/sathop/orchestrator/api/worker_heartbeat.py` owns worker heartbeat version logging, queue/disk field application, lease renewal, revoke calculation, and one-shot signal consumption.
- `src/sathop/orchestrator/api/worker_transitions.py` owns worker-reported state progression, stage timing records, upload completion, and failure retry/blacklist mutation.
- `src/sathop/orchestrator/api/workers.py` now keeps worker routes, lease claiming, endpoint validation, delete-confirm, and operator actions.

## Completed this round
- Re-read `state.md`, confirmed the previous worker heartbeat split was committed and the working tree was clean.
- Compared lease item assembly vs. upload/failure/state transition helpers.
- Chose worker-reported transitions as the stronger boundary because it groups protocol state progression and timing mutation rules under one concept.
- Added `worker_transitions.py` and moved state predecessor/stage mapping, stage recording, upload completion mutation, and failure retry mutation out of `workers.py`.

## Validation
- Focused worker transition tests: `.venv/Scripts/python.exe -m pytest tests/test_worker_state.py tests/test_worker_endpoints.py tests/test_timing.py tests/test_lease_renewal.py` passed (`47 passed`).
- Full suite: `.venv/Scripts/python.exe -m pytest` passed (`430 passed`).
- Ruff: `.venv/Scripts/ruff.exe check .` passed.
- Format: `.venv/Scripts/ruff.exe format . --check` passed.

## Key decisions
- Lease item assembly remains in `workers.py` for now. It is small and directly tied to lease claiming; extracting it would mostly move JSON decoding without reducing enough concepts.
- Worker transition helpers receive `now` from the endpoint so timing boundaries remain explicit and testable.
- Endpoint-level validation stays in `workers.py` so HTTP error semantics remain easy to read next to each route.

## Next suggested priorities
1. Re-open `src/sathop/orchestrator/api/workers.py` and inspect lease/deletable/operator-action code for any remaining stable boundary.
2. If no clear backend boundary remains, inspect `src/sathop/orchestrator/api/admin.py` or frontend `frontend/src/api.ts` for the next highest-value cleanup.
3. Keep each loop iteration small and commit only cohesive refactors with full tests passing.
