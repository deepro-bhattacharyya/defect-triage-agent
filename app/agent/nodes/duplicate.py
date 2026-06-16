"""check_duplicate — duplicate / regression detection (no LLM).

Runs BEFORE any LLM call so confirmed duplicates skip analysis entirely.
Implements the contract from docs/PROJECT_PLAN.md exactly:

  * a match at/above SIMILARITY_THRESHOLD whose status is OPEN  -> DUPLICATE
    (short-circuit: route straight to flag_duplicate, no analysis),
  * a match whose status is RESOLVED/CLOSED/DONE                -> REGRESSION
    (a fixed bug resurfaced; proceed to analyze_defect like a new bug),
  * no match                                                    -> NEW defect.

`similarity_search_with_score` returns SIMILARITY (higher == closer); see
app/tools/vector_store.py for the distance->similarity conversion.
"""

from app.tools.vector_store import get_vector_store

# Calibrated for Gemini gemini-embedding-001 (this POC's embedder): real
# duplicate/regression pairs score ~0.81–0.85 while unrelated defects score
# ≤0.70, so 0.80 is the industry-standard cosine cutoff that separates them.
# (The plan's original 0.88 was tuned for OpenAI embeddings — see CLAUDE.md.)
SIMILARITY_THRESHOLD = 0.80
RESOLVED_STATUSES = {"RESOLVED", "CLOSED", "DONE"}


def check_duplicate(state: "dict") -> dict:
    query = f"{state.get('title', '')} {state.get('description', '')}".strip()
    results = get_vector_store().similarity_search_with_score(query, k=5)

    for doc, score in results:
        if score < SIMILARITY_THRESHOLD:
            continue
        matched_status = (doc.metadata.get("status", "") or "").upper()
        matched_id = doc.metadata.get("defect_id", "")

        if matched_status in RESOLVED_STATUSES:
            # Previously fixed defect is resurfacing — treat as regression.
            return {
                "is_duplicate": False,
                "duplicate_of": "",
                "is_regression": True,
                "regression_of": matched_id,
                "status": "in_triage",
                "triage_notes": [
                    f"[check_duplicate] REGRESSION of resolved defect {matched_id} "
                    f"(score {score:.3f})"
                ],
            }

        # Active duplicate found — skip LLM analysis entirely.
        return {
            "is_duplicate": True,
            "duplicate_of": matched_id,
            "is_regression": False,
            "regression_of": "",
            "status": "duplicate",
            "triage_notes": [
                f"[check_duplicate] DUPLICATE of open defect {matched_id} "
                f"(score {score:.3f})"
            ],
        }

    return {
        "is_duplicate": False,
        "duplicate_of": "",
        "is_regression": False,
        "regression_of": "",
        "status": "in_triage",
        "triage_notes": ["[check_duplicate] No match found — new defect"],
    }
