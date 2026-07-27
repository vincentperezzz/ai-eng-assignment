import json
import tempfile
import unittest
from pathlib import Path

from llm_pipeline.models import ModificationEdit, ModificationObject, Review
from llm_pipeline.pipeline import LLMAnalysisPipeline
from llm_pipeline.tip_eligibility import (
    is_extraction_candidate,
    select_candidate_reviews,
)


class TipEligibilityHelperTests(unittest.TestCase):
    def test_nikujaga_style_recall_cue_enters_pool(self):
        review = Review(
            text="You need at least 1 lb of thinly sliced beef for this.",
            rating=5,
            has_modification=False,
            is_featured=False,
        )
        self.assertTrue(is_extraction_candidate(review))

    def test_praise_only_stays_out(self):
        review = Review(
            text="Absolutely delicious! Will make again and again.",
            rating=5,
            has_modification=False,
            is_featured=False,
        )
        # "will make again" is in HINT_PATTERNS — praise with that phrase enters.
        # Pure praise without cue words must stay out:
        pure = Review(
            text="Absolutely delicious! Perfect cookies.",
            rating=5,
            has_modification=False,
            is_featured=False,
        )
        self.assertFalse(is_extraction_candidate(pure))

    def test_featured_enters_even_without_hint(self):
        review = Review(
            text="Loved this recipe so much.",
            rating=5,
            has_modification=False,
            is_featured=True,
        )
        self.assertTrue(is_extraction_candidate(review))

    def test_select_preserves_order(self):
        reviews = [
            Review(text="Featured tip: I added salt.", rating=4, is_featured=True, has_modification=True),
            Review(text="Perfect cookies.", rating=5, has_modification=False),
            Review(text="You need 2 cups flour.", rating=3, has_modification=False),
        ]
        selected = select_candidate_reviews(reviews)
        self.assertEqual(len(selected), 2)
        self.assertEqual(selected[0].text, reviews[0].text)
        self.assertEqual(selected[1].text, reviews[2].text)


class UntestedEvidenceStub:
    def extract_modifications(self, reviews, recipe, max_reviews=None):
        results = []
        for review in reviews[: max_reviews or len(reviews)]:
            text = review.text.lower()
            if "next time" in text and "prefer" in text and "apple" in text:
                results.append(
                    (
                        ModificationObject(
                            modification_type="quantity_adjustment",
                            reasoning="More apple next time",
                            evidence="untested",
                            edits=[
                                ModificationEdit(
                                    target="ingredients",
                                    operation="replace",
                                    find="1 cup diced apple",
                                    replace="1.5 cups diced apple",
                                )
                            ],
                        ),
                        review,
                    )
                )
            elif "added cinnamon" in text:
                results.append(
                    (
                        ModificationObject(
                            modification_type="addition",
                            reasoning="Cinnamon helps flavor",
                            evidence="tested",
                            edits=[
                                ModificationEdit(
                                    target="ingredients",
                                    operation="add_after",
                                    find="1 cup diced apple",
                                    add="1 teaspoon cinnamon",
                                )
                            ],
                        ),
                        review,
                    )
                )
            elif "need at least 1 lb" in text:
                results.append(
                    (
                        ModificationObject(
                            modification_type="quantity_adjustment",
                            reasoning="Beef amount was too low",
                            evidence="tested",
                            edits=[
                                ModificationEdit(
                                    target="ingredients",
                                    operation="replace",
                                    find="0.5 pound thinly sliced beef",
                                    replace="1 pound thinly sliced beef",
                                )
                            ],
                        ),
                        review,
                    )
                )
        return results


class TipEligibilityPipelineTests(unittest.TestCase):
    def test_untested_suggestion_is_visible_but_not_applied(self):
        recipe_data = {
            "recipe_id": "apple1",
            "title": "Apple Cake",
            "ingredients": ["1 cup diced apple", "1 cup flour"],
            "instructions": ["Mix and bake."],
            "featured_tweaks": [
                {
                    "text": "Next time I would prefer more apple.",
                    "rating": 5,
                    "has_modification": True,
                }
            ],
            "reviews": [],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            recipe_path = Path(temp_dir) / "apple.json"
            recipe_path.write_text(json.dumps(recipe_data), encoding="utf-8")
            pipeline = LLMAnalysisPipeline(
                output_dir=temp_dir,
                tweak_extractor=UntestedEvidenceStub(),
            )
            # Only untested tip -> no applied changes -> pipeline returns None
            enhanced = pipeline.process_single_recipe(str(recipe_path), save_output=False)

        self.assertIsNone(enhanced)

    def test_untested_alongside_tested_keeps_untested_unapplied(self):
        recipe_data = {
            "recipe_id": "apple2",
            "title": "Apple Cake",
            "ingredients": ["1 cup diced apple", "1 cup flour"],
            "instructions": ["Mix and bake."],
            "featured_tweaks": [
                {
                    "text": "I added cinnamon. Next time I would prefer more apple.",
                    "rating": 5,
                    "has_modification": True,
                }
            ],
            "reviews": [],
        }

        class ComboStub:
            def extract_modifications(self, reviews, recipe, max_reviews=None):
                review = reviews[0]
                return [
                    (
                        ModificationObject(
                            modification_type="addition",
                            reasoning="Cinnamon helps",
                            evidence="tested",
                            edits=[
                                ModificationEdit(
                                    target="ingredients",
                                    operation="add_after",
                                    find="1 cup diced apple",
                                    add="1 teaspoon cinnamon",
                                )
                            ],
                        ),
                        review,
                    ),
                    (
                        ModificationObject(
                            modification_type="quantity_adjustment",
                            reasoning="More apple next time",
                            evidence="untested",
                            edits=[
                                ModificationEdit(
                                    target="ingredients",
                                    operation="replace",
                                    find="1 cup diced apple",
                                    replace="1.5 cups diced apple",
                                )
                            ],
                        ),
                        review,
                    ),
                ]

        with tempfile.TemporaryDirectory() as temp_dir:
            recipe_path = Path(temp_dir) / "apple2.json"
            recipe_path.write_text(json.dumps(recipe_data), encoding="utf-8")
            pipeline = LLMAnalysisPipeline(
                output_dir=temp_dir,
                tweak_extractor=ComboStub(),
            )
            enhanced = pipeline.process_single_recipe(
                str(recipe_path), save_output=False, max_reviews=1
            )

        self.assertIsNotNone(enhanced)
        self.assertEqual(enhanced.max_reviews, 1)
        self.assertEqual(enhanced.candidates_considered, 1)
        self.assertIn("1 teaspoon cinnamon", enhanced.ingredients)
        self.assertEqual(enhanced.ingredients[0], "1 cup diced apple")
        statuses = {mod.status for mod in enhanced.modifications_applied}
        self.assertEqual(statuses, {"applied", "unapplied"})
        untested = [m for m in enhanced.modifications_applied if m.evidence == "untested"]
        self.assertEqual(len(untested), 1)
        self.assertEqual(untested[0].status, "unapplied")
        self.assertIn("Untested", untested[0].unapplied_reason)

    def test_nikujaga_missed_hint_still_reaches_extraction(self):
        recipe_data = {
            "recipe_id": "niku1",
            "title": "Nikujaga",
            "ingredients": ["0.5 pound thinly sliced beef", "2 potatoes"],
            "instructions": ["Simmer until tender."],
            "featured_tweaks": [],
            "reviews": [
                {
                    "text": "You need at least 1 lb of thinly sliced beef for this.",
                    "rating": 5,
                    "has_modification": False,
                },
                {
                    "text": "Perfect cookies.",
                    "rating": 5,
                    "has_modification": False,
                },
            ],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            recipe_path = Path(temp_dir) / "niku.json"
            recipe_path.write_text(json.dumps(recipe_data), encoding="utf-8")
            pipeline = LLMAnalysisPipeline(
                output_dir=temp_dir,
                tweak_extractor=UntestedEvidenceStub(),
            )
            enhanced = pipeline.process_single_recipe(str(recipe_path), save_output=False)

        self.assertIsNotNone(enhanced)
        self.assertEqual(enhanced.ingredients[0], "1 pound thinly sliced beef")
        self.assertEqual(enhanced.candidates_considered, 1)


if __name__ == "__main__":
    unittest.main()
