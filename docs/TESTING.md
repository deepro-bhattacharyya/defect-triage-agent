# Testing

How the test suite is structured, the patterns that keep it network-free, and
what each test file proves.

- **Runner:** `pytest`. Run from the repo root (the folder with `requirements.txt`).
- **Status:** 57 unit tests passing. Integration tests require `GOOGLE_API_KEY`.
- **No API key required for unit tests.** Everything runs offline using mocks.

---

## Running the tests

```powershell
# Fast offline check — mocked LLM + store, no key needed (~25 seconds)
pytest tests/unit -q

# Live integration tests — needs GOOGLE_API_KEY + seeded vector store
pytest tests/integration -q

# Lint (ruff)
python -m ruff check app tests scripts

# Everything
pytest -q
```

---

## Test layout — one file per module

| File | Covers | Notes |
|------|--------|-------|
| `tests/unit/test_vector_store.py` | `app/tools/vector_store.py` | In-memory Chroma + fake embedder; verifies similarity > distance, metadata round-trips, score ordering. |
| `tests/unit/test_intake.py` | `app/agent/nodes/intake.py` | Field normalization, image guardrails (size cap, count cap, unsupported types). |
| `tests/unit/test_duplicate.py` | `app/agent/nodes/duplicate.py` | All three verdicts: OPEN match → duplicate, CLOSED match → regression, no match → new. |
| `tests/unit/test_analyze.py` | `app/agent/nodes/analyze.py` | JSON parsing (clean + fenced + malformed), regression prefix, image block assembly. |
| `tests/unit/test_prioritize.py` | `app/agent/nodes/prioritize.py` | LLM severity, rule override, rule fallback, all severity→priority mappings. |
| `tests/unit/test_assign.py` | `app/agent/nodes/assign.py` | Known components → correct team, unknown → Triage default. |
| `tests/unit/test_side_effects.py` | `escalate.py`, `flag_dup.py`, `notify.py` | Tool stubs monkeypatched; asserts each node hits the right integration. |
| `tests/unit/test_graph.py` | `app/agent/graph.py` | Full graph with mocked LLM + store; all 4 branches: new/duplicate/regression/critical-escalate. |
| `tests/unit/test_api.py` | `app/api/routes.py` | Health endpoint; triage SSE stream (log events + result); quota error → error event. |
| `tests/integration/test_full_triage.py` | Full live graph | 5 canonical scenarios against the real Gemini + seeded ChromaDB. Auto-skips without `GOOGLE_API_KEY`. |

---

## The two offline patterns — why tests need no key

### Pattern 1: Mock the LLM with a fake object

`analyze_defect` and `prioritize` call `get_llm()`. Tests monkeypatch it to
return a `FakeMsg` object with a preset `.content`:

```python
class FakeLLM:
    def invoke(self, messages):
        return FakeMsg('{"category":"backend","component":"checkout-service","root_cause":"null deref"}')

monkeypatch.setattr(analyze, "get_llm", lambda: FakeLLM())
out = analyze_defect({"title": "x", "description": "y"})
assert out["category"] == "backend"
```

### Pattern 2: Mock the vector store

`check_duplicate` calls `get_vector_store()`. Tests monkeypatch it to return a
`FakeStore` that serves hand-built `(Document, score)` pairs:

```python
class FakeStore:
    def similarity_search_with_score(self, query, k=5):
        return [(_doc("DEF-101", "OPEN"), 0.95)]

monkeypatch.setattr(duplicate, "get_vector_store", lambda: FakeStore())
out = check_duplicate({"title": "promo 500", "description": "checkout"})
assert out["is_duplicate"] is True
assert out["duplicate_of"] == "DEF-101"
```

Offline fake embedder in the vector-store tests:
```python
class FakeEmbedder:
    def embed_query(self, text):
        return [1.0, 0.0, 0.0] if "checkout" in text.lower() else [0.0, 1.0, 0.0]
    def embed_documents(self, texts):
        return [self.embed_query(t) for t in texts]

store = VectorStore(embedder=FakeEmbedder(), client=chromadb.EphemeralClient())
```
The embedder is injected so no real OpenAI or Gemini call is made.

---

## Integration tests — 5 canonical scenarios

`tests/integration/test_full_triage.py` pushes each scenario in
`tests/fixtures/sample_defects.json` through the real compiled graph:

| Scenario | Expected verdict | Key assert |
|----------|-----------------|-----------|
| 1. Payment service down (prod, all users) | CRITICAL, notified | `severity == "CRITICAL"` (rule override, deterministic) |
| 2. Button misaligned (staging) | LOW, notified | `status == "notified"`, `assigned_team` set |
| 3. Promo 500 → matches OPEN DEF-101 | DUPLICATE, closed | `is_duplicate == True`, `duplicate_of == "DEF-101"` |
| 4. Random logout → matches CLOSED DEF-050 | REGRESSION, notified | `is_regression == True`, `regression_of == "DEF-050"` |
| 5. UI glitch + screenshot | LOW, notified (multimodal) | `status == "notified"`, image block sent to LLM |

**What's asserted strictly (deterministic):**
- `is_duplicate` and `is_regression` and their `_of` IDs
- The route taken (consistent with the actual severity — escalate iff CRITICAL)
- Terminal `status`

**What's asserted loosely (LLM-driven):**
- `severity` is always a valid value
- `severity == "CRITICAL"` only for scenario 1 (forced by keyword override, so it's deterministic)
- Other severities are verified as valid but not exact

Auto-skip logic:
```python
pytestmark = pytest.mark.skipif(
    not os.environ.get("GOOGLE_API_KEY"),
    reason="live integration test needs GOOGLE_API_KEY",
)
```
Scenarios that hit the Gemini quota (429) are skipped individually, not failed.

---

## Test fixtures

| File | Contents |
|------|----------|
| `tests/fixtures/seed_backlog.json` | 5 pre-existing defects seeded into ChromaDB before integration tests. Includes OPEN DEF-101 (dup target) and CLOSED DEF-050 (regression target). |
| `tests/fixtures/sample_defects.json` | 5 canonical scenarios, each with an `expected` block (ground truth). `expected` and `_*` fields are test metadata — strip them before feeding to the live graph. |

---

## Adding a new test — conventions

1. One `test_<module>.py` per file in `tests/unit/`.
2. Default to mocked LLM + store so the test runs offline and deterministically.
3. Assert on **facts and routing** (`is_duplicate`, `severity`, `status`,
   `triage_notes`), not on exact LLM prose (which varies).
4. Run `pytest tests/unit -q` before committing — it should stay green.

---

## Evaluation script (not `pytest`)

`scripts/evaluate.py` runs all 5 scenarios and reports against the plan targets:

| Metric | Target | Observed (N=5) |
|--------|--------|----------------|
| Severity accuracy | ≥ 90% | Mixed (scenario 4 varies HIGH↔CRITICAL) |
| Duplicate precision | ≥ 95% | 100% (1/1) |
| Assignment made | ≥ 85% | 100% |
| Avg. latency | < 10 s | ~2–8 s per defect |

See [EVALUATION.md](EVALUATION.md) for full detail and quota caveats.
