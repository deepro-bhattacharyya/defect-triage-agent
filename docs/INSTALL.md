# Installation

First-time setup: get **DefectTriageBot** running after cloning. This doc owns
the **setup steps** only. For running and demoing, see [RUNBOOK.md](RUNBOOK.md).
For the build status and ADLC phases, see [HANDOFF.md](HANDOFF.md).

All commands run from the **repo root** — the folder that contains `requirements.txt`.

---

## Prerequisites

- **Python 3.11+** — check with `python --version`.
- **Node.js 18+ and npm** — for the React frontend. Check with `node --version`.
- **git** — to clone the repository.
- **A Google API key** — for Gemini LLM (analyze/prioritize) and embeddings (duplicate detection). Get one free at [aistudio.google.com/apikey](https://aistudio.google.com/apikey). One key covers everything.

> **Corporate network?** If your network intercepts TLS (SSL), you'll need to export your OS trust store once (step 5). The project auto-detects the resulting bundle — no ongoing config needed.

---

## Step 1 — Clone the repo

```powershell
git clone https://github.com/deepro-bhattacharyya/defect-triage-agent.git
cd defect-triage-agent
```

---

## Step 2 — Create a Python virtual environment

**Windows (PowerShell):**
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

> If PowerShell blocks the activation: `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` then re-run.

**macOS / Linux:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

Your prompt should now show `(.venv)`.

---

## Step 3 — Install Python dependencies

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

This installs: `langgraph`, `langchain-google-genai` (Gemini LLM + embeddings), `chromadb` (vector store), `fastapi`, `uvicorn`, `pydantic`, `structlog`, `python-dotenv`, `pytest`, `pytest-mock`, `ruff`.

---

## Step 4 — Set your API key

```powershell
Copy-Item .env.example .env
```

Open `.env` and set:
```
GOOGLE_API_KEY=your-key-here
```

`.env` is gitignored and will never be committed. Leave everything else at the defaults.

---

## Step 5 — Corporate TLS (skip if not on a corporate network)

If your network uses a TLS-intercepting proxy, Python's certificate store won't trust it and Gemini calls fail with `CERTIFICATE_VERIFY_FAILED`. Export your OS trust store once:

**Windows (PowerShell):**
```powershell
New-Item -ItemType Directory -Force certs | Out-Null
$out = foreach ($c in Get-ChildItem Cert:\LocalMachine\Root, Cert:\CurrentUser\Root) {
    '-----BEGIN CERTIFICATE-----'
    [Convert]::ToBase64String($c.RawData, 'InsertLineBreaks')
    '-----END CERTIFICATE-----'
}
$certifi = (.venv\Scripts\python.exe -m certifi).Trim()
($out -join "`n") + "`n" + (Get-Content $certifi -Raw) | Set-Content certs\corp-ca-bundle.pem -Encoding ascii
Write-Output "CA bundle written."
```

The project auto-detects `certs/corp-ca-bundle.pem` and uses it. `certs/` is gitignored.

---

## Step 6 — Verify the Python install

```powershell
# Core packages import
python -c "import langgraph, chromadb, fastapi, langchain_google_genai; print('deps OK')"

# LLM client builds
python -c "from app.tools.llm import get_llm; print('LLM client:', type(get_llm()).__name__)"

# Offline unit tests — no network, no key needed (~25 seconds)
pytest tests/unit -q
```

Expected: `57 passed`.

---

## Step 7 — Seed the vector store

Loads 5 defects into ChromaDB so duplicate/regression detection works. Requires `GOOGLE_API_KEY`.

```powershell
python scripts/seed_vector_store.py
```

Expected:
```
Seeded 5 defect(s) into the vector store (collection now holds 5).
  - DEF-101  [OPEN       ] Checkout page throws 500 when applying promo code
  - DEF-050  [CLOSED     ] Login fails intermittently with token refresh race condition
  - DEF-077  [IN_PROGRESS] Dashboard charts load slowly on large accounts
  - DEF-090  [RESOLVED   ] Export to CSV includes deleted rows
  - DEF-066  [OPEN       ] Mobile nav menu overlaps header on small screens
```

Run once at setup; safe to re-run (uses upsert).

---

## Step 8 — Build and run

### Option A — Production mode (one server, serves the React UI)

```powershell
# Build the React frontend (run once, and after JS edits)
cd frontend
$env:NODE_EXTRA_CA_CERTS = "..\certs\corp-ca-bundle.pem"   # only on corporate networks
npm install
npm run build
cd ..

# Start the backend
uvicorn app.api.routes:app --reload --port 8000
```

Open **http://localhost:8000/** — the React UI appears.
API docs at **http://localhost:8000/docs**.

### Option B — Dev mode (hot-reload for JS changes, two terminals)

```powershell
# Terminal 1 — backend
uvicorn app.api.routes:app --reload --port 8000

# Terminal 2 — frontend dev server
cd frontend
$env:NODE_EXTRA_CA_CERTS = "..\certs\corp-ca-bundle.pem"
npm run dev     # http://localhost:5173
```

Vite proxies `/triage` and `/health` to the backend automatically.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `CERTIFICATE_VERIFY_FAILED` | Do step 5. Regenerate the CA bundle if it keeps failing. |
| `RuntimeError: GOOGLE_API_KEY is not set` | Check `.env` has the key; confirm venv is active (`(.venv)` in prompt). |
| `57 tests` → some fail | Run from the repo root with venv active. Re-run `pip install -r requirements.txt`. |
| `npm install` fails with cert error | `$env:NODE_EXTRA_CA_CERTS="..\certs\corp-ca-bundle.pem"` then retry. |
| Seed script fails | Step 5 not done, or quota hit (429). Duplicate path works without seeding, but matching won't. |
| `POST /triage` returns `429` | Gemini free tier = 20 requests/day. Duplicate defects work regardless (no LLM). |
| React UI not showing at `localhost:8000/` | Run `npm run build` in `frontend/` first. |
