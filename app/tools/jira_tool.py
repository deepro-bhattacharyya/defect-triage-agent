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

import base64
import os
import re

import requests
import structlog

from app.tools.certs import configure_corporate_tls

log = structlog.get_logger(__name__)

_TIMEOUT = 20
_HEADERS = {"Accept": "application/json", "Content-Type": "application/json"}

# Image guardrails for attachments pulled off a Jira issue (mirrors intake_defect;
# kept here to avoid a tools→nodes import). intake re-validates regardless.
_SUPPORTED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}


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


def _adf_to_text(adf) -> str:
    """Flatten an Atlassian Document Format value (or plain string) to plain text."""
    if not adf:
        return ""
    if isinstance(adf, str):
        return adf
    parts: list[str] = []

    def walk(node):
        if isinstance(node, list):
            for n in node:
                walk(n)
        elif isinstance(node, dict):
            ntype = node.get("type")
            if ntype == "text":
                parts.append(node.get("text", ""))
            elif ntype == "hardBreak":
                parts.append("\n")
            for child in node.get("content", []) or []:
                walk(child)
            if ntype in ("paragraph", "heading"):
                parts.append("\n")

    walk(adf)
    return "".join(parts).strip()


def _download_attachments(attachments, auth) -> list:
    """Download image attachments off a Jira issue as {media_type, data(base64)},
    applying the image guardrails (count, size, supported types)."""
    max_mb = float(os.environ.get("MAX_IMAGE_MB", "5"))
    max_n = int(os.environ.get("MAX_IMAGES", "3"))
    out = []
    for att in attachments or []:
        if len(out) >= max_n:
            break
        mime = (att.get("mimeType") or "").lower()
        if mime not in _SUPPORTED_IMAGE_TYPES:
            continue
        if att.get("size", 0) > max_mb * 1024 * 1024:
            continue
        url = att.get("content")
        if not url:
            continue
        try:
            rr = requests.get(url, auth=auth, timeout=_TIMEOUT)
            if rr.status_code == 200:
                out.append({"media_type": mime, "data": base64.b64encode(rr.content).decode()})
        except Exception:  # noqa: BLE001 — skip an attachment we can't fetch
            continue
    return out


def get_issue(key: str) -> dict:
    """Fetch a Jira issue and map it to our defect shape. Returns
    {"ok": True, "defect": {...}} or {"ok": False, "reason": ...}. Never raises."""
    if not _configured():
        return {"ok": False, "reason": "Jira not configured"}
    if not key:
        return {"ok": False, "reason": "no issue key given"}

    configure_corporate_tls()
    base, email, token = _config()
    try:
        r = requests.get(
            f"{base}/rest/api/3/issue/{key}",
            params={"fields": "summary,description,environment,reporter,attachment,priority,status"},
            auth=(email, token), headers={"Accept": "application/json"}, timeout=_TIMEOUT,
        )
        if r.status_code == 404:
            return {"ok": False, "reason": f"Issue {key} not found in Jira"}
        if r.status_code in (401, 403):
            return {"ok": False, "reason": "Jira rejected the request (auth)", "status": r.status_code}
        if r.status_code != 200:
            return {"ok": False, "reason": f"Jira returned HTTP {r.status_code}", "status": r.status_code}

        data = r.json()
        f = data.get("fields", {}) or {}
        reporter = f.get("reporter") or {}
        env = f.get("environment")
        defect = {
            "defect_id": data.get("key", key),
            "title": f.get("summary") or "",
            "description": _adf_to_text(f.get("description")),
            "environment": _adf_to_text(env) if isinstance(env, dict) else (env or ""),
            "reporter": reporter.get("displayName") or reporter.get("emailAddress") or "",
            "stack_trace": "",  # not a standard Jira field
            "image_attachments": _download_attachments(f.get("attachment"), (email, token)),
        }
        log.info("jira.get_issue", key=defect["defect_id"], images=len(defect["image_attachments"]))
        return {"ok": True, "defect": defect}
    except Exception as e:  # noqa: BLE001
        log.warning("jira.get_issue.error", error=str(e)[:200])
        return {"ok": False, "reason": str(e)[:200]}


def get_jira_status() -> dict:
    """Lightweight connectivity check. Returns {"connected": bool, ...}. Never raises."""
    if not _configured():
        return {"connected": False, "reason": "not configured"}
    configure_corporate_tls()
    base, email, token = _config()
    try:
        r = requests.get(f"{base}/rest/api/3/myself", auth=(email, token),
                         headers={"Accept": "application/json"}, timeout=_TIMEOUT)
        return {"connected": r.status_code == 200, "status": r.status_code}
    except Exception as e:  # noqa: BLE001
        return {"connected": False, "reason": str(e)[:200]}


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


def warning_for(result: dict) -> str | None:
    """Map a failed jira_tool result to a friendly, user-facing warning string —
    or None if it's a success or an expected "not configured" skip (no warning)."""
    if not isinstance(result, dict) or result.get("ok"):
        return None
    if result.get("skipped"):
        return None  # Jira simply not configured — expected, not a warning
    status = result.get("status")
    if status in (401, 403):
        return "Jira rejected the request — check credentials / permissions."
    if status == 429:
        return "Jira is rate-limiting requests — the ticket wasn't updated; retry shortly."
    reason = result.get("reason") or result.get("error") or "unknown error"
    return f"Jira unreachable — the ticket wasn't updated ({reason})."


def browse_url(key: str) -> str:
    """Human-facing URL for an issue key, or "" if Jira/key is not configured."""
    base, _, _ = _config()
    return f"{base}/browse/{key}" if (base and key) else ""


def update_issue(issue_key: str, fields: dict) -> dict:
    """Update fields on an existing issue (e.g. priority). Best-effort."""
    if not _configured() or not issue_key or not fields:
        return {"ok": False, "skipped": True}
    configure_corporate_tls()
    base, email, token = _config()
    try:
        r = requests.put(f"{base}/rest/api/3/issue/{issue_key}", json={"fields": fields},
                         auth=(email, token), headers=_HEADERS, timeout=_TIMEOUT)
        ok = r.status_code in (200, 204)
        if not ok:
            log.warning("jira.update_issue.failed", key=issue_key, status=r.status_code)
        return {"ok": ok, "status": r.status_code}
    except Exception as e:  # noqa: BLE001
        log.warning("jira.update_issue.error", error=str(e)[:200])
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
