"""Local MCP server exposing grounded Pantry-to-Plan capabilities.

Run directly for a stdio server::

    uv run python meal_tools_server.py

The functions below are deliberately thin adapters. Recipe facts, constraint
checks, scoring, inventory arithmetic, and final plan validation remain in the
existing deterministic modules.
"""

from __future__ import annotations

from contextlib import redirect_stdout
from functools import lru_cache
import sys
from typing import Any

from mcp.server.fastmcp import FastMCP

from mcp_models import (
    CandidateEvaluationResult,
    PlanMetrics,
    PlanToolResult,
    RecipeDetailsResult,
    RecipeSearchResult,
)
from pipeline import materialize_agent_proposal
from repository import get_recipe
from schemas import AppIssue, PantryState, PlanningRequest
from scoring import score_recipe


mcp = FastMCP(
    "pantry-to-plan-meal-tools",
    instructions=(
        "Ground meal plans in the trusted recipe corpus. Use search and details "
        "before proposing recipe ids, simulate a proposed week, and always call "
        "validate_final_plan before finishing. Never relax vegetarian_required."
    ),
)


@lru_cache(maxsize=3)
def _retriever(backend: str):
    from retrieval import create_retriever

    # stdout is the MCP stdio transport. Existing index/retrieval status messages
    # must go to stderr so they cannot corrupt protocol frames.
    with redirect_stdout(sys.stderr):
        return create_retriever(backend)


def _backend_name(retriever: object, requested: str) -> str:
    active = getattr(retriever, "backend", None)
    return str(active or requested)


def search_recipes_impl(
    pantry: dict[str, Any],
    request: dict[str, Any],
    top_k: int = 12,
    backend: str = "auto",
) -> dict[str, Any]:
    pantry_model = PantryState.model_validate(pantry)
    request_model = PlanningRequest.model_validate(request)
    if not 1 <= top_k <= 40:
        raise ValueError("top_k must be between 1 and 40")
    if backend not in {"auto", "local", "pinecone"}:
        raise ValueError("backend must be auto, local, or pinecone")
    retriever = _retriever(backend)
    with redirect_stdout(sys.stderr):
        candidates = retriever.search(pantry_model, request_model, top_k)
    return RecipeSearchResult(
        backend=_backend_name(retriever, backend),
        candidates=candidates,
    ).model_dump(mode="json")


@mcp.tool()
def search_recipes(
    pantry: dict[str, Any],
    request: dict[str, Any],
    top_k: int = 12,
    backend: str = "auto",
) -> dict[str, Any]:
    """Retrieve grounded recipe candidates for a confirmed pantry and request."""
    return search_recipes_impl(pantry, request, top_k, backend)


def get_recipe_details_impl(recipe_ids: list[str]) -> dict[str, Any]:
    recipes = []
    unknown = []
    for recipe_id in recipe_ids:
        recipe = get_recipe(recipe_id)
        if recipe is None:
            unknown.append(recipe_id)
        elif recipe.recipe_id not in {item.recipe_id for item in recipes}:
            recipes.append(recipe)
    return RecipeDetailsResult(
        recipes=recipes,
        unknown_recipe_ids=unknown,
    ).model_dump(mode="json")


@mcp.tool()
def get_recipe_details(recipe_ids: list[str]) -> dict[str, Any]:
    """Return exact recipe facts from the trusted corpus for known recipe ids."""
    return get_recipe_details_impl(recipe_ids)


def evaluate_candidates_impl(
    recipe_ids: list[str],
    pantry: dict[str, Any],
    request: dict[str, Any],
    used_recipe_ids: list[str] | None = None,
) -> dict[str, Any]:
    pantry_model = PantryState.model_validate(pantry)
    request_model = PlanningRequest.model_validate(request)
    used = set(used_recipe_ids or [])
    scores = []
    issues = []
    for recipe_id in recipe_ids:
        recipe = get_recipe(recipe_id)
        if recipe is None:
            issues.append(
                AppIssue(
                    code="UNKNOWN_RECIPE_ID",
                    message=f"Recipe id {recipe_id!r} is not in the trusted corpus.",
                    field="recipe_ids",
                    recoverable=True,
                    suggested_action="Use a recipe id returned by search_recipes.",
                )
            )
            continue
        scores.append(score_recipe(recipe, pantry_model, request_model, used))
    return CandidateEvaluationResult(scores=scores, issues=issues).model_dump(mode="json")


@mcp.tool()
def evaluate_candidates(
    recipe_ids: list[str],
    pantry: dict[str, Any],
    request: dict[str, Any],
    used_recipe_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Apply deterministic eligibility and scoring to grounded candidates."""
    return evaluate_candidates_impl(recipe_ids, pantry, request, used_recipe_ids)


def _plan_tool_result(
    pantry: dict[str, Any],
    request: dict[str, Any],
    ordered_recipe_ids: list[str],
    *,
    require_complete: bool,
) -> dict[str, Any]:
    pantry_model = PantryState.model_validate(pantry)
    request_model = PlanningRequest.model_validate(request)
    plan, issues = materialize_agent_proposal(
        pantry_model,
        request_model,
        ordered_recipe_ids,
        require_complete=require_complete,
    )
    days = plan.day_plans
    metrics = PlanMetrics(
        days_planned=len(days),
        average_pantry_coverage=round(
            sum(day.pantry_coverage for day in days) / len(days), 4
        ) if days else 0.0,
        shopping_item_count=len(plan.shopping_list),
        cuisine_mismatch_count=sum(not day.cuisine_match for day in days),
        calorie_out_of_band_count=sum(
            "calorie_out_of_band" in day.flags for day in days
        ),
    )
    return PlanToolResult(
        approved=not issues,
        plan=plan,
        metrics=metrics,
        issues=issues,
    ).model_dump(mode="json")


def simulate_plan_impl(
    pantry: dict[str, Any],
    request: dict[str, Any],
    ordered_recipe_ids: list[str],
) -> dict[str, Any]:
    return _plan_tool_result(
        pantry,
        request,
        ordered_recipe_ids,
        require_complete=False,
    )


@mcp.tool()
def simulate_plan(
    pantry: dict[str, Any],
    request: dict[str, Any],
    ordered_recipe_ids: list[str],
) -> dict[str, Any]:
    """Simulate an ordered week and report pantry, shopping, and quality metrics."""
    return simulate_plan_impl(pantry, request, ordered_recipe_ids)


def validate_final_plan_impl(
    pantry: dict[str, Any],
    request: dict[str, Any],
    ordered_recipe_ids: list[str],
) -> dict[str, Any]:
    return _plan_tool_result(
        pantry,
        request,
        ordered_recipe_ids,
        require_complete=True,
    )


@mcp.tool()
def validate_final_plan(
    pantry: dict[str, Any],
    request: dict[str, Any],
    ordered_recipe_ids: list[str],
) -> dict[str, Any]:
    """Run the mandatory deterministic gate and return an approved PlanResult."""
    return validate_final_plan_impl(pantry, request, ordered_recipe_ids)


if __name__ == "__main__":
    mcp.run(transport="stdio")
