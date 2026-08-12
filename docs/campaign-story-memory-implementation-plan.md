# Campaign, Story, and Content Memory implementation plan

Starting point: `main` at `749b0b22b384967599bda8bf6f04243e1242396a` on 2026-08-06.

The checkout contains no committed Heritage Banner campaign, Postiz scheduler, seed rotator, publication receipts, or daily completion implementation. Ignored task output does contain three Heritage `campaign.json` receipts and seven Heritage subjects. The migration therefore preserves those observed identifiers and topics, adds a compatible legacy `marketing-plan.json`, and does not modify ignored task output.

Implementation order:

1. Add a strict v1 YAML campaign schema and a Heritage configuration with the established Facebook, America/Chicago, 9:16, 20–60 second, daily, and 30-day defaults.
2. Add deterministic balanced planning and atomic SQLite plan reservation behind disabled-by-default feature flags.
3. Add an offline structured Story Engine with provider-neutral concept generation and an adapter for the existing LLM script function.
4. Add typed Content Memory records, distinct fingerprints, exact/normalized checks, local token similarity, cooldown explanations, lineage, exports, and reversible migrations.
5. Add a canonical adapter that mirrors structured script/search terms into current MPT fields without calling the generation task.
6. Add a developer CLI, focused tests, integration tests, documentation, and verification results.

The existing manual `cli.py`, video task, cross-post service, and any external publisher remain unchanged. No new path calls a publisher.

