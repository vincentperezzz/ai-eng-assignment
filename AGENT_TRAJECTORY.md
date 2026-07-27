# Agent Trajectory

## Purpose

This is the agent-trajectory deliverable from the take-home brief: a clear log of what the coding agent inspected, hypothesized, changed, and validated while improving the in-progress recipe pipeline.

## Starting constraints from the brief

- Decide whether the existing pipeline actually works beyond superficial examples.
- Fix the most important reliability issues; do not try to solve everything.
- Do not build a fancy UI or deploy unless necessary.
- Work in a private clone; do not open a PR to Casper’s original repo.
- Deliver source, a comprehensive document, a video, and this trajectory file.

## Chronological work log

### Phase 1 — Understand and diagnose

1. Read the take-home brief and locked the evaluation target: **does the pipeline work for real?**
2. Inspected the core path:
   - `src/llm_pipeline/pipeline.py`
   - `src/llm_pipeline/tweak_extractor.py`
   - `src/llm_pipeline/recipe_modifier.py`
   - `src/llm_pipeline/enhanced_recipe_generator.py`
   - `src/test_pipeline.py`
3. Inspected sample data and confirmed `featured_tweaks` already existed as stronger signal.
4. Hypothesis: the main failures were orchestration + edit application, not scraping or JSON layout.
5. Confirmed the pipeline chose one random `has_modification` review and extracted one modification blob.
6. Confirmed the modifier often failed on substring / near-match cases, sometimes with no real recipe change.

### Phase 2 — Highest-impact reliability fixes

7. Prioritized two slices: featured-first multi-review flow, and modifier correctness.
8. Fixed `recipe_modifier.py` so `replace` can match text inside a longer instruction line and near-match ingredient lines.
9. Added focused modifier tests.
10. Refactored `pipeline.py` to merge featured + reviews, dedupe, prioritize featured then stars, and apply multiple tips instead of one random path.
11. Added dependency injection so orchestration could be unit-tested without live LLM calls.
12. Extended enhanced-recipe generation for multiple modifications with attribution.
13. Added multi-review extraction support in `tweak_extractor.py`.
14. Added pipeline tests for prioritization and multi-mod apply.
15. Unit tests for these slices passed.

### Phase 3 — Make the system demonstrable

16. Hit an environment block: OpenAI-only assumptions, no OpenAI key available.
17. Added Gemini via the OpenAI-compatible endpoint, provider selection, and clearer missing-key errors.
18. Added `env_loader.py` for `.env` / `.venv/.env`.
19. Fixed CLI path handling from repo root.
20. Added quota-aware env caps (`SINGLE_RECIPE_MAX_REVIEWS`, `ALL_RECIPES_MAX_*`).
21. Added raw JSON fallback when structured parse fails.
22. Live Gemini single-recipe smoke test succeeded; bounded batch smoke also ran.

### Phase 4 — Brief cue #1 (within-review discrete tips)

23. Grilled the plan against the brief and domain language: one Review → Modification set; keep unapplied tips visible; do not invent tips.
24. Implemented `ModificationSet` extraction (list of tips per review).
25. Added `status: applied | unapplied`, `modifications_by_review`, and coarse within-review conflict handling.
26. Added tests for egg/sugar split, unapplied retention, payload parsing, and conflicts.
27. Recorded ADR `docs/adr/0001-modification-set-per-review.md`.

### Phase 5 — Tip eligibility and tested-only apply (cue #2 / scaling)

28. Softened scraper `has_modification` into a candidate-pool hint.
29. Candidate pool = featured + scraper/regex hints + small recall cues (`need`, `threw in`, quantity-ish); pure no-cue praise stays out.
30. Added `evidence: tested | untested`; apply only tested; keep untested visible as unapplied.
31. Recorded `max_reviews` and `candidates_considered` on enhanced output.
32. Added eligibility tests (Nikujaga-style miss, untested not applied, praise-only exclusion).
33. Recorded ADR `docs/adr/0002-tip-eligibility.md`.

### Phase 6 — Stronger live proof + yield consistency

34. Added Alibaba DashScope (Qwen) as an OpenAI-compatible provider for more reliable live demos than Gemini free-tier 503s.
35. Live DashScope run with `max_reviews=2` on chocolate chip cookies: 2 reviews → 6 discrete tips applied, with inspectable diffs in `data/enhanced/`.
36. Fixed servings/yield inconsistency: tips that change batch size can emit a `servings` edit, and enhanced output uses the modified servings value.
37. Updated comprehensive document and this trajectory to match the final system.

## Key decisions (short)

| Decision | Why |
| --- | --- |
| Reliability over breadth / UI | Matches the brief’s main question |
| Fix selection + apply paths first | Those decide whether enhancements are real |
| ModificationSet per review | Direct answer to “egg + halved sugar” |
| Soft eligibility + tested-only apply | Avoid scraper ground-truth and preference-as-fact |
| Multi-provider LLM support | Needed honest live validation |
| Skip ranking / second eligibility LLM / UI | Lower leverage for this take-home |

## Validation performed

### Unit tests

```bash
python -m unittest discover -s tests -v
```

Outcome: focused suite passing for modifier, pipeline, ModificationSet, tip eligibility, and provider config.

### Live single-recipe runs

```bash
python src/test_pipeline.py single
```

Outcomes:

- Gemini: end-to-end success on cookies; multi-review less reliable under free-tier 503s
- DashScope (`qwen3.7-plus`, `SINGLE_RECIPE_MAX_REVIEWS=2`): 6 tips across 2 reviews applied; enhanced JSON written with attribution and servings sync

## Remaining known limitations

1. Fuzzy whole-line overwrite can still pick a wrong line on paraphrased finds.
2. `add_after` / `remove` matching is weaker than `replace`.
3. Conflict detection is coarse (shared find-target among tested tips).
4. Soft recall cues still miss some tip phrasings.
5. Demo defaults may keep `max_reviews` low for quota; capability is proven with higher caps.
6. Failed extractions are logged but not yet fully recorded in enhanced JSON metadata.

## Final outcome

The agent work did not try to rebuild the product. It diagnosed the inherited pipeline, fixed the failures that most hurt trust, proved the brief’s cues with tests and live artifacts, and documented what was intentionally deferred.
