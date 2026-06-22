"""notify — close the loop: write to Jira, post Slack, send email (no LLM).

Terminal node for the analyze/prioritize/assign path. Two Jira behaviours:
- If the defect ORIGINATED from a Jira issue (state["source_jira_key"] set, Task 1),
  UPDATE that issue — add a triage comment + best-effort set its priority.
- Otherwise CREATE a new Jira Bug.
Then posts to Slack/email (stubs). All external calls degrade gracefully — if Jira
is unreachable the node still finishes and records what happened.
"""

from app.tools.email_tool import send_email
from app.tools.jira_tool import add_comment, browse_url, create_issue, update_issue, warning_for
from app.tools.slack_tool import post_message

SLACK_CHANNEL = "#defect-triage"

# Our severity scale → Jira's 5-level priority scale.
SEVERITY_TO_JIRA_PRIORITY = {
    "CRITICAL": "Highest",
    "HIGH": "High",
    "MEDIUM": "Medium",
    "LOW": "Low",
}


def _triage_summary(state: dict) -> str:
    return "\n".join(
        [
            f"Severity: {state.get('severity', '')} (priority {state.get('priority', '')})",
            f"Category: {state.get('category', '')}",
            f"Component: {state.get('component', '')}",
            f"Root cause: {state.get('root_cause', '')}",
            f"Assigned: {state.get('assigned_team', '')} ({state.get('assigned_to', '')})",
            (f"Regression of: {state.get('regression_of', '')}" if state.get("is_regression") else ""),
        ]
    )


def notify(state: dict) -> dict:
    defect_id = state.get("defect_id", "")
    severity = state.get("severity", "")
    team = state.get("assigned_team", "")
    assignee = state.get("assigned_to", "")
    title = state.get("title", "")
    source_key = state.get("source_jira_key", "")
    priority_name = SEVERITY_TO_JIRA_PRIORITY.get(severity)

    if source_key:
        # ---- write back to the existing Jira issue ----
        result = add_comment(source_key, "Automated triage result:\n" + _triage_summary(state))
        if priority_name:
            update_issue(source_key, {"priority": {"name": priority_name}})  # best-effort
        jira_key = source_key if result.get("ok") else ""
        if result.get("ok"):
            note = f"[notify] updated Jira {source_key} with triage result; Slack + email sent"
        elif result.get("skipped"):
            note = f"[notify] Jira not configured; Slack + email sent for {defect_id} ({severity} -> {team})"
            jira_key = source_key  # the key is still known even if we couldn't write
        else:
            note = f"[notify] Jira update FAILED ({result.get('status', 'error')}); Slack + email sent for {defect_id}"
            jira_key = source_key
    else:
        # ---- create a new Jira Bug ----
        description = "\n".join(
            [
                f"Auto-triaged defect {defect_id}.",
                "",
                _triage_summary(state),
                f"Environment: {state.get('environment', '')}",
                "",
                "Original description:",
                state.get("description", ""),
            ]
        )
        result = create_issue(
            summary=f"[{severity}] {title}",
            description=description,
            priority=priority_name,
            labels=["auto-triaged", team, state.get("component", "")],
        )
        jira_key = result.get("key", "")
        if result.get("ok"):
            note = f"[notify] created Jira {jira_key} ({severity} -> {team}); Slack + email sent"
        elif result.get("skipped"):
            note = f"[notify] Jira not configured; Slack + email sent for {defect_id} ({severity} -> {team})"
        else:
            note = (
                f"[notify] Jira create FAILED ({result.get('status', 'error')}); "
                f"Slack + email sent for {defect_id} ({severity} -> {team})"
            )

    summary_line = f"{defect_id} [{severity}] {title} -> {team} ({assignee})"
    post_message(SLACK_CHANNEL, summary_line)
    send_email(assignee, f"[{severity}] {title}", summary_line)

    out = {
        "status": "notified",
        "jira_key": jira_key,
        "jira_url": browse_url(jira_key),
        "triage_notes": [note],
    }
    warning = warning_for(result)  # non-fatal Jira failure → surfaced as a UI toast
    if warning:
        out["warnings"] = [warning]
    return out
