# Data Flow

How a single defect travels through the system, end to end. Follow the numbered
steps; worked examples at the bottom tie it together.

The primary input is **fetching a defect from Jira by ID** (`GET /jira/issue/{key}`),
which auto-fills the form; manual entry is the fallback when Jira isn't connected.
Either way the entry point is `POST /triage` in `app/api/routes.py`, which drives the
compiled graph via `_graph.astream()` and streams each step back as SSE. The run may
**pause** for human assignee selection and continue via `POST /triage/resume`.

---

## The pipeline at a glance

```
        browser / API client
               │
               ▼  POST /triage  (JSON body)
    ┌─────────────────────────┐
    │  FastAPI  routes.py     │  ← validates shape (Pydantic DefectIn)
    └────────────┬────────────┘
                 │  _graph.astream(payload)
                 ▼
    ┌─────────────────────────┐
    │  1. intake_defect       │  normalize fields, validate images
    └────────────┬────────────┘
                 │  triage_notes breadcrumb ──► SSE log event
                 ▼
    ┌─────────────────────────┐
    │  2. check_duplicate     │  embed query → search vector store
    └────────────┬────────────┘
                 │  breadcrumb ──► SSE log event
                 │
     ┌───────────┴───────────┐
     │ match ≥ 0.80?         │
     ├── OPEN match          │──► flag_duplicate ──► SSE result ──► END
     ├── RESOLVED match      │──► is_regression = True → continue
     └── no match            │──► is_duplicate = False → continue
                             ▼
    ┌─────────────────────────┐
    │  3. analyze_defect  LLM │  multimodal prompt → JSON (category/component/root_cause)
    └────────────┬────────────┘
                 │  breadcrumb ──► SSE log event
                 ▼
    ┌─────────────────────────┐
    │  4. prioritize      LLM │  severity + priority; rule override; rule fallback
    └────────────┬────────────┘
                 │  breadcrumb ──► SSE log event
                 │
     ┌───────────┴───────────┐
     │ severity == CRITICAL? │
     └── yes ── escalate     │  page on-call (stub)
     └── no  ────────────────┤
                             ▼
    ┌─────────────────────────┐
    │  5. assign_defect       │  component → team, then PAUSE for human assignee pick
    └────────────┬────────────┘
                 │  breadcrumb ──► SSE log event
                 ▼
    ┌─────────────────────────┐
    │  6. notify              │  create Jira Bug (live) + Slack/email (stubs)
    └────────────┬────────────┘
                 │  breadcrumb ──► SSE log event
                 ▼
         SSE result event (full final TriageState)
```

---

## Step 1 — Receive & normalize (`intake_defect`)

`intake_defect` strips and normalizes every string field. It also enforces image
guardrails: **max 5 MB per image**, **max 3 images**, supported media types only
(`image/png`, `image/jpeg`, `image/gif`, `image/webp`). Oversized or unsupported
attachments are silently dropped and the count reported in the breadcrumb:
`[intake_defect] normalized DEF-901; kept 1 image(s), dropped 2`.

No LLM is called here. No call to the vector store. This step is purely defensive.

---

## Step 2 — Duplicate / regression check (`check_duplicate`)

**This runs before any LLM call.** Confirmed duplicates skip analysis entirely.

`check_duplicate` builds a query string `"{title} {description}"`, embeds it with
Gemini `gemini-embedding-001`, and queries the ChromaDB backlog for the top-5
closest vectors.

For each result, the score (cosine similarity, 0–1) is compared to `SIMILARITY_THRESHOLD = 0.80`:

| Score vs. threshold | Matched status (`metadata["status"]`) | Verdict | Effect |
|---------------------|---------------------------------------|---------|--------|
| `score < 0.80` | — | **NEW** | Proceed to analysis |
| `score ≥ 0.80` | `OPEN` | **DUPLICATE** | Short-circuit → `flag_duplicate` |
| `score ≥ 0.80` | `RESOLVED` / `CLOSED` / `DONE` | **REGRESSION** | `is_regression = True`, proceed to analysis |

The **regression distinction matters**: a bug you thought you fixed coming back is
serious and needs full analysis — it is *not* treated as a duplicate.

The backlog must be seeded before this works: `python scripts/seed_vector_store.py`.

---

## Step 3 — LLM root-cause analysis (`analyze_defect`)

`analyze_defect` builds a multimodal prompt:
- A text block with the defect title, description, and stack trace.
- If `is_regression=True`, a `[REGRESSION]` preamble telling Gemini to focus on
  what may have regressed.
- One `image_url` block per validated attachment (data-URI format).

It calls `get_llm().invoke(...)` and expects strict JSON back:
```json
{ "category": "...", "component": "...", "root_cause": "..." }
```

If the LLM wraps the JSON in fences or adds prose, `app/tools/parsing.py` strips
it. If parsing fails after all retries (`RetryPolicy(max_attempts=3)`), the node
degrades to safe defaults (`category/component = "unknown"`) and appends a `WARN`
breadcrumb — it never crashes the graph.

---

## Step 4 — Severity & priority (`prioritize`)

`prioritize` asks the LLM for:
```json
{ "severity": "CRITICAL|HIGH|MEDIUM|LOW", "priority": 1 }
```
Priority is then **derived from severity** (`CRITICAL=1, HIGH=2, MEDIUM=3, LOW=4`)
— the LLM's raw priority number is ignored.

Two safety nets always run on top of the LLM result:

1. **CRITICAL keyword override** — if the combined defect text contains any of
   `all users`, `completely down`, `outage`, `data loss`, `data breach`, etc., the
   severity is forced to CRITICAL regardless of what the LLM said. This is the most
   important guardrail: under-rating an outage is the costliest mistake.
2. **Rule-based fallback** — if the LLM fails or returns an invalid severity, a
   simple keyword classifier runs: outage keywords → CRITICAL, cosmetic keywords →
   LOW, production environment → HIGH, otherwise MEDIUM. Triage never stops because
   the LLM is down.

---

## Step 5 — On-call paging (`escalate`) — CRITICAL only

If `severity == "CRITICAL"`, the graph routes through `escalate` before assigning.
It calls `oncall_tool.page_oncall(...)` which currently **logs the intent and
returns a stub response**. To activate real paging, replace the stub with a
PagerDuty / Opsgenie API call in `app/tools/oncall_tool.py`.

`escalate` does not change the routing — it feeds into `assign_defect` after firing.

---

## Step 6 — Team assignment (`assign_defect`)

`assign_defect` matches the LLM's free-form `component` string against a keyword
table (`TEAM_ROUTING` in `assign.py`). First match wins:

| Keywords in component | Team | Assignee |
|-----------------------|------|----------|
| checkout, payment, cart, order, gateway | Payments | payments-oncall@example.com |
| auth, login, session, token | Identity & Access | identity-team@example.com |
| report, csv, export | Reporting | reporting-team@example.com |
| analytics, dashboard, chart | Data & Analytics | data-team@example.com |
| frontend, web, ui, css, profile, nav, button, page | Frontend | frontend-team@example.com |
| (no match) | Triage | triage-lead@example.com |

The match is case-insensitive. To add a team, edit `TEAM_ROUTING` in
`app/agent/nodes/assign.py`.

**Human-in-the-loop assignee selection.** Once the team is known, `assign_defect`
gathers candidate assignees (live Jira assignable users via `app/tools/assignees.py`,
else the static `TEAM_MEMBERS` roster) and calls LangGraph's `interrupt()` to **pause
the graph**. The API emits an `assignment_required` SSE event (`{thread_id, team,
candidates}`) and the stream ends. The user picks an assignee in a pop-up; the UI calls
`POST /triage/resume` with the `thread_id`, which resumes the graph via
`Command(resume=<assignee>)` — `interrupt()` returns the choice, `assigned_to` is set,
and flow continues into `notify`. If there are no candidates, it auto-assigns the team
default and does **not** pause. (This requires the graph to be compiled with a
checkpointer — `MemorySaver` — and every run to carry a `thread_id`.)

**Duplicates never reach `assign_defect`**, so the assignment pause never happens on
the duplicate path.

---

## Step 7 — Notifications (`notify`)

`notify` does three things:
1. **Jira — LIVE, update *or* create.**
   - If the defect came **from** Jira (`state["source_jira_key"]` is set — the UI fetched
     it via `GET /jira/issue/{key}`), it **updates that existing issue**: adds a triage
     comment (root cause, category, component, severity, assignee) and best-effort sets
     its priority.
   - Otherwise it **creates a new Bug** in `JIRA_PROJECT_KEY`, mapping severity → Jira
     priority (CRITICAL→Highest, HIGH→High, MEDIUM→Medium, LOW→Low), with `auto-triaged`
     + team + component labels.
   The acted-on key + browse URL are stored in `state["jira_key"]` / `state["jira_url"]`.
2. `slack_tool.post_message("#defect-triage", summary)` — **stub** (logs only).
3. `email_tool.send_email(assignee, subject, body)` — **stub** (logs only).

Jira is **best-effort**: if credentials are missing or Jira is unreachable, the call
returns `{"ok": False, ...}` and triage still completes — it never raises. A real
failure (401/403/429/network) additionally surfaces a non-fatal `warning` SSE event
(`app/tools/jira_tool.py::warning_for`) which the UI shows as a dismissible toast.
Slack/email remain stubs.

For **duplicates**, `flag_duplicate` likewise creates a Jira Bug labeled `duplicate`,
comments which parent it duplicates, and best-effort transitions it to a closed status.

---

## Step 8 — SSE response back to the client

As each node runs, `routes.py` emits a **Server-Sent Event**:

```
data: {"type": "log", "node": "intake_defect", "line": "[intake_defect] normalized DEF-901; kept 0 image(s), dropped 0"}

data: {"type": "log", "node": "check_duplicate", "line": "[check_duplicate] DUPLICATE of open defect DEF-101 (score 0.845)"}

data: {"type": "result", "state": { ...final TriageState... }}
```

The frontend's `LogFeed` renders each `log` event as it arrives; the `result` event
renders the result panel (with root cause prominent + a Jira link). Other events:
`warning` → dismissible toast; `assignment_required` → assignee-picker pop-up (then
`/triage/resume` stitches the remaining events into the same feed); `error` → blocking
modal. The full event list is in [API_REFERENCE.md](API_REFERENCE.md).

---

## Worked examples

### A. Duplicate (LLM never called)

```
"Applying a promo code at checkout causes a 500 error"
 → intake_defect: normalize, 0 images
 → check_duplicate: embed → search → DEF-101 score 0.845 ≥ 0.80, status OPEN
 → verdict: DUPLICATE of DEF-101
 → flag_duplicate: link to DEF-101, close as duplicate
 → SSE: 3 log events + result { is_duplicate: true, status: "closed_duplicate" }
 LLM: never called ✓
```

### B. Regression (full analysis)

```
"Random logouts with 'Invalid session' under concurrent requests"
 → intake_defect: normalize
 → check_duplicate: embed → search → DEF-050 score 0.825 ≥ 0.80, status CLOSED
 → verdict: REGRESSION of DEF-050 (is_regression = true)
 → analyze_defect: LLM → { category: "Authentication", component: "Session Management", ... }
 → prioritize: LLM → HIGH; no emergency keywords
 → assign_defect: "session" → Identity & Access
 → notify: creates real Jira Bug (e.g. SCRUM-12); Slack/email stubs log
 → SSE: 6 log events + result { is_regression: true, severity: "HIGH", status: "notified" }
```

### C. Critical outage (rule override fires)

```
"Payment service completely down in production — all users affected"
 → check_duplicate: no match → NEW
 → analyze_defect: LLM → PaymentClient / External Dependency
 → prioritize: LLM says LOW → rule override detects "all users" + "completely down"
   → severity forced to CRITICAL ✓
 → escalate: stub logs on-call page for DEF-201
 → assign_defect: "payment" → Payments
 → notify: creates real Jira Bug; Slack/email stubs log
 → SSE: result { severity: "CRITICAL", status: "notified" }
```

### D. New bug (normal path)

```
"Submit button slightly misaligned on settings page (staging)"
 → check_duplicate: no match → NEW
 → analyze_defect: LLM → UI/Visual / Settings Page
 → prioritize: LLM → LOW (cosmetic, staging)
 → assign_defect: "page" → Frontend
 → notify: creates real Jira Bug; Slack/email stubs log
 → SSE: result { severity: "LOW", status: "notified" }
```
