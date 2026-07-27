# Extract a Modification set per Review

We decided one Review can yield many discrete Modifications in a single extraction call, returned as a ModificationSet list, because Casper's brief treats "I added an egg and halved the sugar" as two tips — not one blob — and users must inspect which tip was applied and why without thinking the AI invented extras.

## Considered Options

- One ModificationObject per Review (old behavior)
- Two AI calls per Review
- Post-hoc splitting of one blob in code
- One AI call returning a list (chosen)

## Consequences

- Enhanced JSON now has flat `modifications_applied` (each with `source_review` + `status`) and grouped `modifications_by_review`
- Unapplied tips stay visible with reasons; within-review conflicts are shown but not auto-applied
- Soft tip eligibility and tested-only apply are covered in `0002-tip-eligibility.md`
