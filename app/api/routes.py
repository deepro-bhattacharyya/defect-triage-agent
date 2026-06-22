"""FastAPI surface for the Defect Triage agent.

POST /triage runs a defect through the compiled LangGraph and **streams** progress
back as Server-Sent Events (SSE): one `log` event per node as its triage_notes
breadcrumb is written, then a final `result` event carrying the complete
TriageState. This lets the UI show the agent thinking step-by-step in real time.

The React frontend (frontend/) is served from here too once built:
- `npm run build` in frontend/ emits frontend/dist/, which is mounted at "/".
- During `npm run dev` the Vite dev server proxies API calls here (CORS also enabled).

Run locally:
    uvicorn app.api.routes:app --reload --port 8000
"""

import json
import uuid
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command
from pydantic import BaseModel, Field

load_dotenv()  # load GOOGLE_API_KEY etc. before the graph/clients are built

from app.agent.graph import build_graph  # noqa: E402  (after load_dotenv)
from app.tools import jira_tool  # noqa: E402

app = FastAPI(title="DefectTriageBot", version="1.0")

# Allow the Vite dev server (localhost:5173) to call the API during development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # POC; tighten to the UI origin in production
    allow_methods=["*"],
    allow_headers=["*"],
)

# Compile with a checkpointer so assign_defect can interrupt() for human assignee
# selection and resume later. Each run uses a per-defect thread_id.
_graph = build_graph(MemorySaver())


class ImageAttachment(BaseModel):
    media_type: str
    data: str  # base64-encoded


class DefectIn(BaseModel):
    title: str
    defect_id: str = ""
    description: str = ""
    stack_trace: str = ""
    environment: str = ""
    reporter: str = ""
    image_attachments: list[ImageAttachment] = Field(default_factory=list)
    # Set by the UI when the defect was fetched from Jira → notify updates that issue
    # instead of creating a new one (Task 2).
    source_jira_key: str = ""


class ResumeIn(BaseModel):
    thread_id: str
    assignee: str


@app.get("/health")
def health():
    import os

    return {"status": "ok", "llm_available": bool(os.environ.get("GOOGLE_API_KEY"))}


@app.get("/jira/status")
def jira_status():
    """Whether the backend can reach Jira with the configured credentials."""
    return {"connected": bool(jira_tool.get_jira_status().get("connected"))}


@app.get("/jira/issue/{key}")
def jira_issue(key: str):
    """Fetch a Jira issue and return it mapped to our defect shape, ready to triage."""
    result = jira_tool.get_issue(key)
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("reason", "issue not found"))
    return result["defect"]


def _sse(obj: dict) -> str:
    """Format one Server-Sent Event frame."""
    return f"data: {json.dumps(obj)}\n\n"


async def _run_stream(stream_input, thread_id: str):
    """Drive the graph and yield SSE frames. Used by both the initial /triage run
    (stream_input = the defect payload) and /triage/resume (stream_input = a
    Command(resume=...)). Emits `log`/`warning` per node, `assignment_required` when
    the graph pauses for human assignee selection, then `result` (or `error`)."""
    config = {"configurable": {"thread_id": thread_id}}
    final_state = None
    try:
        async for mode, chunk in _graph.astream(stream_input, config=config,
                                                 stream_mode=["updates", "values"]):
            if mode == "updates":
                if "__interrupt__" in chunk:
                    value = chunk["__interrupt__"][0].value or {}
                    yield _sse({
                        "type": "assignment_required",
                        "thread_id": thread_id,
                        "team": value.get("team", ""),
                        "candidates": value.get("candidates", []),
                    })
                    return  # pause: the stream ends here until /triage/resume
                for node, partial in (chunk or {}).items():
                    for line in (partial or {}).get("triage_notes") or []:
                        yield _sse({"type": "log", "node": node, "line": line})
                    for warning in (partial or {}).get("warnings") or []:
                        yield _sse({"type": "warning", "message": warning})
            elif mode == "values":
                final_state = chunk
    except Exception as e:  # surface failures to the UI instead of a broken stream
        msg = str(e)
        if "RESOURCE_EXHAUSTED" in msg or "429" in msg:
            msg = (
                "Gemini quota exhausted (free tier = 20 requests/day). Try a "
                "duplicate defect (no LLM) or retry after the daily reset."
            )
        yield _sse({"type": "error", "message": msg})
        return

    if isinstance(final_state, dict):
        final_state = {k: v for k, v in final_state.items() if k != "__interrupt__"}
    yield _sse({"type": "result", "state": final_state})


def _stream_response(agen):
    return StreamingResponse(
        agen, media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/triage")
async def triage(defect: DefectIn):
    """Stream the triage of one defect as SSE. May pause with `assignment_required`
    (resume via POST /triage/resume) before the final `result`."""
    thread_id = uuid.uuid4().hex
    return _stream_response(_run_stream(defect.model_dump(), thread_id))


@app.post("/triage/resume")
async def triage_resume(body: ResumeIn):
    """Resume a paused triage after the user picks an assignee. Streams the
    remaining events (assign completion, notify, result)."""
    return _stream_response(_run_stream(Command(resume=body.assignee), body.thread_id))


# Serve the built React app (frontend/dist) at the root, if it exists. API routes
# above are registered first, so they take precedence over the static mount.
# Mounted last so /health, /triage, /docs keep working.
_FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _FRONTEND_DIST.is_dir():
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIST), html=True), name="frontend")
