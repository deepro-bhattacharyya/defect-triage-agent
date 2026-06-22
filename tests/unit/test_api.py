"""API-layer tests with the compiled graph replaced by a fake (no key, no network)."""

from fastapi.testclient import TestClient

from app.api import routes


def test_health():
    client = TestClient(routes.app)
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "llm_available" in body


def test_jira_status_endpoint(monkeypatch):
    monkeypatch.setattr(routes.jira_tool, "get_jira_status", lambda: {"connected": True})
    client = TestClient(routes.app)
    resp = client.get("/jira/status")
    assert resp.status_code == 200
    assert resp.json() == {"connected": True}


def test_jira_issue_endpoint_ok(monkeypatch):
    defect = {"defect_id": "SCRUM-42", "title": "Promo 500", "description": "d",
              "environment": "production", "reporter": "Jane", "stack_trace": "",
              "image_attachments": []}
    monkeypatch.setattr(routes.jira_tool, "get_issue", lambda key: {"ok": True, "defect": defect})
    client = TestClient(routes.app)
    resp = client.get("/jira/issue/SCRUM-42")
    assert resp.status_code == 200
    assert resp.json()["defect_id"] == "SCRUM-42"
    assert resp.json()["title"] == "Promo 500"


def test_jira_issue_endpoint_404(monkeypatch):
    monkeypatch.setattr(routes.jira_tool, "get_issue",
                        lambda key: {"ok": False, "reason": "Issue NOPE-1 not found in Jira"})
    client = TestClient(routes.app)
    resp = client.get("/jira/issue/NOPE-1")
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


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
        async def astream(self, state, config=None, stream_mode=None):
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


def test_triage_streams_warning_event(monkeypatch):
    class FakeGraph:
        async def astream(self, state, config=None, stream_mode=None):
            yield ("updates", {"notify": {
                "triage_notes": ["[notify] Jira update FAILED"],
                "warnings": ["Jira rejected the request — check credentials / permissions."],
            }})
            yield ("values", {**state, "status": "notified"})

    monkeypatch.setattr(routes, "_graph", FakeGraph())
    client = TestClient(routes.app)
    resp = client.post("/triage", json={"title": "x"})
    events = _parse_sse(resp.text)

    warnings = [e for e in events if e["type"] == "warning"]
    assert warnings and "credentials" in warnings[0]["message"].lower()
    assert any(e["type"] == "result" for e in events)  # triage still completed


def test_triage_streams_error_on_quota(monkeypatch):
    class BoomGraph:
        async def astream(self, state, config=None, stream_mode=None):
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


class _Interrupt:
    def __init__(self, value):
        self.value = value


def test_triage_emits_assignment_required(monkeypatch):
    class FakeGraph:
        async def astream(self, state, config=None, stream_mode=None):
            yield ("updates", {"analyze_defect": {"triage_notes": ["[analyze_defect] x"]}})
            yield ("updates", {"__interrupt__": (
                _Interrupt({"team": "Payments", "candidates": ["a@x.com", "b@x.com"]}),
            )})

    monkeypatch.setattr(routes, "_graph", FakeGraph())
    client = TestClient(routes.app)
    resp = client.post("/triage", json={"title": "Payment down"})
    events = _parse_sse(resp.text)

    ar = [e for e in events if e["type"] == "assignment_required"]
    assert ar and ar[0]["team"] == "Payments"
    assert ar[0]["candidates"] == ["a@x.com", "b@x.com"]
    assert ar[0]["thread_id"]                       # a thread_id to resume with
    assert not any(e["type"] == "result" for e in events)  # paused, no result yet


def test_triage_resume_completes(monkeypatch):
    seen = {}

    class FakeGraph:
        async def astream(self, command, config=None, stream_mode=None):
            seen["resume"] = getattr(command, "resume", None)
            seen["thread_id"] = config["configurable"]["thread_id"]
            yield ("updates", {"assign_defect": {"triage_notes": ["[assign_defect] selected b@x.com"]}})
            yield ("values", {"status": "notified", "assigned_to": "b@x.com"})

    monkeypatch.setattr(routes, "_graph", FakeGraph())
    client = TestClient(routes.app)
    resp = client.post("/triage/resume", json={"thread_id": "t-123", "assignee": "b@x.com"})
    events = _parse_sse(resp.text)

    assert seen["resume"] == "b@x.com"
    assert seen["thread_id"] == "t-123"
    results = [e for e in events if e["type"] == "result"]
    assert results and results[0]["state"]["assigned_to"] == "b@x.com"
