# Stage vocabulary: orchestrator names ≠ worker names, on purpose

Two naming systems co-exist for the same six pipeline sections:

| Pipeline section            | Orchestrator (timing)   | Worker (counter)               |
|-----------------------------|-------------------------|--------------------------------|
| Granule waiting to download | `download_wait`         | `pending_download`             |
| Granule downloading         | `download`              | `downloading`                  |
| Granule waiting to process  | `process_wait`          | `pending_processing`           |
| Granule processing          | `process`               | `processing`                   |
| Granule waiting to upload   | `upload_wait`           | `pending_upload`               |
| Granule uploading           | `upload`                | `uploading`                    |

The orchestrator names are authoritative for the **Stage** concept (one timing row per state-transition; closes_stage in `STATE_TABLE`). The worker names live in `worker/stages.py::StageName` and propagate to wire-format `WorkerHeartbeat.queue_*` fields and DB columns `workers.queue_*`.

The two vocabularies were diverged early and have not been unified because they encode different things:

- The orchestrator's `<verb>_wait` / `<verb>` pair labels a **time interval**. `download_wait` is the elapsed time between QUEUED and DOWNLOADING; `download` is between DOWNLOADING and DOWNLOADED. The name describes the section as a duration ("wait, then download").
- The worker's `pending_<verb>` / `<verb>ing` pair labels a **counter**. `pending_download` is "this many handlers are waiting on the download semaphore right now"; `downloading` is "this many handlers are actively transferring bytes". The name describes the count's current meaning as a participle.

Aligning them would force one side to use a name that reads wrong:

- Renaming worker → orchestrator gives `queue_download_wait: int`. The field is a count, but the name reads like a duration. Operators reading the heartbeat payload would assume seconds.
- Renaming orchestrator → worker gives a `pending_download` stage row with started_at / finished_at columns. The name reads like a queue depth, but the row is a duration. Charting tools and Prometheus queries would mis-label durations as queue snapshots.

The rename would also touch the wire format, the DB schema (column rename migrations), the frontend (apiTypes.ts + UI labels), the Prometheus metric series, and several years of saved Grafana dashboards. Real cost; cosmetic gain.

So both names stay. The mapping is documented in CONTEXT.md under **Worker stage counter** and reproduced as the table above. When working in either subsystem, prefer that subsystem's vocabulary; when crossing the boundary (e.g. when a heartbeat handler builds a granule_stage_timings row from a worker count), the translation is explicit and the mismatch is obvious by spelling.
