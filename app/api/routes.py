"""FastAPI surface for the Defect Triage agent.

POST /triage accepts a defect payload, runs it through the compiled LangGraph,
and returns the final TriageState (verdict + triage_notes audit trail).

Run locally:
    uvicorn app.api.routes:app --reload --port 8000
"""

from dotenv import load_dotenv
from fastapi import FastAPI
from pydantic import BaseModel, Field

load_dotenv()  # load GOOGLE_API_KEY etc. before the graph/clients are built

from app.agent.graph import build_graph  # noqa: E402  (after load_dotenv)

app = FastAPI(title="DefectTriageBot", version="1.0")

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
