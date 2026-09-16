"""Deterministic test doubles used only by evaluation modes."""

from advisor import (
    ALLOW_REPEAT,
    CROSS_CUISINE,
    GIVE_UP,
    RelaxationChoice,
    RepairContext,
    WeekContext,
    WeekProposal,
)
from telemetry import traced

from mcp_models import AgentModelTurn, AgentToolRequest


class DeterministicMCPDecisionModel:
    """Tool-result-driven stand-in for repeatable MCP trajectory evaluation.

    This is not used by the application. It follows the same model adapter
    contract as the live OpenAI tool caller, but chooses the next action
    deterministically from actual MCP results so agent tests need no API key.
    """

    def __init__(self, pantry: dict, request: dict):
        self.pantry = pantry
        self.request = request
        self.phase = 0
        self.candidate_ids: list[str] = []
        self.proposal: list[str] = []

    @staticmethod
    def _last_tool_result(messages: list[dict]) -> dict:
        import json

        for message in reversed(messages):
            if message.get("role") == "tool":
                return json.loads(message["content"])
        return {}

    async def next_turn(self, messages, tools):
        if self.phase == 0:
            name = "search_recipes"
            arguments = {
                "pantry": self.pantry,
                "request": self.request,
                "top_k": 40,
                "backend": "local",
            }
        elif self.phase == 1:
            result = self._last_tool_result(messages)
            self.candidate_ids = [item["recipe_id"] for item in result["candidates"]]
            name = "get_recipe_details"
            arguments = {"recipe_ids": self.candidate_ids}
        elif self.phase == 2:
            name = "evaluate_candidates"
            arguments = {
                "recipe_ids": self.candidate_ids,
                "pantry": self.pantry,
                "request": self.request,
            }
        elif self.phase == 3:
            result = self._last_tool_result(messages)
            eligible = [score for score in result["scores"] if score["eligible"]]
            eligible.sort(
                key=lambda score: (
                    -score["cuisine_score"],
                    -score["total_score"],
                    -score["pantry_coverage"],
                    abs(score["calorie_delta"]),
                    score["recipe_id"],
                )
            )
            self.proposal = [
                score["recipe_id"] for score in eligible[: self.request["days"]]
            ]
            name = "simulate_plan"
            arguments = {
                "pantry": self.pantry,
                "request": self.request,
                "ordered_recipe_ids": self.proposal,
            }
        else:
            name = "validate_final_plan"
            arguments = {
                "pantry": self.pantry,
                "request": self.request,
                "ordered_recipe_ids": self.proposal,
            }

        self.phase += 1
        call_id = f"fake-mcp-{self.phase}"
        request = AgentToolRequest(call_id=call_id, name=name, arguments=arguments)
        return AgentModelTurn(
            kind="tool_calls",
            tool_calls=[request],
            raw_assistant_message={
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": name,
                            "arguments": __import__("json").dumps(arguments),
                        },
                    }
                ],
            },
        )


class FakePlannerAdvisor:
    """Reproducible advisor that only chooses from supplied candidates/menu."""

    @traced(name="advisor_call", run_type="tool")
    def plan_week(self, ctx: WeekContext) -> WeekProposal:
        eligible = [c for c in ctx.candidates if c.eligible]
        eligible.sort(
            key=lambda c: (
                not c.cuisine_match,
                -c.total_score,
                -c.pantry_coverage,
                abs(c.calorie_delta),
                c.recipe_id,
            )
        )
        return WeekProposal(
            ordered_recipe_ids=[c.recipe_id for c in eligible[: ctx.days]],
            rationale="Deterministic score ordering for reproducible evaluation.",
        )

    @traced(name="relaxation_decision", run_type="tool")
    def choose_relaxation(self, ctx: RepairContext) -> RelaxationChoice:
        for choice in (ALLOW_REPEAT, CROSS_CUISINE, GIVE_UP):
            if choice in ctx.menu and choice not in ctx.tried_relaxations:
                return RelaxationChoice(
                    choice=choice,
                    rationale="First untried allowed relaxation in fixed evaluation order.",
                )
        return RelaxationChoice(choice=GIVE_UP, rationale="No untried relaxation remains.")
