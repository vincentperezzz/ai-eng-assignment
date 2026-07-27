import json
import tempfile
import unittest
from pathlib import Path

from llm_pipeline.models import ModificationEdit, ModificationObject
from llm_pipeline.pipeline import LLMAnalysisPipeline


class StubTweakExtractor:
    def extract_modifications(self, reviews, recipe, max_reviews=None):
        results = []
        for review in reviews:
            text = review.text.lower()

            # Brief cue: one review, two discrete tips.
            if "added an egg" in text and "halved the sugar" in text:
                results.extend(
                    [
                        (
                            ModificationObject(
                                modification_type="addition",
                                reasoning="An extra egg improves structure",
                                edits=[
                                    ModificationEdit(
                                        target="ingredients",
                                        operation="replace",
                                        find="2 eggs",
                                        replace="3 eggs",
                                    )
                                ],
                            ),
                            review,
                        ),
                        (
                            ModificationObject(
                                modification_type="quantity_adjustment",
                                reasoning="Less sugar reduces sweetness",
                                edits=[
                                    ModificationEdit(
                                        target="ingredients",
                                        operation="replace",
                                        find="1 cup white sugar",
                                        replace="0.5 cup white sugar",
                                    )
                                ],
                            ),
                            review,
                        ),
                    ]
                )
                continue

            # One tip applies, one cannot match the recipe.
            if "phantom saffron" in text:
                results.extend(
                    [
                        (
                            ModificationObject(
                                modification_type="addition",
                                reasoning="Egg yolk improves chewiness",
                                edits=[
                                    ModificationEdit(
                                        target="ingredients",
                                        operation="add_after",
                                        find="2 eggs",
                                        add="1 egg yolk",
                                    )
                                ],
                            ),
                            review,
                        ),
                        (
                            ModificationObject(
                                modification_type="addition",
                                reasoning="Saffron was mentioned but is not in this recipe",
                                edits=[
                                    ModificationEdit(
                                        target="ingredients",
                                        operation="replace",
                                        find="1 pinch saffron",
                                        replace="2 pinches saffron",
                                    )
                                ],
                            ),
                            review,
                        ),
                    ]
                )
                continue

            if "egg yolk" in review.text:
                results.append(
                    (
                        ModificationObject(
                            modification_type="addition",
                            reasoning="Extra yolk improves chewiness",
                            edits=[
                                ModificationEdit(
                                    target="ingredients",
                                    operation="add_after",
                                    find="2 eggs",
                                    add="1 egg yolk",
                                )
                            ],
                        ),
                        review,
                    )
                )
            if "cream of tartar" in review.text:
                results.append(
                    (
                        ModificationObject(
                            modification_type="addition",
                            reasoning="Cream of tartar helps cookies hold shape",
                            edits=[
                                ModificationEdit(
                                    target="ingredients",
                                    operation="remove",
                                    find="2 teaspoons hot water",
                                ),
                                ModificationEdit(
                                    target="ingredients",
                                    operation="add_after",
                                    find="0.5 teaspoon salt",
                                    add="1 teaspoon cream of tartar",
                                ),
                            ],
                        ),
                        review,
                    )
                )
        return results


class PipelineTests(unittest.TestCase):
    def test_parse_reviews_data_deduplicates_and_prioritizes_featured_tweaks(self):
        pipeline = LLMAnalysisPipeline(tweak_extractor=StubTweakExtractor())
        recipe_data = {
            "featured_tweaks": [
                {
                    "text": "Use more brown sugar",
                    "rating": 5,
                    "has_modification": True,
                }
            ],
            "reviews": [
                {
                    "text": "Use more brown sugar",
                    "rating": 5,
                    "has_modification": True,
                },
                {
                    "text": "Great recipe",
                    "rating": 5,
                    "has_modification": False,
                },
            ],
        }

        reviews = pipeline.parse_reviews_data(recipe_data)

        self.assertEqual(len(reviews), 2)
        self.assertTrue(reviews[0].is_featured)
        self.assertEqual(reviews[0].text, "Use more brown sugar")

    def test_process_single_recipe_applies_multiple_modifications(self):
        recipe_data = {
            "recipe_id": "10813",
            "title": "Best Chocolate Chip Cookies",
            "ingredients": [
                "1 cup butter, softened",
                "2 eggs",
                "2 teaspoons hot water",
                "0.5 teaspoon salt",
            ],
            "instructions": [
                "Mix everything together.",
                "Bake in the preheated oven until edges are nicely browned, about 10 minutes.",
            ],
            "featured_tweaks": [
                {
                    "text": "I added an additional egg yolk to help keep the cookie chewy.",
                    "rating": 5,
                    "has_modification": True,
                },
                {
                    "text": "I added a teaspoon of cream of tartar to the batter and omitted the water.",
                    "rating": 5,
                    "has_modification": True,
                },
            ],
            "reviews": [],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            recipe_path = Path(temp_dir) / "recipe_10813_best-chocolate-chip-cookies.json"
            recipe_path.write_text(json.dumps(recipe_data), encoding="utf-8")

            pipeline = LLMAnalysisPipeline(
                output_dir=temp_dir,
                tweak_extractor=StubTweakExtractor(),
            )

            enhanced_recipe = pipeline.process_single_recipe(str(recipe_path), save_output=False)

        self.assertIsNotNone(enhanced_recipe)
        self.assertEqual(len(enhanced_recipe.modifications_applied), 2)
        self.assertIn("1 egg yolk", enhanced_recipe.ingredients)
        self.assertIn("1 teaspoon cream of tartar", enhanced_recipe.ingredients)
        self.assertNotIn("2 teaspoons hot water", enhanced_recipe.ingredients)

    def test_one_review_splits_into_two_discrete_modifications(self):
        recipe_data = {
            "recipe_id": "10813",
            "title": "Best Chocolate Chip Cookies",
            "ingredients": [
                "1 cup white sugar",
                "2 eggs",
            ],
            "instructions": ["Mix and bake."],
            "featured_tweaks": [
                {
                    "text": "I added an egg and halved the sugar. Much better.",
                    "rating": 5,
                    "has_modification": True,
                }
            ],
            "reviews": [],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            recipe_path = Path(temp_dir) / "recipe_split.json"
            recipe_path.write_text(json.dumps(recipe_data), encoding="utf-8")
            pipeline = LLMAnalysisPipeline(
                output_dir=temp_dir,
                tweak_extractor=StubTweakExtractor(),
            )
            enhanced = pipeline.process_single_recipe(str(recipe_path), save_output=False)

        self.assertIsNotNone(enhanced)
        self.assertEqual(len(enhanced.modifications_applied), 2)
        self.assertEqual(len(enhanced.modifications_by_review), 1)
        self.assertEqual(len(enhanced.modifications_by_review[0].modifications), 2)
        self.assertEqual(
            {mod.modification_type for mod in enhanced.modifications_applied},
            {"addition", "quantity_adjustment"},
        )
        self.assertTrue(all(mod.status == "applied" for mod in enhanced.modifications_applied))
        self.assertEqual(enhanced.ingredients[0], "0.5 cup white sugar")
        self.assertEqual(enhanced.ingredients[1], "3 eggs")
        # Same source review text on both discrete tips.
        self.assertEqual(
            enhanced.modifications_applied[0].source_review.text,
            enhanced.modifications_applied[1].source_review.text,
        )

    def test_unapplied_modification_is_still_recorded(self):
        recipe_data = {
            "recipe_id": "10813",
            "title": "Best Chocolate Chip Cookies",
            "ingredients": ["2 eggs", "1 cup white sugar"],
            "instructions": ["Mix and bake."],
            "featured_tweaks": [
                {
                    "text": "I added an egg yolk and also used phantom saffron.",
                    "rating": 5,
                    "has_modification": True,
                }
            ],
            "reviews": [],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            recipe_path = Path(temp_dir) / "recipe_partial.json"
            recipe_path.write_text(json.dumps(recipe_data), encoding="utf-8")
            pipeline = LLMAnalysisPipeline(
                output_dir=temp_dir,
                tweak_extractor=StubTweakExtractor(),
            )
            enhanced = pipeline.process_single_recipe(str(recipe_path), save_output=False)

        self.assertIsNotNone(enhanced)
        statuses = {mod.status for mod in enhanced.modifications_applied}
        self.assertEqual(statuses, {"applied", "unapplied"})
        unapplied = [mod for mod in enhanced.modifications_applied if mod.status == "unapplied"]
        self.assertEqual(len(unapplied), 1)
        self.assertIsNotNone(unapplied[0].unapplied_reason)
        self.assertIn("1 egg yolk", enhanced.ingredients)
        self.assertEqual(len(enhanced.modifications_by_review), 1)


if __name__ == "__main__":
    unittest.main()
