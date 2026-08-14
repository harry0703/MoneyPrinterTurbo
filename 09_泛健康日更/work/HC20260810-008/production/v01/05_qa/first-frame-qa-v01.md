# HC20260810-008 first-frame QA v01

## Closeout status

- Formal inputs: 10/10, S01-S10 continuous, all mechanically verified at 1080x1920 PNG.
- Review previews: 10/10, stored only under storyboard_with_copy/, all mechanically verified at 1080x1920.
- Candidate files: base=11, _rejected=10. Evidence-path and independent-generation counts are recorded per shot in asset-inventory-v01.csv; the archived old formal duplicates the prior selected-source bytes and is not counted as a new generated source.
- Contact sheets: firstframes-contactsheet-v01.png and storyboard-with-copy-contactsheet-v01.png were rebuilt as deterministic 5x2 sheets and visually inspected.
- Isolation: the formal Grok-input root contains only text-free formal images; Chinese copy remains in the review-preview layer.
- Scope: this closeout records verified filesystem facts and sampled/contact-sheet visual review. The 2026-08-14 candidate audit below is a fresh original-resolution inspection of only S01/S03/S09 selected and independently rejected candidates; no fresh inspection is claimed for other shots.

## Per-shot mechanical record

| Shot | Formal dimensions | Formal SHA-256 | Evidence paths | Independent generated sources | Selected-source record | Result |
|---|---|---|---:|---:|---|---|
| S01 | 1080x1920 | 002ab59747f69f72d24e58104048b803e386db6946054d457e62fb8b7a0dde86 | 2 | 2 | base/HC20260810-008-v01-S01-selected-source.png | mechanical PASS |
| S02 | 1080x1920 | 84197b437f9336c7063b867f67af04acb7dd1d3fdd6e24452bc87dcf64312cb9 | 1 | 1 | base/HC20260810-008-v01-S02-selected-source.png | mechanical PASS |
| S03 | 1080x1920 | 8ecebf818b6d9971d2b59f9fae7b8f43bc09b84d74b2afe0d65fba4715bcf9f3 | 2 | 2 | base/HC20260810-008-v01-S03-selected-source.png | mechanical PASS |
| S04 | 1080x1920 | 6c9b2689e407458d1bc761769a300db31ab55243fd80da2588584aab3420378b | 2 | 2 | base/HC20260810-008-v01-S04-B-selected-source.png | mechanical PASS |
| S05 | 1080x1920 | c6034c67f12693a0470b16aa06868e8cfc344df45086021f7854735c22d661e8 | 2 | 2 | base/HC20260810-008-v01-S05-selected-source.png | mechanical PASS |
| S06 | 1080x1920 | 8dcbb571e735c6e6dd6ff38d2841ec7596d836f5f48ad3aebf680a2f78072664 | 6 | 5 | base/HC20260810-008-v01-S06-E-phone-audit-selected-source.png | phone-audit repaired; mechanical PASS |
| S07 | 1080x1920 | 2f6d97df70fb1d476a3a77cfb3c5099b63df725f740a836752719576e24140cd | 2 | 2 | base/HC20260810-008-v01-S07-selected-source.png | mechanical PASS |
| S08 | 1080x1920 | 3c98beb544d663af85a44bc401bbb3ff5d564001320032188a17a4b1a7862737 | 1 | 1 | base/HC20260810-008-v01-S08-selected-source.png | mechanical PASS |
| S09 | 1080x1920 | b56dfa9702d007b1811e1fef74de6c09d6a2236c2ee6eb0b5571a50c13ffee3c | 2 | 2 | base/HC20260810-008-v01-S09-selected-source.png | mechanical PASS |
| S10 | 1080x1920 | 8073574da8f41c7f56985ef09736c516a4e73841507594fb704317cb021b0320 | 1 | 1 | base/HC20260810-008-v01-S10-selected-source.png | mechanical PASS |

## Visual-review record

- Formal and review contact sheets were opened with view_image after the final deterministic rebuild.
- At least S01 and S10 formal frames were independently sampled for this episode; additional risk shots were sampled where the audit found a visible concern.
- S04 was replaced by the community-bench version and its preview/contact sheets were refreshed. S04, S05 and S07 now each have two independent candidates with reason-coded rejected filenames.
- Candidate-quality statements from older QA files are retained only where they already existed; newly created closeout documents do not retrofit unobserved rejection reasons.

## Phone-audit repair record (2026-08-14)

- S06 selected source: `base/HC20260810-008-v01-S06-E-phone-audit-selected-source.png`, SHA-256 `d522ed9c1031966ceb169f59b2ad9deb1b609e9964de05cefe24aff362e1eebf`.
- New formal SHA-256: `8dcbb571e735c6e6dd6ff38d2841ec7596d836f5f48ad3aebf680a2f78072664`; refreshed Chinese-copy preview SHA-256: `8b76b43f7a14d6d4a562ff44034969dadaf1730954dc731038e32b60e12dfde2`.
- Original-resolution visual estimate: visible outer phone body approximately 2.05; complete corners/bezel, solid deep-teal screen, no UI/text/logo/watermark, community over-shoulder camera, and pointing fingertip outside the central 70%. Character reference was supplied to generation.
- Rejections: candidate C `18fdfe78…` approximately 2.36 and fingertip at the lower edge; candidate D `09a5dcc1…` approximately 2.23; old formal `14eb82ea…` approximately 2.50. Older candidate B retains its historical filename without a newly invented qualitative reason.
- All three newly generated originals, the selected formal, refreshed preview and both rebuilt 5x2 episode contact sheets were opened with `view_image` after their respective writes.

## Candidate visual decision audit (2026-08-14)

Character reference was reopened at original resolution before this audit. Every selected source and every independent rejected source named below was reopened individually with `view_image`; conclusions are based on visible content rather than filenames or presumed historical intent.

| Shot | Why selected | Why rejected | Candidate result |
|---|---|---|---|
| S01 | The selected frame matches the reference character and shows one fully open five-finger hand hovering above one snack bowl without taking food; the other hand stays on the thigh. | B curls and lowers the fingers closer to the snack, so it reads as continued grasping. | selected PASS |
| S03 | The selected frame is front-centered with both complete hands separately on the thighs and both feet grounded; the quiet seated action survives thumbnail scale and safe-area crop. | B is smaller/off-center and background highlights compete with the hands and posture. | selected PASS |
| S09 | The selected close view clearly separates one ordinary glass in hand, one large carafe placed behind, and one snack bowl in front. | A is wider, making cup/snack too small and the “carafe far away, only cup at hand” relation less legible. | selected PASS |

Across these 3 shots, reference-character appearance, visible hands/object counts and 9:16 safety are coherent; no text, logo, watermark, paper, pen, notebook or medical-device prop was observed. Full Chinese reasons are recorded in `asset-inventory-v01.csv`. No image was changed by this audit.

## Gate

**DOCUMENTATION COMPLETE WITH DISCLOSED RISKS.** This is a first-frame documentation/preview closeout only. It is not Task 8 factual approval, final QA authorization, Grok-video completion, or platform release approval.
