"""Unit tests for assign_defect — static component->team routing. No LLM, no key."""

import pytest

from app.agent.nodes.assign import assign_defect


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


def test_appends_breadcrumb():
    out = assign_defect({"component": "checkout-service"})
    assert out["triage_notes"][0].startswith("[assign_defect]")
    assert "Payments" in out["triage_notes"][0]
