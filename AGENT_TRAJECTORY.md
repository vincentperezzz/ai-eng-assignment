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

### Phase 7 — Ledger integration (handoff from lead diagnosis)

A separate diagnosis pass (live sweep across all 6 sample recipes, real DashScope calls) found two further defects and shipped a built-and-smoke-tested core (`src/llm_pipeline/ledger.py`, additive changes to `src/llm_pipeline/models.py`). This phase is the integration work on top of that.

38. Confirmed what was already built (`RecipeLedger`, `RecipeDocument`, `Line`, new Pydantic models `LedgerEntry`/`RejectedEdit`/`BlameLine`/`ReplayVerification`/`Provenance`) versus what was still wiring (everything downstream of extraction).
39. Read `pipeline.py`, `enhanced_recipe_generator.py`, `models.py`, `ledger.py`, `recipe_modifier.py`, `tests/test_pipeline.py` end to end before editing.
40. **Task 1 — Rewired `pipeline.py`.** `process_single_recipe` now instantiates one `RecipeLedger` per recipe run and calls `ledger.apply_modification(modification, modification_id, review_id)` for every tested tip instead of `RecipeModifier.apply_modification`. Deleted the within-review `conflicting_modification_indices` call (the ledger's compare-and-swap supersedes it); left `modification_conflicts.py` and its tests in place, unused by the pipeline. `Provenance` (fingerprints, ledger entries, rejections, blame, replay verification) is built and attached to every run, including zero-edit runs — `ledger.verify()` always executes, per the handoff's "this is the proof mechanism, it doesn't get to be optional."
41. **Task 2 — No-op recipes stopped hard-failing.** The three `return None` paths (`candidate_reviews` empty, `extracted_modifications` empty, zero committed edits) were replaced with a single honest code path: build an (empty) ledger, still verify it, and produce a real `EnhancedRecipe` with `status="no_changes"`, untouched original content, every extracted tip still listed with its true unapplied reason, and an honest `expected_impact` string instead of the generic "Community-validated" copy. `generate_summary_report` now reports `recipes_enhanced` and `recipes_no_changes` separately so a no-op pass can't inflate the "successfully enhanced" count.
42. **Task 3 — Wired `EnhancedRecipeGenerator`.** `create_modification_record` gained `modification_id` and `rejected_edits` params (both passed straight through, both optional/defaulted so no existing call site broke). `generate_enhanced_recipe_from_records` gained `provenance` and `status` params. `calculate_enhancement_summary` now counts `"partial"` modifications alongside `"applied"` ones (a partial modification still has real committed edits reflected in the recipe) and picks an honest default `expected_impact` string when the run is a no-op.
43. **Task 4 — Tests.** Added `tests/test_ledger.py` (7 tests): the exact clobber-bug regression (two tips targeting the same original line, the second rejected `superseded`/`no_op`, first tip's edit present in final ingredients, `verify().deterministic is True`), replay determinism across a mixed replace/add/remove/servings sequence, tamper detection (an out-of-band mutation of `ledger.document` makes `verify()` report `deterministic=False` with non-empty mismatches), blame correctness (two reviewers, two different lines, correct attribution + untouched lines stay `origin="original"`), the guarded fuzzy match directly (white sugar vs. brown sugar), and an `add_after` anchor surviving a prior rewrite of its anchor line. Updated `tests/test_pipeline.py` with a new zero-reviews no-op test, and fixed one now-incorrect assertion in `tests/test_tip_eligibility.py` (`test_untested_suggestion_is_visible_but_not_applied` asserted the *old* hard-failure behavior returning `None`; updated it to assert the new `status="no_changes"` behavior, which is exactly the Defect-B fix this phase implements — not a loosened assertion). No other existing test needed changes; the three multi-modification pipeline tests in `test_pipeline.py` all passed unmodified against the ledger.
44. **Task 5 — Trust report.** Added `src/tools/trust_report.py` (+ `src/tools/__init__.py`): reads `data/enhanced/enhanced_*.json` with no network/LLM calls and prints per-recipe replay-verification status, applied/partial/unapplied/rejected-silently counts, per-line blame, and the full rejected-edits list with reasons.
45. **Saved-and-replay AI answers for offline demos — skipped** on purpose (demo convenience only; half-implementing a cache that secretly calls the live API on miss is worse than none). Flagged in `ASSESSMENT.md` §10.
46. Ran the full unit test suite (`PYTHONPATH=src ./.scratch_venv/Scripts/python.exe -m unittest discover -s tests -v`) and the live sweep (`ALL_RECIPES_MAX_REVIEWS=4 ... src/test_pipeline.py all`) against real DashScope calls, and inspected the regenerated `enhanced_10813_best-chocolate-chip-cookies.json` directly (not just logs) to confirm the specific clobbered-sugar contradiction no longer appears: the conflicting later edit is now recorded as a rejected, no-op edit inside a `"partial"` modification, and the sugar values in the final `ingredients` list match every `"applied"`/`"partial"` change's `to_text` exactly. See the Validation section below for exact counts.
47. At the end of Phase 7, one residual gap remained (same-line amount overwrite under fuzzy match). **Closed in Phase 8** with rank-then-lock — see below.

## Key decisions (short)

| Decision | Why |
| --- | --- |
| Reliability over breadth / UI | Matches the brief’s main question |
| Fix selection + apply paths first | Those decide whether enhancements are real |
| ModificationSet per review | Direct answer to “egg + halved sugar” |
| Soft eligibility + tested-only apply | Avoid scraper ground-truth and preference-as-fact |
| Multi-provider LLM support | Needed honest live validation |
| Rank-then-lock + tip consensus | Higher-ranked tip wins a line; related warnings can hold apply |
| Skip ranking ML / second eligibility LLM / UI | Lower leverage for this take-home |

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

### Phase 7 validation (ledger integration)

```bash
PYTHONPATH=src ./.scratch_venv/Scripts/python.exe -m unittest discover -s tests -v
ALL_RECIPES_MAX_REVIEWS=4 PYTHONPATH=src ./.scratch_venv/Scripts/python.exe src/test_pipeline.py all
```

- Unit tests: 33/33 passing (25 pre-existing + 8 new/updated: 7 in new `tests/test_ledger.py`, plus pipeline/tip-eligibility test updates for the new `no_changes` status)
- Live sweep (all 6 sample recipes, real DashScope calls, `ALL_RECIPES_MAX_REVIEWS=4`): 6/6 recipes produced output (4 `status=enhanced`, 2 `status=no_changes`), versus 3/6 hard failures before this phase (see `ASSESSMENT.md` §7 for the before/after evidence). Every recipe's `provenance.verification.deterministic` is `True`.
- Independently re-verified (not just by the implementing agent): confirmed via `docs/evidence/live_sweep_before.log` (pre-fix) vs. a fresh post-fix sweep that the specific cookies-file contradiction is gone, and additionally found a *real* `superseded` rejection (not a contrived one) in the regenerated `enhanced_77935_creamy-sweet-potato-with-ginge.json` — proof the stale-read guard fires on real LLM output, not only on hand-built fixtures.
- Directly inspected the regenerated `enhanced_10813_best-chocolate-chip-cookies.json`: the previously-fabricated "applied" quantity-adjustment modification is now recorded as `status="partial"`, with its conflicting edit present in `rejected_edits` (`reason: "no_op"`), and every remaining `to_text` in `changes_made` matches the final `ingredients` list exactly.
- `PYTHONPATH=src ./.scratch_venv/Scripts/python.exe src/tools/trust_report.py data/enhanced/enhanced_*.json` ran with no LLM key configured for the tool itself and printed per-recipe replay verification, apply/partial/unapplied counts, and per-line blame for all 6 regenerated files.

### Phase 8 — Rank-then-lock + tip consensus

48. Product decision: when two tips fight over the same line, keep the higher-ranked tip (Featured → stars) and lock the line; related agree/disagree comments are a confidence layer, not a silent override of ranking.
49. Implemented **line lock** in `ledger.py`: once a `line_id` has a writer, later replace/remove/servings edits on that line are rejected as `superseded` — closes the same-ingredient amount overwrite residual.
50. Added `tip_consensus.py` + `TipConsensus` / `ConsensusComment` models: topic-token overlap + English support/oppose cues; strong opposition → hold auto-apply; attach consensus to every tip record in enhanced JSON.
51. Wired consensus into `pipeline.py` before ledger apply; extended `trust_report.py` to print consensus summaries; tests in `tests/test_tip_consensus.py` (same-line amount lock + opposition hold + support allowed).
52. Unit tests: **37/37 passing**.

## Remaining known limitations

Fixed by Phases 7–8 (see `ASSESSMENT.md` §10):

- ~~Fuzzy whole-line overwrite across different ingredients~~
- ~~Same-line amount overwrite under fuzzy match~~ — rank-then-lock
- ~~Coarse conflict detection~~
- ~~Hard-fail when nothing to apply~~
- ~~Agree/disagree comments ignored~~ — tip consensus confidence layer

Still open:

1. `add_after` / `remove` matching is weaker than `replace`.
2. Soft recall cues still miss some tip phrasings.
3. Consensus cue lists are English heuristics — sarcasm / negation edge cases can mis-score.
4. Demo defaults may keep `max_reviews` low for quota; capability is proven with higher caps.
5. No saved-and-replay AI answers (optional; not needed if demo uses finished JSON + trust report).

## Final outcome

The agent work did not try to rebuild the product. It diagnosed the inherited pipeline, fixed the failures that most hurt trust — including provable attribution, line lock, and community opposition as a hold — proved the brief’s cues with tests and live artifacts, and documented what was intentionally deferred.
