"""UI-supporting business logic (app_services.py, Person 4).

Everything the Streamlit app needs that is NOT a widget lives here so app.py
stays a thin view layer: preference persistence, pantry sourcing, request
building, retrieval, running the planner, and copy helpers. No Streamlit import
in this module, and every function returns plain data or a typed schema object.

Two upstream modules are not built yet: vision.py (P1 image reader) and
retrieval.py (P2 retriever). This module calls them when present and falls back
to a runnable local path otherwise, so the UI works end to end today and
auto-upgrades when those land.
"""

import json
import os
from pathlib import Path

from config import ALL_CUISINES, GOAL_CALORIE_TOLERANCE
from inventory import build_shopping_list  # noqa: F401  (re-exported for callers/tests)
from pipeline import generate_plan
from repository import load_recipes
from schemas import (
    PantryItem,
    PantryParseResult,
    PantryState,
    PlanningRequest,
    PlanResult,
    RecipeCandidate,
)

ROOT = Path(__file__).resolve().parent
FIXTURES_DIR = ROOT / "fixtures"
DEMO_FIXTURE = FIXTURES_DIR / "01_well_stocked_veg_italian.json"
PREFS_FILE = ROOT / "preferences.json"
PREFS_DEFAULT_FILE = ROOT / "preferences.default.json"

# Option lists sourced from the shared contract so the UI can never drift from
# what the planner actually accepts.
CUISINES = list(ALL_CUISINES)
GOALS = list(GOAL_CALORIE_TOLERANCE)

# Items at or below this confidence (or missing a quantity) are surfaced for
# review on the confirm step. The clean demo pantry trips none of these.
LOW_CONFIDENCE_THRESHOLD = 0.6

# Safety net only; the real defaults live in preferences.default.json.
_FALLBACK_PREFS = {
    "cuisines": ["italian"],
    "dinner_calorie_target": 600,
    "days": 3,
    "vegetarian_required": True,
    "goal": "general",
}


# --------------------------------------------------------------- preferences
def load_preferences() -> dict:
    """Persisted user prefs if present, else the committed defaults file, else a
    hardcoded safety net."""
    for path in (PREFS_FILE, PREFS_DEFAULT_FILE):
        if path.exists():
            with open(path) as fh:
                return json.load(fh)
    return dict(_FALLBACK_PREFS)


def save_preferences(prefs: dict) -> None:
    """Persist changed preferences to preferences.json (runtime, gitignored)."""
    with open(PREFS_FILE, "w") as fh:
        json.dump(prefs, fh, indent=2)


# ------------------------------------------------------------ pantry sourcing
def _items_from_fixture(path: Path) -> list[PantryItem]:
    data = json.loads(path.read_text())
    return [
        PantryItem(
            ingredient_id=ing_id,
            display_name=ing_id.replace("_", " ").title(),
            quantity_g=float(grams),
            confidence=1.0,
        )
        for ing_id, grams in data["pantry"]["items"].items()
    ]


def load_demo_parse_result() -> PantryParseResult:
    """The bundled well-stocked vegetarian Italian pantry, as if freshly parsed.

    Used both when the user skips the photo and (per the locked UI decision) as
    the parse result for an uploaded photo until vision.py exists.
    """
    return PantryParseResult(items=_items_from_fixture(DEMO_FIXTURE), warnings=[])


def parse_pantry_image(file_bytes: bytes) -> PantryParseResult:
    """Read a pantry photo into a PantryParseResult.

    Calls P1's vision.py when it lands; until then falls back to the demo pantry
    so the wizard is runnable end to end. A real vision error is not swallowed.
    """
    try:
        from vision import parse_pantry_photo  # type: ignore
    except ImportError:
        return load_demo_parse_result()
    return parse_pantry_photo(file_bytes)


def flagged_items(parse_result: PantryParseResult) -> list[PantryItem]:
    """Items worth a second look before confirming: low confidence or no
    quantity. Empty for the clean demo pantry."""
    return [
        it
        for it in parse_result.items
        if (it.confidence is not None and it.confidence < LOW_CONFIDENCE_THRESHOLD)
        or it.quantity_g is None
    ]


def build_pantry_state(rows: list[dict]) -> PantryState:
    """Turn edited confirm-step rows back into the typed pantry the planner uses.

    Blank ids are dropped; a blank quantity becomes None (unknown amount);
    confidence defaults to 1.0 for user-entered rows.
    """
    items: list[PantryItem] = []
    for row in rows:
        ing_id = str(row.get("ingredient_id") or "").strip()
        if not ing_id:
            continue
        qty = row.get("quantity_g")
        quantity_g = float(qty) if qty not in (None, "") else None
        display = str(row.get("display_name") or "").strip() or ing_id.replace("_", " ").title()
        conf = row.get("confidence")
        items.append(
            PantryItem(
                ingredient_id=ing_id,
                display_name=display,
                quantity_g=quantity_g,
                confidence=float(conf) if conf not in (None, "") else 1.0,
            )
        )
    return PantryState(items=items)


# ------------------------------------------------------------------- request
def build_request(prefs: dict) -> PlanningRequest:
    """Construct the typed PlanningRequest from a preferences dict."""
    return PlanningRequest(
        cuisines=list(prefs["cuisines"]),
        dinner_calorie_target=int(prefs["dinner_calorie_target"]),
        days=int(prefs["days"]),
        vegetarian_required=bool(prefs["vegetarian_required"]),
        goal=str(prefs["goal"]),
    )


# ----------------------------------------------------------------- retrieval
class _CorpusRetriever:
    """Local stand-in matching pipeline.Retriever until P2's retrieval.py lands.

    Mirrors tests/fakes.FakeRetriever: a cuisine prefilter over the corpus,
    sorted by id, no top_k truncation and no vegetarian filter (the planner is
    the authoritative place the vegetarian gate is enforced).
    """

    def __init__(self):
        self._recipes = load_recipes()

    def search(
        self, pantry: PantryState, request: PlanningRequest, top_k: int
    ) -> list[RecipeCandidate]:
        matched = [
            r for r in self._recipes if any(c in r.cuisine_tags for c in request.cuisines)
        ]
        matched.sort(key=lambda r: r.recipe_id)
        return [RecipeCandidate(recipe_id=r.recipe_id, retrieval_score=1.0) for r in matched]


def get_retriever():
    """P2's real retriever when available, else the local corpus stand-in."""
    try:
        from retrieval import LocalRetriever  # type: ignore
    except ImportError:
        return _CorpusRetriever()
    return LocalRetriever()


# ------------------------------------------------------------------- advisor
def advisor_status() -> tuple[bool, str]:
    """Whether the opt-in agentic planner can run. Returns (available, reason);
    reason is a short note to show when it is disabled."""
    if not os.environ.get("OPENAI_API_KEY"):
        return False, "Set OPENAI_API_KEY to enable smart planning."
    try:
        import langchain_openai  # noqa: F401
    except ImportError:
        return False, "Install langchain-openai to enable smart planning."
    return True, ""


def build_advisor():
    """The live LangChain-backed PlannerAdvisor. Only call when advisor_status()
    reports available."""
    from advisor import LangChainPlannerAdvisor

    return LangChainPlannerAdvisor()


# ---------------------------------------------------------------- run planner
def run_plan(pantry: PantryState, request: PlanningRequest, advisor=None, progress=None) -> PlanResult:
    """Drive the deterministic pipeline, emitting coarse stage strings through an
    optional progress(msg) callback for the UI to display."""

    def emit(msg: str) -> None:
        if progress is not None:
            progress(msg)

    emit("Reading your preferences...")
    retriever = get_retriever()
    emit("Retrieving candidate recipes...")
    emit(f"Scoring recipes and building your {request.days}-day plan...")
    result = generate_plan(pantry, request, retriever, advisor=advisor)
    emit("Aggregating your shopping list...")
    return result


# --------------------------------------------------------------- copy helpers
_WARNING_TEXT = {
    "NO_ELIGIBLE_RECIPE": "We ran out of recipes that fit your preferences, so this plan "
    "is shorter than you asked for. Try more cuisines or a wider calorie goal.",
    "RELAXED_CROSS_CUISINE": "To fill every day we included a dish from another cuisine "
    "(flagged on the day it appears).",
    "RELAXED_REPEAT": "To fill every day a recipe had to repeat.",
    "UNKNOWN_RECIPE_ID": "A retrieved recipe was not found in the corpus and was skipped.",
}

FLAG_LABELS = {
    "cross_cuisine": "Different cuisine",
    "calorie_out_of_band": "Outside calorie band",
}


def describe_warning(code: str) -> str:
    """Friendly text for a PlanResult warning code (falls back to the raw code)."""
    return _WARNING_TEXT.get(code, code)
