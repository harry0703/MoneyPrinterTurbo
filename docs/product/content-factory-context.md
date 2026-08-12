# CONTENT FACTORY — PROJECT CONTEXT

> Last updated: 2026-08-12  
> Status: product/engineering context for an AI-assisted short-form content factory  
> Primary use: give this file to coding agents working inside the repository so they understand the product goal, assumptions, architecture, research priors, constraints, and MVP boundaries.

---

## 0. TL;DR FOR THE AGENT

We are building a semi-autonomous **short-form content factory** for TikTok, Instagram Reels, and YouTube Shorts.

The main business objective is **not platform monetization**. Platform monetization is a secondary bonus.

The primary objective is to create a cheap, repeatable organic acquisition/distribution channel for the owner's products and future projects (for example, a VPN product and other SaaS/services) by publishing useful/entertaining short-form videos with lightweight branding / sponsor-style promotion / CTA.

The factory should:

1. Research current trends and evergreen topics.
2. Generate candidate video ideas.
3. Score ideas.
4. Ask the human to approve a small batch of directions/ideas.
5. Generate scripts.
6. Build videos automatically using a renderer (MoneyPrinterTurbo is the current baseline candidate).
7. Select video footage primarily from existing stock/media providers, not by generating every scene from scratch.
8. Add subtitles, branding, and an optional promotional element.
9. Publish to TikTok / Reels / Shorts through platform adapters/connectors/APIs.
10. Pull performance analytics.
11. Learn which topics, hooks, lengths, formats, visual styles, CTAs, and publishing conditions work.
12. Feed those observations back into future idea generation.

The central product concept is:

**Trend / Idea -> Experiment -> Publish -> Measure -> Learn -> Repeat**

This is not intended to be a "generate 1,000 identical AI-slop videos" system.

The real moat, if one develops, should come from:

- fast trend detection,
- good idea filtering,
- consistent content formats,
- cheap experimentation,
- strong analytics,
- accumulated first-party performance data,
- and an automated feedback loop.

Do not overengineer v1.

---

# 1. PRODUCT VISION

The owner wants to build an internal **media acquisition infrastructure** that can be reused across multiple products.

Think of it as a small AI-native media network.

Possible future channel families:

- football stories / football explainers,
- history / weird history,
- gaming,
- internet / cybersecurity / privacy,
- VPN-related educational content,
- science / facts,
- meme/reaction formats,
- simple recurring animated character formats,
- future niche channels discovered from data.

A channel is not necessarily tied directly to one product.

Some channels may be pure entertainment and act as "house ad inventory":

```text
football ─────┐
history ──────┤
gaming ───────┼──> organic attention
science ──────┤
memes ────────┘
                    ↓
              owned products
```

The owner may promote one product today and a different product tomorrow.

Therefore, the factory should separate:

- **content generation**
- **media brand/channel identity**
- **advertiser / owned product promotion**
- **platform-specific publishing**

Do not hard-code the project around one VPN or one niche.

---

# 2. BUSINESS MODEL / SUCCESS CRITERIA

## 2.1 Primary objective

Generate organic reach cheaply enough that even a small conversion rate into product traffic can be economically useful.

The system is attractive because the monetary downside can be low:

- LLM generation is cheap.
- TTS can be cheap.
- Pexels/Pixabay stock video retrieval can be free.
- rendering can be local/open-source.
- publishing can be automated.
- one good video may subsidize many failed experiments.

This should be treated as an **asymmetric experimentation strategy**, not as a guaranteed marketing machine.

## 2.2 Secondary objectives

- platform creator monetization,
- creator fund / ad revenue where available,
- followers/subscribers,
- reusable audiences,
- organic brand awareness,
- creative testing for later paid campaigns.

Platform monetization is not the core optimization target.

## 2.3 Do NOT optimize for views alone

The real acquisition funnel is:

```text
video published
    ↓
impressions / starts
    ↓
view / stayed-to-watch
    ↓
watch time / completion
    ↓
profile visit
    ↓
outbound click
    ↓
registration
    ↓
activation
    ↓
paid user / revenue
```

A 200k-view video with 80 registrations may be more valuable than a 2M-view video with 5 registrations.

The analytics model must preserve this distinction.

---

# 3. OPERATING MODEL: HUMAN AS EDITOR-IN-CHIEF

The system should be autonomous but not fully unsupervised initially.

Preferred operating loop:

## Morning report

A "Chief Editor" / Trend Agent runs once per day and sends something like:

```text
Detected 74 trend signals.

Recommended today:
1. Champions League controversy — 9.1
2. GTA topic — 8.7
3. Weird historical event — 8.2
4. Privacy / public Wi-Fi trend — 7.9

Why each matters:
- trend velocity
- estimated audience fit
- novelty
- existing visual asset coverage
- competition
- expected commercial fit
```

Human approves broad topics/directions.

Example:

```yaml
approved_topics:
  - football_current
  - gta
  - weird_history

daily_video_budget: 8
```

## Midday / afternoon approval

The system can generate a batch of actual video ideas:

```text
1. What happened 14 seconds before the winning goal?
2. The one detail almost nobody noticed in this replay.
3. Why this referee decision caused so much controversy.
4. A strange statistic that explains the result.
```

Human can:

- approve all,
- reject specific ideas,
- edit one,
- request alternatives.

## Autonomous generation

After idea approval:

```text
research
→ fact-check
→ script
→ visual plan
→ media retrieval
→ TTS
→ subtitles
→ render
→ QA
→ publish
```

## Evening report

Example:

```text
Published: 8
Total views: 417,000

Best topic:
football controversy

Best hook class:
specific-detail / "look at X"

Best duration:
27–34 sec

Worst format:
generic listicle

CTA test:
watermark_v2 had no visible retention penalty
end_banner_v1 reduced completion

Conversions:
41 registrations
6 paid users

Recommendation tomorrow:
increase football allocation 30% -> 50%
reduce listicles
continue watermark_v2
```

The exact report should evolve as actual analytics integrations become available.

---

# 4. CORE PRODUCT PRINCIPLE: THIS IS AN EXPERIMENT ENGINE

Do not attempt to write one "perfect viral prompt".

Virality is noisy and highly context-dependent.

The system should instead generate **cheap, informed bets**.

The goal is:

```text
internet / trends / data
        ↓
candidate ideas
        ↓
filter obvious bad ideas
        ↓
publish a manageable number of experiments
        ↓
real viewers evaluate them
        ↓
platform algorithms distribute winners
        ↓
our system records the result
        ↓
next experiments become better informed
```

Humans/platform viewers are the final evaluator.

LLMs are primarily used to:

- discover,
- summarize,
- structure,
- generate variants,
- classify,
- rank,
- and reduce obviously poor options.

Do not assume LLM scoring is an oracle.

---

# 5. HOW SHORT-FORM DISTRIBUTION SHOULD BE MODELED

The exact platform algorithms are private.

Use this as a mental model, NOT an exact algorithm:

```text
publish
   ↓
platform estimates who may like it
   ↓
users encounter the video
   ↓
signals:
- skip vs watch
- watch time
- completion
- replay
- like
- comment
- share
- follow
- other satisfaction signals
   ↓
platform updates predicted relevance
   ↓
distribution expands, changes audience, or decays
```

Important:

There is no reliable universal public rule like:

```text
500 views -> pass
5,000 views -> pass
50,000 views -> viral
```

Do not implement arbitrary "viral batch thresholds" as if they were platform truth.

YouTube officially says its Shorts ranking uses signals including:

- percentage of viewers who chose to view,
- average view duration,
- average percentage viewed.

YouTube also considers viewer satisfaction and topic/context factors.

Source:
https://support.google.com/youtube/answer/11914225

TikTok officially describes recommendation using signals including:

- likes,
- shares,
- comments,
- watch/full watch,
- skips,
- account/content/device/context information.

Source:
https://support.tiktok.com/en/using-tiktok/exploring-videos/how-tiktok-recommends-content

Instagram has explicitly described recommendation changes designed to give smaller/original creators opportunities to reach new audiences.

Sources:
https://creators.instagram.com/blog/helping-creators-of-all-sizes-break-through
https://creators.instagram.com/blog/recommendations-and-originality

---

# 6. RESEARCH PRIORS AS OF AUGUST 2026

These are **starting priors**, not permanent rules.

They must be replaced by our own account-level data as soon as we have enough observations.

## 6.1 TikTok length

Socialinsider analyzed more than 6M TikTok videos published Jan–Jun 2026.

Reported engagement by length:

```text
0–15s       5.90%
15–30s      6.00%
30–60s      4.20%
60–90s      4.80%
90–120s     5.15%
120–180s    5.50%
>180s       5.90%
```

Reported median views:

```text
1–15s       1,274
15–30s      1,000
30–60s      2,200
60–90s      7,200
90–120s     9,620
120–180s    11,136
>180s       10,150
```

Interpretation:

- roughly 15–30 sec performed best for engagement in this dataset,
- 2–3 minute videos had the highest median views,
- therefore "all TikToks should be 10–15 seconds" is not a good universal assumption,
- long videos only make sense when the story can sustain attention.

Source:
https://www.socialinsider.io/blog/how-long-are-tiktok-videos/

## 6.2 Instagram Reels length

Current Socialinsider research indicates Reels in roughly the 30–60 second area are strong for reach.

A specific length analysis reported 45–60 seconds as the highest engagement bracket and highest median-view bracket in the studied sample.

Use **45–60 sec** as an initial prior, not a rule.

Sources:
https://www.socialinsider.io/blog/instagram-reels-length/
https://www.socialinsider.io/blog/instagram-reels-statistics/

## 6.3 TikTok 2026 platform-level dataset

Metricool reports a 2026 TikTok study using:

- 2,314,756 posts
- 92,000 accounts

Reported takeaways include:

- video significantly outperforming image/carousel formats for views/interactions,
- For You contributing the majority of discovery,
- relevant hashtags having a small positive association,
- competition increasing as content volume rises.

Sources:
https://metricool.com/tiktok-study/
https://metricool.com/press-release-tiktok-study-2026/

## 6.4 TikTok cultural/content trend framing for 2026

TikTok's own 2026 trend report highlights:

### Reali-Tea

Preference for:

- honesty,
- real process,
- behind-the-scenes,
- human imperfection,
- community participation,

rather than excessively polished or detached fantasy.

### Curiosity Detours

Discovery is increasingly non-linear:

- FYP
- comments
- search
- related interests
- niche communities

The report explicitly encourages brands to find adjacent niche spaces and to treat comments/community interaction as part of the creative surface.

### Emotional ROI

Commercial content should increasingly explain the "why to buy" / real value, rather than relying purely on viral hype.

Source:
https://ads.tiktok.com/business/en/next

## 6.5 Important interpretation

Do not blindly turn these datasets into constants.

Example:

Wrong:

```python
if platform == "instagram":
    duration = 52
```

Better:

```python
prior = DurationPrior(
    platform="instagram",
    preferred_range=(45, 60),
    confidence="external_benchmark"
)
```

Then our own data can override it later.

---

# 7. INITIAL CONTENT FORMATS

The system should support reusable **formats**, not just niches.

A niche describes the subject.

A format describes the storytelling mechanic.

Initial Format Registry candidates:

```text
micro_documentary
mystery_reveal
myth_busting
explainer
one_detail
hot_take
story_twist
ranking
timeline
primary_source_reveal
before_after
three_clues
comment_followup
news_context
why_it_happened
```

## 7.1 Mystery / reveal

Example:

```text
"Everyone saw this goal.
But look at the player on the left."
```

Structure:

```text
hook
→ open loop
→ clues / context
→ escalation
→ reveal
→ optional second payoff
```

## 7.2 Myth busting

```text
"Everyone says X.
The actual story is Y."
```

Good for:

- history,
- sports narratives,
- tech myths,
- cybersecurity,
- gaming lore.

## 7.3 One detail

```text
"Almost nobody noticed this detail."
```

Works especially well when the visual material can actually demonstrate the detail.

## 7.4 Explainer

```text
"Why does X happen?"
```

Useful for VPN/privacy channels and evergreen acquisition content.

## 7.5 Primary source reveal

Show:

- real document,
- chart,
- map,
- screenshot,
- archive excerpt,
- public record.

Then highlight the relevant portion.

This can create stronger perceived authenticity than generic stock footage.

## 7.6 Comment follow-up

Generate a new video based on:

- a real viewer question,
- a disagreement,
- a frequently repeated misconception,
- a high-performing comment.

This should be a later feature after comments ingestion exists.

---

# 8. HOOK SYSTEM

The first seconds are a separate optimization problem.

Do not let the general script generator casually produce one introduction.

Create a dedicated Hook Generator / Hook Scorer.

For one idea, generate multiple hook candidates.

Possible hook classes:

```text
contradiction
specific_detail
direct_question
unexpected_number
visual_instruction
controversy
stakes
prediction
before_after
myth
confession
challenge
```

Examples:

Generic bad opening:

```text
"Hi everyone, today we're going to talk about..."
```

Better:

```text
"This goal should never have counted."
```

```text
"Look at the player on the left one second before the shot."
```

```text
"Everyone remembers the goal. Almost nobody remembers what happened 14 seconds earlier."
```

The system should log `hook_type` as structured metadata.

---

# 9. SCRIPT / STORY DESIGN

A video should not be treated as a paragraph read aloud.

The script should have timed beats.

Canonical structure:

```text
0s        hook

immediately:
identify subject / context

then:
new information

then:
escalation / unresolved question

then:
payoff

optional:
second twist

final:
soft CTA / branding
```

The viewer should receive a reason to continue watching every few seconds.

Possible attention refresh mechanisms:

- new fact,
- new question,
- visual change,
- diagram,
- zoom/highlight,
- contradiction,
- escalation,
- emotional shift,
- payoff preview.

Avoid padding scripts merely to hit a duration target.

---

# 10. TREND ENGINE

Trend analysis is one of the most valuable planned components.

The Trend Agent should run on a schedule, initially once per day.

Possible sources:

- Google Trends
- TikTok Creative Center / TikTok trend surfaces
- YouTube trends/search signals
- Reddit
- X
- news feeds
- Google News
- niche RSS feeds
- sports schedules/results for sports channels
- Steam / gaming news / patch notes for gaming
- Reddit/community signals
- search APIs
- manual feeds added later

Do not build every integration in v1.

The Trend Engine output should normalize everything into internal `TrendCandidate` objects.

Example:

```json
{
  "id": "trend_123",
  "topic": "example topic",
  "vertical": "football",
  "detected_at": "2026-08-12T08:00:00Z",
  "velocity": 0.89,
  "audience_fit": 0.84,
  "novelty": 0.71,
  "content_competition": 0.65,
  "visual_coverage": 0.92,
  "commercial_fit": 0.38,
  "source_confidence": 0.94,
  "status": "candidate"
}
```

Possible conceptual score:

```text
TREND_SCORE =
    trend_velocity
  × audience_fit
  × novelty
  × format_fit
  × visual_coverage
  × source_confidence
```

Do not obsess over the exact formula initially.

A weighted model with explainable components is enough.

The system should show the human **why** a trend was recommended.

---

# 11. IDEA ENGINE

Trend != video idea.

For each approved trend, create multiple angles.

Example topic:

```text
controversial football match
```

Possible idea angles:

```text
- what actually happened
- one detail nobody noticed
- why the referee made the decision
- a rule most viewers misunderstand
- what happened 15 seconds before the key event
- player's history relevant to the event
- statistic explaining the result
- comparison to another famous match
```

An `IdeaCandidate` should store:

```json
{
  "topic_id": "trend_123",
  "angle": "one_detail",
  "title": "...",
  "summary": "...",
  "hookability": 0.91,
  "novelty": 0.77,
  "visualability": 0.93,
  "source_quality": 0.88,
  "commercial_fit": 0.42,
  "risk": 0.12
}
```

Human approval should operate primarily at this layer in v1.

---

# 12. FACTUALITY / RESEARCH

For factual channels, hallucinated facts can destroy the brand.

The script process should conceptually be:

```text
idea
↓
source retrieval / research
↓
claim list
↓
source-backed outline
↓
script
↓
claim verification
```

Store source URLs / IDs associated with the video.

Example:

```json
{
  "claims": [
    {
      "text": "...",
      "source": "https://...",
      "confidence": 0.93
    }
  ]
}
```

The system does not need a massive RAG architecture in v1 if normal web research is sufficient.

For evergreen internal knowledge, RAG can be added later.

---

# 13. VISUAL STRATEGY

The owner originally considered a custom "video RAG" with a library of mapped clips.

Current MVP decision:

**Do not build a large custom media retrieval RAG initially.**

First test existing stock/video search providers.

MoneyPrinterTurbo already exists as the baseline video-generation/rendering project.

Preferred initial visual providers:

```text
Pexels
Pixabay
local assets
simple generated graphics
```

Later:

```text
Storyblocks
Shutterstock
specialized licensed libraries
own media library
generative video provider
```

## 13.1 Provider abstraction

Design a thin interface from the beginning:

```text
VisualProvider
├── StockProvider
├── LocalAssetProvider
├── GeneratedVisualProvider
└── SpecializedMediaProvider
```

But implement only what v1 needs.

Conceptual interface:

```python
search(
    query,
    orientation,
    min_duration,
    max_duration,
    semantic_context,
    limit
) -> list[MediaAsset]
```

## 13.2 Script -> scene -> search query

Do not request:

```text
"football"
```

For each script beat derive a visual intent.

Example:

```text
Narration:
"the stadium fell silent before the penalty"

Visual intent:
- football stadium
- crowd
- tense
- night
- penalty setup
```

Then generate 2–4 retrieval queries.

## 13.3 Pexels / Pixabay

They are currently attractive for MVP because:

- APIs are available,
- access can be free,
- stock footage is searchable,
- commercial-use licensing is generally much easier than random clips copied from social media.

Always preserve source/license metadata per media asset.

Do NOT treat "publicly visible on the Internet" as "commercially reusable".

---

# 14. COPYRIGHT / MEDIA SAFETY

Be conservative.

High-risk categories:

- TV series clips
- films
- live sports broadcasts
- copyrighted highlights
- copyrighted music
- random TikTok/YouTube clips downloaded and reposted

A database containing such clips does not automatically grant commercial reuse rights.

A technically accessible video API may only allow:

- embedding,
- viewing,
- application integration,

not downloading, modifying, and republishing as native social content.

Therefore, every `MediaAsset` should be able to store:

```json
{
  "source": "...",
  "license_type": "...",
  "commercial_use": true,
  "modification_allowed": true,
  "attribution_required": false,
  "license_notes": "..."
}
```

If license status is unknown, treat the asset as unusable for automated commercial publishing.

---

# 15. GENERATIVE VIDEO / HIGGSFIELD

Generative video may be useful later, especially for:

- custom characters,
- recurring animated formats,
- impossible scenes,
- branded visual identity,
- visual gaps where stock retrieval fails.

However:

**Do not make Higgsfield or any expensive generative video provider a mandatory v1 dependency.**

Preferred v1 ratio:

```text
stock/local retrieval: majority
generated visual inserts: minority / optional
```

If a recurring animated character format becomes promising, then consistent character generation may become strategically useful.

Example future format:

```text
CATS_EXPLAIN
```

with recurring:

- characters,
- rooms/backgrounds,
- poses,
- reaction loops,
- transition animations.

The long-term goal would be recognizable IP, not random AI scenes.

---

# 16. RENDERER

MoneyPrinterTurbo is the current baseline candidate.

Treat it as replaceable.

The factory owns:

```text
idea
script
visual plan
media selection
branding
metadata
analytics
experiment state
```

The renderer is an adapter.

Conceptual interface:

```python
render(video_spec) -> RenderedVideo
```

Possible future renderers:

- MoneyPrinterTurbo
- custom ffmpeg composition
- Remotion
- VideoGen API
- other vendors

Do not let renderer-specific data leak through the whole domain model.

---

# 17. PLATFORM ACCOUNTS / CHANNEL STRATEGY

Initial strategy:

Start with **1–2 content verticals**, each distributed to:

- TikTok
- Instagram Reels
- YouTube Shorts

Therefore roughly:

```text
1 vertical -> 3 platform accounts
2 verticals -> 6 platform accounts
```

Do not immediately start dozens of accounts.

Reason:

We need enough observations per concept/channel to learn.

Split channels by **audience identity / topic universe**, not by minor content format.

Good:

```text
football:
- mystery
- explainers
- history
- controversies
```

Same account can support these.

Bad:

```text
one account:
football
Roman history
VPN tutorials
cats
AI news
```

unless data later proves this mixed format works.

The system should support more accounts eventually, but v1 should not depend on scale.

---

# 18. PLATFORM PUBLISHING

Build platform adapters:

```text
Publisher
├── TikTokPublisher
├── InstagramPublisher
└── YouTubePublisher
```

The platform adapter owns:

- authentication,
- upload,
- caption,
- hashtags,
- thumbnails where relevant,
- disclosure flags,
- scheduling,
- platform-specific constraints,
- returned post/video ID.

The rest of the application should not know platform API details.

Publishing should support manual fallback if an API is difficult to obtain initially.

Do not block MVP on perfect publishing automation.

---

# 19. COMMERCIAL CONTENT / BRANDING / "BANNER"

The owner wants to use content primarily to promote owned products.

This promotional layer should be modeled explicitly, not baked randomly into the renderer.

Example:

```json
{
  "promotion": {
    "type": "own_product",
    "advertiser_id": "vpn_1",
    "creative_id": "watermark_v2",
    "cta_id": "link_in_bio",
    "disclosure_required": true
  }
}
```

Potential creative variants:

```text
A: no promotion
B: small persistent watermark
C: small footer / bottom branding
D: last-3-to-5-second CTA
E: native spoken CTA
F: product-related story with soft mention
```

Do NOT assume a giant static banner is optimal.

It may reduce retention/distribution.

This must be experimentally measured.

---

# 20. PLATFORM COMMERCIAL DISCLOSURES

Platform commercial-content rules change.

At implementation time, verify current official requirements.

Important principle:

If a video promotes an owned product, sponsorship, or paid product, publishing logic should support the platform's required commercial-content disclosure.

Do not attempt to disguise advertising.

Also avoid third-party "banner ads" that imitate the platform's own native ad units.

Official policy/reference pages should be rechecked before production deployment.

---

# 21. ATTRIBUTION

Attribution is crucial because views are not the business objective.

Every campaign / account / creative should ideally be distinguishable.

Example redirect:

```text
go.example.com/a8f3
```

Internal mapping:

```json
{
  "redirect_id": "a8f3",
  "video_id": "video_812",
  "platform": "tiktok",
  "account": "football_en_1",
  "promotion_creative": "watermark_v2",
  "cta": "link_in_bio",
  "campaign": "vpn_launch_1"
}
```

Track where possible:

```text
profile visits
outbound clicks
landing sessions
registrations
activated users
paid users
revenue
```

Not every platform exposes all intermediate steps.

Use the best observable data.

---

# 22. ANALYTICS MODEL

For every video store both **content features** and **outcomes**.

## Content features

```json
{
  "video_id": "video_123",
  "vertical": "football",
  "topic": "example",
  "topic_type": "trend",
  "format": "mystery_reveal",
  "hook_type": "specific_detail",
  "duration_sec": 31.2,
  "voice_id": "voice_03",
  "words_per_minute": 180,
  "scene_count": 12,
  "visual_provider_mix": {
    "pexels": 0.8,
    "generated": 0.2
  },
  "subtitle_style": "karaoke_v1",
  "promotion_type": "watermark",
  "promotion_creative": "vpn_v2",
  "published_at": "..."
}
```

## Platform outcomes

Possible:

```json
{
  "views": 184320,
  "engaged_views": 110000,
  "stayed_to_watch": 0.78,
  "average_view_duration_sec": 27.9,
  "average_percentage_viewed": 0.91,
  "likes": 12400,
  "comments": 830,
  "shares": 2800,
  "followers_gained": 1430
}
```

Fields differ by platform.

Do not fake parity between metrics that platforms define differently.

## Business outcomes

```json
{
  "profile_visits": 3821,
  "outbound_clicks": 912,
  "registrations": 74,
  "activated_users": 31,
  "paid_users": 11,
  "revenue": 93.00
}
```

---

# 23. FEEDBACK LOOP

The initial learning system can be very simple.

Do not start with reinforcement learning.

Start with:

- SQL aggregation,
- cohort analysis,
- grouped averages/medians,
- confidence-aware comparisons,
- simple regression / tree models later,
- LLM-generated summaries of real statistics.

Questions the system should eventually answer:

```text
Which hooks work best for football?
Which durations work best on TikTok?
Which format works best for history?
Does a watermark reduce completion?
Do generated visuals hurt or improve retention?
What publishing time works for this account?
Which topic families create registrations, not just views?
Which visual provider correlates with better outcomes?
```

Example internal finding:

```text
football
+ controversy hook
+ 25–35 sec
+ real-match-adjacent licensed visuals
→ higher retention than generic stock
```

This becomes an account-specific prior.

Own historical data > generic internet benchmark.

---

# 24. EXPERIMENT DESIGN

Every meaningful hypothesis should eventually be testable.

Examples:

```text
H1:
specific-detail hooks outperform generic questions.

H2:
persistent watermark causes less retention loss than a final full-width banner.

H3:
trend-reactive football videos generate more views but fewer product registrations than privacy explainers.

H4:
45–60 sec Reels outperform 20–30 sec Reels for story formats.

H5:
visual scene changes every ~2–4 seconds improve retention for explainers.
```

Do not interpret tiny samples as proof.

Tag experiments explicitly:

```json
{
  "experiment_id": "exp_banner_01",
  "variant": "B"
}
```

---

# 25. INITIAL CONTENT MIX (WORKING HYPOTHESIS)

For an exploratory channel:

```text
30% trend-reactive
30% curiosity / surprising story
20% explanation / myth-busting
10% ranking/list
10% experimental formats
```

This is NOT a proven universal optimum.

It is merely a reasonable exploration allocation.

---

# 26. INITIAL DURATION PRIORS

Again: initial only.

```yaml
tiktok:
  fast:
    target: 20-30s
  story:
    target: 60-150s

instagram_reels:
  default:
    target: 45-60s

youtube_shorts:
  default:
    target: 20-40s
```

The YouTube range here is a product hypothesis, not an externally proven optimum.

Once we have enough data, the scheduler/idea generator should use account-specific priors.

---

# 27. POSTING FREQUENCY

Do not hard-code "post N times/day because the algorithm wants it".

There is no universal magic posting frequency.

The purpose of frequent publishing for this project is:

**more experiments per unit time**

not:

**appease the algorithm**

A reasonable MVP may produce a small number of videos per account/day, but throughput should be constrained by:

- content quality,
- human review capacity,
- platform limits,
- cost,
- risk,
- account health,
- experiment usefulness.

---

# 28. POSTING TIME

Internet benchmark studies disagree.

Use posting time as an exploration variable.

Start with broad evening windows where benchmarks often show activity, but do not treat them as rules.

After enough posts, derive account-specific time/day distributions.

Store:

```text
day_of_week
local_publish_hour
timezone
```

in analytics.

---

# 29. HASHTAGS / SEO / METADATA

Do not optimize for spammy generic hashtags.

Prefer:

- clear topic name,
- entities,
- search-aligned narration,
- on-screen keywords where appropriate,
- natural caption,
- a few relevant hashtags.

Example:

Narration:

```text
"Why was Messi's 2012 scoring record so unusual?"
```

Caption:

```text
How Messi scored 91 goals in 2012.
```

Tags:

```text
#Messi #FootballHistory
```

Not:

```text
#fyp #viral #viralvideo #xyzbca
```

YouTube Shorts should not depend heavily on hashtags for discovery.

---

# 30. COMMENTS AS CONTENT INPUT

Future feature:

```text
comments
↓
cluster questions / disagreements
↓
detect recurring audience curiosity
↓
generate follow-up videos
```

This fits TikTok's 2026 emphasis on comments/community as part of the content experience.

Do not implement until publishing + analytics loop works.

---

# 31. MEDIA RETRIEVAL: MVP DECISION

The owner initially considered a custom RAG where:

```text
topic -> curated clips
```

Example:

```text
football -> large prebuilt library
```

Current decision:

**delay custom media RAG.**

Reasons:

- ingestion is work,
- embeddings/indexing is work,
- copyright/license metadata is hard,
- duplicate management is work,
- stock search APIs may already solve enough of the problem.

MVP:

```text
script scene
↓
visual intent
↓
query generation
↓
Pexels / Pixabay / local
↓
candidate ranking
↓
renderer
```

Later, if stock retrieval repeatedly fails for a niche, add a curated library specifically for that niche.

---

# 32. FUTURE CUSTOM MEDIA LIBRARY

If eventually needed, a `MediaAsset` could look like:

```json
{
  "id": "asset_918",
  "file": "...",
  "topics": ["football"],
  "entities": ["example player"],
  "actions": ["celebration"],
  "moods": ["victory"],
  "start": 12.4,
  "end": 18.9,
  "quality": 0.91,
  "commercial_use": true,
  "license_type": "...",
  "used_last_30d": 4,
  "embedding": "..."
}
```

Retriever can penalize overused clips:

```text
score =
semantic_similarity
+ quality
+ entity_match
- recent_usage_penalty
```

But this is NOT MVP.

---

# 33. DATA MODEL — SUGGESTED ENTITIES

Minimum conceptual entities:

```text
Channel
PlatformAccount
Trend
Idea
ResearchBundle
Script
VideoProject
Scene
MediaAsset
Render
Publication
AnalyticsSnapshot
PromotionCampaign
PromotionCreative
AttributionEvent
Experiment
AgentRun
HumanApproval
```

Do not implement every table on day one.

But domain naming should remain consistent.

---

# 34. STATE MACHINE

Suggested high-level `VideoProject` states:

```text
DRAFT_IDEA
AWAITING_IDEA_APPROVAL
APPROVED
RESEARCHING
SCRIPTING
AWAITING_SCRIPT_APPROVAL   # optional
PLANNING_VISUALS
FETCHING_MEDIA
RENDERING
QA
READY_TO_PUBLISH
PUBLISHING
PUBLISHED
ANALYTICS_PENDING
ACTIVE_ANALYTICS
ARCHIVED
FAILED
```

Allow retries.

Store failure reason and step.

---

# 35. AGENT ROLES

Do not necessarily implement as separate LLM microservices.

"Agent" can simply mean a role/prompt/module.

Logical roles:

## Trend Agent

Finds and ranks current opportunities.

## Idea Agent

Turns trends/evergreen topics into multiple angles.

## Research Agent

Collects factual support and source material.

## Hook Agent

Produces hook variants.

## Script Agent

Creates timed short-form script.

## Visual Director

Turns script beats into visual intents/search queries.

## QA Agent

Checks:

- factual consistency,
- missing media,
- subtitle layout,
- weird cuts,
- promotional disclosure needs,
- prohibited/unsafe output,
- duplicate content risk.

## Analytics Agent

Summarizes results and proposes changes.

## Chief Editor Agent

Produces human-facing daily plans/reports.

Again: these can all be functions around the same model initially.

---

# 36. AUTONOMY LEVELS

Design for configurable autonomy.

Example:

```yaml
autonomy:
  trend_selection: require_approval
  idea_selection: require_approval
  script: automatic
  media_selection: automatic
  render: automatic
  publish: require_approval
```

Later:

```yaml
autonomy:
  publish:
    automatic_if_confidence_above: 0.90
```

Avoid fully autonomous publishing until quality and compliance are understood.

---

# 37. COST MODEL

Track estimated cost per video.

Possible cost categories:

```text
LLM input/output
web/search API
TTS
stock API
generative video
render compute
storage
publishing services
analytics services
human review
```

Store:

```json
{
  "estimated_generation_cost_usd": 0.08,
  "render_cost_usd": 0.02,
  "media_cost_usd": 0.00
}
```

Then compute:

```text
cost / published video
cost / 1k views
cost / registration
cost / paid user
```

The system is only attractive if acquisition economics make sense.

---

# 38. VIDEO QA

Before publish, basic automated checks:

```text
video exists
audio exists
duration within platform constraints
correct aspect ratio
subtitles visible
no blank frames
no obvious repeated clip loop
no missing fonts/assets
promotion element not clipped
branding correct
caption non-empty
license metadata present
```

Optional LLM/multimodal QA can come later.

---

# 39. DUPLICATION / AI-SLOP RISK

The project must avoid becoming a mass template spam engine.

Do not generate hundreds of near-identical videos where only nouns change.

Platform direction increasingly favors original/value-adding content and is hostile to repetitive low-value mass production.

Therefore:

- formats may repeat,
- visual identity may repeat,
- recurring characters may repeat,
- BUT substantive content should vary,
- research should be topic-specific,
- hooks should fit the specific story,
- visuals should fit narration,
- scripts should not be trivial paraphrases of other videos.

The goal is automation of **editorial production**, not automation of spam.

---

# 40. PRODUCT-PROMOTION CHANNEL VS ENTERTAINMENT CHANNELS

Treat these differently.

## VPN/product-native channel

Topics can naturally align with product intent:

```text
privacy
public Wi-Fi
travel internet
security mistakes
data breaches
geo/network explanations
internet infrastructure
privacy myths
cybersecurity stories
```

Product CTA can be more native.

## Entertainment channels

Examples:

```text
football
gaming
history
science
cats
```

Product promotion is more peripheral.

Expected conversion may be lower.

However, if impressions are very cheap, these channels can still create useful house-ad inventory.

Analytics must compare them separately.

---

# 41. CTA STRATEGY

Do not use one CTA forever.

Candidate CTAs:

```text
brand watermark
"link in bio"
short memorable domain
end card
spoken soft mention
native product tie-in
```

A/B test:

```text
retention
completion
profile visits
outbound clicks
registrations
```

Avoid aggressive CTA before the content has delivered value unless data proves it works.

---

# 42. MVP — ONE WEEK / EVENING VIBECODING SCOPE

The owner wants a small project that can be built over roughly a week of evenings.

Therefore MVP should be deliberately small.

## Must have

### 1. Configuration

```text
channels
platforms
vertical
language
brand
promotion
daily limits
```

### 2. Idea input

At minimum:

```text
manual topic
```

Preferably:

```text
simple trend/research command
```

### 3. Idea generation

Generate 5–10 candidates.

### 4. Human approval

CLI / Telegram / simple local web UI is enough.

### 5. Script generation

Generate structured script + scene beats.

### 6. Visual query generation

One or more media queries per scene.

### 7. Pexels/Pixabay retrieval

Use stock footage.

### 8. Rendering

MoneyPrinterTurbo or a thin local renderer adapter.

### 9. Branding

Watermark / simple end card.

### 10. Output

Create final vertical MP4.

### 11. Publication tracking

If direct platform publishing is too much for week one:

- export video,
- save caption,
- save publish metadata,
- user can upload manually.

This is acceptable.

### 12. Basic database

SQLite/Postgres.

Store:

```text
ideas
videos
metadata
publications
basic metrics
```

---

# 43. MVP — SHOULD NOT HAVE

Do NOT spend week one building:

```text
custom vector video RAG
Kafka
microservices
Kubernetes
reinforcement learning
custom distributed scheduler
complex workflow engine
Higgsfield dependency
10 social accounts
full enterprise dashboard
automatic comment ingestion
complex ML prediction
real-time trend streaming
```

All of these are later optimizations.

---

# 44. SUGGESTED REPO STRUCTURE

Example only:

```text
content-factory/
│
├── CONTEXT.md
├── README.md
├── config/
│   ├── channels.yaml
│   ├── brands.yaml
│   └── platforms.yaml
│
├── src/
│   ├── domain/
│   │   ├── models.py
│   │   └── enums.py
│   │
│   ├── agents/
│   │   ├── trend.py
│   │   ├── idea.py
│   │   ├── research.py
│   │   ├── hook.py
│   │   ├── script.py
│   │   ├── visual_director.py
│   │   └── analytics.py
│   │
│   ├── media/
│   │   ├── base.py
│   │   ├── pexels.py
│   │   ├── pixabay.py
│   │   └── local.py
│   │
│   ├── renderers/
│   │   ├── base.py
│   │   └── moneyprinter.py
│   │
│   ├── publishers/
│   │   ├── base.py
│   │   ├── youtube.py
│   │   ├── tiktok.py
│   │   └── instagram.py
│   │
│   ├── analytics/
│   │   ├── collectors.py
│   │   └── reports.py
│   │
│   ├── storage/
│   │   ├── db.py
│   │   └── repositories.py
│   │
│   └── app/
│       ├── cli.py
│       └── workflow.py
│
├── data/
│   ├── assets/
│   ├── renders/
│   └── cache/
│
└── tests/
```

This is a suggestion, not a hard requirement.

Favor simplicity in the actual implementation language/framework chosen.

---

# 45. EXAMPLE VIDEO SPEC

The renderer should receive something like:

```json
{
  "video_id": "v_123",
  "platform_targets": ["tiktok", "instagram", "youtube"],
  "vertical": "football",
  "format": "mystery_reveal",
  "language": "en",
  "duration_target": 30,
  "script": {
    "hook": "Everyone saw the goal. Look at the player on the left.",
    "beats": [
      {
        "start": 0,
        "end": 4,
        "narration": "...",
        "visual_intent": "..."
      }
    ]
  },
  "voice": {
    "provider": "...",
    "voice_id": "..."
  },
  "subtitles": {
    "style": "karaoke_v1"
  },
  "promotion": {
    "type": "own_product",
    "creative": "watermark_v2"
  }
}
```

Renderer should not decide business strategy.

---

# 46. EXAMPLE ANALYTICS REPORT

```text
Channel: football_en_1
Window: last 7 days
Published: 24

Views:
1,120,000

Median video:
18,400 views

Top 20% format:
mystery_reveal

Top hook:
specific_detail

Worst hook:
generic_question

Best duration:
25–35 sec

Promotion:
watermark_v2:
  no obvious retention penalty
  +0.18% profile-visit rate vs no-promo

endcard_v1:
  -9% completion
  +0.31% profile visits

Registrations:
91

Paid:
14

Recommendation:
- increase mystery_reveal allocation
- stop generic_question hooks
- continue watermark_v2
- run another end-card test with shorter duration
```

Do not generate fake conclusions when sample sizes are small.

---

# 47. FIRST EXPERIMENTS TO RUN

When the pipeline works, prioritize learning, not scale.

Suggested first tests:

## Experiment A — hook

Same content class, different hook class.

```text
specific_detail
vs
question
vs
contradiction
```

## Experiment B — duration

```text
20–30 sec
vs
45–60 sec
```

Platform-dependent.

## Experiment C — promotion

```text
no promo
vs
watermark
vs
end CTA
```

## Experiment D — visual density

```text
slower scene changes
vs
faster scene changes
```

## Experiment E — trend vs evergreen

Compare:

```text
trend-reactive
vs
evergreen curiosity
```

Outcome should include registrations where possible, not only views.

---

# 48. DEFINITION OF SUCCESS FOR V1

V1 is successful if we can repeatedly do:

```text
topic
↓
several ideas
↓
approve one
↓
generate script
↓
fetch acceptable visuals
↓
render vertical video
↓
add branding
↓
produce publish-ready MP4 + caption
```

without manual video editing.

Even if publishing and analytics remain partially manual initially, this is enough to validate the content-production concept.

The next validation question is:

**Can a small batch of generated videos occasionally receive meaningful organic distribution?**

If yes, invest more.

If every video receives almost no reach and content quality is poor, improve the content engine before scaling infrastructure.

---

# 49. DECISION RULES FOR FUTURE ENGINEERING

When deciding whether to build something, ask:

## Does it increase content quality?

Examples:

- better hook selection,
- better story structure,
- better visuals.

## Does it increase experiment velocity?

Examples:

- faster rendering,
- easier approvals,
- automated metadata.

## Does it improve learning quality?

Examples:

- better analytics,
- cleaner experiment labels,
- conversion attribution.

## Does it reduce meaningful cost?

Examples:

- free media provider,
- caching,
- cheaper TTS.

If the feature does none of these, it is probably not MVP-critical.

---

# 50. ENGINEERING PRINCIPLES

1. **Simple first.**
2. Renderer must be replaceable.
3. Platform APIs must be adapters.
4. Store structured metadata about every generated video.
5. Preserve source/license provenance for media.
6. Preserve factual sources for research-heavy content.
7. Store experiment variants explicitly.
8. Do not infer "viral rules" from a tiny sample.
9. Use external benchmarks as priors only.
10. Prefer real analytics over LLM opinions.
11. Prefer reusable domain objects over prompt spaghetti.
12. Keep the human approval layer easy.
13. Never let an agent silently publish questionable material.
14. Make failed workflow steps retryable.
15. Cache expensive/reusable results where useful.
16. Do not build infrastructure before content quality is validated.

---

# 51. OPEN QUESTIONS

These are intentionally unresolved.

## Content

- Which vertical should be the first real test?
- English, Russian, or both?
- How aggressive should the promotion be?
- Should the same video be identical across all platforms?
- Should each platform receive a custom cut?

## Rendering

- How good is MoneyPrinterTurbo's actual stock selection for our niches?
- Do we need custom ffmpeg/Remotion eventually?
- Which TTS provider has the best price/quality?

## Trends

- Which signals are cheapest and most predictive?
- How often should trend analysis run?
- Do we need per-country trend signals?

## Analytics

- Which platform APIs expose enough performance metrics?
- How quickly after publishing should snapshots be taken?
- What sample size is enough before changing a prior?

## Promotion

- Which CTA is least harmful to retention?
- How much brand presence is acceptable?
- How much traffic can entertainment channels actually convert?

## Media

- When do Pexels/Pixabay become insufficient?
- Which paid library gives the best incremental value?
- Is a niche custom media library eventually worth the maintenance?

---

# 52. WORKING ROADMAP

## Phase 0 — local proof of concept

```text
manual topic
→ LLM ideas
→ choose idea
→ script
→ Pexels/Pixabay
→ renderer
→ MP4
```

## Phase 1 — publishable factory

Add:

```text
brand configs
CTA variants
subtitles
captions
basic DB
human approval
```

## Phase 2 — distribution

Add:

```text
platform publishers
posting schedule
publication IDs
```

## Phase 3 — analytics

Add:

```text
views
watch metrics
engagement
conversion attribution
daily report
```

## Phase 4 — trend/editor system

Add:

```text
daily trend scan
trend scoring
batch approvals
idea scoring
```

## Phase 5 — learning

Add:

```text
per-format priors
per-channel priors
experiment analysis
automated recommendations
```

## Phase 6 — scale

Only after proof:

```text
more verticals
more accounts
more languages
paid media libraries
custom media retrieval
animated characters
generative video
```

---

# 53. RESEARCH / REFERENCE LINKS

These are reference inputs, not permanent truth.

## Official platform recommendation information

YouTube Shorts search/discovery:
https://support.google.com/youtube/answer/11914225

YouTube content performance metrics:
https://support.google.com/youtube/answer/12220281

TikTok recommendation system:
https://support.tiktok.com/en/using-tiktok/exploring-videos/how-tiktok-recommends-content

Instagram recommendation/originality:
https://creators.instagram.com/blog/recommendations-and-originality

Instagram creator reach:
https://creators.instagram.com/blog/helping-creators-of-all-sizes-break-through

TikTok Next 2026:
https://ads.tiktok.com/business/en/next

## 2026 benchmark research

Socialinsider — TikTok video length, >6M videos:
https://www.socialinsider.io/blog/how-long-are-tiktok-videos/

Socialinsider — Instagram Reel length:
https://www.socialinsider.io/blog/instagram-reels-length/

Socialinsider — Instagram Reels statistics:
https://www.socialinsider.io/blog/instagram-reels-statistics/

Metricool TikTok Study 2026:
https://metricool.com/tiktok-study/

Metricool TikTok Study press release:
https://metricool.com/press-release-tiktok-study-2026/

Metricool Instagram vs TikTok 2026:
https://metricool.com/instagram-vs-tiktok/

## Important rule for agents

If making implementation decisions based on current platform:

- limits,
- API access,
- publishing permissions,
- pricing,
- account eligibility,
- commercial disclosure,
- monetization,
- copyright rules,

**verify the current official documentation at implementation time.**

This context file can become stale.

---

# 54. FINAL PRODUCT PHILOSOPHY

The project is not about predicting virality perfectly.

It is about building a machine that can:

1. observe the Internet,
2. propose reasonable content bets,
3. cheaply produce them,
4. distribute them,
5. observe real human behavior,
6. learn faster than a manual creator workflow,
7. convert part of that attention into traffic for owned products.

The most valuable asset, if the project works, will not be the renderer.

It will be the accumulated dataset:

```text
topic
× format
× hook
× duration
× visual strategy
× platform
× account
× timing
× CTA
→
retention
engagement
reach
conversion
revenue
```

That data can eventually answer questions that generic "how to go viral" articles cannot answer for our specific channels.

Build toward that.

But start with a simple pipeline that can produce one genuinely watchable video end-to-end.
