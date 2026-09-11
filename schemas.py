"""Core data model for Pantry to Plan (Pydantic).

Everything is normalized to grams for this pass; unit conversion is out of scope.
Ingredient ids are lowercase snake_case (e.g. "chicken_breast") and are the
join key across pantry, recipes, and the shopping list.

Models are ordered so that every referenced type is defined before it is used.
"""

from typing import Optional

from pydantic import BaseModel


# --------------------------------------------------------------------- leaves
class PantryItem(BaseModel):
    ingredient_id: str
    display_name: str
    quantity_g: Optional[float] = None
    confidence: float
    source_text: Optional[str] = None


class RecipeIngredient(BaseModel):
    ingredient_id: str
    quantity_g: float
    display_name: Optional[str] = None


class ShoppingListItem(BaseModel):
    ingredient_id: str
    quantity_g: float                        # grams still short after depletion
    aisle: Optional[str] = None              # grocery aisle group for the UI
    display_name: Optional[str] = None
    contributing_recipe_ids: list[str] = []  # planned recipes that drove the need


class TraceEvent(BaseModel):
    step: str                    # e.g. "retrieve", "score", "select", "deplete"
    day: Optional[int] = None    # 1..N when the event is day-scoped
    message: str
    data: Optional[dict] = None


class CandidateScore(BaseModel):
    recipe_id: str
    eligible: bool
    reject_reasons: list[str]    # frozen contract keeps this list[str]
    cuisine_score: float
    calorie_delta: int
    pantry_coverage: float
    repeat_penalty: float
    total_score: float


class AppIssue(BaseModel):
    """Structured error/warning shared across modules (see the blueprint's
    error-code table: INVALID_IMAGE, NO_ELIGIBLE_RECIPE, ...). Used for
    eligibility rejections and dependency/pipeline failures. The frozen
    CandidateScore.reject_reasons and PlanResult.warnings stay list[str]."""

    code: str
    message: str
    field: Optional[str] = None
    recoverable: bool
    suggested_action: Optional[str] = None


class RecipeCandidate(BaseModel):
    """Retriever output: a recipe reference plus its retrieval score. Exact
    recipe facts are always resolved from the corpus, never from the
    retriever; an unknown recipe_id is an error, not a generatable recipe."""

    recipe_id: str
    retrieval_score: float


class EligibilityResult(BaseModel):
    """constraints.validate_eligibility output. Eligibility runs before scoring
    and again before a DayPlan is appended; the vegetarian gate is never
    relaxed."""

    recipe_id: str
    eligible: bool
    reject_reasons: list[AppIssue] = []


class Shortage(BaseModel):
    """inventory.apply_recipe output: unmet demand for one ingredient after
    depleting the pantry for a selected recipe."""

    ingredient_id: str
    quantity_g: float
    aisle: Optional[str] = None
    contributing_recipe_ids: list[str] = []


# ------------------------------------------------------------------ composite
class Recipe(BaseModel):
    recipe_id: str
    title: str
    cuisine_tags: list[str]
    calories_per_serving: int
    vegetarian: bool
    ingredients: list[RecipeIngredient]
    cook_time_min: Optional[int] = None


class DayPlan(BaseModel):
    day: int                     # 1..N, not a real date for the demo
    recipe: Recipe
    cuisine_match: bool
    calorie_delta: int           # actual - target
    pantry_coverage: float       # fraction of ingredients already on hand
    vegetarian_required: bool    # request-level hard constraint
    fallback: bool = False       # picked on closest-calorie fallback, flagged
    score: Optional[CandidateScore] = None
    flags: list[str] = []        # constraint misses, e.g. "calorie_out_of_band"


# ----------------------------------------------------------- request/response
class PantryParseResult(BaseModel):
    items: list[PantryItem]
    warnings: list[str] = []
    model_latency_ms: Optional[int] = None


class PantryState(BaseModel):
    """The confirmed pantry the planner operates on.

    Distinct from PantryParseResult: that is raw vision output (with confidence
    and source text) awaiting user confirmation; this is the authoritative
    "what is true now" state the pipeline threads through each day, depleting
    quantities as recipes are applied. Items reuse PantryItem so state flows
    unchanged into PlanResult.final_pantry.
    """

    items: list[PantryItem]
    as_of: Optional[str] = None  # fixed demo date, not a real plan date


class PlanningRequest(BaseModel):
    cuisines: list[str]
    dinner_calorie_target: int
    days: int                    # 3..5
    vegetarian_required: bool
    goal: str                    # general | nutritional | kids


class PlanResult(BaseModel):
    requested_days: int
    day_plans: list[DayPlan]
    final_pantry: list[PantryItem]
    shopping_list: list[ShoppingListItem]
    warnings: list[str]          # frozen contract; use AppIssue codes as strings
    trace: list[TraceEvent]


# ------------------------------------------------------------------ evaluation
# Person 4's eval contract, drafted from the blueprint's run_eval example.
# Fields may firm up when the eval harness lands; checks/metrics stay open dicts
# so new assertions don't force a schema change.
class CaseEvaluation(BaseModel):
    case_id: str
    passed: bool
    checks: dict = {}       # e.g. schema_valid, vegetarian_violation_count
    metrics: dict = {}       # e.g. retrieval_recall_at_5, latency_ms, model_calls


class EvaluationSummary(BaseModel):
    cases: list[CaseEvaluation]
    passed: int
    failed: int
    metrics: dict = {}       # rolled-up latency/cost/recall across cases
