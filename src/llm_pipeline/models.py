"""
Pydantic data models for the LLM Analysis Pipeline.

These models define the structure for recipe modifications, enhanced recipes,
and all intermediate data formats used throughout the pipeline.
"""

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class ModificationEdit(BaseModel):
    """Individual atomic edit operation for a recipe modification."""

    target: Literal["ingredients", "instructions", "servings"] = Field(
        description="Whether this edit applies to ingredients, instructions, or servings/yield"
    )
    operation: Literal["replace", "add_after", "remove"] = Field(
        default="replace",
        description="Type of operation: replace text, add after target, or remove",
    )
    find: str = Field(description="Text to find in the recipe")
    replace: Optional[str] = Field(
        default=None, description="Replacement text (required for replace operations)"
    )
    add: Optional[str] = Field(
        default=None, description="Text to add (required for add_after operations)"
    )


class ModificationObject(BaseModel):
    """One discrete tip extracted from a review."""

    modification_type: Literal[
        "ingredient_substitution",
        "quantity_adjustment",
        "technique_change",
        "addition",
        "removal",
    ] = Field(description="Category of modification")

    reasoning: str = Field(description="Why this modification improves the recipe")

    evidence: Literal["tested", "untested"] = Field(
        default="tested",
        description=(
            "tested = reviewer reports they actually made this change; "
            "untested = next-time preference or wish"
        ),
    )

    edits: List[ModificationEdit] = Field(description="List of atomic edits to apply")


class ModificationSet(BaseModel):
    """All discrete modifications clearly stated in a single review."""

    modifications: List[ModificationObject] = Field(
        description="One entry per discrete tip in the review; empty if none"
    )


class SourceReview(BaseModel):
    """Reference to the original review that suggested the modification."""

    text: str = Field(description="Full text of the original review")
    reviewer: Optional[str] = Field(description="Username of the reviewer")
    rating: Optional[int] = Field(description="Star rating given by reviewer")


class ChangeRecord(BaseModel):
    """Record of a specific change made to the recipe."""

    type: Literal["ingredient", "instruction", "servings"] = Field(
        description="Type of element that was changed"
    )
    from_text: str = Field(description="Original text before modification")
    to_text: str = Field(description="New text after modification")
    operation: Literal["replace", "add", "remove"] = Field(
        description="Type of operation performed"
    )


class ModificationApplied(BaseModel):
    """Full record of a modification extracted from a review, applied or not."""

    source_review: SourceReview = Field(
        description="Review that suggested this modification"
    )
    modification_type: str = Field(description="Category of modification")
    reasoning: str = Field(description="Why this modification was suggested")
    evidence: Literal["tested", "untested"] = Field(
        default="tested",
        description="Whether the review presents this as a tested tip or untested suggestion",
    )
    changes_made: List[ChangeRecord] = Field(
        default_factory=list,
        description="Detailed list of changes made when status is applied",
    )
    status: Literal["applied", "unapplied"] = Field(
        default="applied",
        description="Whether this modification changed the recipe",
    )
    unapplied_reason: Optional[str] = Field(
        default=None,
        description="Why the modification was not applied, when status is unapplied",
    )


class ReviewModificationGroup(BaseModel):
    """Modifications grouped under one source review for clear attribution."""

    source_review: SourceReview = Field(
        description="The single review these tips came from"
    )
    modifications: List[ModificationApplied] = Field(
        description="Discrete tips extracted from this review"
    )


class EnhancementSummary(BaseModel):
    """Summary of all modifications applied to a recipe."""

    total_changes: int = Field(description="Total number of changes made")
    change_types: List[str] = Field(description="Types of modifications applied")
    expected_impact: str = Field(
        description="Expected improvement from these modifications"
    )


class EnhancedRecipe(BaseModel):
    """Recipe with community modifications applied and full attribution."""

    recipe_id: str = Field(description="Enhanced recipe ID")
    original_recipe_id: str = Field(description="ID of the original recipe")
    title: str = Field(description="Enhanced recipe title")

    # Enhanced recipe content
    ingredients: List[str] = Field(description="Modified ingredients list")
    instructions: List[str] = Field(description="Modified instructions list")

    # Attribution and tracking
    modifications_applied: List[ModificationApplied] = Field(
        description="Flat list of all modifications (applied and unapplied), each with source_review"
    )
    modifications_by_review: List[ReviewModificationGroup] = Field(
        default_factory=list,
        description="Same modifications grouped under each source review",
    )
    enhancement_summary: EnhancementSummary = Field(
        description="Summary of all enhancements"
    )

    # Optional metadata
    description: Optional[str] = Field(description="Enhanced recipe description")
    servings: Optional[str] = Field(description="Number of servings")
    prep_time: Optional[str] = Field(description="Preparation time")
    cook_time: Optional[str] = Field(description="Cooking time")
    total_time: Optional[str] = Field(description="Total time")

    # Generation metadata
    created_at: str = Field(description="When this enhanced recipe was created")
    pipeline_version: str = Field(
        default="1.0.0", description="Version of the pipeline that created this"
    )
    max_reviews: Optional[int] = Field(
        default=None,
        description="Review budget used for this run (None means no cap)",
    )
    candidates_considered: Optional[int] = Field(
        default=None,
        description="How many extraction-candidate reviews were available before the budget cap",
    )


class Recipe(BaseModel):
    """Base recipe model for input data."""

    recipe_id: str
    title: str
    ingredients: List[str]
    instructions: List[str]
    description: Optional[str] = None
    servings: Optional[str] = None
    rating: Optional[Dict[str, Any]] = None
    # Include other fields as needed


class Review(BaseModel):
    """Review model for input data."""

    text: str
    rating: Optional[int] = None
    username: Optional[str] = None
    has_modification: bool = False
    is_featured: bool = False
