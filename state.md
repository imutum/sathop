# SatHop cleanup loop state

## Current status
- Working tree contains a focused frontend layout comment cleanup.
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
- Re-read `state.md`, confirmed the docs/comment stale-reference cleanup was committed, and started from a clean working tree.
- Audited frontend comments for noise that only repeats visible template structure.
- Removed redundant section-marker and structure-summary comments from `frontend/src/layouts/AppLayout.vue`.
- Kept the route-change drawer-closing comment because it explains the event source shared by link clicks, browser navigation, and programmatic navigation.
- Confirmed the diff is comment-only and does not affect UI behavior.

## Validation
- Ruff: `.venv/Scripts/ruff.exe check .` passed.
- Format: `.venv/Scripts/ruff.exe format . --check` passed.
- Frontend build and full pytest were not rerun because tracked changes are comment/state only.

## Key decisions
- Comments should explain non-obvious behavior or constraints, not label sections the template already makes visible.
- `AppLayout.vue` is cohesive enough as the single shell layout; extracting sidebar/mobile/header subcomponents would add indirection without a current duplication or reuse pressure.
- No broader frontend refactor is justified from this audit alone.

## Next suggested priorities
1. If another cleanup round is needed, scan backend comments/docstrings with the same standard: preserve WHY, remove WHAT.
2. If no clear cleanup remains, stop structural refactoring and report that the project is currently in a clean enough state.
3. Future structural work should be driven by a concrete duplication or stale boundary, not file size alone.
