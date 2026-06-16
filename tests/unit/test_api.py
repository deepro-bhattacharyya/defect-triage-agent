"""API-layer tests with the compiled graph replaced by a fake (no key, no network)."""

from fastapi.testclient import TestClient

from app.api import routes


def test_health():
    client = TestClient(routes.app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_triage_returns_final_state(monkeypatch):
    class FakeGraph:
        def invoke(self, state):
            # echo input + a triage verdict, like the real graph's final state
            return {**state, "status": "notified", "severity": "LOW",
                    "assigned_team": "Frontend", "triage_notes": ["[notify] done"]}

    monkeypatch.setattr(routes, "_graph", FakeGraph())
    client = TestClient(routes.app)

    resp = client.post("/triage", json={"title": "Button misaligned", "description": "visual"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "notified"
    assert body["severity"] == "LOW"
    assert body["title"] == "Button misaligned"


def test_triage_requires_title():
    client = TestClient(routes.app)
    resp = client.post("/triage", json={"description": "no title"})
    assert resp.status_code == 422  # pydantic validation error
