# Localization, Voice, Captions, And Audio

Use one locale plan and one timed script per target language. Market style may
change typography, rhythm, and emphasis, but it must not change the approved
concept.

## Contents

- [Language planning](#language-planning)
- [Voice source priority](#voice-source-priority)
- [TTS and avatar gate](#tts-and-avatar-gate)
- [Timing and captions](#timing-and-captions)
- [Visual localization](#visual-localization)
- [Audio mix](#audio-mix)
- [Acceptance checks](#acceptance-checks)

## Language planning

Create a terminology table before writing final copy:

| Field | Examples |
| --- | --- |
| Proper nouns | Game title, character names, item names |
| Classes/mechanics | Warrior, ranger, merge, reroll, tier |
| Claim/offer | Rank, reward, probability, price, download claim |
| CTA | Play now, download, challenge again |
| Compliance | Copyright, rating icon, market-only notice |

Transcreate for natural speech while preserving meaning and claim strength.
Write to the available time slot, not to the source word count. Keep names and
mechanics consistent across voice, captions, UI, endcard, and store-facing CTA.

Locale direction:

- `kr`: concise, high-energy Korean mobile-game copy; use approved Korean
  terminology and full Hangul glyph coverage.
- `jp`: natural Japanese gaming vocabulary and ad rhythm; avoid literal Korean
  or English syntax and avoid ornamental manga styling unrelated to the source.
- `tw`: Traditional Chinese used in Taiwan, not Simplified Chinese; use local
  gaming terms and natural Taiwan ad rhythm.
- `en`: idiomatic target-market English; do not preserve Korean sentence order
  or translate proper nouns inconsistently.

Use an approved licensed font with complete glyph coverage. The project guide
prefers Adobe Fonts; when another downloaded font is used, include it in the
working-file package. Existing project-safe fallbacks include Noto Sans CJK KR,
Noto Sans JP, and Noto Sans TC. Font popularity never overrides licensing,
legibility, or source fidelity.

## Voice source priority

Use this order:

1. Approved localized human or avatar takes selected in the source Slack/Drive
   review.
2. Approved licensed cloud TTS with a stable voice identity and suitable locale.
3. Approved local multilingual voice cloning/TTS.
4. Another model only after a representative sample passes the voice gate.

Never obtain or expose an API key through browser automation. Use an available
credential only when the user has authorized it; otherwise use an approved
local path or report the missing credential.

For this repository, Qwen3-TTS Base is the established local fallback; see
[docs/qwen-local-tts.md](../../../../docs/qwen-local-tts.md). The tested
XTTS-v2 path did not meet the P17 Korean pronunciation and slot-fit bar with
the current references. Do not reuse or batch those rejected XTTS candidates.
A different provider or reference set must pass a new sample gate.

## TTS and avatar gate

Before full generation:

1. Preserve source roles. Two source speakers require two distinguishable,
   stable target voices unless the user explicitly changes the concept.
2. Select one difficult representative line containing a proper noun or
   important mechanic and one emotional line.
3. Generate at least three takes when delivery is unstable.
4. Listen to every candidate and use ASR as supporting evidence.
5. Reject wrong words, extra words, false starts, trailing speech, role drift,
   identity drift, robotic uniformity, overacting that harms intelligibility,
   or a line that requires excessive speed-up.
6. Record provider/model, voice/reference, seed or settings, selected take,
   transcript, raw duration, target duration, and approval state.

For supplied avatar takes, inspect all Hook/Main Body/CTA options. Trim extra
spoken words only when the intended sentence remains clean. Check pronunciation,
mouth sync, expression, camera continuity, background continuity, crop room,
and role consistency. Use the exact takes approved in the linked review thread.

If a model does not pass after a bounded sample iteration, reject it for the
job. Do not keep tuning indefinitely and do not promote it because the API or
license is available.

## Timing and captions

Store every line as:

```json
{
  "id": "02",
  "role": "guest",
  "start": 2.08,
  "end": 4.45,
  "text": "난 궁수. 전사 패스!"
}
```

Rules:

- Generate voice from the exact `text` field.
- Derive word timing from the selected audio using provider timestamps or
  Whisper alignment.
- Build captions and active-word highlighting from that same text/timing data.
- Keep audible and visible wording identical. Punctuation may be visually
  normalized, but words and meaning may not differ.
- Default maximum time-fit speed factor: `1.15`. If a line still does not fit,
  shorten the localized line within the same meaning and seek language review.
- Never cut a final syllable, accelerate a line until it sounds synthetic, or
  move dialogue into another speaker's reaction slot.
- Highlight the word being spoken. Use text color, fill, or a properly padded
  background; never place a duplicate highlight layer across glyphs.
- Choose caption position per shot and ratio. Protect faces, actors, game
  characters, choices, controls, reward values, and legal labels.
- Keep line breaks semantically natural and avoid stranded punctuation.

ASR is not native-language approval. Manually listen to names, emotional
performance, and sentence endings. Record uncertain pronunciation as
`NEEDS_CONFIRMATION`.

## Visual localization

- Remove or rebuild baked source text cleanly before adding target copy.
- Use the official target-locale logo and approved CTA.
- Replace wrong-language gameplay UI with target-locale gameplay showing the
  same mechanic and comparable action.
- Keep a single language throughout voice, captions, labels, gameplay UI,
  logo, and CTA. Player IDs may remain unchanged only when they are real IDs
  rather than ad copy.
- Adapt typographic rhythm to the locale without adding decorations that alter
  the source concept.
- Apply current market-only labels. The KR exact notice is
  `확률형 아이템 포함`; do not carry it into EN, JP, or TW. For TW, use the
  current approved rating asset from the live internal guide rather than
  copying an icon from an old package.

## Audio mix

- Preserve or restore gameplay SFX at an audible level under the voice.
- Use official game music or another rights-cleared track. Do not download an
  attractive commercial track without verified usage rights.
- Use voice-aware ducking so BGM/SFX lower during speech but do not disappear.
- Maintain the body's energy through the endcard unless the concept deliberately
  resolves quietly.
- Default delivery target: near `-14 LUFS` integrated, true peak at or below
  `-1 dBTP`, AAC 48 kHz stereo.
- Check phone-speaker intelligibility, clipping, pumping, abrupt cutoffs,
  channel imbalance, and accidental silence.

## Acceptance checks

A localized voice/caption/audio pass requires:

- correct locale and natural wording
- stable intended speaker for every line
- correct names and mechanics by listening, supported by ASR
- every line fits its slot without more than the approved speed factor
- caption text matches the audible line
- word highlight tracks the audible word
- captions avoid important subjects in all requested ratios
- gameplay SFX and BGM remain audible
- endcard audio sustains the intended energy
- no extra speech, source-language voice, clipping, or extended accidental
  silence

If any item cannot be verified, record it as pending or `NEEDS_CONFIRMATION`;
do not mark it passed from script text alone.
