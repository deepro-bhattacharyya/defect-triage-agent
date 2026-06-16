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


def test_flag_duplicate_links_parent(monkeypatch):
    linked, commented = [], []
    monkeypatch.setattr(flag_mod, "link_duplicate", lambda d, p: linked.append((d, p)) or {"ok": True})
    monkeypatch.setattr(flag_mod, "add_comment", lambda d, c: commented.append(d) or {"ok": True})

    out = flag_duplicate({"defect_id": "DEF-203", "duplicate_of": "DEF-101"})

    assert out["status"] == "closed_duplicate"
    assert linked == [("DEF-203", "DEF-101")]
    assert commented == ["DEF-203"]
    assert "DEF-101" in out["triage_notes"][0]


def test_notify_hits_all_three_channels(monkeypatch):
    jira, slack, email = [], [], []
    monkeypatch.setattr(notify_mod, "update_ticket", lambda d, f: jira.append((d, f)) or {"ok": True})
    monkeypatch.setattr(notify_mod, "post_message", lambda c, t: slack.append((c, t)) or {"ok": True})
    monkeypatch.setattr(notify_mod, "send_email", lambda to, s, b: email.append(to) or {"ok": True})

    out = notify(
        {
            "defect_id": "DEF-201",
            "severity": "CRITICAL",
            "title": "Payment down",
            "assigned_team": "Payments",
            "assigned_to": "payments-oncall@example.com",
            "component": "checkout-service",
        }
    )

    assert out["status"] == "notified"
    assert len(jira) == 1 and jira[0][0] == "DEF-201"
    assert len(slack) == 1 and slack[0][0] == "#defect-triage"
    assert email == ["payments-oncall@example.com"]
    assert out["triage_notes"][0].startswith("[notify]")
