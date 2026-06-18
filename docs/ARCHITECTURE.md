# Architecture

How **DefectTriageBot** is put together, and *why* it's shaped this way. Read
[PROJECT_PLAN.md](PROJECT_PLAN.md) first for the approved behavior spec, and
[PROJECT_EXPLAINED.md](PROJECT_EXPLAINED.md) for a from-basics walkthrough; this
doc explains the structure that delivers it.

---

## 1. The one-paragraph mental model

A bug report enters as a plain dict. It travels through a **LangGraph state
machine**: it's normalized (`intake`), checked against the existing backlog in a
**vector store** (`check_duplicate`) *before* any LLM is touched, and then either
short-circuits (confirmed duplicate) or flows on to an **LLM** that analyzes root
cause (`analyze`) and rates urgency (`prioritize`). Deterministic rules then route
it — page on-call for CRITICAL, pick an owning team — and side-effect nodes close
the loop (Jira live; Slack/email stubbed). One shared `TriageState` dict carries
everything; every node leaves a breadcrumb in `triage_notes` for the audit trail.
The expensive/unreliable parts (LLM, embeddings, integrations) are each isolated
behind a single wrapper, so the graph stays testable and the dev/prod swaps touch
one file.

```
defect (dict)
     │
     ▼
 intake_defect ──► check_duplicate ──┬─ OPEN match ────────► flag_duplicate ─► END
 (normalize,        (vector search,  │  (duplicate)
  cap images)        no LLM)         │
                                     ├─ RESOLVED match ─┐
                                     └─ no match ───────┤ (regression / new)
                                                        ▼
                                                  analyze_defect ──► prioritize
                                                  (LLM, multimodal)   (LLM + rules)
                                                                          │
                                              ┌── CRITICAL ──► escalate ──┤
                                              └── HIGH/MED/LOW ───────────┤
                                                                          ▼
                                                              assign_defect ─► notify ─► END

        app/agent/graph.py wires this │ app/api/routes.py serves it │ frontend/ calls it
```

---

## 2. Layer separation: `nodes/tools → graph → api → frontend`

The codebase is layered so the interface can change without touching the brains.
Each layer depends only on the ones below it.

| Layer | Files | Responsibility | Knows about |
|-------|-------|----------------|-------------|
| **Tools** | `app/tools/` | All "talking to the outside world": LLM, embeddings/vector store, Jira/Slack/email/on-call, TLS, JSON parsing. | Nothing in the agent. |
| **Nodes** | `app/agent/nodes/` | One pure function per triage step. Each takes `TriageState`, returns a partial dict. | `tools` only. |
| **Graph** | `app/agent/graph.py` + `state.py` | The state schema and the wiring (nodes + conditional edges + retries). | `nodes`, `tools`. |
| **API** | `app/api/routes.py` | Thin FastAPI surface: `POST /triage` **streams** the graph run (SSE); also serves the UI. Adds *no* triage logic. | `graph`. |
| **UI** | `frontend/` (React + Vite) | Browser form + result view. Calls the API over HTTP. | `api` only — never imports Python. |

**The golden rule the code enforces:** the *brain* (nodes/graph) is kept separate
from the *hands* (tools that touch Jira/Slack/the LLM/the vector DB). That
separation is exactly what makes the nodes unit-testable — tests swap the real
hands for fakes, so no email is sent and no LLM is called. `POST /triage` is
essentially `build_graph().invoke(defect)` — the CLI-less core and the API share
one compiled graph.

---

## 3. The shared state object (`TriageState`)

There is no database for in-flight work — a single `TypedDict`, `TriageState`
(`app/agent/state.py`), is the shared clipboard. **Every node receives it and
returns a partial dict of only the keys it changed**; LangGraph merges that back
in. Nodes never mutate state in place.

Two field kinds matter:

| Field kind | Examples | Merge behavior |
|------------|----------|----------------|
| **Reducer (`Annotated[list, operator.add]`)** | `triage_notes`, `similar_defects` | returned list is **appended** — lets every node add a breadcrumb without clobbering earlier ones |
| **Plain (last-wins)** | everything else, incl. `image_attachments` | returned value **overwrites** |

> ⚠️ **`image_attachments` is deliberately *not* a reducer.** `intake_defect`
> validates the raw input images and returns the cleaned list; if this field were
> an `operator.add` reducer, the cleaned list would be *appended* to the raw
> seeded one and duplicate the attachments. `intake` is the sole writer, so
> last-wins is correct. (This was a real bug caught when wiring the graph.)

`triage_notes` is the **audit trail**: every node appends `"[node_name] what
happened"`, so the final state explains exactly how the verdict was reached.

---

## 4. The graph: nodes + conditional routing

`build_graph()` (`app/agent/graph.py`) assembles eight nodes. Two are LLM-backed
and carry `RetryPolicy(max_attempts=3)`; the rest are deterministic.

| Node | LLM? | Responsibility |
|------|:----:|----------------|
| `intake_defect` | No | Normalize fields; validate image attachments (cap size/count, drop unsupported) |
| `check_duplicate` | No | Vector similarity vs. backlog; classify duplicate / regression / new |
| `analyze_defect` | **Yes** | Root cause, category, component (multimodal: text + images) |
| `prioritize` | **Yes** | Severity + priority, with rule override & fallback |
| `assign_defect` | No | Component → team → developer routing |
| `escalate` | No | Page on-call (CRITICAL only) |
| `flag_duplicate` | No | Link to parent ticket, close as duplicate |
| `notify` | No | Create Jira Bug (live) + Slack + email (stubs) |

Two **conditional edges** are the only branching:

- `route_after_check` → `flag_duplicate` if `is_duplicate`, else `analyze_defect`.
  (Regressions are *not* duplicates — they go to analysis like new bugs.)
- `route_severity` → `escalate` if `severity == "CRITICAL"`, else `assign_defect`.

Everything else is a straight edge. `escalate` rejoins at `assign_defect`, so the
critical path is `… → escalate → assign_defect → notify`.

---

## 5. Duplicate-before-LLM, and the duplicate-vs-regression split

The single most important ordering decision: **`check_duplicate` runs before any
LLM call.** Confirmed duplicates (~18% of a real backlog) short-circuit straight
to `flag_duplicate` and never pay for analysis.

The verdict hinges on the **status of the matched backlog item**, stored in vector
metadata (`app/agent/nodes/duplicate.py`):

| Match found at score ≥ threshold? | Matched status | Verdict | Path |
|-----------------------------------|----------------|---------|------|
| yes | `OPEN` (anything not resolved) | **DUPLICATE** | short-circuit → `flag_duplicate` |
| yes | `RESOLVED` / `CLOSED` / `DONE` | **REGRESSION** | full analysis (a fixed bug came back — serious) |
| no | — | **NEW** | full analysis |

Constants: `SIMILARITY_THRESHOLD = 0.80`, `RESOLVED_STATUSES = {"RESOLVED",
"CLOSED", "DONE"}`.

---

## 6. The vector store design

ChromaDB is the only datastore (`app/tools/vector_store.py`). One collection,
`defect_backlog`, holds **both** the embeddings (for semantic similarity) **and**
the metadata (`defect_id`, `status`, `component`, …), so there's no separate
relational DB. Seeding (`scripts/seed_vector_store.py`) upserts the backlog, which
makes it idempotent and safe to re-run.

Two design points worth calling out:

- **Similarity, not distance.** Chroma natively returns a cosine *distance* (lower
  = closer), but the plan's `check_duplicate` logic treats the score as a
  *similarity* (higher = match). The wrapper converts `similarity = 1 - distance`
  so callers compare against the `0.80` threshold directly. The collection is
  created with `hnsw:space = cosine` for this reason.
- **The threshold is embedding-model-specific.** `0.80` is calibrated for this
  POC's Gemini `gemini-embedding-001`, where real duplicate/regression pairs score
  ~0.81–0.85 and unrelated bugs ≤0.70. (The plan's original `0.88` was tuned for
  OpenAI embeddings — a different score distribution.) Change the embedding model →
  recalibrate the threshold and re-seed (vector dimensions differ).

The embedder is **injectable** (`VectorStore(embedder=…)`), so unit tests pass a
fake and run fully offline with no API key.

---

## 7. The LLM-optional / resilience pattern

The LLM (`app/tools/llm.py`) is a swappable, isolated component: **Gemini 2.5
Flash in dev, Claude Sonnet 4.6 in prod**, behind one `get_llm()`. Nodes never
name a provider. Because the LLM is the unreliable part, three layers protect the
pipeline:

1. **Defensive JSON parsing** (`app/tools/parsing.py::extract_json`) — strips
   ```json fences``` and surrounding prose; raises `ValueError` if there's no
   object. LLMs (Gemini included) wrap JSON unpredictably.
2. **Graceful degradation in `analyze_defect`** — if parsing fails, it returns
   safe defaults (`category/component = "unknown"`) plus a WARN breadcrumb instead
   of crashing the graph. Transient API errors propagate so `RetryPolicy` can retry.
3. **Rule-based safety nets in `prioritize`** —
   - a **CRITICAL keyword override** forces CRITICAL on unambiguous emergency
     signals (`"all users"`, `"data loss"`, `"outage"`, …) regardless of what the
     LLM said — under-rating a real outage is the costliest mistake;
   - a **rule-based fallback classifier** runs if the LLM call/JSON fails, so the
     node *always* yields a valid severity (an LLM outage can't stop triage).

`priority` is then *derived* from severity (`CRITICAL=1 … LOW=4`), never trusted
from the raw LLM output. This pattern was verified live: on one run Gemini
returned an invalid severity and the rule fallback produced the correct HIGH.

Multimodal note: image blocks use LangChain's data-URI `image_url` format (what
the Gemini chat model accepts), not the plan's Anthropic `source`/`base64` block.

---

## 8. The tools layer: external I/O isolation

Every outward call lives behind `app/tools/`, so nodes stay pure and the graph
runs end-to-end with no credentials.

| Tool | Role | State |
|------|------|-------|
| `llm.py` | Shared chat model (`get_llm()`) | live (Gemini) |
| `vector_store.py` | ChromaDB wrapper + injectable embedder | live (Gemini embeddings) |
| `parsing.py` | Defensive JSON extraction | pure |
| `certs.py` | Corporate-TLS bootstrap (§9) | env setup |
| `jira_tool.py` | `create_issue` / `add_comment` / `transition_to` | **LIVE** (REST API v3) |
| `slack_tool.py` | `post_message` | **stub** |
| `email_tool.py` | `send_email` | **stub** |
| `oncall_tool.py` | `page_oncall` | **stub** |

**Jira is live** — `notify` creates a real Bug per defect and `flag_duplicate`
creates + closes a duplicate Bug. Every Jira call is best-effort: missing creds,
auth failure, or network error returns `{"ok": False, ...}` and the node finishes
anyway (triage never stops). The remaining stubs log via `structlog` and return
canned responses with clear `TODO`s — so `escalate`/`notify` are fully exercisable,
and the side-effect tests monkeypatch the tool functions. (Never log raw image data
or PII.)

---

## 9. Corporate TLS handling

This deployment sits behind a **TLS-intercepting corporate proxy**: it presents
its own certificate, which the OS trust store has but Python's bundled `certifi`
does not — so SDK calls fail with `CERTIFICATE_VERIFY_FAILED`.

`app/tools/certs.py::configure_corporate_tls()` fixes this with **no new
dependency**: it points Python's TLS stack (`SSL_CERT_FILE`, `REQUESTS_CA_BUNDLE`,
`GRPC_DEFAULT_SSL_ROOTS_FILE_PATH`) at a PEM bundle exported from the OS root store
(`certs/corp-ca-bundle.pem`, git-ignored, auto-detected). It's called lazily
before any Gemini client is constructed, and is a **no-op when no bundle exists**,
so CI/cloud machines are unaffected. The Node toolchain needs the same trust via
`NODE_EXTRA_CA_CERTS` for `npm install`.

> Note: OpenAI's API is *policy-blocked* (HTTP 403) on this network — a CA bundle
> can't unblock it, which is why this POC standardized on Gemini for both the LLM
> and embeddings.

---

## 10. Configurability summary

| What | Where | Default |
|------|-------|---------|
| Dev LLM model | `app/tools/llm.py` `DEV_MODEL` | `gemini-2.5-flash` |
| Embedding model | `app/tools/vector_store.py` `GEMINI_EMBEDDING_MODEL` | `gemini-embedding-001` |
| Match threshold | `app/agent/nodes/duplicate.py` `SIMILARITY_THRESHOLD` | `0.80` |
| Resolved statuses | `duplicate.py` `RESOLVED_STATUSES` | `RESOLVED/CLOSED/DONE` |
| Image caps | `app/agent/nodes/intake.py` `MAX_IMAGE_MB` / `MAX_IMAGES` | `5` / `3` |
| Critical keywords | `app/agent/nodes/prioritize.py` `CRITICAL_KEYWORDS` | outage/data-loss set |
| Team routing | `app/agent/nodes/assign.py` `TEAM_ROUTING` | static keyword table |
| Keys / TLS / tracing | `.env` | `GOOGLE_API_KEY`, `CORP_CA_BUNDLE`, `LANGCHAIN_TRACING_V2=false` |

Each of these can change in one place without touching the rest of the architecture.

---

## 11. Testing architecture

Two tiers, mirroring the layer split:

- **Unit (`tests/unit/`, 56 tests)** — one node/tool at a time with the LLM and
  vector store **mocked**. Fast, deterministic, no API key. Includes full-graph
  *wiring* tests (mocked LLM/store) that exercise every branch — new, duplicate,
  regression, critical-escalate.
- **Integration (`tests/integration/`)** — all 5 fixture scenarios through the
  **live** graph. Auto-skips without `GOOGLE_API_KEY` and skips (not fails) on a
  Gemini quota 429. Routing/duplicate/regression are asserted strictly; severity
  is checked for validity (exact only for the deterministic CRITICAL override),
  because the escalate branch is severity-driven and severity is probabilistic.

`scripts/evaluate.py` runs the scenarios and reports severity accuracy, duplicate
precision, assignment rate, and latency. Full results + the quota caveat are in
[EVALUATION.md](EVALUATION.md).

---

## 12. Frontend integration

The UI (`frontend/`, React 18 + Vite 5) is a **thin client over `POST /triage`**
— no triage logic of its own, so the "brain vs. hands" rule holds. It was added
beyond the original v1 scope.

**Live streaming.** `POST /triage` streams **Server-Sent Events** via LangGraph's
`.astream(stream_mode=["updates","values"])`: each node's `triage_notes` breadcrumb
is emitted as a `log` event the moment it's written, then a final `result` event
carries the complete state. The UI shows a live log feed (`LogFeed.jsx`) that fills
in step-by-step as the graph runs, above the unchanged result panel. `api.js` reads
the stream with a `ReadableStream` reader and an SSE frame parser.

- **Dev:** `npm run dev` (port 5173); Vite proxies `/triage` + `/health` to the
  backend (8000), keeping the browser same-origin.
- **Prod:** `npm run build` → `frontend/dist`, which `app/api/routes.py` mounts at
  `/` via `StaticFiles(html=True)` — declared *after* the API routes so `/triage`,
  `/health`, `/docs` keep precedence. CORS is enabled for the dev case.

`src/api.js` maps a Gemini `429`/quota error to a friendly message; the
"Load sample (duplicate)" button exercises the no-LLM path so the UI is usable
even when the daily quota is gone. See [../frontend/README.md](../frontend/README.md).

---

## 13. Key dependencies

| Package | Role |
|---------|------|
| `langgraph` | The state machine: `StateGraph`, conditional edges, `RetryPolicy`. |
| `langchain-google-genai` | Gemini client — LLM (`ChatGoogleGenerativeAI`) **and** embeddings. |
| `langchain-core` | Message types (`HumanMessage`) and base abstractions. |
| `chromadb` | Local persistent vector store (embeddings + metadata). |
| `fastapi` + `uvicorn[standard]` | The HTTP layer (`app/api/routes.py`) + static UI serving. |
| `pydantic` | Request validation (`DefectIn`). |
| `structlog` | Structured logging in the tool stubs. |
| `python-dotenv` | Load `GOOGLE_API_KEY` etc. from `.env`. |
| `pytest` + `pytest-mock` | Tests (`httpx`-backed `TestClient` for the API). |
| `react` + `vite` | The frontend (`frontend/`); its own `package.json`, not the backend's. |

---

## 14. Known constraints

- **Gemini free-tier quota: 20 generate-requests/day** for `gemini-2.5-flash`.
  Exhausting it returns `429 RESOURCE_EXHAUSTED`; the duplicate path (embeddings
  only) still works. Use a paid key or wait for the daily reset for full runs.
- **`RetryPolicy` multiplies quota use on 429** — a quota error becomes 3 rejected
  calls. Recommended improvement: a `retry_on` predicate that excludes
  `RESOURCE_EXHAUSTED`.
- **Severity is the one non-deterministic signal.** Routing, duplicate, and
  regression detection are deterministic; severity depends on the LLM, with the
  rule override (catch emergencies) and rule fallback (always valid) as guards.
- **Jira is live; Slack/email/on-call are stubs.** They log intent only — wiring the
  real APIs is the obvious next step beyond this POC.
