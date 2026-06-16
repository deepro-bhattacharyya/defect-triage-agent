"""Unit tests for analyze_defect. LLM is mocked — no network, no key."""

from app.agent.nodes import analyze
from app.agent.nodes.analyze import analyze_defect


class FakeMsg:
    def __init__(self, content):
        self.content = content


class FakeLLM:
    """Records the message it was invoked with and returns a canned response."""

    def __init__(self, content):
        self._content = content
        self.last_messages = None

    def invoke(self, messages):
        self.last_messages = messages
        return FakeMsg(self._content)


def _patch_llm(monkeypatch, content):
    fake = FakeLLM(content)
    monkeypatch.setattr(analyze, "get_llm", lambda: fake)
    return fake


def test_parses_clean_json(monkeypatch):
    _patch_llm(monkeypatch, '{"category": "backend", "component": "checkout-service", "root_cause": "null deref"}')
    out = analyze_defect({"title": "x", "description": "y"})
    assert out["category"] == "backend"
    assert out["component"] == "checkout-service"
    assert out["root_cause"] == "null deref"
    assert out["triage_notes"][0] == "[analyze_defect] backend in checkout-service"


def test_parses_json_in_markdown_fence(monkeypatch):
    fenced = '```json\n{"category": "ui", "component": "web-frontend", "root_cause": "css"}\n```'
    _patch_llm(monkeypatch, fenced)
    out = analyze_defect({"title": "x", "description": "y"})
    assert out["component"] == "web-frontend"


def test_regression_prefix_and_note(monkeypatch):
    fake = _patch_llm(monkeypatch, '{"category": "auth", "component": "auth-service", "root_cause": "race"}')
    out = analyze_defect({"title": "x", "description": "y", "is_regression": True, "regression_of": "DEF-050"})
    assert out["triage_notes"][0].startswith("[REGRESSION] [analyze_defect]")
    # the regression instruction must reach the model
    text_block = fake.last_messages[0].content[0]["text"]
    assert "REGRESSION" in text_block and "DEF-050" in text_block


def test_image_attachment_included_in_content(monkeypatch):
    fake = _patch_llm(monkeypatch, '{"category": "ui", "component": "web", "root_cause": "x"}')
    analyze_defect(
        {
            "title": "x",
            "description": "y",
            "image_attachments": [{"media_type": "image/png", "data": "QUJD"}],
        }
    )
    content = fake.last_messages[0].content
    image_blocks = [b for b in content if b.get("type") == "image_url"]
    assert len(image_blocks) == 1
    assert image_blocks[0]["image_url"] == "data:image/png;base64,QUJD"


def test_bad_json_degrades_gracefully(monkeypatch):
    _patch_llm(monkeypatch, "Sorry, I cannot help with that.")
    out = analyze_defect({"title": "x", "description": "y"})
    assert out["category"] == "unknown"
    assert out["component"] == "unknown"
    assert "WARN" in out["triage_notes"][0]


def test_missing_key_degrades_gracefully(monkeypatch):
    _patch_llm(monkeypatch, '{"category": "backend"}')  # no component/root_cause
    out = analyze_defect({"title": "x", "description": "y"})
    assert out["category"] == "unknown"  # whole parse falls back, not partial
