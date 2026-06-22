"""Unit tests for the side-effect nodes (escalate, flag_duplicate, notify).

Tool stubs are monkeypatched to record calls — asserts each node hits the right
integration and returns the right status/breadcrumb, without any real I/O.
"""

from app.agent.nodes import escalate as escalate_mod
from app.agent.nodes import flag_dup as flag_mod
from app.agent.nodes import notify as notify_mod
from app.agent.nodes.escalate import escalate
from app.agent.nodes.flag_dup import flag_duplicate
from app.agent.nodes.notify import notify


def test_escalate_pages_oncall(monkeypatch):
    calls = []
    monkeypatch.setattr(escalate_mod, "page_oncall", lambda *a, **k: calls.append((a, k)) or {"ok": True})

    out = escalate({"defect_id": "DEF-201", "severity": "CRITICAL", "title": "Payment down"})

    assert out["status"] == "escalated"
    assert out["triage_notes"][0].startswith("[escalate]")
    assert calls and calls[0][0][0] == "DEF-201" and calls[0][0][1] == "CRITICAL"


def test_flag_duplicate_creates_and_closes_jira(monkeypatch):
    created, commented, transitioned = [], [], []
    monkeypatch.setattr(flag_mod, "create_issue",
                        lambda **kw: created.append(kw) or {"ok": True, "key": "SCRUM-9"})
    monkeypatch.setattr(flag_mod, "add_comment",
                        lambda k, c: commented.append((k, c)) or {"ok": True})
    monkeypatch.setattr(flag_mod, "transition_to",
                        lambda k, *names: transitioned.append((k, names)) or {"ok": True})

    out = flag_duplicate({"defect_id": "DEF-203", "duplicate_of": "DEF-101", "title": "promo 500"})

    assert out["status"] == "closed_duplicate"
    assert out["jira_key"] == "SCRUM-9"
    assert created and "DUPLICATE" in created[0]["summary"]
    assert commented and commented[0][0] == "SCRUM-9" and "DEF-101" in commented[0][1]
    assert transitioned and transitioned[0][0] == "SCRUM-9"
    assert "DEF-101" in out["triage_notes"][0]


def test_flag_duplicate_degrades_when_jira_down(monkeypatch):
    monkeypatch.setattr(flag_mod, "create_issue", lambda **kw: {"ok": False, "skipped": True})
    # add_comment / transition_to must NOT be called when create failed
    monkeypatch.setattr(flag_mod, "add_comment", lambda *a, **k: (_ for _ in ()).throw(AssertionError("called")))
    monkeypatch.setattr(flag_mod, "transition_to", lambda *a, **k: (_ for _ in ()).throw(AssertionError("called")))

    out = flag_duplicate({"defect_id": "DEF-203", "duplicate_of": "DEF-101", "title": "x"})
    assert out["status"] == "closed_duplicate"   # still finishes
    assert out["jira_key"] == ""


def test_notify_creates_jira_when_not_sourced(monkeypatch):
    created, slack, email = [], [], []
    monkeypatch.setattr(notify_mod, "create_issue",
                        lambda **kw: created.append(kw) or {"ok": True, "key": "SCRUM-10"})
    monkeypatch.setattr(notify_mod, "add_comment",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not update")))
    monkeypatch.setattr(notify_mod, "post_message", lambda c, t: slack.append((c, t)) or {"ok": True})
    monkeypatch.setattr(notify_mod, "send_email", lambda to, s, b: email.append(to) or {"ok": True})
    monkeypatch.setattr(notify_mod, "browse_url", lambda k: f"https://j/browse/{k}" if k else "")

    out = notify(
        {
            "defect_id": "DEF-201",
            "severity": "CRITICAL",
            "title": "Payment down",
            "assigned_team": "Payments",
            "assigned_to": "payments-oncall@example.com",
            "component": "checkout-service",
            "source_jira_key": "",   # NOT sourced from Jira → create
        }
    )

    assert out["status"] == "notified"
    assert out["jira_key"] == "SCRUM-10"
    assert out["jira_url"] == "https://j/browse/SCRUM-10"
    assert created and created[0]["priority"] == "Highest"   # CRITICAL -> Highest
    assert "[CRITICAL]" in created[0]["summary"]
    assert len(slack) == 1 and slack[0][0] == "#defect-triage"
    assert email == ["payments-oncall@example.com"]
    assert "created Jira SCRUM-10" in out["triage_notes"][0]


def test_notify_updates_existing_when_sourced_from_jira(monkeypatch):
    commented, updated = [], []
    monkeypatch.setattr(notify_mod, "add_comment",
                        lambda k, body: commented.append((k, body)) or {"ok": True})
    monkeypatch.setattr(notify_mod, "update_issue",
                        lambda k, fields: updated.append((k, fields)) or {"ok": True})
    monkeypatch.setattr(notify_mod, "create_issue",
                        lambda **kw: (_ for _ in ()).throw(AssertionError("should not create")))
    monkeypatch.setattr(notify_mod, "post_message", lambda c, t: {"ok": True})
    monkeypatch.setattr(notify_mod, "send_email", lambda to, s, b: {"ok": True})
    monkeypatch.setattr(notify_mod, "browse_url", lambda k: f"https://j/browse/{k}" if k else "")

    out = notify(
        {
            "defect_id": "SCRUM-42",
            "severity": "HIGH",
            "title": "Regression in auth",
            "category": "Auth",
            "component": "auth-service",
            "root_cause": "token race",
            "assigned_team": "Identity & Access",
            "assigned_to": "identity-team@example.com",
            "source_jira_key": "SCRUM-42",   # sourced from Jira → update
        }
    )

    assert out["status"] == "notified"
    assert out["jira_key"] == "SCRUM-42"
    assert commented and commented[0][0] == "SCRUM-42"
    assert "Root cause: token race" in commented[0][1]
    assert updated and updated[0][1] == {"priority": {"name": "High"}}  # HIGH -> High
    assert "updated Jira SCRUM-42" in out["triage_notes"][0]


def test_notify_degrades_when_jira_down(monkeypatch):
    monkeypatch.setattr(notify_mod, "create_issue", lambda **kw: {"ok": False, "skipped": True})
    monkeypatch.setattr(notify_mod, "post_message", lambda c, t: {"ok": True})
    monkeypatch.setattr(notify_mod, "send_email", lambda to, s, b: {"ok": True})

    out = notify({"defect_id": "DEF-1", "severity": "LOW", "title": "x",
                  "assigned_team": "Frontend", "assigned_to": "f@example.com"})
    assert out["status"] == "notified"     # still finishes
    assert out["jira_key"] == ""
    assert "Jira not configured" in out["triage_notes"][0]
    assert "warnings" not in out           # "not configured" is expected → no toast


def test_notify_emits_warning_on_jira_auth_failure(monkeypatch):
    # create_issue fails with a real auth error (401) → non-fatal warning surfaced
    monkeypatch.setattr(notify_mod, "create_issue", lambda **kw: {"ok": False, "status": 401})
    monkeypatch.setattr(notify_mod, "post_message", lambda c, t: {"ok": True})
    monkeypatch.setattr(notify_mod, "send_email", lambda to, s, b: {"ok": True})

    out = notify({"defect_id": "DEF-1", "severity": "LOW", "title": "x",
                  "assigned_team": "Frontend", "assigned_to": "f@example.com"})
    assert out["status"] == "notified"     # still finishes (non-fatal)
    assert out["warnings"] and "credentials" in out["warnings"][0].lower()
