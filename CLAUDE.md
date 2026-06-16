# CLAUDE.md

This file is read automatically by Claude Code at the start of every session.
It is the single source of truth for how this project is built. Keep it updated.

---

## Project: DefectTriageBot

An LLM-powered LangGraph agent that automatically reviews, prioritizes, and
routes incoming software bug reports. It ingests a defect, checks for
duplicates/regressions via vector similarity, uses Claude to analyze root cause
and severity, assigns it to the right team, and notifies stakeholders — turning
a ~45-minute manual triage into a sub-2-minute automated one.

The full approved plan lives in `docs/PROJECT_PLAN.md` (the original README).
**That document is the spec. Do not deviate from its flow, state schema, or
node contracts without explicitly flagging the change.**

---

## Commands

```bash
# Setup (run once)
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # then fill in real keys

# Seed the vector store with the existing backlog (needed for dup/regression tests)
python scripts/seed_vector_store.py

# Run the API locally
uvicorn app.api.routes:app --reload

# Tests
pytest                          # all tests
pytest tests/unit -q            # unit tests only (mocked LLM)
pytest tests/integration -q     # full-graph end-to-end (hits live LLM)

# Lint / format
ruff check . && ruff format .
```

---

## Architecture

LangGraph `StateGraph` with a single shared `TriageState` (TypedDict).
Flow — duplicate check happens BEFORE any LLM call so confirmed duplicates skip
analysis entirely:

```
START → intake_defect → check_duplicate → ┌─ DUPLICATE  → flag_duplicate → END
                                          ├─ REGRESSION → analyze_defect ─┐
                                          └─ NEW BUG    → analyze_defect ─┤
                                                                          ↓
                          prioritize → ┌─ CRITICAL → escalate → assign_defect ─┐
                                       └─ HIGH/MED/LOW ──────→ assign_defect ───┤
                                                                                ↓
                                                              notify → END
```

| Node | LLM? | Responsibility |
|------|------|----------------|
| `intake_defect`   | No  | Parse/normalize input; extract image attachments |
| `check_duplicate` | No  | Vector similarity vs backlog; flag regression if match is RESOLVED/CLOSED |
| `analyze_defect`  | Yes | Root cause, category, component (multimodal: text + base64 images) |
| `prioritize`      | Yes | Severity (CRITICAL/HIGH/MEDIUM/LOW) + priority (1–4) |
| `assign_defect`   | No  | Component → team → developer routing |
| `escalate`        | No  | Page on-call for CRITICAL bugs |
| `flag_duplicate`  | No  | Link to parent ticket, close as duplicate |
| `notify`          | No  | Jira update + Slack + email |

### Key constants (do not change without flagging)
- `SIMILARITY_THRESHOLD = 0.80` — at/above = match. **Recalibrated from the plan's
  original 0.88** (which was tuned for OpenAI embeddings) for this POC's Gemini
  `gemini-embedding-001`: real dup/regression pairs score ~0.81–0.85, noise ≤0.70, so
  0.80 (industry-standard cosine cutoff) separates them. Flagged deviation from `docs/PROJECT_PLAN.md`.
- `RESOLVED_STATUSES = {"RESOLVED", "CLOSED", "DONE"}` — a match in one of these = regression, not duplicate.
- (The plan's reserved 0.80–0.88 human-review band was OpenAI-calibrated; not used with the Gemini threshold.)

---

## Tech Stack

- Python 3.11+
- LangGraph 1.0+ (`StateGraph`, `RetryPolicy`)
- LLM: Gemini 2.5 Flash (dev) / Claude Sonnet 4.6 (prod)
- Embeddings: Gemini `gemini-embedding-001` (3072-dim). POC is Gemini-only; OpenAI not used.
- Vector store: ChromaDB (local dev) / Pinecone (cloud)
- API: FastAPI + uvicorn
- Tracing/eval: LangSmith
- Logging: structlog; errors: Sentry

---

## Conventions

- **Every node takes `state: TriageState` and returns a partial `dict`** (only the
  keys it changes). Never mutate `state` in place — LangGraph merges the returned dict.
- Fields typed `Annotated[list, operator.add]` (e.g. `triage_notes`,
  `similar_defects`, `image_attachments`) are append-only reducers — return a list
  to append, not the full list.
- Every node appends a breadcrumb to `triage_notes` in the form
  `"[node_name] what happened"`. This is the audit trail.
- LLM nodes (`analyze_defect`, `prioritize`) must request strict JSON output and
  parse defensively. Wrap parsing in try/except; on failure, retry (RetryPolicy
  already set to `max_attempts=3`) and fall back to the rule-based path.
- Keep external I/O (Jira, Slack, vector store) behind the `app/tools/` layer so
  nodes stay unit-testable with mocks.
- Secrets only via environment variables — never hardcode keys. Never log raw
  image data or PII (see Risks in the plan).

---

## Build Order (recommended)

Build and test bottom-up so the graph wires together cleanly. Tackle one item per
session; run its test before moving on.

1. `app/agent/state.py` — `TriageState` schema (**already provided, done**).
2. `app/tools/vector_store.py` — Chroma wrapper + `similarity_search_with_score`.
3. `scripts/seed_vector_store.py` — load `tests/fixtures/seed_backlog.json` into the store.
4. `app/agent/nodes/intake.py` — parse input, pull image attachments.
5. `app/agent/nodes/duplicate.py` — `check_duplicate` (logic given in the plan).
6. `app/agent/nodes/analyze.py` — multimodal `analyze_defect` (logic given in the plan).
7. `app/agent/nodes/prioritize.py` — severity + priority, with rule-based override for known CRITICAL keywords.
8. `app/agent/nodes/assign.py` — component→team mapping (start with a static dict).
9. `app/agent/nodes/escalate.py`, `flag_dup.py`, `notify.py` — side-effect nodes; stub the integrations first.
10. `app/agent/graph.py` — wire it all together (definition given in the plan).
11. `app/api/routes.py` — FastAPI `POST /triage` endpoint that runs the graph.
12. Tests last-to-first: unit per node → integration on the whole graph.

When a node's contract is fully specified in `docs/PROJECT_PLAN.md`
(`check_duplicate`, `analyze_defect`, the graph wiring, the state schema), follow
it exactly rather than inventing a new design.

---

## Testing

- Fixtures live in `tests/fixtures/`. `sample_defects.json` holds the 5 canonical
  scenarios (critical, low, duplicate, regression, multimodal). `seed_backlog.json`
  holds the pre-existing defects (incl. open `DEF-101` and resolved `DEF-050`) the
  duplicate/regression logic must match against — seed these into the vector store
  before running dup/regression tests.
- Unit tests mock the LLM and the vector store. Integration tests may hit the live LLM.
- Targets from the plan: severity accuracy ≥ 90%, duplicate precision ≥ 95%,
  assignment accuracy ≥ 85%, avg triage latency < 10s.

---

## Data note

Public bug datasets exist (Bugzilla / Eclipse-Mozilla on Kaggle) and are good for
severity + assignment evaluation, but they lack duplicate-pair, regression, and
image labels. We therefore ship hand-built fixtures for those scenarios. See
`docs/DATA.md` for sources and how to wire real data in.

---

## Guardrails for Claude Code

- Ask before adding a new third-party dependency or changing a pinned version.
- Never commit `.env` or any real key. `.gitignore` already covers it.
- Don't implement out-of-scope v1 features (auto bug-fixing, test-case generation,
  UI dashboard) — flag them as future work instead.
- After finishing a node, update the relevant checkbox/section here if the contract changes.
