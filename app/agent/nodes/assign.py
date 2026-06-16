"""assign_defect — route the defect to a team + developer (no LLM).

Maps the analyzed `component` to an owning team via a static keyword table
(easy to swap for a config file later). Matching is keyword-based so it tolerates
the free-form component strings the LLM produces (e.g. "PaymentClient",
"Profile Page"), not just the canonical service names. Unknown components fall
back to the Triage team rather than failing.
"""

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


def assign_defect(state: dict) -> dict:
    component = (state.get("component") or "").lower()

    team, assignee = DEFAULT_TEAM
    for keywords, routed_team, routed_dev in TEAM_ROUTING:
        if any(kw in component for kw in keywords):
            team, assignee = routed_team, routed_dev
            break

    return {
        "assigned_team": team,
        "assigned_to": assignee,
        "status": "assigned",
        "triage_notes": [
            f"[assign_defect] routed to {team} ({assignee}) "
            f"for component '{state.get('component', '')}'"
        ],
    }
