"""
LLM Analysis Pipeline - Main Orchestrator

This module coordinates the complete 3-step pipeline:
1. Extract modifications from reviews
2. Apply modifications to recipes
3. Generate enhanced recipes with attribution

Processes recipe data from scraped JSON files and outputs enhanced recipes.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

from .env_loader import load_project_env
from .enhanced_recipe_generator import EnhancedRecipeGenerator
from .ledger import RecipeDocument, RecipeLedger, modification_id_for, review_id_for
from .models import (
    ChangeRecord,
    EnhancedRecipe,
    ModificationApplied,
    ModificationObject,
    Provenance,
    Recipe,
    Review,
)
from .recipe_modifier import RecipeModifier
from .tip_consensus import annotate_extractions_with_consensus
from .tip_eligibility import select_candidate_reviews
from .tweak_extractor import TweakExtractor

# LedgerEntry.section -> ChangeRecord.type
_SECTION_TO_CHANGE_TYPE = {
    "ingredients": "ingredient",
    "instructions": "instruction",
    "servings": "servings",
}


class LLMAnalysisPipeline:
    """Complete pipeline for analyzing recipes and generating enhanced versions."""

    def __init__(
        self,
        openai_api_key: Optional[str] = None,
        output_dir: str = "data/enhanced",
        pipeline_version: str = "1.2.0",
        tweak_extractor: Optional[TweakExtractor] = None,
        recipe_modifier: Optional[RecipeModifier] = None,
        enhanced_generator: Optional[EnhancedRecipeGenerator] = None,
    ):
        """
        Initialize the complete LLM Analysis Pipeline.

        Args:
            openai_api_key: OpenAI API key (loads from env if not provided)
            output_dir: Directory to save enhanced recipes
            pipeline_version: Version identifier for tracking
        """
        # Load environment variables
        load_project_env()

        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Initialize pipeline components
        self.tweak_extractor = tweak_extractor or TweakExtractor(api_key=openai_api_key)
        self.recipe_modifier = recipe_modifier or RecipeModifier()
        self.enhanced_generator = enhanced_generator or EnhancedRecipeGenerator(
            pipeline_version=pipeline_version
        )

        logger.info(f"Initialized LLM Analysis Pipeline v{pipeline_version}")
        logger.info(f"Output directory: {self.output_dir}")

    def load_recipe_data(self, file_path: str) -> Dict[str, Any]:
        """
        Load recipe data from JSON file.

        Args:
            file_path: Path to recipe JSON file

        Returns:
            Recipe data dictionary
        """
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def parse_recipe_data(self, recipe_data: Dict[str, Any]) -> Recipe:
        """
        Parse raw recipe data into Recipe object.

        Args:
            recipe_data: Raw recipe data from JSON

        Returns:
            Recipe object
        """
        return Recipe(
            recipe_id=recipe_data.get("recipe_id", "unknown"),
            title=recipe_data.get("title", "Unknown Recipe"),
            ingredients=recipe_data.get("ingredients", []),
            instructions=recipe_data.get("instructions", []),
            description=recipe_data.get("description"),
            servings=recipe_data.get("servings"),
            rating=recipe_data.get("rating"),
        )

    def parse_reviews_data(self, recipe_data: Dict[str, Any]) -> List[Review]:
        """
        Parse raw review data into Review objects.

        Args:
            recipe_data: Raw recipe data containing reviews

        Returns:
            List of Review objects
        """
        def normalize_review_text(text: str) -> str:
            return " ".join(text.split()).strip().lower()

        combined_reviews: dict[str, Review] = {}

        for review_data in recipe_data.get("featured_tweaks", []):
            if not review_data.get("text"):
                continue

            review = Review(
                text=review_data["text"],
                rating=review_data.get("rating"),
                username=review_data.get("username"),
                has_modification=review_data.get("has_modification", True),
                is_featured=True,
            )
            combined_reviews[normalize_review_text(review.text)] = review

        for review_data in recipe_data.get("reviews", []):
            if not review_data.get("text"):
                continue

            normalized_text = normalize_review_text(review_data["text"])
            existing_review = combined_reviews.get(normalized_text)

            if existing_review:
                existing_review.rating = existing_review.rating or review_data.get("rating")
                existing_review.username = existing_review.username or review_data.get("username")
                existing_review.has_modification = (
                    existing_review.has_modification
                    or review_data.get("has_modification", False)
                )
                continue

            combined_reviews[normalized_text] = Review(
                text=review_data["text"],
                rating=review_data.get("rating"),
                username=review_data.get("username"),
                has_modification=review_data.get("has_modification", False),
                is_featured=False,
            )

        return sorted(
            combined_reviews.values(),
            key=lambda review: (
                not review.is_featured,
                -(review.rating or 0),
            ),
        )

    def process_single_recipe(
        self,
        recipe_file: str,
        save_output: bool = True,
        max_reviews: Optional[int] = None,
    ) -> Optional[EnhancedRecipe]:
        """
        Process a single recipe through the complete pipeline.

        Args:
            recipe_file: Path to recipe JSON file
            save_output: Whether to save the enhanced recipe

        Returns:
            EnhancedRecipe if successful, None otherwise
        """
        try:
            logger.info(f"Processing recipe file: {recipe_file}")

            # Step 0: Load and parse data
            recipe_data = self.load_recipe_data(recipe_file)
            recipe = self.parse_recipe_data(recipe_data)
            reviews = self.parse_reviews_data(recipe_data)

            logger.info(f"Loaded recipe: {recipe.title}")
            hint_count = len([r for r in reviews if r.has_modification])
            logger.info(
                f"Found {len(reviews)} reviews, {hint_count} with scraper modification hints"
            )

            candidate_reviews = select_candidate_reviews(reviews)

            extracted_modifications: List[tuple[ModificationObject, Review]] = []
            if not candidate_reviews:
                logger.warning(
                    "No extraction-candidate reviews found; recording a "
                    "no-op enhancement instead of failing"
                )
            else:
                # Step 1: Extract modifications from soft-eligibility candidates.
                logger.info(
                    f"Step 1: Extracting modifications from {len(candidate_reviews)} "
                    "candidate reviews..."
                )
                extracted_modifications = self.tweak_extractor.extract_modifications(
                    candidate_reviews, recipe, max_reviews=max_reviews
                )

                if not extracted_modifications:
                    logger.warning(
                        "No modifications could be extracted; recording a "
                        "no-op enhancement instead of failing"
                    )
                else:
                    logger.info(
                        f"Successfully extracted {len(extracted_modifications)} "
                        "candidate modifications"
                    )

            # Step 2: Apply modifications transactionally through one shared
            # RecipeLedger for the whole recipe run. The ledger is what makes
            # cross-tip stale-read detection possible: every tip's edits are
            # compare-and-swapped against the *current* document, so a later
            # tip authored against the original recipe cannot silently clobber
            # an earlier tip's already-landed change (see ASSESSMENT.md §7).
            # Rank-then-lock + community consensus: Featured/stars decide order;
            # related agree/disagree comments can hold a tip back; a locked line
            # is never overwritten by a weaker tip.
            logger.info("Step 2: Applying extracted modifications via RecipeLedger...")
            ledger = RecipeLedger(recipe)
            modification_records: List[ModificationApplied] = []
            reviewer_by_modification: Dict[str, Optional[str]] = {}
            review_id_by_key: Dict[str, str] = {}
            modification_index_by_key: Dict[str, int] = {}

            scored_modifications = annotate_extractions_with_consensus(
                extracted_modifications, reviews
            )

            for modification, source_review, consensus in scored_modifications:
                key = " ".join(source_review.text.split()).strip().lower()
                review_id = review_id_by_key.setdefault(key, review_id_for(source_review))
                index = modification_index_by_key.get(key, 0)
                modification_index_by_key[key] = index + 1
                modification_id = modification_id_for(source_review, index)
                reviewer_by_modification[modification_id] = source_review.username

                if modification.evidence == "untested":
                    modification_records.append(
                        self.enhanced_generator.create_modification_record(
                            modification,
                            source_review,
                            change_records=[],
                            status="unapplied",
                            unapplied_reason=(
                                "Untested suggestion (next-time / preference language); "
                                "kept visible but not auto-applied"
                            ),
                            modification_id=modification_id,
                            consensus=consensus,
                        )
                    )
                    logger.info(
                        f"Left {modification.modification_type} unapplied: untested evidence"
                    )
                    continue

                if consensus.decision == "held_for_opposition":
                    modification_records.append(
                        self.enhanced_generator.create_modification_record(
                            modification,
                            source_review,
                            change_records=[],
                            status="unapplied",
                            unapplied_reason=consensus.summary,
                            modification_id=modification_id,
                            consensus=consensus,
                        )
                    )
                    logger.info(
                        f"Left {modification.modification_type} unapplied: "
                        f"community opposition ({consensus.summary})"
                    )
                    continue

                committed_entries, rejected_edits = ledger.apply_modification(
                    modification, modification_id, review_id
                )

                change_records = [
                    ChangeRecord(
                        type=_SECTION_TO_CHANGE_TYPE[entry.section],
                        from_text=entry.before_text,
                        to_text=entry.after_text,
                        operation=entry.operation,
                    )
                    for entry in committed_entries
                ]

                if committed_entries and not rejected_edits:
                    status, unapplied_reason = "applied", None
                    logger.info(
                        f"Applied {modification.modification_type}: "
                        f"{len(change_records)} changes made"
                    )
                elif committed_entries and rejected_edits:
                    status, unapplied_reason = "partial", None
                    logger.warning(
                        f"Partially applied {modification.modification_type}: "
                        f"{len(committed_entries)} committed, {len(rejected_edits)} rejected"
                    )
                else:
                    status = "unapplied"
                    unapplied_reason = (
                        rejected_edits[0].detail
                        if rejected_edits
                        else "Extracted modification carried no edits that could be attempted"
                    )
                    logger.warning(
                        f"Recorded unapplied {modification.modification_type}: {unapplied_reason}"
                    )

                modification_records.append(
                    self.enhanced_generator.create_modification_record(
                        modification,
                        source_review,
                        change_records=change_records,
                        status=status,
                        unapplied_reason=unapplied_reason,
                        modification_id=modification_id,
                        rejected_edits=rejected_edits,
                        consensus=consensus,
                    )
                )

            # Replay verification runs unconditionally -- including when zero
            # edits committed -- because it is the proof mechanism, not an
            # optional extra. An empty ledger trivially replays.
            verification = ledger.verify()
            provenance = Provenance(
                original_fingerprint=RecipeDocument.from_recipe(recipe).fingerprint(),
                enhanced_fingerprint=ledger.document.fingerprint(),
                ledger=ledger.entries,
                rejected_edits=ledger.rejections,
                blame=ledger.blame(reviewer_by_modification),
                verification=verification,
            )

            modified_recipe = ledger.document.to_recipe(
                recipe, recipe_id=f"{recipe.recipe_id}_modified"
            )

            status = "enhanced" if ledger.entries else "no_changes"

            # Step 3: Generate enhanced recipe with attribution
            logger.info("Step 3: Generating enhanced recipe with attribution...")

            enhanced_recipe = self.enhanced_generator.generate_enhanced_recipe_from_records(
                recipe,
                modified_recipe,
                modification_records,
                max_reviews=max_reviews,
                candidates_considered=len(candidate_reviews),
                provenance=provenance,
                status=status,
            )

            logger.info(
                f"Generated enhanced recipe: {enhanced_recipe.title} (status={status}, "
                f"replay deterministic={verification.deterministic})"
            )

            # Save output
            if save_output:
                output_filename = f"enhanced_{recipe.recipe_id}_{recipe.title.lower().replace(' ', '-')[:30]}.json"
                output_path = self.output_dir / output_filename
                self.enhanced_generator.save_enhanced_recipe(
                    enhanced_recipe, str(output_path)
                )

            return enhanced_recipe

        except Exception as e:
            logger.error(f"Failed to process recipe {recipe_file}: {e}")
            import traceback

            traceback.print_exc()
            return None

    def process_recipe_directory(
        self,
        data_dir: str = "data",
        max_reviews_per_recipe: Optional[int] = None,
        max_recipes: Optional[int] = None,
    ) -> List[EnhancedRecipe]:
        """
        Process all recipe files in a directory.

        Args:
            data_dir: Directory containing recipe JSON files
            max_reviews_per_recipe: Optional cap on extracted reviews per recipe
            max_recipes: Optional cap on number of recipe files to process

        Returns:
            List of successfully processed EnhancedRecipe objects
        """
        data_path = Path(data_dir)
        recipe_files = sorted(data_path.glob("recipe_*.json"))

        if max_recipes is not None:
            recipe_files = recipe_files[:max_recipes]

        logger.info(f"Found {len(recipe_files)} recipe files to process")

        enhanced_recipes = []
        for recipe_file in recipe_files:
            logger.info(f"\n{'=' * 60}")
            enhanced_recipe = self.process_single_recipe(
                str(recipe_file),
                max_reviews=max_reviews_per_recipe,
            )

            if enhanced_recipe:
                enhanced_recipes.append(enhanced_recipe)
                logger.info(f"✓ Successfully processed: {enhanced_recipe.title}")
            else:
                logger.warning(f"✗ Failed to process: {recipe_file.name}")

        logger.info(f"\n{'=' * 60}")
        logger.info(
            f"Pipeline complete: {len(enhanced_recipes)}/{len(recipe_files)} recipes successfully enhanced"
        )

        return enhanced_recipes

    def generate_summary_report(
        self, enhanced_recipes: List[EnhancedRecipe]
    ) -> Dict[str, Any]:
        """
        Generate a summary report of pipeline results.

        Args:
            enhanced_recipes: List of enhanced recipes

        Returns:
            Summary report dictionary
        """
        if not enhanced_recipes:
            return {"status": "no_recipes_processed"}

        recipes_enhanced = sum(
            1 for recipe in enhanced_recipes if recipe.status == "enhanced"
        )
        recipes_no_changes = sum(
            1 for recipe in enhanced_recipes if recipe.status == "no_changes"
        )

        total_modifications = sum(
            sum(1 for mod in recipe.modifications_applied if mod.status == "applied")
            for recipe in enhanced_recipes
        )
        total_unapplied = sum(
            sum(1 for mod in recipe.modifications_applied if mod.status == "unapplied")
            for recipe in enhanced_recipes
        )
        total_changes = sum(
            recipe.enhancement_summary.total_changes for recipe in enhanced_recipes
        )

        change_type_counts = {}
        for recipe in enhanced_recipes:
            for change_type in recipe.enhancement_summary.change_types:
                change_type_counts[change_type] = (
                    change_type_counts.get(change_type, 0) + 1
                )

        report = {
            "pipeline_summary": {
                "recipes_processed": len(enhanced_recipes),
                # "recipes_processed" includes honest no-op passes (status ==
                # "no_changes"); don't let those inflate "successfully enhanced".
                "recipes_enhanced": recipes_enhanced,
                "recipes_no_changes": recipes_no_changes,
                "total_modifications_applied": total_modifications,
                "total_modifications_unapplied": total_unapplied,
                "total_changes_made": total_changes,
                "change_type_distribution": change_type_counts,
            },
            "enhanced_recipes": [
                {
                    "recipe_id": recipe.recipe_id,
                    "title": recipe.title,
                    "status": recipe.status,
                    "modifications_count": sum(
                        1 for mod in recipe.modifications_applied if mod.status == "applied"
                    ),
                    "unapplied_count": sum(
                        1 for mod in recipe.modifications_applied if mod.status == "unapplied"
                    ),
                    "review_groups": len(recipe.modifications_by_review),
                    "changes_count": recipe.enhancement_summary.total_changes,
                    "change_types": recipe.enhancement_summary.change_types,
                }
                for recipe in enhanced_recipes
            ],
        }

        return report

    def save_summary_report(
        self, enhanced_recipes: List[EnhancedRecipe], output_path: Optional[str] = None
    ) -> str:
        """
        Save pipeline summary report to JSON file.

        Args:
            enhanced_recipes: List of enhanced recipes
            output_path: Path to save report (auto-generated if None)

        Returns:
            Path to saved report
        """
        if output_path is None:
            output_path = str(self.output_dir / "pipeline_summary_report.json")

        report = self.generate_summary_report(enhanced_recipes)

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        logger.info(f"Saved pipeline summary report to: {output_path}")
        return output_path
