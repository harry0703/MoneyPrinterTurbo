# HC20260810-005 first-frame QA v01

## Closeout status

- Formal inputs: 10/10, S01-S10 continuous, all mechanically verified at 1080x1920 PNG.
- Review previews: 10/10, stored only under storyboard_with_copy/, all mechanically verified at 1080x1920.
- Candidate files: base=10, _rejected=10. Independent-byte counts are recorded per shot in asset-inventory-v01.csv.
- Contact sheets: firstframes-contactsheet-v01.png and storyboard-with-copy-contactsheet-v01.png were rebuilt as deterministic 5x2 sheets and visually inspected.
- Isolation: the formal Grok-input root contains only text-free formal images; Chinese copy remains in the review-preview layer.
- Scope: this closeout records verified filesystem facts and sampled/contact-sheet visual review. The 2026-08-14 candidate audit below is a fresh original-resolution inspection of only S01/S02/S05/S06/S09 selected and independently rejected candidates; no fresh inspection is claimed for other shots.

## Per-shot mechanical record

| Shot | Formal dimensions | Formal SHA-256 | Candidate files | Independent bytes | Selected-source record | Result |
|---|---|---|---:|---:|---|---|
| S01 | 1080x1920 | 3d7f949c8f6dd935d001dc3be011b64da797203f64f8acd03cd57e6a64150a93 | 2 | 2 | base/HC20260810-005-v01-S01-candidate-A.png | mechanical PASS |
| S02 | 1080x1920 | 03fb5eb2ad52001e9bbe4f0c675bc9011a063522f3c3f69e78f4ff2d67071739 | 2 | 2 | base/HC20260810-005-v01-S02-candidate-B.png | mechanical PASS |
| S03 | 1080x1920 | 84ee0f278cccf95a7107f377b4570a93b17a3122e0af18f36339d235099d3dc0 | 2 | 2 | base/HC20260810-005-v01-S03-base.png | mechanical PASS |
| S04 | 1080x1920 | fb72921c5eea6358eef40cf5c804dbb71ccce56c5fcbf889edbd7313115c57e0 | 2 | 2 | base/HC20260810-005-v01-S04-candidate-B-selected.png | mechanical PASS |
| S05 | 1080x1920 | 860a17d37988a369a3ea14a15ef48741f5f99ff2c2ef7cd89dc6baf9b5a6660b | 2 | 2 | base/HC20260810-005-v01-S05-candidate-A.png | mechanical PASS |
| S06 | 1080x1920 | fb03a5f41501a74ba483a4fcef03f51e18f46dd615fc605e4bd03dcf37838af7 | 2 | 2 | base/HC20260810-005-v01-S06-candidate-A.png | mechanical PASS |
| S07 | 1080x1920 | 5349c0e0599b1c7d25847fb4c1951bbcdd7602cce3d466e03b3518b532cb5397 | 2 | 2 | base/HC20260810-005-v01-S07-candidate-A.png | mechanical PASS |
| S08 | 1080x1920 | b814961c498764a3f97e78195e802cd56c7527b3646e742ea6fc8b72886636a9 | 3 | 2 | base/HC20260810-005-v01-S08-base-v2.png | mechanical PASS |
| S09 | 1080x1920 | 7352ac291770cdf923c8562ef3ad5cf5375263f2ac2dc85239c3795f95b7e584 | 2 | 2 | base/HC20260810-005-v01-S09-candidate-A.png | mechanical PASS |
| S10 | 1080x1920 | fc204e0f197c9ebc70a1f35b69229c906ab2353d48e139f19d69aad730d2d88a | 1 | 1 | base/HC20260810-005-v01-S10-base.png | mechanical PASS |

## Visual-review record

- Formal and review contact sheets were opened with view_image after the final deterministic rebuild.
- At least S01 and S10 formal frames were independently sampled for this episode; additional risk shots were sampled where the audit found a visible concern.
- S04 was replaced by a three-panel image with no person silhouette and its preview/contact sheets were refreshed. Two S08 rejected paths contain identical bytes, so they count as one independent rejected image. The two required contact sheets use complete 5x2 layouts; the obsolete legacy-name sheet is retained under 05_qa/_review_work/ only.
- Candidate-quality statements from older QA files are retained only where they already existed; newly created closeout documents do not retrofit unobserved rejection reasons.

## Candidate visual decision audit (2026-08-14)

Character reference was reopened at original resolution before this audit. Every selected source and every independent rejected source named below was reopened individually with `view_image`; conclusions are based on visible content rather than filenames or presumed historical intent.

| Shot | Why selected | Why rejected | Candidate result |
|---|---|---|---|
| S01 | A is a closer reference-consistent character view, looking stuck at the solid-teal monitor with both complete hands folded away on the lap. | B keeps the hands near the keyboard/desk and the gaze away, so it reads as more ready to work than “not started”. | selected PASS |
| S02 | B is a clean overhead with one monitor, one keyboard and two complete hands clearly withdrawn from the keyboard. | A lets the inverted head/chair intrude and keeps the hands nearer the keyboard, weakening both action and safe-area focus. | selected PASS |
| S05 | A is over-shoulder with four phone corners visible, blank teal screen, natural fingers and an estimated outer ratio about 1:2.1; its central screen area is open for timer animation. | B is visibly too short/wide at about 1:1.6–1.8, below the required 1:2.0–2.2. | selected PASS |
| S06 | A shows the reference character in an unmistakable stride toward the window, with complete hands, legs and feet. | B is already standing still and does not preserve the rise/walk transition. | selected PASS |
| S09 | A shows one large, legible car key with no generated markings, still on an ordinary desk. | B makes the key smaller and introduces three pseudo pictograms/button marks on the fob, adding visual/forbidden-mark risk. | selected PASS |

Across these 5 shots, visible hands/object counts are coherent, 9:16 action subjects remain inside the safe area, and no text, logo, watermark, paper, pen, notebook or medical-device prop was observed in the selected images. Full Chinese reasons are recorded in `asset-inventory-v01.csv`. No image was changed by this audit.

## Gate

**DOCUMENTATION COMPLETE WITH DISCLOSED RISKS.** This is a first-frame documentation/preview closeout only. It is not Task 8 factual approval, final QA authorization, Grok-video completion, or platform release approval.
