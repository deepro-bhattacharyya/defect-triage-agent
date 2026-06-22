# DefectTriageBot — Frontend (React + Vite)

A small React single-page app for submitting a defect and viewing the triage
result (severity, priority, team/assignee, duplicate/regression flags, root-cause
analysis, a Jira link, and the full audit trail).

**What it does:**
- **Fetch by Jira ID** — when Jira is connected (`GET /jira/status`), the form leads
  with a Jira defect ID + Fetch button that auto-fills every field from the issue
  (`GET /jira/issue/{key}`), including image attachments. Manual entry is the fallback.
- **Live streaming** — `POST /triage` streams Server-Sent Events, so a **live log feed**
  shows each node's breadcrumb the moment it runs, above the final result.
- **Assignee pop-up** — when the graph pauses (`assignment_required`), a modal lists
  candidate assignees; confirming calls `POST /triage/resume` and the same feed continues.
- **Error modal & warning toasts** — a missing Gemini key / fatal quota error shows a
  blocking modal; a non-fatal Jira failure shows a dismissible toast.

> Note: a UI was out of the original v1 scope (`CLAUDE.md` guardrails) — this was
> added as an explicit, approved extension. It's a thin client over the API; no
> backend logic lives here.

## Stack
- React 18 + Vite 5 (vanilla JS/JSX, no extra UI libraries)
- Talks to the FastAPI backend via `POST /triage`, `POST /triage/resume`,
  `GET /health`, `GET /jira/status`, `GET /jira/issue/{key}`

## Components (`src/components/`)
- `DefectForm.jsx` — Jira-ID fetch + manual fields + screenshot upload
- `LogFeed.jsx` — live, streaming node-by-node log
- `ResultPanel.jsx` — verdict, prominent root cause, Jira link, audit trail
- `AssignmentModal.jsx` — human-in-the-loop assignee picker
- `ErrorModal.jsx` — blocking fatal-error modal · `Toasts.jsx` — dismissible warnings

## Prerequisites
- Node.js 18+ and npm (built/tested on Node 22, npm 10)
- The backend running (see the repo `INSTALL.md`)
- **Corporate TLS proxy:** if `npm install` fails with a certificate error, point
  Node at the repo's CA bundle first:
  ```powershell
  $env:NODE_EXTRA_CA_CERTS = "..\certs\corp-ca-bundle.pem"
  ```

## Install
```bash
cd frontend
npm install
```

## Two ways to run

### A) Dev mode (hot reload) — two servers
```bash
# terminal 1 — backend (from repo root)
uvicorn app.api.routes:app --reload --port 8000

# terminal 2 — frontend
cd frontend
npm run dev        # http://localhost:5173
```
The Vite dev server proxies `/triage` and `/health` to `http://localhost:8000`
(see `vite.config.js`), so the browser stays same-origin — no CORS needed.

### B) Production mode — one server
```bash
cd frontend
npm run build      # emits frontend/dist/
# then, from repo root:
uvicorn app.api.routes:app --port 8000
```
The backend serves the built app at **http://localhost:8000/** (it mounts
`frontend/dist` if present). API stays at `/triage`, `/health`, docs at `/docs`.

## Layout
```
frontend/
├── index.html              # Vite entry
├── vite.config.js          # dev proxy + build config
├── package.json
└── src/
    ├── main.jsx            # React root
    ├── App.jsx             # state + layout (logs, result, modals, toasts)
    ├── api.js              # SSE reader + Jira/health helpers + resume
    ├── styles.css
    └── components/
        ├── DefectForm.jsx       # Jira-ID fetch + manual fields + screenshot
        ├── LogFeed.jsx          # live, streaming node-by-node log feed
        ├── ResultPanel.jsx      # verdict, root cause, Jira link, audit trail
        ├── AssignmentModal.jsx  # human-in-the-loop assignee picker
        ├── ErrorModal.jsx       # blocking fatal-error modal
        └── Toasts.jsx           # dismissible warning toasts
```

## Notes
- The **“Load sample (duplicate)”** button fills a defect that matches open
  `DEF-101`; that path short-circuits before any LLM call, so it works even when
  the Gemini daily quota is exhausted.
- On a Gemini `429`/quota error the UI shows a friendly message instead of a raw 500.
