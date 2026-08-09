# Source Fidelity Contract

Use this reference to decide what may change when one approved ad becomes
another language or ratio. The source concept is the authority unless the user
explicitly requests a concept revision.

## Contents

- [Evidence collection](#evidence-collection)
- [Timeline contract](#timeline-contract)
- [Change classification](#change-classification)
- [Known failure patterns](#known-failure-patterns)
- [Ratio adaptation](#ratio-adaptation)
- [Pilot comparison](#pilot-comparison)

## Evidence collection

Before editing:

1. Resolve the exact source revision and retain its Slack/Drive link.
2. Record SHA-256, duration, frame rate, dimensions, codecs, audio streams, and
   source locale.
3. Watch and listen to the complete source at normal speed.
4. Extract an ASR transcript with word timing when speech exists. Identify each
   speaker instead of flattening dialogue into one narrator.
5. Inspect the opening frames densely, every scene transition, every
   text-bearing frame, gameplay UI, the endcard transition, and the final frame.
6. Record original BGM, SFX, voice, silence, and energy changes.
7. Capture enough source frames for side-by-side comparison, but never use a
   contact sheet as the only motion or audio review.

## Timeline contract

Map the full duration. Use this minimum shape in the job manifest:

| Segment | Required record |
| --- | --- |
| Hook | Start/end, immediate promise or joke, actors, copy, voice, first cut |
| Body | Scene sequence, gameplay beats, dialogue turns, key UI and claims |
| Endcard | Transition time, logo, CTA, background action, BGM/SFX resolution |

For concepts with multiple rounds or beats, add child segments rather than
compressing the body into a vague note. Segment boundaries must cover the
whole file without unexplained gaps.

Default timing tolerance:

- Preserve non-language cuts within two frames.
- Preserve every voice slot unless a logged exception is approved.
- Preserve total duration within two frames unless the delivery spec says
  otherwise.
- Investigate any unexplained blank, frozen, silent, or low-information span of
  at least 0.6 seconds.

## Change classification

### Lock by default

- concept, joke, value proposition, claim strength, and CTA intent
- Hook-Body-Endcard order and the function of every scene
- actor identity, number of actors, conversation roles, and reaction timing
- primary characters, choice order, results, rewards, and gameplay meaning
- source cuts, reveal timing, transition rhythm, and intended duration
- exact user-locked phrases, ranked claims, offer numbers, and proper nouns
- source aspect composition until a ratio-specific plan is approved

### Localize

- spoken dialogue or narration
- captions, active-word highlighting, labels, names, buttons, and CTA wording
- official logo variant, font, line breaks, and market-required legal elements
- text-bearing endcard areas
- gameplay footage or UI only when the source language would remain visible in
  the target version

### Replace only with a recorded reason

- actor or avatar: only with explicit user authorization
- gameplay: only with semantically equivalent target-locale footage
- BGM: only with rights-cleared music that preserves or improves the same energy
- source graphics: only when clean removal/rebuild is required for localization
- scene duration or order: only when the user approves a concept-level change

When uncertain, lock the element. Add an `exceptions` entry containing the
source timestamp, observed problem, planned change, expected fidelity, evidence,
and approval state.

## Minimal-intervention order

Use the first method that preserves the source cleanly:

1. Swap an editable text/logo layer.
2. Rebuild only the baked text-bearing patch using clean plate, mask, crop, or
   source artwork.
3. Replace a wrong-locale gameplay/UI segment with a matched local recording.
4. Recompose a segment from approved source assets while retaining actors,
   timing, and motion.
5. Replace an actor or scene only after explicit approval.

Do not hide a difficult source area with a large opaque lower panel. Do not
place translated text on top of visible source text. Do not redesign the
entire frame to solve one localizable element.

## Known failure patterns

- Rewriting a source headline because the translation sounds more marketable.
- Losing a two-person conversation by using one voice or covering both actors.
- Turning a compact source caption into a full-width panel that blocks the
  actor, characters, controls, or rewards.
- Replacing the original sequence with generic gameplay montage.
- Extending a weak or blank scene merely to hit 30 seconds.
- Using a calm endcard bed after a high-energy body.
- Keeping English gameplay UI in JP/TW/KR or keeping KR UI in EN.
- Recreating the localized game name as text instead of using the official
  logo.
- Applying one fixed caption position even when subjects move between shots.
- Adding market-style decoration that changes the concept rather than only its
  local visual rhythm.

## Ratio adaptation

Produce the localized master at the source's primary ratio first. Derive each
delivery ratio from the master and original assets, never from another cropped
delivery file.

| Ratio | Resolution | Required framing review |
| --- | --- | --- |
| Portrait | 1080x1920 | Actor faces, vertical UI, caption and platform-safe zones |
| Square | 1080x1080 | Both speakers/choices, primary gameplay action, CTA legibility |
| Landscape | 1920x1080 | Horizontal balance, important top/bottom UI, endcard composition |

For each scene and ratio, record the subject box and protected UI. Prefer
intentional reframing or source-layer recomposition. Use background extension
only when it does not create a decorative frame, blur important content, or
make the foreground look like a pasted vertical video.

## Pilot comparison

Compare source and pilot at matching timestamps for:

- structure and cut order
- actor visibility and dialogue role
- key copy and claim strength
- gameplay event and UI meaning
- voice start/end and reaction timing
- caption footprint and subject occlusion
- BGM/SFX energy
- endcard transition, logo, CTA, and final frame

Write differences as `preserved`, `localized`, `approved exception`, or
`defect`. Any unexplained difference is a defect and blocks batch expansion.
