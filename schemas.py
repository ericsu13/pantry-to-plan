"""Core data model for Pantry to Plan.

Everything is normalized to grams for this pass; unit conversion is out of scope.
Ingredient ids are lowercase snake_case (e.g. "chicken_breast") and are the
join key across pantry, recipes, and the shopping list.
"""

from dataclasses import dataclass
from datetime import date


@dataclass
class PantryItem:
    ingredient_id: str      # lowercase snake_case, e.g. "chicken_breast"
    quantity_g: float       # normalize everything to grams for this pass —
                            # skip unit conversion logic entirely


@dataclass
class PantryState:
    items: list[PantryItem]
    as_of: date


@dataclass
class Recipe:
    recipe_id: str
    title: str
    cuisine: str                    # single tag, e.g. "italian"
    calories: int                   # per serving
    vegetarian: bool                # hard-filter metadata
    ingredients: dict[str, float]   # ingredient_id -> grams needed


@dataclass
class DayPlan:
    day: int                        # 1..N, not a real date for the demo
    recipe: Recipe
    cuisine_match: bool
    calorie_delta: int              # actual - target
    pantry_coverage: float          # % of ingredients already on hand
    vegetarian_required: bool       # request-level hard constraint


@dataclass
class ShoppingListItem:
    ingredient_id: str
    grams_needed: float
