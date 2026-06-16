"""Unit tests for intake_defect — normalization + image guardrails. No LLM, no key."""

import base64

from app.agent.nodes import intake
from app.agent.nodes.intake import intake_defect


def _img(media_type="image/png", kb=1):
    data = base64.b64encode(b"x" * (kb * 1024)).decode()
    return {"media_type": media_type, "data": data}


def test_normalizes_fields_and_trims_whitespace():
    out = intake_defect(
        {
            "defect_id": " DEF-201 ",
            "title": "  Payment down  ",
            "description": "  all users  ",
            "environment": " production ",
            "reporter": " oncall ",
        }
    )
    assert out["defect_id"] == "DEF-201"
    assert out["title"] == "Payment down"
    assert out["description"] == "all users"
    assert out["environment"] == "production"
    assert out["reporter"] == "oncall"
    assert out["stack_trace"] == ""           # missing field defaulted
    assert out["image_attachments"] == []
    assert out["triage_notes"][0].startswith("[intake_defect]")


def test_missing_fields_default_safely():
    out = intake_defect({})
    for key in ("defect_id", "title", "description", "stack_trace", "environment", "reporter"):
        assert out[key] == ""
    assert out["image_attachments"] == []


def test_valid_image_is_kept_and_media_type_lowercased():
    out = intake_defect({"title": "x", "image_attachments": [_img("IMAGE/PNG")]})
    assert len(out["image_attachments"]) == 1
    assert out["image_attachments"][0]["media_type"] == "image/png"


def test_unsupported_media_type_is_dropped():
    out = intake_defect({"image_attachments": [{"media_type": "image/bmp", "data": "abc"}]})
    assert out["image_attachments"] == []
    assert "dropped 1" in out["triage_notes"][0]


def test_empty_data_is_dropped():
    out = intake_defect({"image_attachments": [{"media_type": "image/png", "data": ""}]})
    assert out["image_attachments"] == []


def test_oversized_image_is_dropped(monkeypatch):
    monkeypatch.setattr(intake, "MAX_IMAGE_MB", 0.001)  # ~1 KB cap
    out = intake_defect({"image_attachments": [_img("image/png", kb=50)]})
    assert out["image_attachments"] == []


def test_caps_at_max_images(monkeypatch):
    monkeypatch.setattr(intake, "MAX_IMAGES", 3)
    out = intake_defect({"image_attachments": [_img() for _ in range(5)]})
    assert len(out["image_attachments"]) == 3
    assert "dropped 2" in out["triage_notes"][0]


def test_does_not_mutate_input():
    state = {"title": "x", "image_attachments": [_img("image/bmp")]}
    before = list(state["image_attachments"])
    intake_defect(state)
    assert state["image_attachments"] == before  # original untouched
