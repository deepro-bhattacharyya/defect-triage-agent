"""Jira integration — Atlassian Cloud REST API v3.

Creates and manages real Jira issues for triaged defects. Auth is HTTP Basic with
JIRA_EMAIL + JIRA_API_TOKEN.

Every call is **best-effort and never raises**: on missing credentials, an auth
failure, or a network error it returns ``{"ok": False, ...}`` and logs a warning,
so the triage graph always completes (the calling node records whether Jira
succeeded). This preserves the "triage never stops" guarantee.

Config (env / .env):
  JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN   — required for live calls
  JIRA_PROJECT_KEY   (default "SCRUM")         — project new issues are created in
  JIRA_ISSUE_TYPE    (default "Bug")           — issue type to create

Jira Cloud v3 requires the description/comment body in Atlassian Document Format
(ADF), not plain text — `_adf()` handles that. Never logs secrets.
"""

import os
import re

import requests
import structlog

from app.tools.certs import configure_corporate_tls

log = structlog.get_logger(__name__)

_TIMEOUT = 20
_HEADERS = {"Accept": "application/json", "Content-Type": "application/json"}


def _config():
    return (
        os.environ.get("JIRA_BASE_URL", "").rstrip("/"),
        os.environ.get("JIRA_EMAIL", ""),
        os.environ.get("JIRA_API_TOKEN", ""),
    )


def _configured() -> bool:
    return all(_config())


def _slug(text: str) -> str:
    """Jira labels can't contain spaces — collapse to a hyphenated slug."""
    return re.sub(r"[^A-Za-z0-9]+", "-", str(text)).strip("-")[:50]


def _adf(text: str) -> dict:
    """Wrap plain text in Atlassian Document Format (required by REST v3)."""
    lines = text.split("\n") or [""]
    return {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": ([{"type": "text", "text": line}] if line else []),
            }
            for line in lines
        ],
    }


def create_issue(*, summary: str, description: str, priority: str | None = None,
                 labels: list | None = None, project_key: str | None = None,
                 issue_type: str | None = None) -> dict:
    """Create a Jira issue. Returns {"ok": True, "key": "SCRUM-1", "url": ...} or
    {"ok": False, ...}."""
    if not _configured():
        log.info("jira.create_issue.skipped", reason="not configured")
        return {"ok": False, "skipped": True, "reason": "jira not configured"}

    configure_corporate_tls()
    base, email, token = _config()
    project_key = project_key or os.environ.get("JIRA_PROJECT_KEY", "SCRUM")
    issue_type = issue_type or os.environ.get("JIRA_ISSUE_TYPE", "Bug")

    fields = {
        "project": {"key": project_key},
        "summary": summary[:250],
        "issuetype": {"name": issue_type},
        "description": _adf(description),
    }
    if priority:
        fields["priority"] = {"name": priority}
    if labels:
        fields["labels"] = [_slug(label) for label in labels if label]

    try:
        r = requests.post(f"{base}/rest/api/3/issue", json={"fields": fields},
                          auth=(email, token), headers=_HEADERS, timeout=_TIMEOUT)
        if r.status_code in (200, 201):
            key = r.json().get("key")
            log.info("jira.create_issue", key=key, project=project_key)
            return {"ok": True, "key": key, "url": f"{base}/browse/{key}"}
        log.warning("jira.create_issue.failed", status=r.status_code, body=r.text[:300])
        return {"ok": False, "status": r.status_code, "error": r.text[:300]}
    except Exception as e:  # noqa: BLE001 — best-effort, must never raise
        log.warning("jira.create_issue.error", error=str(e)[:200])
        return {"ok": False, "error": str(e)[:200]}


def add_comment(issue_key: str, comment: str) -> dict:
    """Add a comment to an existing issue."""
    if not _configured() or not issue_key:
        return {"ok": False, "skipped": True}

    configure_corporate_tls()
    base, email, token = _config()
    try:
        r = requests.post(f"{base}/rest/api/3/issue/{issue_key}/comment",
                          json={"body": _adf(comment)}, auth=(email, token),
                          headers=_HEADERS, timeout=_TIMEOUT)
        ok = r.status_code in (200, 201)
        if not ok:
            log.warning("jira.add_comment.failed", key=issue_key, status=r.status_code)
        return {"ok": ok, "status": r.status_code}
    except Exception as e:  # noqa: BLE001
        log.warning("jira.add_comment.error", error=str(e)[:200])
        return {"ok": False, "error": str(e)[:200]}


def transition_to(issue_key: str, *candidate_names: str) -> dict:
    """Best-effort: move the issue to the first available transition whose name
    (or target status) matches one of candidate_names, case-insensitive
    (e.g. "Done", "Closed", "Resolved")."""
    if not _configured() or not issue_key:
        return {"ok": False, "skipped": True}

    configure_corporate_tls()
    base, email, token = _config()
    wanted = {n.lower() for n in candidate_names}
    try:
        r = requests.get(f"{base}/rest/api/3/issue/{issue_key}/transitions",
                         auth=(email, token), headers=_HEADERS, timeout=_TIMEOUT)
        if r.status_code != 200:
            return {"ok": False, "status": r.status_code}
        for t in r.json().get("transitions", []):
            name = t.get("name", "").lower()
            to_name = t.get("to", {}).get("name", "").lower()
            if name in wanted or to_name in wanted:
                rr = requests.post(
                    f"{base}/rest/api/3/issue/{issue_key}/transitions",
                    json={"transition": {"id": t["id"]}}, auth=(email, token),
                    headers=_HEADERS, timeout=_TIMEOUT,
                )
                ok = rr.status_code in (200, 204)
                log.info("jira.transition", key=issue_key, to=t.get("name"), ok=ok)
                return {"ok": ok, "to": t.get("name")}
        return {"ok": False, "reason": "no matching transition"}
    except Exception as e:  # noqa: BLE001
        log.warning("jira.transition.error", error=str(e)[:200])
        return {"ok": False, "error": str(e)[:200]}
