"""Worker-side progress HTTP server: nonce issue/revoke and forwarding."""

from __future__ import annotations

from fastapi.testclient import TestClient

from sathop.shared.protocol import ProgressEvent
from sathop.worker.progress import ProgressServer


class _Sink:
    """Stand-in for ProgressBuffer.enqueue_event — a non-blocking callable that
    collects forwarded checkpoints (or raises, to prove the server swallows it)."""

    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[tuple[str, ProgressEvent]] = []
        self._fail = fail

    def __call__(self, granule_id: str, event: ProgressEvent) -> None:
        if self._fail:
            raise RuntimeError("buffer error")
        self.calls.append((granule_id, event))


def _server(sink=None) -> tuple[ProgressServer, TestClient]:
    s = sink or _Sink()
    srv = ProgressServer(s, port=0)  # port unused: we drive via TestClient
    return srv, TestClient(srv.app)


def test_valid_nonce_forwards_event():
    srv, tc = _server()
    _, url = srv.issue("g-abc", "b1")
    nonce = url.rsplit("/", 1)[-1]

    r = tc.post(f"/progress/{nonce}", json={"step": "read", "pct": 20})
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert len(srv._sink.calls) == 1  # type: ignore[attr-defined]
    gid, evt = srv._sink.calls[0]  # type: ignore[attr-defined]
    assert gid == "g-abc"
    assert evt.step == "read"
    assert evt.pct == 20


def test_unknown_nonce_returns_404():
    srv, tc = _server()
    r = tc.post("/progress/made-up-nonce", json={"step": "read"})
    assert r.status_code == 404


def test_revoked_nonce_returns_404():
    srv, tc = _server()
    nonce, url = srv.issue("g-abc", "b1")
    srv.revoke(nonce)
    r = tc.post(f"/progress/{nonce}", json={"step": "read"})
    assert r.status_code == 404


def test_bad_json_returns_400():
    srv, tc = _server()
    _, url = srv.issue("g-abc", "b1")
    nonce = url.rsplit("/", 1)[-1]
    r = tc.post(
        f"/progress/{nonce}",
        content=b"not-json",
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 400


def test_missing_step_returns_422():
    srv, tc = _server()
    _, url = srv.issue("g-abc", "b1")
    nonce = url.rsplit("/", 1)[-1]
    r = tc.post(f"/progress/{nonce}", json={"pct": 10})
    assert r.status_code == 422


def test_sink_failure_still_returns_200():
    """Bundle's progress report must NOT fail because the sink raised (e.g. the
    buffer is briefly unhappy) — that would corrupt the bundle's own error
    handling. The server swallows sink errors in `forward()`."""
    srv, tc = _server(sink=_Sink(fail=True))
    _, url = srv.issue("g-abc", "b1")
    nonce = url.rsplit("/", 1)[-1]
    r = tc.post(f"/progress/{nonce}", json={"step": "read"})
    assert r.status_code == 200


def test_disabled_server_drops_progress_but_still_200():
    """Fast detail mode: _enabled=False makes forward() a no-op, so neither the
    bundle self-report nor the download callback reaches the sink — yet the
    bundle's POST still gets a 200 (it must never break on progress plumbing)."""
    sink = _Sink()
    srv, tc = _server(sink=sink)
    srv._enabled = False
    _, url = srv.issue("g-abc", "b1")
    nonce = url.rsplit("/", 1)[-1]
    r = tc.post(f"/progress/{nonce}", json={"step": "read", "pct": 50})
    assert r.status_code == 200
    assert sink.calls == []  # suppressed


def test_multiple_granules_get_distinct_nonces():
    srv, _ = _server()
    n1, _ = srv.issue("g1", "b1")
    n2, _ = srv.issue("g2", "b1")
    assert n1 != n2
    assert srv._tokens[n1] == ("g1", "b1")
    assert srv._tokens[n2] == ("g2", "b1")
