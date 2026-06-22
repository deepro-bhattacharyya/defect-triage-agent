"""Unit tests for assign_defect — team routing + no-candidate auto-assign. No LLM, no key.

assign_defect calls interrupt() when candidates exist, which only works inside a
running graph. So these direct-call tests force the no-candidate path (auto-assign);
the interrupt + resume flow is covered in test_graph.py.
"""

import pytest

from app.agent.nodes import assign as assign_mod
from app.agent.nodes.assign import assign_defect


@pytest.fixture(autouse=True)
def no_candidates(monkeypatch):
    # No candidates → assign_defect auto-assigns the team default, no interrupt.
    monkeypatch.setattr(assign_mod, "get_team_candidates", lambda team, fallback=None: [])


@pytest.mark.parametrize(
    "component,expected_team",
    [
        ("checkout-service", "Payments"),
        ("PaymentClient", "Payments"),          # free-form LLM string
        ("auth-service", "Identity & Access"),
        ("reporting-service", "Reporting"),
        ("analytics-service", "Data & Analytics"),
        ("web-frontend", "Frontend"),
        ("Profile Page", "Frontend"),           # free-form LLM string
    ],
)
def test_routes_known_components(component, expected_team):
    out = assign_defect({"component": component})
    assert out["assigned_team"] == expected_team
    assert "@" in out["assigned_to"]
    assert out["status"] == "assigned"


def test_unknown_component_falls_back_to_triage():
    out = assign_defect({"component": "quantum-warp-core"})
    assert out["assigned_team"] == "Triage"
    assert out["assigned_to"] == "triage-lead@example.com"


def test_missing_component_falls_back_to_triage():
    out = assign_defect({})
    assert out["assigned_team"] == "Triage"


def test_appends_breadcrumb_and_notes_no_candidates():
    out = assign_defect({"component": "checkout-service"})
    assert out["triage_notes"][0].startswith("[assign_defect]")
    assert "Payments" in out["triage_notes"][0]
    assert "auto-assigned" in out["triage_notes"][0]
