# Pantry to Plan

Turn a pantry photo into a 3 to 5 day dinner plan and a consolidated shopping
list. This is a five-hour prototype: one contiguous, demoable pipeline, with
any complexity that does not prove the core loop cut rather than deferred.

Full spec: [Pantry to Plan PRD](https://docs.google.com/document/d/1tc3IKXzLXF_MYZABZueAzt01adY4Mr-4/edit)

## Goal

Prove that vision parsing, recipe retrieval, deterministic scoring, an optional
hard vegetarian filter, pantry depletion, and shopping-list aggregation can work
as one understandable flow within a five-hour build window.

```
pantry photo  ->  preferences + vegetarian gate  ->  meal plan  ->  shopping list
```

![End to end product experience: snap pantry photo, AI finds ingredients, choose preferences, build the meal plan, get shopping list](docs/pantry-to-plan-overview.png)

*Figure 1: End to end product experience.*

## What the demo shows

1. Upload a pantry photo, see a parsed ingredient list.
2. Pick a cuisine preference, a daily calorie target, and optionally require
   vegetarian recipes.
3. Get a 3 to 5 day plan where each day's recipe roughly matches the cuisine,
   roughly hits the calorie target, is vegetarian whenever that hard constraint
   is enabled, and prefers ingredients already on hand.
4. See a shopping list of what is missing across the plan.

## Architecture

![Technical solution architecture: OpenAI vision and embeddings, Pinecone retrieval, Python scoring in a per-day loop, and a thin persistence interface, producing day plans, a shopping list, and constraint flags](docs/pantry-to-plan-architecture.png)

*Figure 2: Technical solution architecture and daily planning loop.*

- **OpenAI (GPT-4o)** handles image understanding, structured/JSON output, and
  query embeddings (`text-embedding-3-small`).
- **Pinecone** stores the recipe corpus and retrieves a small candidate set per
  day, applying the `vegetarian=true` metadata filter when requested. Pinecone's
  job is recall; the local recipe corpus is the source of truth for exact
  ingredients and quantities.
- **Python** enforces the vegetarian gate again, applies exact scoring rules,
  and updates pantry state.
- **Persistence** (pantry state, generated day plans) goes through a thin
  `memory.py` interface so the storage choice stays isolated. Default to a local
  JSON file unless mem0 is explicitly a requirement to demo; either way the rest
  of the code only calls `save_pantry`, `update_pantry`, `append_day_plan`,
  `load_pantry`, `load_day_plans`. The recipe corpus lives in Pinecone, kept
  separate from the "what is true now / what happened" store.

## The daily loop

A simple for-loop over 3 to 5 days. No retries, no relax loop, just best-match.

For each day:
1. Build a query from the current pantry plus cuisine preference, embed it, and
   query Pinecone (top-k). When vegetarian is required, apply the metadata
   filter.
2. Discard any non-vegetarian candidate when the hard constraint is on, then
   score the eligible candidates in Python on: cuisine match (in/out), calorie
   distance from target, percentage of ingredients already in the pantry, and
   not already used this week.
3. Pick the single best-scoring candidate. If nothing eligible matches the
   cuisine, fall back to the closest calorie match and flag it. There is no
   substitution logic, just a flag. Never fall back to a non-vegetarian recipe.
4. Subtract the recipe's ingredients from the in-memory pantry, persist the
   updated state, and append the `DayPlan`.

Then aggregate: the list of `DayPlan`s plus a shopping list (sum of all recipe
ingredients minus the final pantry state), and report which days missed a
constraint and by how much.

## Constraints

- **Cuisine**: one or more tags from a fixed list of four (`italian`,
  `american`, `chinese`, `indian`), matching the corpus tags exactly. A recipe
  either matches or it does not, no fuzzy reasoning.
- **Calories**: one `dinner_calorie_target` plus a tolerance band derived from
  the request `goal` (`general` +/- 150, `nutritional` +/- 75, `kids` +/- 200
  kcal). One recipe equals one day's dinner; the target is for that single meal,
  not a full day's macros.
- **Vegetarian (optional hard gate)**: a `vegetarian_required` boolean. When on,
  only recipes tagged vegetarian are eligible, enforced as a Pinecone metadata
  filter and again in Python before scoring. It is never relaxed or downgraded
  to a warning. If no eligible recipe remains, return fewer days and clearly
  report that the hard constraint prevented completion.

Cut for time (easy to bolt on later as more filter predicates): protein/carb/fat
targets, allergies, per-meal dietary constraints, per-day target variation.

## Data model

See [schemas.py](schemas.py) (Pydantic models, frozen shared contracts per the
implementation blueprint): `PantryItem`, `PantryParseResult`, `PantryState`,
`PlanningRequest`, `Recipe`, `RecipeIngredient`, `RecipeCandidate`,
`CandidateScore`, `EligibilityResult`, `DayPlan`, `Shortage`,
`ShoppingListItem`, `AppIssue`, `PlanResult`, and the eval types
(`CaseEvaluation`, `EvaluationSummary`). Everything is normalized to grams; unit
conversion is out of scope. Ingredient ids are lowercase snake_case (e.g.
`chicken_breast`) and are the join key across pantry, recipes, and shopping
list.

## Repository layout

Current state:

| File | Purpose | Status |
|---|---|---|
| [schemas.py](schemas.py) | Core Pydantic models | done |
| [recipes.py](recipes.py) | 40-recipe corpus, 10 per cuisine, >=4 vegetarian each | done |
| [generate_fixtures.py](generate_fixtures.py) | Builds eval fixtures from the corpus | done |
| [fixtures/](fixtures/) | 23 eval scenarios (see [fixtures/README.md](fixtures/README.md)) | done |
| `vision_parse.py` | OpenAI vision call -> `PantryItem[]` | todo |
| `retrieval.py` | Pinecone index build + per-day query | todo |
| `memory.py` | Thin persistence wrapper | todo |
| `planner.py` | Scoring + day loop + aggregation + shopping-list diff | todo |
| `main.py` | CLI entrypoint | todo |
| `eval/run_eval.py` | Fixture scenarios + assertions | todo |

The PRD calls for `recipes.json`; this repo uses [recipes.py](recipes.py)
instead (typed `Recipe` objects, directly importable, no parse step). The
retrieval index-build reads from it and writes the Pinecone metadata
(`cuisine_tags`, `calories_per_serving`, `vegetarian`).

## Eval

Automated checks that the loop does what it claims, run against fixed fixtures
directly against `planner.py` (no subprocess, no live vision call), so they are
cheap to run repeatedly. The [fixtures/](fixtures/) folder holds 23 scenarios
covering the four required cases (well-stocked vegetarian, sparse pantry with
fallback, tight calorie band, vegetarian exhaustion) plus happy paths, join
mismatches, sizing edges, and vision-noise cases with unclear or poorly-labeled
pantry items.

Planned assertions (mechanical, not subjective):
- Every planned day produces exactly one `DayPlan`; a short plan is allowed only
  when a hard constraint leaves no unused recipe, and the reason is reported.
- With `vegetarian_required=True`, every selected recipe is vegetarian.
- `cuisine_match` agrees with any requested cuisine being in `recipe.cuisine_tags`.
- `calorie_delta` equals `recipe.calories_per_serving - dinner_calorie_target`
  exactly.
- Pantry never goes negative across day mutations.
- The final shopping list lists only ingredients still short, with
  `quantity_g > 0`.

## Build order

1. **Corpus + schemas** (done): unblocks everything, no dependencies.
2. **Vision parse**: one OpenAI call, image in, structured JSON out. Highest
   risk, do it early against 1 to 2 real photos.
3. **Retrieval**: build the Pinecone index, upsert the corpus, write the per-day
   query with the vegetarian metadata filter. Test standalone first.
4. **Planner**: day loop against a fake pantry first, then wire in real vision
   output and persistence. Confirm pantry depletion actually changes choices
   across days.
5. **Shopping-list diff, eval, CLI**: get the eval script working before
   polishing the CLI; the eval is what proves the demo works.
