"""Evaluate the triage agent against the plan's target metrics.

Runs all scenarios in tests/fixtures/sample_defects.json through the live graph
and reports: severity accuracy, duplicate precision, assignment-made rate, and
average latency. Requires GOOGLE_API_KEY (Gemini).

    python scripts/evaluate.py

NOTE: the fixture set is only 5 scenarios — too small for the plan's percentage
targets (which are dataset-level goals). This is a smoke-level evaluation that the
pipeline behaves correctly end-to-end; scale up with a real labeled dataset
(see docs/DATA.md) for statistically meaningful accuracy.
"""

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from app.agent.graph import build_graph  # noqa: E402
from app.tools.vector_store import get_vector_store  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"


def _defect_input(scenario):
    keep = ("defect_id", "title", "description", "stack_trace", "environment", "reporter")
    payload = {k: scenario[k] for k in keep if k in scenario}
    payload["image_attachments"] = [
        {"media_type": img["media_type"], "data": img["data"]}
        for img in scenario.get("image_attachments", [])
    ]
    return payload


def main():
    get_vector_store().add_defects(
        json.loads((FIXTURES / "seed_backlog.json").read_text(encoding="utf-8"))["defects"]
    )
    scenarios = json.loads((FIXTURES / "sample_defects.json").read_text(encoding="utf-8"))["scenarios"]
    graph = build_graph()

    sev_total = sev_ok = 0
    dup_predicted = dup_correct = 0
    assign_total = assign_ok = 0
    latencies = []

    print(f"{'scenario':<42}{'sev':<10}{'expected':<10}{'route ok':<10}{'sec':<6}")
    print("-" * 78)

    for s in scenarios:
        exp = s["expected"]
        start = time.perf_counter()
        try:
            out = graph.invoke(_defect_input(s))
        except Exception as e:
            if "RESOURCE_EXHAUSTED" in str(e) or "429" in str(e):
                print(f"{s['_scenario']:<42}QUOTA EXHAUSTED — stopping early (free tier = 20 req/day)")
                break
            raise
        elapsed = time.perf_counter() - start
        latencies.append(elapsed)

        # severity accuracy
        sev = out.get("severity")
        if "severity" in exp:
            sev_total += 1
            if sev == exp["severity"]:
                sev_ok += 1

        # duplicate precision (of predicted duplicates, how many were correct)
        if out.get("is_duplicate"):
            dup_predicted += 1
            if exp.get("is_duplicate") and out.get("duplicate_of") == exp.get("duplicate_of"):
                dup_correct += 1

        # assignment made for non-duplicate paths
        if not exp["is_duplicate"]:
            assign_total += 1
            if out.get("assigned_team"):
                assign_ok += 1

        route_ok = "yes" if out.get("status") in ("notified", "closed_duplicate") else "NO"
        print(f"{s['_scenario']:<42}{str(sev):<10}{str(exp.get('severity','-')):<10}{route_ok:<10}{elapsed:<6.1f}")

    print("-" * 78)
    if not latencies:
        print("\nNo scenarios completed (quota exhausted before the first call).")
        return

    def pct(n, d):
        return f"{100 * n / d:.0f}% ({n}/{d})" if d else "n/a"

    print("\n=== Metrics (N=5 smoke eval; targets are dataset-level goals) ===")
    print(f"  Severity accuracy   : {pct(sev_ok, sev_total)}   target >= 90%")
    print(f"  Duplicate precision : {pct(dup_correct, dup_predicted)}   target >= 95%")
    print(f"  Assignment made     : {pct(assign_ok, assign_total)}   target >= 85%")
    print(f"  Avg latency         : {sum(latencies)/len(latencies):.1f}s   target < 10s")
    print(f"  Max latency         : {max(latencies):.1f}s")


if __name__ == "__main__":
    main()
