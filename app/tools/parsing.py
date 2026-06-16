"""Defensive JSON extraction for LLM output.

LLMs (Gemini included) often wrap JSON in ```json fences``` or add a sentence
before/after it. `extract_json` pulls the first JSON object out of a string and
parses it, raising ValueError if there isn't one — callers catch that to fall
back to safe defaults / the rule-based path.
"""

import json


def extract_json(text: str) -> dict:
    if not text or not text.strip():
        raise ValueError("empty LLM response")

    cleaned = text.strip()

    # Strip a leading ```json / ``` fence and trailing ``` if present.
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1] if "\n" in cleaned else cleaned[3:]
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rstrip()[:-3]

    # Fast path: it's already clean JSON.
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Fallback: grab the outermost {...} span and parse that.
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("no JSON object found in LLM response")
    return json.loads(cleaned[start : end + 1])
