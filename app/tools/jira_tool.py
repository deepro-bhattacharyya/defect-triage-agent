"""Jira integration — STUB.

Real implementation will use the Jira REST API v3 (atlassian-python-api) with
JIRA_BASE_URL / JIRA_EMAIL / JIRA_API_TOKEN. For now these log the intended
action and return a stub response so the graph runs end-to-end without
credentials and stays unit-testable. Never logs secrets.
"""

import structlog

log = structlog.get_logger(__name__)


def update_ticket(defect_id: str, fields: dict) -> dict:
    # TODO: PUT /rest/api/3/issue/{defect_id} with the mapped fields.
    log.info("jira.update_ticket", defect_id=defect_id, fields=sorted(fields))
    return {"ok": True, "defect_id": defect_id, "updated": sorted(fields)}


def add_comment(defect_id: str, comment: str) -> dict:
    # TODO: POST /rest/api/3/issue/{defect_id}/comment
    log.info("jira.add_comment", defect_id=defect_id)
    return {"ok": True, "defect_id": defect_id}


def link_duplicate(defect_id: str, parent_id: str) -> dict:
    # TODO: create a "Duplicate" issue link and transition the issue to Closed.
    log.info("jira.link_duplicate", defect_id=defect_id, parent_id=parent_id)
    return {"ok": True, "defect_id": defect_id, "linked_to": parent_id}
