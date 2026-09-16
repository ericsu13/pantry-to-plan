"""Run the 23-case golden dataset through the single agent + real MCP transport."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import time

from evaluation.dataset import build_cases
from evaluation.evaluators import evaluate_case
from evaluation.fakes import DeterministicMCPDecisionModel
from evaluation.run_eval import load_case_inputs
from mcp_planner_agent import MCPPlannerAgent


RESULTS = Path(__file__).resolve().parent / "results" / "baseline-mcp-agent-fake-v1"
EXPECTATION_OVERRIDES = (
    Path(__file__).resolve().parent / "datasets" / "mcp_agent_expectations_v1.json"
)


def agent_expected(case: dict) -> dict:
    overrides = json.loads(EXPECTATION_OVERRIDES.read_text())
    return overrides.get(case["case_id"], case["expected"])


async def run_case(case: dict) -> dict:
    pantry, request = load_case_inputs(case["inputs"])
    model = DeterministicMCPDecisionModel(
        pantry.model_dump(mode="json"),
        request.model_dump(mode="json"),
    )
    agent = MCPPlannerAgent(
        model,
        max_tool_calls=8,
        max_plan_revisions=1,
        total_timeout_seconds=20,
    )
    started = time.perf_counter()
    try:
        plan = await agent.plan(pantry, request)
        error = None
    except Exception as exc:  # keep the batch running and report the failed case
        plan = None
        error = f"{type(exc).__name__}: {exc}"
    latency_ms = round((time.perf_counter() - started) * 1000, 3)
    if plan is None:
        return {
            "case_id": case["case_id"],
            "overall_case_pass": False,
            "latency_ms": latency_ms,
            "error": error,
        }
    outputs = {
        "predicted": plan.model_dump(mode="json"),
        "advisor_mode": "mcp-agent-fake",
        "latency_ms": latency_ms,
        "error": None,
    }
    evaluated = evaluate_case(case["inputs"], outputs, {"expected": agent_expected(case)})
    return {
        "case_id": case["case_id"],
        **evaluated,
        "latency_ms": latency_ms,
        "tool_calls": sum(event.step == "mcp_tool" for event in plan.trace),
        "error": None,
    }


async def main_async() -> int:
    results = []
    for case in build_cases():
        result = await run_case(case)
        results.append(result)
        print(
            f"{result['case_id']}: "
            f"{'PASS' if result['overall_case_pass'] else 'FAIL'}"
        )
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "case_results.json").write_text(json.dumps(results, indent=2) + "\n")
    summary = {
        "cases": len(results),
        "passed": sum(item["overall_case_pass"] for item in results),
        "failed": sum(not item["overall_case_pass"] for item in results),
        "average_latency_ms": round(
            sum(item["latency_ms"] for item in results) / len(results), 3
        ),
        "scope": "single fake decision model over real local stdio MCP tools; vision excluded",
    }
    (RESULTS / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return 0 if summary["failed"] == 0 else 1


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    raise SystemExit(main())
