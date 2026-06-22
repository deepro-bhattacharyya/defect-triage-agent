"""Candidate assignee lookup for the human-in-the-loop assignment step (Task 4).

Lives in the tools layer so the node stays pure. When Jira is configured it fetches
users assignable in the project; otherwise it returns the caller-supplied static
fallback roster. Never raises — returns [] on any failure so the node can decide
to skip the interrupt and auto-assign.
"""

import os

import requests
import structlog

from app.tools.certs import configure_corporate_tls

log = structlog.get_logger(__name__)
_TIMEOUT = 15


def _jira_cfg():
    return (
        os.environ.get("JIRA_BASE_URL", "").rstrip("/"),
        os.environ.get("JIRA_EMAIL", ""),
        os.environ.get("JIRA_API_TOKEN", ""),
    )


def _jira_assignable_users() -> list:
    base, email, token = _jira_cfg()
    if not (base and email and token):
        return []
    configure_corporate_tls()
    project = os.environ.get("JIRA_PROJECT_KEY", "SCRUM")
    try:
        r = requests.get(
            f"{base}/rest/api/3/user/assignable/search",
            params={"project": project, "maxResults": 20},
            auth=(email, token), headers={"Accept": "application/json"}, timeout=_TIMEOUT,
        )
        if r.status_code != 200:
            return []
        names = []
        for u in r.json():
            if u.get("accountType") == "app":  # skip bots / app users
                continue
            name = u.get("displayName") or u.get("emailAddress")
            if name:
                names.append(name)
        return names
    except Exception as e:  # noqa: BLE001
        log.warning("jira.assignable.error", error=str(e)[:200])
        return []


def get_team_candidates(team: str, fallback: list | None = None) -> list:
    """Return candidate assignees for the matched team. Prefers live Jira
    assignable users; falls back to the static roster the caller passes in."""
    users = _jira_assignable_users()
    if users:
        return users
    return list(fallback or [])
