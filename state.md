# SatHop cleanup loop state

## Current status
- Working tree contains a focused backend comment/docstring cleanup.
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
- Re-read `state.md`, confirmed the frontend layout comment cleanup was committed, and started from a clean working tree.
- Audited backend Python comments/docstrings for WHAT-only noise versus useful WHY/constraint notes.
- Removed pure title docstrings from `orchestrator/background.py`, `orchestrator/pubsub.py`, `receiver/agent.py`, `receiver/runtime.py`, and `worker/main.py`.
- Removed obvious helper docstrings from `shared/http.py` where function names and type signatures already say the same thing.
- Preserved comments/docstrings that explain concurrency races, backwards compatibility, retention ordering, config precedence, and protocol constraints.

## Validation
- Ruff: `.venv/Scripts/ruff.exe check .` passed.
- Format: `.venv/Scripts/ruff.exe format . --check` passed.
- Full pytest was not rerun because tracked code changes only remove comments/docstrings.

## Key decisions
- Keep WHY comments: race guards, compatibility notes, retention/cleanup ordering, and operational failure semantics are worth the lines.
- Do not mechanically remove every module docstring; only remove cases that merely repeat the filename or function name.
- No backend structural split is justified by this audit alone.

## Next suggested priorities
1. If another cleanup round is needed, do a final high-level scan for concrete duplication or stale boundaries rather than continuing comment-only churn.
2. If no clear cleanup remains, stop structural refactoring and report that the project is currently in a clean enough state.
3. Future structural work should be driven by a concrete duplication or stale boundary, not file size alone.
