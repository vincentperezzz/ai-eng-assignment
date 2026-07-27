# Casper Studios AI Engineer Take-Home

## Comprehensive Document

## 1. Assignment Understanding

The assignment was not to build a new product from scratch. The real task was to inherit an in-progress AI workflow, evaluate whether it actually works, and then improve the most important reliability failures under realistic time constraints.

The core product idea is straightforward:

- ingest recipe data and user reviews
- identify community-provided modifications
- convert those suggestions into structured edits
- apply them to the recipe
- produce an enhanced recipe with attribution and line-level reasoning

The brief strongly suggested that the right question was: does this system work beyond a couple of superficial examples?

That framing drove the solution. I chose not to spend time on UI, deployment, or cosmetic cleanup. The highest-value work was making the pipeline more trustworthy.

## 2. Assumptions

The following assumptions guided the work:

- `featured_tweaks` represent stronger community signal than ordinary reviews and should be prioritized.
- Extraction quality and edit application are the primary product risks; scraper heuristics are a secondary but real scaling risk (especially the `has_modification` gate).
- A deterministic and testable pipeline is more valuable than a wider but less reliable set of features.
- It is acceptable to improve environment compatibility if that materially helps demonstrate the system.
- The deliverable does not require solving every edge case; it requires good engineering judgment about what matters most, and honesty about what was deferred.

## 3. Problem Analysis

After tracing the control flow, I identified three primary issues.

### Issue A: The pipeline selected one random review

The original orchestrator chose a single random review with `has_modification=true`, extracted one modification, and generated one enhanced recipe from that single path.

That created several problems:

- the output changed between runs
- useful community tweaks were ignored
- featured feedback already present in the dataset was underused
- the behavior did not match the brief’s emphasis on highest-voted or strongest community-tested modifications

### Issue B: Valid edits often failed to apply

Even when extraction succeeded, the modifier logic often failed because it assumed the target text would closely match a full ingredient line or instruction line.

That broke common real-world cases such as:

- changes that referred to only part of a longer instruction
- near-match ingredient wording
- case differences or small formatting differences

This was especially important because the pipeline could appear to succeed while making no actual recipe change.

### Issue C: The repo was harder to validate than necessary

The original setup was effectively OpenAI-oriented. In practice, the available environment did not include an OpenAI key, which blocked live validation.

This was not the core product issue, but it was a practical engineering blocker. A working solution should be demonstrable under available conditions.

## 4. Solution Approach

I prioritized the work in this order:

1. make recipe changes apply correctly
2. make review selection more product-correct
3. make the result testable and attributable
4. make the repo runnable in the current environment

This sequence was deliberate. If modifier application is broken, then better extraction does not matter. If selection logic is random, then the result is still untrustworthy even when some individual edits succeed.

## 5. Technical Decisions And Rationale

### Decision 1: Merge `featured_tweaks` and `reviews`

Reason:

- the dataset already contains stronger signal in `featured_tweaks`
- the product goal is to apply the best community-tested changes, not a random subset

Implementation result:

- reviews are deduplicated by normalized text
- featured items are preserved and prioritized
- ordinary reviews still remain available as lower-priority candidates

### Decision 2: Split discrete tips within a review, then apply across reviews

Reason:

- the brief’s first cue treats “I added an egg and halved the sugar” as two discrete modifications
- users inspecting diffs need a clear type/reason per tip, with credit back to the same source review
- multi-review aggregation alone was not enough

Implementation result:

- extraction returns a `ModificationSet` (list) per review
- enhanced recipes include flat `modifications_applied` and grouped `modifications_by_review`
- each tip has `status: applied|unapplied` so failed applies stay visible instead of disappearing
- tips that conflict on the same recipe find-target are kept visible but not auto-applied

### Decision 3: Repair modifier matching instead of masking it

Reason:

- edit application is the point where extraction becomes real product behavior
- exact-match assumptions were too brittle for natural-language review content

Implementation result:

- substring-aware matching for `replace`
- case-insensitive replacement
- fuzzy fallback when a near match is strong enough (with a residual whole-line overwrite risk documented in Known Limitations)

### Decision 4: Add focused tests, not broad synthetic coverage

Reason:

- the key risk was specific logic failure, not general test absence everywhere
- targeted tests give fast signal on the highest-risk slices

Implementation result:

- tests for modifier reliability
- tests for review prioritization and multi-review orchestration
- config tests for provider selection behavior

### Decision 5: Support Gemini through the OpenAI-compatible interface

Reason:

- it solved the environment block with minimal architectural disruption
- it preserved the existing client abstraction
- it made live validation possible without a larger refactor

Implementation result:

- provider selection for Gemini or OpenAI
- base URL support
- environment loading from `.env` and `.venv/.env`
- quota-aware validation controls for bounded smoke tests

## 6. Implementation Details

### Pipeline changes

- merged featured and ordinary review sources
- deduplicated reviews by normalized text
- prioritized featured reviews, then higher-rated reviews
- extracted and applied multiple modifications instead of one random modification

### Modifier changes

- handled partial matches inside longer instruction lines
- improved near-match ingredient replacement behavior
- preserved concrete change records for attribution

### Enhanced recipe generation changes

- supported multi-modification output
- aggregated summary statistics across successful changes
- preserved per-review attribution in the final artifact

### Runtime and environment changes

- added Gemini support
- added fallback env loading from `.venv/.env`
- fixed CLI path handling from repo root
- added raw JSON extraction fallback when structured parsing fails
- added bounded all-run controls for free-tier validation

## 7. Validation And Results

### Automated validation

```bash
uv run python -m unittest discover -s tests -v
```

Result:

- 7 tests passed

### Live single-recipe validation

```bash
uv run python src/test_pipeline.py single
```

Result:

- successful Gemini-backed end-to-end run
- generated enhanced chocolate chip cookie output

### Controlled batch smoke test

```powershell
$env:ALL_RECIPES_MAX_FILES='2'
$env:ALL_RECIPES_MAX_REVIEWS='1'
uv run python src/test_pipeline.py all
```

Result:

- 1 of 2 recipes enhanced successfully in a bounded live test
- summary report generated

### What this means

The project is materially stronger than the original baseline in three important ways:

- the recipe changes are more likely to apply correctly
- the review selection logic is more aligned with the intended product behavior
- the system is now easier to test and demonstrate in practice

## 8. Challenges Encountered

### Challenge 1: Hidden product signal in the data

The strongest product clue was already present in `featured_tweaks`, but the pipeline was not using that signal effectively.

### Challenge 2: Silent failures in edit application

The pipeline could produce the appearance of success without actual recipe edits. This required fixing the mutation layer, not just the extraction layer.

### Challenge 3: Environment mismatch

The absence of an OpenAI key would have blocked live validation. Supporting Gemini through the compatible endpoint solved that without unnecessary architectural churn.

### Challenge 4: Gemini free-tier behavior

Longer responses and bounded quotas introduced runtime noise. The final repo handles this more gracefully and exposes settings for smaller validation runs.

## 9. Tradeoffs

- I did not build a UI because it would not answer the brief’s main question.
- I did not attempt full conflict resolution across overlapping modifications because that is a second-order problem after getting the core pipeline reliable.
- I did not optimize for unrestricted batch throughput because free-tier runtime constraints made correctness and bounded validation the more defensible target.

## 10. Known Limitations And Future Improvements

### Addressed in this revision (v1.1)

Within-review discrete modifications are now supported:

- extraction returns a `ModificationSet` (list of tips) per review
- enhanced output keeps a flat list **and** `modifications_by_review` grouping
- each tip carries `source_review` plus `status` (`applied` / `unapplied`)
- conflicting tips that target the same recipe text are left visible but not auto-applied

Known limitations still open:

1. **Scraper `has_modification` gate** — the pipeline hard-filters on the scraper’s regex flag; some genuine tweak reviews never reach the LLM.
2. **Demo `max_reviews` defaults to 1** — multi-review aggregation is implemented and unit-tested, but default live smoke runs usually show one review’s tips for quota reasons.
3. **Fuzzy `replace` whole-line fallback** — when a surgical substring edit fails but similarity ≥ 0.6, the matched line can be overwritten entirely; wrong-line matches are possible on paraphrased finds.
4. **`add_after` / `remove` matching** — substring-aware rescue was focused on `replace`; the other operations remain fuzzier.
5. **Dead few-shot prompt path** — inherited brace bug leaves `build_few_shot_prompt` unusable; live extraction uses the simple prompt (now list-aware).
6. **Conflict detection is coarse** — only same `(target, find)` pairs within one review; richer conflict resolution is deferred.

Future improvements:

1. Recompute or LLM-classify “contains a modification” instead of trusting scraper regex alone.
2. Guard fuzzy replaces (same-entity / token overlap checks) before whole-line overwrite.
3. Wire substring matching into `add_after` and `remove`, and revive few-shot examples after fixing the format-string brace.
4. Build a stable offline fixture suite that covers representative recipes and reviews without requiring live LLM calls.
5. Raise default demo `max_reviews` (or ship a second artifact) so multi-review aggregation is visible in committed outputs.
6. Richer conflict resolution beyond shared find-target detection.


## 11. Final Summary

The most important improvement was not simply adding more code. It was changing the system from a brittle demonstration into a more credible product pipeline.

The finished work focuses on:

- better product alignment
- more reliable edit application
- stronger attribution
- better validation coverage
- more practical runtime flexibility

That is the reason this solution matches the spirit of the assignment: it treats the work like a real engineering handoff problem, not a toy implementation exercise.