"""Tests for tip consensus (support / oppose) and residual same-line amount lock."""

import unittest

from llm_pipeline.ledger import RecipeLedger, modification_id_for, review_id_for
from llm_pipeline.models import ModificationEdit, ModificationObject, Recipe, Review
from llm_pipeline.tip_consensus import score_tip_consensus


def make_recipe(ingredients=None, instructions=None, servings=None):
    return Recipe(
        recipe_id="t",
        title="Test Recipe",
        ingredients=ingredients if ingredients is not None else [],
        instructions=instructions if instructions is not None else [],
        servings=servings,
    )


class SameLineAmountLockTests(unittest.TestCase):
    """Residual gap: same ingredient words, different amounts — later tip must not win."""

    def test_later_amount_change_on_already_rewritten_line_is_superseded(self):
        recipe = make_recipe(
            ingredients=["1 cup white sugar", "2 eggs"],
            instructions=["Mix."],
            servings="24",
        )
        ledger = RecipeLedger(recipe)
        review_a = Review(text="I used half the white sugar and loved it.", rating=5, username="Ann")
        review_b = Review(text="I used 0.75 cup white sugar instead.", rating=4, username="Bob")

        mod_a = ModificationObject(
            modification_type="quantity_adjustment",
            reasoning="Less sweet",
            evidence="tested",
            edits=[
                ModificationEdit(
                    target="ingredients",
                    operation="replace",
                    find="1 cup white sugar",
                    replace="0.5 cup white sugar",
                )
            ],
        )
        mod_b = ModificationObject(
            modification_type="quantity_adjustment",
            reasoning="Slightly less sweet",
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
        self.assertEqual(rejected_b[0].reason, "superseded")
        self.assertIn("0.5 cup white sugar", ledger.document.texts("ingredients"))
        self.assertNotIn("0.75 cup white sugar", ledger.document.texts("ingredients"))
        self.assertTrue(ledger.verify().deterministic)


class TipConsensusTests(unittest.TestCase):
    def test_strong_opposition_holds_tip(self):
        tip_review = Review(
            text="I swapped in brown sugar and the cookies were chewier.",
            rating=3,
            username="LowStar",
        )
        oppose = Review(
            text="Brown sugar makes it lumpy — don't try it.",
            rating=5,
            username="Warn",
        )
        support = Review(
            text="Yea brown sugar tastes better, agree with that tip.",
            rating=4,
            username="Fan",
        )
        modification = ModificationObject(
            modification_type="ingredient_substitution",
            reasoning="Brown sugar for chew",
            evidence="tested",
            edits=[
                ModificationEdit(
                    target="ingredients",
                    operation="replace",
                    find="1 cup white sugar",
                    replace="1 cup packed brown sugar",
                )
            ],
        )

        consensus = score_tip_consensus(
            modification, tip_review, [tip_review, oppose, support]
        )
        # One oppose + one support → oppose >= support → held
        self.assertEqual(consensus.decision, "held_for_opposition")
        self.assertEqual(consensus.oppose_count, 1)
        self.assertEqual(consensus.support_count, 1)

    def test_support_without_opposition_allows_apply(self):
        tip_review = Review(
            text="I used brown sugar instead of white — great chew.",
            rating=5,
            username="Author",
        )
        echo = Review(
            text="Yea brown sugar tastes better, me too.",
            rating=4,
            username="Echo",
        )
        modification = ModificationObject(
            modification_type="ingredient_substitution",
            reasoning="Brown sugar for chew",
            evidence="tested",
            edits=[
                ModificationEdit(
                    target="ingredients",
                    operation="replace",
                    find="1 cup white sugar",
                    replace="1 cup packed brown sugar",
                )
            ],
        )
        consensus = score_tip_consensus(modification, tip_review, [tip_review, echo])
        self.assertEqual(consensus.decision, "apply_allowed")
        self.assertEqual(consensus.support_count, 1)
        self.assertEqual(consensus.oppose_count, 0)

    def test_unrelated_comments_do_not_count(self):
        tip_review = Review(text="I added an egg yolk.", rating=5, username="A")
        other = Review(text="These were delicious, baked them for a party.", rating=5, username="B")
        modification = ModificationObject(
            modification_type="addition",
            reasoning="Richer dough",
            evidence="tested",
            edits=[
                ModificationEdit(
                    target="ingredients",
                    operation="add_after",
                    find="2 eggs",
                    add="1 egg yolk",
                )
            ],
        )
        consensus = score_tip_consensus(modification, tip_review, [tip_review, other])
        self.assertEqual(consensus.decision, "insufficient_signal")


if __name__ == "__main__":
    unittest.main()
