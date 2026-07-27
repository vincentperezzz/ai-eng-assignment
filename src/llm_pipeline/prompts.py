"""
LLM prompts and examples for recipe modification extraction.

This module contains carefully crafted prompts for extracting structured
modifications from user review text.
"""

SYSTEM_PROMPT = """You are an expert recipe analyst. Your job is to extract structured recipe modifications from user reviews.

When a user shares their experience modifying a recipe, you need to:
1. Identify every discrete change they clearly stated
2. Treat multiple tips in one review as separate modifications
   Example: "I added an egg and halved the sugar" -> two modifications (addition + quantity_adjustment)
3. Understand why they made each change
4. Convert each modification into structured edit operations
5. Label whether each tip is tested or untested

You must output valid JSON that matches the ModificationSet schema:
a top-level object with a "modifications" array. Each array item is one discrete tip.

Honesty rules:
- Only extract tips the review clearly states
- Do not invent related tips or guess extras
- If the review states only one tip, return a one-item list
- If the review states no concrete tip, return an empty list

Evidence labels:
- "tested": the reviewer reports they actually made this change (I added / I used / I made with / threw in)
- "untested": preference, wish, or next-time advice (next time / prefer / wish / should try / I would)

Categories:
- "ingredient_substitution": Replacing one ingredient with another
- "quantity_adjustment": Changing amounts of existing ingredients
- "technique_change": Altering cooking method, temperature, time
- "addition": Adding new ingredients or steps
- "removal": Removing ingredients or steps

Edit operations:
- "replace": Find existing text and replace it
- "add_after": Add new text after finding target text
- "remove": Remove text that matches the find pattern

Be precise with text matching - use the exact text from the original recipe when possible."""


EXTRACTION_PROMPT = """Original Recipe:
Title: {title}
Ingredients: {ingredients}
Instructions: {instructions}

User Review: "{review_text}"

Extract the recipe modifications from this review. The user has made changes to improve the recipe.

Output a JSON object with this structure:
{{
    "modifications": [
        {{
            "modification_type": "quantity_adjustment|ingredient_substitution|technique_change|addition|removal",
            "reasoning": "Brief explanation of why this one tip improves the recipe",
            "evidence": "tested|untested",
            "edits": [
                {{
                    "target": "ingredients|instructions",
                    "operation": "replace|add_after|remove",
                    "find": "exact text to find",
                    "replace": "replacement text (for replace operations)",
                    "add": "text to add (for add_after operations)"
                }}
            ]
        }}
    ]
}}

Rules:
- One array item per discrete tip
- evidence=tested when the reviewer did the change; untested for next-time/prefer/wish
- Return an empty modifications list when there is no concrete tip"""

FEW_SHOT_EXAMPLES = [
    {
        "review": "I used a half cup of sugar and one-and-a-half cups of brown sugar instead of the recipe amounts. Made the cookies much more chewy and flavorful!",
        "ingredients": [
            "1 cup butter, softened",
            "1 cup white sugar",
            "1 cup packed brown sugar",
            "2 eggs",
        ],
        "expected_output": {
            "modifications": [
                {
                    "modification_type": "quantity_adjustment",
                    "reasoning": "Makes cookies more chewy and flavorful by increasing brown sugar ratio",
                    "evidence": "tested",
                    "edits": [
                        {
                            "target": "ingredients",
                            "operation": "replace",
                            "find": "1 cup white sugar",
                            "replace": "0.5 cup white sugar",
                        },
                        {
                            "target": "ingredients",
                            "operation": "replace",
                            "find": "1 cup packed brown sugar",
                            "replace": "1.5 cups packed brown sugar",
                        },
                    ],
                }
            ]
        },
    },
    {
        "review": "I added a teaspoon of cream of tartar to the batter and omitted the water. The cookies retained their shape and didn't spread when baked.",
        "ingredients": [
            "1 teaspoon baking soda",
            "2 teaspoons hot water",
            "0.5 teaspoon salt",
        ],
        "expected_output": {
            "modifications": [
                {
                    "modification_type": "addition",
                    "reasoning": "Helps cookies retain shape and prevents spreading during baking",
                    "evidence": "tested",
                    "edits": [
                        {
                            "target": "ingredients",
                            "operation": "add_after",
                            "find": "0.5 teaspoon salt",
                            "add": "1 teaspoon cream of tartar",
                        },
                        {
                            "target": "ingredients",
                            "operation": "remove",
                            "find": "2 teaspoons hot water",
                        },
                    ],
                }
            ]
        },
    },
    {
        "review": "I used 1 tsp of salt instead of 1/2 tsp and omitted the nuts. Much better flavor without being too salty.",
        "ingredients": ["0.5 teaspoon salt", "1 cup chopped walnuts"],
        "expected_output": {
            "modifications": [
                {
                    "modification_type": "quantity_adjustment",
                    "reasoning": "Improves flavor balance without making cookies too salty",
                    "evidence": "tested",
                    "edits": [
                        {
                            "target": "ingredients",
                            "operation": "replace",
                            "find": "0.5 teaspoon salt",
                            "replace": "1 teaspoon salt",
                        },
                        {
                            "target": "ingredients",
                            "operation": "remove",
                            "find": "1 cup chopped walnuts",
                        },
                    ],
                }
            ]
        },
    },
    {
        "review": "I baked them at 375 degrees instead of 350 for about 8-9 minutes. They came out perfectly crispy on the edges.",
        "instructions": [
            "Preheat the oven to 350 degrees F (175 degrees C)",
            "Bake in the preheated oven until edges are nicely browned, about 10 minutes",
        ],
        "expected_output": {
            "modifications": [
                {
                    "modification_type": "technique_change",
                    "reasoning": "Higher temperature and shorter time creates crispier edges",
                    "evidence": "tested",
                    "edits": [
                        {
                            "target": "instructions",
                            "operation": "replace",
                            "find": "350 degrees F",
                            "replace": "375 degrees F",
                        },
                        {
                            "target": "instructions",
                            "operation": "replace",
                            "find": "about 10 minutes",
                            "replace": "about 8-9 minutes",
                        },
                    ],
                }
            ]
        },
    },
]


def build_few_shot_prompt(
    review_text: str, title: str, ingredients: list, instructions: list
) -> str:
    """Build a few-shot prompt with examples for better extraction accuracy."""

    examples_text = "\n\n".join(
        [
            f"Example {i + 1}:\n"
            f'Review: "{example["review"]}"\n'
            f"Output: {example['expected_output']}"
            for i, example in enumerate(
                FEW_SHOT_EXAMPLES[:2]
            )  # Use 2 most relevant examples
        ]
    )

    prompt = f"""{SYSTEM_PROMPT}

Here are some examples of how to extract modifications:

{examples_text}

Now extract from this review:

{
        EXTRACTION_PROMPT.format(
            title=title,
            ingredients=ingredients,
            instructions=instructions,
            review_text=review_text,
        )
    }"""

    return prompt


def build_simple_prompt(
    review_text: str, title: str, ingredients: list, instructions: list
) -> str:
    """Build a simple prompt without examples for faster processing."""
    return f"""{SYSTEM_PROMPT}

Original Recipe:
Title: {title}
Ingredients: {ingredients}
Instructions: {instructions}

User Review: "{review_text}"

Extract ALL discrete recipe modifications clearly stated in this review.

Output a JSON object with this structure:
{{
    "modifications": [
        {{
            "modification_type": "quantity_adjustment|ingredient_substitution|technique_change|addition|removal",
            "reasoning": "Brief explanation of why this one tip improves the recipe",
            "evidence": "tested|untested",
            "edits": [
                {{
                    "target": "ingredients|instructions",
                    "operation": "replace|add_after|remove",
                    "find": "exact text to find",
                    "replace": "replacement text (for replace operations)",
                    "add": "text to add (for add_after operations)"
                }}
            ]
        }}
    ]
}}

Rules:
- One array item per discrete tip (do not merge unrelated tips into one object)
- Only include tips clearly stated in the review text
- Do not invent tips
- evidence=tested when the reviewer says they actually did the change
- evidence=untested for next-time / prefer / wish / should-try language
- Focus on concrete tips; return an empty modifications list for praise-only text"""

