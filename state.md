# SatHop cleanup loop state

## Current status
- Working tree contains a focused docs/comment stale-reference cleanup.
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
- Re-read `state.md`, confirmed the dashboard pipeline-summary helper split was committed, and started from a clean working tree.
- Audited docs/comments for stale references after the recent backend/frontend helper splits.
- Updated `frontend/src/features/batch/schemas.ts` so the create-batch header schema comment points to `types.ts` helpers instead of stale modal-local validation names.
- Updated ignored local `CLAUDE.md` context references to current worker/receiver modules (`receiver/agent.py`, `worker/runtime.py`, `runtime_helpers.py::auth_for`) and included the `queued` state in the state-machine description.
- Confirmed no remaining matches for the stale references searched this round.

## Validation
- Stale-reference grep passed for the corrected worker/receiver/create-batch references.
- Ruff: `.venv/Scripts/ruff.exe check .` passed.
- Format: `.venv/Scripts/ruff.exe format . --check` passed.
- Frontend build and full pytest were not rerun because tracked changes are comments/state only.

## Key decisions
- Do not create new documentation; only correct stale references that would mislead future maintenance.
- `CLAUDE.md` is intentionally ignored by Git in this repo, so its local context fixes are kept out of the commit boundary.
- No code split is justified this round: `StateBarChart.vue` remains a per-state chart presentation component, distinct from pipeline rollup semantics.

## Next suggested priorities
1. Re-check whether any remaining frontend comments explain obvious template structure and can be deleted without losing intent.
2. If no clear cleanup remains, stop structural refactoring and report that the project is currently in a clean enough state.
3. Future structural work should be driven by a concrete duplication or stale boundary, not file size alone.
