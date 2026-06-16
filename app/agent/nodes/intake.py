"""intake_defect — the first node. Normalize raw input + validate attachments.

No LLM. Enforces the image guardrails from the plan's Risks table:
  * at most MAX_IMAGES images (default 3),
  * at most MAX_IMAGE_MB per image (default 5 MB),
  * only supported media types,
oversized / excess / unsupported / malformed attachments are dropped here so
every later node — especially the multimodal LLM in analyze_defect — only ever
sees safe, well-formed images.

⚠️ Reducer caveat (flagged for Phase 5 graph wiring): `image_attachments` is an
`operator.add` field in TriageState, so a returned list is *appended* to whatever
is already there. intake is the canonical validator and returns the cleaned list;
the graph must therefore start intake with an *empty* `image_attachments` channel
(i.e. don't pre-seed the reducer with the raw images and also return them) or the
raw + cleaned lists will concatenate. See the note in graph.py when we get there.
"""

import os

MAX_IMAGE_MB = float(os.environ.get("MAX_IMAGE_MB", "5"))
MAX_IMAGES = int(os.environ.get("MAX_IMAGES", "3"))
SUPPORTED_MEDIA_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}


def _estimated_bytes(b64_data: str) -> int:
    """Decoded byte size of a base64 string, without actually decoding it."""
    stripped = b64_data.strip()
    padding = stripped.count("=")
    return (len(stripped) * 3) // 4 - padding


def _valid_images(raw_images):
    """Return (kept, dropped_count) after applying the guardrails in order."""
    kept, dropped = [], 0
    max_bytes = MAX_IMAGE_MB * 1024 * 1024
    for img in raw_images:
        if len(kept) >= MAX_IMAGES:
            dropped += 1
            continue
        media_type = (img.get("media_type") or "").lower()
        data = img.get("data") or ""
        if media_type not in SUPPORTED_MEDIA_TYPES or not data:
            dropped += 1
            continue
        if _estimated_bytes(data) > max_bytes:
            dropped += 1
            continue
        kept.append({"media_type": media_type, "data": data})
    return kept, dropped


def intake_defect(state: "dict") -> dict:
    defect_id = (state.get("defect_id") or "").strip()
    title = (state.get("title") or "").strip()
    description = (state.get("description") or "").strip()
    stack_trace = (state.get("stack_trace") or "").strip()
    environment = (state.get("environment") or "").strip()
    reporter = (state.get("reporter") or "").strip()

    kept_images, dropped = _valid_images(state.get("image_attachments") or [])

    note = (
        f"[intake_defect] normalized {defect_id or '(no id)'}; "
        f"kept {len(kept_images)} image(s), dropped {dropped}"
    )

    return {
        "defect_id": defect_id,
        "title": title,
        "description": description,
        "stack_trace": stack_trace,
        "environment": environment,
        "reporter": reporter,
        "image_attachments": kept_images,
        "triage_notes": [note],
    }
