# DefectTriageBot — The Whole Project Explained From Basics

> A personal study guide. This explains *what* we're building, *why* every piece
> exists, and the *concepts* behind them — assuming no prior knowledge of LLM
> agents, LangGraph, or vector databases. Read top to bottom once; after that use
> it as a reference. This is a companion to `PROJECT_PLAN.md` (the formal spec) and
> `HANDOFF.md` (the build-it-in-phases checklist).

---

## Part 1 — The Problem, In Plain English

A "defect" is just a bug report. In a real software team, bug reports pour in from
customers, QA testers, monitoring tools, and developers. Before anyone can *fix* a
bug, someone has to **triage** it — like a hospital emergency room sorting patients:

1. **Is this even new?** Maybe five people already reported the same crash. (duplicate)
2. **Didn't we already fix this?** Maybe a bug we closed months ago came back. (regression)
3. **How bad is it?** A typo on a settings page is not the same as payments being down. (severity)
4. **Whose problem is it?** The auth team? The frontend team? (assignment)
5. **Who needs to know right now?** If it's critical, page the on-call engineer. (escalation/notification)

Doing this by hand takes a senior person ~45 minutes per bug, and they're
inconsistent — two people rate the same bug differently. Duplicates pile up (~18%
of the backlog is junk), and ~30% of bugs get sent to the wrong team and bounce
around.

**The goal:** an automated agent that does all five triage steps in under 2 minutes,
consistently. That's DefectTriageBot.

---

## Part 2 — The Core Concepts (the vocabulary you need)

### 2.1 What is an "LLM"?

A **Large Language Model** (LLM) like Claude or Gemini is a program that, given text,
predicts useful text back. You can ask it to "read this bug report and tell me the root
cause and which component is affected," and it answers in natural language — or, if you
ask nicely, in a strict format like JSON. **Production uses Claude Sonnet 4.6**, but for
**local development and testing this project is currently wired to Google Gemini 1.5
Flash** (cheaper/faster to iterate). Both are multimodal, so the flow is identical; only
the client in `app/tools/llm.py` differs.

Two important traits we rely on:
- **It can read images too** ("multimodal"). We can hand it a screenshot of a UI glitch
  and it understands it. That's why bug attachments matter.
- **It is not deterministic and not perfect.** It can be wrong about severity. That's
  why we add *rule-based overrides* and *fallbacks* (more later). Never blindly trust an LLM.

### 2.2 What is an "embedding" and why do we need it?

To find duplicate bugs, we can't just check if two reports use the exact same words —
"app crashes on login" and "login screen freezes and dies" are the same bug in
different words.

An **embedding** is a way to turn a piece of text into a list of numbers (a "vector",
e.g. 1,536 numbers) that captures its *meaning*. Texts with similar meaning get
similar number-lists. Production uses OpenAI's **text-embedding-3-small**; local dev
uses Google's **gemini-embedding-001** (because OpenAI's API is blocked on the corporate
network). Either way the idea is identical — text in, meaning-vector out.

Once both bugs are vectors, we measure how "close" they are. Close vectors = similar
meaning = likely duplicate. The closeness number is a **similarity score** between
0 (unrelated) and 1 (identical).

> **Our magic threshold is `0.80`.** At or above 0.80, we call it a match. Below, we
> treat it as a different bug. (This was recalibrated from the plan's original 0.88, which
> was tuned for OpenAI embeddings; with this POC's Gemini `gemini-embedding-001`, real
> matches score ~0.81–0.85 and unrelated bugs ≤0.70, so 0.80 — the industry-standard cosine
> cutoff — cleanly separates them. Thresholds are embedding-model-specific.)

### 2.3 What is a "vector store"?

A **vector store** (we use **ChromaDB** locally) is a database built to hold those
number-lists and answer one question fast: *"Here's a new vector — which stored
vectors are most similar to it?"* That's the `similarity_search_with_score` call you'll
see everywhere. We pre-load ("seed") it with our existing backlog of bugs so new bugs
have something to be compared against.

### 2.4 Duplicate vs. Regression — the key distinction

Both mean "this new bug looks like an old one we have on file." The difference is the
**status** of the old one:

- If the old matching bug is still **OPEN** → this is a **DUPLICATE**. Don't waste the
  LLM's time analyzing it; just link it to the original and stop.
- If the old matching bug was already **RESOLVED / CLOSED / DONE** → this is a
  **REGRESSION** — a bug we thought we killed has come back. This is *serious* and
  needs full analysis, so it proceeds like a new bug (but flagged as a regression).

This is why the duplicate check happens **before** any expensive LLM call — to
short-circuit obvious duplicates early.

### 2.5 What is an "agent" and what is "LangGraph"?

An **agent** here just means: a program that takes a bug through a series of decision
steps automatically. Our agent isn't one giant function — it's a **graph** of small
steps called **nodes**, wired together with arrows called **edges**.

**LangGraph** is the library that lets us define this graph. Think of it as a flowchart
you can actually run:

- Each **node** is a small Python function that does one job (parse input, check
  duplicates, ask the LLM, etc.).
- **Edges** connect nodes — "after this, go to that."
- **Conditional edges** are forks in the road — "if it's a duplicate go *here*,
  otherwise go *there*."
- All nodes share one common clipboard of data called the **state**.

### 2.6 The "state" — the shared clipboard

Every node reads from and writes to a single shared dictionary called **`TriageState`**
(defined in `app/agent/state.py`, already written). It holds everything known about the
bug as it travels through the graph: its title, description, the duplicate verdict, the
severity, the assigned team, and a running **audit log** (`triage_notes`).

Two rules that matter (they're project conventions):
1. **A node never edits the state in place.** It *returns* a small dictionary of only the
   fields it changed, and LangGraph merges that in. This keeps steps isolated and testable.
2. **Some fields are "append-only" lists** (like `triage_notes`). When a node returns one
   of these, LangGraph *adds to* the list rather than replacing it. That's how every node
   leaves a breadcrumb and we get a complete audit trail. (In code this is the
   `Annotated[list, operator.add]` you see in the schema.)

---

## Part 3 — The Flow, Step By Step

Here's the journey of a single bug report through the graph. Follow the arrows:

```
START
  │
  ▼
intake_defect      ← clean up the raw input, pull out any image attachments
  │
  ▼
check_duplicate    ← turn it into a vector, search the backlog
  │
  ├──── is an OPEN duplicate? ───────────────► flag_duplicate ──► END
  │                                            (link to original, stop. LLM never runs.)
  │
  └──── new bug OR a regression? ──► analyze_defect   ← ask Claude: root cause? category? component?
                                          │              (sends images too, if any)
                                          ▼
                                     prioritize        ← ask Claude: severity + priority 1–4
                                          │              (plus rule-based override, see below)
                                          │
                       ┌── severity == CRITICAL? ──► escalate  ← page the on-call engineer
                       │                                  │
                       │                                  ▼
                       └── HIGH / MEDIUM / LOW ──────► assign_defect  ← route to the right team + dev
                                                          │
                                                          ▼
                                                       notify         ← update Jira, ping Slack, email
                                                          │
                                                          ▼
                                                         END
```

### What each node does and *why*

| Node | Uses LLM? | What it does | Why it exists |
|------|:---------:|--------------|---------------|
| **intake_defect** | No | Reads the raw bug payload, normalizes fields, separates out image attachments into state. | Garbage in, garbage out. Clean the input once so every later node can trust it. |
| **check_duplicate** | No | Embeds the title+description, searches the vector store, applies the 0.80 rule and the open-vs-resolved rule. | Catches duplicates *before* spending money/time on the LLM. Distinguishes regressions. |
| **flag_duplicate** | No | Links the new bug to its original parent ticket and closes it as a duplicate. | The dead-end for duplicates — no further work needed. |
| **analyze_defect** | **Yes** | Sends text (and any images) to Claude, gets back root cause, category, component as JSON. | This is the "understanding" step. Multimodal so screenshots help. |
| **prioritize** | **Yes** | Asks Claude for severity (CRITICAL/HIGH/MEDIUM/LOW) and priority (1–4). Then a rule-based safety net forces CRITICAL for danger keywords. | Severity drives everything downstream. The LLM can under-rate a real emergency, so rules back it up. |
| **escalate** | No | Pages the on-call engineer for CRITICAL bugs only. | Humans must be woken up for true emergencies, fast. |
| **assign_defect** | No | Maps component → team → a specific developer using a lookup table. | Gets the bug to the people who can fix it, avoiding the 30% mis-routing. |
| **notify** | No | Posts the outcome to Jira, Slack, and email. | Close the loop so stakeholders know what happened. |

### Why these specific design choices

- **Duplicate check is first and LLM-free** → saves time and money on the ~18% that are junk.
- **Regression ≠ duplicate** → a returning bug is dangerous and deserves full analysis,
  not a quick "dupe, ignore."
- **Two LLM nodes, not one** → "understand the bug" and "rate its urgency" are different
  jobs; keeping them separate makes each prompt simpler and each node easier to test.
- **A rule-based override on severity** → the single most expensive mistake is calling a
  real outage "LOW." Hard-coded keyword rules are a cheap insurance policy on top of the LLM.
- **Side-effect nodes (escalate/notify) are last and isolated** → we don't page people or
  spam Slack until the decision is final, and we keep all external calls behind a tools
  layer so we can test the brain without actually emailing anyone.

---

## Part 4 — The Architecture (how the code is organized)

```
defect-triage-agent/
├── app/
│   ├── agent/
│   │   ├── state.py          ← the shared clipboard (TriageState). DONE.
│   │   ├── graph.py          ← wires all nodes + edges into a runnable graph
│   │   └── nodes/            ← one file per step in the flow
│   │       ├── intake.py
│   │       ├── duplicate.py
│   │       ├── analyze.py
│   │       ├── prioritize.py
│   │       ├── assign.py
│   │       ├── escalate.py
│   │       ├── flag_dup.py
│   │       └── notify.py
│   ├── tools/                ← all "talking to the outside world" lives here
│   │   ├── llm.py            ← shared chat-model client (Gemini dev / Claude prod)
│   │   ├── vector_store.py   ← ChromaDB wrapper (embeddings + similarity search)
│   │   ├── certs.py          ← corporate-TLS bootstrap (trusts the proxy CA bundle)
│   │   ├── jira_tool.py      ← (stub) update Jira tickets
│   │   ├── slack_tool.py     ← (stub) post to Slack
│   │   ├── email_tool.py     ← (stub) send email
│   │   └── oncall_tool.py    ← (stub) page on-call
│   └── api/
│       └── routes.py         ← FastAPI: POST /triage + serves the React UI at /
├── scripts/
│   ├── seed_vector_store.py  ← one-time loader: backlog JSON → vector store
│   └── evaluate.py           ← metrics runner (severity/dup/assignment/latency)
├── frontend/                 ← React 18 + Vite UI (post-v1 addition; thin client over /triage)
│   └── src/                  ← App.jsx, DefectForm, ResultPanel, api.js
├── tests/
│   ├── unit/                 ← per-node tests (mocked LLM + store)
│   ├── integration/          ← full graph, live (5 scenarios)
│   └── fixtures/             ← canned test data (the 5 scenarios + the backlog)
└── docs/                     ← you are here
```

**The golden rule of the layout:** *brain* (nodes/graph) is kept separate from *hands*
(tools that touch Jira/Slack/the vector DB). This is what makes the nodes unit-testable —
in tests we swap the real hands for fake ones ("mocks") so no real emails get sent and no
real LLM is called.

### Why each technology was chosen
- **LangGraph** — gives us the flowchart-you-can-run model, plus built-in retries
  (`RetryPolicy`) for the flaky LLM steps.
- **Claude Sonnet 4.6 (prod) / Gemini 2.5 Flash (dev)** — big context window (handles
  giant stack traces), reliable JSON output, reads images, cost-effective. The LLM client
  is isolated in `app/tools/llm.py`, so dev runs on Gemini and prod on Claude without
  touching any node. Set `GOOGLE_API_KEY` for the Gemini dev client.
- **Embeddings (Gemini dev / OpenAI prod)** — turn defect text into vectors for the
  similarity search. Isolated in `app/tools/vector_store.py` (injectable embedder), so the
  swap touches one place. ⚠️ Score scales differ by model, so the match threshold (0.80
  here) is calibrated for the embedding model in use.
- **React + Vite frontend** (`frontend/`) — a small single-page UI to submit a defect and
  see the triaged result. It's a *thin client* over `POST /triage` (no logic of its own), so
  the "brain vs. hands" rule still holds. Served by FastAPI at `/` in production, or via the
  Vite dev server (with an API proxy) during development. Added beyond the original v1 scope.
- **ChromaDB** — runs locally with zero setup for development; can swap to Pinecone in the
  cloud later without changing the node code (because it's behind the tools layer).
- **FastAPI** — turns the graph into a web service with a `POST /triage` endpoint.
- **LangSmith / structlog / Sentry** — observability: trace what the LLM did, log each
  node, catch crashes.

---

## Part 5 — The Data (what we test against)

We do **not** train a model — Claude is already trained. We only need *evaluation* data:
example bugs with known-correct answers, to check the agent triages them right.

Two fixture files drive all the tests:

- **`tests/fixtures/seed_backlog.json`** — the "already known" bugs we load into the vector
  store first. Most important entries:
  - `DEF-101` (status **OPEN**) — a checkout 500 error. New bugs that match it should be
    flagged **duplicates**.
  - `DEF-050` (status **CLOSED**) — a login race condition. New bugs that match it should be
    flagged **regressions**.
- **`tests/fixtures/sample_defects.json`** — the 5 canonical incoming bugs we push through
  the graph, each with an `expected` block (the ground-truth answer the test asserts against):

| # | Scenario | Expected result | Path it should take |
|---|----------|-----------------|---------------------|
| 1 | Payment service down in prod, all users | **CRITICAL** | intake → dup → analyze → prioritize → **escalate** → assign → notify |
| 2 | Button 3px misaligned in staging | **LOW** | intake → dup → analyze → prioritize → assign → notify |
| 3 | Promo-code 500 (matches OPEN DEF-101) | **duplicate** | dup → **flag_duplicate** → END (LLM skipped!) |
| 4 | Random logouts (matches CLOSED DEF-050) | **regression**, HIGH | dup → analyze (as regression) → prioritize → assign → notify |
| 5 | UI glitch with a screenshot | **LOW** | dup → analyze (**multimodal**) → prioritize → assign → notify |

These five cover every branch in the graph: critical/escalate, normal, duplicate-shortcut,
regression, and multimodal. If all five pass, the whole flow works.

> Public datasets (Bugzilla, Eclipse/Mozilla on Kaggle) exist and are good for *severity*
> and *assignment* testing at scale — but they don't ship duplicate pairs, regression labels,
> or screenshots, which is exactly what this agent specializes in. Hence our hand-built
> fixtures. Details in `docs/DATA.md`.

---

## Part 6 — How We Know It Works (testing & targets)

Two layers of tests:
- **Unit tests** — test one node at a time, with the LLM and vector store *mocked* (faked).
  Fast, free, deterministic. This is where most of the testing lives.
- **Integration tests** — push the 5 fixtures through the *whole* compiled graph end-to-end.
  May hit the live LLM.

The plan's success targets:

| Metric | Target | Plain meaning |
|--------|--------|---------------|
| Severity accuracy | ≥ 90% | It rates urgency like an expert would, 9 times out of 10. |
| Duplicate precision | ≥ 95% | When it says "duplicate," it's right 95%+ of the time (few false alarms). |
| Assignment accuracy | ≥ 85% | It picks the right team 85%+ of the time. |
| Avg. triage latency | < 10 s | One bug goes through the whole graph in under 10 seconds. |

---

## Part 7 — The Safety Nets (risks & how we handle them)

This is mostly *why* certain "extra" code exists. None of it is decoration.

| Risk | Our mitigation | Where it lives |
|------|----------------|----------------|
| LLM rates a real emergency too low | Rule-based keyword override forces CRITICAL ("payment down", "outage", "data loss", "all users") | `prioritize.py` |
| False-positive duplicate | Threshold (0.80) sits in the clean gap between real matches (~0.81–0.85) and noise (≤0.70); tune per embedding model | `check_duplicate` threshold logic |
| Regression mistaken for a new bug | We store each bug's *status* in the vector store metadata; RESOLVED/CLOSED ⇒ regression | `seed_vector_store.py` + `duplicate.py` |
| Huge images slow everything down | Cap at 5 MB/image, max 3 images; strip unsupported formats | `intake.py` |
| LLM returns broken JSON | Parse defensively in try/except; `RetryPolicy(max_attempts=3)` retries; fall back to rule-based path | `analyze.py`, `prioritize.py`, `graph.py` |
| LLM provider outage | Fall back to the rule-based classifier | `prioritize.py` |
| Jira API rate limits | Exponential backoff + request queue | `jira_tool.py` |
| PII / secrets in reports or screenshots | Scrub PII from text; **never log raw image data** | tools layer + logging config |

---

## Part 8 — A Glossary, For Quick Reference

- **Defect** — a bug report.
- **Triage** — sorting/prioritizing bugs before they get fixed.
- **LLM** — Large Language Model (Claude); reads text/images, returns text.
- **Multimodal** — the LLM can take images as well as text.
- **Embedding** — text turned into a list of numbers that captures its meaning.
- **Vector store** — a database that finds the most-similar stored vectors fast (ChromaDB).
- **Similarity score** — 0-to-1 number for how alike two texts are; ≥ 0.80 = match here.
- **Duplicate** — new bug matches an OPEN existing one → short-circuit, no LLM.
- **Regression** — new bug matches a RESOLVED/CLOSED one → a fixed bug came back → full analysis.
- **Agent** — a program that walks a bug through automated decision steps.
- **LangGraph** — the library for defining that walk as a graph of nodes + edges.
- **Node** — one step/function in the graph.
- **Edge** — a connection between nodes; **conditional edge** = a fork based on the state.
- **State (`TriageState`)** — the shared dictionary every node reads/writes.
- **Reducer / append-only field** — a state field where returns get *added* to a list
  (e.g. `triage_notes`) instead of overwriting.
- **Node contract** — the rule that every node takes `state` and returns a *partial* dict.
- **Mock** — a fake stand-in for a real service (LLM, Jira) used in tests.
- **RetryPolicy** — LangGraph's built-in "try this node up to N times if it fails."
- **Seeding** — pre-loading the vector store with the existing backlog.
- **FastAPI / uvicorn** — the web framework / server that exposes `POST /triage` (and serves the UI).
- **Frontend (React + Vite)** — the browser UI in `frontend/` for submitting defects and viewing results; a thin client over the API.
- **Vite proxy** — in dev, the Vite server forwards `/triage` + `/health` calls to the backend so there's no CORS.
- **LangSmith / structlog / Sentry** — tracing / structured logging / crash reporting.

---

*Next: open `docs/HANDOFF.md` to build it, one phase at a time.*
