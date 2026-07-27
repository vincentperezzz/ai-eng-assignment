# Agent Trajectory

## Purpose

This file is the agent-trajectory deliverable requested in the take-home brief. It summarizes the actual coding-agent workflow, including what was inspected, what hypotheses were formed, what was changed, and how the work was validated.

## Starting Constraints From The Brief

- Focus on whether the existing recipe-enhancement pipeline actually works.
- Prioritize the most important reliability issues instead of trying to solve everything.
- Do not spend time building a UI unless it is necessary.
- Use a private clone rather than opening a pull request to the original repository.
- Provide source code, a comprehensive document, a video presentation, and an agent trajectory file.

## Chronological Work Log

1. Read the take-home brief and extracted the real evaluation target: determine whether the recipe pipeline works beyond superficial examples.
2. Cloned the assignment repository locally and inspected the core execution path:
   - `src/llm_pipeline/pipeline.py`
   - `src/llm_pipeline/tweak_extractor.py`
   - `src/llm_pipeline/recipe_modifier.py`
   - `src/llm_pipeline/enhanced_recipe_generator.py`
   - `src/test_pipeline.py`
3. Inspected sample data and confirmed that the dataset already contained `featured_tweaks`, which are stronger signals than ordinary reviews.
4. Formed an initial local hypothesis: the main failure was not scraping or JSON structure, but orchestration and edit application reliability.
5. Verified that the pipeline chose only one random review, which made results non-deterministic and left useful tweaks unused.
6. Verified that the modifier logic depended too heavily on exact or near-exact line matches, causing valid extracted edits to fail silently.
7. Chose to focus on two highest-impact slices:
   - review prioritization and multi-review processing
   - modifier application correctness
8. Updated `recipe_modifier.py` so edits could succeed when the target text was embedded inside a larger instruction line or only approximately matched the original ingredient text.
9. Added focused tests in `tests/test_recipe_modifier.py` to lock in the repaired modifier behavior.
10. Refactored `pipeline.py` to merge `featured_tweaks` and ordinary `reviews`, deduplicate them, prioritize featured feedback, and process multiple modification reviews instead of one random selection.
11. Added dependency injection hooks to the pipeline to make orchestration behavior easier to test without relying on live model calls.
12. Extended `enhanced_recipe_generator.py` so one enhanced recipe could contain multiple successful modifications and preserve attribution for each one.
13. Extended `models.py` to track whether a review came from the featured-tweak path.
14. Extended `tweak_extractor.py` with multi-review extraction support.
15. Added focused pipeline tests in `tests/test_pipeline.py` covering:
   - deduplication and prioritization of featured tweaks
   - applying multiple modifications in one recipe run
16. Ran the unit test suite and confirmed the targeted logic changes were passing.
17. Hit an environment constraint: the original repo assumed OpenAI-only credentials, but the available setup did not include an OpenAI key.
18. Adapted the extractor to support Gemini through the OpenAI-compatible endpoint so the repo could be validated without rewriting the entire LLM integration layer.
19. Added provider selection logic for `gemini` and `openai`, default models, optional base URL support, and clearer missing-key behavior.
20. Added `env_loader.py` so credentials could be loaded from either the repo root `.env` or `.venv/.env`, matching the actual local setup.
21. Fixed `src/test_pipeline.py` path handling so `uv run python src/test_pipeline.py ...` works correctly from the repository root.
22. Added quota-aware controls for Gemini smoke tests:
   - `SINGLE_RECIPE_MAX_REVIEWS`
   - `ALL_RECIPES_MAX_FILES`
   - `ALL_RECIPES_MAX_REVIEWS`
23. Encountered a Gemini-specific failure mode where structured parsing and long responses could still truncate under free-tier constraints.
24. Added a raw-completion fallback path in `tweak_extractor.py` so parser failures did not immediately collapse the extraction attempt.
25. Re-ran validation and confirmed:
   - unit tests passed
   - a live single-recipe Gemini run succeeded
   - a controlled all-recipes Gemini smoke test succeeded on a small bounded run
26. Prepared documentation that matched the brief more closely:
   - comprehensive document
   - handoff checklist
   - presentation outline
   - presentation script
27. Reorganized the documentation into the workspace root as requested.

## Key Decisions And Why They Were Chosen

### 1. Prioritize reliability over breadth

The brief explicitly emphasized product judgment and whether the system truly works. Because of that, the work focused on the highest-leverage failures instead of adding new features or a UI.

### 2. Fix root-cause control points, not symptoms

The real problems lived in the pipeline selection logic and the modifier application logic. Those paths decide whether a recipe is improved correctly at all.

### 3. Add tests around the changed slices

Without tests, the fixes would only be claims. The targeted tests convert those claims into repeatable evidence.

### 4. Support Gemini pragmatically

The goal was not to redesign the LLM layer. The goal was to make the repo runnable and demonstrable under the available environment. Using the OpenAI-compatible Gemini path was the lowest-friction solution.

## Validation Performed

### Automated tests

```bash
uv run python -m unittest discover -s tests -v
```

Outcome:

- 7 tests passed

### Live single-recipe validation

```bash
uv run python src/test_pipeline.py single
```

Outcome:

- successful end-to-end Gemini-backed run
- generated enhanced chocolate chip cookie output

### Controlled all-recipes smoke test

```powershell
$env:ALL_RECIPES_MAX_FILES='2'
$env:ALL_RECIPES_MAX_REVIEWS='1'
uv run python src/test_pipeline.py all
```

Outcome:

- 1 of 2 recipes enhanced successfully in a bounded free-tier test
- summary report generated

## Remaining Known Limitations

1. Gemini free-tier still shows output-length and quota sensitivity on some longer review inputs. The code now handles this more gracefully and supports quota-aware smoke tests, but a fully unrestricted batch run is still more reliable with higher quota or a paid provider.
2. Default demo env caps (`*_MAX_REVIEWS=1`) mean live artifacts usually process one review even though the orchestration loop supports more.
3. Modifier substring rescue is strongest on `replace`; fuzzy whole-line overwrite and weaker `add_after`/`remove` matching remain residual risks.
4. The pipeline still gates on scraper `has_modification` flags rather than re-detecting modifications.
5. Within-review conflict detection is coarse (shared find-target only).

## Follow-up: Within-Review Discrete Modifications (v1.1)

28. Grilled the fix plan against the brief and domain language (`CONTEXT.md`): one Review → Modification set; show grouped + per-tip `source_review`; keep unapplied tips visible; extract only clearly stated tips; defer scraper-gate and fuzzy-safety work.
29. Implemented `ModificationSet` extraction, applied/unapplied status, `modifications_by_review` grouping, and coarse conflict handling.
30. Added unit tests for egg/sugar split, unapplied retention, payload parsing, and conflict detection (15 tests passing).
31. Recorded the decision in `docs/adr/0001-modification-set-per-review.md` and updated this trajectory / assessment docs.

## Follow-up: Tip Eligibility (v1.2)

32. Softened scraper has_modification into a candidate-pool hint; featured + regex hints + recall cues (
eed, 	hrew in, quantity-ish) may reach extraction; pure no-cue praise stays out.
33. Added evidence (	ested | untested) on each tip; apply only tested; keep untested visible as unapplied (and exclude them from within-review conflict checks).
34. Recorded max_reviews and candidates_considered on enhanced output for budget honesty.
35. Added unit tests for Nikujaga-style recall, untested-not-applied, praise-only exclusion, and metadata; ADR docs/adr/0002-tip-eligibility.md.

## Final Outcome

The agent work did not attempt to solve every possible problem in the repo. It focused on the most important question in the brief: whether the pipeline actually works reliably enough to trust. The final result is materially stronger in determinism, edit correctness, attribution quality, test coverage, and environment flexibility.