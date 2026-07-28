#!/usr/bin/env python3
"""Trust report: auditor-facing summary of enhanced-recipe provenance.

Reads already-produced `data/enhanced/enhanced_*.json` files and prints a
compact, human-readable report of what changed, who gets credit for each line,
and whether the ledger's replay verification actually proves it -- rather than
merely claiming it (see ASSESSMENT.md §7 for the defect this
replaces).

This tool makes **no network or LLM calls**. It only parses JSON already
written by the pipeline, so it runs with no API key configured.

Usage:
    PYTHONPATH=src python src/tools/trust_report.py data/enhanced/*.json
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List

from llm_pipeline.models import BlameLine, EnhancedRecipe, RejectedEdit

LINE_LABEL_COLUMN = 62


def load_enhanced_recipe(path: Path) -> EnhancedRecipe:
    return EnhancedRecipe.model_validate_json(path.read_text(encoding="utf-8"))


def _status_badge(recipe: EnhancedRecipe) -> str:
    return "[ENHANCED]" if recipe.status == "enhanced" else "[NO CHANGES]"


def _header_line(recipe: EnhancedRecipe) -> str:
    badge = _status_badge(recipe)
    title = recipe.title
    pad = max(1, 78 - len(title) - len(badge))
    return f"{title}{' ' * pad}{badge}"


def _counts(recipe: EnhancedRecipe):
    applied = sum(1 for m in recipe.modifications_applied if m.status == "applied")
    partial = sum(1 for m in recipe.modifications_applied if m.status == "partial")
    unapplied = sum(1 for m in recipe.modifications_applied if m.status == "unapplied")
    # An "unapplied" record with no explanation would mean something was
    # dropped without a reason -- the whole point of this tool is proving
    # that never happens silently. This should always read 0.
    silently_rejected = sum(
        1
        for m in recipe.modifications_applied
        if m.status == "unapplied" and not m.unapplied_reason
    )
    return applied, partial, unapplied, silently_rejected


def _reviewer_label(reviewers: List[str]) -> str:
    return ", ".join(reviewers) if reviewers else "unknown reviewer"


def _line_label(line: BlameLine) -> str:
    if line.origin == "original":
        return "(original)"
    ids = ", ".join(line.modification_ids)
    return f"<- {ids} ({_reviewer_label(line.reviewers)})"


def _print_blamed_lines(recipe: EnhancedRecipe, section: str) -> None:
    fallback = recipe.ingredients if section == "ingredients" else recipe.instructions

    if not recipe.provenance:
        # Should not happen once the pipeline is wired to the ledger, but
        # degrade gracefully to the raw content rather than crash.
        for text in fallback:
            print(f"    {text}")
        return

    blame_lines = [b for b in recipe.provenance.blame if b.section == section]
    if not blame_lines:
        for text in fallback:
            print(f"    {text}")
        return

    for line in blame_lines:
        label = _line_label(line)
        pad = max(1, LINE_LABEL_COLUMN - len(line.text))
        print(f"    {line.text}{' ' * pad}{label}")


def print_report(recipe: EnhancedRecipe) -> None:
    print(_header_line(recipe))

    if recipe.provenance:
        verification = recipe.provenance.verification
        state = "DETERMINISTIC" if verification.deterministic else "NOT DETERMINISTIC"
        print(
            f"  replay verification: {state} "
            f"({verification.entries_replayed} entries replayed, "
            f"{len(verification.mismatches)} mismatches)"
        )
        if not verification.deterministic:
            for mismatch in verification.mismatches:
                print(f"    ! {mismatch}")
    else:
        print("  replay verification: NOT AVAILABLE (no provenance recorded on this file)")

    applied, partial, unapplied, silent = _counts(recipe)
    print(
        f"  {applied} applied - {partial} partial - {unapplied} unapplied "
        f"- {silent} rejected-silently"
    )
    print("  ---")

    print("  ingredients:")
    _print_blamed_lines(recipe, "ingredients")

    if recipe.instructions:
        print("  instructions:")
        _print_blamed_lines(recipe, "instructions")

    if recipe.servings:
        print(f"  servings: {recipe.servings}")

    consensus_notes = [
        m
        for m in recipe.modifications_applied
        if m.consensus and m.consensus.decision != "insufficient_signal"
    ]
    if consensus_notes:
        print("  consensus:")
        for mod in consensus_notes:
            c = mod.consensus
            assert c is not None
            tip = mod.modification_type
            print(
                f"    - {tip}: {c.decision} "
                f"(support={c.support_count}, oppose={c.oppose_count}) — {c.summary}"
            )

    rejected_edits: List[RejectedEdit] = (
        recipe.provenance.rejected_edits if recipe.provenance else []
    )
    if rejected_edits:
        print("  rejected:")
        for rejected in rejected_edits:
            find_preview = (
                rejected.find if len(rejected.find) <= 60 else rejected.find[:57] + "..."
            )
            superseded_note = (
                f" (already rewritten by {rejected.superseded_by})"
                if rejected.superseded_by
                else ""
            )
            print(
                f"    - {rejected.operation} on {rejected.section} "
                f"({rejected.review_id}): {rejected.reason} "
                f'-- "{find_preview}"{superseded_note}'
            )

    print()


def main(argv: List[str]) -> int:
    if not argv:
        print(
            "Usage: PYTHONPATH=src python src/tools/trust_report.py "
            "data/enhanced/*.json",
            file=sys.stderr,
        )
        return 1

    exit_code = 0
    for arg in argv:
        path = Path(arg)
        if not path.exists():
            print(f"! {path}: file not found", file=sys.stderr)
            exit_code = 1
            continue
        try:
            recipe = load_enhanced_recipe(path)
        except Exception as exc:  # noqa: BLE001 - report and keep going
            print(f"! {path}: could not parse as EnhancedRecipe ({exc})", file=sys.stderr)
            exit_code = 1
            continue
        print_report(recipe)

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
