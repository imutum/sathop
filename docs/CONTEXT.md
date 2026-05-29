# SatHop

A distributed remote-sensing data pipeline: workers download products, run user-supplied processing scripts, and ship outputs to receivers. The orchestrator owns all authoritative state.

## Language

### Core domain

**Granule**:
The unit of work — one remote-sensing product (a set of input files identified by URL + checksum) that flows through the full pipeline.
_Avoid_: job, task, product, item

**Batch**:
A user-submitted group of **Granules** that share execution config and credentials.
_Avoid_: campaign, run

**Worker**:
A long-running process that leases **Granules**, downloads inputs, runs the **Bundle**, and uploads outputs to its **Storage**.
_Avoid_: node, agent (overloaded — see below)

**Receiver**:
A pull client that fetches uploaded objects from a **Worker**'s **Storage** and acknowledges them.
_Avoid_: consumer, subscriber

**Orchestrator**:
The single FastAPI + SQLite process that schedules **Granules**, owns the state DB, and exposes the Web UI.
_Avoid_: controller, master, server

### Pipeline mechanics

**Lease**:
A 30-minute exclusive reservation of a **Granule** by a specific **Worker**. Expires passively (on next `/lease` call) or actively (background sweeper).
_Avoid_: claim (overloaded — see **ClaimByLease** event), assignment, reservation

**Bundle**:
A user-supplied, versioned script package (zip) referenced by `orch:<name>@<version>`. Each **Bundle** version gets its own isolated venv on the **Worker**.
_Avoid_: package, plugin, script

**Shared file**:
**Orchestrator**-hosted auxiliary data (masks, DEMs, LUTs) declared in a **Bundle**'s manifest, synced to each **Worker** lazily on lease.
_Avoid_: asset, resource

**Stage**:
A named timing checkpoint along the **Granule**'s pipeline (`download_wait`, `download`, `process_wait`, `process`, `upload_wait`, `upload`). Each closes at a specific state-transition; the row goes into `granule_stage_timings` so the UI can chart wall-clock durations. Authoritative names live in `STATE_TABLE[<state>].closes_stage`.
_Avoid_: step, phase

**Worker stage counter**:
The worker-side counterpart to **Stage** — a six-bucket count of "how many granule handlers are in this section of the pipeline right now". Each name corresponds to a **Stage**, with two differences:
  1. Suffix conventions: `_wait` (orchestrator, duration) ↔ `pending_` prefix (worker, count); active-stage names match exactly (`download` ↔ `downloading` is the one true rename — historical, kept stable). The full mapping lives in [ADR-0004](adr/0004-stage-vocabulary-dual-names.md).
  2. Wire-format DB column names mirror the worker names (`queue_pending_download`, `queue_downloading`, …) because that's where the count is reported.

Both vocabularies are deliberate and stable: rename ADR-0004 explains why we did not collapse them into one.

**State**:
One of 11 values in the **Granule**'s lifecycle (pending → queued → downloading → … → uploaded → acked → deleted, plus failed/blacklisted). Declared in `shared/state_machine.py::STATE_TABLE`.
_Avoid_: status, phase

**Reap**:
Hard-delete a **Granule** and every row that references it (objects, stage timings), children before parent. Distinct from the soft `deleted` **State** / `DeleteConfirmed` **GranuleEvent**, which mark a Granule's outputs gone but keep the row alive for the UI — reaping removes the row itself. The single owner of the child-table set and delete order is `orchestrator/reaping.py::reap_granules`, called by both the batch-delete handler and the retention sweeper.
_Avoid_: purge, cascade, cleanup

### State machine (this design)

**GranuleEvent**:
A discriminated-union DTO representing a single trigger to the state machine. Worker-emitted events (`DownloadStarted`, `DownloadFinished`, `ProcessStarted`, `ProcessFinished`, `UploadStarted`, `UploadCompleted`, `ProcessingFailed`, `DeleteConfirmed`) ride the wire as the `GranuleEvent` discriminated union; orchestrator-internal triggers (`ClaimByLease`, `RevokedByOperator`, `CancelGranule`, `RetryGranule`, `ObjectAcked`) are separate Pydantic classes that `apply()` accepts but the wire endpoint refuses to deserialise. **One documented carve-out**: the lease sweeper (`background.py::sweep_expired_leases`) keeps a bulk UPDATE with a re-asserted WHERE predicate to remain race-safe against concurrent `/heartbeat::renew_worker_leases`; it does not flow through `apply()`.
_Avoid_: command (we don't distinguish events from commands here), message, signal

**Transition**:
The act of moving a **Granule** from one **State** to another by applying a **GranuleEvent**. Modeled as a pure function `state_machine.apply(snapshot, event, …) → TransitionResult`.

**TransitionResult**:
The pure-function output that describes everything that must happen as a result of one **Transition**: target **State**, field updates on the **Granule** row, child rows to insert (stage timings, uploaded objects), and the SSE scope to publish. Strictly scoped to DB state mutations — never logs, metrics, or out-of-band side effects (see ADR-0002).

**Runner**:
The thin orchestrator-side adapter that translates a **TransitionResult** into SQLAlchemy mutations on an `AsyncSession`. The single seam where the pure state machine meets the ORM.
_Avoid_: applier, executor, reducer

### Infrastructure

**Storage**:
Per-**Worker** object store for processed outputs. Two backends: `LocalStorage` (HTTP static server) and `MinioStorage` (S3-API). Env-selected.

**Downloader**:
**Worker**-side fetcher for input files. Two backends: `HttpDownloader` (httpx) and `Aria2Downloader` (aria2c JSON-RPC). Env-selected.

**Credentials**:
Named auth records (`basic` or `bearer`) attached to a **Batch** and propagated verbatim in every **Lease** item. Worker's **Downloader** translates them to backend-native auth.

## Relationships

- A **Batch** contains one or more **Granules**.
- A **Granule** is leased by exactly one **Worker** at a time (or zero, when `pending`).
- A **Worker** runs exactly one **Bundle** version per leased **Granule**.
- A **GranuleEvent** triggers exactly one **Transition**, producing exactly one **TransitionResult**.
- The **Runner** applies a **TransitionResult** to exactly one `AsyncSession`.
- A **Receiver** pulls **Granule** outputs from one or more **Workers**, then emits `ObjectAcked` per **Granule**.

## Flagged ambiguities

- "agent" was used in code for both "the long-running worker/receiver process lifecycle" (`shared/agent_lifecycle.py`) and the worker/receiver HTTP clients to orchestrator (`worker/agent.py`, `receiver/agent.py`). The former is a process-lifecycle concept; the latter is a thin client. Resolved by convention: **Worker** / **Receiver** for the process; `*Client` (`OrchestratorClient`) for the HTTP wrapper. The `agent.py` filenames remain for now (historical).
- "claim" — used both for the **Lease** acquisition step (`claim_pending_granules`) and as the **GranuleEvent** name (`ClaimByLease`). Acceptable overlap since `ClaimByLease` is precisely the event the function emits.
- "event" — distinct from the SSE pubsub channel scope (`pubsub.publish({"scope": "batches"})`). The former is a state-machine input; the latter is a UI refresh signal. Don't conflate.

## Example dialogue

> **Dev:** When a **Worker** finishes downloading inputs, what does it send on the wire?
> **Architect:** It POSTs `/workers/events` with a `DownloadFinished` **GranuleEvent**. The orchestrator's handler authenticates the **Lease** ownership, then calls `state_machine.apply(snapshot, event, …)`. The returned **TransitionResult** says "new state = downloaded, insert one stage row for `download`, publish scope=batches." The **Runner** applies that to the session, the orchestrator commits.
> **Dev:** What if the **Worker** sends `DownloadFinished` but the state is already `processed` because a stale duplicate?
> **Architect:** `apply()` raises `StateConflict`. The handler returns 409. Worker swallows it — see the existing comment in `workers.py::failure`.
