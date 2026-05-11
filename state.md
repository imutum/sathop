# SatHop cleanup loop state

## Current status
- Working tree contains a focused orchestrator commit/publish helper cleanup.
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
- Re-read `state.md`, confirmed the backend comment/docstring cleanup was committed, and started from a clean working tree.
- Scanned for concrete duplication/stale boundaries instead of continuing comment-only churn.
- Found route-level drift where bundles, shared upload, and receiver routes manually did `commit()` plus `publish({scope})` despite existing `commit_and_publish`.
- Replaced simple `commit()+publish(scope)` sequences in `bundles.py`, `shared.py`, and `receivers.py` with `commit_and_publish`.
- Preserved special cases: receiver failed-ack branch still commits without publishing, progress publishes a richer event payload, admin GC publishes only when work happened, and shared delete still unlinks the file after DB commit before publishing.

## Validation
- Related pytest subset passed: `tests/test_receiver_agent.py tests/test_receiver_pipeline.py tests/test_receiver_heartbeat_stats.py tests/test_node_lifecycle.py tests/test_restart_signal.py tests/test_shared.py tests/test_bundle_registry.py` (`97 passed`).
- Ruff: `.venv/Scripts/ruff.exe check .` passed.
- Format: `.venv/Scripts/ruff.exe format . --check` passed.

## Key decisions
- `commit_and_publish` should be the default for simple transaction + scope publication paths across orchestrator routes.
- Do not force custom publication paths into the helper when they carry richer payloads, conditional publish semantics, or filesystem ordering constraints.
- This is a boundary consistency cleanup, not a new abstraction.

## Next suggested priorities
1. Run one final high-level scan for concrete duplication or stale boundaries; if nothing clear appears, stop structural refactoring.
2. Avoid further comment-only churn unless a comment is actively misleading.
3. Future structural work should be driven by concrete duplication or stale boundary, not file size alone.
