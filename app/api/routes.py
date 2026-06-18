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
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

load_dotenv()  # load GOOGLE_API_KEY etc. before the graph/clients are built

from app.agent.graph import build_graph  # noqa: E402  (after load_dotenv)

app = FastAPI(title="DefectTriageBot", version="1.0")

# Allow the Vite dev server (localhost:5173) to call the API during development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # POC; tighten to the UI origin in production
    allow_methods=["*"],
    allow_headers=["*"],
)

# Compile the graph once at startup (compiling does not call the LLM).
_graph = build_graph()


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


@app.get("/health")
def health():
    return {"status": "ok"}


def _sse(obj: dict) -> str:
    """Format one Server-Sent Event frame."""
    return f"data: {json.dumps(obj)}\n\n"


@app.post("/triage")
async def triage(defect: DefectIn):
    """Stream the triage of one defect as SSE: live `log` events per node, then a
    final `result` event with the complete TriageState (or an `error` event)."""
    payload = defect.model_dump()

    async def event_stream():
        final_state = None
        try:
            # "updates" → each node's returned partial (its new triage_notes);
            # "values"  → the full cumulative state (last one is the final state).
            async for mode, chunk in _graph.astream(payload, stream_mode=["updates", "values"]):
                if mode == "updates":
                    for node, partial in (chunk or {}).items():
                        for line in (partial or {}).get("triage_notes") or []:
                            yield _sse({"type": "log", "node": node, "line": line})
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
        yield _sse({"type": "result", "state": final_state})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# Serve the built React app (frontend/dist) at the root, if it exists. API routes
# above are registered first, so they take precedence over the static mount.
# Mounted last so /health, /triage, /docs keep working.
_FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _FRONTEND_DIST.is_dir():
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIST), html=True), name="frontend")
