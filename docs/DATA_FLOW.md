# Data Flow

How a single defect travels through the system, end to end. Follow the numbered
steps; worked examples at the bottom tie it together.

The entry point is always `POST /triage` in `app/api/routes.py`, which drives
the compiled graph via `_graph.astream()` and streams each step back as SSE.

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
    │  5. assign_defect       │  component → team → developer
    └────────────┬────────────┘
                 │  breadcrumb ──► SSE log event
                 ▼
    ┌─────────────────────────┐
    │  6. notify              │  Jira + Slack + email (stubs)
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

---

## Step 7 — Notifications (`notify`)

`notify` calls three tool stubs in sequence:
1. `jira_tool.update_ticket(defect_id, {...})` — logs the fields that *would* be updated.
2. `slack_tool.post_message("#defect-triage", summary)` — logs the message.
3. `email_tool.send_email(assignee, subject, body)` — logs the email.

All three are **stubs**: they log via `structlog` and return `{"ok": True}`. No
network calls are made. To activate them, add the real credentials to `.env` and
replace the stub body with the actual API calls. The integration points are in
`app/tools/jira_tool.py`, `slack_tool.py`, and `email_tool.py`.

---

## Step 8 — SSE response back to the client

As each node runs, `routes.py` emits a **Server-Sent Event**:

```
data: {"type": "log", "node": "intake_defect", "line": "[intake_defect] normalized DEF-901; kept 0 image(s), dropped 0"}

data: {"type": "log", "node": "check_duplicate", "line": "[check_duplicate] DUPLICATE of open defect DEF-101 (score 0.845)"}

data: {"type": "result", "state": { ...final TriageState... }}
```

The frontend's `LogFeed` component renders each `log` event as it arrives. The
`result` event renders the full result panel. On an error, an `error` event is sent
instead.

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
 → notify: stubs log Jira/Slack/email
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
 → notify: stubs log
 → SSE: result { severity: "CRITICAL", status: "notified" }
```

### D. New bug (normal path)

```
"Submit button slightly misaligned on settings page (staging)"
 → check_duplicate: no match → NEW
 → analyze_defect: LLM → UI/Visual / Settings Page
 → prioritize: LLM → LOW (cosmetic, staging)
 → assign_defect: "page" → Frontend
 → notify: stubs log
 → SSE: result { severity: "LOW", status: "notified" }
```
