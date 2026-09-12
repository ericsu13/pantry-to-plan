"""Recipe retrieval: Retriever protocol with Pinecone + OpenAI and local fallback.

Defines a Retriever as a Protocol so implementations can be swapped
(Pinecone + OpenAI embeddings, local TF-IDF, etc.) without downstream code changing.

PineconeRetriever uses OpenAI's text-embedding-3-small to embed queries and recipes,
then searches Pinecone for semantic matches. LocalRetriever provides offline fallback
using cached TF-IDF embeddings.

The output is a ranked list of RecipeCandidate objects with recipe IDs and
retrieval scores. Exact recipe facts are resolved by downstream code using
repository.get_recipe(), never inferred by the retriever.
"""

import os
from typing import Optional, Protocol

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from index_recipes import index_recipes
from repository import get_recipe, load_recipes
from schemas import PantryState, PlanningRequest, RecipeCandidate


class Retriever(Protocol):
    """Protocol for recipe retrieval backends.

    Retrieve callable objects that take a PlanningRequest, confirmed pantry
    state, and top_k limit, then return a ranked list of recipe candidates.

    The caller is responsible for resolving recipe facts from candidates
    using repository.get_recipe(); retrieval provides IDs and scores only.
    """

    def search(
        self,
        pantry: PantryState,
        request: PlanningRequest,
        top_k: int = 8,
    ) -> list[RecipeCandidate]:
        """Retrieve top-k recipe candidates matching the request and pantry.

        Args:
            request: PlanningRequest with cuisines, calorie_target, days, etc.
            pantry: Current confirmed PantryState with items on hand.
            top_k: Number of candidates to return.

        Returns:
            List of RecipeCandidate objects sorted by retrieval_score (descending).
            If fewer than top_k eligible recipes exist, return what's available.
        """
        ...


class PineconeRetriever:
    """Cloud retriever using Pinecone + OpenAI embeddings.

    Uses OpenAI's text-embedding-3-small to embed queries and recipes.
    Defaults to 512 dimensions (configurable via OPENAI_EMBEDDING_DIMENSIONS).

    Requires valid OPENAI_API_KEY and PINECONE_API_KEY environment variables.

    For production use or larger corpora, this provides better scaling and
    does not require keeping vectors in memory.
    """

    def __init__(self):
        """Initialize Pinecone client and OpenAI embeddings."""
        from openai import OpenAI
        from pinecone import Pinecone

        self.openai_client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        self.embedding_model = os.environ.get("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
        self.embedding_dimensions = int(os.environ.get("OPENAI_EMBEDDING_DIMENSIONS", "512"))

        self.pc = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
        self.index = self.pc.Index(os.environ["PINECONE_INDEX_NAME"])
        self.namespace = os.environ.get("PINECONE_NAMESPACE", "recipes")

        self.recipes_by_id = {r.recipe_id: r for r in load_recipes()}

    def _embed_text(self, text: str) -> list[float]:
        """Embed text using OpenAI's embedding model."""
        response = self.openai_client.embeddings.create(
            model=self.embedding_model,
            input=text,
            dimensions=self.embedding_dimensions
        )
        return response.data[0].embedding

    def search(
        self,
        pantry: PantryState,
        request: PlanningRequest,
        top_k: int = 8,
    ) -> list[RecipeCandidate]:
        """Retrieve top-k recipe candidates using Pinecone.

        Query construction:
            - Ingredient IDs from the current pantry (what's available)
            - Requested cuisine tags
            - Goal (general/nutritional/kids)

        Vegetarian metadata is filtered in Pinecone and checked locally.
        Cuisine mismatches remain available at a reduced score for fallback.

        Returns:
            Top-k RecipeCandidate objects, sorted by retrieval_score descending.
        """
        if top_k <= 0:
            raise ValueError("top_k must be positive")

        # Build search query from pantry and request
        query_text = self._build_query(request, pantry)

        # Embed the query using OpenAI
        query_vector = self._embed_text(query_text)

        # Search Pinecone
        results = self.index.query(
            vector=query_vector,
            top_k=top_k * 2,  # Get more candidates for filtering
            namespace=self.namespace,
            include_metadata=True,
            **({"filter": {"vegetarian": {"$eq": True}}}
               if request.vegetarian_required else {}),
        )

        # Process results and apply metadata filtering
        candidates = []
        for match in results["matches"]:
            recipe_id = match["id"]
            score = float(match["score"])

            if recipe_id not in self.recipes_by_id:
                raise ValueError(f"UNKNOWN_RECIPE_ID: {recipe_id}")

            recipe = self.recipes_by_id[recipe_id]

            # Metadata filter: cuisine match
            cuisine_match = any(c in recipe.cuisine_tags for c in request.cuisines)
            if not cuisine_match:
                score *= 0.5

            # Metadata filter: vegetarian requirement
            if request.vegetarian_required and not recipe.vegetarian:
                continue

            candidates.append((recipe_id, score))

        # Sort by score descending and return top-k
        candidates.sort(key=lambda x: x[1], reverse=True)
        result = [
            RecipeCandidate(recipe_id=recipe_id, retrieval_score=score)
            for recipe_id, score in candidates[:top_k]
        ]

        return result

    def _build_query(self, request: PlanningRequest, pantry: PantryState) -> str:
        """Build a search query from the pantry and request."""
        parts = []

        # Add pantry ingredients
        for item in pantry.items:
            if item.quantity_g is not None and item.quantity_g > 0:
                parts.append(item.ingredient_id)

        # Add cuisine preferences
        parts.extend(request.cuisines)

        # Add goal as a signal
        parts.append(request.goal)

        return " ".join(parts)


class LocalRetriever:
    """Local in-memory retriever using TF-IDF embeddings and cosine similarity.

    Builds a search query from pantry ingredients, cuisine preference, and goal,
    then ranks recipes by semantic similarity. Applies metadata filtering
    (cuisine match, vegetarian flag) as a prefilter before returning results.

    For the 20-40 recipe corpus, this is fast, deterministic, and offline-capable.
    For larger corpora, this can be replaced with a vector database backend
    while keeping the same interface.
    """

    def __init__(self):
        """Load or build the recipe embedding index."""
        self.embeddings, self.recipe_index, self.vectorizer = index_recipes()
        self.recipes = load_recipes()
        self.recipes_by_id = {r.recipe_id: r for r in self.recipes}

    def search(
        self,
        pantry: PantryState,
        request: PlanningRequest,
        top_k: int = 8,
    ) -> list[RecipeCandidate]:
        """Retrieve top-k recipe candidates.

        Query construction:
            - Ingredient IDs from the current pantry (what's available)
            - Requested cuisine tags
            - Goal (general/nutritional/kids)

        Vegetarian recipes are required when requested. Cuisine mismatches
        remain available at a reduced score for the planner fallback.

        Ranking:
            - TF-IDF cosine similarity between query and recipe embeddings
            - Higher score = more relevant

        Returns:
            Top-k RecipeCandidate objects, sorted by retrieval_score descending.
        """
        if top_k <= 0:
            raise ValueError("top_k must be positive")

        # Build search query from pantry and request
        query_text = self._build_query(request, pantry)

        # Vectorize the query using the cached vectorizer
        query_vector = self.vectorizer.transform([query_text]).toarray()[0]

        # Compute cosine similarity against all recipes
        similarities = cosine_similarity([query_vector], self.embeddings)[0]

        # Collect candidates with metadata filtering
        candidates = []
        for recipe in self.recipes:
            recipe_idx = self.recipe_index[recipe.recipe_id]
            score = float(similarities[recipe_idx])

            # Metadata filter: cuisine match
            cuisine_match = any(c in recipe.cuisine_tags for c in request.cuisines)
            if not cuisine_match:
                # Reduce score but don't exclude; scoring.py will filter later
                score *= 0.5

            # Metadata filter: vegetarian requirement
            if request.vegetarian_required and not recipe.vegetarian:
                # Exclude before top-k; the planner checks the gate again.
                continue

            candidates.append((recipe, score))

        # Sort by score descending and return top-k
        candidates.sort(key=lambda x: x[1], reverse=True)
        result = [
            RecipeCandidate(recipe_id=recipe.recipe_id, retrieval_score=score)
            for recipe, score in candidates[:top_k]
        ]

        return result

    def _build_query(self, request: PlanningRequest, pantry: PantryState) -> str:
        """Build a search query from the pantry and request.

        Combines:
            - Ingredient IDs currently available (what you want to use)
            - Cuisine preferences
            - Goal (general, nutritional, kids)

        Returns:
            A space-separated string for TF-IDF vectorization.
        """
        parts = []

        # Add pantry ingredients (prioritize these)
        for item in pantry.items:
            if item.quantity_g is not None and item.quantity_g > 0:
                parts.append(item.ingredient_id)

        # Add cuisine preferences
        parts.extend(request.cuisines)

        # Add goal as a signal
        parts.append(request.goal)

        return " ".join(parts)


def create_retriever() -> Retriever:
    """Factory to create a retriever instance.

    Tries to create a PineconeRetriever if API keys are available.
    Falls back to LocalRetriever (TF-IDF) if Pinecone keys are missing.

    Environment variables:
        OPENAI_API_KEY: Required for Pinecone mode
        PINECONE_API_KEY: Required for Pinecone mode
        PINECONE_INDEX_NAME: Required for Pinecone mode
        OPENAI_EMBEDDING_DIMENSIONS: Default 512; must match the indexed recipe vectors
        RETRIEVAL_BACKEND: Optional; "pinecone" or "local" to force choice

    Pinecone Index Setup:
        Create index in https://console.pinecone.io/ with:
        - Dimension: 512 (to match OPENAI_EMBEDDING_DIMENSIONS)
        - Metric: cosine
        - Namespace: "recipes" (or set PINECONE_NAMESPACE env var)

    Returns:
        A Retriever instance (either Pinecone or local).
    """
    backend = os.environ.get("RETRIEVAL_BACKEND", "pinecone").lower()

    # Force local if explicitly requested
    if backend == "local":
        print("Using LocalRetriever (TF-IDF)")
        return LocalRetriever()

    # Try Pinecone
    if all([
        os.environ.get("OPENAI_API_KEY"),
        os.environ.get("PINECONE_API_KEY"),
        os.environ.get("PINECONE_INDEX_NAME"),
    ]):
        try:
            print("Using PineconeRetriever (OpenAI embeddings + Pinecone)")
            return PineconeRetriever()
        except Exception as e:
            print(f"Failed to initialize Pinecone: {e}")
            print("Falling back to LocalRetriever (TF-IDF)")
            return LocalRetriever()

    # Fall back to local if Pinecone keys missing
    print("Pinecone keys not found; using LocalRetriever (TF-IDF)")
    return LocalRetriever()


# Backward compatibility
def create_local_retriever() -> Retriever:
    """Deprecated: Use create_retriever() instead."""
    return LocalRetriever()


if __name__ == "__main__":
    import argparse
    import json
    from pathlib import Path

    from dotenv import load_dotenv
    from schemas import PantryItem

    parser = argparse.ArgumentParser(description="Search recipes using a pantry fixture")
    parser.add_argument("--backend", choices=("local", "pinecone"), default="local")
    parser.add_argument("--fixture", type=Path, default=Path(__file__).resolve().parent /
                        "fixtures/01_well_stocked_veg_italian.json")
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()
    load_dotenv(Path(__file__).resolve().parent / ".env")
    fixture = json.loads(args.fixture.read_text())
    pantry_data = dict(fixture["pantry"])
    if isinstance(pantry_data["items"], dict):
        pantry_data["items"] = [PantryItem(
            ingredient_id=name, display_name=name.replace("_", " "),
            quantity_g=quantity, confidence=1,
        ) for name, quantity in pantry_data["items"].items()]
    pantry = PantryState.model_validate(pantry_data)
    request = PlanningRequest.model_validate(fixture["request"])
    # Explicit backend selection: a cloud failure should be visible in this demo.
    retriever = LocalRetriever() if args.backend == "local" else PineconeRetriever()
    print(f"Backend: {args.backend}; fixture: {args.fixture.name}", flush=True)
    for candidate in retriever.search(pantry, request, args.top_k):
        recipe = get_recipe(candidate.recipe_id)
        print(f"{candidate.retrieval_score:.4f}  {recipe.recipe_id}: {recipe.title} "
              f"(vegetarian={recipe.vegetarian})")
