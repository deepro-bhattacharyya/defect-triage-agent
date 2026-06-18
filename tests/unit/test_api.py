"""API-layer tests with the compiled graph replaced by a fake (no key, no network)."""

from fastapi.testclient import TestClient

from app.api import routes


def test_health():
    client = TestClient(routes.app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def _parse_sse(text):
    """Pull the JSON payloads out of an SSE response body."""
    import json

    events = []
    for frame in text.split("\n\n"):
        for line in frame.splitlines():
            if line.startswith("data:"):
                events.append(json.loads(line[5:].strip()))
    return events


def test_triage_streams_logs_then_result(monkeypatch):
    class FakeGraph:
        async def astream(self, state, stream_mode=None):
            # one node's breadcrumb, then the final cumulative state
            yield ("updates", {"intake_defect": {"triage_notes": ["[intake_defect] normalized"]}})
            yield ("updates", {"notify": {"triage_notes": ["[notify] done"]}})
            yield ("values", {**state, "status": "notified", "severity": "LOW",
                              "assigned_team": "Frontend",
                              "triage_notes": ["[intake_defect] normalized", "[notify] done"]})

    monkeypatch.setattr(routes, "_graph", FakeGraph())
    client = TestClient(routes.app)

    resp = client.post("/triage", json={"title": "Button misaligned", "description": "visual"})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")

    events = _parse_sse(resp.text)
    logs = [e for e in events if e["type"] == "log"]
    results = [e for e in events if e["type"] == "result"]

    assert [e["line"] for e in logs] == ["[intake_defect] normalized", "[notify] done"]
    assert logs[0]["node"] == "intake_defect"
    assert len(results) == 1
    assert results[0]["state"]["status"] == "notified"
    assert results[0]["state"]["severity"] == "LOW"
    assert results[0]["state"]["title"] == "Button misaligned"


def test_triage_streams_error_on_quota(monkeypatch):
    class BoomGraph:
        async def astream(self, state, stream_mode=None):
            raise RuntimeError("429 RESOURCE_EXHAUSTED quota")
            yield  # pragma: no cover (makes this an async generator)

    monkeypatch.setattr(routes, "_graph", BoomGraph())
    client = TestClient(routes.app)

    resp = client.post("/triage", json={"title": "x"})
    events = _parse_sse(resp.text)
    errors = [e for e in events if e["type"] == "error"]
    assert errors and "quota" in errors[0]["message"].lower()


def test_triage_requires_title():
    client = TestClient(routes.app)
    resp = client.post("/triage", json={"description": "no title"})
    assert resp.status_code == 422  # pydantic validation error
