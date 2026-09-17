"""Deterministic trajectory tests for the single MCP planning agent."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import unittest

from mcp_models import AgentModelTurn, AgentToolRequest, MCPToolDefinition
from mcp_planner_agent import MCPAgentError, MCPPlannerAgent
from meal_tools_server import (
    evaluate_candidates_impl,
    get_recipe_details_impl,
    search_recipes_impl,
    simulate_plan_impl,
    validate_final_plan_impl,
)
from schemas import PantryItem, PantryState, PlanningRequest


ROOT = Path(__file__).resolve().parents[1]
PROPOSAL = ["it_mushroom_risotto", "it_penne_arrabbiata", "it_aglio_e_olio"]


def case_inputs():
    fx = json.loads((ROOT / "fixtures/01_well_stocked_veg_italian.json").read_text())
    pantry = PantryState(
        items=[
            PantryItem(
                ingredient_id=ingredient_id,
                display_name=ingredient_id.replace("_", " "),
                quantity_g=quantity,
                confidence=1.0,
            )
            for ingredient_id, quantity in fx["pantry"]["items"].items()
        ]
    )
    return pantry, PlanningRequest.model_validate(fx["request"])


class InProcessMealToolsClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def list_tools(self):
        names = [
            "search_recipes",
            "get_recipe_details",
            "evaluate_candidates",
            "simulate_plan",
            "validate_final_plan",
        ]
        return [MCPToolDefinition(name=name, input_schema={}) for name in names]

    async def call_tool(self, name, arguments):
        functions = {
            "search_recipes": search_recipes_impl,
            "get_recipe_details": get_recipe_details_impl,
            "evaluate_candidates": evaluate_candidates_impl,
            "simulate_plan": simulate_plan_impl,
            "validate_final_plan": validate_final_plan_impl,
        }
        return functions[name](**arguments)


class ScriptedDecisionModel:
    def __init__(self, calls):
        self.calls = list(calls)

    async def next_turn(self, messages, tools):
        if not self.calls:
            return AgentModelTurn(kind="message", message="done", raw_assistant_message={"role": "assistant", "content": "done"})
        name, arguments = self.calls.pop(0)
        call_id = f"call-{len(messages)}"
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
                        "function": {"name": name, "arguments": json.dumps(arguments)},
                    }
                ],
            },
        )


def calls_for(pantry, request, *, include_simulation=True):
    pantry_data = pantry.model_dump(mode="json")
    request_data = request.model_dump(mode="json")
    calls = [
        ("search_recipes", {"pantry": pantry_data, "request": request_data, "top_k": 12, "backend": "local"}),
        ("get_recipe_details", {"recipe_ids": PROPOSAL}),
        ("evaluate_candidates", {"recipe_ids": PROPOSAL, "pantry": pantry_data, "request": request_data}),
    ]
    if include_simulation:
        calls.append(("simulate_plan", {"pantry": pantry_data, "request": request_data, "ordered_recipe_ids": PROPOSAL}))
    calls.append(("validate_final_plan", {"pantry": pantry_data, "request": request_data, "ordered_recipe_ids": PROPOSAL}))
    return calls


class MCPPlannerAgentTests(unittest.TestCase):
    def test_agent_uses_tools_and_returns_only_validated_plan(self):
        pantry, request = case_inputs()
        agent = MCPPlannerAgent(
            ScriptedDecisionModel(calls_for(pantry, request)),
            client_factory=InProcessMealToolsClient,
            total_timeout_seconds=5,
        )
        plan = asyncio.run(agent.plan(pantry, request))
        self.assertEqual([day.recipe.recipe_id for day in plan.day_plans], PROPOSAL)
        steps = [event.step for event in plan.trace]
        self.assertEqual(steps.count("mcp_tool"), 5)
        self.assertIn("agent_complete", steps)
        self.assertTrue(all(day.recipe.vegetarian for day in plan.day_plans))

    def test_controller_requires_simulation_before_final_validation(self):
        pantry, request = case_inputs()
        calls = calls_for(pantry, request, include_simulation=False)
        model = ScriptedDecisionModel(calls)
        agent = MCPPlannerAgent(
            model,
            client_factory=InProcessMealToolsClient,
            total_timeout_seconds=5,
        )
        with self.assertRaises(MCPAgentError):
            asyncio.run(agent.plan(pantry, request))

    def test_tool_budget_is_bounded(self):
        pantry, request = case_inputs()
        repeated = [("get_recipe_details", {"recipe_ids": PROPOSAL})] * 5
        agent = MCPPlannerAgent(
            ScriptedDecisionModel(repeated),
            client_factory=InProcessMealToolsClient,
            max_tool_calls=2,
            total_timeout_seconds=5,
        )
        with self.assertRaisesRegex(MCPAgentError, "tool-call budget"):
            asyncio.run(agent.plan(pantry, request))

    def test_model_cannot_weaken_authoritative_vegetarian_request(self):
        pantry, request = case_inputs()
        weakened = request.model_copy(update={"vegetarian_required": False}).model_dump(mode="json")
        pantry_data = pantry.model_dump(mode="json")
        nonvegetarian = [
            "it_chicken_parmesan",
            "it_spaghetti_bolognese",
            "it_shrimp_scampi_linguine",
        ]
        calls = [
            (
                "simulate_plan",
                {
                    "pantry": pantry_data,
                    "request": weakened,
                    "ordered_recipe_ids": nonvegetarian,
                },
            ),
            (
                "validate_final_plan",
                {
                    "pantry": pantry_data,
                    "request": weakened,
                    "ordered_recipe_ids": nonvegetarian,
                },
            ),
        ]
        agent = MCPPlannerAgent(
            ScriptedDecisionModel(calls),
            client_factory=InProcessMealToolsClient,
            max_plan_revisions=0,
            total_timeout_seconds=5,
        )
        with self.assertRaisesRegex(MCPAgentError, "revision budget"):
            asyncio.run(agent.plan(pantry, request))


if __name__ == "__main__":
    unittest.main()
