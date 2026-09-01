# Trend Discovery Design

## Goal

Add evidence-backed topic discovery for YouTube Shorts, TikTok, and Instagram Reels. Rank global opportunities by their potential to keep viewers listening to faceless narrated videos, then hand a selected topic and content angle to the existing Studio workflow.

The product must call this score **Retention Potential**. Public trend data does not prove measured audience retention.

## Scope

The MVP provides:

- Separate YouTube Shorts, TikTok, and Instagram Reels results.
- Global discovery by aggregating available country-level signals.
- Fast Trend, Durable Opportunity, Emerging, and Unverified classifications.
- Evidence-backed topic clusters and three content angles per topic.
- Filters, manual refresh, cached results, shortlist, and `Use Topic` handoff.
- Explainable scoring, source confidence, timestamps, and safety filtering.

The MVP excludes automatic background polling, predictive trend forecasting, account-connected analytics, social-account credentials, and automatic video generation or publishing.

## Reuse Audit

Live research on 2026-09-01 found no maintained free package that reliably supplies global trends for all three platforms.

| Candidate | License and maintenance | Windows and security | Integration decision |
|---|---|---|---|
| `trendspy` 0.1.6 | MIT; latest PyPI release 2024-12-25 | Pure Python; unofficial Google Trends access may break or rate-limit | Candidate for a replaceable Google Trends adapter, not a system foundation |
| `trends-checker` | MIT; repository active in 2026 | Python CLI; wraps `pytrends`, whose primary repository is archived | Do not embed CLI or inherit archived dependency as core |
| `yt-dlp` | Unlicense; actively maintained in August 2026 | Strong Windows support; public extraction can face platform changes and terms constraints | Reuse only for allowed public metadata if official YouTube data is insufficient |
| Official YouTube Data API | Official and maintained; quota/key required | Stable HTTPS interface; least scraping risk | Preferred YouTube evidence source when configured |
| Public TikTok Creative Center and Instagram public signals | Platform-controlled pages; no dependable free global trend API | Access and structure may change; scraping and terms risk require isolation | Use compliant public evidence where available; otherwise label inferred or unavailable |

Only the missing product-specific layer should be custom: source normalization, historical snapshots, topic clustering, scoring, safety filtering, and Studio handoff. Each source remains replaceable.

## Architecture

```text
Platform evidence
  -> country aggregation
  -> topic normalization and clustering
  -> safety filter
  -> momentum and history analysis
  -> retention-potential scoring
  -> evidence-grounded content angles
  -> ranked platform views
  -> Studio handoff
```

### Source adapters

Each adapter returns a common signal record and owns its timeout, rate limit, parsing, and source-specific confidence. Adapter failure is isolated by platform. The service never stores social-account credentials.

### Trend service

The service aggregates country signals into global evidence, removes duplicates, clusters related phrases without merging distinct stories, reads prior snapshots, assigns classifications, and caches the last successful result.

### Retention scorer

The deterministic score uses normalized evidence:

- Retention/listenability potential: 30%
- Momentum: 20%
- Hook and curiosity strength: 15%
- Durability: 10%
- Cross-platform strength: 10%
- Faceless narrated-video fit: 10%
- Evidence confidence: 5%

The UI exposes component scores and a short explanation. Unverified evidence cannot outrank verified evidence solely because an LLM finds the topic interesting.

### Angle generator

The existing configured LLM generates three angles only after evidence collection. Its prompt receives the stored evidence and must return angles, not new trend claims. Invalid output degrades to the scored topic without angles.

### Storage

Use the repository's existing managed storage patterns. Store normalized snapshots, refresh timestamps, source status, and shortlist entries. Do not add a database for the MVP. Writes must be atomic to avoid losing the last successful cache.

### WebUI integration

Add a `Trend Discovery` navigation page with separate platform tabs. `Use Topic` writes the chosen topic and angle into existing Studio session fields and navigates to Studio; it does not start generation.

## Data Model

A normalized trend result contains:

- Stable cluster identifier and display topic.
- Platform and contributing markets.
- Source type, evidence reference, collection time, and confidence.
- Current signal, prior signal, momentum, and available engagement indicators.
- Classification and all score components.
- Safety status and exclusion reason when filtered.
- Three optional content angles grounded in the evidence.

Evidence references may be URLs or source identifiers. Secrets, cookies, raw credentials, and personal data are never stored.

## Classification

- **Fast Trend:** sharp recent growth with insufficient sustained history.
- **Durable Opportunity:** sustained signal across enough stored snapshots.
- **Emerging:** promising momentum but insufficient evidence for Fast or Durable.
- **Unverified:** inferred, weak, stale, or single-source evidence.

On the first refresh, the system cannot claim durability. It labels results Emerging or Unverified until history exists.

## User Workflow

1. User opens Trend Discovery.
2. Page shows the last successful cache, timestamp, and source status.
3. User optionally selects niche, classification, market coverage, and minimum score.
4. User triggers `Refresh Trends` manually.
5. Each platform updates independently and keeps stale cached results if refresh fails.
6. User expands a ranked card to inspect evidence, score explanation, and content angles.
7. User can shortlist a card or choose `Use Topic`.
8. `Use Topic` fills Studio topic and angle fields, then navigates to Studio.

Default view shows at most 20 global results per platform. Manual refresh controls cost and rate-limit exposure.

## Failure Handling

- Bound every external request with timeout and source-specific rate limits.
- Retry only transient failures with a small capped backoff.
- Keep the last successful cache and label its age when a refresh fails.
- Show unavailable sources and reduced confidence; never fabricate replacement evidence.
- Reject malformed adapter data at the normalization boundary.
- Make cache writes atomic and preserve the previous snapshot on write failure.
- Log operational metadata without response bodies that may contain sensitive or restricted data.

## Safety

Filter adult, graphic, exploitative tragedy, dangerous-instruction, hateful, and clearly unsupported factual topics before ranking. Sensitive news may appear only when evidence is strong and the generated angle avoids exploitation or unsupported claims.

The feature must respect platform terms and robots/access restrictions. When compliant automated collection is unavailable, return an unavailable or inferred state instead of bypassing controls.

## Validation

- Unit tests: normalization, clustering, scoring weights, classifications, confidence caps, and safety filters.
- Adapter contract tests: recorded, sanitized fixtures for each source schema.
- Integration tests: partial-source failure, timeout, stale-cache fallback, atomic snapshot writes, and first-run classification.
- WebUI tests: platform separation, filters, evidence display, refresh state, shortlist, and Studio handoff.
- Evaluation set: manually label representative topics and confirm evidence-backed, listenable topics rank above generic or weakly sourced topics.
- Live acceptance: independently verify current source access and real results on Windows. Mocked and fixture tests do not prove live trend availability.

## Acceptance Criteria

- Three platform tabs display independently ranked results.
- Every visible score has evidence, timestamp, confidence, and component explanation.
- First-run results never claim durability.
- A failed source does not erase other platform results or the last successful cache.
- `Use Topic` fills Studio without starting a task.
- No social-account credential is requested or persisted.
- All affected automated tests pass, followed by separate live-source and browser acceptance evidence.
