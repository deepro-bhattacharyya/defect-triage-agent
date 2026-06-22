# DefectTriageBot — Documentation

**All project documentation lives in `docs/`.** This page is the index and a
one-paragraph overview; every other topic has exactly one home, linked below.

> **What it is.** An LLM-powered LangGraph agent that automatically reviews,
> prioritizes, and routes incoming software bug reports. You **fetch a defect from
> Jira by ID** (or enter it manually); it checks for duplicates/regressions via
> vector similarity, uses Google Gemini to analyze root cause and severity, routes
> it to the right team, **pauses for a human to pick the assignee**, then **writes
> the result back to Jira** (updating the source issue, or creating a Bug) and
> notifies stakeholders — turning a ~45-minute manual triage into a sub-2-minute
> one. Includes a React UI with live step-by-step streaming.
>
> **ADLC Status:** Phases 1–5 complete (Planning → Design → Development → Testing →
> Deployment); Phase 6 (UI) and Phase 7 (Jira integration, streaming, human-in-the-loop
> assignment) done. **82 unit tests passing.** Full phase log: [docs/HANDOFF.md](docs/HANDOFF.md).

---

## New here? Read in this order

[docs/ONBOARDING.md](docs/ONBOARDING.md) is the orientation map — what to read
in what order, where code lives, and where to look when things go wrong.
Short path: **ONBOARDING → INSTALL → RUNBOOK**.

---

## All documents

### Understand the system
| Doc | Owns |
|-----|------|
| [docs/ONBOARDING.md](docs/ONBOARDING.md) | Reading order, full code map, "where to look when…" — start here. |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | How the system is structured and *why*: LangGraph state machine, duplicate-before-LLM, vector store design, layer separation, streaming. |
| [docs/DATA_FLOW.md](docs/DATA_FLOW.md) | How one defect travels from `POST /triage` → every node → SSE response, with worked examples. |
| [docs/PROJECT_EXPLAINED.md](docs/PROJECT_EXPLAINED.md) | From-basics explainer: embeddings, LangGraph, each node's purpose. No prior knowledge assumed. |

### Build & run
| Doc | Owns |
|-----|------|
| [docs/INSTALL.md](docs/INSTALL.md) | First-time setup: venv → pip → `.env` → seed → run. |
| [docs/RUNBOOK.md](docs/RUNBOOK.md) | Demo sequence, how to send a defect, live streaming behaviour, troubleshooting. |
| [docs/CONFIGURATION.md](docs/CONFIGURATION.md) | Every tunable: similarity threshold, model names, image caps, team routing, future integration keys. |

### APIs & contracts
| Doc | Owns |
|-----|------|
| [docs/API_REFERENCE.md](docs/API_REFERENCE.md) | `POST /triage` (SSE streaming) and `GET /health`: shapes, event types, error handling. |
| [frontend/README.md](frontend/README.md) | The React UI: dev mode, production build, the live log feed. |

### Testing & evaluation
| Doc | Owns |
|-----|------|
| [docs/TESTING.md](docs/TESTING.md) | Test layout (unit vs. integration), offline patterns (mocked LLM + store), how to run. |
| [docs/EVALUATION.md](docs/EVALUATION.md) | Observed metrics vs. targets, Gemini quota caveat, how to run `scripts/evaluate.py`. |

### Project state & formal spec
| Doc | Owns |
|-----|------|
| [docs/HANDOFF.md](docs/HANDOFF.md) | ADLC phase-by-phase build status, progress tracker, deviations from the original plan. |
| [docs/PROJECT_PLAN.md](docs/PROJECT_PLAN.md) | The original approved spec (the formal ADLC contract — do not deviate without flagging). |
| [docs/DATA.md](docs/DATA.md) | Dataset findings and how to wire real/synthetic data for larger evaluations. |

### Architecture diagrams
| File | |
|------|---|
| [docs/architecture-flowchart.svg](docs/architecture-flowchart.svg) | Full triage flow — color-coded SVG (scales to any size, importable into PowerPoint/Slides). |
| [docs/architecture-flowchart.png](docs/architecture-flowchart.png) | Same at 2× resolution — ready to paste into slides or a report. |

---

## ADLC Phase Summary

| ADLC Phase | What was built | Status |
|------------|---------------|--------|
| **Phase 1 — Planning** | Requirements, problem statement, tool selection, ADLC plan | ✅ Complete |
| **Phase 2 — Design** | State schema (`TriageState`), LangGraph flow, node contracts, API design | ✅ Complete |
| **Phase 3 — Development** | All 8 triage nodes, vector store, LLM client, FastAPI + SSE streaming, React UI | ✅ Complete |
| **Phase 4 — Testing** | 82 unit tests (mocked LLM/store/Jira), 5-scenario integration tests, evaluation script | ✅ Complete |
| **Phase 5 — Deployment** | Local deployment via uvicorn, backend-served React UI, env-based config | ✅ Complete |
| **Phase 6 — UI & streaming** | React UI, SSE live log feed, error modal / warning toasts | ✅ Complete |
| **Phase 7 — Integrations & HITL** | Jira live (fetch-by-ID, write-back, create); human-in-the-loop assignee selection (interrupt/resume) | ✅ Complete |
| **Phase 8 — Future** | Real Slack/email/on-call, Pinecone cloud store, prod Claude Sonnet 4.6 | ⏳ Planned |
