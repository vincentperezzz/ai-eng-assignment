"""Tests for RecipeLedger: compare-and-swap edits, replay verification, and blame.

These are the tests that prove Defect A (fabricated attribution / silent
whole-line clobbering, documented in ASSESSMENT.md §7) is
actually fixed rather than just re-described. See that section for the full
before/after evidence from the live sweep.
"""

import unittest

from llm_pipeline.ledger import RecipeLedger, modification_id_for, review_id_for
from llm_pipeline.models import ModificationEdit, ModificationObject, Recipe, Review


def make_recipe(ingredients=None, instructions=None, servings=None):
    return Recipe(
        recipe_id="t",
        title="Test Recipe",
        ingredients=ingredients if ingredients is not None else [],
        instructions=instructions if instructions is not None else [],
        servings=servings,
    )


class RegressionClobberTests(unittest.TestCase):
    """Case 1: the exact clobber bug from enhanced_10813_best-chocolate-chip-cookies.json.

    Tip A (from one review) rewrites a whole ingredient line. Tip B (from a
    later, different review) was authored against the *original* recipe and
    targets the same original text with a different value. The inherited
    RecipeModifier would silently overwrite tip A's landed change; the ledger
    must instead reject tip B as a stale read.
    """

    def test_second_tip_authored_against_original_is_rejected_not_applied(self):
        recipe = make_recipe(
            ingredients=[
                "1 cup white sugar",
                "1 cup packed brown sugar",
                "2 eggs",
            ],
            instructions=["Mix it."],
            servings="48",
        )
        ledger = RecipeLedger(recipe)

        review_a = Review(text="I used superfine sugar instead, great cookies.", rating=5, username="Jane")
        review_b = Review(
            text="These are awesome cookies. I followed the advice and used 0.75 cup white sugar instead.",
            rating=4,
            username="Bob",
        )

        mod_a = ModificationObject(
            modification_type="ingredient_substitution",
            reasoning="Superfine sugar dissolves better",
            evidence="tested",
            edits=[
                ModificationEdit(
                    target="ingredients",
                    operation="replace",
                    find="1 cup white sugar",
                    replace="1 cup superfine sugar",
                )
            ],
        )
        # Authored independently against the ORIGINAL recipe text -- has no
        # idea tip A already rewrote this line.
        mod_b = ModificationObject(
            modification_type="quantity_adjustment",
            reasoning="Less sugar reduces sweetness",
            evidence="tested",
            edits=[
                ModificationEdit(
                    target="ingredients",
                    operation="replace",
                    find="1 cup white sugar",
                    replace="0.75 cup white sugar",
                )
            ],
        )

        committed_a, rejected_a = ledger.apply_modification(
            mod_a, modification_id_for(review_a, 0), review_id_for(review_a)
        )
        committed_b, rejected_b = ledger.apply_modification(
            mod_b, modification_id_for(review_b, 0), review_id_for(review_b)
        )

        self.assertEqual(len(committed_a), 1)
        self.assertEqual(rejected_a, [])

        self.assertEqual(committed_b, [])
        self.assertEqual(len(rejected_b), 1)
        self.assertIn(rejected_b[0].reason, {"superseded", "no_op"})

        # Tip A's edit is present in the final ingredients.
        self.assertIn("1 cup superfine sugar", ledger.document.texts("ingredients"))
        # Tip B never landed -- the recipe was not silently rewritten again.
        self.assertNotIn("0.75 cup white sugar", ledger.document.texts("ingredients"))
        self.assertNotIn("1 cup white sugar", ledger.document.texts("ingredients"))

        verification = ledger.verify()
        self.assertTrue(verification.deterministic)
        self.assertEqual(verification.mismatches, [])


class ReplayDeterminismTests(unittest.TestCase):
    """Case 2: replaying a mixed sequence of edits reproduces the output exactly."""

    def test_mixed_sequence_replays_deterministically(self):
        recipe = make_recipe(
            ingredients=["1 cup flour", "2 eggs", "1 cup white sugar"],
            instructions=["Mix everything.", "Bake for 20 minutes."],
            servings="24",
        )
        ledger = RecipeLedger(recipe)
        review = Review(text="Made several changes and they all worked great.", rating=5, username="Sam")
        review_id = review_id_for(review)

        replace_mod = ModificationObject(
            modification_type="quantity_adjustment",
            reasoning="Less sweet",
            evidence="tested",
            edits=[
                ModificationEdit(
                    target="ingredients", operation="replace",
                    find="1 cup white sugar", replace="0.5 cup white sugar",
                )
            ],
        )
        add_mod = ModificationObject(
            modification_type="addition",
            reasoning="Extra flavor",
            evidence="tested",
            edits=[
                ModificationEdit(
                    target="instructions", operation="add_after",
                    find="Mix everything.", add="Add a pinch of cinnamon.",
                )
            ],
        )
        remove_mod = ModificationObject(
            modification_type="removal",
            reasoning="Not needed",
            evidence="tested",
            edits=[ModificationEdit(target="ingredients", operation="remove", find="2 eggs")],
        )
        servings_mod = ModificationObject(
            modification_type="quantity_adjustment",
            reasoning="Made a bigger batch",
            evidence="tested",
            edits=[ModificationEdit(target="servings", operation="replace", find="24", replace="36")],
        )

        for index, mod in enumerate([replace_mod, add_mod, remove_mod, servings_mod]):
            committed, rejected = ledger.apply_modification(
                mod, modification_id_for(review, index), review_id
            )
            self.assertEqual(rejected, [])
            self.assertEqual(len(committed), 1)

        verification = ledger.verify()
        self.assertTrue(verification.deterministic)
        self.assertEqual(verification.mismatches, [])
        self.assertEqual(verification.entries_replayed, 4)


class TamperDetectionTests(unittest.TestCase):
    """Case 3: verify() must catch out-of-band edits that bypass the ledger."""

    def test_out_of_band_mutation_is_detected(self):
        recipe = make_recipe(ingredients=["1 cup flour", "2 eggs"], instructions=["Mix it."])
        ledger = RecipeLedger(recipe)
        review = Review(text="I added vanilla.", rating=5, username="Sam")

        mod = ModificationObject(
            modification_type="addition",
            reasoning="Adds flavor",
            evidence="tested",
            edits=[
                ModificationEdit(
                    target="ingredients", operation="add_after",
                    find="2 eggs", add="1 tsp vanilla",
                )
            ],
        )
        committed, rejected = ledger.apply_modification(
            mod, modification_id_for(review, 0), review_id_for(review)
        )
        self.assertEqual(len(committed), 1)
        self.assertEqual(rejected, [])

        sanity = ledger.verify()
        self.assertTrue(sanity.deterministic)

        # Simulate an out-of-band edit that never went through the ledger.
        from llm_pipeline.ledger import Line

        ledger.document.sections["ingredients"].append(Line("ing:tampered", "1 stray line"))

        tampered = ledger.verify()
        self.assertFalse(tampered.deterministic)
        self.assertNotEqual(tampered.mismatches, [])


class BlameCorrectnessTests(unittest.TestCase):
    """Case 4: per-line blame attributes changed lines to the right tip/reviewer."""

    def test_blame_attributes_lines_to_correct_reviewer(self):
        recipe = make_recipe(
            ingredients=["1 cup flour", "2 eggs", "1 cup white sugar"],
            instructions=["Mix it."],
        )
        ledger = RecipeLedger(recipe)

        review_jane = Review(text="I added an egg yolk for chewiness.", rating=5, username="Jane")
        review_bob = Review(text="I halved the sugar and it was still great.", rating=4, username="Bob")

        mod_jane = ModificationObject(
            modification_type="addition",
            reasoning="Chewier cookies",
            evidence="tested",
            edits=[
                ModificationEdit(
                    target="ingredients", operation="add_after",
                    find="2 eggs", add="1 egg yolk",
                )
            ],
        )
        mod_bob = ModificationObject(
            modification_type="quantity_adjustment",
            reasoning="Less sweet",
            evidence="tested",
            edits=[
                ModificationEdit(
                    target="ingredients", operation="replace",
                    find="1 cup white sugar", replace="0.5 cup white sugar",
                )
            ],
        )

        jane_id = modification_id_for(review_jane, 0)
        bob_id = modification_id_for(review_bob, 0)
        ledger.apply_modification(mod_jane, jane_id, review_id_for(review_jane))
        ledger.apply_modification(mod_bob, bob_id, review_id_for(review_bob))

        reviewer_by_modification = {jane_id: review_jane.username, bob_id: review_bob.username}
        blame_lines = ledger.blame(reviewer_by_modification)
        blame_by_text = {line.text: line for line in blame_lines}

        self.assertEqual(blame_by_text["1 cup flour"].origin, "original")
        self.assertEqual(blame_by_text["1 cup flour"].modification_ids, [])
        self.assertEqual(blame_by_text["1 cup flour"].reviewers, [])

        self.assertEqual(blame_by_text["1 egg yolk"].origin, "community")
        self.assertEqual(blame_by_text["1 egg yolk"].modification_ids, [jane_id])
        self.assertEqual(blame_by_text["1 egg yolk"].reviewers, ["Jane"])

        self.assertEqual(blame_by_text["0.5 cup white sugar"].origin, "community")
        self.assertEqual(blame_by_text["0.5 cup white sugar"].modification_ids, [bob_id])
        self.assertEqual(blame_by_text["0.5 cup white sugar"].reviewers, ["Bob"])


class GuardedFuzzyMatchTests(unittest.TestCase):
    """Case 5: the guard must not let 'white sugar' match a 'brown sugar' line."""

    def test_white_sugar_find_does_not_match_brown_sugar_line(self):
        recipe = make_recipe(
            ingredients=["1 cup white sugar", "1 cup packed brown sugar"],
            instructions=[],
        )
        ledger = RecipeLedger(recipe)

        lines = ledger.document.sections["ingredients"]
        match = ledger._fuzzy_match(lines, "1 cup white sugar")

        self.assertIsNotNone(match)
        index, line, score = match
        # Must resolve to the white sugar line, never the brown sugar line,
        # even though SequenceMatcher alone scores that pair ~0.75.
        self.assertEqual(line.text, "1 cup white sugar")
        self.assertNotEqual(line.text, "1 cup packed brown sugar")

    def test_replace_targeting_white_sugar_never_lands_on_brown_sugar_line(self):
        recipe = make_recipe(
            ingredients=["1 cup packed brown sugar", "1 cup white sugar"],
            instructions=[],
        )
        ledger = RecipeLedger(recipe)
        review = Review(text="I halved the white sugar.", rating=5, username="Sam")

        mod = ModificationObject(
            modification_type="quantity_adjustment",
            reasoning="Less sweet",
            evidence="tested",
            edits=[
                ModificationEdit(
                    target="ingredients", operation="replace",
                    find="1 cup white sugar", replace="0.5 cup white sugar",
                )
            ],
        )
        committed, rejected = ledger.apply_modification(
            mod, modification_id_for(review, 0), review_id_for(review)
        )
        self.assertEqual(len(committed), 1)
        self.assertEqual(rejected, [])
        self.assertIn("1 cup packed brown sugar", ledger.document.texts("ingredients"))
        self.assertIn("0.5 cup white sugar", ledger.document.texts("ingredients"))


class AddAfterAnchorSurvivesRewriteTests(unittest.TestCase):
    """Case 6: an add_after anchor quoting the pre-rewrite text still lands correctly."""

    def test_anchor_targeting_original_text_survives_a_prior_rewrite(self):
        recipe = make_recipe(
            ingredients=["1 cup white sugar", "2 eggs"],
            instructions=["Mix it."],
            servings="48",
        )
        ledger = RecipeLedger(recipe)

        review_a = Review(text="I used superfine sugar instead.", rating=5, username="Jane")
        review_b = Review(text="I added cream of tartar after the white sugar.", rating=5, username="Bob")

        mod_a = ModificationObject(
            modification_type="ingredient_substitution",
            reasoning="Finer texture",
            evidence="tested",
            edits=[
                ModificationEdit(
                    target="ingredients", operation="replace",
                    find="1 cup white sugar", replace="1 cup superfine sugar",
                )
            ],
        )
        # This add_after quotes the ORIGINAL (pre-rewrite) line text as its anchor.
        mod_b = ModificationObject(
            modification_type="addition",
            reasoning="Helps cookies hold shape",
            evidence="tested",
            edits=[
                ModificationEdit(
                    target="ingredients", operation="add_after",
                    find="1 cup white sugar", add="1 tsp cream of tartar",
                )
            ],
        )

        committed_a, rejected_a = ledger.apply_modification(
            mod_a, modification_id_for(review_a, 0), review_id_for(review_a)
        )
        committed_b, rejected_b = ledger.apply_modification(
            mod_b, modification_id_for(review_b, 0), review_id_for(review_b)
        )

        self.assertEqual(len(committed_a), 1)
        self.assertEqual(rejected_a, [])
        self.assertEqual(len(committed_b), 1)
        self.assertEqual(rejected_b, [])
        self.assertTrue(committed_b[0].anchor_superseded)

        ingredients = ledger.document.texts("ingredients")
        # Insertion still lands right after the (now-rewritten) sugar line.
        self.assertEqual(
            ingredients,
            ["1 cup superfine sugar", "1 tsp cream of tartar", "2 eggs"],
        )

        verification = ledger.verify()
        self.assertTrue(verification.deterministic)
        self.assertEqual(verification.mismatches, [])


if __name__ == "__main__":
    unittest.main()
