"""analyze_defect — LLM root-cause analysis (multimodal: text + images).

Runs only for new bugs and regressions (confirmed duplicates short-circuit
before this). Sends the defect text plus any image attachments to the LLM and
asks for strict JSON: category, component, root_cause.

Parsing is defensive (see app/tools/parsing.extract_json). On a parse failure
the node degrades gracefully to safe defaults instead of crashing the graph —
transient API errors propagate so the graph-level RetryPolicy(max_attempts=3)
can retry the call.

NOTE: the image blocks use LangChain's data-URI `image_url` format, which the
Gemini chat model accepts. (The plan's Anthropic-style `source`/`base64` block is
provider-specific; this is the equivalent for the dev LLM.)
"""

from langchain_core.messages import HumanMessage

from app.tools.llm import get_llm
from app.tools.parsing import extract_json


def _build_content(state: dict) -> list:
    regression_note = (
        f"[REGRESSION] This defect matches previously resolved issue "
        f"{state.get('regression_of', '')}. Focus on what may have regressed.\n\n"
        if state.get("is_regression")
        else ""
    )
    text = (
        f"{regression_note}"
        "Analyze this software defect. Respond with ONLY a JSON object containing "
        'exactly these keys: "category", "component", "root_cause".\n\n'
        f"Title: {state.get('title', '')}\n"
        f"Description: {state.get('description', '')}\n"
        f"Stack Trace: {state.get('stack_trace') or 'N/A'}"
    )

    content = [{"type": "text", "text": text}]
    for img in state.get("image_attachments", []):
        content.append(
            {
                "type": "image_url",
                "image_url": f"data:{img['media_type']};base64,{img['data']}",
            }
        )
    return content


def _as_text(content) -> str:
    """AIMessage.content is usually a str, but can be a list of blocks."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                parts.append(block.get("text", ""))
        return "".join(parts)
    return str(content)


def analyze_defect(state: dict) -> dict:
    response = get_llm().invoke([HumanMessage(content=_build_content(state))])
    raw = _as_text(response.content)

    prefix = "[REGRESSION] " if state.get("is_regression") else ""
    try:
        data = extract_json(raw)
        category = str(data["category"])
        component = str(data["component"])
        root_cause = str(data["root_cause"])
    except (ValueError, KeyError, TypeError):
        # Graceful degradation — keep the graph moving with safe defaults.
        return {
            "category": "unknown",
            "component": "unknown",
            "root_cause": "analysis unavailable (could not parse LLM output)",
            "triage_notes": [
                f"{prefix}[analyze_defect] WARN: unparseable LLM output; used defaults"
            ],
        }

    return {
        "category": category,
        "component": component,
        "root_cause": root_cause,
        "triage_notes": [f"{prefix}[analyze_defect] {category} in {component}"],
    }
