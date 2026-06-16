"""prioritize — severity (CRITICAL/HIGH/MEDIUM/LOW) + priority (1–4).

Asks the LLM for a severity/priority, then applies a deterministic safety net:

1. **Rule-based CRITICAL override** — if the defect text contains an
   unambiguous outage/data-loss signal, force CRITICAL regardless of what the
   LLM said. The costliest mistake is under-rating a real emergency, so rules win.
2. **Rule-based fallback** — if the LLM call or its JSON fails, fall back to a
   keyword classifier so the node always yields a valid severity (LLM provider
   outage must not stop triage).

Priority is derived from severity: CRITICAL=1, HIGH=2, MEDIUM=3, LOW=4.
"""

from langchain_core.messages import HumanMessage

from app.tools.llm import get_llm
from app.tools.parsing import extract_json

VALID_SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW")
SEVERITY_TO_PRIORITY = {"CRITICAL": 1, "HIGH": 2, "MEDIUM": 3, "LOW": 4}

# Unambiguous "this is an emergency" signals — force CRITICAL if any appear.
CRITICAL_KEYWORDS = (
    "all users",
    "completely down",
    "service down",
    "service is down",
    "no user can",
    "outage",
    "data loss",
    "data breach",
    "data corruption",
    "security breach",
    "payment service down",
)

# Cheap LOW signals used only by the rule-based fallback classifier.
LOW_KEYWORDS = ("cosmetic", "typo", "misaligned", "visual only", "purely visual", "alignment")


def _text_blob(state: dict) -> str:
    return " ".join(
        [state.get("title", ""), state.get("description", ""), state.get("stack_trace", "")]
    ).lower()


def _rule_based_severity(state: dict) -> str:
    blob = _text_blob(state)
    if any(kw in blob for kw in CRITICAL_KEYWORDS):
        return "CRITICAL"
    if any(kw in blob for kw in LOW_KEYWORDS):
        return "LOW"
    if state.get("environment", "").lower() == "production":
        return "HIGH"
    return "MEDIUM"


def _llm_severity(state: dict) -> str:
    prompt = (
        "You are triaging a software defect. Respond with ONLY a JSON object with keys "
        '"severity" (one of CRITICAL, HIGH, MEDIUM, LOW) and "priority" (1=highest..4=lowest).\n\n'
        f"Title: {state.get('title', '')}\n"
        f"Description: {state.get('description', '')}\n"
        f"Environment: {state.get('environment', '')}\n"
        f"Category: {state.get('category', '')}\n"
        f"Component: {state.get('component', '')}"
    )
    response = get_llm().invoke([HumanMessage(content=prompt)])
    raw = response.content if isinstance(response.content, str) else str(response.content)
    data = extract_json(raw)
    severity = str(data["severity"]).upper().strip()
    if severity not in VALID_SEVERITIES:
        raise ValueError(f"invalid severity from LLM: {severity!r}")
    return severity


def prioritize(state: dict) -> dict:
    notes = []

    try:
        severity = _llm_severity(state)
        source = "LLM"
    except Exception:
        severity = _rule_based_severity(state)
        source = "rule-based fallback"
        notes.append("[prioritize] LLM unavailable/invalid — used rule-based fallback")

    # Deterministic CRITICAL override always wins over the LLM.
    if any(kw in _text_blob(state) for kw in CRITICAL_KEYWORDS) and severity != "CRITICAL":
        notes.append(f"[prioritize] rule override: {severity} -> CRITICAL (emergency keyword)")
        severity = "CRITICAL"

    priority = SEVERITY_TO_PRIORITY[severity]
    notes.append(f"[prioritize] {severity} (priority {priority}) via {source}")

    return {"severity": severity, "priority": priority, "triage_notes": notes}
