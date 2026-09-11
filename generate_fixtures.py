"""Generate pantry eval fixtures for Pantry to Plan.

Each fixture is a self-contained eval scenario: the parsed pantry (what the
vision step would emit), the plan request, and the expected outcome. Pantries
are built from the real ingredient ids in recipes.py so pantry_coverage,
fallback, and exhaustion behaviour are genuine rather than hand-faked.

Run:  python3 generate_fixtures.py
Writes ~20 JSON files to fixtures/.
"""

import json
import os

from recipes import RECIPES

AS_OF = "2026-09-11"  # matches the demo's fixed "today"; not a real plan date
OUT_DIR = os.path.join(os.path.dirname(__file__), "fixtures")

by_id = {r.recipe_id: r for r in RECIPES}


def by_cuisine(cuisine, veg_only=False):
    return [
        r
        for r in RECIPES
        if r.cuisine == cuisine and (r.vegetarian or not veg_only)
    ]


def stock(recipe_ids, mult=3.0, drop=()):
    """Pantry that covers the union of the given recipes' ingredients.

    mult scales per-serving grams up so there's headroom for multi-day plans
    and pantry depletion. `drop` removes specific ingredients to create
    deliberately partial coverage.
    """
    agg = {}
    for rid in recipe_ids:
        for ing, g in by_id[rid].ingredients.items():
            agg[ing] = max(agg.get(ing, 0.0), g)
    return {
        ing: round(g * mult)
        for ing, g in sorted(agg.items())
        if ing not in drop
    }


def fixture(fid, description, tags, pantry, request, expect):
    return {
        "id": fid,
        "description": description,
        "tags": tags,
        "pantry": {"as_of": AS_OF, "items": pantry},
        "request": request,
        "expect": expect,
    }


def req(cuisines, target, tol, days, veg=False):
    return {
        "cuisines": cuisines if isinstance(cuisines, list) else [cuisines],
        "calorie_target": target,   # kcal for the one dinner recipe of the day
        "calorie_tolerance": tol,   # +/- band; outside -> pick-best-and-flag
        "days": days,
        "vegetarian_required": veg,
    }


FIXTURES = [
    # ============================================================= key case 1
    fixture(
        "01_well_stocked_veg_italian",
        "Well-stocked pantry covering several vegetarian Italian dinners; "
        "600 kcal target, 3 days, vegetarian required.",
        ["well-stocked", "vegetarian", "happy-path"],
        stock(
            [
                "it_aglio_e_olio",
                "it_penne_arrabbiata",
                "it_margherita_flatbread",
                "it_mushroom_risotto",
            ],
            mult=3.0,
        ),
        req("italian", 600, 150, 3, veg=True),
        {
            "all_vegetarian": True,
            "all_cuisine_match": True,
            "all_within_calorie_band": True,
            "fallback_flags": False,
            "days_returned": 3,
            "notes": "Clean happy path: high coverage, every day veg + Italian "
            "+ in band (450-750), no fallback.",
        },
    ),
    # ============================================================= key case 2
    fixture(
        "02_sparse_chinese_fallback",
        "Nearly empty pantry, Chinese cuisine, 5 days. Only 4 Chinese recipes "
        "fall in the 350-550 band, so day 5 must fall back to closest calorie.",
        ["sparse", "fallback", "edge"],
        {"rice": 120, "soy_sauce": 40, "garlic": 20},
        req("chinese", 450, 100, 5, veg=False),
        {
            "low_pantry_coverage": True,
            "all_cuisine_match": True,
            "at_least_one_fallback": True,
            "days_returned": 5,
            "notes": "4 recipes in band (broccoli 410, egg-drop 440, fried "
            "rice 480, kung pao tofu 520); 5th day forced to closest-calorie "
            "outside band (e.g. mapo/lo mein 560). Proves fallback fires "
            "instead of crashing or returning nothing.",
        },
    ),
    # ============================================================= key case 3
    fixture(
        "03_tight_band_indian",
        "Indian cuisine, very narrow 350 +/- 50 band, 4 days. No Indian recipe "
        "sits inside 300-400, so every day is an out-of-band flagged pick.",
        ["tight-band", "flagging", "edge"],
        stock(["in_dal_tadka", "in_aloo_gobi"], mult=2.0),
        req("indian", 350, 50, 4, veg=False),
        {
            "all_cuisine_match": True,
            "all_within_calorie_band": False,
            "every_day_flagged_out_of_band": True,
            "days_returned": 4,
            "notes": "Lowest Indian recipe is aloo gobi at 440 (>400), so no "
            "day can satisfy the band. Per spec there is no reject-and-retry: "
            "pick the 4 closest (aloo gobi 440, dal 470, chana 520, paneer "
            "wrap 540) and flag each as out-of-band.",
        },
    ),
    # ============================================================= key case 4
    fixture(
        "04_veg_exhaustion_american",
        "Sparse pantry, American cuisine, vegetarian required, 7 days requested "
        "but only 6 eligible vegetarian American recipes exist.",
        ["vegetarian", "exhaustion", "edge"],
        {"onion": 60, "cheddar": 50, "black_beans": 80},
        req("american", 550, 150, 7, veg=True),
        {
            "all_vegetarian": True,
            "no_non_vegetarian_selected": True,
            "days_returned": 6,
            "reports_constraint_prevented_completion": True,
            "notes": "6 vegetarian American recipes exist; 7 days requested. "
            "Return 6 days, never substitute a non-veg recipe, and clearly "
            "report the hard constraint blocked day 7.",
        },
    ),
    # ===================================================== additional variety
    fixture(
        "05_empty_pantry_italian",
        "Completely empty pantry, Italian, 3 days. Extreme sparse edge: "
        "coverage is 0 everywhere, everything lands on the shopping list.",
        ["empty", "sparse", "edge"],
        {},
        req("italian", 600, 150, 3, veg=False),
        {
            "low_pantry_coverage": True,
            "all_pantry_coverage_zero": True,
            "all_cuisine_match": True,
            "days_returned": 3,
            "notes": "Plan still succeeds; shopping list equals full ingredient "
            "demand for the 3 chosen recipes.",
        },
    ),
    fixture(
        "06_well_stocked_omnivore_italian",
        "Well-stocked pantry for hearty Italian dinners; 700 kcal, 4 days, "
        "no dietary restriction.",
        ["well-stocked", "omnivore", "happy-path"],
        stock(
            [
                "it_chicken_parmesan",
                "it_spaghetti_bolognese",
                "it_prosciutto_arugula_pizza",
                "it_shrimp_scampi_linguine",
            ],
            mult=3.0,
        ),
        req("italian", 700, 150, 4, veg=False),
        {
            "all_cuisine_match": True,
            "high_pantry_coverage": True,
            "days_returned": 4,
            "notes": "Meat/seafood Italian dishes cluster 590-720, all inside "
            "550-850 band.",
        },
    ),
    fixture(
        "07_well_stocked_indian_veg",
        "Well-stocked pantry for vegetarian Indian dinners; 500 kcal, 5 days, "
        "vegetarian required.",
        ["well-stocked", "vegetarian", "happy-path"],
        stock(
            [
                "in_vegetable_biryani",
                "in_chana_masala",
                "in_palak_paneer",
                "in_dal_tadka",
                "in_aloo_gobi",
                "in_paneer_tikka_wrap",
            ],
            mult=3.0,
        ),
        req("indian", 500, 150, 5, veg=True),
        {
            "all_vegetarian": True,
            "all_cuisine_match": True,
            "all_within_calorie_band": True,
            "days_returned": 5,
            "notes": "6 veg Indian recipes span 440-590, all inside 350-650; "
            "5 days fit comfortably.",
        },
    ),
    fixture(
        "08_well_stocked_chinese_omnivore",
        "Well-stocked pantry for Chinese dinners; 600 kcal, 4 days.",
        ["well-stocked", "omnivore", "happy-path"],
        stock(
            [
                "cn_kung_pao_chicken",
                "cn_beef_and_broccoli",
                "cn_shrimp_lo_mein",
                "cn_general_tso_chicken",
            ],
            mult=3.0,
        ),
        req("chinese", 600, 150, 4, veg=False),
        {
            "all_cuisine_match": True,
            "high_pantry_coverage": True,
            "days_returned": 4,
            "notes": "General Tso at 700 sits at the top edge of 450-750.",
        },
    ),
    fixture(
        "09_well_stocked_american_veg",
        "Well-stocked pantry for vegetarian American dinners; 550 kcal, 4 days, "
        "vegetarian required.",
        ["well-stocked", "vegetarian", "happy-path"],
        stock(
            [
                "am_mac_and_cheese",
                "am_black_bean_burger",
                "am_veggie_quesadilla",
                "am_buffalo_cauliflower_bowl",
                "am_grilled_cheese_tomato_soup",
            ],
            mult=3.0,
        ),
        req("american", 550, 150, 4, veg=True),
        {
            "all_vegetarian": True,
            "all_cuisine_match": True,
            "all_within_calorie_band": True,
            "days_returned": 4,
            "notes": "5 stocked veg options 480-650, all inside 400-700.",
        },
    ),
    fixture(
        "10_multi_cuisine_italian_indian",
        "Two cuisine preferences (Italian + Indian), vegetarian, 550 kcal, "
        "5 days. Exercises multiple cuisine tags at once.",
        ["multi-cuisine", "vegetarian", "happy-path"],
        stock(
            [
                "it_penne_arrabbiata",
                "it_mushroom_risotto",
                "in_chana_masala",
                "in_palak_paneer",
                "in_vegetable_biryani",
            ],
            mult=3.0,
        ),
        req(["italian", "indian"], 550, 150, 5, veg=True),
        {
            "all_vegetarian": True,
            "all_cuisine_match": True,
            "days_returned": 5,
            "notes": "cuisine_match is True when a recipe's tag is in the "
            "requested set; plan may mix Italian and Indian days.",
        },
    ),
    fixture(
        "11_narrow_band_american_exact",
        "American, very tight 700 +/- 20 band, 2 days. Cheeseburger hits 700 "
        "exactly (delta 0); day 2 must fall back to closest calorie.",
        ["tight-band", "exact-match", "fallback", "edge"],
        stock(["am_classic_cheeseburger", "am_mac_and_cheese"], mult=2.0),
        req("american", 700, 20, 2, veg=False),
        {
            "all_cuisine_match": True,
            "exact_calorie_match_day_exists": True,
            "at_least_one_fallback": True,
            "days_returned": 2,
            "notes": "Only the cheeseburger (700) is in 680-720. Day 1 delta=0; "
            "day 2 closest is mac and cheese (650, delta -50), flagged.",
        },
    ),
    fixture(
        "12_partial_pantry_italian",
        "Partial Italian pantry (about half the needed ingredients present); "
        "550 kcal, 3 days. Coverage lands mid-range.",
        ["partial", "happy-path"],
        stock(
            ["it_aglio_e_olio", "it_penne_arrabbiata", "it_caprese_farro_salad"],
            mult=3.0,
            drop=("olive_oil", "garlic", "mozzarella", "parsley"),
        ),
        req("italian", 550, 150, 3, veg=False),
        {
            "all_cuisine_match": True,
            "partial_pantry_coverage": True,
            "days_returned": 3,
            "notes": "Shared staples (olive_oil, garlic) dropped so coverage "
            "sits well below 100% but above 0.",
        },
    ),
    fixture(
        "13_wrong_cuisine_pantry",
        "Pantry fully stocked with Indian ingredients but request is Italian; "
        "600 kcal, 3 days. Full jars, near-zero coverage.",
        ["mismatch", "edge"],
        stock(["in_chana_masala", "in_butter_chicken", "in_palak_paneer"], mult=4.0),
        req("italian", 600, 150, 3, veg=False),
        {
            "all_cuisine_match": True,
            "low_pantry_coverage": True,
            "days_returned": 3,
            "notes": "Coverage is low despite a large pantry because the ids "
            "don't join the Italian recipes; checks join specificity (shared "
            "items like onion/garlic/tomato still count).",
        },
    ),
    fixture(
        "14_single_day_chinese",
        "Single-day plan, Chinese, 500 kcal. Minimum-days edge.",
        ["min-days", "edge"],
        stock(["cn_vegetable_fried_rice"], mult=3.0),
        req("chinese", 500, 150, 1, veg=False),
        {
            "all_cuisine_match": True,
            "days_returned": 1,
            "notes": "One recipe, one day; makes sure N=1 doesn't break "
            "aggregation or depletion.",
        },
    ),
    fixture(
        "15_large_pantry_all_ingredients",
        "Huge pantry covering the entire corpus; Italian, 5 days, no "
        "restriction. Coverage should be at or near 100% and the shopping "
        "list nearly empty.",
        ["well-stocked", "full-coverage", "happy-path"],
        stock([r.recipe_id for r in RECIPES], mult=5.0),
        req("italian", 600, 150, 5, veg=False),
        {
            "all_cuisine_match": True,
            "high_pantry_coverage": True,
            "shopping_list_small_or_empty": True,
            "days_returned": 5,
            "notes": "Stresses aggregation when almost nothing needs buying.",
        },
    ),
    fixture(
        "16_veg_tight_band_indian",
        "Vegetarian Indian with a tight 450 +/- 30 band, 4 days. Combines the "
        "hard veg gate with band flagging.",
        ["vegetarian", "tight-band", "edge"],
        stock(
            ["in_dal_tadka", "in_aloo_gobi", "in_chana_masala", "in_palak_paneer"],
            mult=3.0,
        ),
        req("indian", 450, 30, 4, veg=True),
        {
            "all_vegetarian": True,
            "all_cuisine_match": True,
            "all_within_calorie_band": False,
            "some_days_flagged_out_of_band": True,
            "days_returned": 4,
            "notes": "Only dal (470) and aloo gobi (440) sit in 420-480; the "
            "other 2 veg days are flagged out-of-band but stay vegetarian.",
        },
    ),
    fixture(
        "17_sparse_indian",
        "Sparse pantry, Indian, 4 days, 500 kcal. Sparse coverage on a "
        "non-Chinese cuisine for variety.",
        ["sparse", "edge"],
        {"rice": 200, "onion": 60, "garam_masala": 15},
        req("indian", 500, 150, 4, veg=False),
        {
            "low_pantry_coverage": True,
            "all_cuisine_match": True,
            "days_returned": 4,
            "notes": "Only staples on hand; most Indian dinners sit in band so "
            "no forced fallback, but coverage stays low.",
        },
    ),
    fixture(
        "18_american_family_pantry",
        "Well-stocked American family pantry; 650 kcal, 5 days, no restriction.",
        ["well-stocked", "omnivore", "happy-path"],
        stock(
            [
                "am_classic_cheeseburger",
                "am_bbq_pulled_chicken_sandwich",
                "am_cobb_salad",
                "am_maple_glazed_salmon",
                "am_mac_and_cheese",
            ],
            mult=3.0,
        ),
        req("american", 650, 150, 5, veg=False),
        {
            "all_cuisine_match": True,
            "high_pantry_coverage": True,
            "days_returned": 5,
            "notes": "Mix of meat, fish, and cheese mains inside 500-800.",
        },
    ),
    fixture(
        "19_low_target_veg_italian",
        "Vegetarian Italian with a low 400 +/- 80 target, 3 days. Pushes the "
        "scorer toward lighter dishes (salad, soup).",
        ["vegetarian", "low-calorie", "edge"],
        stock(
            [
                "it_caprese_farro_salad",
                "it_tuscan_white_bean_soup",
                "it_penne_arrabbiata",
            ],
            mult=3.0,
        ),
        req("italian", 400, 80, 3, veg=True),
        {
            "all_vegetarian": True,
            "all_cuisine_match": True,
            "days_returned": 3,
            "notes": "Caprese (470) and Tuscan bean soup (430) fall in 320-480; "
            "the 3rd day flags out-of-band but stays vegetarian.",
        },
    ),
    fixture(
        "20_mixed_realistic_pantry",
        "A realistic mixed household pantry; Italian, 600 kcal, 4 days. The "
        "everyday normal case.",
        ["realistic", "happy-path"],
        {
            "olive_oil": 500,
            "garlic": 120,
            "onion": 400,
            "canned_tomatoes": 800,
            "spaghetti": 500,
            "penne": 500,
            "parmesan": 150,
            "mozzarella": 200,
            "egg": 300,
            "chicken_breast": 400,
            "carrot": 300,
            "basil": 20,
            "parsley": 20,
        },
        req("italian", 600, 150, 4, veg=False),
        {
            "all_cuisine_match": True,
            "mixed_pantry_coverage": True,
            "days_returned": 4,
            "notes": "Common staples on hand; some recipes well covered, "
            "others need a few buys. Representative demo run.",
        },
    ),
    # ============================ vision noise: unclear / poorly-labeled items
    # The vision step emits whatever it read off the photo. These fixtures use
    # non-canonical ids to model low-confidence or ambiguous labels. They must
    # NOT join the corpus, so coverage stays low and the planner ignores them
    # rather than crashing or over-counting.
    fixture(
        "21_ambiguous_labels_italian",
        "Pantry parsed from a messy photo: generic, low-confidence labels "
        "('cheese', 'pasta', 'canned_stuff') that don't resolve to specific "
        "corpus ingredients. Italian, 600 kcal, 3 days.",
        ["unclear-labels", "vision-noise", "edge"],
        {
            "cheese": 200,          # which cheese? mozzarella/parmesan/cheddar unknown
            "pasta": 500,           # ambiguous: spaghetti vs penne vs linguine
            "canned_stuff": 400,    # unreadable can
            "green_herb": 15,       # basil? parsley? unclear
            "cooking_oil": 300,     # olive_oil vs generic
            "unknown_jar": 250,     # unidentified
        },
        req("italian", 600, 150, 3, veg=False),
        {
            "low_pantry_coverage": True,
            "unrecognized_items_ignored": True,
            "all_cuisine_match": True,
            "days_returned": 3,
            "notes": "None of these labels match canonical ids, so coverage is "
            "~0 and everything shows on the shopping list. Verifies unknown "
            "ids are silently ignored, not fatal.",
        },
    ),
    fixture(
        "22_mixed_clear_and_unclear",
        "Realistic parse: some confident canonical ids alongside garbage/"
        "low-confidence labels. Italian, 600 kcal, 4 days.",
        ["unclear-labels", "vision-noise", "realistic", "edge"],
        {
            # confidently identified -> should join and count
            "spaghetti": 500,
            "garlic": 120,
            "olive_oil": 400,
            "canned_tomatoes": 800,
            # unclear / mislabeled -> should be ignored
            "leftover_container": 300,
            "white_powder": 100,       # flour? sugar? salt? unknown
            "misc_vegetable": 200,
            "half_eaten_thing": 150,
        },
        req("italian", 600, 150, 4, veg=False),
        {
            "partial_pantry_coverage": True,
            "unrecognized_items_ignored": True,
            "all_cuisine_match": True,
            "days_returned": 4,
            "notes": "Coverage comes only from the 4 recognized staples; the "
            "junk labels contribute nothing. Aglio e olio / arrabbiata should "
            "score high on coverage.",
        },
    ),
    fixture(
        "23_near_miss_labels_chinese",
        "Vision near-misses: plausible but non-canonical spellings ('soy', "
        "'spring_onion', 'rice_grains') that look right but don't match the "
        "exact join key. Chinese, 550 kcal, 3 days.",
        ["unclear-labels", "vision-noise", "normalization", "edge"],
        {
            "soy": 60,            # should be soy_sauce
            "spring_onion": 40,   # should be green_onion
            "rice_grains": 300,   # should be rice
            "fresh_ginger": 30,   # should be ginger
            "bell_peppers": 150,  # plural; should be bell_pepper
        },
        req("chinese", 550, 150, 3, veg=False),
        {
            "low_pantry_coverage": True,
            "unrecognized_items_ignored": True,
            "all_cuisine_match": True,
            "days_returned": 3,
            "notes": "Every item is a near-miss on a real ingredient, so exact "
            "join yields ~0 coverage. Documents why label canonicalization "
            "would matter (explicitly out of scope this pass) without letting "
            "near-misses silently inflate coverage.",
        },
    ),
]


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    for f in FIXTURES:
        path = os.path.join(OUT_DIR, f["id"] + ".json")
        with open(path, "w") as fh:
            json.dump(f, fh, indent=2)
            fh.write("\n")
    print(f"wrote {len(FIXTURES)} fixtures to {OUT_DIR}")


if __name__ == "__main__":
    main()
