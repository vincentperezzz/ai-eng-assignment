"""
Step 3: Enhanced Recipe Generation with Attribution

This module generates enhanced recipes with full citation tracking.
It combines modified recipes with attribution information to create
comprehensive enhanced recipe objects.
"""

from collections import OrderedDict
from datetime import datetime
from typing import Any, Dict, List, Optional

from loguru import logger

from .models import (
    ChangeRecord,
    EnhancedRecipe,
    EnhancementSummary,
    ModificationApplied,
    ModificationObject,
    Recipe,
    Review,
    ReviewModificationGroup,
    SourceReview,
)


class EnhancedRecipeGenerator:
    """Generates enhanced recipes with full citation tracking and attribution."""

    def __init__(self, pipeline_version: str = "1.1.0"):
        self.pipeline_version = pipeline_version
        logger.info(f"Initialized EnhancedRecipeGenerator v{pipeline_version}")

    def create_source_review(self, review: Review) -> SourceReview:
        return SourceReview(
            text=review.text, reviewer=review.username, rating=review.rating
        )

    def create_modification_record(
        self,
        modification: ModificationObject,
        source_review: Review,
        change_records: Optional[List[ChangeRecord]] = None,
        status: str = "applied",
        unapplied_reason: Optional[str] = None,
    ) -> ModificationApplied:
        return ModificationApplied(
            source_review=self.create_source_review(source_review),
            modification_type=modification.modification_type,
            reasoning=modification.reasoning,
            evidence=modification.evidence,
            changes_made=change_records or [],
            status=status,  # type: ignore[arg-type]
            unapplied_reason=unapplied_reason,
        )

    def create_modification_applied(
        self,
        modification: ModificationObject,
        source_review: Review,
        change_records: List[ChangeRecord],
    ) -> ModificationApplied:
        """Backward-compatible helper for applied modifications."""
        return self.create_modification_record(
            modification,
            source_review,
            change_records=change_records,
            status="applied",
        )

    def group_modifications_by_review(
        self, modifications: List[ModificationApplied]
    ) -> List[ReviewModificationGroup]:
        grouped: OrderedDict[str, ReviewModificationGroup] = OrderedDict()

        for record in modifications:
            key = " ".join(record.source_review.text.split()).strip().lower()
            if key not in grouped:
                grouped[key] = ReviewModificationGroup(
                    source_review=record.source_review,
                    modifications=[],
                )
            grouped[key].modifications.append(record)

        return list(grouped.values())

    def calculate_enhancement_summary(
        self, modifications_applied: List[ModificationApplied]
    ) -> EnhancementSummary:
        applied = [mod for mod in modifications_applied if mod.status == "applied"]
        total_changes = sum(len(mod.changes_made) for mod in applied)
        change_types = list(set(mod.modification_type for mod in applied))

        impact_descriptions = [mod.reasoning for mod in applied if mod.reasoning]
        expected_impact = "; ".join(impact_descriptions[:3])
        if len(impact_descriptions) > 3:
            expected_impact += (
                f" (and {len(impact_descriptions) - 3} more improvements)"
            )

        return EnhancementSummary(
            total_changes=total_changes,
            change_types=change_types,
            expected_impact=expected_impact
            or "Community-validated recipe improvements",
        )

    def generate_enhanced_recipe(
        self,
        original_recipe: Recipe,
        modified_recipe: Recipe,
        modification: ModificationObject,
        source_review: Review,
        change_records: List[ChangeRecord],
    ) -> EnhancedRecipe:
        modification_applied = self.create_modification_applied(
            modification, source_review, change_records
        )
        return self.generate_enhanced_recipe_from_records(
            original_recipe, modified_recipe, [modification_applied]
        )

    def generate_enhanced_recipe_from_modifications(
        self,
        original_recipe: Recipe,
        modified_recipe: Recipe,
        modifications_with_reviews: List[
            tuple[ModificationObject, Review, List[ChangeRecord]]
        ],
    ) -> EnhancedRecipe:
        records = [
            self.create_modification_applied(modification, source_review, change_records)
            for modification, source_review, change_records in modifications_with_reviews
        ]
        return self.generate_enhanced_recipe_from_records(
            original_recipe, modified_recipe, records
        )

    def generate_enhanced_recipe_from_records(
        self,
        original_recipe: Recipe,
        modified_recipe: Recipe,
        modification_records: List[ModificationApplied],
        max_reviews: Optional[int] = None,
        candidates_considered: Optional[int] = None,
    ) -> EnhancedRecipe:
        logger.info(
            f"Generating enhanced recipe for: {original_recipe.title} "
            f"from {len(modification_records)} modification record(s)"
        )

        enhancement_summary = self.calculate_enhancement_summary(modification_records)
        modifications_by_review = self.group_modifications_by_review(modification_records)

        enhanced_recipe = EnhancedRecipe(
            recipe_id=f"{original_recipe.recipe_id}_enhanced",
            original_recipe_id=original_recipe.recipe_id,
            title=f"{original_recipe.title} (Community Enhanced)",
            ingredients=modified_recipe.ingredients,
            instructions=modified_recipe.instructions,
            modifications_applied=modification_records,
            modifications_by_review=modifications_by_review,
            enhancement_summary=enhancement_summary,
            description=original_recipe.description,
            servings=modified_recipe.servings,
            prep_time=getattr(original_recipe, "prep_time", None),
            cook_time=getattr(original_recipe, "cook_time", None),
            total_time=getattr(original_recipe, "total_time", None),
            created_at=datetime.now().isoformat(),
            pipeline_version=self.pipeline_version,
            max_reviews=max_reviews,
            candidates_considered=candidates_considered,
        )

        applied_count = sum(1 for mod in modification_records if mod.status == "applied")
        logger.info(
            f"Generated enhanced recipe with {enhancement_summary.total_changes} changes "
            f"from {applied_count} applied / {len(modification_records)} total modifications "
            f"across {len(modifications_by_review)} review group(s)"
        )

        return enhanced_recipe

    def generate_comparison_data(
        self, original_recipe: Recipe, enhanced_recipe: EnhancedRecipe
    ) -> Dict[str, Any]:
        applied = [
            mod for mod in enhanced_recipe.modifications_applied if mod.status == "applied"
        ]
        return {
            "original": {
                "title": original_recipe.title,
                "ingredients": original_recipe.ingredients,
                "instructions": original_recipe.instructions,
                "servings": original_recipe.servings,
            },
            "enhanced": {
                "title": enhanced_recipe.title,
                "ingredients": enhanced_recipe.ingredients,
                "instructions": enhanced_recipe.instructions,
                "servings": enhanced_recipe.servings,
            },
            "changes": {
                "total_modifications": len(applied),
                "total_changes": enhanced_recipe.enhancement_summary.total_changes,
                "change_types": enhanced_recipe.enhancement_summary.change_types,
                "expected_impact": enhanced_recipe.enhancement_summary.expected_impact,
            },
            "citations": [
                {
                    "reviewer": mod.source_review.reviewer,
                    "rating": mod.source_review.rating,
                    "modification_type": mod.modification_type,
                    "reasoning": mod.reasoning,
                    "status": mod.status,
                    "unapplied_reason": mod.unapplied_reason,
                    "changes": [
                        {
                            "type": change.type,
                            "from": change.from_text,
                            "to": change.to_text,
                            "operation": change.operation,
                        }
                        for change in mod.changes_made
                    ],
                }
                for mod in enhanced_recipe.modifications_applied
            ],
            "by_review": [
                {
                    "review_text": group.source_review.text,
                    "modification_count": len(group.modifications),
                    "statuses": [mod.status for mod in group.modifications],
                }
                for group in enhanced_recipe.modifications_by_review
            ],
        }

    def save_enhanced_recipe(
        self, enhanced_recipe: EnhancedRecipe, output_path: str
    ) -> str:
        import json
        import os

        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(enhanced_recipe.model_dump(), f, indent=2, ensure_ascii=False)

        logger.info(f"Saved enhanced recipe to: {output_path}")
        return output_path
