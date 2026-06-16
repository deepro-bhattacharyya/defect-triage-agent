"""Unit tests for check_duplicate. Vector store is mocked — no embeddings, no key."""

from app.agent.nodes import duplicate
from app.agent.nodes.duplicate import check_duplicate, SIMILARITY_THRESHOLD
from app.tools.vector_store import Document


class FakeStore:
    """Returns a preset list of (Document, similarity) pairs, most-similar first."""

    def __init__(self, pairs):
        self._pairs = pairs

    def similarity_search_with_score(self, query, k=5):
        return self._pairs[:k]


def _patch_store(monkeypatch, pairs):
    monkeypatch.setattr(duplicate, "get_vector_store", lambda: FakeStore(pairs))


def _doc(defect_id, status):
    return Document(page_content="...", metadata={"defect_id": defect_id, "status": status})


def test_open_match_is_duplicate(monkeypatch):
    _patch_store(monkeypatch, [(_doc("DEF-101", "OPEN"), 0.95)])
    out = check_duplicate({"title": "promo 500", "description": "checkout"})

    assert out["is_duplicate"] is True
    assert out["duplicate_of"] == "DEF-101"
    assert out["is_regression"] is False
    assert out["status"] == "duplicate"
    assert "DUPLICATE" in out["triage_notes"][0]


def test_resolved_match_is_regression(monkeypatch):
    _patch_store(monkeypatch, [(_doc("DEF-050", "CLOSED"), 0.91)])
    out = check_duplicate({"title": "random logout", "description": "invalid session"})

    assert out["is_regression"] is True
    assert out["regression_of"] == "DEF-050"
    assert out["is_duplicate"] is False
    assert out["status"] == "in_triage"
    assert "REGRESSION" in out["triage_notes"][0]


def test_done_status_counts_as_regression(monkeypatch):
    _patch_store(monkeypatch, [(_doc("DEF-090", "DONE"), 0.90)])
    out = check_duplicate({"title": "x", "description": "y"})
    assert out["is_regression"] is True
    assert out["regression_of"] == "DEF-090"


def test_below_threshold_is_new_defect(monkeypatch):
    _patch_store(monkeypatch, [(_doc("DEF-101", "OPEN"), 0.70)])  # noise-level score
    out = check_duplicate({"title": "unrelated", "description": "thing"})

    assert out["is_duplicate"] is False
    assert out["is_regression"] is False
    assert out["duplicate_of"] == ""
    assert out["regression_of"] == ""
    assert out["status"] == "in_triage"
    assert "No match" in out["triage_notes"][0]


def test_no_results_is_new_defect(monkeypatch):
    _patch_store(monkeypatch, [])
    out = check_duplicate({"title": "brand", "description": "new"})
    assert out["is_duplicate"] is False
    assert out["is_regression"] is False


def test_exact_threshold_counts_as_match(monkeypatch):
    _patch_store(monkeypatch, [(_doc("DEF-101", "OPEN"), SIMILARITY_THRESHOLD)])
    out = check_duplicate({"title": "x", "description": "y"})
    assert out["is_duplicate"] is True  # score >= 0.88 matches (only < skips)


def test_first_qualifying_match_wins(monkeypatch):
    # Below-threshold noise first, then a real OPEN match — loop must skip the
    # noise and act on the qualifying match.
    _patch_store(
        monkeypatch,
        [(_doc("DEF-999", "OPEN"), 0.50), (_doc("DEF-101", "OPEN"), 0.93)],
    )
    out = check_duplicate({"title": "x", "description": "y"})
    assert out["duplicate_of"] == "DEF-101"
