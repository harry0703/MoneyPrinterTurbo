# HC20260810-003 first-frame QA v01

## Closeout status

- Formal inputs: 10/10, S01-S10 continuous, all mechanically verified at 1080x1920 PNG.
- Review previews: 10/10, stored only under storyboard_with_copy/, all mechanically verified at 1080x1920.
- Candidate files: selected raster sources in base=10, editable SVG sources=1, rejected candidate evidence=16, archived superseded formals=2. Independent candidate counts are recorded per shot in asset-inventory-v01.csv.
- Contact sheets: firstframes-contactsheet-v01.png and storyboard-with-copy-contactsheet-v01.png were rebuilt as deterministic 5x2 sheets and visually inspected.
- Isolation: the formal Grok-input root contains only text-free formal images; Chinese copy remains in the review-preview layer.
- Scope: this closeout records verified filesystem facts and sampled/contact-sheet visual review. The 2026-08-14 candidate audit below is a fresh original-resolution inspection of only S01/S02/S04/S06/S09 selected and independently rejected candidates; no fresh inspection is claimed for other shots.

## Per-shot mechanical record

| Shot | Formal dimensions | Formal SHA-256 | Candidate files | Independent bytes | Selected-source record | Result |
|---|---|---|---:|---:|---|---|
| S01 | 1080x1920 | 32fad8b746573df906464e3acbc66adcf5a7e4d04c5a56cd10d828bcc4b6a358 | 2 | 2 | base/S01-candidate-B.png | mechanical PASS |
| S02 | 1080x1920 | 05309d5c341f121a8c0a400f17f748bf1457bbecc3f36168632e841103c1d080 | 2 | 2 | base/S02-candidate-A.png | mechanical PASS |
| S03 | 1080x1920 | 301d09376129abe9858ac34f48e9f35683347f214d80de4dee8ada08f87e34db | 4 | 4 | base/S03-candidate-C-v02-selected-source.png | visual + mechanical PASS |
| S04 | 1080x1920 | 06a0cca336f9c9ac43b082c507c23b0088adabd85a5cc4cbc7cfda418f2fff45 | 2 | 2 | base/S04-candidate-B.png | mechanical PASS |
| S05 | 1080x1920 | 802b42cc210425d087f335882ea36a37f8a26e2281304e26ccd208dc4105e960 | 1 | 1 | base/S05-candidate-A.png | mechanical PASS |
| S06 | 1080x1920 | 62d9fee71a209ce1cea3e39061749507a0c296454589c7f4a294f18b3e859ee2 | 2 | 2 | base/S06-candidate-B.png | mechanical PASS |
| S07 | 1080x1920 | 4b00b7752cae6bd2d3e9b8b921148a8e74e17642b7691894bea50460b5b80515 | 5 | 5 | base/S07-candidate-E-v02.png | visual + mechanical PASS |
| S08 | 1080x1920 | aaaca833b87a55a4c4f8086ded09f959fa0e2730f07c8ccad4912d81eb976217 | 2 | 2 | base/S08-candidate-A.png | mechanical PASS |
| S09 | 1080x1920 | bff8a986fb10938fe4f58d16c29ddc13e1d8ff6e92e3883da0cad3f99f4ec611 | 3 | 3 | base/S09-candidate-C.png | mechanical PASS |
| S10 | 1080x1920 | c2a5f88d4c681ebf5a373561823705b7109c68faaf63374686c1bbcd91ee1f47 | 3 | 3 | base/S10-candidate-A.png | mechanical PASS |

## Visual-review record

- Formal and review contact sheets were opened with view_image after the final deterministic rebuild.
- At least S01 and S10 formal frames were independently sampled for this episode; additional risk shots were sampled where the audit found a visible concern.
- S03 remediation was opened at original resolution: the formal is a text-free left/right tabletop still life with an empty bowl on the left and a same-style added meal plate on the right. It contains no chart, person, paper or notebook.
- S07 remediation was opened at original resolution after a deterministic SVG revision: the deep-teal open C-shaped plate retains a conspicuous gap, while short chopsticks and a pale-peach spoon on its right establish an ordinary place-setting cue. It has no baseline, semicircle, tick, gauge, graph or text.
- The rebuilt formal and storyboard-with-copy 5x2 sheets were opened after replacement. Existing Chinese review copy remains “开始盛多少 / 是否添加” and “不设统一份量”; formal files remain text-free.
- Candidate-quality statements from older QA files are retained only where they already existed; newly created closeout documents do not retrofit unobserved rejection reasons.

## Remediation archive record

- S03 superseded formal: `_rejected/S03-old-formal-chart-like.png`, SHA-256 `c08435561219967976741e4275b0fd123577453a13c57359ee0d8ce019429708`; retired source: `_rejected/S03-candidate-A-retired-chart-like.png`.
- S07 superseded formal: `_rejected/S07-old-formal-baseline-risk.png`, SHA-256 `9e1866c4adafeba22d074eb91308176771704b16d728e7374e6c9ab4cbb7af62`; retired source: `_rejected/S07-candidate-A-retired-baseline-risk.png`.

## Candidate visual decision audit (2026-08-14)

Character reference was reopened at original resolution before this audit. Every selected source and every independent rejected source named below was then reopened individually with `view_image`; conclusions are based on visible content rather than filenames or presumed historical intent.

| Shot | Why selected | Why rejected | Candidate result |
|---|---|---|---|
| S01 | B keeps the reference face/hair/clothes, shows a seated pause looking at the personal plate, complete hands, one serving dish and one serving spoon. | A still has both hands moving/holding the personal plate, so it reads as continued plate movement rather than a pause. | selected PASS |
| S02 | A retains the serving dish/personal-plate relationship while one complete hand lowers the single serving spoon beside the shared dish. | B is cropped too tightly to preserve the personal-plate context, making “put back” versus “pick up” less legible. | selected PASS |
| S04 | B suspends one fork above the plate without food contact; the other hand is resting, so the stop is readable. | A points/touches the food with the fork and adds a foreground spoon, which reads as continued eating and diffuses the action. | selected PASS |
| S06 | B shows one spoon with a small portion above an empty personal plate, with the shared dish at left. | A already has food on the personal plate and carries more on the spoon, which reads as adding again. | selected PASS |
| S09 | C shows the fork resting on the plate while the reference character is mid-rise with complete hands and feet. | A still reaches toward/touches the fork; B is already fully upright, so neither preserves the two-step transition as clearly. | selected PASS |

Across these 5 shots, visible hands/object counts are coherent, 9:16 action subjects remain inside the safe area, and no text, logo, watermark, paper, pen, notebook or medical-device prop was observed. Full Chinese reasons are recorded in the corresponding `decision_record` cells of `asset-inventory-v01.csv`. No image was changed by this audit.

## Gate

**FIRST-FRAME REMEDIATION DOCUMENTED AND VERIFIED.** This is a first-frame documentation/preview closeout only. It is not Task 8 factual approval, final QA authorization, Grok-video completion, or platform release approval.
