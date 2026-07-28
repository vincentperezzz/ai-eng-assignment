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
| Silent edit failures / fake “applied” | Early: stronger `replace` matching. Later: **`RecipeLedger`** compare-and-swap + **rank-then-lock** + replay verify |
| Scraper hard gate | Soft candidate pool: featured + scraper hint + small recall cues |
| Wish vs tested tip | `evidence: tested \| untested`; apply only tested |
| Agree / warn comments on the same tip | **Tip consensus** confidence layer (`tip_consensus.py`): related support/oppose; strong opposition holds auto-apply |
| Yield inconsistency | `servings` edit target + write modified servings into enhanced output |
| No usable tips → hard fail | Honest `status="no_changes"` enhanced output (6/6 samples produce a file) |
| Provider lock-in | OpenAI-compatible providers: Gemini and Alibaba DashScope (Qwen) |
| Auditor can’t check without API | `src/tools/trust_report.py` (offline blame + rejected edits + consensus) |

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

### Decision 4 — Fix apply reliability, then make attribution provable

**Why:** Without reliable apply, extraction is theater. Without stale-write detection, “applied” can lie.

**What changed (in order):**
1. Early hardening of `recipe_modifier.py` (substring / fuzzy `replace`) — still unit-tested, **no longer used by the live pipeline**.
2. Live path rewired to `ledger.py` (`RecipeLedger`): stable line IDs, reject stale/no-op edits, replay verification, per-line blame. See §7.
3. **Rank-then-lock:** once a higher-ranked tip rewrites a line, later tips cannot overwrite it (closes same-ingredient amount fights).
4. **Tip consensus** (`tip_consensus.py`): related agree/disagree comments are scored; strong opposition holds auto-apply; agreement is recorded but never overrides ranking or a locked line.

### Decision 5 — Provider flexibility for real demos

**Why:** The assignment requires proving the system works; provider lock-in blocked that.

**What changed:** OpenAI-compatible clients for Gemini and DashScope (`qwen3.7-plus` used successfully for multi-review live validation). Env loading supports `.env` / `.venv/.env`.

---

## 6. Implementation details

### Pipeline (`src/llm_pipeline/`)

- `pipeline.py` — orchestration, eligibility, consensus gate, **ledger apply**, provenance attachment
- `ledger.py` — compare-and-swap edits, **line lock**, replay verify, blame (live apply path)
- `tip_consensus.py` — related support/oppose scoring for extracted tips
- `tweak_extractor.py` — LLM extraction of `ModificationSet`
- `recipe_modifier.py` — legacy edit helper (superseded; kept + unit-tested)
- `enhanced_recipe_generator.py` — attribution + `provenance` / `status` / `consensus` in enhanced JSON
- `tip_eligibility.py` — soft candidate pool
- `models.py` / `prompts.py` — schemas (incl. ledger + consensus types) and extraction rules
- `src/tools/trust_report.py` — offline auditor report over `data/enhanced/`

### Tests

Focused unit tests cover:

- ledger clobber regression, **same-line amount lock**, replay determinism, blame, guarded fuzzy match
- tip consensus hold-for-opposition / support-allowed / unrelated ignored
- instruction substring replace / fuzzy ingredient replace (legacy modifier)
- featured prioritization, multi-mod apply, and honest `no_changes` output
- within-review tip split and unapplied retention
- tip eligibility (Nikujaga-style recall, praise-only exclusion, untested not applied)
- provider config (OpenAI / Gemini / DashScope)

```bash
# from repo root, with PYTHONPATH=src or via uv
python -m unittest discover -s tests -v
# or: python -m pytest tests/ -q
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

## 7. Post-handoff hardening: provable attribution

After the work in §§1–6 shipped, a further live sweep across all 6 sample recipes (`ALL_RECIPES_MAX_REVIEWS=4 python src/test_pipeline.py all`, real DashScope calls) surfaced two more defects — one a correctness bug in the trust story, one a scaling gap.

### Defect A — Fabricated attribution

`enhanced_10813_best-chocolate-chip-cookies.json` claimed a modification was `"applied"`:

```
[applied] quantity_adjustment  rev="These are awesome cookies. I followed the adv..."
    replace '1 cup white sugar' -> '0.5 cup white sugar'
    replace '1 cup packed brown sugar' -> '1.5 cups packed brown sugar'
```

But the final `ingredients` list in that same file contained `1 cup white sugar` (reverted) and `1/2 cup packed brown sugar` (a different value again). A **later** review's fuzzy matcher (`RecipeModifier.find_best_match`, threshold 0.6) matched against the *rewritten* line, scored it "similar enough," and silently overwrote it — while the pipeline still recorded the earlier tip as applied with a diff that no longer existed anywhere in the recipe. An auditor diffing the JSON against the ingredient list would have caught this in thirty seconds.

Root cause: `RecipeModifier` treats every edit as an independent, context-free search-and-replace against "the current recipe text." With more than one tip in flight, the recipe is a **shared mutable document** and the tips are **concurrent writers**, each authored by the LLM against the *original* recipe. Nothing detected that a later edit was reading stale state.

### Defect B — Recipes with no viable tip produced no output at all

`spicy-apple-cake` (all tips were "next time" / untested), `spiced-purple-plum-jam` and `mango-teriyaki-marinade` (zero reviews in the scraped data at all) came back as hard failures — `process_single_recipe` returned `None`, nothing was written to `data/enhanced/`. 3 of 6 sample recipes produced zero output before this fix, directly contradicting the brief's "does it scale beyond the examples we gave" question.

### The fix — a recipe ledger

Tips are now modeled as transactions against an addressable document (`src/llm_pipeline/ledger.py`, `RecipeLedger` / `RecipeDocument` / `Line`):

- every recipe line gets a **stable `line_id`** that survives edits;
- every edit **reads a specific content hash**; if the line no longer holds that hash, the edit is a **stale read** — rejected and blamed on whichever tip got there first, never silently applied;
- a guarded fuzzy match (ratio ≥ 0.82 **and** every distinctive token of the find text present in the candidate line) replaces the old 0.6-threshold whole-line match, so `"1 cup white sugar"` cannot match `"1 cup packed brown sugar"`;
- every committed edit becomes an **invertible ledger entry**, and the whole ledger is **replayed from the original recipe and byte-compared** to the pipeline's own output before anything is trusted (`ledger.verify()` → `ReplayVerification`) — attribution is proven, not claimed;
- every line of the final recipe gets **blame**: which modification(s), which reviewer(s) (`ledger.blame()` → `BlameLine`).

`pipeline.py` now instantiates one `RecipeLedger` per recipe run (not per review, so cross-tip stale-read detection works across the whole run) and calls `ledger.apply_modification(...)` instead of `RecipeModifier.apply_modification(...)`. A modification's `status` is now `applied` / `partial` / `unapplied` depending on how many of its edits committed, and every rejected edit carries a machine-readable `reason` (`no_op`, `superseded`, `no_match`, `missing_payload`, `unsafe_removal`, `duplicate`) plus a human-readable `detail`. **Rank-then-lock:** after a tip commits to a `line_id`, later replace/remove/servings edits on that same line are rejected as `superseded` — so a higher-ranked tip's amount change cannot be overwritten by a later tip that still fuzzy-matches the same ingredient words. `RecipeModifier` is unchanged and still covered by its own unit tests — it's superseded, not deleted.

### Community consensus (confidence layer)

Related comments can agree (“yea brown sugar tastes better”) or warn (“brown sugar makes it lumpy, don’t try it”). `tip_consensus.py` clusters those by shared tip-topic tokens, scores support vs oppose, and attaches a `TipConsensus` object to each tip in the enhanced JSON. **Strong opposition holds auto-apply** (`held_for_opposition`) even if the tip itself is tested; agreement is recorded and visible but **never** lets a weaker tip overwrite a locked line. Featured + stars still decide apply order.

Re-running the live sweep post-fix on the same cookies recipe: the same later review's edit (`find='1 cup white sugar', replace='1 cup white sugar'`) is now rejected as `no_op` (the ledger sees the line already reads `0.5 cup white sugar` and refuses to record a fabricated no-op as an applied change), while that review's *other*, non-conflicting edit (adjusting brown sugar) still commits — the modification's status is honestly `partial` instead of a blanket `applied`. `ledger.verify()` reports `deterministic: true` on that file, with zero mismatches.

Recipes with nothing to apply (Defect B) now produce a real `EnhancedRecipe` with `status="no_changes"`: the untouched original content, every extracted tip still listed with its true unapplied reason, and a still-executed (trivially passing) replay verification — no output is ever silently dropped. Live sweep result: **6/6 sample recipes now produce output** (some `enhanced`, some honestly `no_changes`), versus 3/6 before this fix.

### The trust report

`src/tools/trust_report.py` reads already-produced `data/enhanced/enhanced_*.json` files (no LLM key, no network) and prints a compact per-recipe report: replay verification status, applied/partial/unapplied/rejected-silently counts, every ingredient/instruction line with its blame, and the full list of rejected edits with reasons. This is the artifact meant to make "we proved attribution instead of claiming it" visible in one command:

```bash
PYTHONPATH=src python src/tools/trust_report.py data/enhanced/enhanced_*.json
```

---

## 8. Challenges

1. **Featured signal was already in the data** but unused — product fix, not a scrape rewrite.
2. **Silent apply failures** looked like success until we inspected diffs.
3. **Within-review splitting** required schema + prompt + output shape changes, not just “process more reviews.”
4. **Provider/quota friction** forced pragmatic multi-provider support so validation was honest.
5. **Yield vs servings** — LLM correctly suggested 16 cookies while metadata stayed 48 until we added an explicit servings edit path.
6. **Same-line amount fights** — closed with rank-then-lock; covered by a dedicated regression test that keeps the same ingredient words and only changes quantity.

---

## 9. Tradeoffs

- No UI: the brief asked whether the pipeline works; JSON attribution is enough to inspect.
- No second LLM eligibility call: cost/latency without enough proven gain.
- No new ranking model: featured + stars is enough signal for this dataset.
- Coarse conflict detection only (shared find-target among tested tips) — superseded by the ledger's compare-and-swap + line lock for cross-tip cases; within-review conflict detection code (`modification_conflicts.py`) is left in place but unused by the pipeline.
- Default demo `max_reviews` can stay low for quota; the capability exists and was shown with `max_reviews=2` and, in the post-handoff sweep, `max_reviews=4`.
- Consensus uses transparent phrase cues + topic-token overlap (not a second LLM call) — explainable, cheap, and good enough for this dataset; a richer semantic model can replace the cue lists later without changing the product rule.
- No “saved AI answers” replay mode for fully offline demos — see §10 item 5. Not needed if the demo walks finished JSON + trust report.

---

## 10. Known limitations and future improvements

Still open (honest leftovers):

1. `add_after` / `remove` matching is weaker than `replace`.
2. Soft recall cues still miss some tip phrasings.
3. Inherited few-shot prompt path remains broken; live path uses the simple list-aware prompt.
4. Consensus cue lists are English phrase heuristics — sarcasm, negation edge cases, and non-English reviews can mis-score; a dedicated stance model would tighten this without changing the apply policy.
5. No saved-and-replay AI answers yet. To generate a *new* enhanced recipe from scratch, you still need a live AI API key. The audit tool (`trust_report.py`) already works with no key. Optional convenience only — not required for a demo that uses finished artifacts.

Fixed recently (no longer open):

- ~~Same-line amount overwrite under guarded fuzzy match~~ — **rank-then-lock** rejects later replace/remove/servings edits once a `line_id` has a writer; covered by `tests/test_tip_consensus.py`.
- ~~Fuzzy whole-line overwrite across different ingredients~~ — guarded fuzzy match + ledger verify.
- ~~Recipes with nothing to apply hard-failed~~ — honest `no_changes` outputs.
- ~~Agree/disagree comments ignored~~ — tip consensus confidence layer records support/oppose and can hold auto-apply.

Worth doing next, if this were a real team handoff:

1. Substring parity for `add_after` and `remove`.
2. Richer stance model (or small LLM classify) behind the same `TipConsensus` schema.
3. Optionally save and replay past AI answers so the full generate step can demo with zero API key.
4. Render a servings blame line in `trust_report.py` when a tip changed batch size.

---

## 11. Final summary

The inherited pipeline looked complete but was not trustworthy: random single-review selection, brittle edits, no clean multi-tip model, and later a silent overwrite that still claimed tips were “applied.”

The solution makes the system behave like the product described in the brief:

- prioritize Featured Tweaks, then higher star ratings
- split and attribute discrete community tips
- apply only tested changes through a ledger that rejects stale edits and **locks a line after the higher-ranked tip wins**
- weigh related agree/disagree comments as a confidence layer (opposition can hold auto-apply)
- leave failures, preferences, and rejections visible (including honest `no_changes` outputs)
- prove attribution via replay verification + offline `trust_report.py`
- prove it with focused tests (incl. the original clobber bug and same-line amount lock) and live enhanced artifacts

That matches the spirit of the assignment: budget attention on what most improves trust in an in-progress AI workflow.
