"""Unit tests for prioritize. LLM is mocked — no network, no key."""

import pytest

from app.agent.nodes import prioritize as prio
from app.agent.nodes.prioritize import prioritize


class FakeMsg:
    def __init__(self, content):
        self.content = content


def _patch_llm_returns(monkeypatch, content):
    monkeypatch.setattr(prio, "get_llm", lambda: type("L", (), {"invoke": lambda self, m: FakeMsg(content)})())


def _patch_llm_raises(monkeypatch):
    def boom():
        raise RuntimeError("provider outage")

    monkeypatch.setattr(prio, "get_llm", lambda: boom())


def test_uses_llm_severity_for_normal_bug(monkeypatch):
    _patch_llm_returns(monkeypatch, '{"severity": "LOW", "priority": 4}')
    out = prioritize({"title": "Button misaligned", "description": "purely visual", "environment": "staging"})
    assert out["severity"] == "LOW"
    assert out["priority"] == 4


def test_priority_derived_from_severity(monkeypatch):
    _patch_llm_returns(monkeypatch, '{"severity": "HIGH", "priority": 99}')  # bogus priority ignored
    out = prioritize({"title": "x", "description": "y"})
    assert out["severity"] == "HIGH"
    assert out["priority"] == 2  # derived, not the LLM's 99


def test_keyword_override_forces_critical_even_if_llm_says_low(monkeypatch):
    _patch_llm_returns(monkeypatch, '{"severity": "LOW", "priority": 4}')
    out = prioritize(
        {
            "title": "Payment service completely down in production",
            "description": "All users affected, no user can complete a purchase.",
            "environment": "production",
        }
    )
    assert out["severity"] == "CRITICAL"
    assert out["priority"] == 1
    assert any("override" in n for n in out["triage_notes"])


def test_llm_failure_falls_back_to_rules(monkeypatch):
    _patch_llm_raises(monkeypatch)
    out = prioritize({"title": "Dashboard slow", "description": "loads slowly", "environment": "production"})
    assert out["severity"] in ("CRITICAL", "HIGH", "MEDIUM", "LOW")
    assert out["severity"] == "HIGH"  # production, no low/critical keywords
    assert any("fallback" in n for n in out["triage_notes"])


def test_llm_failure_still_honors_critical_keywords(monkeypatch):
    _patch_llm_raises(monkeypatch)
    out = prioritize({"title": "Total outage", "description": "data loss across all users", "environment": "production"})
    assert out["severity"] == "CRITICAL"
    assert out["priority"] == 1


def test_invalid_llm_severity_falls_back(monkeypatch):
    _patch_llm_returns(monkeypatch, '{"severity": "SUPERBAD", "priority": 1}')
    out = prioritize({"title": "x", "description": "y", "environment": "staging"})
    assert out["severity"] == "MEDIUM"  # rule fallback: staging, no keywords
    assert any("fallback" in n for n in out["triage_notes"])


@pytest.mark.parametrize("sev,pri", [("CRITICAL", 1), ("HIGH", 2), ("MEDIUM", 3), ("LOW", 4)])
def test_all_severities_map_to_priority(monkeypatch, sev, pri):
    _patch_llm_returns(monkeypatch, f'{{"severity": "{sev}", "priority": 0}}')
    out = prioritize({"title": "neutral", "description": "neutral bug"})
    assert out["severity"] == sev
    assert out["priority"] == pri
