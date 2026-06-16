"""FastAPI surface for the Defect Triage agent.

POST /triage accepts a defect payload, runs it through the compiled LangGraph,
and returns the final TriageState (verdict + triage_notes audit trail).

The React frontend (frontend/) is served from here too once built:
- `npm run build` in frontend/ emits frontend/dist/, which is mounted at "/".
- During `npm run dev` the Vite dev server proxies API calls here (CORS also enabled).

Run locally:
    uvicorn app.api.routes:app --reload --port 8000
"""

from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
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


@app.post("/triage")
def triage(defect: DefectIn):
    """Run one defect through the triage graph and return the final state."""
    result = _graph.invoke(defect.model_dump())
    return result


# Serve the built React app (frontend/dist) at the root, if it exists. API routes
# above are registered first, so they take precedence over the static mount.
# Mounted last so /health, /triage, /docs keep working.
_FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _FRONTEND_DIST.is_dir():
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIST), html=True), name="frontend")
