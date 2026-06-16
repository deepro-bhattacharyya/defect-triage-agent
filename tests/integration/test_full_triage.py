"""End-to-end integration tests: the 5 canonical scenarios through the live graph.

These hit the real Gemini LLM + embeddings, so they're skipped automatically when
GOOGLE_API_KEY isn't available (e.g. CI without secrets). Run with:

    pytest tests/integration -q

Deterministic behavior (routing, duplicate/regression detection) is asserted
strictly. Severity is LLM-driven and probabilistic, so exact severity is asserted
only where the rule-based CRITICAL override makes it deterministic; elsewhere it's
checked for validity and measured as an accuracy metric in scripts/evaluate.py.
"""

import json
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

load_dotenv()

pytestmark = pytest.mark.skipif(
    not os.environ.get("GOOGLE_API_KEY"),
    reason="live integration test needs GOOGLE_API_KEY (Gemini LLM + embeddings)",
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures"

KNOWN_NODES = [
    "intake_defect", "check_duplicate", "analyze_defect", "prioritize",
    "escalate", "assign_defect", "flag_duplicate", "notify",
]


def _load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _defect_input(scenario):
    """Strip test-only metadata (_*, expected) before feeding the graph."""
    keep = ("defect_id", "title", "description", "stack_trace", "environment", "reporter")
    payload = {k: scenario[k] for k in keep if k in scenario}
    payload["image_attachments"] = [
        {"media_type": img["media_type"], "data": img["data"]}
        for img in scenario.get("image_attachments", [])
    ]
    return payload


def _visited(notes):
    """Reconstruct the ordered list of nodes visited from the triage_notes breadcrumbs."""
    seq = []
    for note in notes:
        for name in KNOWN_NODES:
            if f"[{name}]" in note:
                if not seq or seq[-1] != name:
                    seq.append(name)
                break
    return seq


@pytest.fixture(scope="module")
def graph():
    # Seed the backlog (idempotent upsert) so dup/regression scenarios have matches.
    from app.agent.graph import build_graph
    from app.tools.vector_store import get_vector_store

    get_vector_store().add_defects(_load("seed_backlog.json")["defects"])
    return build_graph()


SCENARIOS = _load("sample_defects.json")["scenarios"]


def _invoke_or_skip(graph, payload):
    try:
        return graph.invoke(payload)
    except Exception as e:
        if "RESOURCE_EXHAUSTED" in str(e) or "429" in str(e):
            pytest.skip(f"Gemini free-tier quota exhausted (20 req/day): {type(e).__name__}")
        raise


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s["_scenario"] for s in SCENARIOS])
def test_scenario_routes_and_classifies(graph, scenario):
    expected = scenario["expected"]
    out = _invoke_or_skip(graph, _defect_input(scenario))
    visited = _visited(out["triage_notes"])

    # --- duplicate / regression detection (deterministic at threshold 0.80) ---
    assert out.get("is_duplicate", False) == expected["is_duplicate"]
    assert out.get("is_regression", False) == expected["is_regression"]
    if expected.get("duplicate_of"):
        assert out["duplicate_of"] == expected["duplicate_of"]
    if expected.get("regression_of"):
        assert out["regression_of"] == expected["regression_of"]

    # --- routing: assert it's consistent with the ACTUAL severity, not a fixed one.
    # The escalate branch is severity-driven (LLM), so the route is only deterministic
    # *given* the severity; duplicate short-circuit is fully deterministic.
    if expected["is_duplicate"]:
        assert visited == ["intake_defect", "check_duplicate", "flag_duplicate"]
        assert out["status"] == "closed_duplicate"
    else:
        path = ["intake_defect", "check_duplicate", "analyze_defect", "prioritize"]
        if out.get("severity") == "CRITICAL":
            path.append("escalate")
        path += ["assign_defect", "notify"]
        assert visited == path
        assert out["status"] == "notified"
        assert out["assigned_team"]  # an owner was chosen

    # --- severity: validity always; exact only for the deterministic override case ---
    if "severity" in expected:
        assert out["severity"] in ("CRITICAL", "HIGH", "MEDIUM", "LOW")
        if expected["severity"] == "CRITICAL":
            assert out["severity"] == "CRITICAL"  # forced by keyword override
