"""Unit tests for the VectorStore wrapper.

Fully offline: a fake keyword-based embedder replaces OpenAI, and an in-memory
(ephemeral) Chroma client replaces the persistent store. No OPENAI_API_KEY needed.

What we're pinning down:
- the wrapper returns SIMILARITY (higher == closer), not raw distance;
- metadata (defect_id, status) round-trips so check_duplicate can read it;
- a near-identical query clears the 0.88 threshold; an unrelated one does not.
"""

import chromadb
import pytest

from app.tools.vector_store import VectorStore

SIMILARITY_THRESHOLD = 0.88  # mirrors the constant check_duplicate uses


class FakeEmbedder:
    """Deterministic, offline embedder. Maps text to one of a few orthogonal
    unit vectors by keyword, so cosine similarity is fully predictable:
    same bucket -> similarity 1.0, different bucket -> 0.0."""

    def _vec(self, text):
        t = text.lower()
        if "promo" in t or "checkout" in t:
            return [1.0, 0.0, 0.0]
        if "login" in t or "token" in t or "session" in t:
            return [0.0, 1.0, 0.0]
        if "nav" in t or "menu" in t or "header" in t:
            return [0.0, 0.0, 1.0]
        return [0.577, 0.577, 0.577]  # neutral

    def embed_documents(self, texts):
        return [self._vec(t) for t in texts]

    def embed_query(self, text):
        return self._vec(text)


BACKLOG = [
    {"defect_id": "DEF-101", "title": "Checkout 500 on promo code",
     "description": "Applying a promo code returns HTTP 500.",
     "component": "checkout-service", "severity": "HIGH", "status": "OPEN"},
    {"defect_id": "DEF-050", "title": "Login token refresh race",
     "description": "Intermittent invalid session on token refresh.",
     "component": "auth-service", "severity": "HIGH", "status": "CLOSED"},
    {"defect_id": "DEF-066", "title": "Mobile nav overlaps header",
     "description": "Hamburger menu overlaps the logo on small screens.",
     "component": "web-frontend", "severity": "LOW", "status": "OPEN"},
]


@pytest.fixture
def store():
    vs = VectorStore(embedder=FakeEmbedder(), client=chromadb.EphemeralClient())
    vs.add_defects(BACKLOG)
    return vs


def test_add_defects_writes_all(store):
    assert store.count() == 3


def test_open_match_clears_threshold_with_metadata(store):
    results = store.similarity_search_with_score("promo code at checkout throws 500", k=5)
    top_doc, top_score = results[0]

    assert top_doc.metadata["defect_id"] == "DEF-101"
    assert top_doc.metadata["status"] == "OPEN"
    assert top_score >= SIMILARITY_THRESHOLD          # similarity, higher == closer
    assert top_score == pytest.approx(1.0, abs=1e-6)  # identical bucket


def test_resolved_match_is_findable_for_regression(store):
    results = store.similarity_search_with_score("random logout invalid session token", k=5)
    top_doc, top_score = results[0]

    assert top_doc.metadata["defect_id"] == "DEF-050"
    assert top_doc.metadata["status"] == "CLOSED"     # check_duplicate => regression
    assert top_score >= SIMILARITY_THRESHOLD


def test_unrelated_query_stays_below_threshold(store):
    results = store.similarity_search_with_score("billing invoice pdf generation", k=5)
    # neutral vector vs orthogonal buckets -> all well under 0.88
    assert all(score < SIMILARITY_THRESHOLD for _doc, score in results)


def test_scores_are_descending(store):
    results = store.similarity_search_with_score("checkout promo", k=5)
    scores = [s for _d, s in results]
    assert scores == sorted(scores, reverse=True)
