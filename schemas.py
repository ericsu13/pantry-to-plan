"""Core data model for Pantry to Plan (Pydantic).

Everything is normalized to grams for this pass; unit conversion is out of scope.
Ingredient ids are lowercase snake_case (e.g. "chicken_breast") and are the
join key across pantry, recipes, and the shopping list.

Models are ordered so that every referenced type is defined before it is used.
"""

from pydantic import BaseModel


# --------------------------------------------------------------------- leaves
class PantryItem(BaseModel):
    ingredient_id: str
    display_name: str
    quantity_g: float | None = None
    confidence: float
    source_text: str | None = None


class RecipeIngredient(BaseModel):
    ingredient_id: str
    quantity_g: float
    display_name: str | None = None


class ShoppingListItem(BaseModel):
    ingredient_id: str
    grams_needed: float
    display_name: str | None = None


class TraceEvent(BaseModel):
    step: str                    # e.g. "retrieve", "score", "select", "deplete"
    day: int | None = None       # 1..N when the event is day-scoped
    message: str
    data: dict | None = None


class CandidateScore(BaseModel):
    recipe_id: str
    eligible: bool
    reject_reasons: list[str]
    cuisine_score: float
    calorie_delta: int
    pantry_coverage: float
    repeat_penalty: float
    total_score: float


# ------------------------------------------------------------------ composite
class Recipe(BaseModel):
    recipe_id: str
    title: str
    cuisine_tags: list[str]
    calories_per_serving: int
    vegetarian: bool
    ingredients: list[RecipeIngredient]
    cook_time_min: int | None = None


class DayPlan(BaseModel):
    day: int                     # 1..N, not a real date for the demo
    recipe: Recipe
    cuisine_match: bool
    calorie_delta: int           # actual - target
    pantry_coverage: float       # fraction of ingredients already on hand
    vegetarian_required: bool    # request-level hard constraint
    fallback: bool = False       # picked on closest-calorie fallback, flagged
    score: CandidateScore | None = None
    flags: list[str] = []        # constraint misses, e.g. "calorie_out_of_band"


# ----------------------------------------------------------- request/response
class PantryParseResult(BaseModel):
    items: list[PantryItem]
    warnings: list[str] = []
    model_latency_ms: int | None = None


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
    warnings: list[str]
    trace: list[TraceEvent]
