# Production Layout And Delivery Matrix

Use a fresh project folder for each approved source concept or tightly related
batch. Keep source, analysis, generated intermediates, masters, delivery files,
and QA evidence separate.

## Contents

- [Recommended layout](#recommended-layout)
- [Manifest contract](#manifest-contract)
- [Locale and ratio matrix](#locale-and-ratio-matrix)
- [Technical defaults](#technical-defaults)
- [Naming and compliance](#naming-and-compliance)
- [Review evidence](#review-evidence)
- [Readiness states](#readiness-states)

## Recommended layout

```text
project/
├── source/                 # exact approved source and fetched resources
├── analysis/               # probe, transcript, frames, source comparison
├── config/
│   └── job.json            # localization_job.py manifest
├── voice/
│   ├── references/
│   ├── raw/<locale>/<concept>/
│   ├── fitted/<locale>/<concept>/
│   ├── timing/<locale>/<concept>.json
│   └── final/<locale>/<concept>.wav
├── overlays/<locale>/      # text, captions, logos, endcard, legal assets
├── masters/<locale>/       # one source-ratio localized master per locale
├── delivery/               # locale x ratio rendered outputs
├── working-files/          # editable project/config and required resources
└── qa/                     # reports, contacts, comparisons, checksums
```

Do not put generated candidates in `delivery`. Promote only selected,
fully-rendered files.

## Manifest contract

Initialize `config/job.json` with `scripts/localization_job.py`. Complete it as
the source of truth for:

- exact source file, hash, probe, locale, and duration
- Hook-Body-Endcard timeline and locked/localizable elements
- source voice roles, text-bearing areas, BGM, and gameplay SFX
- target locale scripts, assets, gameplay source, compliance, and review state
- ratio-specific framing and protected safe zones
- the selected pilot output, source comparison, full playback, and pilot QA
- expected output matrix and exact paths
- source, pilot, batch, native-language, and compliance approvals
- manual QA evidence and approved source-fidelity exceptions

Do not keep conflicting timing or copy in another spreadsheet without updating
the manifest. Voice, captions, and highlight data must point to one timed script.

## Locale and ratio matrix

Default video resolutions:

| Ratio key | Resolution |
| --- | --- |
| `portrait` | 1080x1920 |
| `square` | 1080x1080 |
| `landscape` | 1920x1080 |

Expected count is `number of target locales x number of requested ratios`.
Every matrix cell needs an explicit output path and status. Do not omit a failed
cell from the manifest to make the batch look complete.

Create in this order:

1. one pilot locale x primary ratio
2. `validate --phase pilot` and record approval or explicit batch authorization
3. remaining localized masters at the primary ratio
4. square variants from each locale master and original assets
5. landscape variants from each locale master and original assets
6. full technical validation and full manual review

## Technical defaults

Unless the placement supplies a different spec:

- H.264 video, high profile where available
- yuv420p pixel format
- constant 30 fps
- AAC audio, 48 kHz, stereo
- `+faststart` for MP4
- source duration within two frames
- integrated loudness near `-14 LUFS`
- true peak at or below `-1 dBTP`
- no decode errors, unexplained black frames, frozen padding, or extended
  accidental silence

The manifest validator checks file existence, matrix completeness, dimensions,
duration, frame rate, stream presence, codecs, pixel format, sample rate, and
channels. It does not replace full playback, loudness measurement, caption
inspection, language review, or the BPA review skill.

## Naming and compliance

Use the live BPA production guide through the sibling review skill.

Key defaults from the bundled guide:

- Pre-test: `YYMMDD_type_keyname_language`.
- Post-test: `bpa_materialid_language_ratio_resolution_keyname`.
- Material IDs must come from the registry; never invent an ID silently.
- Use the locale-matched official logo; use EN for an unsupported locale.
- KR requires exact `확률형 아이템 포함`.
- EN, JP, and TW must not inherit the KR-only randomized-item notice.
- TW must use the current approved rating icon from the live internal rule.
- Use exact copyright copy and placement from the current guide.
- Include fonts and external resources required to continue the working file.

Treat provisional material IDs, policy ambiguity, missing native review, and
unverified workflow approvals as `NEEDS_CONFIRMATION`.

## Review evidence

For every manual QA result, store a file/timestamp or another concrete evidence
reference. Minimum evidence set:

- source-versus-pilot side-by-side frames at hook, body, and endcard
- complete primary-ratio playback for every locale
- opening, transition, intermediate, and final frames for every ratio
- ASR/word-timing report plus manual voice listening result
- caption/highlight checks at multiple words and shots
- loudness, true peak, silence, black-frame, full-decode, and stream metadata
- compliance/logo/legal close-ups for each locale and ratio
- SHA-256 checksums for promoted delivery files

Run both:

```bash
python3 <skill-dir>/scripts/localization_job.py validate \
  --manifest /absolute/path/project/config/job.json --phase pilot

python3 <skill-dir>/scripts/localization_job.py validate \
  --manifest /absolute/path/project/config/job.json --phase delivery

python3 <review-skill-dir>/scripts/inspect_assets.py \
  /absolute/path/project/delivery --stage passed
```

Then use `$bpa-creative-review` for the independent quality/readiness report.

## Readiness states

- `NOT_READY`: Any required output is missing, a deterministic check fails, a
  manual check is `pending`/`fail`, or a review finding is `BLOCKER`/`FIX`.
- `READY_WITH_CONFIRMATIONS`: All inspectable work passes, but native review,
  current policy, material ID, approval, rights, or another external fact is
  explicitly `NEEDS_CONFIRMATION`.
- `READY`: Complete matrix, all deterministic checks, full playback, source
  comparison, native/cultural checks, current compliance, and required approval
  evidence all pass.

Never use `READY` for an asset-only review when delivery workflow or current
market requirements were outside the supplied evidence.
