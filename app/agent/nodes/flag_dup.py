"""flag_duplicate — terminal node for confirmed duplicates (no LLM).

Reached only when check_duplicate found an OPEN match (analysis was skipped).
Links the new defect to its parent ticket and closes it as a duplicate.
"""

from app.tools.jira_tool import add_comment, link_duplicate


def flag_duplicate(state: dict) -> dict:
    defect_id = state.get("defect_id", "")
    parent_id = state.get("duplicate_of", "")

    link_duplicate(defect_id, parent_id)
    add_comment(defect_id, f"Automatically closed as a duplicate of {parent_id}.")

    return {
        "status": "closed_duplicate",
        "triage_notes": [
            f"[flag_duplicate] linked {defect_id} to parent {parent_id}; closed as duplicate"
        ],
    }
