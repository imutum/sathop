# TransitionResult is for DB mutations only

`shared/state_machine.py::apply()` returns a `TransitionResult` describing **what the orchestrator must write to the database** as a consequence of one `GranuleEvent`: target state, granule-row field updates, stage-timing rows to insert, granule-object rows to insert, and (for `DeleteConfirmed`) a marker to soft-delete sibling object rows. It also carries the SSE `publish_scope` so the runner can republish on commit.

It does **not** carry: log lines, metrics samples, Prometheus counters, audit-trail rows, webhook payloads, email triggers, or any other side-channel artefact. Those remain the handler's concern.

Why this line: the entire reason we split apply() out of the per-endpoint helpers is that the state-machine module deserves to be testable in isolation, with no FastAPI, no SQLite, no metrics registry, no logger. Every field added to `TransitionResult` is an additional concern the test surface has to evaluate, and an additional reason for apply() to grow imports. Once one side-effect leaks in, the next has the precedent. So: hold the line at "DB state mutations describing the new state of this granule." Anything else is a handler-level concern (the handler can call `eventlog.log(...)`, increment a metric, etc., after the runner returns).

If we ever want apply() to *describe* (not perform) a non-DB side-effect — say, "this transition warrants a high-priority event-log entry" — extend `TransitionResult` with a structured field for that intent (`log_entries: tuple[LogEntry, ...]`) and have the runner forward it. **Never** import a logger / metric registry / network client into `state_machine.py`.
