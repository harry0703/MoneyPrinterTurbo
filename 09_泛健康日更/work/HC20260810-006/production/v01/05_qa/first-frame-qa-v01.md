# HC20260810-006 first-frame QA v01

## Closeout status

- Formal inputs: 10/10, S01-S10 continuous, all mechanically verified at 1080x1920 PNG.
- Review previews: 10/10, stored only under storyboard_with_copy/, all mechanically verified at 1080x1920.
- Candidate files: base=14, _rejected=16. Evidence-path and independent-generation counts are recorded per shot in asset-inventory-v01.csv; selected H is a G-derived edit and archived old formals are not counted as new independent generated sources.
- Contact sheets: firstframes-contactsheet-v01.png and storyboard-with-copy-contactsheet-v01.png were rebuilt as deterministic 5x2 sheets and visually inspected.
- Isolation: the formal Grok-input root contains only text-free formal images; Chinese copy remains in the review-preview layer.
- Scope: this closeout records verified filesystem facts and sampled/contact-sheet visual review. It does not invent historical candidate decisions or claim that every candidate was newly inspected.

## Per-shot mechanical record

| Shot | Formal dimensions | Formal SHA-256 | Evidence paths | Independent generated sources | Selected-source record | Result |
|---|---|---|---:|---:|---|---|
| S01 | 1080x1920 | bb69eac4f625277a5b4cae88930d332d89fa665eaa2442d720a9b451a4989229 | 4 | 3 | base/HC20260810-006-v01-S01-candidate-c-phone-audit-selected-source.png | phone-audit repaired; mechanical PASS |
| S02 | 1080x1920 | 20a14d22ade2122be92f23655185bab3989fed4297de61867b0d795afc64c616 | 1 | 1 | base/HC20260810-006-v01-S02-candidate-a.png | mechanical PASS |
| S03 | 1080x1920 | 60de6bec80a1df458d969ca5dea06462e87b04b8313e36922837217cf3e11128 | 2 | 2 | base/HC20260810-006-v01-S03-candidate-b.png | mechanical PASS |
| S04 | 1080x1920 | 36df82d591b4f379ef6aa15a46d7c3d3ec6837a8d9c627e02eea470d304371ce | 1 | 1 | base/HC20260810-006-v01-S04-candidate-a.png | mechanical PASS |
| S05 | 1080x1920 | 43e64290ae7dad7d101e4aeac18425c466d4f42df51b74dbb11c3c289b29b73d | 4 | 3 | base/HC20260810-006-v01-S05-candidate-c-phone-audit-selected-source.png | phone-audit repaired; mechanical PASS |
| S06 | 1080x1920 | f5681f85197e05004527028eb3752087183ed0f3c3e29b8aa9930cb0dfbde5b8 | 11 | 7 | base/HC20260810-006-v01-S06-candidate-h-phone-adjudication-selected-source.png | independently adjudicated H selected; phone P2 CLOSED; mechanical PASS |
| S07 | 1080x1920 | 8ef36806244aa23ec5c2de5b6352ac4cdedc441ea4e5d4a0e4884703c1c3c7fd | 2 | 2 | base/HC20260810-006-v01-S07-candidate-b.png | mechanical PASS |
| S08 | 1080x1920 | 3b87681f9f908d12f5810ad567b3d95352d7907432458e11dd3d6072fbca223f | 2 | 2 | base/HC20260810-006-v01-S08-candidate-b.png | mechanical PASS |
| S09 | 1080x1920 | 88b13bc976ce3192467d267dddc7536c870200c0a5c369cff1b268dccfcc4b8c | 1 | 1 | base/HC20260810-006-v01-S09-candidate-a.png | mechanical PASS |
| S10 | 1080x1920 | 6da9004450024f7c3df3fffe3e0e18fdf3f1d3751327855dbb2abe78f68ddadd | 2 | 2 | base/HC20260810-006-v01-S10-candidate-b.png | mechanical PASS |

## Visual-review record

- Formal and review contact sheets were opened with view_image after the final deterministic rebuild.
- At least S01 and S10 formal frames were independently sampled for this episode; the final S06 H source, 1080x1920 formal, Chinese-copy preview and both rebuilt contact sheets were each opened at original resolution after the replacement.
- No additional one-ticket issue was observed in the sampled formal frames and final contact sheets; this closeout does not claim a fresh individual inspection of every candidate.
- Candidate-quality statements from older QA files are retained only where they already existed; newly created closeout documents do not retrofit unobserved rejection reasons.

## Phone-audit repair record (2026-08-14)

| Shot | Selected source / formal SHA-256 | Phone-ratio estimate | Verified image facts | Rejected/archived reason |
|---|---|---|---|---|
| S01 | `e8fdb036…` / `bb69eac…` | intrinsic design approximately 2.10; oblique projection not treated as a literal pixel ratio | complete unbranded phone, solid deep-teal screen, no UI/text/watermark; character reference used | old formal `29569153…`: approximately 1.68 plus screen artifacts |
| S05 | `ff6464db…` / `43e64290…` | intrinsic design approximately 2.10 under strong tabletop perspective | one phone lies flat and untouched; no silver stylus, second device or ghosting; character reference used | old formal `c74f3f62…`: silver stylus/second-device ghost |
| S06 | `524c3149…` / `f5681f85…` | outer body approximately 2.05; screen approximately 2.12; both PASS the accepted 2.05-2.15 P2 range | over-shoulder near-front-on phone; visually uniform deep-teal blank screen; complete bezel/corners; pointing finger remains outside the screen and the central 70% is clear | prior E formal `e0f097fe…`: outer approximately 1.99 and archived; candidate F `687f8a24…`: screen approximately 2.30; original G `2143ce15…`: visible screen gradient |

- Every newly generated source was opened at original resolution with `view_image`; the selected formal, refreshed Chinese-copy preview and both rebuilt 5x2 episode contact sheets were also opened after write.
- Refreshed preview SHA-256 values: S01 `b7d5ef4ef9dd78a47c0670e508023c0a381a57f14f2d0b5c4677eac91d27461a`; S05 `fc1ee135794784f91f329c9dd125817157fbaf253ac4e5e3a5a2512398e8787b`; S06 `7f48611366d54998e3b63f6295cdfc6f7983d3597e9be91432085f7a161d8c7d`.
- Rebuilt contact-sheet SHA-256 values: formal `8edf93d0f20191b61939d1e2f404b94157259765c2ddc9e2ab61d1689e88faf8`; storyboard-with-copy `c14e5e5b81d25d9637e4e1d01c03fc51469ed3c7423a971b1a148467a6b36a24`.
- Historical note: the prior E formal had a screen ratio of approximately 2.02 but an outer-body estimate of approximately 1.99, so it did not clear the stricter P2 contract. It is preserved as `_rejected/HC20260810-006-v01-S06-old-formal-e-replaced-by-adjudicated-h.png`, SHA-256 `e0f097fefb3694fd730ecfcd4494d78132d5afa69fd237230838170c48de7657`.

### S06 independent P2 terminal review

- Requirement: both the maximum outer-body and screen-opening height/width ratios must target 2.08-2.12 (acceptable 2.05-2.15), with a pure solid deep-teal/deep-gray blank screen, complete corners/bezel, and the fingertip outside the screen while central 70% remains clear.
- Candidate F: `_rejected/HC20260810-006-v01-S06-candidate-f-rejected-screen-ratio-2.30.png`, SHA-256 `687f8a24155e161224d597bd030d42366329e5a7e732014abf409d6a1aef8069`. Original-resolution estimate: outer approximately 2.13, screen approximately 2.30. Rejected for screen geometry above 2.15.
- Candidate G: `_rejected/HC20260810-006-v01-S06-candidate-g-rejected-screen-gradient-outer-2.05-screen-2.12.png`, SHA-256 `2143ce1530c48c9c6e869431ce6afef92539019ae64f633992f870ee25fb48f1`. Strict maximum-bound estimate: outer approximately `455/222 = 2.05`, screen approximately `437/206 = 2.12`. Geometry passes the acceptable range, but the conservative screen interior has top luminance mean approximately 51 versus bottom approximately 35, so the visible gradient violates the pure-solid-screen contract.
- Candidate H: `base/HC20260810-006-v01-S06-candidate-h-phone-adjudication-selected-source.png`, SHA-256 `524c31499a80ba096d14e8bf7b43d4e59d401f8e0493a895023607cd880a191c`, 941x1672. This is the former G-only edit01 evidence path, moved from `_rejected/HC20260810-006-v01-S06-candidate-edit01-rejected-non-screen-pixel-drift.png` into `base/` without retaining duplicate bytes. Independent original-resolution visual adjudication accepted H: outer approximately 2.05, screen approximately 2.12, visually uniform deep-teal screen, complete corners/bezel, and pointing finger outside the screen. S06 is therefore **P2 CLOSED**.
- H was formalized with aspect-preserving Lanczos scaling to 1080x1919 and one duplicated bottom edge row to satisfy the exact 1080x1920 canvas; no source content was cropped. The resulting formal SHA-256 is `f5681f85197e05004527028eb3752087183ed0f3c3e29b8aa9930cb0dfbde5b8`.

### S06 G-only edit continuation and adjudication

- Edit 01 / selected H: `base/HC20260810-006-v01-S06-candidate-h-phone-adjudication-selected-source.png`, SHA-256 `524c31499a80ba096d14e8bf7b43d4e59d401f8e0493a895023607cd880a191c`, 941x1672. The screen is nearly uniform (conservative interior top/middle/bottom means approximately 48.92/48.71/48.40). A previous pixel-only comparison found broad small-value resampling differences outside the phone; independent full-image visual adjudication found no visible object, anatomy, composition or scene drift. Pixel resampling is not itself visual drift, so that earlier rejection is superseded and the file is selected as H.
- Edit 02: `_rejected/HC20260810-006-v01-S06-candidate-edit02-rejected-dimension-and-non-screen-drift.png`, SHA-256 `abd155b4d1233b7019fa3d0fcfd3cb78e45c937a95b08c45a4e63db3712d5bcd`, 941x1670. It changed the source height from 1672 to 1670; over the aligned area, approximately 66.8% of outside pixels changed by more than 3 channel levels. Rejected for dimension and non-screen drift.
- Both edits used candidate G as the only built-in imagegen edit target. Edit02 remains rejected; Edit01 is now the sole selected H path and is not duplicated under `_rejected/`. The selected H source, formal, preview and two contact sheets were opened with `view_image` after the final write.

## Gate

**DOCUMENTATION COMPLETE; S06 FIRST-FRAME P2 CLOSED.** This is a first-frame documentation/preview closeout only. It is not Task 8 factual approval, final QA authorization, Grok-video completion, or platform release approval.
