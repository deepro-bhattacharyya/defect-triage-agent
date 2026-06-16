"""LLM client for the Defect Triage agent.

Centralizes the chat-model client so nodes (analyze_defect, prioritize) import
one shared `get_llm()` instead of constructing a client each. Keeping it behind
this tools layer means swapping providers/models touches only this file.

NOTE: Production uses Anthropic Claude Sonnet 4.6 (claude-sonnet-4-6). For local
development and testing this is currently wired to Google Gemini 1.5 Flash, which
is cheaper/faster for iteration. The model is multimodal (text + base64 images),
matching how analyze_defect builds its content blocks.
"""

import os

from langchain_google_genai import ChatGoogleGenerativeAI

# Gemini 1.5 Flash — local dev / testing only. Swap back to ChatAnthropic
# (claude-sonnet-4-6) for production. Key comes from the GOOGLE_API_KEY env var.
DEV_MODEL = "gemini-1.5-flash"


def get_llm(temperature: float = 0.0) -> ChatGoogleGenerativeAI:
    """Return the shared chat-model client.

    Reads GOOGLE_API_KEY from the environment. temperature defaults to 0 for
    deterministic, structured-JSON-friendly output.
    """
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GOOGLE_API_KEY is not set. Add it to your .env "
            "(local dev uses Gemini; production uses Claude Sonnet 4.6)."
        )
    return ChatGoogleGenerativeAI(
        model=DEV_MODEL,
        google_api_key=api_key,
        temperature=temperature,
    )
