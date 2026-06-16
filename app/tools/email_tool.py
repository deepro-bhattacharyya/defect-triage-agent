"""Email integration — STUB.

Real implementation will send via SMTP or an email provider. For now this logs
and returns a stub response. Never logs PII-heavy bodies in full.
"""

import structlog

log = structlog.get_logger(__name__)


def send_email(to: str, subject: str, body: str) -> dict:
    # TODO: real SMTP / provider send.
    log.info("email.send", to=to, subject=subject, body_chars=len(body))
    return {"ok": True, "to": to}
