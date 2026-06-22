"""Unit tests for jira_tool read functions (get_issue / get_jira_status / ADF).

`requests` is monkeypatched — no network. Credentials are faked via env so
_configured() is True for the live-path tests.
"""

import base64
import json

import pytest

from app.tools import jira_tool


class FakeResp:
    def __init__(self, status_code=200, json_data=None, content=b""):
        self.status_code = status_code
        self._json = json_data
        self.content = content
        self.text = json.dumps(json_data) if json_data is not None else ""

    def json(self):
        return self._json or {}


SAMPLE_ISSUE = {
    "key": "SCRUM-42",
    "fields": {
        "summary": "Checkout 500 on promo code",
        "description": {
            "type": "doc",
            "version": 1,
            "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": "Applying a promo code returns 500."}]},
                {"type": "paragraph", "content": [{"type": "text", "text": "Cart is emptied."}]},
            ],
        },
        "environment": "production",
        "reporter": {"displayName": "Jane QA", "emailAddress": "jane@x.com"},
        "attachment": [
            {"mimeType": "image/png", "size": 1234, "content": "https://jira/att/1"},
            {"mimeType": "application/pdf", "size": 10, "content": "https://jira/att/2"},  # dropped: type
        ],
    },
}


@pytest.fixture
def jira_env(monkeypatch):
    monkeypatch.setenv("JIRA_BASE_URL", "https://jira.example.com")
    monkeypatch.setenv("JIRA_EMAIL", "me@x.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "tok")


def test_adf_to_text_flattens_paragraphs():
    text = jira_tool._adf_to_text(SAMPLE_ISSUE["fields"]["description"])
    assert "Applying a promo code returns 500." in text
    assert "Cart is emptied." in text


def test_adf_to_text_handles_plain_and_empty():
    assert jira_tool._adf_to_text("plain string") == "plain string"
    assert jira_tool._adf_to_text(None) == ""


def test_get_issue_maps_all_fields(monkeypatch, jira_env):
    def fake_get(url, **kw):
        if url.endswith("/issue/SCRUM-42"):
            return FakeResp(200, SAMPLE_ISSUE)
        if url == "https://jira/att/1":
            return FakeResp(200, content=b"PNGDATA")
        return FakeResp(404)

    monkeypatch.setattr(jira_tool.requests, "get", fake_get)
    out = jira_tool.get_issue("SCRUM-42")

    assert out["ok"] is True
    d = out["defect"]
    assert d["defect_id"] == "SCRUM-42"
    assert d["title"] == "Checkout 500 on promo code"
    assert "promo code returns 500" in d["description"]
    assert d["environment"] == "production"
    assert d["reporter"] == "Jane QA"
    # only the PNG attachment is kept (pdf dropped by type); base64 round-trips
    assert len(d["image_attachments"]) == 1
    assert d["image_attachments"][0]["media_type"] == "image/png"
    assert base64.b64decode(d["image_attachments"][0]["data"]) == b"PNGDATA"


def test_get_issue_404_returns_reason(monkeypatch, jira_env):
    monkeypatch.setattr(jira_tool.requests, "get", lambda url, **kw: FakeResp(404))
    out = jira_tool.get_issue("NOPE-1")
    assert out["ok"] is False
    assert "not found" in out["reason"].lower()


def test_get_issue_not_configured(monkeypatch):
    for var in ("JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    out = jira_tool.get_issue("SCRUM-1")
    assert out["ok"] is False
    assert "not configured" in out["reason"].lower()


def test_get_jira_status(monkeypatch, jira_env):
    monkeypatch.setattr(jira_tool.requests, "get", lambda url, **kw: FakeResp(200, {"accountId": "x"}))
    assert jira_tool.get_jira_status()["connected"] is True

    monkeypatch.setattr(jira_tool.requests, "get", lambda url, **kw: FakeResp(401))
    assert jira_tool.get_jira_status()["connected"] is False


def test_browse_url(monkeypatch, jira_env):
    assert jira_tool.browse_url("SCRUM-9") == "https://jira.example.com/browse/SCRUM-9"


def test_browse_url_empty_when_unconfigured(monkeypatch):
    monkeypatch.delenv("JIRA_BASE_URL", raising=False)
    assert jira_tool.browse_url("SCRUM-9") == ""


def test_warning_for_classifies_failures():
    assert jira_tool.warning_for({"ok": True, "key": "X"}) is None
    assert jira_tool.warning_for({"ok": False, "skipped": True}) is None  # not configured → silent
    assert "credentials" in jira_tool.warning_for({"ok": False, "status": 401}).lower()
    assert "credentials" in jira_tool.warning_for({"ok": False, "status": 403}).lower()
    assert "rate-limit" in jira_tool.warning_for({"ok": False, "status": 429}).lower()
    assert "unreachable" in jira_tool.warning_for({"ok": False, "error": "timeout"}).lower()


def test_update_issue(monkeypatch, jira_env):
    calls = []

    def fake_put(url, **kw):
        calls.append((url, kw.get("json")))
        return FakeResp(204)

    monkeypatch.setattr(jira_tool.requests, "put", fake_put)
    out = jira_tool.update_issue("SCRUM-9", {"priority": {"name": "High"}})
    assert out["ok"] is True
    assert calls and calls[0][0].endswith("/issue/SCRUM-9")
    assert calls[0][1] == {"fields": {"priority": {"name": "High"}}}
