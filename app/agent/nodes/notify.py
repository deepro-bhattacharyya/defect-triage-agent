"""notify — close the loop: update Jira, post Slack, send email (no LLM).

Terminal node for the analyze/prioritize/assign path. All external calls go
through the tools layer (stubbed for now), keeping this node unit-testable.
"""

from app.tools.email_tool import send_email
from app.tools.jira_tool import update_ticket
from app.tools.slack_tool import post_message

SLACK_CHANNEL = "#defect-triage"


def notify(state: dict) -> dict:
    defect_id = state.get("defect_id", "")
    severity = state.get("severity", "")
    team = state.get("assigned_team", "")
    assignee = state.get("assigned_to", "")

    summary = (
        f"{defect_id} [{severity}] {state.get('title', '')} "
        f"-> {team} ({assignee})"
    )

    update_ticket(
        defect_id,
        {
            "severity": severity,
            "assignee": assignee,
            "component": state.get("component", ""),
            "status": "assigned",
        },
    )
    post_message(SLACK_CHANNEL, summary)
    send_email(assignee, f"[{severity}] {state.get('title', '')}", summary)

    return {
        "status": "notified",
        "triage_notes": [
            f"[notify] Jira updated + Slack/email sent for {defect_id} ({severity} -> {team})"
        ],
    }
