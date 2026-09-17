"""Bounded single-agent planner whose actions are MCP tool calls.

The model controls the soft planning trajectory: which tools to call, what to
inspect, which week to simulate, and when to submit. The controller enforces a
tool budget, a revision budget, simulation-before-validation, and a mandatory
deterministic final validator. On any failure the caller can safely fall back to
the existing Python planner.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Protocol

from mcp_models import AgentModelTurn, AgentToolRequest, MCPToolDefinition, PlanToolResult
from meal_tools_client import MealToolsClient, StdioMealToolsClient
from schemas import PantryState, PlanningRequest, PlanResult, TraceEvent
from telemetry import trace_span


SYSTEM_PROMPT = """You are the single Pantry-to-Plan meal-planning agent.
You must use the provided tools to build a grounded weekly plan.

Required behavior:
1. Search the trusted recipe corpus; never invent recipe ids or facts.
2. Inspect and deterministically evaluate promising candidates.
3. Optimize in this order: hard dietary safety, requested day count, requested
   cuisines, calorie proximity, pantry use, fewer shopping items, variety.
4. Call simulate_plan before validate_final_plan. Revise the ordering when the
   simulation exposes avoidable shopping burden, repetition, or poor coverage.
5. Finish only by calling validate_final_plan with the exact confirmed pantry,
   request, and ordered recipe ids. Vegetarian is never relaxable.
6. Do not calculate quantities or scores yourself; use tool results.
"""


class MCPAgentError(RuntimeError):
    pass


class ToolDecisionModel(Protocol):
    async def next_turn(
        self,
        messages: list[dict[str, Any]],
        tools: list[MCPToolDefinition],
    ) -> AgentModelTurn: ...


class OpenAIToolDecisionModel:
    """OpenAI chat tool-calling adapter with no planning logic of its own."""

    def __init__(self, model: str, temperature: float = 0.0):
        from openai import OpenAI

        self.model = model
        self.temperature = temperature
        self._client = OpenAI()

    async def next_turn(
        self,
        messages: list[dict[str, Any]],
        tools: list[MCPToolDefinition],
    ) -> AgentModelTurn:
        tool_specs = [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.input_schema,
                },
            }
            for tool in tools
        ]

        def invoke():
            return self._client.chat.completions.create(
                model=self.model,
                temperature=self.temperature,
                messages=messages,
                tools=tool_specs,
                tool_choice="auto",
            )

        response = await asyncio.to_thread(invoke)
        message = response.choices[0].message
        assistant_message: dict[str, Any] = {
            "role": "assistant",
            "content": message.content,
        }
        requests: list[AgentToolRequest] = []
        if message.tool_calls:
            assistant_message["tool_calls"] = []
            for call in message.tool_calls:
                try:
                    arguments = json.loads(call.function.arguments or "{}")
                except json.JSONDecodeError as exc:
                    raise MCPAgentError(
                        f"Model returned invalid JSON for tool {call.function.name!r}."
                    ) from exc
                requests.append(
                    AgentToolRequest(
                        call_id=call.id,
                        name=call.function.name,
                        arguments=arguments,
                    )
                )
                assistant_message["tool_calls"].append(
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.function.name,
                            "arguments": call.function.arguments,
                        },
                    }
                )
        return AgentModelTurn(
            kind="tool_calls" if requests else "message",
            tool_calls=requests,
            message=message.content or "",
            raw_assistant_message=assistant_message,
        )


class MCPPlannerAgent:
    def __init__(
        self,
        model: ToolDecisionModel,
        *,
        client_factory=None,
        max_tool_calls: int = 12,
        max_plan_revisions: int = 2,
        total_timeout_seconds: float = 30.0,
    ):
        self.model = model
        self.client_factory = client_factory or StdioMealToolsClient
        self.max_tool_calls = max_tool_calls
        self.max_plan_revisions = max_plan_revisions
        self.total_timeout_seconds = total_timeout_seconds

    async def plan(self, pantry: PantryState, request: PlanningRequest) -> PlanResult:
        try:
            return await asyncio.wait_for(
                self._plan(pantry, request),
                timeout=self.total_timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            raise MCPAgentError("MCP agent exceeded its total execution timeout.") from exc

    async def _plan(self, pantry: PantryState, request: PlanningRequest) -> PlanResult:
        pantry_json = pantry.model_dump(mode="json")
        request_json = request.model_dump(mode="json")
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "goal": "Build and validate the best requested multi-day dinner plan.",
                        "confirmed_pantry": pantry_json,
                        "planning_request": request_json,
                    }
                ),
            },
        ]
        tool_trace: list[TraceEvent] = [
            TraceEvent(
                step="agent_start",
                message="single MCP planning agent started",
                data={"requested_days": request.days},
            )
        ]
        tool_calls = 0
        revisions = 0
        simulated = False
        started = time.perf_counter()

        client_cm = self.client_factory()
        async with client_cm as client:
            client = client  # type: MealToolsClient
            tools = await client.list_tools()
            allowed = {tool.name for tool in tools}
            required = {
                "search_recipes",
                "get_recipe_details",
                "evaluate_candidates",
                "simulate_plan",
                "validate_final_plan",
            }
            missing = sorted(required - allowed)
            if missing:
                raise MCPAgentError(f"MCP server is missing required tools: {missing}")

            while tool_calls < self.max_tool_calls:
                with trace_span(
                    "mcp_agent_decide",
                    run_type="llm",
                    inputs={"message_count": len(messages), "tool_count": len(tools)},
                    metadata={"planner_mode": "mcp_agent"},
                ):
                    turn = await self.model.next_turn(messages, tools)
                messages.append(turn.raw_assistant_message)
                if not turn.tool_calls:
                    raise MCPAgentError(
                        "Agent stopped without an approved validate_final_plan tool result."
                    )

                for call in turn.tool_calls:
                    if tool_calls >= self.max_tool_calls:
                        break
                    tool_calls += 1
                    # Pantry and request are authoritative application state,
                    # never model-controlled tool arguments. Overwrite them on
                    # every applicable call so a mistaken or adversarial model
                    # cannot weaken vegetarian or alter inventory quantities.
                    arguments = dict(call.arguments)
                    if call.name in {
                        "search_recipes",
                        "evaluate_candidates",
                        "simulate_plan",
                        "validate_final_plan",
                    }:
                        arguments["pantry"] = pantry_json
                        arguments["request"] = request_json
                    if call.name not in allowed:
                        result = {"error": "UNKNOWN_TOOL", "tool_name": call.name}
                    elif call.name == "validate_final_plan" and not simulated:
                        result = {
                            "approved": False,
                            "error": "SIMULATION_REQUIRED",
                            "message": "Call simulate_plan before final validation.",
                        }
                    else:
                        with trace_span(
                            f"mcp_{call.name}",
                            run_type="tool",
                            inputs={"tool_name": call.name, "call_number": tool_calls},
                            metadata={"planner_mode": "mcp_agent"},
                        ):
                            result = await client.call_tool(call.name, arguments)

                    tool_trace.append(
                        TraceEvent(
                            step="mcp_tool",
                            message=f"agent called {call.name}",
                            data={
                                "call_number": tool_calls,
                                "approved": result.get("approved"),
                            },
                        )
                    )
                    if call.name == "simulate_plan" and "error" not in result:
                        simulated = True
                    if call.name == "validate_final_plan" and not result.get("approved", False):
                        revisions += 1

                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.call_id,
                            "content": json.dumps(result),
                        }
                    )

                    if call.name == "validate_final_plan" and result.get("approved"):
                        validated = PlanToolResult.model_validate(result)
                        plan = validated.plan
                        plan.trace = tool_trace + plan.trace + [
                            TraceEvent(
                                step="agent_complete",
                                message="deterministic validator approved MCP agent plan",
                                data={
                                    "tool_calls": tool_calls,
                                    "revisions": revisions,
                                    "latency_ms": round(
                                        (time.perf_counter() - started) * 1000, 3
                                    ),
                                },
                            )
                        ]
                        return plan
                    if revisions > self.max_plan_revisions:
                        raise MCPAgentError("MCP agent exceeded its plan revision budget.")

        raise MCPAgentError("MCP agent exceeded its tool-call budget.")


def run_mcp_agent_sync(
    pantry: PantryState,
    request: PlanningRequest,
    agent: MCPPlannerAgent,
) -> PlanResult:
    """Synchronous boundary used by Streamlit and CLI callers."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(agent.plan(pantry, request))
    raise RuntimeError("run_mcp_agent_sync cannot be called from an active event loop")
