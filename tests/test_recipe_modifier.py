import unittest

from llm_pipeline.models import ModificationEdit, ModificationObject, Recipe
from llm_pipeline.recipe_modifier import RecipeModifier


class RecipeModifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.modifier = RecipeModifier()

    def test_replace_substring_within_instruction_line(self) -> None:
        edit = ModificationEdit(
            target="instructions",
            operation="replace",
            find="about 10 minutes",
            replace="about 8-9 minutes",
        )
        instructions = [
            "Bake in the preheated oven until edges are nicely browned, about 10 minutes."
        ]

        updated, changes = self.modifier.apply_edit(edit, instructions)

        self.assertEqual(
            updated[0],
            "Bake in the preheated oven until edges are nicely browned, about 8-9 minutes.",
        )
        self.assertEqual(len(changes), 1)

    def test_replace_fuzzy_ingredient_line_uses_matched_content(self) -> None:
        edit = ModificationEdit(
            target="ingredients",
            operation="replace",
            find="1 cup butter softened",
            replace="1 cup browned butter, cooled",
        )
        ingredients = ["1 cup butter, softened"]

        updated, changes = self.modifier.apply_edit(edit, ingredients)

        self.assertEqual(updated[0], "1 cup browned butter, cooled")
        self.assertEqual(len(changes), 1)

    def test_servings_replace_keeps_yield_consistent(self) -> None:
        recipe = Recipe(
            recipe_id="10813",
            title="Cookies",
            ingredients=["2 eggs"],
            instructions=["Drop spoonfuls of dough onto sheets."],
            servings="48",
        )
        modification = ModificationObject(
            modification_type="technique_change",
            reasoning="Scoop makes fewer larger cookies",
            evidence="tested",
            edits=[
                ModificationEdit(
                    target="instructions",
                    operation="replace",
                    find="Drop spoonfuls of dough onto sheets.",
                    replace="Drop dough with an ice cream scoop to make 16 big cookies.",
                ),
                ModificationEdit(
                    target="servings",
                    operation="replace",
                    find="48",
                    replace="16",
                ),
            ],
        )

        updated, changes = self.modifier.apply_modification(recipe, modification)

        self.assertEqual(updated.servings, "16")
        self.assertTrue(any(c.type == "servings" for c in changes))
        self.assertIn("16 big cookies", updated.instructions[0])


if __name__ == "__main__":
    unittest.main()
