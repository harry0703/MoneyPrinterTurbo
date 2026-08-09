---
name: bpa-localize-ad-creatives
description: Produce source-faithful localized Backpack Arena / Overgeared Hero video-ad variations from an approved source video, including EN/KR/JP/TW transcreation, localized gameplay and UI, multi-speaker TTS or approved avatar takes, voice-synced captions and active-word highlighting, BGM/SFX mixing, official logos and market labels, and 9:16/1:1/16:9 delivery. Use when Codex is asked to make 언어 베리에이션, 다국어 영상 광고 소재, JP/TW/KR/EN localization, ratio or size variations, vendor-video adaptations, or to rebuild an approved source video without changing its core concept and structure.
---

# BPA Localized Ad Creative Production

Build language and ratio variations as controlled adaptations of an approved
source. Treat source fidelity, localized performance, and delivery QA as
separate gates. Never redesign the concept merely because rebuilding it is
easier.

## Required reading

Read these files before editing or rendering:

1. [references/source-fidelity.md](references/source-fidelity.md) for every job.
2. [references/localization-audio.md](references/localization-audio.md) whenever
   language, gameplay UI, voice, captions, avatar takes, BGM, or SFX changes.
3. [references/delivery-matrix.md](references/delivery-matrix.md) whenever more
   than one locale or ratio is requested, or delivery packaging is in scope.
4. The sibling
   [BPA review skill](../bpa-creative-review/SKILL.md) and all references it
   requires. Use that skill for the final independent review.

When the user requests current country law, platform policy, or the latest
internal rule, refresh the applicable primary source. Do not treat a bundled
snapshot as current law or platform policy.

## Non-negotiable invariants

- Preserve the approved concept, Hook-Body-Endcard order, actors, dialogue
  roles, gameplay meaning, key claims, cut logic, and intentional pacing.
- If unsure whether an element is important, classify it as locked until the
  user or source evidence says otherwise.
- Keep exact user-locked copy exact. Never paraphrase a phrase such as
  `전략상위 1%` without explicit approval.
- Localize only language-bearing or market-required elements. Do not add a
  translated text panel over baked source copy as a shortcut.
- If the source contains spoken voice or TTS, every target-language version
  must contain corresponding target-language voice. Preserve the number of
  speakers and turn-taking concept.
- Drive voice, captions, and active-word highlighting from one timed script.
  Visible caption wording must match the audible wording.
- Keep gameplay SFX audible and maintain an energetic, rights-cleared BGM bed.
  Do not let the endcard become unintentionally calm or silent.
- Use the official localized logo. Do not substitute the game name as plain
  text.
- Do not add filler, freeze frames, or unrelated footage to reach a round
  duration. Preserve the source duration unless the user explicitly changes it.
- Do not replace an actor, avatar, music track, or gameplay sequence without an
  explicit source-fidelity reason recorded in the job manifest. Actor
  replacement also requires explicit user authorization.
- Do not batch all locales and ratios before one pilot passes its gate.
- Do not claim visual, audio, pronunciation, or sync review without inspecting
  the rendered media itself. A contact sheet and ASR report are supporting
  evidence, not substitutes for full playback.

## Execution protocol

Follow the phases in order. Do not skip a gate because the user requested many
outputs at once.

### Phase 0: Resolve the exact source and authority

Collect:

- the exact approved source file, not a thumbnail, contact sheet, or earlier
  revision
- the latest user instructions and any Slack/Drive approval that selects takes
  or resources
- source locale, target locales, required ratios/resolutions, campaign stage,
  placement, and naming specification
- official logos, fonts, rating/legal assets, localized gameplay, approved
  voice references or avatar takes, and rights-cleared audio

Download connected Drive/Slack assets into a new project directory and retain
their source links. Never edit the approved source in place. If the exact
source cannot be obtained, stop and report the missing input.

### Phase 1: Create and complete the job manifest

Initialize a manifest before making creative changes:

```bash
python3 <skill-dir>/scripts/localization_job.py init \
  --source /absolute/path/source.mp4 \
  --source-locale en \
  --target-locale kr \
  --ratio portrait \
  --concept P17 \
  --keyname mtf_p17_ai_versus_001 \
  --stage post-test \
  --material-id v0080 \
  --output-root /absolute/path/new-project \
  --manifest /absolute/path/new-project/config/job.json
```

Repeat `--target-locale` and `--ratio` once for every requested value. Do not
comma-separate them or omit matrix cells.

Inspect the complete source with `ffprobe`, full video/audio playback, ASR with
word timing when voice exists, and frames spanning every scene. Fill the
manifest's source contract, locale plans, ratio plans, approvals, and
exceptions. Then run:

```bash
python3 <skill-dir>/scripts/localization_job.py validate \
  --manifest /absolute/path/new-project/config/job.json \
  --phase plan
```

Do not start a pilot until plan validation passes. Fix the manifest instead of
weakening the validator.

### Phase 2: Build the source contract

Record a complete timeline map with `hook`, `body`, and `endcard` boundaries.
For every segment, record:

- its communication purpose
- locked visuals, actors, cuts, copy, claims, and audio cues
- language-bearing elements that may change
- wrong-locale gameplay/UI that must be replaced
- voice role, exact source wording, and target speech slot
- safe caption areas and subjects that must not be covered

Log every planned departure from the source in `exceptions` with evidence and
approval. An undocumented departure is a defect.

### Phase 3: Write the timed localization plan

Transcreate for natural local advertising rhythm while preserving meaning,
claim strength, character names, CTA intent, number of speakers, and timing.
Store each line as `id`, `role`, `start`, `end`, and exact `text`. Keep the
translated script concise enough for the existing slot; do not solve an
overlong line with aggressive time compression.

Create a terminology table for names, classes, item terms, CTA, and legal copy.
Record all source text-bearing areas and how each is removed, rebuilt, or
replaced. A target version must not contain accidental source-language copy.

### Phase 4: Produce one pilot

Default pilot: one target locale at the source's primary ratio. If the user
names a first locale or ratio, use that combination.

For voice work, approve a short representative sample before generating the
full timeline. Generate multiple takes when pronunciation or emotion is
unstable. Reject extra words, identity drift, wrong role, flat delivery, and
lines that cannot fit naturally.

Render and review the complete pilot. Compare it side by side with the source
at the same timestamps. Default behavior is to stop for user approval after
the pilot. Continue without a user checkpoint only when the user explicitly
authorized full batch execution or the manifest records an already-approved
pilot for this exact concept revision.

Record the pilot output, source-comparison evidence, full-playback evidence,
voice sample, word timing, and every `pilot_qa` result. Then run:

```bash
python3 <skill-dir>/scripts/localization_job.py validate \
  --manifest /absolute/path/new-project/config/job.json \
  --phase pilot
```

Do not expand the batch until this command reports `PILOT_READY` or
`PILOT_READY_WITH_CONFIRMATIONS` and any confirmation is acceptable for the
stated stage.

### Phase 5: Expand the approved pilot

Create one localized master per locale first. Derive ratio variants from the
locale master and original assets, not from an already cropped delivery file.

For every target:

- replace wrong-language gameplay/UI with semantically equivalent localized
  footage when required
- rebuild baked copy cleanly rather than stacking translation over it
- preserve actor framing, facial visibility, key characters, controls, rewards,
  and source transition rhythm
- adapt line breaks, caption position, and safe zones per shot and ratio
- apply the official locale logo, CTA, legal copy, and current market assets
- retain game sound and BGM under voice-aware ducking

### Phase 6: Validate and review

Fill every expected output path and every manual QA item in the manifest with
timestamped evidence. Run delivery validation:

```bash
python3 <skill-dir>/scripts/localization_job.py validate \
  --manifest /absolute/path/new-project/config/job.json \
  --phase delivery
```

Then run the sibling review skill's deterministic preflight against the
delivery folder:

```bash
python3 <review-skill-dir>/scripts/inspect_assets.py \
  /absolute/path/new-project/delivery --stage passed
```

Use `$bpa-creative-review` for independent visual/audio and production-guide
review. Fix every `BLOCKER` and `FIX`. Preserve `NEEDS_CONFIRMATION` instead of
converting it to `PASS` by assumption.

### Phase 7: Package and report

Keep the package structure described in `delivery-matrix.md`. Include rendered
outputs, editable project/config files, timed scripts, voice timing, overlays,
fonts or external resources required for handoff, QA reports, manual-review
evidence, and checksums. Do not upload, rename remote files, message reviewers,
or mark approvals unless the user explicitly asks for those writes.

## Hard gates

| Gate | Required evidence | Stop when |
| --- | --- | --- |
| Source | Exact file, hash, probe, full inspection | Source/revision is unclear |
| Contract | Complete timeline and locked/localizable lists | Structure is inferred from a few frames |
| Voice | Approved sample, correct role/text, natural slot fit | Source voice exists but localized voice is missing |
| Pilot | `--phase pilot`, full playback, source comparison, voice/caption evidence | Concept, framing, copy, voice, sync, or mix diverges |
| Batch | Approved pilot or explicit batch authorization | Pilot is pending or based on another revision |
| Delivery | Complete locale x ratio matrix and technical checks | Any expected output is missing or malformed |
| Review | Full playback plus BPA review findings | A `BLOCKER`, `FIX`, or unexplained pending check remains |

## Failure behavior

- Prefer returning to the approved source and rebuilding fewer elements over
  adding compensating graphics.
- If a localized line cannot fit at acceptable performance speed, rewrite it
  within the same meaning and request language confirmation; never drop voice.
- If a TTS model fails pronunciation or naturalness after a bounded sample
  iteration, reject that model for the job and move to the next approved
  provider. Do not batch a weak voice.
- If market policy, native pronunciation, rights, or source approval is not
  verifiable, finish the inspectable work but report `NEEDS_CONFIRMATION` and
  do not call the package fully ready.

## Final response contract

Report:

1. source and approved revision used
2. target locale x ratio matrix produced
3. pilot and source-fidelity decision
4. voice/caption/audio approach and evidence
5. deterministic validation and BPA review result
6. exact output and QA paths
7. unresolved confirmations or deviations

Never close with a generic quality claim. State what was inspected and what
remains unverified.
