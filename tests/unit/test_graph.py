"""Full-graph wiring tests with the LLM + vector store mocked (no key, no network).

Exercises every branch of the flow deterministically: new bug, duplicate
short-circuit, regression, and the CRITICAL escalate path.
"""

import pytest

from app.agent.graph import build_graph
from app.agent.nodes import analyze as analyze_mod
from app.agent.nodes import duplicate as dup_mod
from app.agent.nodes import prioritize as prio_mod
from app.tools.vector_store import Document


class FakeMsg:
    def __init__(self, content):
        self.content = content


class FakeLLM:
    def __init__(self, content):
        self.content = content

    def invoke(self, messages):
        return FakeMsg(self.content)


class FakeStore:
    def __init__(self, pairs):
        self.pairs = pairs

    def similarity_search_with_score(self, query, k=5):
        return self.pairs[:k]


def _doc(defect_id, status):
    return Document(page_content="x", metadata={"defect_id": defect_id, "status": status})


ANALYZE_JSON = '{"category": "backend", "component": "checkout-service", "root_cause": "x"}'


def _patch(monkeypatch, store_pairs, prio_json='{"severity": "LOW", "priority": 4}',
           analyze_json=ANALYZE_JSON):
    monkeypatch.setattr(dup_mod, "get_vector_store", lambda: FakeStore(store_pairs))
    monkeypatch.setattr(analyze_mod, "get_llm", lambda: FakeLLM(analyze_json))
    monkeypatch.setattr(prio_mod, "get_llm", lambda: FakeLLM(prio_json))


@pytest.fixture
def graph():
    return build_graph()


def _notes(state):
    return " || ".join(state.get("triage_notes", []))


def test_new_bug_takes_full_path(monkeypatch, graph):
    _patch(monkeypatch, store_pairs=[])  # no match
    out = graph.invoke(
        {"defect_id": "DEF-202", "title": "Submit button misaligned",
         "description": "purely visual", "environment": "staging"}
    )
    assert out["is_duplicate"] is False and out["is_regression"] is False
    assert out["severity"] == "LOW"
    assert out["status"] == "notified"
    notes = _notes(out)
    assert "[analyze_defect]" in notes and "[prioritize]" in notes
    assert "[assign_defect]" in notes and "[notify]" in notes
    assert "[escalate]" not in notes and "[flag_duplicate]" not in notes


def test_open_duplicate_short_circuits(monkeypatch, graph):
    _patch(monkeypatch, store_pairs=[(_doc("DEF-101", "OPEN"), 0.95)])
    out = graph.invoke(
        {"defect_id": "DEF-203", "title": "Promo code 500 at checkout",
         "description": "discount code gives 500", "environment": "production"}
    )
    assert out["is_duplicate"] is True and out["duplicate_of"] == "DEF-101"
    assert out["status"] == "closed_duplicate"
    # analyze/prioritize skipped entirely
    assert out.get("severity") is None
    notes = _notes(out)
    assert "[flag_duplicate]" in notes and "[analyze_defect]" not in notes


def test_regression_goes_through_analysis(monkeypatch, graph):
    _patch(monkeypatch, store_pairs=[(_doc("DEF-050", "CLOSED"), 0.90)],
           prio_json='{"severity": "HIGH", "priority": 2}')
    out = graph.invoke(
        {"defect_id": "DEF-204", "title": "Random logout invalid session",
         "description": "token refresh race", "environment": "production"}
    )
    assert out["is_regression"] is True and out["regression_of"] == "DEF-050"
    assert out["is_duplicate"] is False
    assert out["severity"] == "HIGH"
    assert out["status"] == "notified"
    notes = _notes(out)
    assert "[REGRESSION]" in notes and "[assign_defect]" in notes


def test_critical_routes_through_escalate(monkeypatch, graph):
    # LLM says LOW, but the emergency keywords force CRITICAL -> escalate path.
    _patch(monkeypatch, store_pairs=[], prio_json='{"severity": "LOW", "priority": 4}')
    out = graph.invoke(
        {"defect_id": "DEF-201", "title": "Payment service completely down in production",
         "description": "All users affected; no user can complete a purchase.",
         "environment": "production"}
    )
    assert out["severity"] == "CRITICAL"
    assert out["status"] == "notified"
    assert "[escalate]" in _notes(out)
