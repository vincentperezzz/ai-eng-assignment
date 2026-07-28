# Recipe Enhancement Platform

Automatically enhances recipes by analyzing and applying community-tested modifications from AllRecipes.com. Uses LLM processing to extract meaningful recipe tweaks and apply them with full citation tracking.

## Installation

This project uses [`uv`](https://docs.astral.sh/uv/) for fast, reliable Python package management.

### Prerequisites

- Python 3.13+
- `uv` package manager

## Setup

```bash
# Install dependencies
uv venv
source .venv/bin/activate
uv pip sync pyproject.toml
```

### Environment Variables

Create a `.env` file in the project root:

```env
# Option 1: Google AI Studio / Gemini
LLM_PROVIDER=gemini
GEMINI_API_KEY=your-google-ai-studio-key-here

# Option 2: OpenAI
# LLM_PROVIDER=openai
# OPENAI_API_KEY=your-openai-api-key-here

# Optional overrides
# LLM_MODEL=gemini-3.5-flash
# LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
```

The repo now supports either provider:

- `gemini` via Google AI Studio using the OpenAI-compatible Gemini endpoint
- `openai` via the standard OpenAI API

If `LLM_PROVIDER` is not set, the code will prefer `GEMINI_API_KEY` when present, otherwise it falls back to `OPENAI_API_KEY`.

The loader will read either `./.env` or `./.venv/.env`, so an existing virtualenv-local secret file also works.

## Usage

### 1. Scrape Recipes (Optional - data already provided)

```bash
uv run python src/scraper_v2.py
```

### 2. Run Recipe Enhancement Pipeline

```bash
# Test single recipe (chocolate chip cookies)
uv run python src/test_pipeline.py single

# Process all recipes
uv run python src/test_pipeline.py all

# Run focused unit tests
uv run python -m unittest discover -s tests -v
```

### Quota-Aware Gemini Usage

Google AI Studio free-tier limits are tight enough that the default live checks intentionally stay small:

- `single` defaults to `SINGLE_RECIPE_MAX_REVIEWS=1`
- `all` supports `ALL_RECIPES_MAX_FILES` and `ALL_RECIPES_MAX_REVIEWS`

Example PowerShell smoke test:

```powershell
$env:ALL_RECIPES_MAX_FILES='2'
$env:ALL_RECIPES_MAX_REVIEWS='1'
uv run python src/test_pipeline.py all
```

This keeps the batch validation under a small request budget while still exercising the live extraction path.

## Verified Validation

Validated locally on 2026-05-25:

- `uv run python -m unittest discover -s tests -v` -> 7 tests passed
- `uv run python src/test_pipeline.py single` -> succeeded with Gemini and wrote `data/enhanced/enhanced_10813_best-chocolate-chip-cookies.json`
- quota-aware batch run with `ALL_RECIPES_MAX_FILES=2` and `ALL_RECIPES_MAX_REVIEWS=1` -> processed 1 of 2 recipes successfully and wrote `data/enhanced/pipeline_summary_report.json`

The controlled batch run is intended as a free-tier smoke test, not a claim that Gemini free tier is stable enough for a full unrestricted sweep across all recipes.

## Output

### Enhanced Recipes

Enhanced recipes are saved in `data/enhanced/`:

- `enhanced_[recipe_id]_[recipe-name].json` - Individual enhanced recipes with modifications applied
- `pipeline_summary_report.json` - Summary of all processing results

### Data Structure

Original scraped recipes in `data/` directory contain reviews with `has_modification: true` flags. Enhanced recipes include:

```json
{
  "recipe_id": "10813_enhanced",
  "title": "Best Chocolate Chip Cookies (Community Enhanced)",
  "ingredients": ["1 cup butter", "1 additional egg yolk", ...],
  "modifications_applied": [
    {
      "source_review": {
        "text": "I added an egg and halved the sugar",
        "rating": 5
      },
      "modification_type": "addition",
      "reasoning": "Extra egg improves structure",
      "status": "applied",
      "changes_made": [...]
    },
    {
      "source_review": {
        "text": "I added an egg and halved the sugar",
        "rating": 5
      },
      "modification_type": "quantity_adjustment",
      "reasoning": "Less sugar reduces sweetness",
      "status": "applied",
      "changes_made": [...]
    }
  ],
  "modifications_by_review": [
    {
      "source_review": { "text": "I added an egg and halved the sugar", "rating": 5 },
      "modifications": ["...same two tips grouped under one review..."]
    }
  ],
  "enhancement_summary": {
    "total_changes": 2,
    "change_types": ["addition", "quantity_adjustment"],
    "expected_impact": "..."
  }
}
```

One review can yield multiple discrete tips. Each tip keeps `source_review` so counts stay explainable, and `modifications_by_review` groups them for inspection.

## How It Works

The LLM Analysis Pipeline processes recipes in 3 steps:

1. **Review Prioritization**: Deduplicates review text, prioritizes featured tweaks, and orders remaining modification reviews by signal
2. **Tweak Extraction**: Extracts structured changes from multiple prioritized reviews
3. **Recipe Modification & Attribution**: Applies changes sequentially and generates an enhanced recipe with full attribution back to each source review

Each run produces one enhanced recipe per original recipe, with complete attribution showing what changed, which review suggested it, and the aggregate impact of the applied community tweaks.

## Trust report

`src/tools/trust_report.py` reads already-produced `data/enhanced/enhanced_*.json` files and prints a compact, auditor-facing summary for each recipe: whether the ledger's replay verification is deterministic, how many modifications landed (`applied`/`partial`/`unapplied`), a per-line blame view of the ingredients and instructions (which community tip and reviewer is responsible for each changed line), and every rejected edit with a plain-English reason.

This tool makes **no network or LLM calls** — it only parses JSON the pipeline already wrote, so it runs with no API key configured at all:

```bash
PYTHONPATH=src python src/tools/trust_report.py data/enhanced/enhanced_*.json
```

Sample output shape:

```
Best Chocolate Chip Cookies (Community Enhanced)                    [ENHANCED]
  replay verification: DETERMINISTIC (14 entries replayed, 0 mismatches)
  6 applied - 1 partial - 2 unapplied - 0 rejected-silently
  ---
  ingredients:
    1 cup butter, softened                                    (original)
    0.5 cup white sugar                          <- rev:7c177579#0 (unknown reviewer)
    ...
  rejected:
    - replace on ingredients (rev:2625a5a8): no_op -- "1 cup white sugar"
```

This is the mechanism behind §7 of `ASSESSMENT.md` ("Post-handoff hardening: provable attribution") — every applied/partial modification's committed edits are backed by a `RecipeLedger` (`src/llm_pipeline/ledger.py`) that replays from the original recipe and byte-compares the result to the pipeline's own output before anything is reported as trustworthy.

## Development

```bash
# Add dependencies
uv add <package_name>

# Run tests
uv run python -m unittest discover -s tests -v
```
