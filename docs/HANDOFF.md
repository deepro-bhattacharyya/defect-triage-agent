# DefectTriageBot — Build Handoff (Phase-by-Phase)

> This is your implementation checklist. The project is broken into **6 phases**,
> each made of small, testable steps. Do **one step at a time**, run its test, then
> move on. Don't build everything in one shot.
>
> - The *what* and *why* of each piece: see `docs/PROJECT_EXPLAINED.md`.
> - The exact contracts (state schema, node logic, graph wiring): see `docs/PROJECT_PLAN.md` — **that is the spec; follow it exactly.**
> - Conventions and constants: see `CLAUDE.md`.
>
> **How to use this with Claude Code:** paste the "Prompt to use" from each step,
> review the generated code, run the test, then commit before the next step.

---

## Status Legend
- ⬜ Not started
- 🟦 In progress
- ✅ Done

## Progress Tracker

| Phase | Step | Item | Status |
|-------|------|------|:------:|
| 0 | 0.1 | Environment + dependencies installed | ⬜ |
| 0 | 0.2 | `app/tools/llm.py` (Gemini dev client) | ✅ |
| 1 | 1.1 | `app/tools/vector_store.py` | ⬜ |
| 1 | 1.2 | `scripts/seed_vector_store.py` | ⬜ |
| 2 | 2.1 | `app/agent/nodes/intake.py` | ⬜ |
| 2 | 2.2 | `app/agent/nodes/duplicate.py` | ⬜ |
| 3 | 3.1 | `app/agent/nodes/analyze.py` | ⬜ |
| 3 | 3.2 | `app/agent/nodes/prioritize.py` | ⬜ |
| 4 | 4.1 | `app/agent/nodes/assign.py` | ⬜ |
| 4 | 4.2 | `escalate.py`, `flag_dup.py`, `notify.py` + tool stubs | ⬜ |
| 5 | 5.1 | `app/agent/graph.py` | ⬜ |
| 5 | 5.2 | `app/api/routes.py` | ⬜ |
| 6 | 6.1 | Integration tests (5 scenarios) | ⬜ |
| 6 | 6.2 | Full suite + metrics report | ⬜ |

---

## Phase 0 — Groundwork (one-time setup)

**Goal:** a working Python environment with all dependencies and your API keys in place.

### Step 0.1 — Environment
```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
Copy-Item .env.example .env   # then open .env and paste real ANTHROPIC_API_KEY + OPENAI_API_KEY
```
**Done when:** `pip list` shows langgraph, langchain-google-genai, chromadb, fastapi,
pytest; `.env` exists with at least the `GOOGLE_API_KEY` (local-dev LLM) and `OPENAI_API_KEY`.

> **LLM note:** local dev/testing runs on **Google Gemini 1.5 Flash** (key: `GOOGLE_API_KEY`);
> **production** uses **Claude Sonnet 4.6**. The provider is isolated in `app/tools/llm.py`,
> so nodes never change when you swap. You can build and unit-test almost everything
> *without* real keys (tests mock the LLM). You only need real keys for the seed script and
> the live integration tests.

### Step 0.2 — LLM client  →  `app/tools/llm.py`  ✅ already created
The shared chat-model client exposing `get_llm()`. Currently wired to Gemini 1.5 Flash
for local dev (reads `GOOGLE_API_KEY`); swap to `ChatAnthropic(claude-sonnet-4-6)` here for
production. Nodes import `get_llm()` and never reference a provider directly.

**Done when:** `from app.tools.llm import get_llm` imports cleanly once
`langchain-google-genai` is installed.

---

## Phase 1 — The Foundation: Vector Store + Seeding

**Goal:** be able to store the existing backlog and ask "what's similar to this?".
Nothing else works until duplicate detection has something to search against.
**Concepts:** embeddings, vector store, similarity score (see Explained §2.2–2.4).

### Step 1.1 — Vector store wrapper  →  `app/tools/vector_store.py`
Build a ChromaDB wrapper exposing `get_vector_store()` and
`similarity_search_with_score(query, k)`, using OpenAI `text-embedding-3-small`.
Match exactly how `check_duplicate` calls it in the plan (returns `(doc, score)` pairs;
each `doc` has `.metadata` with `defect_id` and `status`).

> **Prompt to use:** *"Implement `app/tools/vector_store.py`: a ChromaDB wrapper exposing
> `get_vector_store()` and `similarity_search_with_score(query, k)` matching how
> `check_duplicate` uses it in the plan. Use OpenAI `text-embedding-3-small`. Add a unit
> test with a mocked embedder."*

**Test / Done when:** unit test with a mocked embedder passes; the returned shape is
`[(doc, score), ...]` and metadata round-trips.

⚠️ **Watch the score convention.** Chroma natively returns a *distance* (lower = closer),
but the plan's logic treats the number as a *similarity* (higher = closer, ≥ 0.88 = match).
Make the wrapper return a **similarity** so `check_duplicate` works as written. Note in code
how you convert distance→similarity.

### Step 1.2 — Seed script  →  `scripts/seed_vector_store.py`
Load `tests/fixtures/seed_backlog.json` into the store, putting `defect_id` and `status`
into each document's **metadata** (status drives duplicate-vs-regression later).

> **Prompt to use:** *"Write `scripts/seed_vector_store.py` that loads
> `tests/fixtures/seed_backlog.json` into the vector store, storing `defect_id` and
> `status` in each document's metadata."*

**Test / Done when:** running `python scripts/seed_vector_store.py` loads 5 defects;
a quick similarity query for "promo code checkout 500" returns `DEF-101` near the top.

---

## Phase 2 — The Non-LLM Brain: Intake + Duplicate Detection

**Goal:** clean the input and make the duplicate/regression decision — the whole left
half of the flowchart, no LLM yet. **Concepts:** the state clipboard, node contract,
append-only notes, duplicate vs. regression (Explained §2.4–2.6).

### Step 2.1 — Intake node  →  `app/agent/nodes/intake.py`
`intake_defect`: validate/normalize the raw payload, extract image attachments into
state. Enforce the image caps (max 5 MB/image, max 3 images; drop unsupported formats —
this is the risk mitigation). No LLM. Append a `triage_notes` breadcrumb.

> **Prompt to use:** *"Implement `app/agent/nodes/intake.py` (`intake_defect`) per the
> plan: validate input and extract image attachments into state, enforcing max 5 MB/image
> and max 3 images. No LLM. Append a triage_notes breadcrumb. Add a unit test."*

**Test / Done when:** unit test confirms fields normalized, oversized/extra images dropped,
breadcrumb appended, and only changed keys are returned (never mutates state in place).

### Step 2.2 — Duplicate/regression node  →  `app/agent/nodes/duplicate.py`
`check_duplicate`: implement **exactly** as in the plan — `SIMILARITY_THRESHOLD = 0.88`,
`RESOLVED_STATUSES = {"RESOLVED","CLOSED","DONE"}`, OPEN match ⇒ duplicate (short-circuit),
RESOLVED match ⇒ regression (proceed to analyze), no match ⇒ new bug.

> **Prompt to use:** *"Implement `app/agent/nodes/duplicate.py` (`check_duplicate`) exactly
> as specified in the plan, including the 0.88 threshold and RESOLVED/CLOSED → regression
> logic. Add unit tests using `seed_backlog.json` covering: open-duplicate,
> resolved-regression, and no-match."*

**Test / Done when:** three unit tests pass (mock the vector store):
match-on-OPEN-DEF-101 ⇒ `is_duplicate=True`; match-on-CLOSED-DEF-050 ⇒ `is_regression=True`;
no match ⇒ both False, status `in_triage`.

---

## Phase 3 — The LLM Brain: Analyze + Prioritize

**Goal:** the two intelligent steps. **Concepts:** multimodal LLM calls, strict JSON
output, defensive parsing, rule-based override and fallback (Explained §2.1, §7).

### Step 3.1 — Analyze node  →  `app/agent/nodes/analyze.py`
`analyze_defect`: build multimodal content (text block first, then each base64 image),
call the shared client via `get_llm()` from `app/tools/llm.py` (Gemini 1.5 Flash in dev,
Claude Sonnet 4.6 in prod), parse **strict JSON** for `category`/`component`/`root_cause`.
Add the regression note when `is_regression` is set. Wrap parsing in try/except.

> **Prompt to use:** *"Implement `app/agent/nodes/analyze.py` (`analyze_defect`) per the
> plan: build multimodal content (text + base64 images), call the shared client from
> `app/tools/llm.py` (`get_llm()`), parse strict JSON, handle the regression note, parse
> defensively. Mock the LLM in tests."*

**Test / Done when:** unit tests (LLM mocked) confirm: text+image content assembled
correctly; JSON parsed into the three fields; regression prefix added when flagged;
bad JSON is handled gracefully (no crash).

### Step 3.2 — Prioritize node  →  `app/agent/nodes/prioritize.py`
`prioritize`: ask the LLM for severity (CRITICAL/HIGH/MEDIUM/LOW) + priority (1–4),
**plus** a rule-based override that forces CRITICAL on danger keywords
("payment down", "data loss", "outage", "all users", etc.). On LLM failure, fall back
to the rule-based classifier.

> **Prompt to use:** *"Implement `app/agent/nodes/prioritize.py`: LLM severity + priority,
> PLUS a rule-based override that forces CRITICAL on known keywords (e.g. 'payment down',
> 'data loss', 'outage', 'all users'). Fall back to rules if the LLM fails. Add unit tests."*

**Test / Done when:** unit tests confirm: normal bug gets the LLM's rating; a
"payment service down… all users" report is forced to CRITICAL even if the mock LLM
says LOW; LLM failure still yields a valid severity via the rule path.

---

## Phase 4 — Routing + Side Effects

**Goal:** decide who gets it and (stub out) telling the world. **Concepts:** tools layer
isolation, stubbing external I/O (Explained §4, §2.5).

### Step 4.1 — Assign node  →  `app/agent/nodes/assign.py`
`assign_defect`: map component → team → developer with a static dict (easy to swap for a
config file later). Have a sensible default for unknown components.

> **Prompt to use:** *"Implement `app/agent/nodes/assign.py`: map component → team →
> developer with a static dict (make it easy to swap for a config file later), with a
> default for unknown components. Add a unit test."*

**Test / Done when:** unit test maps a known component to the right team/dev and an
unknown one to the default.

### Step 4.2 — Side-effect nodes + tool stubs  →  `escalate.py`, `flag_dup.py`, `notify.py`
Implement the three side-effect nodes. Put the actual Jira/Slack/email calls behind
`app/tools/` (`jira_tool.py`, `slack_tool.py`) as **stubs with clear TODOs**, so the graph
runs end-to-end with no live credentials. Log via structlog; **never log raw image data**.

> **Prompt to use:** *"Implement `escalate.py`, `flag_dup.py`, and `notify.py`. Stub the
> Jira/Slack/email integrations behind `app/tools/` with clear TODOs so the graph runs
> end-to-end without live credentials. Log actions via structlog; never log raw image data."*

**Test / Done when:** each node appends its breadcrumb and returns the right status;
tool stubs are call-logged, not making real network calls.

---

## Phase 5 — Wire It Together + Expose It

**Goal:** a runnable graph and a web endpoint. **Concepts:** StateGraph, conditional
edges, RetryPolicy, FastAPI (Explained §2.5, §4).

### Step 5.1 — The graph  →  `app/agent/graph.py`
Wire all nodes and edges **exactly** as in the plan: the two routing functions
(`route_after_check`, `route_severity`), the conditional edges, and
`RetryPolicy(max_attempts=3)` on the two LLM nodes.

> **Prompt to use:** *"Implement `app/agent/graph.py` exactly as in the plan (nodes,
> conditional edges, retry policies). Confirm it compiles and a smoke run of one fixture
> reaches END."*

**Test / Done when:** `build_graph()` compiles; pushing scenario #2 (the LOW staging bug)
through reaches END with the expected route.

### Step 5.2 — The API  →  `app/api/routes.py`
FastAPI app with `POST /triage` that accepts a defect payload, runs the graph, returns
the final state.

> **Prompt to use:** *"Implement `app/api/routes.py`: a FastAPI app with `POST /triage`
> that accepts a defect payload, runs the graph, and returns the final state. Add a smoke
> test with TestClient."*

**Test / Done when:** `uvicorn app.api.routes:app --reload` starts; a `POST /triage` with a
sample defect returns a populated final state with `triage_notes`.

---

## Phase 6 — Prove It Works

**Goal:** confidence against the plan's targets. **Concepts:** unit vs. integration tests,
evaluation metrics (Explained §6).

### Step 6.1 — Integration tests (the 5 scenarios)
Push each scenario in `sample_defects.json` through the compiled graph and assert the
expected **route** and **severity** from the plan's test table. Seed the vector store first
so scenarios #3 and #4 (duplicate/regression) work.

> **Prompt to use:** *"Write an integration test that seeds the vector store, then pushes
> each scenario in `tests/fixtures/sample_defects.json` through the compiled graph and
> asserts the expected route and severity from the plan's test table."*

**Test / Done when:** all 5 scenarios pass — critical→escalate, low, duplicate-shortcut,
regression, multimodal.

### Step 6.2 — Full suite + metrics
Run everything, fix failures, and report coverage against the targets.

> **Prompt to use:** *"Run the full test suite, fix failures, and report results against the
> plan's targets: severity ≥ 90%, duplicate precision ≥ 95%, assignment ≥ 85%, latency < 10s."*

**Test / Done when:** `pytest` is green; you have a short report of where you stand vs. the
four targets.

---

## Dependency Map (what blocks what)

```
Phase 0 (setup)
   │
   ▼
Phase 1  vector_store ──► seed_script
   │
   ▼
Phase 2  intake ──► duplicate    (duplicate needs the vector store from Phase 1)
   │
   ▼
Phase 3  analyze ──► prioritize
   │
   ▼
Phase 4  assign + side-effect nodes (+ tool stubs)
   │
   ▼
Phase 5  graph ──► api           (graph needs ALL nodes from Phases 2–4)
   │
   ▼
Phase 6  integration tests ──► metrics report
```

You *can* build the nodes in Phase 3/4 in any order since they're independent, but the
graph (5.1) can't be wired until every node exists. Build bottom-up; the graph snaps
together cleanly at the end.

---

## Per-Step Definition of Done (apply to every step)

1. Code follows the **node contract**: takes `state`, returns a *partial* dict, never
   mutates state in place.
2. Appends a `"[node_name] what happened"` breadcrumb to `triage_notes`.
3. Has at least one passing test (unit for nodes/tools, integration for the graph).
4. External I/O stays behind `app/tools/`; secrets only from env vars; no raw image/PII logging.
5. Matches the plan's contract exactly where the plan specifies it — flag any deviation.
6. Commit it (`git add -A && git commit -m "..."`) before starting the next step.
