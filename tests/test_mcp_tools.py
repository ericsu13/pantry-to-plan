"""Contract and invariant tests for the local MCP meal tools."""

import json
from pathlib import Path
import unittest

from meal_tools_server import (
    evaluate_candidates_impl,
    get_recipe_details_impl,
    search_recipes_impl,
    simulate_plan_impl,
    validate_final_plan_impl,
)
from schemas import PantryItem, PantryState


ROOT = Path(__file__).resolve().parents[1]


def fixture(stem="01_well_stocked_veg_italian"):
    return json.loads((ROOT / "fixtures" / f"{stem}.json").read_text())


def pantry_json(fx):
    return PantryState(
        items=[
            PantryItem(
                ingredient_id=ingredient_id,
                display_name=ingredient_id.replace("_", " "),
                quantity_g=quantity,
                confidence=1.0,
            )
            for ingredient_id, quantity in fx["pantry"]["items"].items()
        ]
    ).model_dump(mode="json")


class MCPMealToolTests(unittest.TestCase):
    def setUp(self):
        self.fx = fixture()
        self.pantry = pantry_json(self.fx)
        self.request = self.fx["request"]

    def test_search_returns_grounded_candidates(self):
        result = search_recipes_impl(self.pantry, self.request, 8, "local")
        self.assertEqual(result["backend"], "local")
        self.assertTrue(result["candidates"])
        details = get_recipe_details_impl(
            [candidate["recipe_id"] for candidate in result["candidates"]]
        )
        self.assertEqual(details["unknown_recipe_ids"], [])
        self.assertEqual(len(details["recipes"]), len(result["candidates"]))

    def test_unknown_recipe_is_reported_not_invented(self):
        details = get_recipe_details_impl(["not_a_real_recipe"])
        self.assertEqual(details["recipes"], [])
        self.assertEqual(details["unknown_recipe_ids"], ["not_a_real_recipe"])
        evaluated = evaluate_candidates_impl(
            ["not_a_real_recipe"], self.pantry, self.request
        )
        self.assertEqual(evaluated["scores"], [])
        self.assertEqual(evaluated["issues"][0]["code"], "UNKNOWN_RECIPE_ID")

    def test_final_validator_rejects_nonvegetarian_proposal(self):
        result = validate_final_plan_impl(
            self.pantry,
            self.request,
            ["it_chicken_parmesan", "it_mushroom_risotto", "it_penne_arrabbiata"],
        )
        self.assertFalse(result["approved"])
        self.assertIn("VEGETARIAN_REQUIRED", {i["code"] for i in result["issues"]})
        self.assertTrue(all(day["recipe"]["vegetarian"] for day in result["plan"]["day_plans"]))

    def test_simulation_and_validation_use_same_arithmetic(self):
        proposal = [
            "it_mushroom_risotto",
            "it_penne_arrabbiata",
            "it_aglio_e_olio",
        ]
        simulation = simulate_plan_impl(self.pantry, self.request, proposal)
        validation = validate_final_plan_impl(self.pantry, self.request, proposal)
        self.assertTrue(validation["approved"])
        self.assertEqual(simulation["plan"]["final_pantry"], validation["plan"]["final_pantry"])
        self.assertEqual(simulation["plan"]["shopping_list"], validation["plan"]["shopping_list"])
        self.assertEqual(simulation["metrics"], validation["metrics"])


if __name__ == "__main__":
    unittest.main()

