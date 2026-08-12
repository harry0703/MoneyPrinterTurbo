# Campaign, Story, and Content Memory Engine

This guide describes the local-first, opt-in campaign workflow introduced alongside MoneyPrinterTurbo's existing manual video workflow. The new path stops at generation-ready data. It does not call MoneyPrinterTurbo's media pipeline, Postiz, Facebook, or any publisher.

## Architecture

The connected flow is:

```text
versioned campaign YAML
  -> deterministic campaign plan
  -> persisted planned item
  -> content-memory eligibility decision
  -> atomic reservation
  -> structured story brief
  -> concept candidates and explainable selection
  -> hook -> beats -> script -> scenes -> captions
  -> actionable validation issues
  -> persisted lineage and fingerprints
  -> canonical legacy MPT payload adapter
  -> existing VideoParams-compatible input (caller controlled)
```

The existing `cli.py`, API controllers, video task, upload service, and manual generation behavior were not replaced. The new CLI is `campaign_cli.py`; it never submits a video task or publishes.

Key modules:

- `app/campaigns/models.py`: versioned typed contracts and lifecycle states.
- `app/campaigns/config.py`: registry, schema loading, compatibility checks, and legacy seed preview.
- `app/campaigns/planner.py`: planning strategy interface and balanced deterministic strategy.
- `app/campaigns/memory.py`: SQLite repository, migrations, fingerprints, duplicate explanations, reports, and reservations.
- `app/campaigns/story.py`: offline staged Story Engine and the injected existing-LLM adapter.
- `app/campaigns/adapter.py`: canonical structured-to-MPT payload mapping.
- `app/campaigns/workflow.py`: feature-gated orchestration through generation-ready content.

## Campaign schema

Campaign files are YAML, JSON, or YML named `campaign.yaml`, `campaign.yml`, or `campaign.json` beneath the configured campaign directory. Schema `1.x` is supported. Unknown fields are rejected so configuration mistakes cannot silently change behavior.

The model covers identity and versioning, enablement, IANA timezone, platforms, content type and aspect, duration limits, cadence, audience problems/interests/motivations, positioning and voice, tone constraints, weighted pillars and themes, story formats, hooks, CTAs, captions, visual styles, seasonal rules, exclusions, safety, cooldowns, campaign stop phrases, seeds, and open-ended metadata.

Pillars carry their own themes, audience goals, allowed formats, hooks, CTAs, and visual treatments. Seeds reference a pillar and theme and may carry source notes, required facts, source status, and metadata.

`CampaignConfig` validates:

- supported schema major version;
- duration ordering;
- unique pillar and seed IDs;
- pillar/theme references;
- allowed and disallowed format consistency.

`validate-compatibility` additionally checks each allowed story format begins with a hook, contains narrative progression, and is available to every pillar that names it.

## Heritage Banner migration

The committed checkout did not contain the described Heritage campaign source, scheduler, Postiz workflow, seed rotator, receipts, or daily marker. Ignored task artifacts did preserve three `campaign.json` receipts and seven Heritage subjects. The new configuration preserves the observed identifiers and behavior:

- campaign ID `heritage-banner-facebook`;
- brand ID `heritage-banner`;
- Facebook only;
- `America/Chicago`;
- daily cadence;
- vertical `9:16`;
- 20–60 seconds;
- 30-day topic cooldown;
- short social captions and the observed Heritage hashtags;
- the seven recovered topics, expanded into a 32-seed supply aligned to the same intent.

The source of truth is `campaigns/heritage-banner/campaign.yaml`. A compatible, deprecated `campaigns/heritage-banner/marketing-plan.json` preserves the legacy seed supply and the exact path recorded in old task receipts. `migrate-seeds` only previews differences; it never edits either file or ignored task history.

No existing publication receipt, daily-completion marker, or task output is deleted or rewritten. A deployment that has additional legacy data should export it, run the migration preview, and reconcile it manually before enabling the new path.

## Planning

`CampaignPlanningStrategy` is the extension point. `BalancedDeterministicStrategy` implements the initial strategy. Given the same campaign, start date, day count, target platforms, random seed, history state, and injected creation timestamp, it produces identical IDs and selections.

The strategy:

- evaluates dates in campaign local time and records timezone-aware UTC windows;
- follows configured weekdays;
- rejects seeds still in topic cooldown;
- never repeats a seed immediately;
- prevents adjacent theme reuse when another theme is eligible;
- balances prior pillar, theme, seed, format, hook, and CTA counts;
- rotates formats rather than allowing one to dominate;
- raises eligible seasonal seed weights;
- uses a stable hash only as the final tie-breaker;
- emits a decision record with selection factors and rejected-seed explanations;
- emits no item, rather than silently reusing a recent topic, when the pool is exhausted.

Stable plan and item IDs make persistence retry-safe. SQLite also enforces one planned item per campaign, local date, and platform.

Lifecycle states are `planned`, `reserved`, `generating`, `generated`, `awaiting_review`, `approved`, `publishing`, `published`, `rejected`, `failed`, `skipped`, and `cancelled`.

## Story Engine

The Story Engine does not request an entire video response as one prompt. Every stage is typed and separately inspectable:

1. Story brief
2. Concept candidates
3. Selected concept
4. Hook
5. Ordered story beats
6. Structured narration
7. Scene plan
8. Caption package
9. Validation issues

`RuleBasedConceptGenerator` is deterministic and offline. It produces multiple candidates. `StoryEngine.select_concept` records a score breakdown for campaign fit, audience relevance, novelty, clarity, emotional potential, visual potential, duration fit, CTA fit, and safety. Memory similarity reduces the novelty component. The highest total wins, with a stable concept ID tie-breaker.

`LegacyLlmConceptAdapter` wraps the current `app.services.llm.generate_script` signature through dependency injection. Importing or testing the adapter does not call an LLM. Callers must explicitly construct and invoke it.

### Story formats

Beat patterns and hook patterns are configuration, not Python conditionals. Heritage defines all of these templates while enabling only the formats suitable for the campaign:

- reflective question;
- micro-history;
- family-memory prompt;
- tradition spotlight;
- before-and-after;
- three-part lesson;
- myth versus reality;
- object-centered story;
- place-centered story;
- first-person anecdotal frame;
- mini mystery;
- emotional reveal;
- list with narrative progression;
- quote or saying with interpretation;
- community engagement prompt.

Disallowed templates remain available to future campaigns but cannot be selected for Heritage.

### Hooks, beats, narration, and duration

Hooks are separate records with hook type, desired response, estimated duration, novelty fingerprint, alternatives, risks, and reasoning. Beats specify purpose, key information, emotional function, word/duration budgets, visual objective, transitions, required facts, and supporting details.

Narration records segments linked to beats. Duration is `word count / configurable words per minute`; the default is 150 WPM. The estimate method and rate are stored with the script. Character count is not used as the duration estimate.

### Scene plan and captions

Each narration segment receives one timed scene with subject, setting, action, shot, motion, transition, stock search terms, optional structured visual prompt, continuity, safety note, and fingerprint. Tests need no images or external media APIs.

The caption package contains primary and short captions, first and pinned-comment suggestions, community question, CTA, hashtags, accessibility text, platform variants, and its own fingerprint. It is not published.

### Source status

The story brief distinguishes creative or reflective work from claims requiring research:

- `source_not_required`
- `source_recommended`
- `source_required`
- `source_verified`
- `blocked_pending_source`

`source_required` and `blocked_pending_source` produce validation errors until verification is recorded. The engine never invents citations and does not require online research.

### Validation

Validation returns a list of errors and warnings, each with a code, stage, message, and suggested action. Checks include hook presence/reuse, beat progression, formats, duration and words, CTA, repetition, contradictions, placeholders, generic openings, disclaimers, rhetorical questions, source status, exclusions, tone, unsafe or private-person language, living-artist imitation phrasing, narration/scene alignment, and visual variety.

Errors stop the workflow before an MPT payload is produced. Warnings remain inspectable and can be handled according to feature flags and review policy.

### Regeneration and lineage

`StoryEngine.regenerate` supports `hook`, one `beat`, `script`, `scene_plan`, `caption`, `alternate_concept`, or `validation`. An alternate concept is appended to the candidate set and its dependent hook, beats, script, scenes, and caption are rebuilt. Each changed stage records a stage version and parent stage ID. Each package records a story version and parent story version. Preserved stages remain byte-for-byte unchanged. Regenerating a prerequisite independently may intentionally create an alignment warning until dependent stages are regenerated.

## Content Memory

SQLite is used because existing task state is transient process memory or optional Redis and has no durable content migration convention. The default file is ignored local storage at `storage/campaigns/content-memory.sqlite3`. Importing a module does not create it. The repository creates it only when a persistence method is explicitly used.

Migration `001_campaign_story_memory` adds plans, planned items/reservations, memory records, and duplicate-decision audit records. Both up and down SQL are committed. `migration-preview` is read-only and reports pending migrations. Rollback SQL is intentionally manual because it removes new engine data; back up the database and execute the down file only as an explicit rollback operation.

Memory records retain campaign/planned/story/generation/publication IDs; pillar/theme/seed; distinct fingerprints; hook text; visual and search-term fingerprints; media hashes; platform and dates; external receipt fields; lifecycle, rejection and failure reasons; lineage and supersession; series data; metric placeholders; and the structured story package and payload provenance.

Rejected and failed concepts are retained. They are not silently forgotten and may be reported separately from published content.

### Normalization and fingerprints

Text normalization uses Unicode NFKC, case folding, whitespace collapse, punctuation removal, repeated-punctuation collapse, and configured boilerplate stop-phrase removal. Caption hashtag order is canonicalized. SHA-256 includes an artifact-type namespace, so identical text used as a hook and a script has different fingerprints.

Duplicate terms mean different things:

- Exact duplicate: byte-identical input or identical media hash.
- Normalized duplicate: text differs only in normalized formatting, case, punctuation, hashtag order, or configured boilerplate.
- Structural duplicate: a beat or scene structure has the same canonical JSON representation.
- Topic reuse: a topic fingerprint appears within topic cooldown.
- Hook reuse: a hook fingerprint appears within hook cooldown.
- Script reuse: narration fingerprint reuse, normally a hard block for a long period.
- Media reuse: final or source media hash reuse, independent of text reuse.

These fingerprints are never collapsed into one generic content hash.

`ApproximateSimilarity` is an interface. `TokenJaccardSimilarity` is the dependency-free implementation. A warning records method, score, threshold, artifact, matching IDs, and recommended action. Future MinHash or embedding adapters can implement the same interface without adding vector infrastructure to the current runtime.

### Cooldowns and explainability

Campaigns may independently configure topic, theme, hook, story format, script, caption, visual concept, and media cooldowns. Exact or normalized matches within cooldown block when duplicate blocking is enabled. Matches outside cooldown warn. CTA-only overlap is explicitly allowed.

Every check returns one of `allowed`, `allowed_with_warning`, `blocked`, `exact_duplicate`, `recent_topic`, `recent_hook`, `recent_script`, `recent_media`, `intentional_series_match`, `insufficient_history`, or `comparison_error`, along with the reason, record IDs, comparison evidence, rule, days since prior use, and next action.

### Intentional series

Planned items and memory records may include a series ID/title, episode number, adjacent episodes, recurring-format allowance, continuity requirements, permitted overlap types, and completion status. A same-series match is allowed only when recurring overlap is explicitly enabled and the artifact type appears in `permitted_overlap`.

### Reservations and retries

Selection uses `BEGIN IMMEDIATE` and a conditional row update. Reservation data includes worker, timestamp, expiration, idempotency key, and attempt count. Exactly one concurrent worker receives a new reservation. Other workers receive `already_reserved`; a retry with the same key receives the original reservation as an idempotent replay. Expired reservations can be released automatically or explicitly. A generated item remains tied to its idempotency key, so a same-key workflow retry reloads the stored story lineage instead of generating it again.

A published memory record for a campaign local date returns `already_completed_today`. No machine-UTC date is used for daily selection.

## Legacy MPT payload adapter

The canonical script source is `StoryPackage.script.full_narration`. It is mirrored to both `script` and `video_script`. The canonical search terms are the ordered, de-duplicated `Scene.stock_search_terms`; they are mirrored to `search_terms` and `video_terms`.

Contradictory aliases are rejected. Empty top-level or nested required values are rejected before task submission. Every field records provenance as story output, campaign default, user override, or legacy fallback. Use of a legacy override or fallback emits a deprecation warning.

`StructuredMptPayloadAdapter.task_params()` returns only keys accepted by the existing `VideoParams`. It does not submit a task. The structured campaign context, scene plan, captions, IDs, fingerprints, and provenance remain stored separately rather than being discarded to fit the legacy model.

## Feature flags

All flags default to `false` in `config.example.toml`:

- `campaign_engine`
- `story_engine`
- `content_memory`
- `structured_mpt_payload_adapter`
- `automatic_daily_campaign_planning`
- `memory_duplicate_blocking`
- `memory_duplicate_warnings`

The current manual CLI and generation task do not consult these flags and therefore retain their old behavior. `CampaignWorkflow` requires the first three flags. It only returns an MPT payload when the structured adapter flag is enabled. Automatic planning has no scheduler wiring in this change; it is a future integration gate and remains off.

## CLI

Run commands from the repository root:

```powershell
python campaign_cli.py validate
python campaign_cli.py list
python campaign_cli.py show heritage-banner-facebook
python campaign_cli.py validate-compatibility heritage-banner-facebook
python campaign_cli.py plan-preview heritage-banner-facebook --start-date 2026-08-06 --days 7 --seed 42
python campaign_cli.py plan-save heritage-banner-facebook --start-date 2026-08-06 --days 7 --seed 42
python campaign_cli.py why-selected heritage-banner-facebook --start-date 2026-08-06 --days 7 --seed 42
python campaign_cli.py why-skipped heritage-banner-facebook --start-date 2026-08-06 --days 7 --seed 42
python campaign_cli.py next heritage-banner-facebook
python campaign_cli.py select-today heritage-banner-facebook --worker dev --idempotency-key heritage-2026-08-06
python campaign_cli.py recent heritage-banner-facebook
python campaign_cli.py find-topic heritage-banner-facebook "a familiar gathering place"
python campaign_cli.py find-hook heritage-banner-facebook "What does this place remember?"
python campaign_cli.py find-script heritage-banner-facebook "Proposed script"
python campaign_cli.py usage heritage-banner-facebook
python campaign_cli.py activity heritage-banner-facebook
python campaign_cli.py lineage heritage-banner-facebook
python campaign_cli.py release-stale
python campaign_cli.py rebuild-fingerprints heritage-banner-facebook
python campaign_cli.py audit heritage-banner-facebook
python campaign_cli.py export heritage-banner-facebook --format json
python campaign_cli.py migrate-seeds heritage-banner-facebook
python campaign_cli.py migration-preview
python campaign_cli.py prepare heritage-banner-facebook --worker dev --idempotency-key heritage-2026-08-06
```

`plan-preview`, `why-selected`, `why-skipped`, `next`, `migrate-seeds`, `validate`, `list`, `show`, `validate-compatibility`, and `migration-preview` are read-only. `plan-save`, `select-today`, `prepare`, `release-stale`, `rebuild-fingerprints`, and audited duplicate searches mutate only the selected local SQLite file. No command publishes.

## Local testing

Focused tests:

```powershell
python -X utf8 -m unittest discover -s test/campaigns -p "test_*.py" -v
```

Complete suite:

```powershell
python -X utf8 -m unittest discover -s test -p "test_*.py" -v
```

Repository CI's deterministic subset remains:

```powershell
python -X utf8 -m unittest test.services.test_state test.services.test_task test.services.test_schema test.services.test_webui_i18n
```

Compile check:

```powershell
python -m compileall app campaign_cli.py cli.py main.py webui test
```

Tests use temporary SQLite databases, the rule-based provider, and mock receipt data. They do not call LLMs, media providers, Postiz, Facebook, or home-network services.

## Migration, rollback, and manual verification

Before enabling any feature in a production-like checkout:

1. Back up existing scheduler files, publication receipts, daily markers, and campaign history.
2. Run `validate`, `validate-compatibility`, `migrate-seeds`, and `migration-preview`.
3. Export or adapt any campaign assets absent from this checkout and compare them with the 32 committed seeds.
4. Use a disposable database to run `plan-preview`, `plan-save`, `next`, and `prepare`.
5. Inspect story validation, payload provenance, duration, ordered terms, and the generated/failed memory record.
6. Simulate a publisher receipt through application code and confirm a retry returns `already_completed_today`.
7. Enable flags one at a time. Keep automatic planning and publishing disconnected until focused integration review is complete.
8. If rollback is required, disable all flags first. Preserve/export the SQLite file. Run the down migration only against the new campaign database; do not delete old task artifacts or receipts.

The bridge can now opt into this engine through the versioned `bridge-v1` CLI profile, carry stable creative lineage through generation, and record the observed terminal generation result. Publication and provider state intentionally remain bridge-owned; MPT does not receive publication receipts. Production activation, reconciliation of historical Heritage data, and Windows Task Scheduler changes remain separate operator decisions.
