# HC20260810-007 first-frame QA v01

## Closeout status

- Formal inputs: 10/10, S01-S10 continuous, all mechanically verified at 1080x1920 PNG.
- Review previews: 10/10, stored only under storyboard_with_copy/, all mechanically verified at 1080x1920.
- Candidate files: base=20, _rejected=12. Evidence-path and independent-generation counts are recorded per shot in asset-inventory-v01.csv; mirrored files and archived old formals are not counted as new generated sources.
- Contact sheets: firstframes-contactsheet-v01.png and storyboard-with-copy-contactsheet-v01.png were rebuilt as deterministic 5x2 sheets and visually inspected.
- Isolation: the formal Grok-input root contains only text-free formal images; Chinese copy remains in the review-preview layer.
- Scope: this closeout records verified filesystem facts and sampled/contact-sheet visual review. It does not invent historical candidate decisions or claim that every candidate was newly inspected.

## Per-shot mechanical record

| Shot | Formal dimensions | Formal SHA-256 | Evidence paths | Independent generated sources | Selected-source record | Result |
|---|---|---|---:|---:|---|---|
| S01 | 1080x1920 | 16ec5daff52082f399981e9e98d0986a5c055ecc54a3ac95af8968fedc787cf7 | 3 | 2 | base/HC20260810-007-v01-S01-candidate-01-source.png | mechanical PASS |
| S02 | 1080x1920 | 03689ddc5d1c7b70f6d8d470a3f9cd6390be49e9cfe656594f01052be5f71f83 | 3 | 2 | base/HC20260810-007-v01-S02-candidate-02-source.png | mechanical PASS |
| S03 | 1080x1920 | 2708995cb40bf82de0a015a0465d0be4561e520e8d85c672eb6ffcc04967826d | 3 | 2 | base/HC20260810-007-v01-S03-candidate-01-source.png | mechanical PASS |
| S04 | 1080x1920 | 06b655be8f317a9cf70150074d0412d53fa7856f6c9852587d5f75a978467693 | 3 | 2 | base/HC20260810-007-v01-S04-candidate-02-source.png | mechanical PASS |
| S05 | 1080x1920 | 4c6d64ae276c0099e7aeb07be81dff37d2670bec8955eb3bd97aa9b9c5aa661d | 3 | 2 | base/HC20260810-007-v01-S05-candidate-02-source.png | mechanical PASS |
| S06 | 1080x1920 | 57ec7fd4f7f4d9dc9a1c5ab226cba8832a982f971179b2f769cbf0659d331b05 | 7 | 5 | base/HC20260810-007-v01-S06-candidate-05-phone-audit-selected-source.png | phone-audit repaired; mechanical PASS |
| S07 | 1080x1920 | 4911caa0c6d9fc7389d81091ee5212e6bee31369a1f4b13f8eb88a205b480d56 | 3 | 2 | base/HC20260810-007-v01-S07-candidate-02-source.png | mechanical PASS |
| S08 | 1080x1920 | 2bf5d72920dfacf14e7b8d17e7d8eee7685accb8872894765f3f6aefc75fe73e | 1 | 1 | base/HC20260810-007-v01-S08-candidate-01-source.png | mechanical PASS |
| S09 | 1080x1920 | c487d88970416e894fb900afba52dc81f73564480cecd80bc01847c457e1413d | 3 | 2 | base/HC20260810-007-v01-S09-candidate-02-source.png | mechanical PASS |
| S10 | 1080x1920 | bdf5b8d7459aa4c8011c3b0993fae9f1510f8f8b53888e739adc7f18d70e9d59 | 3 | 2 | base/HC20260810-007-v01-S10-candidate-02-source.png | mechanical PASS |

## Visual-review record

- Formal and review contact sheets were opened with view_image after the final deterministic rebuild.
- At least S01 and S10 formal frames were independently sampled for this episode; additional risk shots were sampled where the audit found a visible concern.
- No additional one-ticket issue was observed in the sampled formal frames and final contact sheets; this closeout does not claim a fresh individual inspection of every candidate.
- Candidate-quality statements from older QA files are retained only where they already existed; newly created closeout documents do not retrofit unobserved rejection reasons.

## Phone-audit repair record (2026-08-14)

- S06 selected source: `base/HC20260810-007-v01-S06-candidate-05-phone-audit-selected-source.png`, SHA-256 `632c94c8e126aa69c3dd1cbfd3efe5292216f6b9856c87a2d2ea288aaa349b45`.
- New formal SHA-256: `57ec7fd4f7f4d9dc9a1c5ab226cba8832a982f971179b2f769cbf0659d331b05`; refreshed Chinese-copy preview SHA-256: `3571a68155cfe0b54cd7694346b4cfd5af336cb8068b6516869ab7747823c1ab`.
- Original-resolution visual estimate: visible outer phone body approximately `441/211 = 2.09`; complete corners/bezel, solid deep-gray screen, no UI/text/logo/watermark, over-shoulder camera, and pointing fingertip outside the central 70%. Character reference was supplied to generation.
- Rejections: candidate-03 `268aa2e2…` approximately 2.20; candidate-04 `7b19afc5…` approximately 2.24 and wrong front-facing-character camera angle; old formal `70640164…` approximately 2.33. The older mirrored candidate-02 has no newly invented qualitative reason.
- All three newly generated originals, the selected formal, refreshed preview and both rebuilt 5x2 episode contact sheets were opened with `view_image` after their respective writes.

## Gate

**DOCUMENTATION COMPLETE WITH DISCLOSED RISKS.** This is a first-frame documentation/preview closeout only. It is not Task 8 factual approval, final QA authorization, Grok-video completion, or platform release approval.
