"""Community consensus for extracted tips (support / oppose / neutral).

This is a confidence layer on top of Featured + star ranking — not a replacement
for it. Related comments can agree ("yea brown sugar tastes better") or warn
("brown sugar makes it lumpy, don't try it"). Strong opposition holds a tip
back from auto-apply; agreement is recorded but never lets a weaker tip
overwrite a line already locked by a higher-ranked tip.
"""

from __future__ import annotations

import re
from typing import Iterable, List, Optional, Sequence, Set, Tuple

from .ledger import distinctive_tokens, normalize
from .models import (
    ConsensusComment,
    ModificationObject,
    Review,
    TipConsensus,
)

# Phrases that push *for* a tip already under discussion.
_SUPPORT_CUES = (
    "agree",
    "me too",
    "same here",
    "same thing",
    "works great",
    "worked great",
    "tastes better",
    "taste better",
    "so much better",
    "much better",
    "highly recommend",
    "do this",
    "try this",
    "this tip",
    "game changer",
)

# Phrases that push *against* applying a tip.
_OPPOSE_CUES = (
    "don't try",
    "do not try",
    "didn't work",
    "did not work",
    "doesn't work",
    "does not work",
    "made it worse",
    "too sweet",
    "too dry",
    "too greasy",
    "lumpy",
    "ruined",
    "avoid",
    "never again",
    "wouldn't recommend",
    "would not recommend",
    "skip the",
    "don't use",
    "do not use",
    "instead of brown",
    "rather than brown",
)


def tip_topic_tokens(modification: ModificationObject) -> Set[str]:
    """Content words that define what tip family a comment must relate to."""
    parts: List[str] = [modification.reasoning or ""]
    for edit in modification.edits:
        parts.extend(
            [
                edit.find or "",
                edit.replace or "",
                edit.add or "",
            ]
        )
    tokens = set()
    for part in parts:
        tokens |= distinctive_tokens(part)
    return tokens


def _shares_topic(review_text: str, topic: Set[str]) -> bool:
    if not topic:
        return False
    review_tokens = distinctive_tokens(review_text)
    return bool(topic & review_tokens)


def _stance_for(text: str) -> Optional[str]:
    lowered = normalize(text)
    # Oppose first so "don't try brown sugar it tastes better" leans caution.
    for cue in _OPPOSE_CUES:
        if cue in lowered:
            return "oppose"
    for cue in _SUPPORT_CUES:
        if cue in lowered:
            return "support"
    return None


def _excerpt(text: str, limit: int = 140) -> str:
    cleaned = re.sub(r"\s+", " ", text or "").strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"


def score_tip_consensus(
    modification: ModificationObject,
    source_review: Review,
    all_reviews: Sequence[Review],
) -> TipConsensus:
    """Score related community comments for one extracted tip.

    The tip author's own review is excluded from support/oppose counts so we
    do not treat the tip itself as consensus for itself.
    """
    topic = tip_topic_tokens(modification)
    source_key = normalize(source_review.text)
    related: List[ConsensusComment] = []
    support = oppose = neutral = 0

    for review in all_reviews:
        if normalize(review.text) == source_key:
            continue
        if not _shares_topic(review.text, topic):
            continue

        stance = _stance_for(review.text)
        if stance is None:
            # Related to the topic but no clear agree/disagree cue — still
            # useful for auditors, not decisive for apply.
            neutral += 1
            related.append(
                ConsensusComment(
                    stance="neutral",
                    reviewer=review.username,
                    rating=review.rating,
                    excerpt=_excerpt(review.text),
                )
            )
            continue

        if stance == "support":
            support += 1
        else:
            oppose += 1
        related.append(
            ConsensusComment(
                stance=stance,  # type: ignore[arg-type]
                reviewer=review.username,
                rating=review.rating,
                excerpt=_excerpt(review.text),
            )
        )

    if oppose > 0 and oppose >= support:
        decision = "held_for_opposition"
        summary = (
            f"Held back: {oppose} related comment(s) warn against this tip "
            f"vs {support} in support"
        )
    elif support > 0 or oppose > 0 or neutral > 0:
        decision = "apply_allowed"
        summary = (
            f"Consensus signal: {support} support, {oppose} oppose, "
            f"{neutral} related neutral — ranking still decides order"
        )
    else:
        decision = "insufficient_signal"
        summary = "No related agree/disagree comments found beyond the tip author"

    return TipConsensus(
        support_count=support,
        oppose_count=oppose,
        neutral_count=neutral,
        decision=decision,  # type: ignore[arg-type]
        summary=summary,
        related_comments=related,
    )


def annotate_extractions_with_consensus(
    extracted: Iterable[Tuple[ModificationObject, Review]],
    all_reviews: Sequence[Review],
) -> List[Tuple[ModificationObject, Review, TipConsensus]]:
    """Attach a consensus score to every extracted (tip, source review) pair."""
    return [
        (modification, source_review, score_tip_consensus(modification, source_review, all_reviews))
        for modification, source_review in extracted
    ]
