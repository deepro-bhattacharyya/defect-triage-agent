# Runbook

How to start the project, send a defect, demo the live streaming, and fix things
when they go wrong. Setup is owned by [INSTALL.md](INSTALL.md) — do that first.

> **What's working today:** the full triage pipeline + React UI with live streaming.
> **Jira integration is live** — each triaged defect creates a real Jira Bug (see
> [CONFIGURATION.md](CONFIGURATION.md) → Jira). Slack, email, and on-call are still
> **stubs** that log intent only; activating them is a future step (add credentials
> to `.env` + replace the stub body in `app/tools/`).

---

## Starting the project

### Step 1 — Activate the venv (every terminal session)

**Windows (PowerShell):**
```powershell
.venv\Scripts\Activate.ps1
```
Your prompt should show `(.venv)`.

### Step 2 — Seed the vector store (once, or after changing the backlog)

```powershell
python scripts/seed_vector_store.py
```
Expected output:
```
Seeded 5 defect(s) into the vector store (collection now holds 5).
  - DEF-101  [OPEN       ] Checkout page throws 500 when applying promo code
  - DEF-050  [CLOSED     ] Login fails intermittently with token refresh race condition
  - DEF-077  [IN_PROGRESS] Dashboard charts load slowly on large accounts
  - DEF-090  [RESOLVED   ] Export to CSV includes deleted rows
  - DEF-066  [OPEN       ] Mobile nav menu overlaps header on small screens
```
If you see a `CERTIFICATE_VERIFY_FAILED` error, `certs/corp-ca-bundle.pem` may
have expired — regenerate it (see [INSTALL.md](INSTALL.md) §5).

### Step 3 — Start the backend

```powershell
uvicorn app.api.routes:app --reload --port 8000
```

The backend serves everything:
- **React UI** → `http://localhost:8000/`
- **Swagger docs** → `http://localhost:8000/docs`
- **Health check** → `http://localhost:8000/health`

---

## The demo sequence

### Option A — React UI (best for a demo)

Open `http://localhost:8000/` in your browser. You see a two-panel layout:
left = defect form, right = live log + result.

**Jira-first flow (when Jira is connected):** the form leads with a **Jira defect ID**
field. Enter a key (e.g. `SCRUM-9`), click **Fetch** — every field auto-populates from
the issue (description, reporter, environment, and any image attachments). Edit if
needed, then **Triage**. Because it came from Jira, the result is written **back** to
that same issue (a triage comment + priority) rather than creating a new Bug. If Jira
isn't connected, the form falls back to fully manual entry.

**Assignee pop-up:** for non-duplicate defects, the run pauses at assignment and a
pop-up lists candidate assignees for the matched team. Pick one and click
**Assign & continue** — the live log resumes and finishes. (Duplicates skip this.)

**Pop-ups & toasts:** a missing Gemini key or a fatal quota error shows a blocking
**error modal**; a non-fatal Jira failure shows a dismissible **warning toast** while
triage still completes.

**Recommended demo flow (works without any Gemini quota):**

1. Click **"Load sample (duplicate)"** → the form fills with the promo-code 500 bug.
2. Click **"Triage defect"**.
3. Watch the **Live log** panel: 3 lines appear one by one in real time:
   - `[intake_defect]` normalized …
   - `[check_duplicate]` DUPLICATE of open defect DEF-101 (score 0.845)
   - `[flag_duplicate]` linked to parent DEF-101; closed as duplicate
4. The result panel shows: `DUPLICATE`, `closed_duplicate` status, audit trail.

**Demo with LLM (uses Gemini quota):**

Fill in a new defect that isn't in the backlog, e.g.:
```
Title: Dashboard reports showing stale data after cache clear
Environment: production
Description: After clearing the cache in the reporting service, users still see
             data from 6 hours ago. The cache invalidation event seems to be
             silently failing.
```
Watch the log feed update as `analyze_defect` and `prioritize` stream in.

### Option B — Swagger UI (good for showing the API)

Open `http://localhost:8000/docs` → expand **POST /triage** → **Try it out** →
paste a sample body → **Execute**. The response streams in the Responses panel.

### Option C — PowerShell (terminal demo)

Health check:
```powershell
Invoke-RestMethod http://localhost:8000/health
```

Triage a duplicate (no quota needed):
```powershell
$body = @'
{
  "title": "Applying a promo code at checkout causes a 500 error",
  "defect_id": "DEF-901",
  "description": "Valid discount code during checkout returned a 500 and emptied my cart.",
  "environment": "production"
}
'@
Invoke-RestMethod -Uri http://localhost:8000/triage -Method Post -Body $body -ContentType "application/json"
```

---

## Gemini quota behaviour

The free tier allows **20 generate-requests/day** for `gemini-2.5-flash`. The
`analyze_defect` and `prioritize` nodes each consume 1 request per defect, so a
full new-defect run costs 2 requests.

| Scenario | Gemini calls used |
|---|---|
| Duplicate defect (short-circuit) | **0** |
| Normal new bug | 2 (analyze + prioritize) |
| Regression | 2 |

When quota is exhausted the API returns a friendly message. The duplicate path
always works regardless of quota. Quota resets daily at midnight Pacific time.

---

## Running the frontend in dev mode (hot reload)

If you're editing the React code, run two terminals:

```powershell
# Terminal 1 — backend
uvicorn app.api.routes:app --reload --port 8000

# Terminal 2 — frontend
cd frontend
$env:NODE_EXTRA_CA_CERTS = "..\certs\corp-ca-bundle.pem"   # corporate TLS
npm run dev      # http://localhost:5173
```
The Vite dev server proxies `/triage` and `/health` to the backend automatically.
After editing JSX/CSS, the browser hot-reloads instantly. When you're done, rebuild
for production: `npm run build`.

---

## Running the tests

```powershell
# Offline unit tests — no API key, no network, fast (~25 seconds)
pytest tests/unit -q

# Live integration tests — needs GOOGLE_API_KEY + seeded store
pytest tests/integration -q

# Everything
pytest -q
```

See [TESTING.md](TESTING.md) for the full test layout.

---

## Evaluation (metrics against targets)

```powershell
python scripts/evaluate.py
```
Runs all 5 scenarios against the live graph and reports severity accuracy,
duplicate precision, assignment rate, and latency vs. the plan's targets. Needs
`GOOGLE_API_KEY` and the seeded store. See [EVALUATION.md](EVALUATION.md) for
caveats (free-tier quota, N=5 sample size).

---

## When something looks wrong — troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `RuntimeError: GOOGLE_API_KEY is not set` | Key not in `.env` or venv not active | Check `.env` has `GOOGLE_API_KEY=...`; run `.venv\Scripts\Activate.ps1` |
| `CERTIFICATE_VERIFY_FAILED` on Gemini calls | Corporate CA bundle missing or stale | Regenerate `certs/corp-ca-bundle.pem` (see [INSTALL.md](INSTALL.md) §5) |
| `429 RESOURCE_EXHAUSTED` | Gemini free-tier quota exhausted (20/day) | Wait for daily reset, or use a paid key. Duplicates still work (no LLM). |
| `[check_duplicate] No match found` for a defect that should be a duplicate | Vector store not seeded, or store was deleted | `python scripts/seed_vector_store.py` |
| `ModuleNotFoundError: No module named 'app'` | Running from the wrong directory | Run commands from the repo root (the folder with `requirements.txt`) |
| React UI shows blank page at `localhost:8000/` | `frontend/dist` not built | `cd frontend && npm run build` |
| `npm install` fails with cert error | Corporate TLS proxy | `$env:NODE_EXTRA_CA_CERTS="..\certs\corp-ca-bundle.pem"` then retry |
| `POST /triage` returns HTTP 500 with LLM error | Gemini quota or TLS | Check logs for `RESOURCE_EXHAUSTED` or `CERTIFICATE_VERIFY_FAILED` |
| All `prioritize` results are fallback-based | LLM JSON parsing failing | Check if Gemini is returning valid JSON; look at the WARN in `triage_notes` |
| Jira ticket not created/updated | Creds missing/invalid, or org blocks API access | Run `python scripts/jira_check.py`. Check `JIRA_BASE_URL` has a single `https://`. A warning toast + the breadcrumb explain it; triage still completes. |
| "Fetch" by Jira ID returns nothing / 404 | Wrong key, or Jira not connected | Confirm the key exists; check `GET /jira/status`. The manual form is the fallback. |
| Assignee pop-up never appears | Duplicate defect (skips assign), or no candidates for the team | Expected for duplicates; otherwise it auto-assigned the team default. |
| Assignee pop-up appears but resume hangs | Backend restarted between pause and resume (in-memory checkpointer lost the thread) | Re-submit the defect — `MemorySaver` state doesn't survive a restart. |
| Slack/email not actually sending | Stubs not yet wired | Expected — fill in `app/tools/slack_tool.py` / `email_tool.py` with real calls + credentials |

### Useful log output

Every node appends a `triage_notes` breadcrumb. The final response always contains
`triage_notes: [...]` showing exactly which path was taken and what each step found.
When something looks wrong, this is the first thing to read.

```json
"triage_notes": [
  "[intake_defect] normalized DEF-901; kept 0 image(s), dropped 0",
  "[check_duplicate] No match found — new defect",
  "[analyze_defect] backend in checkout-service",
  "[prioritize] rule override: LOW -> CRITICAL (emergency keyword)",
  "[escalate] paged on-call for CRITICAL defect DEF-901",
  "[assign_defect] routed to Payments (payments-oncall@example.com) for component 'checkout-service'",
  "[notify] created Jira SCRUM-12 (CRITICAL -> Payments); Slack + email sent"
]
```
