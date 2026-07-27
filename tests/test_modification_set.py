import json
import unittest

from llm_pipeline.models import ModificationEdit, ModificationObject, ModificationSet
from llm_pipeline.modification_conflicts import conflicting_modification_indices
from llm_pipeline.tweak_extractor import TweakExtractor


class ModificationSetParsingTests(unittest.TestCase):
    def test_parse_modification_set_wrapper(self):
        payload = json.dumps(
            {
                "modifications": [
                    {
                        "modification_type": "addition",
                        "reasoning": "Extra egg",
                        "edits": [
                            {
                                "target": "ingredients",
                                "operation": "replace",
                                "find": "2 eggs",
                                "replace": "3 eggs",
                            }
                        ],
                    },
                    {
                        "modification_type": "quantity_adjustment",
                        "reasoning": "Less sugar",
                        "edits": [
                            {
                                "target": "ingredients",
                                "operation": "replace",
                                "find": "1 cup white sugar",
                                "replace": "0.5 cup white sugar",
                            }
                        ],
                    },
                ]
            }
        )

        mods = TweakExtractor._parse_modification_set_payload(payload)
        self.assertEqual(len(mods), 2)
        self.assertEqual(mods[0].modification_type, "addition")
        self.assertEqual(mods[1].modification_type, "quantity_adjustment")

    def test_parse_legacy_single_object_payload(self):
        payload = json.dumps(
            {
                "modification_type": "addition",
                "reasoning": "Extra yolk",
                "edits": [
                    {
                        "target": "ingredients",
                        "operation": "add_after",
                        "find": "2 eggs",
                        "add": "1 egg yolk",
                    }
                ],
            }
        )

        mods = TweakExtractor._parse_modification_set_payload(payload)
        self.assertEqual(len(mods), 1)
        self.assertEqual(mods[0].modification_type, "addition")

    def test_parse_top_level_array_keeps_all_items(self):
        payload = json.dumps(
            [
                {
                    "modification_type": "addition",
                    "reasoning": "Egg",
                    "edits": [
                        {
                            "target": "ingredients",
                            "operation": "replace",
                            "find": "2 eggs",
                            "replace": "3 eggs",
                        }
                    ],
                },
                {
                    "modification_type": "quantity_adjustment",
                    "reasoning": "Sugar",
                    "edits": [
                        {
                            "target": "ingredients",
                            "operation": "replace",
                            "find": "1 cup white sugar",
                            "replace": "0.5 cup white sugar",
                        }
                    ],
                },
            ]
        )

        mods = TweakExtractor._parse_modification_set_payload(payload)
        self.assertEqual(len(mods), 2)

    def test_modification_set_schema_accepts_list(self):
        parsed = ModificationSet(
            modifications=[
                ModificationObject(
                    modification_type="addition",
                    reasoning="Egg",
                    edits=[
                        ModificationEdit(
                            target="ingredients",
                            operation="replace",
                            find="2 eggs",
                            replace="3 eggs",
                        )
                    ],
                )
            ]
        )
        self.assertEqual(len(parsed.modifications), 1)


class ConflictDetectionTests(unittest.TestCase):
    def test_shared_find_target_marks_conflict(self):
        mods = [
            ModificationObject(
                modification_type="quantity_adjustment",
                reasoning="More sugar",
                edits=[
                    ModificationEdit(
                        target="ingredients",
                        operation="replace",
                        find="1 cup white sugar",
                        replace="1.5 cups white sugar",
                    )
                ],
            ),
            ModificationObject(
                modification_type="quantity_adjustment",
                reasoning="Less sugar",
                edits=[
                    ModificationEdit(
                        target="ingredients",
                        operation="replace",
                        find="1 cup white sugar",
                        replace="0.5 cup white sugar",
                    )
                ],
            ),
        ]

        self.assertEqual(conflicting_modification_indices(mods), {0, 1})

    def test_distinct_find_targets_do_not_conflict(self):
        mods = [
            ModificationObject(
                modification_type="addition",
                reasoning="Egg",
                edits=[
                    ModificationEdit(
                        target="ingredients",
                        operation="replace",
                        find="2 eggs",
                        replace="3 eggs",
                    )
                ],
            ),
            ModificationObject(
                modification_type="quantity_adjustment",
                reasoning="Sugar",
                edits=[
                    ModificationEdit(
                        target="ingredients",
                        operation="replace",
                        find="1 cup white sugar",
                        replace="0.5 cup white sugar",
                    )
                ],
            ),
        ]

        self.assertEqual(conflicting_modification_indices(mods), set())


if __name__ == "__main__":
    unittest.main()
