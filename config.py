"""Shared configuration: score weights, calorie band, and run settings.

Per the implementation blueprint, config.py is the single home for tunable
knobs so the planner's behavior is inspectable and versioned rather than
scattered as magic numbers. Both the planner and the fixture generator import
the goal->band mapping from here, so there is one source of truth.
"""

import os

from schemas import PlanningRequest

# Calorie tolerance band (+/- kcal) derived from the request `goal`. The user
# picks a goal (everyday vs health-focused vs kid-friendly); that choice sets
# how strict the calorie band is. This is the authoritative mapping.
GOAL_CALORIE_TOLERANCE = {
    "general": 150,       # everyday cooking, generous band
    "nutritional": 75,    # health-focused, tighter band
    "kids": 200,          # kid-friendly, widest band
}

# Relative weights for the score components (see scoring.py). Tune freely; they
# only need to order candidates sensibly, not sum to 1. cuisine is weighted
# highest because a requested-cuisine match is the primary preference.
SCORE_WEIGHTS = {
    "cuisine": 0.40,
    "pantry_coverage": 0.30,
    "calorie": 0.20,
    "repeat_penalty": 0.10,
}

DEFAULT_TOP_K = 8         # candidate pool per day (blueprint default)

# Selection temperature for the per-day pick. The planner samples among the
# eligible, in-cuisine, unused candidates with probability proportional to
# exp(total_score / T) instead of always taking the argmax, so the same pantry
# yields varied (but still sensibly ranked) plans on re-runs. Higher T = more
# variety; T <= 0 collapses to the deterministic tie-break (argmax), which is
# what evals pin. Hard constraints (vegetarian gate, cuisine scope, calorie
# band flagging, depletion) are unaffected: only the choice among already-valid
# candidates is randomized.
SELECTION_TEMPERATURE = 0.10


def calorie_band(request: PlanningRequest) -> tuple[int, int]:
    """Inclusive (low, high) kcal band for a request, derived from its goal."""
    tol = GOAL_CALORIE_TOLERANCE.get(request.goal, GOAL_CALORIE_TOLERANCE["general"])
    target = request.dinner_calorie_target
    return target - tol, target + tol


class Settings:
    """Minimal env-backed settings. Secrets stay absent by default so the demo
    runs against mocks/local retrieval without an API key. Kept dependency-free
    (plain os.environ) for a clean fresh-checkout run."""

    def __init__(self):
        self.retriever_backend = os.environ.get("RETRIEVER_BACKEND", "local")
        self.top_k = int(os.environ.get("TOP_K", DEFAULT_TOP_K))
        self.use_llm_explanations = (
            os.environ.get("USE_LLM_EXPLANATIONS", "false").lower() == "true"
        )
        self.score_weights = dict(SCORE_WEIGHTS)
        self.selection_temperature = float(
            os.environ.get("SELECTION_TEMPERATURE", SELECTION_TEMPERATURE)
        )


def load_settings() -> Settings:
    return Settings()
