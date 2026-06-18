"""notify — close the loop: create a Jira ticket, post Slack, send email (no LLM).

Terminal node for the analyze/prioritize/assign path. Creates a real Jira Bug for
the triaged defect (severity → Jira priority), then posts to Slack/email (stubs).
All external calls go through the tools layer and degrade gracefully — if Jira is
unreachable the node still finishes and records what happened.
"""

from app.tools.email_tool import send_email
from app.tools.jira_tool import create_issue
from app.tools.slack_tool import post_message

SLACK_CHANNEL = "#defect-triage"

# Our severity scale → Jira's 5-level priority scale.
SEVERITY_TO_JIRA_PRIORITY = {
    "CRITICAL": "Highest",
    "HIGH": "High",
    "MEDIUM": "Medium",
    "LOW": "Low",
}


def notify(state: dict) -> dict:
    defect_id = state.get("defect_id", "")
    severity = state.get("severity", "")
    team = state.get("assigned_team", "")
    assignee = state.get("assigned_to", "")
    title = state.get("title", "")

    description = "\n".join(
        [
            f"Auto-triaged defect {defect_id}.",
            "",
            f"Severity: {severity} (priority {state.get('priority', '')})",
            f"Category: {state.get('category', '')}",
            f"Component: {state.get('component', '')}",
            f"Root cause: {state.get('root_cause', '')}",
            f"Assigned team: {team} ({assignee})",
            f"Environment: {state.get('environment', '')}",
            (f"Regression of: {state.get('regression_of', '')}" if state.get("is_regression") else ""),
            "",
            "Original description:",
            state.get("description", ""),
        ]
    )

    jira = create_issue(
        summary=f"[{severity}] {title}",
        description=description,
        priority=SEVERITY_TO_JIRA_PRIORITY.get(severity),
        labels=["auto-triaged", team, state.get("component", "")],
    )

    summary_line = f"{defect_id} [{severity}] {title} -> {team} ({assignee})"
    post_message(SLACK_CHANNEL, summary_line)
    send_email(assignee, f"[{severity}] {title}", summary_line)

    if jira.get("ok"):
        note = f"[notify] created Jira {jira['key']} ({severity} -> {team}); Slack + email sent"
    elif jira.get("skipped"):
        note = f"[notify] Jira not configured; Slack + email sent for {defect_id} ({severity} -> {team})"
    else:
        note = (
            f"[notify] Jira create FAILED ({jira.get('status', 'error')}); "
            f"Slack + email sent for {defect_id} ({severity} -> {team})"
        )

    return {
        "status": "notified",
        "jira_key": jira.get("key", ""),
        "triage_notes": [note],
    }
