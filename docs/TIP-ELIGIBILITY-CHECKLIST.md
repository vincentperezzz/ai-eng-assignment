# Tip Eligibility Slice — Implementation Checklist

Locked after grilling. Implemented as pipeline v1.2.

## Goal

Improve which Reviews reach extraction, and only apply **tested** tips while keeping **untested** suggestions visible.

## Checklist

### 1. Candidate pool (before LLM)
- [x] Stop treating missing/`false` `has_modification` as a hard pipeline refusal for all reviews
- [x] Build candidate pool =
  - all featured reviews with text
  - regex-hint positives (`has_modification`)
  - small recall cue matches (`need`, `threw in`, `should`, quantity/unit-ish patterns)
- [x] Keep dedupe + order: featured first, then higher stars
- [x] Still skip pure no-cue praise (not every review)

### 2. Extraction schema / prompt
- [x] Add `evidence` (or equivalent) on each Modification: `tested` | `untested`
- [x] Prompt rules: tested = reviewer says they did it; untested = next time / prefer / wish
- [x] Empty modifications list when comment has no concrete tip

### 3. Apply policy
- [x] Apply only `evidence=tested` tips that match recipe lines
- [x] Record `evidence=untested` as `status=unapplied` with clear reason
- [x] Keep existing conflict / failed-match unapplied behavior

### 4. Review budget honesty
- [x] Keep demo default `max_reviews=1`
- [x] Record the `max_reviews` value used in enhanced output metadata

### 5. Proof
- [x] Fixture/test: Nikujaga-style missed tip enters pool and can extract
- [x] Fixture/test: “next time / prefer more apple” → untested, not applied
- [x] Fixture/test: praise-only still does not become a candidate (or extracts empty)
- [x] Unit tests for candidate-pool helper and evidence apply policy

### 6. Docs after code
- [x] Update `ASSESSMENT.md` known limitations / decisions
- [x] Update `AGENT_TRAJECTORY.md`
- [x] Optional ADR for soft eligibility + tested-only apply

## Explicitly out of this slice

- New ranking score beyond featured + stars
- Second LLM eligibility call
- UI
- Full scraper rewrite
