# PR Readout: Independent Pantry Vision Pipeline

## Summary

This change adds an independently runnable pantry-image workflow that converts
an uploaded image into a user-confirmed `PantryState`. It intentionally stops
before recipe retrieval and planning, allowing those components to be developed
and integrated separately.

## What the workflow does

1. Validates JPEG, PNG, or WebP uploads up to 10 MB.
2. Runs either the live OpenAI vision provider or a deterministic mock provider.
3. Parses provider output through strict Pydantic models.
4. Normalizes detected labels to canonical ingredient IDs.
5. Distinguishes recognized ingredients from ingredients supported by the
   current recipe corpus.
6. Presents detections for human review, correction, exclusion, or manual entry.
7. Produces a downloadable `confirmed_pantry.json` matching `PantryState`.

## Design decisions

- Vision proposes ingredients; the user confirms what becomes planner input.
- The model never creates canonical join keys directly.
- Unknown ingredients are preserved rather than silently discarded.
- Quantities remain unknown unless an exact gram value is readable.
- Recognition and recipe support are separate. For example, `dragon_fruit` is
  recognized but is not recipe-supported until a recipe uses it.
- The UI does not import or invoke retrieval, scoring, inventory, or planning.

## Data and contracts

- The recipe corpus currently contributes 96 supported ingredient IDs.
- The effective recognition catalog contains 205 ingredient IDs.
- Semantic aliases are maintained in JSON, for example
  `capsicum -> bell_pepper` and `pitaya -> dragon_fruit`.
- The handoff contract is `PantryState` in `schemas.py`.

## Validation

```bash
python -m unittest discover -s tests -v
```

Result at submission: **38 tests passing**, including all pre-existing planner
tests plus schema, normalization, vision, and confirmation-boundary tests.

Manual UI check:

```bash
pip install -r requirements.txt
streamlit run vision_app.py
```

Test both `Mock demo` and `Live OpenAI`, edit at least one detection, add one
ingredient manually, confirm the pantry, and download `confirmed_pantry.json`.

## Files in this change

### Modified existing files

- `README.md`
- `requirements.txt`
- `schemas.py`

### New implementation and data files

- `normalization.py`
- `vision.py`
- `vision_app.py`
- `vision_ui_helpers.py`
- `data/ingredient_catalog.json`
- `data/ingredient_aliases.json`
- `examples/run_vision_mock.py`
- `examples/run_vision_live.py`

### New tests and documentation

- `tests/test_schemas.py`
- `tests/test_normalization.py`
- `tests/test_vision.py`
- `tests/test_vision_ui_helpers.py`
- `docs/vision-pr-readout.md`

## Out of scope

- Recipe retrieval and ranking
- Meal-plan generation
- Pantry depletion and shopping-list generation
- Unit conversion to grams
- Automatic recipe expansion for recognized-but-unsupported ingredients
- Live external ingredient-catalog lookup

## Integration handoff

The planner can consume the downloaded JSON as follows:

```python
from pathlib import Path
from schemas import PantryState

pantry = PantryState.model_validate_json(
    Path("confirmed_pantry.json").read_text()
)
```

No vision-provider or Streamlit dependency is required on the planning side
once `PantryState` has been produced.

## Reviewer checklist

- [ ] Mock and live providers return the same structured contract.
- [ ] Invalid images fail before a provider call.
- [ ] Canonical IDs remain lowercase snake_case.
- [ ] Unknown quantities are not invented.
- [ ] Unmapped and recipe-unsupported ingredients remain visible to the user.
- [ ] Confirmed output validates as `PantryState`.
- [ ] Existing planner tests remain green.
