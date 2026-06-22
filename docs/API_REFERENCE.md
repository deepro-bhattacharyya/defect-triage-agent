# API Reference

The HTTP interface defined in `app/api/routes.py`. It is a **thin pass-through**:
it runs the compiled LangGraph and streams the result back. It adds no triage logic.

- **Framework:** FastAPI (ASGI), served with uvicorn.
- **Base URL (local):** `http://localhost:8000`
- **Interactive docs:** `http://localhost:8000/docs` (Swagger UI, auto-generated).
- **Content type (request):** `application/json`
- **Content type (response for /triage):** `text/event-stream` (SSE)

---

## Jira endpoints

The primary input flow is **fetch a defect from Jira by ID**, then triage it.

### `GET /jira/status`
Whether the backend can reach Jira with the configured credentials.
```json
{ "connected": true }
```
The UI uses this to decide between the Jira-fetch flow and the manual fallback form.

### `GET /jira/issue/{key}`
Fetch a Jira issue and return it mapped to our defect shape (description flattened
from ADF, image attachments downloaded + base64-encoded, capped by the image
guardrails). `200` with the defect dict, or `404` with a reason.
```json
{
  "defect_id": "SCRUM-42",
  "title": "Checkout 500 on promo code",
  "description": "Applying a promo code returns 500. Cart is emptied.",
  "environment": "production",
  "reporter": "Jane QA",
  "stack_trace": "",
  "image_attachments": [{ "media_type": "image/png", "data": "<base64>" }]
}
```
`404`: `{ "detail": "Issue NOPE-1 not found in Jira" }`

---

## `POST /triage`

Run one defect through the triage graph. The response is a **Server-Sent Event
stream**, not a single JSON object. Events are emitted in real time as each node
executes. The stream ends after the final `result` event, an `error` event, **or**
an `assignment_required` event (which pauses the run for human assignee selection —
resume with `POST /triage/resume`).

### Request body

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `title` | string | **yes** | Bug summary. Drives the duplicate-detection embedding. |
| `defect_id` | string | no (default `""`) | Your ticket ID, e.g. `DEF-901`. |
| `description` | string | no | Full description of the bug. |
| `stack_trace` | string | no | Stack trace, if available. |
| `environment` | string | no | `production` / `staging` / `development` / `test`. Influences severity. |
| `reporter` | string | no | Who filed it, e.g. `customer-support`. |
| `image_attachments` | array | no | Screenshots. Each item: `{ "media_type": "image/png", "data": "<base64>" }`. Max 3 images, max 5 MB each, supported types: `image/png`, `image/jpeg`, `image/gif`, `image/webp`. |
| `source_jira_key` | string | no | Set by the UI when the defect was fetched from Jira. When present, `notify` **updates that existing issue** (comment + priority) instead of creating a new Bug. |

**Minimal valid request:**
```json
{ "title": "Payment service completely down in production" }
```

**Full request:**
```json
{
  "defect_id": "DEF-901",
  "title": "Applying a promo code at checkout causes a 500 error",
  "description": "Used a valid discount code at checkout and got a 500. Cart emptied.",
  "stack_trace": "",
  "environment": "production",
  "reporter": "customer-support",
  "image_attachments": []
}
```

### SSE response events

The response body is a stream of newline-delimited SSE frames. Each frame is:
```
data: {JSON payload}\n\n
```

**Event types:** `log`, `warning`, `assignment_required`, `result`, `error`.

#### `log` — emitted once per node, as the node completes

```json
{ "type": "log", "node": "intake_defect", "line": "[intake_defect] normalized DEF-901; kept 0 image(s), dropped 0" }
```

| Field | Value |
|-------|-------|
| `type` | `"log"` |
| `node` | The node name: `intake_defect`, `check_duplicate`, `analyze_defect`, `prioritize`, `escalate`, `assign_defect`, `flag_duplicate`, `notify` |
| `line` | The node's `triage_notes` breadcrumb — one sentence describing what happened |

You receive one `log` event per node that executes. Duplicates skip `analyze_defect`,
`prioritize`, `assign_defect`, and `notify`, so they produce 3 `log` events total.

#### `warning` — non-fatal issue; triage still completes (UI shows a dismissible toast)

```json
{ "type": "warning", "message": "Jira rejected the request — check credentials / permissions." }
```
Emitted e.g. when a Jira write fails (401/403/429/network) but the agent finishes anyway.

#### `assignment_required` — the run PAUSED for human assignee selection

```json
{ "type": "assignment_required", "thread_id": "a1b2c3…", "team": "Payments",
  "candidates": ["alice@example.com", "bob@example.com"] }
```
The stream ends here. Show the candidates, let the user pick, then call
`POST /triage/resume` with the `thread_id` to continue. **Duplicates never reach
`assign_defect`, so this event never fires on the duplicate path.** If a team has no
candidates, the graph auto-assigns the default and this event is skipped.

#### `result` — the final event, carries the complete TriageState

```json
{
  "type": "result",
  "state": {
    "defect_id": "DEF-901",
    "title": "Applying a promo code at checkout causes a 500 error",
    "description": "...",
    "stack_trace": "",
    "environment": "production",
    "reporter": "customer-support",
    "image_attachments": [],
    "category": null,
    "component": null,
    "root_cause": null,
    "is_duplicate": true,
    "duplicate_of": "DEF-101",
    "is_regression": false,
    "regression_of": "",
    "similar_defects": [],
    "severity": null,
    "priority": null,
    "assigned_team": null,
    "assigned_to": null,
    "triage_notes": [
      "[intake_defect] normalized DEF-901; kept 0 image(s), dropped 0",
      "[check_duplicate] DUPLICATE of open defect DEF-101 (score 0.845)",
      "[flag_duplicate] linked DEF-901 to parent DEF-101; closed as duplicate"
    ],
    "status": "closed_duplicate"
  }
}
```

**Key fields in `state`:**

| Field | Type | Meaning |
|-------|------|---------|
| `is_duplicate` | bool | True if matched an OPEN backlog defect |
| `duplicate_of` | string | The matched defect's ID (e.g. `"DEF-101"`) |
| `is_regression` | bool | True if matched a RESOLVED/CLOSED backlog defect |
| `regression_of` | string | The previously-resolved defect's ID |
| `severity` | string | `CRITICAL` / `HIGH` / `MEDIUM` / `LOW` — null for duplicates |
| `priority` | int | `1` (highest) – `4` (lowest) — null for duplicates |
| `assigned_team` | string | Team name (null for duplicates) |
| `assigned_to` | string | Assignee email (null for duplicates) |
| `category` | string | LLM-assigned defect category (null for duplicates) |
| `component` | string | LLM-identified affected component (null for duplicates) |
| `root_cause` | string | LLM-analyzed root cause (null for duplicates) |
| `triage_notes` | string[] | Full audit trail — one entry per node |
| `status` | string | `notified` (normal/regression/critical), `closed_duplicate` (duplicate), `escalated` (intermediate CRITICAL step) |

#### `error` — replaces `result` when the graph fails

```json
{ "type": "error", "message": "Gemini quota exhausted (free tier = 20 requests/day). Try a duplicate defect (no LLM) or retry after the daily reset." }
```

The stream ends after this event. Common error messages:
- Gemini quota (429) → friendly quota message
- Other exceptions → the exception message

### Complete stream example — duplicate path

```
data: {"type": "log", "node": "intake_defect", "line": "[intake_defect] normalized DEF-901; kept 0 image(s), dropped 0"}

data: {"type": "log", "node": "check_duplicate", "line": "[check_duplicate] DUPLICATE of open defect DEF-101 (score 0.845)"}

data: {"type": "log", "node": "flag_duplicate", "line": "[flag_duplicate] linked DEF-901 to parent DEF-101; closed as duplicate"}

data: {"type": "result", "state": {...}}
```

### Reading the stream in PowerShell

```powershell
$body = '{"title":"Applying a promo code at checkout causes a 500 error","environment":"production","description":"Valid discount code at checkout returned a 500."}'
$req = [System.Net.HttpWebRequest]::Create("http://localhost:8000/triage")
$req.Method = "POST"; $req.ContentType = "application/json"
$bytes = [Text.Encoding]::UTF8.GetBytes($body)
$req.GetRequestStream().Write($bytes, 0, $bytes.Length)
$resp = $req.GetResponse()
$sr = New-Object IO.StreamReader($resp.GetResponseStream())
while (-not $sr.EndOfStream) {
    $line = $sr.ReadLine()
    if ($line) { Write-Output $line }
}
```

---

## `POST /triage/resume`

Resume a triage that paused with `assignment_required`, supplying the chosen
assignee. Streams the remaining events (assign completion, notify, `result`) as SSE,
exactly like `/triage`.

**Request body:**
```json
{ "thread_id": "a1b2c3…", "assignee": "bob@example.com" }
```
The `thread_id` must be the one from the `assignment_required` event. The frontend
continues consuming this stream into the **same** live-log feed.

---

## `GET /health`

Liveness check + whether the Gemini key is configured.

**Response `200 OK`:**
```json
{ "status": "ok", "llm_available": true }
```
`llm_available` is `false` when `GOOGLE_API_KEY` is unset — the UI shows a blocking
error pop-up on load in that case.

---

## Error cases

| Situation | Response |
|-----------|----------|
| `title` missing or wrong type | `422 Unprocessable Entity` (Pydantic validation, before any graph runs) |
| Graph raises — Gemini quota (429) | SSE `error` event with friendly quota message |
| Graph raises — other exception | SSE `error` event with the exception message |
| `image_attachments` contains oversized/unsupported | The bad attachments are silently dropped by `intake_defect`; the rest proceed |

---

## CORS

CORS is open to all origins for local development:
```python
allow_origins=["*"]
```
For production, tighten to your specific front-end origin.

---

## Static file serving

When `frontend/dist/` exists (after `npm run build`), the backend mounts it at `/`:
```
GET /           → React app (index.html)
GET /assets/…   → Bundled JS/CSS
GET /health     → still works (API routes take precedence over static)
GET /triage     → still works
GET /docs       → still works (Swagger)
```
API routes are registered *before* the static mount, so they always win.
