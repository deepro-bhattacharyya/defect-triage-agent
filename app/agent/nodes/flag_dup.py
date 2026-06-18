"""flag_duplicate — terminal node for confirmed duplicates (no LLM).

Reached only when check_duplicate found an OPEN match (analysis was skipped).
Creates a Jira Bug recording the duplicate, comments with the parent it duplicates,
and best-effort transitions it to a closed state. Degrades gracefully if Jira is
unavailable — the node always finishes.
"""

from app.tools.jira_tool import add_comment, create_issue, transition_to


def flag_duplicate(state: dict) -> dict:
    defect_id = state.get("defect_id", "")
    parent_id = state.get("duplicate_of", "")
    title = state.get("title", "")

    jira = create_issue(
        summary=f"[DUPLICATE] {title}",
        description="\n".join(
            [
                f"Auto-triaged defect {defect_id} — detected as a DUPLICATE of {parent_id}.",
                "",
                "Original description:",
                state.get("description", ""),
            ]
        ),
        labels=["auto-triaged", "duplicate"],
    )

    jira_key = ""
    if jira.get("ok"):
        jira_key = jira["key"]
        add_comment(jira_key, f"Automatically detected as a duplicate of {parent_id}. Closing.")
        transition_to(jira_key, "Done", "Closed", "Resolved", "Won't Do")

    if jira.get("ok"):
        note = f"[flag_duplicate] created Jira {jira_key}, flagged duplicate of {parent_id}, closed"
    elif jira.get("skipped"):
        note = f"[flag_duplicate] Jira not configured; {defect_id} flagged duplicate of {parent_id}"
    else:
        note = f"[flag_duplicate] Jira create FAILED; {defect_id} flagged duplicate of {parent_id}"

    return {
        "status": "closed_duplicate",
        "jira_key": jira_key,
        "triage_notes": [note],
    }
