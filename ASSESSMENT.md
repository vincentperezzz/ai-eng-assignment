# Casper Studios AI Engineer Take-Home

## Comprehensive Document

### Deliverables covered by this repo

| Brief requirement | Where it lives |
| --- | --- |
| Private source clone (not a PR to Casper) | This repository |
| Comprehensive write-up | This file (`ASSESSMENT.md`) |
| Agent trajectory | `AGENT_TRAJECTORY.md` |
| Video (5–7 min) | Submitted separately by email |
| Enhanced sample output | `data/enhanced/` |

---

## 1. What the assignment asked for

I inherited an in-progress recipe pipeline that should:

1. take an AllRecipes-style recipe and community reviews
2. find the strongest community-tested tips (especially Featured Tweaks)
3. turn those tips into structured edits
4. apply the edits
5. produce an enhanced recipe people can inspect, with line-level credit for each change

The brief’s real question was not “can you build a UI?” It was: **does this pipeline actually work beyond a couple of superficial examples?**

I treated that as a product-reliability problem under time pressure, not a greenfield build.

---

## 2. Assumptions

- Featured Tweaks are stronger signal than ordinary reviews and should be tried first.
- One review can contain several discrete tips (brief cue #1).
- Only tips the reviewer clearly states should be extracted; invented extras are worse than misses.
- Only **tested** tips should rewrite the recipe; next-time preferences can stay visible but unapplied.
- Scraper `has_modification` is a useful hint, not ground truth.
- No UI/deployment in this take-home; JSON attribution is the inspection surface.
- It is better to fix the highest-risk failures and document tradeoffs than to polish every edge case.

---

## 3. Problem analysis

After reading the pipeline end-to-end, three failures mattered most.

### Problem A — Wrong orchestration

The original code picked **one random** review with `has_modification=true`, extracted **one** modification blob, and stopped.

That meant:

- results changed between runs
- Featured Tweaks were ignored as a priority signal
- multi-tip reviews were collapsed or under-used
- the product story (“best community-tested changes”) was not what the code did

### Problem B — Edits often did not apply

Even when the LLM extracted a tip, `RecipeModifier` often failed because it assumed the find-text would match a whole ingredient/instruction line.

Common failures:

- tip text that is only a phrase inside a longer instruction
- small wording / case differences
- “success” with zero real recipe changes

### Problem C — Brief cue #1 was not modeled

“I added an egg and halved the sugar” is two tips. The original schema treated a review as one modification object, so users could not inspect discrete tips cleanly.

A related scaling issue (cue #2): trusting scraper regex alone dropped real tips (for example “You need at least 1 lb…”), and next-time preferences could be treated like proven changes.

---

## 4. Plan and solution

I ordered the work by product risk:

1. Make edits actually land on the recipe
2. Prefer Featured Tweaks, then stronger ratings
3. Split discrete tips inside one review
4. Soften tip eligibility and apply only tested tips
5. Keep attribution inspectable in the enhanced JSON
6. Make live demos runnable with available LLM providers

### Solution map

| Risk | Solution |
| --- | --- |
| Random single-review path | Merge featured + reviews, dedupe, featured-first then by stars, process up to `max_reviews` |
| One tip blob per review | Extract a `ModificationSet` (list of tips) per review |
| Silent edit failures | Stronger `replace` matching (substring, then fuzzy) + record applied/unapplied |
| Scraper hard gate | Soft candidate pool: featured + scraper hint + small recall cues |
| Wish vs tested tip | `evidence: tested \| untested`; apply only tested |
| Yield inconsistency | `servings` edit target + write modified servings into enhanced output |
| Provider lock-in | OpenAI-compatible providers: Gemini and Alibaba DashScope (Qwen) |

I did **not** build ranking beyond featured + stars, a second LLM eligibility call, or a UI. Those were lower leverage for this brief.

---

## 5. Technical decisions and rationale

### Decision 1 — Featured-first multi-review flow

**Why:** Matches the product intent and the data we already had.

**What changed:** `pipeline.py` merges `featured_tweaks` and `reviews`, dedupes by normalized text, sorts featured first then higher stars, then extracts/applies across a review budget.

### Decision 2 — One review → many Modifications

**Why:** Direct answer to cue #1.

**What changed:** Extraction returns `ModificationSet`. Enhanced JSON has:

- `modifications_applied` — flat list, each tip has its own `source_review`, `status`, `evidence`, and `changes_made`
- `modifications_by_review` — same tips grouped under one review for easier inspection

Unapplied tips stay visible with a reason (no match, conflict, or untested).

### Decision 3 — Soft tip eligibility + tested-only apply

**Why:** Cue #2 / scaling: scraper regex misses real tips; preferences should not silently rewrite recipes.

**What changed:**

- candidate pool in `tip_eligibility.py`
- `evidence` on each tip
- apply tested tips only; untested tips remain `unapplied`
- metadata: `max_reviews`, `candidates_considered`

### Decision 4 — Fix modifier matching where it hurts most

**Why:** Without reliable apply, extraction is theater.

**What changed:** substring-aware `replace`, case-insensitive replace, fuzzy fallback for strong near-matches. Residual risk of whole-line overwrite is documented below.

### Decision 5 — Provider flexibility for real demos

**Why:** The assignment requires proving the system works; provider lock-in blocked that.

**What changed:** OpenAI-compatible clients for Gemini and DashScope (`qwen3.7-plus` used successfully for multi-review live validation). Env loading supports `.env` / `.venv/.env`.

---

## 6. Implementation details

### Pipeline (`src/llm_pipeline/`)

- `pipeline.py` — orchestration, eligibility, apply policy, conflict handling among tested tips
- `tweak_extractor.py` — LLM extraction of `ModificationSet`
- `recipe_modifier.py` — edit application, including `servings`
- `enhanced_recipe_generator.py` — attribution + enhanced artifact
- `tip_eligibility.py` — soft candidate pool
- `models.py` / `prompts.py` — schemas and extraction rules

### Tests

Focused unit tests cover:

- instruction substring replace / fuzzy ingredient replace
- featured prioritization and multi-mod apply
- within-review tip split and unapplied retention
- tip eligibility (Nikujaga-style recall, praise-only exclusion, untested not applied)
- provider config (OpenAI / Gemini / DashScope)

```bash
# from repo root, with PYTHONPATH=src or via uv
python -m unittest discover -s tests -v
```

### Live validation

```bash
python src/test_pipeline.py single
```

Successful live run with Alibaba DashScope (`qwen3.7-plus`, `SINGLE_RECIPE_MAX_REVIEWS=2`) on Best Chocolate Chip Cookies:

- 2 featured reviews processed
- 6 discrete tips extracted and applied
- line-level diffs + per-tip attribution written to `data/enhanced/enhanced_10813_best-chocolate-chip-cookies.json`
- servings updated when a tip changed yield (48 → 16)

Gemini also works for smoke tests, but free-tier 503s made multi-review demos less reliable than DashScope in our environment.

---

## 7. Challenges

1. **Featured signal was already in the data** but unused — product fix, not a scrape rewrite.
2. **Silent apply failures** looked like success until we inspected diffs.
3. **Within-review splitting** required schema + prompt + output shape changes, not just “process more reviews.”
4. **Provider/quota friction** forced pragmatic multi-provider support so validation was honest.
5. **Yield vs servings** — LLM correctly suggested 16 cookies while metadata stayed 48 until we added an explicit servings edit path.

---

## 8. Tradeoffs

- No UI: the brief asked whether the pipeline works; JSON attribution is enough to inspect.
- No second LLM eligibility call: cost/latency without enough proven gain.
- No new ranking model: featured + stars is enough signal for this dataset.
- Coarse conflict detection only (shared find-target among tested tips).
- Default demo `max_reviews` can stay low for quota; the capability exists and was shown with `max_reviews=2`.

---

## 9. Known limitations and future improvements

Still open (honest leftovers):

1. Fuzzy whole-line overwrite can still choose a wrong line on paraphrased finds.
2. `add_after` / `remove` matching is weaker than `replace`.
3. Conflict detection is coarse.
4. Soft recall cues still miss some tip phrasings.
5. Inherited few-shot prompt path remains broken; live path uses the simple list-aware prompt.

Worth doing next, if this were a real team handoff:

1. Safer fuzzy replace guards (entity / token overlap).
2. Substring parity for `add_after` and `remove`.
3. Offline fixture suite that does not depend on live LLM calls.
4. Record skipped/failed extraction attempts in enhanced metadata.
5. Richer conflict resolution when tips partially overlap.

---

## 10. Final summary

The inherited pipeline looked complete but was not trustworthy: random single-review selection, brittle edits, and no clean model for multiple tips in one review.

The solution makes the system behave like the product described in the brief:

- prioritize Featured Tweaks
- split and attribute discrete community tips
- apply only tested changes that actually match the recipe
- leave failures and preferences visible
- prove it with tests and a live enhanced artifact

That matches the spirit of the assignment: budget attention on what most improves trust in an in-progress AI workflow.
