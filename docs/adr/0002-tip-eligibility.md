# Soft tip eligibility + tested-only apply

We decided scraper `has_modification` is a soft hint, not a hard gate: the candidate pool is featured reviews + scraper/regex hints + a small recall cue set. Extraction labels each tip `evidence=tested|untested`, and only tested tips are auto-applied so next-time preferences stay visible without rewriting the recipe.

## Considered Options

- Keep hard `has_modification` filter (rejected: drops real tips like Nikujaga-style “need 1 lb”)
- Second LLM eligibility call (deferred: cost/latency without enough proof yet)
- Soft candidate pool + evidence field in the same extraction call (chosen)

## Consequences

- More reviews reach extraction; praise-only without cues still stays out
- Untested tips appear as `unapplied` and do not participate in within-review conflict checks
- Enhanced JSON records `max_reviews` and `candidates_considered` for budget honesty
- Ranking beyond featured + stars and full scraper rewrite remain out of scope
