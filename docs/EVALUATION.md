# Evaluation — Phase 6

How the agent is tested, the results observed, and how to reproduce them.

## How to run

```bash
pytest tests/unit -q            # offline: mocks LLM + vector store, no key (56 tests)
pytest tests/integration -q     # live: 5 scenarios through the real graph (needs GOOGLE_API_KEY)
python scripts/evaluate.py      # live: metrics report (needs GOOGLE_API_KEY)
```

**Manual / exploratory testing** also goes through the React UI (`frontend/`): build it
(`npm run build`) and open `http://localhost:8000/`, or run `npm run dev`. The
"Load sample (duplicate)" button exercises the no-LLM duplicate path, handy when the
Gemini daily quota is exhausted. See `frontend/README.md`.

The integration tests **skip automatically** when `GOOGLE_API_KEY` is unset (e.g. CI),
and skip individual scenarios that hit a Gemini quota error instead of failing.

## What the integration tests assert

For each of the 5 canonical scenarios (`tests/fixtures/sample_defects.json`):

- **Duplicate / regression detection** (deterministic at threshold 0.80) — `is_duplicate`,
  `is_regression`, `duplicate_of`, `regression_of` must match the fixture.
- **Routing** — asserted *consistent with the actual severity*: duplicates take
  `intake → check_duplicate → flag_duplicate`; everything else takes
  `intake → check_duplicate → analyze → prioritize → [escalate if CRITICAL] → assign → notify`.
  (Routing is only deterministic *given* the severity, because the escalate branch is
  severity-driven and severity is produced by the LLM.)
- **Severity** — checked for validity; asserted exactly only for the CRITICAL case, which
  the rule-based keyword override makes deterministic.
- **Terminal status** — `closed_duplicate` for duplicates, `notified` otherwise, with a team assigned.

## Observed results (across live runs on Gemini)

| Scenario | Expected | Observed | Notes |
|----------|----------|----------|-------|
| 1 Payment down | CRITICAL → escalate | ✅ CRITICAL, escalated, Payments | severity forced by keyword override (deterministic) |
| 2 Cosmetic staging | LOW | ✅ LOW, Frontend | |
| 3 Promo 500 | DUPLICATE of DEF-101 | ✅ dup of DEF-101 (score 0.845–0.850), LLM skipped | verified live (embedding-only) |
| 4 Random logout | REGRESSION of DEF-050, HIGH | ✅ regression of DEF-050 (0.819–0.825); severity **HIGH one run, CRITICAL another** | regression detection deterministic; severity is the noisy signal |
| 5 Screenshot | LOW (multimodal) | ✅ analyze accepted the image (UI/UX) | multimodal path confirmed in Phase 3 |

### Metrics vs. the plan's targets

> **N = 5 is a smoke-level check, not a statistical evaluation.** The plan's percentage
> targets are dataset-level goals; with 5 hand-built scenarios they can only be indicative.
> Scale up with a real labeled dataset (see `docs/DATA.md`) for meaningful numbers.

| Metric | Target | Observed (N=5 smoke) |
|--------|--------|----------------------|
| Duplicate precision | ≥ 95% | 100% (1/1 predicted duplicates correct) |
| Regression detection | — | correct (DEF-050) |
| Assignment made | ≥ 85% | 100% (every non-duplicate got a team) |
| Severity accuracy | ≥ 90% | mixed — correct for 1/2/5; scenario 4 varied HIGH↔CRITICAL between runs |
| Avg latency | < 10 s | ~2–8 s/scenario nominally; spikes to tens of seconds when the LLM 429s and retries |

## Known constraints & recommendations

- **Gemini free-tier quota: 20 generate-requests/day** for `gemini-2.5-flash`. A full live
  `evaluate.py` run (≈8 generate calls) plus the integration suite can exhaust it; further
  calls return `429 RESOURCE_EXHAUSTED`. Use a paid key or wait for the daily reset for a
  full metrics run. (Embeddings are a separate quota, so the duplicate path still runs.)
- **RetryPolicy multiplies quota use on 429.** `analyze`/`prioritize` retry up to 3× on any
  exception, so a quota error becomes 3 rejected calls. *Recommendation:* give the
  `RetryPolicy` a `retry_on` predicate that excludes `RESOURCE_EXHAUSTED`, or back off on 429.
- **Severity is the variable signal.** Routing, duplicate, and regression detection are
  deterministic; severity depends on the LLM. The rule-based override guarantees true
  emergencies are caught, and the rule-based fallback guarantees a valid severity on LLM failure.
