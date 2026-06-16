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
  - **`GOOGLE_API_KEY`** — Google Gemini 1.5 Flash, the **local-dev LLM** (analyze
    + prioritize nodes). Get one at <https://aistudio.google.com/apikey>.
    *(Production swaps to Claude Sonnet 4.6 — see [CLAUDE.md](CLAUDE.md).)*
  - **`OPENAI_API_KEY`** — OpenAI `text-embedding-3-small`, used to embed defects
    for duplicate/regression detection in the vector store.
  - Keys are **not** needed for unit tests (they mock the LLM and the vector
    store); they're needed to actually run the graph end-to-end.

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

Open `.env` and fill in at least:

| Variable | Why | Needed when |
|----------|-----|-------------|
| `GOOGLE_API_KEY` | Gemini 1.5 Flash — the dev LLM | Running analyze/prioritize for real |
| `OPENAI_API_KEY` | `text-embedding-3-small` embeddings | Seeding the store / duplicate detection |

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

⏳ **Full test suite — pending (Phase 6).** Once the nodes and tests are built:

```bash
pytest                  # all tests
pytest tests/unit -q    # unit tests only (mocked LLM + vector store)
```

## 7. Seed the vector store ⏳ *pending (Phase 1)*

Loads the existing backlog (`tests/fixtures/seed_backlog.json`, incl. open
`DEF-101` and resolved `DEF-050`) into the local ChromaDB store so
duplicate/regression detection has something to match against.

```bash
python scripts/seed_vector_store.py
```

> The first time ChromaDB initializes it may download a small default model
> (tens of MB, ~1 min). Subsequent runs are fast. Re-run this after changing the
> backlog fixture.

## 8. Run it ⏳ *pending (Phase 5)*

Start the API locally and triage a defect via `POST /triage`:

```bash
uvicorn app.api.routes:app --reload --port 8000
```

Then send a sample defect (one of the five scenarios in
`tests/fixtures/sample_defects.json`) to `http://localhost:8000/triage`.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `pip install` fails building `chromadb`/`pydantic-core` on Python 3.13/3.14 | Create the venv with Python 3.11 or 3.12 instead: `py -3.12 -m venv .venv` (Windows) — newest Python releases often lack prebuilt wheels. |
| `RuntimeError: GOOGLE_API_KEY is not set` | You called `get_llm()` without the key. Set it in `.env`, or export a dummy value just for the import check in step 6. |
| PowerShell: "running scripts is disabled" on activate | `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`, then re-run the activate line. |
| `ModuleNotFoundError: app...` | Run commands from the repo root (the folder with `requirements.txt`), with the venv activated. |
| `scripts/seed_vector_store.py` / `app/api/routes.py` not found | Expected — those arrive in Phases 1 and 5. See [docs/HANDOFF.md](docs/HANDOFF.md). |

For the full build order and what each phase delivers, see
[docs/HANDOFF.md](docs/HANDOFF.md).
