# Pantry eval fixtures

23 self-contained eval scenarios for Pantry to Plan. Each JSON file is what the
pipeline sees *after* the vision step: a parsed pantry plus the plan request and
the expected outcome. Regenerate with `python3 generate_fixtures.py` from the
repo root (fixtures are built from the real ingredient ids in `recipes.py`, so
`pantry_coverage`, fallback, and exhaustion behaviour are genuine).

## File schema

```json
{
  "id": "01_well_stocked_veg_italian",
  "description": "human-readable scenario summary",
  "tags": ["well-stocked", "vegetarian", "happy-path"],
  "pantry": {
    "as_of": "2026-09-11",
    "items": { "ingredient_id": grams, ... }   // maps to PantryItem[] in schemas.py
  },
  "request": {
    "cuisines": ["italian"],        // one or more of italian|american|chinese|indian
    "calorie_target": 600,          // kcal for the single dinner recipe of the day
    "calorie_tolerance": 150,       // +/- band; outside the band -> pick-best-and-flag
    "days": 3,
    "vegetarian_required": false    // hard gate; never relaxed to a warning
  },
  "expect": { "...": "assertions + notes for the eval harness" }
}
```

`pantry.items` uses the same lowercase snake_case join key as recipes. Ingredient
ids that don't match the corpus (the vision-noise fixtures) are expected to be
**ignored** — they must not count toward coverage or crash the planner.

## Key eval cases (as specified)

| Fixture | Purpose | Expected |
|---|---|---|
| `01_well_stocked_veg_italian` | Well-stocked vegetarian happy path | All 3 days veg + Italian + in band; no fallback flags |
| `02_sparse_chinese_fallback` | Sparse pantry, fallback path | Low coverage; >=1 day falls back to closest calorie (only 4 of 5 fit the band) |
| `03_tight_band_indian` | Narrow band, no reject-and-retry | 0 recipes in 300-400 band; all 4 days flagged out-of-band |
| `04_veg_exhaustion_american` | Vegetarian exhaustion | 6 eligible veg recipes, 7 requested -> return 6, report constraint blocked completion, never pick non-veg |

## Full matrix (23 fixtures)

- **Happy path / well-stocked** (01, 06, 07, 08, 09, 10, 15, 18, 20): high or
  full coverage across each cuisine, veg and omnivore, single- and multi-cuisine.
- **Fallback & tight band** (02, 03, 11, 16, 19): scenarios where recipes fall
  outside the calorie band and the scorer must pick-best-and-flag; 11 also
  exercises an exact `delta = 0` match.
- **Sparse / empty** (02, 05, 17): near-zero coverage; 05 is a fully empty pantry.
- **Vegetarian hard gate** (01, 04, 07, 09, 10, 16, 19): `vegetarian_required`
  true; 04 forces exhaustion.
- **Join / mismatch** (13): full pantry of the *wrong* cuisine's ingredients.
- **Min/edge sizing** (14 single day).
- **Vision noise / unclear labels** (21, 22, 23): pantries with generic,
  low-confidence, or near-miss labels that must not join. 22 mixes recognized
  staples with junk; 23 uses plausible near-misses (`soy`, `spring_onion`) to
  document why canonicalization matters (out of scope this pass).
