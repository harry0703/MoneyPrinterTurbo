# Trend Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Add evidence-backed, retention-potential topic discovery with separate YouTube Shorts, TikTok, and Instagram Reels results and safe Studio handoff.

**Architecture:** Google Trends public RSS supplies global seed evidence, while optional official YouTube Data API results strengthen YouTube ranking. A focused service package normalizes evidence, stores atomic snapshots, applies deterministic scoring, and clearly labels TikTok and Instagram results as inferred; existing LLM routing generates angles only on demand from stored evidence.

**Tech Stack:** Python 3.11+, requests, stdlib XML/JSON/dataclasses, existing LLM service, Streamlit, pytest.

**Spec:** docs/superpowers/specs/2026-09-01-trend-discovery-design.md

## Global Constraints

- Preserve unrelated dirty changes. Before execution, owner must checkpoint current dashboard/duration work or approve in-place execution because WebUI files already contain uncommitted work.
- Add no dependency; reuse requests and xml.etree.ElementTree.
- Sample global markets: US, IN, GB, CA, AU. Always display contributing markets.
- YouTube uses official videos.list chart=mostPopular only when youtube_data_api_key exists.
- TikTok and Instagram MVP results are inferred. Never scrape authenticated or restricted endpoints.
- Store no cookies, social credentials, personal data, or raw secret-bearing responses.
- Name score Retention Potential, never measured retention.
- First refresh cannot classify any topic as durable.
- External calls use timeout (3.05, 10), one transient retry maximum, and manual refresh.
- Use Topic fills Studio and never starts generation.

---

### Task 1: Models, safety, clustering, and scoring

**Files:**

- Create: app/services/trends/__init__.py
- Create: app/services/trends/models.py
- Create: app/services/trends/scoring.py
- Test: test/services/trends/test_scoring.py

**Interfaces:**

- models.py exports TrendSignal, TopicCandidate, ScoredTopic, SourceStatus, TrendSnapshot.
- scoring.py exports normalize_topic(text), is_safe_topic(text), cluster_signals(signals), score_topic(candidate, previous).
- ScoredTopic contains classification, retention_potential 0..100, components, confidence_label, evidence, and angles.

- [ ] **Step 1: Write failing tests**

In the test file, define a local `signal(topic, market, rank)` factory that
returns `TrendSignal` with fixed UTC collection time and public source reference.

    def test_first_snapshot_is_never_durable():
        candidate = cluster_signals([signal("Ocean mystery", "US", rank=1)])[0]
        result = score_topic(candidate, previous=None)
        assert result.classification != "durable"
        assert sum(result.components.values()) == result.retention_potential

    def test_cluster_merges_equivalent_phrases_only():
        results = cluster_signals([
            signal("Mars mystery", "US", 1),
            signal("mars-mystery!", "IN", 2),
            signal("Mars mission launch", "GB", 1),
        ])
        assert [item.topic for item in results] == [
            "Mars mystery", "Mars mission launch"
        ]
        assert results[0].markets == {"US", "IN"}

    def test_safety_filter_rejects_graphic_and_dangerous_topics():
        assert not is_safe_topic("graphic death footage")
        assert not is_safe_topic("instructions to build a bomb")
        assert is_safe_topic("why deep ocean exploration is difficult")

- [ ] **Step 2: Run RED**

Run: uv run --no-sync pytest -q test/services/trends/test_scoring.py

Expected: import failure because app.services.trends is absent.

- [ ] **Step 3: Implement minimum pure functions**

Use frozen dataclasses for evidence. Normalize via casefold, punctuation-to-space, and whitespace collapse. Merge exact normalized phrases only; do not add embeddings.

Component weights:

    listenability = 30
    momentum = 20
    curiosity = 15
    durability = 10
    cross_platform = 10
    faceless_fit = 10
    evidence_confidence = 5

Clamp inputs to 0..1, multiply by component weight, round each component once, and total component points. Rank, market convergence, source confidence, and prior snapshots drive evidence-based components. Conservative keyword rules drive listenability, curiosity, faceless fit, and safety.

- [ ] **Step 4: Run GREEN and Ruff**

Run: uv run --no-sync pytest -q test/services/trends/test_scoring.py

Run: uv run --no-sync ruff check app/services/trends test/services/trends/test_scoring.py

- [ ] **Step 5: Commit owned files**

    git add app/services/trends test/services/trends/test_scoring.py
    git commit -m "feat(trends): add evidence scoring model"

---

### Task 2: Atomic snapshots and shortlist

**Files:**

- Create: app/services/trends/storage.py
- Test: test/services/trends/test_storage.py

**Interfaces:**

- TrendStore(base_dir=None) defaults to utils.storage_dir("trends", create=True).
- Methods: load_latest(), load_previous(), save_snapshot(snapshot), list_shortlist(), add_shortlist(topic), remove_shortlist(topic_id).

- [ ] **Step 1: Write failing tests**

In the test file, define `sample_snapshot` and `snapshots` fixtures using the
Task 1 dataclasses; keep their collection times one day apart.

    def test_snapshot_write_keeps_latest_and_previous(tmp_path, snapshots):
        store = TrendStore(str(tmp_path))
        store.save_snapshot(snapshots[0])
        store.save_snapshot(snapshots[1])
        assert store.load_latest().collected_at == snapshots[1].collected_at
        assert store.load_previous().collected_at == snapshots[0].collected_at
        assert not list(tmp_path.glob("*.tmp"))

    def test_broken_latest_falls_back_to_last_good(tmp_path, snapshot):
        store = TrendStore(str(tmp_path))
        store.save_snapshot(snapshot)
        (tmp_path / "latest.json").write_text("{broken", encoding="utf-8")
        assert store.load_latest().collected_at == snapshot.collected_at

- [ ] **Step 2: Run RED**

Run: uv run --no-sync pytest -q test/services/trends/test_storage.py

Expected: storage module missing.

- [ ] **Step 3: Implement atomic JSON storage**

Write UTF-8 JSON to a same-directory temporary file, flush and close, then os.replace. Validate latest before copying it to previous. Maintain last_good.json. Apply the same helper to shortlist.json. Never serialize credentials or raw response bodies.

- [ ] **Step 4: Run GREEN and commit**

Run: uv run --no-sync pytest -q test/services/trends/test_storage.py test/services/trends/test_scoring.py

    git add app/services/trends/storage.py test/services/trends/test_storage.py
    git commit -m "feat(trends): persist atomic trend snapshots"

---

### Task 3: Public evidence adapters

**Files:**

- Create: app/services/trends/sources.py
- Modify: config.example.toml
- Test: test/services/trends/test_sources.py
- Create: test/resources/trends/google_trends_us.xml
- Create: test/resources/trends/youtube_most_popular.json

**Interfaces:**

- GoogleTrendsRssSource(session).fetch(markets, collected_at) returns signals and SourceStatus.
- YouTubeMostPopularSource(session, api_key).fetch(markets, collected_at) returns signals and SourceStatus.
- Google endpoint: https://trends.google.com/trending/rss?geo={market}
- YouTube endpoint: https://www.googleapis.com/youtube/v3/videos with part=snippet,statistics, chart=mostPopular, maxResults=50, regionCode.

- [ ] **Step 1: Add sanitized fixtures and failing contract tests**

Define `fixed_time` and a small `fake_session` fixture in the test file. The
fake records calls and returns fixture bytes through the same `.get()` and
`.raise_for_status()` surface used by production code.

    def test_google_source_maps_market_rank_and_reference(fake_session):
        fake_session.reply_file("test/resources/trends/google_trends_us.xml")
        signals, status = GoogleTrendsRssSource(fake_session).fetch(
            ("US",), fixed_time
        )
        assert [(s.market, s.rank) for s in signals] == [("US", 1), ("US", 2)]
        assert status.available

    def test_youtube_without_key_skips_network(fake_session):
        signals, status = YouTubeMostPopularSource(fake_session, "").fetch(
            ("US",), fixed_time
        )
        assert signals == []
        assert status.reason == "youtube_data_api_key_not_configured"
        assert fake_session.calls == []

- [ ] **Step 2: Run RED**

Run: uv run --no-sync pytest -q test/services/trends/test_sources.py

Expected: sources module missing.

- [ ] **Step 3: Implement bounded adapters**

Use requests.Session.get with timeout=(3.05, 10), raise_for_status, and one retry only for timeout, connection failure, 429, or 5xx. Parse RSS with ElementTree and reject wrong roots. Never log YouTube query parameters. Add commented youtube_data_api_key="" to config.example.toml.

- [ ] **Step 4: Run GREEN, Ruff, and commit**

Run: uv run --no-sync pytest -q test/services/trends/test_sources.py

Run: uv run --no-sync ruff check app/services/trends/sources.py test/services/trends/test_sources.py

    git add app/services/trends/sources.py config.example.toml test/services/trends/test_sources.py test/resources/trends
    git commit -m "feat(trends): collect public trend evidence"

---

### Task 4: Aggregation, history, platform projection, and fallback

**Files:**

- Create: app/services/trends/service.py
- Test: test/services/trends/test_service.py

**Interfaces:**

- TrendDiscoveryService(store, google_source, youtube_source)
- Methods: refresh(), get_cached(), shortlist(topic_id), remove_shortlist(topic_id).
- Snapshot platform keys: youtube_shorts, tiktok, instagram_reels.
- Default markets: US, IN, GB, CA, AU.

- [ ] **Step 1: Write failing orchestration tests**

Build local fake source and store fixtures in this test file. Each fake returns
real Task 1 dataclasses, so tests exercise orchestration rather than mock shapes.

    def test_refresh_keeps_platforms_separate(service):
        snapshot = service.refresh()
        assert set(snapshot.platforms) == {
            "youtube_shorts", "tiktok", "instagram_reels"
        }
        assert snapshot.platforms["youtube_shorts"][0].confidence_label == "verified"
        assert snapshot.platforms["tiktok"][0].confidence_label == "inferred"
        assert snapshot.platforms["instagram_reels"][0].confidence_label == "inferred"

    def test_all_sources_failed_returns_stale_cache(service_with_failures, cached):
        result = service_with_failures.refresh()
        assert result.stale
        assert result.collected_at == cached.collected_at
        assert not result.source_status["google_trends"].available

- [ ] **Step 2: Run RED**

Run: uv run --no-sync pytest -q test/services/trends/test_service.py

Expected: service module missing.

- [ ] **Step 3: Implement orchestration**

Fetch sources, normalize, cluster, remove unsafe candidates, match previous
clusters by normalized key, score, and project:

- YouTube combines Google and official YouTube evidence.
- TikTok and Instagram use Google evidence with bounded platform-fit component adjustments and inferred confidence.
- Native-source absence can never produce verified TikTok/Instagram cards.
- Sort by total, confidence, then normalized topic; keep 20 per platform.
- If every source fails, return latest cache with stale=True and current failure statuses.
- Save a new atomic snapshot when at least one source succeeds.

- [ ] **Step 4: Run GREEN and commit**

Run: uv run --no-sync pytest -q test/services/trends

    git add app/services/trends/service.py test/services/trends/test_service.py
    git commit -m "feat(trends): rank platform topic opportunities"

---

### Task 5: Evidence-grounded angles

**Files:**

- Modify: app/services/llm.py near structured social metadata helpers
- Modify: app/services/trends/service.py
- Test: test/services/trends/test_angles.py
- Test: test/services/test_llm.py

**Interfaces:**

- build_trend_angles_prompt(topic, evidence) returns prompt text.
- generate_trend_angles(topic, evidence, app_config=None) returns zero or exactly three strings.
- TrendDiscoveryService.add_angles(topic_id) updates only selected cached topic.

- [ ] **Step 1: Write failing tests**

    def test_angle_prompt_forbids_new_evidence():
        prompt = llm.build_trend_angles_prompt(
            "Ocean mystery",
            [{"source_type": "google_trends_rss", "markets": ["US", "IN"]}],
        )
        assert "Do not invent trend evidence" in prompt
        assert "exactly 3" in prompt

    def test_invalid_angle_response_returns_empty(monkeypatch):
        monkeypatch.setattr(llm, "_generate_response", lambda *a, **k: "bad")
        assert llm.generate_trend_angles("Ocean mystery", []) == []

- [ ] **Step 2: Run RED**

Run: uv run --no-sync pytest -q test/services/trends/test_angles.py test/services/test_llm.py -k trend_angle

Expected: functions missing.

- [ ] **Step 3: Implement strict on-demand generation**

Request JSON object containing angles with exactly three unique strings, maximum 180 characters each. Pass normalized topic and stored evidence summaries only. Reuse existing LLM routing. Reject malformed JSON, extra fields, duplicates, wrong counts, or excessive length; return [] and leave score unchanged.

- [ ] **Step 4: Run GREEN and commit**

Run: uv run --no-sync pytest -q test/services/test_llm.py test/services/trends

    git add app/services/llm.py app/services/trends/service.py test/services/test_llm.py test/services/trends/test_angles.py
    git commit -m "feat(trends): generate evidence-grounded angles"

---

### Task 6: WebUI, shortlist, and Studio handoff

**Files:**

- Modify: webui/Main.py
- Modify: webui/styles.css
- Modify: webui/i18n/en.json
- Modify: webui/i18n/zh.json
- Create: test/services/test_webui_trend_discovery.py
- Modify: test/services/test_webui_navigation_dashboard.py

**Interfaces:**

- _render_trend_discovery_view() renders cached-first page.
- _apply_trend_topic_to_studio(topic, angle) sets video_subject, video_script_prompt, nav_view=studio, main_nav_radio=studio.
- It never invokes task.start or generation submission.

- [ ] **Step 1: Write failing WebUI tests**

    def test_page_has_separate_platform_tabs(app_with_trends):
        app = app_with_trends.run()
        assert [tab.label for tab in app.tabs] == [
            "YouTube Shorts", "TikTok", "Instagram Reels"
        ]

    def test_use_topic_fills_studio_without_generation(app_with_trends, start):
        app = app_with_trends.run()
        app.button(key="trend_use_youtube_shorts_ocean-mystery").click().run()
        assert app.session_state["nav_view"] == "studio"
        assert app.session_state["video_subject"] == "Ocean mystery"
        assert app.session_state["video_script_prompt"]
        start.assert_not_called()

- [ ] **Step 2: Run RED**

Run: uv run --no-sync pytest -q test/services/test_webui_trend_discovery.py test/services/test_webui_navigation_dashboard.py

Expected: trends navigation and view absent.

- [ ] **Step 3: Add route and cached-first view**

Add trends navigation between Studio and Settings. Render cache immediately. Refresh only on button click. Show source availability, stale age, three platform tabs, filters, classification, score components, confidence, markets, timestamps, and evidence references. Generate angles for one selected card. Persist shortlist through TrendStore. Use Topic fills Studio and reruns.

- [ ] **Step 4: Add minimal accessible styling and copy**

Reuse existing dashboard tokens. No new font or frontend package. Do not rely on color alone for confidence/classification. Keep visible button labels and keyboard focus. Add exact English and Chinese strings for navigation, refresh, classifications, score components, stale/inferred warnings, shortlist, angles, and handoff.

- [ ] **Step 5: Run GREEN and static checks**

Run: uv run --no-sync pytest -q test/services/test_webui_trend_discovery.py test/services/test_webui_navigation_dashboard.py test/services/test_webui_generation_defaults.py

Run: uv run --no-sync python -m py_compile webui/Main.py

Run: uv run --no-sync ruff check app/services/trends test/services/trends test/services/test_webui_trend_discovery.py

- [ ] **Step 6: Commit after owner-approved UI checkpoint**

    git add webui/Main.py webui/styles.css webui/i18n/en.json webui/i18n/zh.json test/services/test_webui_trend_discovery.py test/services/test_webui_navigation_dashboard.py
    git commit -m "feat(webui): add trend discovery workflow"

---

### Task 7: Consolidated verification and live acceptance

**Files:**

- Create: docs/testing/2026-09-01-trend-discovery-acceptance.md
- Modify: README.md

- [ ] **Step 1: Run affected automated suite**

Run:

    uv run --no-sync pytest -q test/services/trends test/services/test_llm.py test/services/test_webui_trend_discovery.py test/services/test_webui_navigation_dashboard.py test/services/test_webui_generation_defaults.py test/services/test_webui_task.py

Expected: zero failures. Record exact pass and skip counts.

- [ ] **Step 2: Run owned static verification**

Run:

    uv run --no-sync python -m compileall app/services/trends webui/Main.py
    uv run --no-sync ruff check app/services/trends test/services/trends test/services/test_webui_trend_discovery.py
    git diff --check

Document unrelated pre-existing findings separately; do not claim whole-repository cleanliness from scoped checks.

- [ ] **Step 3: Perform live Windows source acceptance**

Without YouTube key, verify current Google evidence or explicit unavailable state, YouTube key-not-configured status, inferred TikTok/Instagram labels, and partial-market isolation. With owner-provided key through existing config handling, verify official evidence strengthens YouTube only. Never print or record key.

- [ ] **Step 4: Perform browser acceptance**

Verify separate tabs, filters, score explanation, evidence links, stale badge, manual refresh, shortlist persistence, on-demand angles, keyboard focus, narrow layout, and Use Topic handoff without generation.

- [ ] **Step 5: Document limitations and evidence**

README and acceptance document must state sampled markets, manual refresh, inferred TikTok/Instagram data, predictive Retention Potential, exact live timestamps, failures, and distinction between fixture tests and live availability.

- [ ] **Step 6: Commit documentation and review owned diff**

    git add README.md docs/testing/2026-09-01-trend-discovery-acceptance.md
    git commit -m "docs: record trend discovery acceptance"
    git status --short --branch
    git log --oneline --max-count=10

Confirm no credentials, trend cache, generated media, screenshots, or unrelated user changes entered feature commits.
