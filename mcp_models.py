"""Typed contracts shared by the Pantry-to-Plan MCP server and agent client."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from schemas import AppIssue, CandidateScore, PlanResult, Recipe, RecipeCandidate


class MCPBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class RecipeSearchResult(MCPBaseModel):
    backend: str
    candidates: list[RecipeCandidate] = Field(default_factory=list)


class RecipeDetailsResult(MCPBaseModel):
    recipes: list[Recipe] = Field(default_factory=list)
    unknown_recipe_ids: list[str] = Field(default_factory=list)


class CandidateEvaluationResult(MCPBaseModel):
    scores: list[CandidateScore] = Field(default_factory=list)
    issues: list[AppIssue] = Field(default_factory=list)


class PlanMetrics(MCPBaseModel):
    days_planned: int = Field(ge=0)
    average_pantry_coverage: float = Field(ge=0, le=1)
    shopping_item_count: int = Field(ge=0)
    cuisine_mismatch_count: int = Field(ge=0)
    calorie_out_of_band_count: int = Field(ge=0)


class PlanToolResult(MCPBaseModel):
    approved: bool
    plan: PlanResult
    metrics: PlanMetrics
    issues: list[AppIssue] = Field(default_factory=list)


class MCPToolDefinition(MCPBaseModel):
    name: str
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)


class AgentToolRequest(MCPBaseModel):
    call_id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class AgentModelTurn(MCPBaseModel):
    kind: Literal["tool_calls", "message"]
    tool_calls: list[AgentToolRequest] = Field(default_factory=list)
    message: str = ""
    raw_assistant_message: dict[str, Any] = Field(default_factory=dict)

