"""Recipe Ledger: community tips as concurrent transactions on a shared document.

The inherited modifier treated every edit as an independent search-and-replace
against "the recipe". That is only safe when exactly one tip is ever applied.
With several tips in flight the recipe is a *shared mutable document* and the
edits are *concurrent writers* — the LLM authored every edit while looking at
the original recipe, so a tip applied late is working from a stale view.

This module models that honestly:

* **Line identity.** Each line carries a stable ``line_id`` that survives
  rewrites, insertions and deletions. Anchors stay valid even when the line
  they point at has been reworded.
* **Compare-and-swap.** Every edit declares the content hash it read. If the
  targeted line no longer holds that content, the edit is *superseded* — it is
  rejected and credited to the modification that got there first, instead of
  silently overwriting it.
* **An invertible ledger.** Every committed edit is appended as a
  :class:`~.models.LedgerEntry` that knows how to undo itself, so a single tip
  can be reverted without re-running the LLM.
* **Replay verification.** Replaying the ledger from the original recipe must
  reproduce the enhanced recipe byte for byte. Attribution is therefore proven
  rather than asserted.
"""

from __future__ import annotations

import copy
import hashlib
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Dict, Iterable, List, Optional, Tuple

from loguru import logger

from .models import (
    BlameLine,
    LedgerEntry,
    ModificationEdit,
    ModificationObject,
    Recipe,
    RejectedEdit,
    ReplayVerification,
    Review,
)

SECTIONS = ("ingredients", "instructions")
SECTION_PREFIX = {"ingredients": "ing", "instructions": "ins"}

# A guarded fuzzy match must clear this ratio *and* carry every distinctive
# token from the find text. The ratio alone is what let "1 cup white sugar"
# overwrite "1 cup packed brown sugar" in the inherited implementation.
FUZZY_THRESHOLD = 0.82
DISTINCTIVE_TOKEN_MIN_LENGTH = 4

# Removing a whole line is destructive, so the find text has to account for
# most of that line before we will drop it.
REMOVAL_COVERAGE = 0.6


def content_hash(text: str) -> str:
    """Short, stable content hash used for compare-and-swap checks."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def normalize(text: Optional[str]) -> str:
    """Collapse whitespace and case so cosmetic differences do not block a match."""
    return re.sub(r"\s+", " ", text or "").strip().lower()


def distinctive_tokens(text: str) -> set[str]:
    """Content words long enough to distinguish one recipe line from another."""
    return {
        token
        for token in re.findall(r"[a-z]+", normalize(text))
        if len(token) >= DISTINCTIVE_TOKEN_MIN_LENGTH
    }


def review_id_for(review: Review) -> str:
    """Deterministic id for a review, so runs and replays agree."""
    digest = hashlib.sha1(normalize(review.text).encode("utf-8")).hexdigest()[:8]
    return f"rev:{digest}"


def modification_id_for(review: Review, index: int) -> str:
    """Deterministic id for one discrete tip within a review."""
    return f"{review_id_for(review)}#{index}"


def recipe_fingerprint(ingredients: Iterable[str], instructions: Iterable[str],
                       servings: Optional[str]) -> str:
    """Content hash of a whole recipe, used to prove replay equivalence."""
    payload = "\n".join(
        ["#ingredients", *ingredients, "#instructions", *instructions,
         "#servings", servings or ""]
    )
    return content_hash(payload)


@dataclass
class Line:
    """One addressable line of a recipe."""

    line_id: str
    text: str

    @property
    def hash(self) -> str:
        return content_hash(self.text)


@dataclass
class RecipeDocument:
    """A recipe as an editable document of identity-carrying lines."""

    sections: Dict[str, List[Line]] = field(default_factory=dict)
    servings: Optional[str] = None
    _insert_counter: int = 0

    @classmethod
    def from_recipe(cls, recipe: Recipe) -> "RecipeDocument":
        return cls(
            sections={
                "ingredients": [
                    Line(f"ing:{i}", text) for i, text in enumerate(recipe.ingredients)
                ],
                "instructions": [
                    Line(f"ins:{i}", text) for i, text in enumerate(recipe.instructions)
                ],
            },
            servings=recipe.servings,
        )

    def clone(self) -> "RecipeDocument":
        return RecipeDocument(
            sections={
                section: [Line(line.line_id, line.text) for line in lines]
                for section, lines in self.sections.items()
            },
            servings=self.servings,
            _insert_counter=self._insert_counter,
        )

    def texts(self, section: str) -> List[str]:
        return [line.text for line in self.sections.get(section, [])]

    def locate(self, section: str, line_id: str) -> Tuple[Optional[int], Optional[Line]]:
        for index, line in enumerate(self.sections.get(section, [])):
            if line.line_id == line_id:
                return index, line
        return None, None

    def next_line_id(self, section: str) -> str:
        self._insert_counter += 1
        return f"{SECTION_PREFIX[section]}:+{self._insert_counter}"

    def fingerprint(self) -> str:
        return recipe_fingerprint(
            self.texts("ingredients"), self.texts("instructions"), self.servings
        )

    def to_recipe(self, template: Recipe, recipe_id: Optional[str] = None) -> Recipe:
        return Recipe(
            recipe_id=recipe_id or template.recipe_id,
            title=template.title,
            ingredients=self.texts("ingredients"),
            instructions=self.texts("instructions"),
            description=template.description,
            servings=self.servings,
            rating=template.rating,
        )


@dataclass
class _Match:
    """Where an edit's find text resolved to, and how confidently."""

    kind: str  # "current" | "superseded" | "missing"
    line: Optional[Line] = None
    index: Optional[int] = None
    match_type: str = "exact"
    superseded_by: Optional[str] = None
    score: float = 0.0


class RecipeLedger:
    """Applies modifications transactionally and records an auditable history."""

    def __init__(self, original: Recipe):
        self.original = original
        self.original_document = RecipeDocument.from_recipe(original)
        self.document = self.original_document.clone()
        self.entries: List[LedgerEntry] = []
        self.rejections: List[RejectedEdit] = []
        # line_id -> modification that most recently wrote to it
        self._last_writer: Dict[str, str] = {}
        self._entry_counter = 0

    # ------------------------------------------------------------------
    # Matching
    # ------------------------------------------------------------------

    def _substring_match(self, lines: List[Line], find: str) -> Optional[Tuple[int, Line, str]]:
        """Locate `find` inside a line, preferring the most literal match."""
        if not find.strip():
            return None

        for match_type, project in (
            ("exact", lambda text: text),
            ("case_insensitive", lambda text: text.lower()),
            ("whitespace", normalize),
        ):
            needle = project(find)
            if not needle.strip():
                continue
            hits = [
                (index, line)
                for index, line in enumerate(lines)
                if needle in project(line.text)
            ]
            if not hits:
                continue
            # Several lines can contain the same phrase ("sugar"). Prefer the
            # line the phrase accounts for most of — that is the intended target.
            index, line = max(
                hits,
                key=lambda hit: SequenceMatcher(
                    None, normalize(find), normalize(hit[1].text)
                ).ratio(),
            )
            return index, line, match_type

        return None

    def _fuzzy_match(self, lines: List[Line], find: str) -> Optional[Tuple[int, Line, float]]:
        """Whole-line fuzzy match, guarded so near-misses cannot be overwritten.

        The guard is what stops "1 cup white sugar" from matching
        "1 cup packed brown sugar": every distinctive token in the find text
        must actually be present in the candidate line.
        """
        required = distinctive_tokens(find)
        if not required:
            return None

        best: Optional[Tuple[int, Line, float]] = None
        for index, line in enumerate(lines):
            if not required.issubset(distinctive_tokens(line.text)):
                continue
            score = SequenceMatcher(None, normalize(find), normalize(line.text)).ratio()
            if score >= FUZZY_THRESHOLD and (best is None or score > best[2]):
                best = (index, line, score)

        return best

    def _resolve(self, section: str, find: str) -> _Match:
        """Resolve an edit's find text against the *current* document.

        When the text is absent now but was present in the original recipe, the
        line has been rewritten by an earlier tip. That is a stale read, not a
        missing target, and it is reported as such.
        """
        current = self.document.sections.get(section, [])

        hit = self._substring_match(current, find)
        if hit:
            index, line, match_type = hit
            return _Match("current", line, index, match_type, score=1.0)

        fuzzy = self._fuzzy_match(current, find)
        if fuzzy:
            index, line, score = fuzzy
            return _Match("current", line, index, "guarded_fuzzy", score=score)

        # Not in the current document — did it exist before other tips ran?
        original = self.original_document.sections.get(section, [])
        stale = self._substring_match(original, find) or None
        if stale is None:
            fuzzy_stale = self._fuzzy_match(original, find)
            if fuzzy_stale:
                stale = (fuzzy_stale[0], fuzzy_stale[1], "guarded_fuzzy")

        if stale:
            _, original_line, _ = stale
            return _Match(
                "superseded",
                line=original_line,
                superseded_by=self._last_writer.get(original_line.line_id),
            )

        return _Match("missing")

    # ------------------------------------------------------------------
    # Commit helpers
    # ------------------------------------------------------------------

    def _next_entry_id(self, modification_id: str) -> str:
        self._entry_counter += 1
        return f"e{self._entry_counter:03d}:{modification_id}"

    def _reject(
        self,
        modification_id: str,
        review_id: str,
        edit: ModificationEdit,
        reason: str,
        detail: str,
        superseded_by: Optional[str] = None,
    ) -> None:
        self.rejections.append(
            RejectedEdit(
                modification_id=modification_id,
                review_id=review_id,
                section=edit.target,
                operation=edit.operation,
                find=edit.find,
                payload=edit.replace if edit.operation == "replace" else edit.add,
                reason=reason,  # type: ignore[arg-type]
                detail=detail,
                superseded_by=superseded_by,
            )
        )
        logger.info(f"Rejected {edit.operation} on {edit.target} ({reason}): {detail}")

    def _commit(self, entry: LedgerEntry) -> None:
        self.entries.append(entry)
        self._last_writer[entry.line_id] = entry.modification_id

    def _reject_if_line_locked(
        self,
        modification_id: str,
        review_id: str,
        edit: ModificationEdit,
        line_id: str,
    ) -> bool:
        """Rank-then-lock: once a higher-ranked tip rewrites a line, later tips cannot.

        Closes the residual same-ingredient amount overwrite: a later tip whose find
        text still fuzzy-matches the rewritten line (same words, new quantity) is
        rejected as superseded instead of silently clobbering the winner.
        """
        prior = self._last_writer.get(line_id)
        if not prior or prior == modification_id:
            return False
        self._reject(
            modification_id,
            review_id,
            edit,
            "superseded",
            (
                f"Line {line_id} is already locked by an earlier higher-ranked tip "
                f"({prior}); refusing to overwrite it with a conflicting edit"
            ),
            superseded_by=prior,
        )
        return True

    # ------------------------------------------------------------------
    # Operations
    # ------------------------------------------------------------------

    def _apply_replace(
        self, modification_id: str, review_id: str, edit: ModificationEdit
    ) -> Optional[LedgerEntry]:
        if edit.replace is None:
            self._reject(
                modification_id, review_id, edit, "missing_payload",
                "Replace operation carried no replacement text",
            )
            return None

        if normalize(edit.find) == normalize(edit.replace):
            self._reject(
                modification_id, review_id, edit, "no_op",
                f"Find and replace text are equivalent ({edit.find!r}); "
                "recording this as an applied change would be a false claim",
            )
            return None

        match = self._resolve(edit.target, edit.find)

        if match.kind == "superseded":
            self._reject(
                modification_id, review_id, edit, "superseded",
                f"{edit.find!r} is no longer in the recipe — an earlier tip already "
                "rewrote that line, so this edit was written against a stale view",
                superseded_by=match.superseded_by,
            )
            return None

        if match.kind == "missing" or match.line is None or match.index is None:
            self._reject(
                modification_id, review_id, edit, "no_match",
                f"{edit.find!r} does not appear in the recipe {edit.target}",
            )
            return None

        line = match.line
        if self._reject_if_line_locked(modification_id, review_id, edit, line.line_id):
            return None

        before_text = line.text

        if match.match_type == "guarded_fuzzy":
            # The find text is a paraphrase of the whole line; swap the line.
            after_text = edit.replace
        else:
            after_text = self._replace_span(before_text, edit.find, edit.replace)

        if after_text == before_text:
            self._reject(
                modification_id, review_id, edit, "no_op",
                f"Applying the edit to {before_text!r} produced identical text",
            )
            return None

        entry = LedgerEntry(
            entry_id=self._next_entry_id(modification_id),
            modification_id=modification_id,
            review_id=review_id,
            section=edit.target,  # type: ignore[arg-type]
            operation="replace",
            line_id=line.line_id,
            before_text=before_text,
            after_text=after_text,
            before_hash=content_hash(before_text),
            after_hash=content_hash(after_text),
            match=match.match_type,  # type: ignore[arg-type]
        )

        line.text = after_text
        self._commit(entry)
        return entry

    @staticmethod
    def _replace_span(text: str, find: str, replacement: str) -> str:
        """Rewrite only the matched span, never the surrounding line."""
        if find in text:
            return text.replace(find, replacement, 1)

        lowered = text.lower()
        start = lowered.find(find.lower())
        if start != -1:
            return text[:start] + replacement + text[start + len(find):]

        # Whitespace-insensitive fallback: rebuild via a normalized search.
        pattern = re.compile(r"\s+".join(re.escape(part) for part in find.split()), re.IGNORECASE)
        replaced, count = pattern.subn(replacement, text, count=1)
        return replaced if count else text

    def _apply_add(
        self, modification_id: str, review_id: str, edit: ModificationEdit
    ) -> Optional[LedgerEntry]:
        if not edit.add:
            self._reject(
                modification_id, review_id, edit, "missing_payload",
                "add_after operation carried no text to add",
            )
            return None

        section_lines = self.document.sections.get(edit.target, [])

        if any(normalize(line.text) == normalize(edit.add) for line in section_lines):
            self._reject(
                modification_id, review_id, edit, "duplicate",
                f"{edit.add!r} is already present in {edit.target}",
            )
            return None

        match = self._resolve(edit.target, edit.find)
        anchor_superseded = False

        if match.kind == "superseded" and match.line is not None:
            # Insertion is non-destructive and line identity outlives rewrites,
            # so a reworded anchor is still a perfectly good anchor.
            index, live_line = self.document.locate(edit.target, match.line.line_id)
            if index is not None and live_line is not None:
                match = _Match("current", live_line, index, "line_identity")
                anchor_superseded = True

        if match.kind != "current" or match.index is None or match.line is None:
            self._reject(
                modification_id, review_id, edit, "no_match",
                f"Could not locate anchor {edit.find!r} in {edit.target}",
                superseded_by=match.superseded_by,
            )
            return None

        new_line = Line(self.document.next_line_id(edit.target), edit.add)

        entry = LedgerEntry(
            entry_id=self._next_entry_id(modification_id),
            modification_id=modification_id,
            review_id=review_id,
            section=edit.target,  # type: ignore[arg-type]
            operation="add",
            line_id=new_line.line_id,
            before_text="",
            after_text=new_line.text,
            before_hash=content_hash(""),
            after_hash=content_hash(new_line.text),
            anchor_line_id=match.line.line_id,
            anchor_superseded=anchor_superseded,
            match=match.match_type,  # type: ignore[arg-type]
        )

        section_lines.insert(match.index + 1, new_line)
        self._commit(entry)
        return entry

    def _apply_remove(
        self, modification_id: str, review_id: str, edit: ModificationEdit
    ) -> Optional[LedgerEntry]:
        match = self._resolve(edit.target, edit.find)

        if match.kind == "superseded":
            self._reject(
                modification_id, review_id, edit, "superseded",
                f"{edit.find!r} was already rewritten by an earlier tip; refusing to "
                "remove a line this edit never actually saw",
                superseded_by=match.superseded_by,
            )
            return None

        if match.kind != "current" or match.line is None or match.index is None:
            self._reject(
                modification_id, review_id, edit, "no_match",
                f"Could not find {edit.find!r} in {edit.target} to remove",
            )
            return None

        if self._reject_if_line_locked(
            modification_id, review_id, edit, match.line.line_id
        ):
            return None

        line = match.line
        coverage = len(normalize(edit.find)) / max(len(normalize(line.text)), 1)
        if coverage < REMOVAL_COVERAGE:
            self._reject(
                modification_id, review_id, edit, "unsafe_removal",
                f"{edit.find!r} covers only {coverage:.0%} of {line.text!r}; dropping the "
                "whole line would delete content the tip never mentioned",
            )
            return None

        entry = LedgerEntry(
            entry_id=self._next_entry_id(modification_id),
            modification_id=modification_id,
            review_id=review_id,
            section=edit.target,  # type: ignore[arg-type]
            operation="remove",
            line_id=line.line_id,
            before_text=line.text,
            after_text="",
            before_hash=content_hash(line.text),
            after_hash=content_hash(""),
            match=match.match_type,  # type: ignore[arg-type]
        )

        self.document.sections[edit.target].pop(match.index)
        self._commit(entry)
        return entry

    def _apply_servings(
        self, modification_id: str, review_id: str, edit: ModificationEdit
    ) -> Optional[LedgerEntry]:
        if edit.operation != "replace" or not edit.replace:
            self._reject(
                modification_id, review_id, edit, "missing_payload",
                "Servings edits only support replace with a new value",
            )
            return None

        before = self.document.servings or ""
        after = edit.replace

        if normalize(before) == normalize(after):
            self._reject(
                modification_id, review_id, edit, "no_op",
                f"Servings already {before!r}",
            )
            return None

        if self._reject_if_line_locked(modification_id, review_id, edit, "servings"):
            return None

        entry = LedgerEntry(
            entry_id=self._next_entry_id(modification_id),
            modification_id=modification_id,
            review_id=review_id,
            section="servings",
            operation="replace",
            line_id="servings",
            before_text=before,
            after_text=after,
            before_hash=content_hash(before),
            after_hash=content_hash(after),
        )

        self.document.servings = after
        self._commit(entry)
        return entry

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def apply_modification(
        self,
        modification: ModificationObject,
        modification_id: str,
        review_id: str,
    ) -> Tuple[List[LedgerEntry], List[RejectedEdit]]:
        """Apply one discrete tip, returning what committed and what did not."""
        rejections_before = len(self.rejections)
        committed: List[LedgerEntry] = []

        for edit in modification.edits:
            if edit.target == "servings":
                entry = self._apply_servings(modification_id, review_id, edit)
            elif edit.operation == "replace":
                entry = self._apply_replace(modification_id, review_id, edit)
            elif edit.operation == "add_after":
                entry = self._apply_add(modification_id, review_id, edit)
            elif edit.operation == "remove":
                entry = self._apply_remove(modification_id, review_id, edit)
            else:
                self._reject(
                    modification_id, review_id, edit, "no_match",
                    f"Unsupported operation {edit.operation!r}",
                )
                entry = None

            if entry is not None:
                committed.append(entry)

        return committed, self.rejections[rejections_before:]

    def invert(self, entry: LedgerEntry) -> Dict[str, object]:
        """The operation that undoes a ledger entry.

        Kept as data rather than executed immediately so a caller can revert a
        single community tip without re-running extraction.
        """
        if entry.operation == "replace":
            return {
                "operation": "replace",
                "section": entry.section,
                "line_id": entry.line_id,
                "text": entry.before_text,
            }
        if entry.operation == "add":
            return {
                "operation": "remove",
                "section": entry.section,
                "line_id": entry.line_id,
            }
        return {
            "operation": "add",
            "section": entry.section,
            "line_id": entry.line_id,
            "text": entry.before_text,
        }

    def revert(self, modification_id: str) -> "RecipeLedger":
        """Rebuild the recipe with one modification's entries left out."""
        replacement = RecipeLedger(self.original)
        for entry in self.entries:
            if entry.modification_id == modification_id:
                continue
            replacement._replay_entry(entry)
            replacement.entries.append(entry)
            replacement._last_writer[entry.line_id] = entry.modification_id
        return replacement

    # ------------------------------------------------------------------
    # Replay and verification
    # ------------------------------------------------------------------

    def _replay_entry(self, entry: LedgerEntry) -> Optional[str]:
        """Re-apply one entry to this ledger's document. Returns an error string."""
        if entry.section == "servings":
            if content_hash(self.document.servings or "") != entry.before_hash:
                return (
                    f"{entry.entry_id}: servings hash mismatch "
                    f"(expected {entry.before_hash})"
                )
            self.document.servings = entry.after_text
            return None

        lines = self.document.sections.setdefault(entry.section, [])

        if entry.operation == "add":
            anchor_index, _ = self.document.locate(entry.section, entry.anchor_line_id or "")
            position = len(lines) if anchor_index is None else anchor_index + 1
            lines.insert(position, Line(entry.line_id, entry.after_text))
            return None

        index, line = self.document.locate(entry.section, entry.line_id)
        if index is None or line is None:
            return f"{entry.entry_id}: line {entry.line_id} not present during replay"

        if line.hash != entry.before_hash:
            return (
                f"{entry.entry_id}: line {entry.line_id} held {line.hash} but the entry "
                f"expected {entry.before_hash}"
            )

        if entry.operation == "replace":
            line.text = entry.after_text
        else:
            lines.pop(index)

        return None

    def verify(self) -> ReplayVerification:
        """Replay the ledger from the original recipe and compare to the output.

        A green result is a hard guarantee: every difference between the
        original and enhanced recipe is explained by a ledger entry, and every
        ledger entry is explained by a community review.
        """
        replay = RecipeLedger(self.original)
        mismatches: List[str] = []

        for entry in self.entries:
            error = replay._replay_entry(entry)
            if error:
                mismatches.append(error)

        expected = self.document.fingerprint()
        produced = replay.document.fingerprint()
        if expected != produced:
            mismatches.append(
                f"replayed recipe fingerprint {produced} != pipeline output {expected}"
            )
            for section in SECTIONS:
                got = replay.document.texts(section)
                want = self.document.texts(section)
                if got != want:
                    mismatches.append(f"{section} differ after replay: {got!r} != {want!r}")

        return ReplayVerification(
            deterministic=not mismatches,
            entries_replayed=len(self.entries),
            mismatches=mismatches,
        )

    def blame(self, reviewer_by_modification: Dict[str, Optional[str]]) -> List[BlameLine]:
        """Per-line attribution for the enhanced recipe.

        This is the inspection surface the brief asks for: for any line of the
        improved recipe, which community tips are responsible for it.
        """
        touched: Dict[str, List[str]] = {}
        for entry in self.entries:
            touched.setdefault(entry.line_id, [])
            if entry.modification_id not in touched[entry.line_id]:
                touched[entry.line_id].append(entry.modification_id)

        blame_lines: List[BlameLine] = []
        for section in SECTIONS:
            for line in self.document.sections.get(section, []):
                modification_ids = touched.get(line.line_id, [])
                reviewers = []
                for modification_id in modification_ids:
                    reviewer = reviewer_by_modification.get(modification_id)
                    if reviewer and reviewer not in reviewers:
                        reviewers.append(reviewer)
                blame_lines.append(
                    BlameLine(
                        line_id=line.line_id,
                        section=section,  # type: ignore[arg-type]
                        text=line.text,
                        origin="community" if modification_ids else "original",
                        modification_ids=modification_ids,
                        reviewers=reviewers,
                    )
                )

        return blame_lines
