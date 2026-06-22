# Configuration

Every tunable in one place: where it lives, its default, and when you'd change it.

> **Design rule:** each setting can be changed in exactly one place without
> touching the rest of the architecture. Model, threshold, image caps, team routing
> — all are isolated behind a single constant or env variable.

---

## Environment variables (`.env`)

Copy `.env.example` → `.env` (gitignored, never commit it). Recognized variables:

| Variable | Required? | Default | Purpose |
|----------|-----------|---------|---------|
| `GOOGLE_API_KEY` | **Yes** | — | Gemini 2.5 Flash (LLM) + gemini-embedding-001 (embeddings). One key covers both. |
| `OPENAI_API_KEY` | No | — | Prod embeddings only (`text-embedding-3-small`). Not used in dev — OpenAI is blocked on the corporate network. |
| `CHROMA_PERSIST_DIR` | No | `./.chroma` | Where ChromaDB writes the vector store to disk. |
| `CORP_CA_BUNDLE` | No | auto-detected | Path to corporate CA bundle. Auto-detected at `certs/corp-ca-bundle.pem` if present. |
| `LANGCHAIN_TRACING_V2` | No | `false` | Set `true` only with a real `LANGSMITH_API_KEY` — otherwise causes 401 noise. |
| `LANGSMITH_API_KEY` | No | — | LangSmith tracing (optional observability). |
| `MAX_IMAGE_MB` | No | `5` | Max megabytes per image attachment. |
| `MAX_IMAGES` | No | `3` | Max number of image attachments per defect. |
| `JIRA_BASE_URL` | For Jira | — | e.g. `https://your-org.atlassian.net`. **Single `https://`!** Jira integration is live. |
| `JIRA_EMAIL` | For Jira | — | Email of the Atlassian account that owns the API token. |
| `JIRA_API_TOKEN` | For Jira | — | Create at [id.atlassian.com/manage-profile/security/api-tokens](https://id.atlassian.com/manage-profile/security/api-tokens). |
| `JIRA_PROJECT_KEY` | No | `SCRUM` | Project key new triaged Bugs are created in. |
| `JIRA_ISSUE_TYPE` | No | `Bug` | Issue type created for each defect. |
| `SLACK_WEBHOOK_URL` | No | — | Slack incoming webhook URL. Used when the Slack stub is replaced. |
| `SENTRY_DSN` | No | — | Sentry error tracking (optional). |
| `SIMILARITY_THRESHOLD` | No | `0.80` | Note: this is read from `.env` for reference; the live constant is in `duplicate.py`. |

---

## Similarity threshold

| Setting | File | Default | What it does |
|---------|------|---------|--------------|
| `SIMILARITY_THRESHOLD` | `app/agent/nodes/duplicate.py` | `0.80` | Cosine similarity at/above which a backlog match is declared a duplicate or regression. Calibrated for `gemini-embedding-001`. Real match pairs score ~0.81–0.85; unrelated bugs ≤0.70. |
| `RESOLVED_STATUSES` | `app/agent/nodes/duplicate.py` | `{"RESOLVED", "CLOSED", "DONE"}` | Statuses that make a match a *regression* rather than a *duplicate*. |

> **If you change the embedding model**, recalibrate this threshold — score distributions
> differ per model. Delete `.chroma/` and re-seed after any model change.

---

## LLM models

| Setting | File | Default | What it does |
|---------|------|---------|--------------|
| `DEV_MODEL` | `app/tools/llm.py` | `"gemini-2.5-flash"` | The LLM used in local dev/testing. Change here to use a different Gemini model. |
| `GEMINI_EMBEDDING_MODEL` | `app/tools/vector_store.py` | `"models/gemini-embedding-001"` | The embedding model (3072-dim). Change in one place; re-seed the store after. |

To switch to **production mode** (Claude Sonnet 4.6), replace `ChatGoogleGenerativeAI` in
`app/tools/llm.py` with `ChatAnthropic(model="claude-sonnet-4-6")` reading
`ANTHROPIC_API_KEY`. The node code doesn't change — it only imports `get_llm()`.

---

## Image guardrails

| Setting | File | Default | What it does |
|---------|------|---------|--------------|
| `MAX_IMAGE_MB` | `app/agent/nodes/intake.py` | `5` | Images larger than this are dropped before they reach the LLM. Override with env var `MAX_IMAGE_MB`. |
| `MAX_IMAGES` | `app/agent/nodes/intake.py` | `3` | Maximum attachments per defect. Extra attachments are dropped. Override with `MAX_IMAGES`. |
| `SUPPORTED_MEDIA_TYPES` | `app/agent/nodes/intake.py` | `{image/png, image/jpeg, image/gif, image/webp}` | Any other type is dropped. |

---

## CRITICAL keyword override

If the defect text contains any of these phrases, severity is forced to `CRITICAL`
regardless of what the LLM said:

```python
# app/agent/nodes/prioritize.py
CRITICAL_KEYWORDS = (
    "all users", "completely down", "service down", "service is down",
    "no user can", "outage", "data loss", "data breach", "data corruption",
    "security breach", "payment service down",
)
```

To add a new keyword, add it to this tuple. To remove one, remove it. No other
change is needed.

---

## Team routing

To add or change a team, edit `TEAM_ROUTING` in `app/agent/nodes/assign.py`:

```python
# First match wins. Matching is case-insensitive substring on the component string.
TEAM_ROUTING = (
    (("checkout", "payment", "cart", "order", "gateway"), "Payments", "payments-oncall@example.com"),
    (("auth", "login", "session", "token", "identity"),   "Identity & Access", "identity-team@example.com"),
    (("report", "csv", "export"),                          "Reporting", "reporting-team@example.com"),
    (("analytics", "dashboard", "chart", "metric"),        "Data & Analytics", "data-team@example.com"),
    (("frontend", "web", "ui", "css", "profile", "nav",
      "button", "layout", "page"),                         "Frontend", "frontend-team@example.com"),
)
DEFAULT_TEAM = ("Triage", "triage-lead@example.com")
```

The `component` value comes from the LLM (free-form text), so the keyword approach
tolerates strings like `"PaymentClient"`, `"Profile Page"`, etc.

---

## Assignee candidates (human-in-the-loop)

After routing to a team, `assign_defect` pauses for a human to pick the assignee.
The candidate list comes from `app/tools/assignees.py::get_team_candidates`:

- **If Jira is connected** → live assignable users for `JIRA_PROJECT_KEY`
  (`GET /rest/api/3/user/assignable/search`).
- **Otherwise** → the static `TEAM_MEMBERS` roster in `app/agent/nodes/assign.py`:

```python
TEAM_MEMBERS = {
    "Payments": ["payments-oncall@example.com", "alice@example.com", "bob@example.com"],
    "Identity & Access": ["identity-team@example.com", "carol@example.com", "dan@example.com"],
    "Reporting": ["reporting-team@example.com", "erin@example.com"],
    "Data & Analytics": ["data-team@example.com", "frank@example.com"],
    "Frontend": ["frontend-team@example.com", "grace@example.com", "heidi@example.com"],
    "Triage": ["triage-lead@example.com"],
}
```

If a team has **no candidates**, the node auto-assigns the team default and does not
pause. Tune the roster by editing `TEAM_MEMBERS`. (The interrupt requires the graph to
be compiled with a checkpointer — the API uses `MemorySaver`, which is in-memory, so a
paused run is lost on restart.)

---

## Jira integration (live)

`notify` **updates the source Jira issue** when the defect was fetched from Jira
(`source_jira_key` set: a triage comment + priority), otherwise **creates a Bug**.
`flag_duplicate` creates a duplicate Bug and best-effort closes it. Fetching a defect
by ID uses `GET /jira/issue/{key}`. Configured via the `.env` variables above
(`JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN`, `JIRA_PROJECT_KEY`, `JIRA_ISSUE_TYPE`).

**Severity → Jira priority mapping** (`app/agent/nodes/notify.py`):

| Our severity | Jira priority |
|--------------|---------------|
| CRITICAL | Highest |
| HIGH | High |
| MEDIUM | Medium |
| LOW | Low |

**Verify your connection** any time with:
```powershell
python scripts/jira_check.py
```
It prints your authenticated user, accessible projects, issue types, and priority
values — useful for confirming `JIRA_PROJECT_KEY`/`JIRA_ISSUE_TYPE` are valid.

**Resilience:** every Jira call is best-effort. Missing creds, a 401, or a network
error returns `{"ok": False, ...}`, is logged, and the triage still completes — the
breadcrumb records "created Jira SCRUM-N", "Jira not configured", or "Jira create FAILED".

> **Common gotcha:** `JIRA_BASE_URL` must have a **single** `https://`. A doubled
> `https://https://...` causes a DNS resolution error. Enterprise orgs may also block
> API-token access — if `jira_check.py` returns 401 with a valid token, ask your
> Atlassian admin to allow REST API access (or use a personal Atlassian site).

---

## ChromaDB / vector store

| Setting | File | Default | |
|---------|------|---------|---|
| `COLLECTION_NAME` | `app/tools/vector_store.py` | `"defect_backlog"` | The Chroma collection name. Renaming requires re-seeding. |
| `DEFAULT_PERSIST_DIR` | `app/tools/vector_store.py` | `"./.chroma"` | Overridable by `CHROMA_PERSIST_DIR` env var or `CORP_CA_BUNDLE`. |

---

## "I changed a setting — what do I re-run?"

| You changed… | Do this |
|---|---|
| `SIMILARITY_THRESHOLD` or `RESOLVED_STATUSES` | Just restart the server. No re-seed needed. |
| Embedding model (`GEMINI_EMBEDDING_MODEL`) | Delete `.chroma/` → `python scripts/seed_vector_store.py` → restart. |
| LLM model (`DEV_MODEL`) | Just restart. |
| `CRITICAL_KEYWORDS` or `TEAM_ROUTING` | Just restart. |
| Image guardrails (`MAX_IMAGE_MB`, `MAX_IMAGES`) | Just restart. |
| Any `.env` variable | Just restart. |
| Jira/Slack/email/on-call credentials | Add to `.env` + replace the stub body in `app/tools/` → restart. |
