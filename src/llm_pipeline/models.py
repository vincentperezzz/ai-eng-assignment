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


class LedgerEntry(BaseModel):
    """One committed, invertible edit in the recipe ledger.

    Each entry names the line it touched by stable `line_id` and records the
    content hash the edit *read* (`before_hash`) alongside the hash it wrote
    (`after_hash`). That pair is what makes the ledger replayable and lets a
    later edit detect that it is working from a stale view of the recipe.
    """

    entry_id: str = Field(description="Stable identifier for this ledger entry")
    modification_id: str = Field(description="Modification that produced this entry")
    review_id: str = Field(description="Review the modification came from")
    section: Literal["ingredients", "instructions", "servings"] = Field(
        description="Recipe section this entry changed"
    )
    operation: Literal["replace", "add", "remove"] = Field(
        description="Concrete operation performed on the document"
    )
    line_id: str = Field(description="Stable identity of the line that changed")
    before_text: str = Field(description="Line text before the operation")
    after_text: str = Field(description="Line text after the operation")
    before_hash: str = Field(description="Content hash the edit expected to find")
    after_hash: str = Field(description="Content hash written by the edit")
    anchor_line_id: Optional[str] = Field(
        default=None, description="For add operations, the line inserted after"
    )
    anchor_superseded: bool = Field(
        default=False,
        description="True when the anchor line had already been rewritten by an earlier tip",
    )
    match: Literal[
        "exact", "case_insensitive", "whitespace", "guarded_fuzzy", "line_identity"
    ] = Field(default="exact", description="How the edit's find text was located")


class RejectedEdit(BaseModel):
    """An edit that was deliberately not committed, with the reason why."""

    modification_id: str = Field(description="Modification the edit belonged to")
    review_id: str = Field(description="Review the modification came from")
    section: str = Field(description="Recipe section the edit targeted")
    operation: str = Field(description="Operation the edit asked for")
    find: str = Field(description="Text the edit tried to locate")
    payload: Optional[str] = Field(
        default=None, description="Replacement or added text the edit carried"
    )
    reason: Literal[
        "no_op",
        "superseded",
        "no_match",
        "missing_payload",
        "unsafe_removal",
        "duplicate",
    ] = Field(description="Why this edit was not committed")
    detail: str = Field(description="Human-readable explanation")
    superseded_by: Optional[str] = Field(
        default=None,
        description="Modification that had already rewritten the targeted line",
    )


class BlameLine(BaseModel):
    """Provenance for a single line of the enhanced recipe."""

    line_id: str = Field(description="Stable identity of this line")
    section: Literal["ingredients", "instructions"] = Field(
        description="Section the line belongs to"
    )
    text: str = Field(description="Final text of the line")
    origin: Literal["original", "community"] = Field(
        description="Whether the line came from the original recipe or a community tip"
    )
    modification_ids: List[str] = Field(
        default_factory=list, description="Modifications that touched this line, in order"
    )
    reviewers: List[str] = Field(
        default_factory=list, description="Reviewers credited for this line"
    )


class ReplayVerification(BaseModel):
    """Result of replaying the ledger from the original recipe."""

    deterministic: bool = Field(
        description="True when replaying the ledger reproduces the enhanced recipe exactly"
    )
    entries_replayed: int = Field(description="Number of ledger entries replayed")
    mismatches: List[str] = Field(
        default_factory=list, description="Differences found between replay and output"
    )


class Provenance(BaseModel):
    """Auditable record of how the enhanced recipe was produced."""

    original_fingerprint: str = Field(description="Content hash of the original recipe")
    enhanced_fingerprint: str = Field(description="Content hash of the enhanced recipe")
    ledger: List[LedgerEntry] = Field(
        default_factory=list, description="Committed edits in application order"
    )
    rejected_edits: List[RejectedEdit] = Field(
        default_factory=list, description="Edits that were not committed, and why"
    )
    blame: List[BlameLine] = Field(
        default_factory=list, description="Per-line attribution for the enhanced recipe"
    )
    verification: ReplayVerification = Field(
        description="Proof that the ledger reproduces the enhanced recipe"
    )


class ConsensusComment(BaseModel):
    """One related community comment that agrees with, warns against, or only mentions a tip."""

    stance: Literal["support", "oppose", "neutral"] = Field(
        description="Whether this comment backs, warns against, or only mentions the tip topic"
    )
    reviewer: Optional[str] = Field(default=None, description="Username if known")
    rating: Optional[int] = Field(default=None, description="Star rating if known")
    excerpt: str = Field(description="Short excerpt of the related comment")


class TipConsensus(BaseModel):
    """Community agree/disagree signal for one extracted tip (confidence layer)."""

    support_count: int = Field(description="Related comments that support applying the tip")
    oppose_count: int = Field(description="Related comments that warn against the tip")
    neutral_count: int = Field(
        description="Related comments that mention the topic without a clear stance"
    )
    decision: Literal["apply_allowed", "held_for_opposition", "insufficient_signal"] = Field(
        description=(
            "apply_allowed = ranking may apply; held_for_opposition = do not auto-apply; "
            "insufficient_signal = no related agree/disagree found"
        )
    )
    summary: str = Field(description="Human-readable consensus summary")
    related_comments: List[ConsensusComment] = Field(
        default_factory=list,
        description="Related comments used to form the consensus view",
    )


class ModificationApplied(BaseModel):
    """Full record of a modification extracted from a review, applied or not."""

    modification_id: Optional[str] = Field(
        default=None, description="Stable identifier used by the ledger and blame view"
    )
    source_review: SourceReview = Field(
        description="Review that suggested this modification"
    )
    modification_type: str = Field(description="Category of modification")
    reasoning: str = Field(description="Why this modification was suggested")
    evidence: Literal["tested", "untested"] = Field(
        default="tested",
        description="Whether the review presents this as a tested tip or untested suggestion",
    )
    consensus: Optional[TipConsensus] = Field(
        default=None,
        description=(
            "Related community support/opposition for this tip; strong opposition "
            "can hold auto-apply even when the tip itself is tested"
        ),
    )
    changes_made: List[ChangeRecord] = Field(
        default_factory=list,
        description="Detailed list of changes made when status is applied",
    )
    status: Literal["applied", "unapplied", "partial"] = Field(
        default="applied",
        description=(
            "applied = every edit landed; partial = some edits landed and some were "
            "rejected; unapplied = nothing changed"
        ),
    )
    unapplied_reason: Optional[str] = Field(
        default=None,
        description="Why the modification was not applied, when status is unapplied",
    )
    rejected_edits: List[RejectedEdit] = Field(
        default_factory=list,
        description="Edits from this modification that were not committed, and why",
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
    status: Literal["enhanced", "no_changes"] = Field(
        default="enhanced",
        description=(
            "enhanced = at least one community tip changed the recipe; no_changes = the "
            "recipe is a faithful pass-through because no tested tip could be applied"
        ),
    )
    provenance: Optional[Provenance] = Field(
        default=None,
        description="Replayable ledger, per-line blame, and self-verification for this run",
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
