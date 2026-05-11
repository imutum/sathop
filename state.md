# SatHop cleanup loop state

## Current status
- Working tree contains a state-only cleanup-loop closure record.
- The project is currently clean enough: no new concrete duplication, stale boundary, or naming drift surfaced in the final cross-check.
- `src/sathop/orchestrator/pubsub.py` owns event publishing, event logging, and `commit_and_publish` transaction/scope publication helper.
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
- Re-read `state.md`, confirmed the onboarding token-boundary cleanup was committed, and started from a clean working tree.
- Performed a state-only final cross-check for duplication/boundary drift across token access, commit/publish paths, state-count helpers, feature imports, and legacy/compat references.
- Confirmed direct token storage access is limited to `apiClient.ts` and login rollback/removal in `Login.vue`.
- Confirmed remaining manual commit/publish paths are intentional special cases: background tasks, admin GC conditional publish, progress rich payload, receiver failed-ack no-publish branch, and shared delete's DB-then-filesystem ordering.
- Confirmed state-count helpers are intentionally split by semantics: batch summary math, dashboard pipeline rollups, and per-state chart presentation.

## Validation
- Git status was clean at the start of the round.
- Cross-check grep found no new concrete cleanup target.
- No build/test rerun this round because no source code changed.

## Key decisions
- Stop structural refactoring now; continuing to search for cleanup would likely create churn rather than reduce maintenance cost.
- Treat the current module boundaries as the baseline unless a future feature, bug, or test failure exposes a concrete duplication or stale abstraction.
- Comment-only changes should stop unless a comment is actively misleading.

## Next suggested priorities
1. Move on to feature, bug, release, or test work; do not continue cleanup-only rounds by default.
2. If future cleanup is requested, require a concrete trigger: duplicated logic, stale boundary, failing test, or confusing ownership.
3. Before any release, run the normal full validation suite rather than more structural reshuffling.
