"""Detect simple conflicting modifications within one review's tip set."""

from __future__ import annotations

from collections import defaultdict

from .models import ModificationObject


def conflicting_modification_indices(
    modifications: list[ModificationObject],
) -> set[int]:
    """
    Mark modifications that share the same recipe find-target as conflicting.

    First-slice rule: if two discrete tips from the same review both edit the
    same (target, find) text, treat them as conflicting and do not auto-apply.
    """
    find_to_indices: dict[tuple[str, str], list[int]] = defaultdict(list)

    for index, modification in enumerate(modifications):
        seen_in_mod: set[tuple[str, str]] = set()
        for edit in modification.edits:
            key = (edit.target, edit.find.strip().lower())
            if key in seen_in_mod:
                continue
            seen_in_mod.add(key)
            find_to_indices[key].append(index)

    conflicting: set[int] = set()
    for indices in find_to_indices.values():
        unique = set(indices)
        if len(unique) > 1:
            conflicting.update(unique)

    return conflicting
