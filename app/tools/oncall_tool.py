"""On-call paging — STUB.

Real implementation will trigger PagerDuty / Opsgenie. For now this logs and
returns a stub response so escalate() runs without a paging integration.
"""

import structlog

log = structlog.get_logger(__name__)


def page_oncall(defect_id: str, severity: str, summary: str) -> dict:
    # TODO: trigger a PagerDuty/Opsgenie incident for the on-call rotation.
    log.warning("oncall.page", defect_id=defect_id, severity=severity)
    return {"ok": True, "defect_id": defect_id, "paged": True}
