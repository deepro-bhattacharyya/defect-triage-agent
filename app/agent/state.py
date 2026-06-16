"""Shared state for the Defect Triage graph.

Every node receives the current TriageState and returns a partial dict that
LangGraph merges back in. Fields annotated with `operator.add` are *appended*
(list concatenation) instead of overwritten, so multiple nodes can each add
their own triage notes / similar defects without clobbering earlier ones.
"""

import operator
from typing import Annotated

from typing_extensions import TypedDict


class TriageState(TypedDict, total=False):
    # ---- Input (populated by intake_defect) ----
    defect_id: str
    title: str
    description: str
    stack_trace: str
    environment: str
    reporter: str
    # Each attachment: {"media_type": "image/png", "data": "<base64>"}
    # NOTE: last-wins (intentionally NOT an operator.add reducer). intake_defect
    # validates the raw input images and returns the cleaned list; a reducer here
    # would append the cleaned list to the raw seeded one and duplicate attachments.
    # intake_defect is the only writer, so overwrite semantics are correct.
    image_attachments: list[dict]

    # ---- Analysis (analyze_defect) ----
    category: str
    component: str
    root_cause: str

    # ---- Duplicate / Regression detection (check_duplicate) ----
    is_duplicate: bool
    duplicate_of: str
    is_regression: bool   # True when a match exists but is RESOLVED/CLOSED/DONE
    regression_of: str    # ID of the previously resolved defect
    similar_defects: Annotated[list[dict], operator.add]

    # ---- Triage (prioritize) ----
    severity: str         # CRITICAL | HIGH | MEDIUM | LOW
    priority: int         # 1 (highest) .. 4 (lowest)

    # ---- Assignment (assign_defect) ----
    assigned_team: str
    assigned_to: str

    # ---- Audit ----
    triage_notes: Annotated[list[str], operator.add]
    status: str           # in_triage | duplicate | assigned | escalated | ...
