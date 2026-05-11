# SatHop cleanup loop state

## Current status
- Working tree contains a focused frontend API transport split.
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

## Completed this round
- Re-read `state.md`, confirmed the admin read-model split was committed, and started from a clean working tree.
- Re-checked `admin.py` bundle GC and decided not to split it because it is still a single operational route with commit/log/publish semantics.
- Inspected `frontend/src/api.ts` and found a stronger boundary between transport/auth behavior and typed endpoint catalog than between individual endpoint domains.
- Added `frontend/src/apiClient.ts` for token access, auth headers, 401 recovery, HTTP error parsing, and JSON request helpers.
- Kept `frontend/src/api.ts` as the stable public facade, re-exporting existing auth helpers so current imports do not churn.
- Updated `useLiveStream` to reuse the shared token getter instead of duplicating localStorage access.

## Validation
- Frontend build/type-check: `npm --prefix frontend run build` passed.
- Full suite: `.venv/Scripts/python.exe -m pytest` passed (`430 passed`).
- Ruff: `.venv/Scripts/ruff.exe check .` passed.
- Format: `.venv/Scripts/ruff.exe format . --check` passed.

## Key decisions
- Splitting `frontend/src/api.ts` by backend domain would force widespread import churn while preserving the same concept count; keeping one `API` facade is cheaper for callers.
- Transport/auth/error handling is a real boundary because it is shared by endpoint methods and SSE token usage, and can evolve without touching endpoint definitions.
- CLI modules are currently small enough; their duplicated URL/token parsing already goes through shared config helpers, so further splitting would be low value.

## Next suggested priorities
1. Re-open `frontend/src/apiTypes.ts` and check whether protocol type definitions have a clearer split from frontend-only view types.
2. If frontend type splitting is low-value, inspect large Vue pages/components for extractable presentation helpers without changing behavior.
3. If UI cleanup is low-value, review `src/sathop/cli/validate_bundle.py` for validator rule grouping only if new bundle checks are being added.
