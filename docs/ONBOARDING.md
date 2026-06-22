# Onboarding — DefectTriageBot

> **Audience:** anyone picking this project up for the first time — teammate,
> reviewer, or AI coding agent. This is the **orientation map**: what to read in
> what order, where each piece of code lives, and where to look when something
> goes wrong. It deliberately does *not* repeat the spec, the architecture, or
> the run steps — it points you to them.

---

## 1. Read these in this order

1. **This file** — orientation.
2. [ARCHITECTURE.md](ARCHITECTURE.md) — how the system is structured and *why*.
3. [DATA_FLOW.md](DATA_FLOW.md) — how one defect travels end to end.
4. [INSTALL.md](INSTALL.md) — get it running, then send a defect through it.
5. [RUNBOOK.md](RUNBOOK.md) — demo it, troubleshoot it.
6. [HANDOFF.md](HANDOFF.md) — current build status and ADLC phase log.

The 30-second version: it's a **defect triage agent** — reachable via a React UI
or `POST /triage` directly. You **fetch a defect from Jira by ID** (or enter it
manually); it checks whether the bug is already known (no LLM), asks Gemini for root
cause and severity, picks the right team, **pauses for a human to choose the
assignee**, then **writes the result back to Jira** and streams every step to the UI
in real time. **Jira is live** (fetch, write-back, create); Slack/email/on-call are
still stubs, ready to be wired with real credentials.

---

## 2. Code map

All Python code lives under `app/`. The public entry point is
`app.api.routes` (FastAPI). The frontend lives in `frontend/`.

| File / folder | Role |
|---------------|------|
| `app/agent/state.py` | `TriageState` — shared dict (incl. `source_jira_key`, `jira_key`, `jira_url`, `warnings`) |
| `app/agent/graph.py` | `build_graph(checkpointer)` — wires nodes + edges + retries; API passes `MemorySaver()` |
| `app/agent/nodes/intake.py` | Normalize input, validate image attachments |
| `app/agent/nodes/duplicate.py` | Vector similarity search — duplicate / regression / new |
| `app/agent/nodes/analyze.py` | LLM (Gemini) — root cause, category, component |
| `app/agent/nodes/prioritize.py` | LLM — severity + priority; rule override + fallback |
| `app/agent/nodes/assign.py` | Component → team, then `interrupt()` for human assignee pick |
| `app/agent/nodes/escalate.py` | Page on-call for CRITICAL (stub — logs only) |
| `app/agent/nodes/flag_dup.py` | Create + close a duplicate Bug in Jira (live) |
| `app/agent/nodes/notify.py` | Update the source Jira issue, or create a Bug (live) + Slack/email (stubs) |
| `app/tools/llm.py` | `get_llm()` — Gemini 2.5 Flash (dev) / Claude Sonnet 4.6 (prod) |
| `app/tools/vector_store.py` | ChromaDB wrapper — `similarity_search_with_score` |
| `app/tools/certs.py` | Corporate-TLS bootstrap (auto-detects `certs/corp-ca-bundle.pem`) |
| `app/tools/parsing.py` | Defensive JSON extraction from LLM output |
| `app/tools/jira_tool.py` | Jira REST v3 — **live**: `get_issue`, `create_issue`, `update_issue`, `add_comment`, `transition_to`, `get_jira_status`, `warning_for` |
| `app/tools/assignees.py` | Candidate assignee lookup (live Jira assignable users, else static roster) |
| `app/tools/slack_tool.py` / `email_tool.py` / `oncall_tool.py` | Slack / email / on-call **stubs** |
| `app/api/routes.py` | FastAPI: `POST /triage` + `/triage/resume` (SSE), `GET /health`, `GET /jira/status`, `GET /jira/issue/{key}`, serves React UI |
| `scripts/seed_vector_store.py` | One-time loader: `seed_backlog.json` → ChromaDB |
| `scripts/jira_check.py` | Jira connectivity/discovery check (projects, issue types, priorities) |
| `scripts/evaluate.py` | Metrics runner: severity accuracy, dup precision, latency |
| `tests/unit/` | Per-node + tool + API tests, mocked (82 tests, no key needed) |
| `tests/integration/` | Full graph, live Gemini (5 canonical scenarios) |
| `tests/fixtures/` | `sample_defects.json` (5 scenarios) + `seed_backlog.json` |
| `frontend/` | React 18 + Vite UI — `src/api.js`, `App.jsx`, `components/` (DefectForm, LogFeed, ResultPanel, AssignmentModal, ErrorModal, Toasts) |
| `docs/` | All documentation (you are here) |

---

## 3. Where to look when…

- *"Why did it call this a duplicate?"* → `app/agent/nodes/duplicate.py`
  (`SIMILARITY_THRESHOLD = 0.80`, `RESOLVED_STATUSES`). Check the score in the
  `triage_notes` field of the response.
- *"Why did it rate this CRITICAL?"* → `app/agent/nodes/prioritize.py`
  (`CRITICAL_KEYWORDS`). If the keyword override fired, the note says "rule override".
- *"Why was it assigned to the wrong team?"* → `app/agent/nodes/assign.py`
  (`TEAM_ROUTING` table). The component string from the LLM drives the match.
- *"The LLM returned garbage / no JSON"* → `app/tools/parsing.py` and the
  `triage_notes` WARN breadcrumb in the response. `analyze` and `prioritize` both
  degrade gracefully.
- *"How does the streaming work?"* → `app/api/routes.py` (`astream`) and
  `frontend/src/api.js` (`triageDefectStream`). See [API_REFERENCE.md](API_REFERENCE.md).
- *"How does Jira work (fetch / create / write-back)?"* → `app/tools/jira_tool.py`
  (`get_issue` to fetch, `create_issue`/`update_issue`/`add_comment` to write).
  `notify` updates the source issue when `source_jira_key` is set, else creates a Bug.
  Verify connectivity with `python scripts/jira_check.py`. Config in [CONFIGURATION.md](CONFIGURATION.md).
- *"Why did a pop-up ask me to pick an assignee?"* → `app/agent/nodes/assign.py`
  calls `interrupt()` with candidates from `app/tools/assignees.py`. The API emits
  `assignment_required`; the UI resumes via `POST /triage/resume`. See [DATA_FLOW.md](DATA_FLOW.md).
- *"Why a warning toast / blocking error modal?"* → `jira_tool.warning_for` (non-fatal
  Jira failures → `warning` SSE) and the Gemini-quota `error` SSE in `routes.py`. UI in
  `frontend/src/components/{Toasts,ErrorModal}.jsx`.
- *"How do I wire real Slack/email?"* → `app/tools/slack_tool.py`,
  `app/tools/email_tool.py` — each has a clear `# TODO` where the HTTP call goes.
- *"How is a test written for a node?"* → `tests/unit/test_intake.py` or
  `tests/unit/test_duplicate.py` as worked examples. See [TESTING.md](TESTING.md).

---

## 4. Common tasks — which doc tells you how

| You want to… | Go to |
|---|---|
| Get the project running from scratch | [INSTALL.md](INSTALL.md) |
| Run a demo / send a defect | [RUNBOOK.md](RUNBOOK.md) |
| Change the similarity threshold or image caps | [CONFIGURATION.md](CONFIGURATION.md) |
| Add a new team to the routing table | [CONFIGURATION.md](CONFIGURATION.md) → `assign_defect` |
| Wire real Jira / Slack / email integrations | `app/tools/jira_tool.py` etc. + [CONFIGURATION.md](CONFIGURATION.md) |
| Understand the `POST /triage` SSE response | [API_REFERENCE.md](API_REFERENCE.md) |
| Run or write tests | [TESTING.md](TESTING.md) |
| See the full triage flow for a defect | [DATA_FLOW.md](DATA_FLOW.md) |
| Check ADLC phase build status | [HANDOFF.md](HANDOFF.md) |
| Present the architecture | `docs/architecture-flowchart.svg` / `.png` |

---

## 5. House rules

1. [PROJECT_PLAN.md](PROJECT_PLAN.md) is the formal ADLC spec — the source of
   truth for behavior. Do not deviate without flagging the change in
   [HANDOFF.md](HANDOFF.md) and [CLAUDE.md](../CLAUDE.md).
2. **Every node takes `state: TriageState` and returns a partial dict of only the
   keys it changed.** Never mutate state in place — LangGraph merges the result.
3. **All external I/O lives in `app/tools/`** — nodes must not make HTTP calls
   directly. This is what keeps them unit-testable.
4. **Never commit `.env` or any real key.** `.gitignore` covers it.
5. Keep `pytest tests/unit` green before merging anything.
