# Trend Discovery acceptance

Date: 2026-09-02 (Asia/Calcutta)

## Scope

Trend Discovery samples public evidence for US, IN, GB, CA, and AU on manual refresh. Google Trends RSS is the seed source. Official YouTube `videos.list?chart=mostPopular` evidence is optional and used only when `youtube_data_api_key` is configured. TikTok and Instagram Reels results remain explicitly inferred.

Retention Potential is a deterministic predictive score, not measured viewer retention. First-run snapshots cannot be classified as durable. The feature does not collect social credentials, poll in the background, generate videos automatically, or publish content.

## Automated and static verification

Command:

```powershell
uv run --no-sync pytest -q test/services/trends test/services/test_llm.py test/services/test_webui_trend_discovery.py test/services/test_webui_navigation_dashboard.py test/services/test_webui_generation_defaults.py test/services/test_webui_task.py
```

Result: 127 passed, 1 skipped, 1 warning in 17.55 seconds. The skip was the credential-gated live LLM integration test. The warning was an existing Starlette `TestClient` deprecation warning.

The following gates also passed:

```powershell
uv run --no-sync python -m compileall app/services/trends webui/Main.py
uv run --no-sync ruff check app/services/trends test/services/trends test/services/test_webui_trend_discovery.py
git diff --check
```

These are scoped technical checks, not whole-repository release certification.

## Live Windows source acceptance

At `2026-09-02T05:38:44.354719+00:00`, Google Trends RSS returned 50 signals across AU, CA, GB, IN, and US. YouTube configuration was absent; the adapter returned `unavailable`, performed no key-backed acceptance, and exposed no key.

At `2026-09-02T05:39:01.036965+00:00`, a disposable end-to-end refresh produced 20 YouTube Shorts, 20 TikTok, and 20 Instagram Reels results. No first-run item was durable. TikTok and Instagram labels were exclusively `inferred`; the snapshot was fresh.

Fixture tests cover YouTube mapping, retry bounds, missing-key behavior, and the rule that only topics with official YouTube evidence receive verified confidence. Real key-backed YouTube acceptance remains pending until an owner supplies a key through existing configuration handling.

## Browser acceptance

Playwright drove the real Streamlit app at `http://127.0.0.1:8502` between 05:40 and 05:48 UTC. Verified:

- Manual refresh rendered the live source timestamp and source availability.
- YouTube Shorts, TikTok, and Instagram Reels appeared as separate tabs.
- Classification, market, and minimum-score filters were keyboard-addressable.
- Cards exposed classification, confidence, contributing markets, score components, timestamps, and Google evidence links.
- Non-Latin Punjabi and Tamil topics rendered with unique widget keys.
- A shortlist click persisted one entry; the acceptance entry was then removed.
- `Use Topic` navigated to Studio and filled the video subject without submitting generation.
- A 390 x 844 viewport rendered the page, and Tab navigation produced a visible active focus target.

Live on-demand LLM angle generation was not invoked because it can consume the configured provider's quota. Strict response validation and selected-topic cache updates are covered by automated tests.

## Known limits

- Google RSS and optional YouTube evidence do not provide native TikTok or Instagram trend measurements.
- Public endpoints can rate-limit or change; bounded retries and stale-cache fallback reduce impact but cannot guarantee availability.
- Exact-phrase clustering intentionally avoids semantic merging in this MVP.
- Safety filtering is conservative keyword screening, not editorial or factual review.
- Automated and browser checks do not prove media rendering, provider credentials, or release readiness.
