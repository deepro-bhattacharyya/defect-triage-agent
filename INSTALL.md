# Installation

First-time setup: get **DefectTriageBot** — an LLM-powered LangGraph agent that
reviews, prioritizes, and routes incoming bug reports — running after cloning.
This doc owns the **setup steps** only. For the architecture and concepts see
[docs/PROJECT_EXPLAINED.md](docs/PROJECT_EXPLAINED.md); for the formal spec
[docs/PROJECT_PLAN.md](docs/PROJECT_PLAN.md); for the build-it-in-phases checklist
and current status [docs/HANDOFF.md](docs/HANDOFF.md).

All commands run from the `defect-triage-agent/` directory (the one containing
`requirements.txt`).

> **⚠️ Build status — read this first.** This project is being built phase by
> phase (see [docs/HANDOFF.md](docs/HANDOFF.md)). **Steps 1–5 below (environment
> setup) work today.** Steps 6–8 (seed the vector store, run the API, full test
> suite) depend on components that are still being implemented — each is marked
> ⏳ *pending* with the phase that delivers it. Until then, use the import check in
> step 6 to verify the environment.

---

## 1. Prerequisites

- **Python 3.11–3.12** — check with `python --version`. (3.13/3.14 may work but
  some deps like `chromadb` can lack prebuilt wheels on the newest releases; see
  [Troubleshooting](#troubleshooting).)
- **git** — to clone the repository.
- **API keys** — two are used at runtime:
  - **`GOOGLE_API_KEY`** — Google Gemini 2.5 Flash, the **local-dev LLM** (analyze
    + prioritize nodes). Get one at <https://aistudio.google.com/apikey>.
    *(Production swaps to Claude Sonnet 4.6 — see [CLAUDE.md](CLAUDE.md).)*
  - **Embeddings** — for duplicate/regression detection, also Gemini
    (`gemini-embedding-001`, the same `GOOGLE_API_KEY`). This POC is Gemini-only;
    OpenAI is not used (its API is blocked on the corporate network).
  - The key is **not** needed for unit tests (they mock the LLM and the vector
    store); it's needed to actually run the graph end-to-end.

> **🏢 Corporate network with a TLS proxy?** If SDK calls fail with
> `CERTIFICATE_VERIFY_FAILED`, export your OS root store (which trusts the proxy CA)
> to a PEM bundle and the app will use it automatically. On Windows PowerShell:
> ```powershell
> New-Item -ItemType Directory -Force certs | Out-Null
> $out = foreach ($c in Get-ChildItem Cert:\LocalMachine\Root,Cert:\CurrentUser\Root) {
>   '-----BEGIN CERTIFICATE-----'
>   [Convert]::ToBase64String($c.RawData,'InsertLineBreaks')
>   '-----END CERTIFICATE-----' }
> $out + (Get-Content (.venv\Scripts\python.exe -m certifi)) | Set-Content certs\corp-ca-bundle.pem -Encoding ascii
> ```
> `app/tools/certs.py` auto-detects `certs/corp-ca-bundle.pem` (gitignored). Note:
> `api.openai.com` is *policy-blocked* (HTTP 403) on this network — a CA bundle won't
> unblock it, which is why dev embeddings use Gemini.

## 2. Clone and enter the project

```bash
git clone https://github.com/deepro-bhattacharyya/defect-triage-agent.git
cd defect-triage-agent
```

## 3. Create and activate a virtual environment

The `.venv/` folder is gitignored.

**Windows (PowerShell):**
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```
> If PowerShell blocks the activation script, run once per session:
> `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`

**Windows (cmd):**
```cmd
python -m venv .venv
.venv\Scripts\activate.bat
```

**macOS / Linux:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

Your prompt should now show `(.venv)`. Leave it later with `deactivate`.

## 4. Install dependencies

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

This installs `langgraph` + `langchain-core` (the agent framework),
`langchain-google-genai` (Gemini dev LLM), `langchain-openai` (embeddings),
`chromadb` (local vector store), `fastapi` + `uvicorn[standard]` (the HTTP API),
`atlassian-python-api` + `requests` (Jira / Slack integrations),
`langsmith` + `structlog` + `sentry-sdk` (observability), `python-dotenv`
(config), and `pytest` + `pytest-mock` + `ruff` (testing / tooling).

## 5. Configure your API keys

```bash
# Windows (PowerShell)
Copy-Item .env.example .env
# macOS / Linux
cp .env.example .env
```

Open `.env` and set the one key you need:

| Variable | Why |
|----------|-----|
| `GOOGLE_API_KEY` | Gemini — the LLM **and** the embeddings | 

That single key covers everything in this POC.

`.env` is gitignored — never commit real keys. The other entries (Jira, Slack,
LangSmith, Sentry, and the tunables `SIMILARITY_THRESHOLD` / `MAX_IMAGE_MB` /
`MAX_IMAGES`) already have sensible defaults; leave them blank/unchanged for local
dev. Full detail on each is in [docs/PROJECT_PLAN.md](docs/PROJECT_PLAN.md).

## 6. Verify the install

**Available now — import check.** Confirms the environment and the LLM client
layer (`app/tools/llm.py`) resolve:

```bash
# core libraries import
python -c "import langgraph, chromadb, fastapi, langchain_google_genai; print('deps OK')"

# the shared LLM client constructs (needs GOOGLE_API_KEY set, even a dummy value)
python -c "from app.tools.llm import get_llm; print('llm client OK')"

# the state schema imports
python -c "from app.agent.state import TriageState; print('state OK')"
```

**Unit tests — partially available.** The vector-store unit tests run offline
today (no API key); more arrive per phase. Full end-to-end suite is Phase 6.

```bash
pytest tests/unit -q    # offline unit tests (mocked LLM + embedder)
pytest                  # everything (grows as phases land)
```

## 7. Seed the vector store ✅ *working*

Loads the existing backlog (`tests/fixtures/seed_backlog.json`, incl. open
`DEF-101` and resolved `DEF-050`) into the local ChromaDB store so
duplicate/regression detection has something to match against. Embeds via Gemini
(dev) using your `GOOGLE_API_KEY`.

```bash
python scripts/seed_vector_store.py
```

Expected: `Seeded 5 defect(s)...` listing DEF-101 … DEF-066.

> The first time ChromaDB initializes it may download a small default model
> (tens of MB, ~1 min). Subsequent runs are fast. Re-run this after changing the
> backlog fixture.

## 8. Run it ✅ *working*

Start the API locally:

```bash
uvicorn app.api.routes:app --reload --port 8000
```

- API docs (Swagger): `http://localhost:8000/docs`
- Health: `http://localhost:8000/health`
- Triage a defect: `POST http://localhost:8000/triage` with a sample defect (see
  the five scenarios in `tests/fixtures/sample_defects.json`).

## 9. Frontend (React UI) — optional

A React + Vite UI lives in [frontend/](frontend/). Full detail in
[frontend/README.md](frontend/README.md). Quick start:

```bash
cd frontend
npm install                 # if it fails on TLS: $env:NODE_EXTRA_CA_CERTS="..\certs\corp-ca-bundle.pem"
npm run build               # emits frontend/dist/
```

Then the backend serves the UI at **http://localhost:8000/** (it auto-mounts
`frontend/dist` when present). For hot-reload dev instead, run `npm run dev`
(http://localhost:5173) alongside the backend — Vite proxies the API calls.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `pip install` fails building `chromadb`/`pydantic-core` on Python 3.13/3.14 | Create the venv with Python 3.11 or 3.12 instead: `py -3.12 -m venv .venv` (Windows) — newest Python releases often lack prebuilt wheels. |
| `RuntimeError: GOOGLE_API_KEY is not set` | You called `get_llm()` without the key. Set it in `.env`, or export a dummy value just for the import check in step 6. |
| PowerShell: "running scripts is disabled" on activate | `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`, then re-run the activate line. |
| `ModuleNotFoundError: app...` | Run commands from the repo root (the folder with `requirements.txt`), with the venv activated. |
| `npm install` fails with a certificate error | Corporate TLS proxy. Trust the bundle: `$env:NODE_EXTRA_CA_CERTS="..\certs\corp-ca-bundle.pem"` then retry. |
| UI loads but triage calls fail in `npm run dev` | Make sure the backend is running on port 8000 (the Vite proxy targets it). |

For the full build order and what each phase delivers, see
[docs/HANDOFF.md](docs/HANDOFF.md).
