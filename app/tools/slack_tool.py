"""Slack integration — STUB.

Real implementation will POST to SLACK_WEBHOOK_URL. For now this logs and
returns a stub response so the graph runs without a webhook configured.
"""

import structlog

log = structlog.get_logger(__name__)


def post_message(channel: str, text: str) -> dict:
    # TODO: requests.post(SLACK_WEBHOOK_URL, json={"text": text})
    log.info("slack.post_message", channel=channel, chars=len(text))
    return {"ok": True, "channel": channel}
