"""Recipe corpus validation and embedding index builder.

Validates the recipe corpus at startup, ensuring:
  - All required fields are present and valid
  - Cuisine tags match the fixed set (italian, american, chinese, indian)
  - Ingredient IDs are consistently formatted (lowercase snake_case)
  - Quantities are positive numbers

Builds embeddings once and caches them locally so retrieval doesn't rebuild
on every run. For the prototype, uses TfidfVectorizer on recipe titles +
ingredients as a lightweight baseline; production can swap in sentence-transformers
or a custom embedding model.
"""

import json
import os
from pathlib import Path
from typing import Optional

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

from recipes import RECIPES
from schemas import Recipe

# Configuration
CACHE_DIR = Path(".embeddings_cache")
EMBEDDINGS_FILE = CACHE_DIR / "recipe_embeddings.json"
VECTORIZER_FILE = CACHE_DIR / "vectorizer.json"

VALID_CUISINES = {"italian", "american", "chinese", "indian"}


def validate_corpus() -> list[str]:
    """Validate all recipes in the corpus. Return a list of validation errors.

    Checks:
    - All required fields present (recipe_id, title, cuisine_tags, ingredients, etc.)
    - Cuisine tags are in the valid set
    - Ingredient IDs are lowercase snake_case
    - Ingredient quantities are positive
    - No duplicate recipe IDs
    """
    errors = []
    seen_ids = set()

    for i, recipe in enumerate(RECIPES):
        # Check required fields
        if not recipe.recipe_id:
            errors.append(f"Recipe {i}: missing recipe_id")
        if not recipe.title:
            errors.append(f"Recipe {i}: missing title")
        if not recipe.cuisine_tags:
            errors.append(f"Recipe {i}: missing cuisine_tags")
        if not recipe.ingredients:
            errors.append(f"Recipe {i}: missing ingredients")

        # Check cuisine tags
        for cuisine in recipe.cuisine_tags:
            if cuisine not in VALID_CUISINES:
                errors.append(
                    f"Recipe {recipe.recipe_id}: invalid cuisine '{cuisine}' "
                    f"(valid: {VALID_CUISINES})"
                )

        # Check for duplicates
        if recipe.recipe_id in seen_ids:
            errors.append(f"Recipe {recipe.recipe_id}: duplicate recipe_id")
        seen_ids.add(recipe.recipe_id)

        # Check ingredients
        for ing in recipe.ingredients:
            # Ingredient ID should be lowercase snake_case
            if ing.ingredient_id != ing.ingredient_id.lower():
                errors.append(
                    f"Recipe {recipe.recipe_id}: ingredient_id '{ing.ingredient_id}' "
                    "should be lowercase"
                )
            if not ing.ingredient_id or "_" not in ing.ingredient_id and len(ing.ingredient_id) > 1:
                # Allow single-word ingredients (e.g., "egg") or snake_case
                if " " in ing.ingredient_id or any(c.isupper() for c in ing.ingredient_id):
                    errors.append(
                        f"Recipe {recipe.recipe_id}: ingredient_id '{ing.ingredient_id}' "
                        "should be lowercase snake_case"
                    )
            if ing.quantity_g <= 0:
                errors.append(
                    f"Recipe {recipe.recipe_id}: ingredient '{ing.ingredient_id}' "
                    f"has invalid quantity {ing.quantity_g}"
                )

    return errors


def build_embeddings() -> tuple[np.ndarray, dict[str, int]]:
    """Build TF-IDF embeddings for all recipes.

    Returns:
        embeddings: (n_recipes, n_features) array of embedding vectors
        recipe_index: dict mapping recipe_id to row index in embeddings array
    """
    recipe_index = {}
    texts = []

    for idx, recipe in enumerate(RECIPES):
        recipe_index[recipe.recipe_id] = idx

        # Build a search text from recipe title, ingredients, and cuisine
        ingredients_text = " ".join(ing.ingredient_id for ing in recipe.ingredients)
        search_text = f"{recipe.title} {ingredients_text} {' '.join(recipe.cuisine_tags)}"
        texts.append(search_text)

    # Build TF-IDF vectorizer
    vectorizer = TfidfVectorizer(
        lowercase=True,
        stop_words="english",
        max_features=200,  # Limit to 200 features for efficiency
        ngram_range=(1, 2),  # Unigrams and bigrams
    )
    embeddings = vectorizer.fit_transform(texts).toarray()

    return embeddings, recipe_index, vectorizer


def save_embeddings(embeddings: np.ndarray, recipe_index: dict[str, int], vectorizer) -> None:
    """Cache embeddings and vectorizer to disk."""
    CACHE_DIR.mkdir(exist_ok=True)

    # Save embeddings as JSON
    with open(EMBEDDINGS_FILE, "w") as f:
        json.dump({
            "embeddings": embeddings.tolist(),
            "recipe_index": recipe_index,
        }, f)

    # Save vectorizer vocabulary (convert numpy types to native Python types)
    with open(VECTORIZER_FILE, "w") as f:
        json.dump({
            "vocabulary": {k: int(v) for k, v in vectorizer.vocabulary_.items()},
            "idf": vectorizer.idf_.tolist(),
        }, f)

    print(f"Cached embeddings to {EMBEDDINGS_FILE}")


def load_embeddings() -> Optional[tuple[np.ndarray, dict[str, int], dict]]:
    """Load cached embeddings and vectorizer from disk."""
    if not EMBEDDINGS_FILE.exists() or not VECTORIZER_FILE.exists():
        return None

    try:
        with open(EMBEDDINGS_FILE, "r") as f:
            data = json.load(f)
            embeddings = np.array(data["embeddings"])
            recipe_index = data["recipe_index"]

        with open(VECTORIZER_FILE, "r") as f:
            vectorizer_data = json.load(f)

        return embeddings, recipe_index, vectorizer_data
    except Exception as e:
        print(f"Failed to load cached embeddings: {e}")
        return None


def index_recipes(force_rebuild: bool = False) -> tuple[np.ndarray, dict[str, int], TfidfVectorizer]:
    """Load or build the recipe embedding index.

    Args:
        force_rebuild: If True, rebuild embeddings even if cache exists.

    Returns:
        embeddings: (n_recipes, n_features) array
        recipe_index: dict mapping recipe_id to embedding row
        vectorizer: fitted TfidfVectorizer for new queries

    Raises:
        ValueError: If corpus validation fails.
    """
    # Validate corpus first
    errors = validate_corpus()
    if errors:
        error_msg = "Corpus validation failed:\n" + "\n".join(errors)
        raise ValueError(error_msg)

    # Try to load cached embeddings
    if not force_rebuild:
        cached = load_embeddings()
        if cached:
            embeddings, recipe_index, vectorizer_data = cached
            # Reconstruct vectorizer (we only need it for new queries)
            vectorizer = TfidfVectorizer(vocabulary=vectorizer_data["vocabulary"])
            vectorizer.idf_ = np.array(vectorizer_data["idf"])
            return embeddings, recipe_index, vectorizer

    # Build from scratch
    print("Building recipe embeddings...")
    embeddings, recipe_index, vectorizer = build_embeddings()
    save_embeddings(embeddings, recipe_index, vectorizer)

    return embeddings, recipe_index, vectorizer


if __name__ == "__main__":
    # Validation and build for CLI
    try:
        embeddings, recipe_index, vectorizer = index_recipes(force_rebuild=True)
        print(f"✓ Corpus valid: {len(RECIPES)} recipes")
        print(f"✓ Embeddings built: shape {embeddings.shape}")
        print(f"✓ Cache ready at {EMBEDDINGS_FILE}")
    except ValueError as e:
        print(f"✗ {e}")
        exit(1)
