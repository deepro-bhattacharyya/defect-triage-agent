"""escalate — page the on-call engineer for CRITICAL defects (no LLM).

Only CRITICAL bugs reach this node (the graph routes here on severity). It pages
on-call via the tools layer, then flow continues to assign_defect.
"""

from app.tools.oncall_tool import page_oncall


def escalate(state: dict) -> dict:
    defect_id = state.get("defect_id", "")
    page_oncall(defect_id, state.get("severity", ""), state.get("title", ""))
    return {
        "status": "escalated",
        "triage_notes": [
            f"[escalate] paged on-call for CRITICAL defect {defect_id}"
        ],
    }
