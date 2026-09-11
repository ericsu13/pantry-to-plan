"""Deterministic scoring and stable ordering (scoring.py, Person 3).

Pure functions only; the language model never contributes to scoring or
arithmetic. Every component value is retained on CandidateScore so explanations
and evals can cite exact evidence.

Score components (weights in config.SCORE_WEIGHTS):
- cuisine_score:    1.0 if any requested cuisine is in the recipe's tags, else 0
- pantry_coverage:  fraction of the recipe's ingredients already on hand (>0 g)
- calorie:          normalized closeness of calories to the target (1.0 at exact)
- repeat_penalty:   1.0 if the recipe was already used this week, else 0

Stable tie-break (blueprint): highest total_score, then higher pantry_coverage,
then smaller absolute calorie delta, then recipe_id ascending.
"""

from config import SCORE_WEIGHTS
from constraints import validate_eligibility
from schemas import CandidateScore, PantryState, PlanningRequest, Recipe


def pantry_quantities(pantry: PantryState) -> dict[str, float]:
    """Map ingredient_id -> grams on hand. Unknown/None quantity counts as 0."""
    return {item.ingredient_id: (item.quantity_g or 0.0) for item in pantry.items}


def cuisine_matches(recipe: Recipe, request: PlanningRequest) -> bool:
    return any(c in recipe.cuisine_tags for c in request.cuisines)


def _calorie_score(calorie_delta: int, target: int) -> float:
    # Normalized distance: 1.0 at the target, decaying to 0 a full target away.
    return max(0.0, 1.0 - abs(calorie_delta) / max(target, 1))


def score_recipe(
    recipe: Recipe,
    pantry: PantryState,
    request: PlanningRequest,
    used_ids: frozenset[str] | set[str] = frozenset(),
    weights: dict[str, float] | None = None,
) -> CandidateScore:
    weights = weights or SCORE_WEIGHTS
    eligibility = validate_eligibility(recipe, request)
    qty = pantry_quantities(pantry)

    cuisine_score = 1.0 if cuisine_matches(recipe, request) else 0.0
    calorie_delta = recipe.calories_per_serving - request.dinner_calorie_target
    on_hand = sum(1 for ing in recipe.ingredients if qty.get(ing.ingredient_id, 0.0) > 0)
    pantry_coverage = on_hand / len(recipe.ingredients) if recipe.ingredients else 0.0
    repeat_penalty = 1.0 if recipe.recipe_id in used_ids else 0.0

    total_score = (
        weights["cuisine"] * cuisine_score
        + weights["pantry_coverage"] * pantry_coverage
        + weights["calorie"] * _calorie_score(calorie_delta, request.dinner_calorie_target)
        - weights["repeat_penalty"] * repeat_penalty
    )

    return CandidateScore(
        recipe_id=recipe.recipe_id,
        eligible=eligibility.eligible,
        reject_reasons=[r.code for r in eligibility.reject_reasons],
        cuisine_score=cuisine_score,
        calorie_delta=calorie_delta,
        pantry_coverage=round(pantry_coverage, 4),
        repeat_penalty=repeat_penalty,
        total_score=round(total_score, 6),
    )


def tie_break_key(score: CandidateScore) -> tuple:
    return (-score.total_score, -score.pantry_coverage, abs(score.calorie_delta), score.recipe_id)


def rank(scores: list[CandidateScore]) -> list[CandidateScore]:
    """Stable, deterministic ordering; best candidate first."""
    return sorted(scores, key=tie_break_key)
