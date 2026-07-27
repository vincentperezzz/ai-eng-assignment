"""Tip eligibility: which reviews may reach extraction."""

from __future__ import annotations

import re
from collections.abc import Iterable

from .models import Review

# Scraper-style hint patterns (kept aligned with scraper_v2 intent).
HINT_PATTERNS = [
    r"I (added|used|substituted|replaced|made with|changed)",
    r"(instead of|rather than|in place of)",
    r"(next time|will make again|definitely make)",
    r"(doubled|tripled|halved|increased|decreased)",
    r"(more|less|extra) ([\w\s]+)",
]

# Extra recall cues for tips the scraper hint often misses.
RECALL_CUE_PATTERNS = [
    r"\bneed\b",
    r"\bshould\b",
    r"\brecommend",
    r"threw in",
    r"throw in",
    r"\bat least\b",
    r"\b\d+\s*(lb|lbs|pound|pounds|cup|cups|tsp|tbsp|teaspoon|tablespoon|oz)\b",
]


def matches_any_pattern(text: str, patterns: list[str]) -> bool:
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)


def has_recall_cue(text: str) -> bool:
    return matches_any_pattern(text, RECALL_CUE_PATTERNS)


def has_scraper_style_hint(text: str) -> bool:
    return matches_any_pattern(text, HINT_PATTERNS)


def is_extraction_candidate(review: Review) -> bool:
    """
    Soft eligibility for LLM extraction.

    Featured reviews, scraper modification hints, and a small recall cue set
    may enter. Pure praise with no cues stays out.
    """
    if not review.text or not review.text.strip():
        return False
    if review.is_featured:
        return True
    if review.has_modification:
        return True
    if has_scraper_style_hint(review.text):
        return True
    if has_recall_cue(review.text):
        return True
    return False


def select_candidate_reviews(reviews: Iterable[Review]) -> list[Review]:
    """Preserve input order (already featured-first / rating-sorted)."""
    return [review for review in reviews if is_extraction_candidate(review)]
