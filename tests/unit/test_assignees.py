"""Unit tests for the candidate-assignee lookup tool. No network."""

from app.tools import assignees


def test_falls_back_to_static_roster_when_no_jira(monkeypatch):
    for var in ("JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    out = assignees.get_team_candidates("Payments", fallback=["a@x.com", "b@x.com"])
    assert out == ["a@x.com", "b@x.com"]


def test_uses_jira_assignable_users_when_available(monkeypatch):
    monkeypatch.setenv("JIRA_BASE_URL", "https://jira.example.com")
    monkeypatch.setenv("JIRA_EMAIL", "me@x.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "tok")

    class FakeResp:
        status_code = 200

        def json(self):
            return [
                {"displayName": "Jane QA", "accountType": "atlassian"},
                {"displayName": "Bot", "accountType": "app"},          # skipped
                {"emailAddress": "ops@x.com", "accountType": "atlassian"},
            ]

    monkeypatch.setattr(assignees.requests, "get", lambda *a, **k: FakeResp())
    out = assignees.get_team_candidates("Payments", fallback=["ignored@x.com"])
    assert out == ["Jane QA", "ops@x.com"]  # live Jira wins over fallback; bot skipped


def test_jira_error_falls_back(monkeypatch):
    monkeypatch.setenv("JIRA_BASE_URL", "https://jira.example.com")
    monkeypatch.setenv("JIRA_EMAIL", "me@x.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "tok")

    def boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(assignees.requests, "get", boom)
    out = assignees.get_team_candidates("Payments", fallback=["fallback@x.com"])
    assert out == ["fallback@x.com"]
