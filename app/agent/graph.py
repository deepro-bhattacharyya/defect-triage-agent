"""LangGraph wiring for the Defect Triage agent.

Assembles the nodes into the flow defined in docs/PROJECT_PLAN.md:

    START → intake_defect → check_duplicate ─┬─ DUPLICATE  → flag_duplicate → END
                                             └─ NEW/REGRESSION → analyze_defect
                                                                      ↓
                              prioritize ─┬─ CRITICAL → escalate → assign_defect ─┐
                                          └─ HIGH/MED/LOW ─────────→ assign_defect ┤
                                                                                   ↓
                                                                  notify → END

check_duplicate runs BEFORE any LLM call so confirmed duplicates skip analysis.
analyze_defect and prioritize get RetryPolicy(max_attempts=3) since they call the LLM.

assign_defect pauses via interrupt() for human assignee selection, so the graph must
be compiled with a checkpointer (the API passes MemorySaver()); every run then needs
a config with configurable.thread_id. Compiling without one (tests of the
straight-through path) still works as long as assign_defect finds no candidates.
"""

from typing import Literal

from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy

from app.agent.nodes.analyze import analyze_defect
from app.agent.nodes.assign import assign_defect
from app.agent.nodes.duplicate import check_duplicate
from app.agent.nodes.escalate import escalate
from app.agent.nodes.flag_dup import flag_duplicate
from app.agent.nodes.intake import intake_defect
from app.agent.nodes.notify import notify
from app.agent.nodes.prioritize import prioritize
from app.agent.state import TriageState


def route_after_check(state: TriageState) -> Literal["flag_duplicate", "analyze_defect"]:
    # Only confirmed duplicates of an OPEN defect short-circuit. Regressions
    # (is_regression=True) proceed to analyze_defect like new bugs.
    return "flag_duplicate" if state.get("is_duplicate") else "analyze_defect"


def route_severity(state: TriageState) -> Literal["escalate", "assign_defect"]:
    return "escalate" if state.get("severity") == "CRITICAL" else "assign_defect"


def build_graph(checkpointer=None):
    builder = StateGraph(TriageState)

    builder.add_node("intake_defect", intake_defect)
    builder.add_node("check_duplicate", check_duplicate)
    builder.add_node("analyze_defect", analyze_defect, retry_policy=RetryPolicy(max_attempts=3))
    builder.add_node("prioritize", prioritize, retry_policy=RetryPolicy(max_attempts=3))
    builder.add_node("assign_defect", assign_defect)
    builder.add_node("escalate", escalate)
    builder.add_node("flag_duplicate", flag_duplicate)
    builder.add_node("notify", notify)

    builder.add_edge(START, "intake_defect")
    builder.add_edge("intake_defect", "check_duplicate")  # duplicate check first
    builder.add_conditional_edges(
        "check_duplicate", route_after_check, ["flag_duplicate", "analyze_defect"]
    )
    builder.add_edge("analyze_defect", "prioritize")
    builder.add_conditional_edges(
        "prioritize", route_severity, ["escalate", "assign_defect"]
    )
    builder.add_edge("escalate", "assign_defect")
    builder.add_edge("assign_defect", "notify")
    builder.add_edge("notify", END)
    builder.add_edge("flag_duplicate", END)

    return builder.compile(checkpointer=checkpointer)
