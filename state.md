# SatHop cleanup loop state

## Current status
- Working tree contains a focused `batches.py` read-model split.
- `src/sathop/orchestrator/api/batch_readmodels.py` owns BatchSummary/GranuleRow assembly, state counts, ETA, and exhausted-object read queries.
- `src/sathop/orchestrator/api/batches.py` now keeps route handlers and write-side mutations.

## Completed this round
- Established this state file because none existed.
- Reviewed the existing uncommitted batch read-model split against the cleanup goal.
- Verified the split is a long-term boundary improvement rather than a local patch: read-side query/model assembly is separated from write endpoints without changing behavior.
- Confirmed tests had already been updated to import ETA/count helpers from the new read-model module.

## Validation
- Batch tests: `.venv/Scripts/python.exe -m pytest tests/test_batch_admin.py tests/test_batch_env.py tests/test_batch_granules.py tests/test_batch_credentials.py tests/test_batch_delete.py tests/test_batch_summary_exhausted.py tests/test_batch_eta.py tests/test_batch_create_prefix.py` passed (`52 passed`).
- Full suite: `.venv/Scripts/python.exe -m pytest` passed (`430 passed`).
- Ruff: `.venv/Scripts/ruff.exe check .` passed.
- Format: `.venv/Scripts/ruff.exe format . --check` passed.

## Key decisions
- Do not split `batches.py` write operations yet. Cancel/retry/delete share transaction and state-transition semantics, so moving them before a clearer service boundary would add indirection without enough payoff.
- Avoid compatibility re-exports for old private helper names; tests now depend on the new module boundary directly.

## Next suggested priorities
1. Re-open `batches.py` and look specifically for a clean write-side state-transition helper/service boundary.
2. If that is not clearly simpler, inspect `orchestrator/api/workers.py` for lease/heartbeat read-write separation.
3. Keep each loop iteration small and commit only cohesive refactors with full tests passing.
