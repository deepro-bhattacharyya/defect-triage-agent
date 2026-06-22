"""assign_defect — route the defect to a team, then a human picks the assignee (no LLM).

Maps the analyzed `component` to an owning team via a static keyword table. Then,
instead of auto-picking the assignee, it gathers candidate users for that team and
calls interrupt() to PAUSE the graph for a human to choose (resumed via
Command(resume=<assignee>)). If there are no candidates to choose from, it
auto-assigns the team default and does NOT interrupt.

Candidate lookup lives in app/tools/assignees.py (live Jira users, else the static
TEAM_MEMBERS roster below) — never inside this node.
"""

from langgraph.types import interrupt

from app.tools.assignees import get_team_candidates

# First match wins. Each entry: (component keywords, team, default assignee).
TEAM_ROUTING = (
    (("checkout", "payment", "cart", "order", "gateway"), "Payments", "payments-oncall@example.com"),
    (("auth", "login", "session", "token", "identity"), "Identity & Access", "identity-team@example.com"),
    (("report", "csv", "export"), "Reporting", "reporting-team@example.com"),
    (("analytics", "dashboard", "chart", "metric"), "Data & Analytics", "data-team@example.com"),
    (("frontend", "web", "ui", "css", "profile", "nav", "button", "layout", "page"),
     "Frontend", "frontend-team@example.com"),
)
DEFAULT_TEAM = ("Triage", "triage-lead@example.com")

# Static fallback roster per team — used when Jira can't supply assignable users.
TEAM_MEMBERS = {
    "Payments": ["payments-oncall@example.com", "alice@example.com", "bob@example.com"],
    "Identity & Access": ["identity-team@example.com", "carol@example.com", "dan@example.com"],
    "Reporting": ["reporting-team@example.com", "erin@example.com"],
    "Data & Analytics": ["data-team@example.com", "frank@example.com"],
    "Frontend": ["frontend-team@example.com", "grace@example.com", "heidi@example.com"],
    "Triage": ["triage-lead@example.com"],
}


def _route_team(component: str):
    comp = (component or "").lower()
    for keywords, team, default_assignee in TEAM_ROUTING:
        if any(kw in comp for kw in keywords):
            return team, default_assignee
    return DEFAULT_TEAM


def assign_defect(state: dict) -> dict:
    team, default_assignee = _route_team(state.get("component", ""))
    candidates = get_team_candidates(team, fallback=TEAM_MEMBERS.get(team, []))

    if not candidates:
        # Nobody to choose from → auto-assign the default, don't pause.
        return {
            "assigned_team": team,
            "assigned_to": default_assignee,
            "status": "assigned",
            "triage_notes": [
                f"[assign_defect] routed to {team} ({default_assignee}); no candidates — auto-assigned"
            ],
        }

    # Pause for a human to choose. On resume, interrupt() returns the selected value.
    selected = interrupt({"team": team, "candidates": candidates})
    chosen = selected or default_assignee

    return {
        "assigned_team": team,
        "assigned_to": chosen,
        "status": "assigned",
        "triage_notes": [f"[assign_defect] routed to {team}; assignee selected: {chosen}"],
    }
