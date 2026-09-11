"""Fixed N-day planning loop (pipeline.py, Person 3).

One deterministic pass over the requested days. No autonomous branching, no
retries, no constraint relaxation: only explicit result paths (complete or
partial). The Retriever is injected so unit tests can pass a deterministic fake.

Per day:
  retrieve top-k -> resolve to corpus recipes -> score all (for the trace) ->
  keep eligible + in requested cuisine + unused -> pick best by tie-break ->
  flag if outside the calorie band (fallback) -> apply to pantry -> record.

Cuisine handling (see module note below): candidates are scoped to the
requested cuisine(s). A cuisine with no unused eligible recipe left ends the
plan early with a NO_ELIGIBLE_RECIPE warning (this is how vegetarian exhaustion
surfaces). The calorie band is soft: the closest in-cuisine recipe is picked
and flagged rather than skipped.
"""

from typing import Protocol

from config import DEFAULT_TOP_K, calorie_band
from inventory import apply_recipe, build_shopping_list
from repository import get_recipe
from schemas import (
    CandidateScore,
    DayPlan,
    PantryState,
    PlanningRequest,
    PlanResult,
    RecipeCandidate,
    TraceEvent,
)
from scoring import rank, score_recipe


class Retriever(Protocol):
    """Matches the retrieval.py contract (Person 2 owns the real adapters)."""

    def search(
        self, pantry: PantryState, request: PlanningRequest, top_k: int
    ) -> list[RecipeCandidate]:
        ...


def generate_plan(
    pantry: PantryState,
    request: PlanningRequest,
    retriever: Retriever,
    top_k: int = DEFAULT_TOP_K,
) -> PlanResult:
    low, high = calorie_band(request)
    initial = pantry.model_copy(deep=True)
    current = pantry.model_copy(deep=True)

    used: set[str] = set()
    day_plans: list[DayPlan] = []
    warnings: list[str] = []
    trace: list[TraceEvent] = []

    for day in range(1, request.days + 1):
        candidates = retriever.search(current, request, top_k)
        trace.append(
            TraceEvent(
                step="retrieve",
                day=day,
                message=f"retrieved {len(candidates)} candidate(s)",
                data={"ids": [c.recipe_id for c in candidates]},
            )
        )

        # Resolve ids against the corpus; unknown ids are reported, not invented.
        recipes = []
        for cand in candidates:
            recipe = get_recipe(cand.recipe_id)
            if recipe is None:
                warnings.append("UNKNOWN_RECIPE_ID")
                trace.append(
                    TraceEvent(
                        step="retrieve",
                        day=day,
                        message=f"unknown recipe_id ignored: {cand.recipe_id}",
                    )
                )
                continue
            recipes.append(recipe)

        scores = [score_recipe(r, current, request, used) for r in recipes]
        for s in scores:
            trace.append(
                TraceEvent(step="score", day=day, message=f"scored {s.recipe_id}", data=s.model_dump())
            )

        # Selectable = passes the hard gate, matches a requested cuisine, unused.
        selectable = [
            s for s in scores if s.eligible and s.cuisine_score > 0 and s.recipe_id not in used
        ]
        if not selectable:
            warnings.append("NO_ELIGIBLE_RECIPE")
            trace.append(
                TraceEvent(
                    step="select",
                    day=day,
                    message="no eligible unused recipe for the requested cuisine; "
                    "returning a partial plan (hard constraint not relaxed)",
                )
            )
            break

        chosen: CandidateScore = rank(selectable)[0]
        recipe = get_recipe(chosen.recipe_id)
        out_of_band = not (low <= recipe.calories_per_serving <= high)
        flags = ["calorie_out_of_band"] if out_of_band else []
        trace.append(
            TraceEvent(
                step="select",
                day=day,
                message=f"selected {chosen.recipe_id}"
                + (" (out of calorie band; flagged)" if out_of_band else ""),
                data={"total_score": chosen.total_score, "calorie_delta": chosen.calorie_delta},
            )
        )

        day_plans.append(
            DayPlan(
                day=day,
                recipe=recipe,
                cuisine_match=chosen.cuisine_score > 0,
                calorie_delta=chosen.calorie_delta,
                pantry_coverage=chosen.pantry_coverage,
                vegetarian_required=request.vegetarian_required,
                fallback=out_of_band,
                score=chosen,
                flags=flags,
            )
        )

        current, shortages = apply_recipe(current, recipe)
        used.add(recipe.recipe_id)
        trace.append(
            TraceEvent(
                step="deplete",
                day=day,
                message=f"applied {recipe.recipe_id}; {len(shortages)} shortage(s)",
            )
        )

    if len(day_plans) < request.days and "NO_ELIGIBLE_RECIPE" not in warnings:
        warnings.append("NO_ELIGIBLE_RECIPE")

    shopping_list = build_shopping_list(day_plans, initial)

    return PlanResult(
        requested_days=request.days,
        day_plans=day_plans,
        final_pantry=current.items,
        shopping_list=shopping_list,
        warnings=warnings,
        trace=trace,
    )
