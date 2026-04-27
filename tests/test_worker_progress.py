"""Worker-side progress HTTP server: nonce issue/revoke and forwarding."""

from __future__ import annotations

from fastapi.testclient import TestClient

from sathop.shared.protocol import ProgressEvent
from sathop.worker.progress import ProgressServer


class _FakeClient:
    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[tuple[str, ProgressEvent]] = []
        self._fail = fail

    async def report_progress(self, granule_id: str, event: ProgressEvent) -> None:
        if self._fail:
            raise RuntimeError("upstream down")
        self.calls.append((granule_id, event))


def _server(client=None) -> tuple[ProgressServer, TestClient]:
    fc = client or _FakeClient()
    srv = ProgressServer(fc, port=0)  # port unused: we drive via TestClient
    return srv, TestClient(srv.app)


def test_valid_nonce_forwards_event():
    srv, tc = _server()
    _, url = srv.issue("g-abc")
    nonce = url.rsplit("/", 1)[-1]

    r = tc.post(f"/progress/{nonce}", json={"step": "read", "pct": 20})
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert len(srv._client.calls) == 1  # type: ignore[attr-defined]
    gid, evt = srv._client.calls[0]  # type: ignore[attr-defined]
    assert gid == "g-abc"
    assert evt.step == "read"
    assert evt.pct == 20


def test_unknown_nonce_returns_404():
    srv, tc = _server()
    r = tc.post("/progress/made-up-nonce", json={"step": "read"})
    assert r.status_code == 404


def test_revoked_nonce_returns_404():
    srv, tc = _server()
    nonce, url = srv.issue("g-abc")
    srv.revoke(nonce)
    r = tc.post(f"/progress/{nonce}", json={"step": "read"})
    assert r.status_code == 404


def test_bad_json_returns_400():
    srv, tc = _server()
    _, url = srv.issue("g-abc")
    nonce = url.rsplit("/", 1)[-1]
    r = tc.post(
        f"/progress/{nonce}",
        content=b"not-json",
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 400


def test_missing_step_returns_422():
    srv, tc = _server()
    _, url = srv.issue("g-abc")
    nonce = url.rsplit("/", 1)[-1]
    r = tc.post(f"/progress/{nonce}", json={"pct": 10})
    assert r.status_code == 422


def test_upstream_failure_still_returns_200():
    """Bundle's progress report must NOT fail because orchestrator is briefly down —
    that would corrupt the bundle's own error handling."""
    srv, tc = _server(client=_FakeClient(fail=True))
    _, url = srv.issue("g-abc")
    nonce = url.rsplit("/", 1)[-1]
    r = tc.post(f"/progress/{nonce}", json={"step": "read"})
    assert r.status_code == 200


def test_multiple_granules_get_distinct_nonces():
    srv, _ = _server()
    n1, _ = srv.issue("g1")
    n2, _ = srv.issue("g2")
    assert n1 != n2
    assert srv._tokens[n1] == "g1"
    assert srv._tokens[n2] == "g2"
