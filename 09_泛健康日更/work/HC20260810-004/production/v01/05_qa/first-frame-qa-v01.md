# HC20260810-004 first-frame QA v01

## Closeout status

- Formal inputs: 10/10, S01-S10 continuous, all mechanically verified at 1080x1920 PNG.
- Review previews: 10/10, stored only under storyboard_with_copy/, all mechanically verified at 1080x1920.
- Candidate images: base=12, _rejected=9; one additional editable SVG source belongs to S01. Independent-byte counts are recorded per shot in asset-inventory-v01.csv.
- Contact sheets: firstframes-contactsheet-v01.png and storyboard-with-copy-contactsheet-v01.png were rebuilt as deterministic 5x2 sheets and visually inspected.
- Isolation: the formal Grok-input root contains only text-free formal images; Chinese copy remains in the review-preview layer.
- Scope: this closeout records verified filesystem facts and sampled/contact-sheet visual review. The 2026-08-14 candidate audit below is a fresh original-resolution inspection of only S01/S04/S07 selected and independently rejected candidates; no fresh inspection is claimed for other shots.

## Per-shot mechanical record

| Shot | Formal dimensions | Formal SHA-256 | Candidate files | Independent bytes | Selected-source record | Result |
|---|---|---|---:|---:|---|---|
| S01 | 1080x1920 | 18c8c7da776a75dacc1329f2bd40a489d95ae29ddf480fc51c0f1afe1d8c984f | 4 | 3 | base/S01-candidate-C-deterministic-selected-source.png | deterministic posture-semantics PASS |
| S02 | 1080x1920 | e9d089b1b5e08b59efeccfae05c3d98f28620d8d01690a9c5216a1614368f45d | 1 | 1 | base/S02-candidate-A.png | mechanical PASS |
| S03 | 1080x1920 | 950757e90a34ee63a3377b026dacd0d2d2bc28120f75c4adb0b31cdbc6815cee | 2 | 2 | base/S03-candidate-A.png | mechanical PASS |
| S04 | 1080x1920 | a4acd32ca95071875366d6ad082221ad41e8f1e949301a4b78b1d7df33034d1b | 2 | 2 | base/S04-candidate-B.png | mechanical PASS |
| S05 | 1080x1920 | 9b6be7190d64657d80b949214bc827c0ad2d39c43286cd2f99be5fabd2a7351e | 2 | 2 | base/S05-candidate-A.png | mechanical PASS |
| S06 | 1080x1920 | 36fd7218d48a35b33f354e7c07c0ec42c3597113ad21cb27aa84006ed3dfaa96 | 2 | 2 | base/S06-candidate-A.png | mechanical PASS |
| S07 | 1080x1920 | 86f018f359ac4fb07d47a191a92ed1774f06e6803c34c31b261a0c5768d8958a | 4 | 3 | base/S07-candidate-C-phone-audit-selected-source.png | phone/action contract PASS |
| S08 | 1080x1920 | 62165c540f63c02a5ee6803b0fc08c3be195e274d003dace014cc165969ca24e | 1 | 1 | base/S08-candidate-A.png | mechanical PASS |
| S09 | 1080x1920 | 87181d1586621c93b031fe4542c99056a2b6eeee2f8234bfac41498d68765705 | 2 | 2 | base/S09-candidate-B.png | mechanical PASS |
| S10 | 1080x1920 | 6729c508cf00d90ab3434f3770fb18da72160abd5c38941ea0cfdf2883e7b608 | 1 | 1 | base/S10-candidate-A.png | mechanical PASS |

## Visual-review record

- Formal and review contact sheets were opened with view_image after the final deterministic rebuild.
- At least S01 and S10 formal frames were independently sampled for this episode; additional risk shots were sampled where the audit found a visible concern.
- No additional one-ticket issue was observed in the sampled formal frames and final contact sheets; this closeout does not claim a fresh individual inspection of every candidate.
- Candidate-quality statements from older QA files are retained only where they already existed; newly created closeout documents do not retrofit unobserved rejection reasons.

## Candidate visual decision audit (2026-08-14)

Character reference was reopened at original resolution before this audit. Every selected source and every independent rejected source named below was reopened individually with `view_image`; conclusions are based on visible content rather than filenames or presumed historical intent.

| Shot | Why selected | Why rejected | Candidate result |
|---|---|---|---|
| S01 | New deterministic C has exactly seven vertically ordered tiles. Positions 1/3/5/7 show a seated silhouette with an explicit high chair back, horizontal seat, bent knee and grounded foot; positions 2/4/6 show a walking silhouette with a wide stride and counter-swinging arms. Alternating left/right icon placement and peach/fresh-teal fields remain readable on the 25% contact sheet. | A and its archived old formal use seven nearly identical human glyphs, so the seated/walking difference is ambiguous; B is a central ring with seven dots and has neither posture nor linear order. | **PASS: C closes the seated-versus-walking semantic gap at original resolution and 25% review size.** |
| S04 | B matches the reference character, sits fully on the bench with gaze down, two complete hands on thighs and both feet grounded. | A looks forward/upward and reads more like waiting or route-watching than quietly feeling the moment. | selected PASS |
| S07 | New independent C keeps the locked character standing/stopped at a flat community-path exit in a three-quarter rear-side view. Its single near-front phone has four complete corners, a uniform deep-teal-gray blank screen and a fingertip with visible air gap outside the central 70%. | A and its archived old formal have a visibly short phone (about 1:1.5–1.7) and the wrong camera angle; B has usable phone geometry but seats the character on a bench. | **PASS: original-source screen is about 115/53=2.17; outer-body threshold estimates are about 2.13–2.17. Both are inside the mandatory 2.0–2.2 interval, though slightly above the 2.08–2.12 target center.** |

All eight independent candidate images (ten evidence paths including the two archived old formals) are free of visible text, logo, watermark, paper, pen, notebook and medical-device props, and their visible hands/object counts are coherent. Full Chinese reasons are recorded in `asset-inventory-v01.csv`.

## S01 deterministic-board semantic repair record (2026-08-14)

- Editable source: `base/S01-candidate-C-deterministic-selected-source.svg`, 1080x1920 viewBox, SHA-256 `d0ba0ff6e50257649ff011354d8afdc44a93b6cce5e8e44b6c5dadd3364c6ab3`.
- Selected deterministic PNG source and formal: 1080x1920, SHA-256 `18c8c7da776a75dacc1329f2bd40a489d95ae29ddf480fc51c0f1afe1d8c984f`.
- Chinese-copy review preview: 1080x1920, SHA-256 `ab4bcff1240588b4451c6778e9cc07f6fcc20b97237067c08f6b8c25f3cfde8c`. Copy exists only in `storyboard_with_copy/`; the formal input remains text-free.
- The former formal was preserved at `_rejected/HC20260810-004-v01-S01-old-formal-rejected-posture-ambiguity.png`, SHA-256 `0035cdf557cb091dacde64c76e831545ed791a822497baceebada3a3061a7393`; it intentionally duplicates candidate A bytes and is not counted as a new independent candidate.
- Original A, B, C, new formal and review preview were individually reopened with `view_image`. C visibly contains seven and only seven tiles in the intended seated/walking/seated/walking/seated/walking/seated order. Sitting is established by chair plus bent-knee geometry; walking is established by separated arms and legs. No text, number, Logo, watermark, UI, paper, pen, notebook, medical device or professional-identity signal appears in C or the formal.
- The rebuilt 5x2 formal and preview sheets were reopened with `view_image` at original resolution. S01 remains distinguishable in the first 270x480 cell, so the fix passes the required 25% review.

## S07 phone-audit repair record (2026-08-14)

- Character reference SHA-256: `82626e6832dbc83bd22d1985f02cee9772a36c5bd390449837367c704d525646`.
- Selected original source: `base/S07-candidate-C-phone-audit-selected-source.png`, 941x1672, SHA-256 `3c19c703628c46f185bcaa2fb6fe01b9a623b3afe63b30ce804889d2c1031814`.
- The generated original was opened at original resolution with `view_image`. It visibly contains one standing woman, two grounded feet on one flat path level, one complete near-front phone, no sitting surface, and none of the prohibited text/logo/paper/pen/medical/step/ladder elements.
- Strict phone measurement on the generated original: the uniform screen connected component is approximately 115 px high by 53 px at maximum row width (`2.17`). Multiple dark-body thresholds place the outer body at approximately `2.13–2.17`. Both pass the mandatory `2.0–2.2` interval; neither is represented as exactly meeting the narrower `2.08–2.12` target center.
- Screen color component RGB mean/std is approximately `(33.15,49.11,54.22)/(1.28,1.37,1.61)`; top/middle/bottom band means remain within one channel level, supporting a uniform blank deep-teal-gray screen.
- New formal: 1080x1920, SHA-256 `86f018f359ac4fb07d47a191a92ed1774f06e6803c34c31b261a0c5768d8958a`. New Chinese-copy preview: 1080x1920, SHA-256 `5a682a40a1733dedf4d4efca833429ebbe722629047e5911a012c1f47dc7731b`.
- Old formal was preserved at `_rejected/HC20260810-004-v01-S07-old-formal-rejected-phone-ratio-camera-angle.png`, SHA-256 `e8b538fdbdc1482b3855621b7df7c332c63a1dc081a9fc8769e8ea7dd80e46b7`.
- After the later S01 semantic repair, both final contact sheets were rebuilt again as 1446x1008 5x2 composites and reopened at original resolution with `view_image`: formal sheet SHA-256 `0c07e0979853af4060be622a071f2b1cd3b3ab4afe03bf76581b7a1386ff4cf0`; copy sheet SHA-256 `3d0d66db1b179ed1f824d4bd415014bdc1b139d496752fec809e0d86d7bf5591`.

## Gate

**DOCUMENTATION UPDATED; S01 DETERMINISTIC POSTURE SEMANTICS PASS; S07 PHONE/ACTION CONTRACT PASS.** This closes only the local first-frame repairs. It is not Task 8 factual approval, final QA authorization, Grok-video completion, or platform release approval.
