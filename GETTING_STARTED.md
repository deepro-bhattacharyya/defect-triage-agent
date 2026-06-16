# Getting Started

This guide takes you from an empty folder to a working DefectTriageBot, using
Claude Code to do the heavy lifting. Follow it top to bottom.

---

## 0. What's already in this folder

```
defect-triage-agent/
├── CLAUDE.md                 # context Claude Code reads automatically — the project's brain
├── GETTING_STARTED.md        # this file
├── requirements.txt          # Python dependencies
├── .env.example              # template for your secrets
├── .gitignore
├── docs/
│   ├── PROJECT_PLAN.md        # the approved plan (your original README) — the spec
│   └── DATA.md                # dataset findings + how to wire real/synthetic data
├── app/
│   └── agent/state.py         # TriageState schema — fully implemented, ready to use
├── scripts/                   # (Claude Code will fill: seed_vector_store.py)
└── tests/
    └── fixtures/
        ├── sample_defects.json   # 5 canonical test scenarios
        └── seed_backlog.json     # existing defects for duplicate/regression matching
```

Everything else (the nodes, the graph, the API, the tools) is built by Claude Code,
guided by `CLAUDE.md` and `docs/PROJECT_PLAN.md`.

---

## 1. Prerequisites

- **Python 3.11+** — check with `python --version`
- **Git** — to version-control the project
- **API keys**: an Anthropic API key (for Claude) and an OpenAI key (for embeddings).
  Optionally a LangSmith key for tracing.
- **A Claude plan that includes Claude Code**: Pro, Max, Team, Enterprise, or a
  pay-as-you-go Anthropic Console (API) account. The free plan does not include Claude Code.

---

## 2. Install Claude Code

Anthropic's **recommended method is the native installer** (no Node.js needed, auto-updates):

- **macOS / Linux:**
  ```bash
  curl -fsSL https://claude.ai/install.sh | bash
  ```
- **Windows (PowerShell):**
  ```powershell
  irm https://claude.ai/install.ps1 | iex
  ```

Prefer npm (needs Node.js 18+)? `npm install -g @anthropic-ai/claude-code` works too.

Then verify and authenticate:
```bash
claude --version          # confirm it's on your PATH
cd defect-triage-agent
claude                    # first launch opens a browser to log in
```
If anything looks off, run `claude doctor` — it diagnoses install/auth/config issues.

> Always check the official docs for the latest commands:
> https://docs.claude.com/en/docs/claude-code/overview

---

## 3. Set up the project environment

```bash
cd defect-triage-agent

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env                # then open .env and paste your real keys
```

---

## 4. Drive Claude Code through the build

Open Claude Code in this folder (`claude`). It reads `CLAUDE.md` automatically, so it
already knows the architecture and build order. Work **one step at a time** and review
its changes before approving — don't ask it to build everything in one shot.

Paste these prompts in order. Each maps to a step in the build order in `CLAUDE.md`.

**Step 1 — orient**
> Read CLAUDE.md and docs/PROJECT_PLAN.md. Summarize the architecture back to me and
> list the files you'll create, in build order. Don't write code yet.

**Step 2 — vector store tool**
> Implement `app/tools/vector_store.py`: a ChromaDB wrapper exposing a
> `get_vector_store()` and `similarity_search_with_score(query, k)` matching how
> `check_duplicate` uses it in the plan. Use OpenAI `text-embedding-3-small`. Add a unit
> test with a mocked embedder.

**Step 3 — seed script**
> Write `scripts/seed_vector_store.py` that loads `tests/fixtures/seed_backlog.json`
> into the vector store, storing `defect_id` and `status` in each document's metadata.

**Step 4 — intake node**
> Implement `app/agent/nodes/intake.py` (`intake_defect`) per the plan: validate input
> and extract image attachments into state. No LLM. Add a unit test.

**Step 5 — duplicate/regression node**
> Implement `app/agent/nodes/duplicate.py` (`check_duplicate`) exactly as specified in
> the plan, including the 0.88 threshold and RESOLVED/CLOSED → regression logic. Add unit
> tests using `seed_backlog.json` covering: open-duplicate, resolved-regression, and no-match.

**Step 6 — analyze node (multimodal)**
> Implement `app/agent/nodes/analyze.py` (`analyze_defect`) per the plan: build multimodal
> content (text + base64 images), call Claude Sonnet 4.6, parse strict JSON, handle the
> regression note. Mock the LLM in tests.

**Step 7 — prioritize node**
> Implement `app/agent/nodes/prioritize.py`: LLM severity + priority, PLUS a rule-based
> override that forces CRITICAL on known keywords (e.g. "payment down", "data loss",
> "outage", "all users"). Add unit tests.

**Step 8 — assign node**
> Implement `app/agent/nodes/assign.py`: map component → team → developer with a static
> dict for now (make it easy to swap for a config file later). Add a unit test.

**Step 9 — side-effect nodes**
> Implement `escalate.py`, `flag_dup.py`, and `notify.py`. Stub the Jira/Slack/email
> integrations behind `app/tools/` with clear TODOs so the graph runs end-to-end without
> live credentials. Log actions via structlog; never log raw image data.

**Step 10 — wire the graph**
> Implement `app/agent/graph.py` exactly as in the plan (nodes, conditional edges, retry
> policies). Then run an integration test that pushes each scenario in
> `tests/fixtures/sample_defects.json` through the compiled graph and asserts the expected
> route and severity from the plan's test table.

**Step 11 — API**
> Implement `app/api/routes.py`: a FastAPI app with `POST /triage` that accepts a defect
> payload, runs the graph, and returns the final state. Add a smoke test with TestClient.

**Step 12 — close the loop**
> Run the full test suite, fix failures, and report coverage against the plan's targets
> (severity ≥90%, duplicate precision ≥95%, assignment ≥85%, latency <10s).

Tip: after each step, commit (`git add -A && git commit -m "..."`) so you can roll back.

---

## 5. About test data (you asked)

You don't need to train anything — this agent uses a pre-trained LLM (Claude), so there's
**no training step**. You only need *evaluation* data to check it triages correctly.

- **Public datasets do exist** on Kaggle and elsewhere (Bugzilla, Eclipse/Mozilla defect
  tracking, BugsRepo) and are great for testing **severity** and **assignment** accuracy
  at scale. Details and links are in `docs/DATA.md`.
- **But** none of them ship ready-made *duplicate pairs*, *regression* labels, or *image
  attachments* — exactly the scenarios this agent is built around. So this repo ships
  **hand-built fixtures** (`tests/fixtures/`) that cover all five canonical scenarios.

Start with the fixtures (they're enough to validate the whole flow), then optionally load
a slice of a public dataset later for a larger severity/assignment benchmark.

---

## 6. First thing to try once it's running

```bash
uvicorn app.api.routes:app --reload
# in another terminal:
curl -X POST localhost:8000/triage \
  -H "Content-Type: application/json" \
  -d @tests/fixtures/sample_defects.json    # or a single defect object
```

You should see the defect routed, classified, and the triage_notes audit trail populated.
