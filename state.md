# SatHop cleanup loop state

## Current status
- Working tree contains a focused admin read-model helper split.
- `src/sathop/orchestrator/api/batch_readmodels.py` owns BatchSummary/GranuleRow assembly, state counts, ETA, and exhausted-object read queries.
- `src/sathop/orchestrator/api/batch_transitions.py` owns cancel/retry granule state rules.
- `src/sathop/orchestrator/api/worker_heartbeat.py` owns worker heartbeat version logging, queue/disk field application, revoke calculation, and one-shot signal consumption.
- `src/sathop/orchestrator/api/worker_leases.py` owns lease duration, worker in-flight counts, lease-size clamping, lease item assembly, pending-granule claiming, lease renewal, held-granule sampling, and force revoke mutation.
- `src/sathop/orchestrator/api/worker_transitions.py` owns worker-reported state progression, stage timing records, upload completion, and failure retry/blacklist mutation.
- `src/sathop/orchestrator/api/workers.py` now keeps worker routes, endpoint validation, commit/publish/log orchestration, delete-confirm, and operator actions.
- `src/sathop/orchestrator/api/admin_readmodels.py` owns admin overview, in-flight rows, stuck-granule rows, limit clamping, and stuck-age constants.
- `src/sathop/orchestrator/api/admin.py` now keeps admin routes, bundle GC mutation, settings info, commit/log/publish behavior, and route-level validation.

## Completed this round
- Re-read `state.md` and confirmed the previous worker lease helper split was committed with a clean working tree.
- Re-opened `workers.py` and judged remaining operator actions too thin to split without turning the refactor into route-name shuffling.
- Split admin dashboard/stuck/in-flight read-model assembly into `admin_readmodels.py`.
- Kept bundle GC and settings info in `admin.py` because they are route-level operational actions, not dashboard read models.
- Preserved the public admin endpoint behavior and existing `STUCK_AGE_HOURS` import path through `admin.py`.

## Validation
- Focused admin tests: `.venv/Scripts/python.exe -m pytest tests/test_admin_stuck.py tests/test_admin_gc.py` passed (`11 passed`).
- Full suite: `.venv/Scripts/python.exe -m pytest` passed (`430 passed`).
- Ruff: `.venv/Scripts/ruff.exe check .` passed.
- Format: `.venv/Scripts/ruff.exe format . --check` passed.

## Key decisions
- `workers.py` should not be split further right now: the remaining operator endpoints are already thin, and moving them would add a module boundary without removing a concept.
- Admin dashboard/stuck/in-flight queries are a stable read-model boundary because they share row shaping, stuck-age semantics, non-terminal filtering, and query-only behavior.
- Bundle GC stays in `admin.py` because it performs deletion, blob unlinking, logging, commit, and publish orchestration in one operational route.

## Next suggested priorities
1. Re-open `src/sathop/orchestrator/api/admin.py` after this commit and check whether bundle GC deserves a tiny domain helper; only split if deletion/blob-unlink logic grows beyond the current single route.
2. Inspect `frontend/src/api.ts` for a domain split if backend API files now look sufficiently clean.
3. If frontend API splitting is low-value, review CLI modules under `src/sathop/cli/` for duplicated request/validation patterns.
