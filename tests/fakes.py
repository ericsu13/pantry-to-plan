"""Deterministic test doubles for the planner.

FakeRetriever mirrors the real retriever's cuisine prefilter without embeddings
or a vector store, so the planner can be built and tested before retrieval.py
lands. It intentionally does NOT truncate to top_k or apply the vegetarian
filter: returning the full cuisine-scoped set keeps evals deterministic, and the
planner is the authoritative place the vegetarian gate is enforced.
"""

from advisor import CROSS_CUISINE, GIVE_UP, RelaxationChoice, WeekProposal
from repository import load_recipes
from schemas import PantryState, PlanningRequest, RecipeCandidate


class FakeRetriever:
    def __init__(self, recipes=None):
        self._recipes = recipes if recipes is not None else load_recipes()

    def search(
        self, pantry: PantryState, request: PlanningRequest, top_k: int
    ) -> list[RecipeCandidate]:
        matched = [
            r
            for r in self._recipes
            if any(c in r.cuisine_tags for c in request.cuisines)
        ]
        matched.sort(key=lambda r: r.recipe_id)
        return [RecipeCandidate(recipe_id=r.recipe_id, retrieval_score=1.0) for r in matched]


class FakePlannerAdvisor:
    """Deterministic PlannerAdvisor for the agentic path (no LLM / API key).

    plan_week returns eligible candidates in rank order (best first), unique and
    truncated to `days`; a caller can force a specific week with `week_override`.
    choose_relaxation walks a fixed escalation sequence, defaulting to crossing
    cuisines then giving up, so repair fills a day without repeating recipes.
    """

    def __init__(self, week_override=None, relaxation_sequence=None):
        self._week_override = list(week_override) if week_override is not None else None
        self._sequence = list(relaxation_sequence) if relaxation_sequence is not None else [
            CROSS_CUISINE,
            GIVE_UP,
        ]

    def plan_week(self, ctx) -> WeekProposal:
        if self._week_override is not None:
            return WeekProposal(ordered_recipe_ids=list(self._week_override), rationale="fake: override")
        eligible = [c for c in ctx.candidates if c.eligible]
        eligible.sort(key=lambda c: (-c.total_score, c.recipe_id))
        ordered, seen = [], set()
        for c in eligible:
            if c.recipe_id in seen:
                continue
            seen.add(c.recipe_id)
            ordered.append(c.recipe_id)
            if len(ordered) >= ctx.days:
                break
        return WeekProposal(ordered_recipe_ids=ordered, rationale="fake: rank order")

    def choose_relaxation(self, ctx) -> RelaxationChoice:
        for choice in self._sequence:
            if choice not in ctx.tried_relaxations:
                return RelaxationChoice(choice=choice, rationale="fake")
        return RelaxationChoice(choice=GIVE_UP, rationale="fake: exhausted")
