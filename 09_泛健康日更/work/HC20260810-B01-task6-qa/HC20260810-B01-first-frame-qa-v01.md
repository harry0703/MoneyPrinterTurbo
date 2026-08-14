# HC20260810-B01 Task 6 batch first-frame QA v01 — R3 evidence refresh

## R3 closeout status

- Scope is evidence refresh only. No episode formal first frame and no episode `storyboard_with_copy` preview was edited by this batch task.
- Inputs were reread after the episode documents and repaired files had stable modification times. The current evidence incorporates the final 004/S01 deterministic posture board, the final 004/S07 phone/action replacement, the final 006/S06 adjudicated-H replacement, five deterministic preview-layout repairs, and the 25-shot candidate-decision audit (including the merged 009 records).
- Batch deliverables were rebuilt from the current episode layers in deterministic episode/shot order: `001/S01` through `010/S10`.
- This document supersedes the former active batch statement that treated 006/S06 outer-body `~1.99` as an unresolved lower-bound risk. That value belongs only to the archived prior-E repair history. The current H formal is `~2.05` outer / `~2.12` screen and the episode P2 is **CLOSED**.
- Gate: **BATCH R3 EVIDENCE CURRENT; LOCAL MECHANICAL AND CONTRACT CHECKS PASS.** The R2 `004/S01` posture-semantics blocker is closed. This is not Task 8 factual approval, final release approval, Grok-video completion, or platform publishing authorization.

## Current official batch artifacts

| Artifact | Role | Dimensions / rows | SHA-256 |
|---|---|---:|---|
| `HC20260810-B01-firstframes-contactsheet-v01.png` | official 25% formal review sheet, 10x10, each cell 270x480 | 2780x4880 | `51ac30b14d602a3a40a849faf693bf115147bd5a40c23ac5737b11894fe39539` |
| `HC20260810-B01-storyboard-with-copy-contactsheet-v01.png` | official 25% Chinese-copy review sheet, 10x10, each cell 270x480 | 2780x4880 | `ed37a388606fd387732ea1dfedc1a36ab7f80f1d055dd3ec94a8aa2629b04a3e` |
| `HC20260810-B01-firstframes-overview-12p5pct-v01.png` | navigation-only derivative of current formal sheet | 1390x2440 | `1e5c9709e0d7b79d82a88b0af7266f244ff7187e455da7ec02c5b7863a0388bb` |
| `HC20260810-B01-storyboard-with-copy-overview-12p5pct-v01.png` | navigation-only derivative of current preview sheet | 1390x2440 | `c643453f458bed7ce992f7d4d6dd707a3858f8dc16bcce3fc0c510b8e7431ef9` |
| `HC20260810-B01-phone-ratio-review-v01.png` | current 13-shot phone montage, row-major order below | 1112x1952 | `1285699a9742548f27b64f785785fb7da3a74be7e03d9dde1c5b282c5dfab026` |
| `HC20260810-B01-first-frame-inventory-v01.csv` | current-disk 100-row batch inventory | 100 rows | `faac2d14d50a9ccbd6dee6edfbab49e74e2b3e017d35430764b4d546aeefa787` |
| `HC20260810-B01-first-frame-final-matrix-v01.csv` | original planning matrix plus current actual evidence | 100 rows | `a0b61710f4b2aa2d705f47c375138a979e88d41eee2a692cce3347bab23808d2` |

The two `overview-12p5pct` files were regenerated from the current official 25% sheets. They are navigation aids only and must not be substituted for the 270x480-per-cell official review sheets. The current phone montage was likewise regenerated after the formal replacements; older phone montages and old batch conclusions are not valid review evidence.

## Mechanical and provenance audit

| Check | Current result |
|---|---:|
| Formal first frames resolved from episode roots | 100/100 |
| Chinese-copy previews resolved from `storyboard_with_copy/` | 100/100 |
| Formal dimensions 1080x1920 | 100/100 |
| Preview dimensions 1080x1920 | 100/100 |
| Unique formal SHA-256 values | 100/100 |
| Unique preview SHA-256 values | 100/100 |
| Identical SHA-256 across formal and preview layers | 0 |
| Active candidate PNG evidence paths, excluding filenames marked `old-formal` | 213 |
| Audit-adjusted independent generated sources | 201 |
| Matrix minimum independent candidates required | 164 |
| Shots below their matrix candidate minimum | 0/100 |
| Selected-candidate paths missing | 0/100 |
| Source inventory / episode QA / two episode contact sheets | 10/10 episodes |
| Episode inventory rows | 10 per episode, 100 total |
| Episode contact-sheet dimensions | 1446x1008 for all 20 sheets |
| Original 19 planning fields changed in final matrix | 0 |

`candidate_file_count` is a filesystem evidence-path count after excluding files explicitly named `old-formal`. `actual_independent_candidate_count` is the stricter generation-source count from the episode audit and does not inflate the total for mirrors, archives, crops, color edits, or derived resampling. In particular, 006/S06 selected H is derived from independent source G and does not add an eighth generation source: the shot remains seven independent generated sources. All 100 shots meet or exceed `candidate_minimum` under this stricter count.

## Candidate-decision R3 audit

The following 25 requested candidate-bearing shots have substantive source-level `decision_record`, `decision_note`, or `rejection_reason` text in the refreshed batch inventory; placeholder phrases such as “historical qualitative reason not recorded” are not accepted for this set.

- 003: S01, S02, S04, S06, S09
- 004: S01, S04, S07
- 005: S01, S02, S05, S06, S09
- 008: S01, S03, S09
- 009: S01, S03, S04, S05, S06, S09
- 010: S01, S02, S04

Result: 25/25 rows present; empty or placeholder decision records 0/25. The 009 decisions are read from the current merged episode inventory/QA rather than a detached batch-side note.

## Closed repair audit

### 004/S01 — seated/walking posture semantics closed

- Current formal SHA-256: `18c8c7da776a75dacc1329f2bd40a489d95ae29ddf480fc51c0f1afe1d8c984f`.
- Selected deterministic source: `base/S01-candidate-C-deterministic-selected-source.png`, same SHA-256 as the formal; editable SVG SHA-256: `d0ba0ff6e50257649ff011354d8afdc44a93b6cce5e8e44b6c5dadd3364c6ab3`.
- The seven vertically ordered tiles now show seated silhouettes with chair, bent knee and grounded foot at positions 1/3/5/7, alternating with walking silhouettes with split legs and counter-swinging arms at positions 2/4/6. Both posture classes remain distinguishable in the official 270x480 review cell.
- The former formal/A bytes (`0035cdf557cb091dacde64c76e831545ed791a822497baceebada3a3061a7393`) are retained only as archived rejection history. Candidate B was also rejected because its ring-and-dot layout did not carry posture or linear-order semantics. The active formal remains text-free and contains no Logo, UI, paper/pen/notebook or medical signal.

### 004/S07 — phone/action repair closed

- Current formal SHA-256: `86f018f359ac4fb07d47a191a92ed1774f06e6803c34c31b261a0c5768d8958a`.
- Selected original: `base/S07-candidate-C-phone-audit-selected-source.png`, SHA-256 `3c19c703628c46f185bcaa2fb6fe01b9a623b3afe63b30ce804889d2c1031814`.
- Original-resolution measurement recorded by episode QA: screen approximately `2.17`; outer body approximately `2.13–2.17`. Both are within the mandatory `2.0–2.2` interval. The blank screen is uniform, all four phone corners are present, and the pointing finger has an air gap outside the screen.
- Action/camera now show the locked character standing and stopped on a flat community path in a three-quarter rear-side view. The prior short-phone/wrong-angle formal remains preserved at `_rejected/...S07-old-formal-rejected-phone-ratio-camera-angle.png`, SHA-256 `e8b538fdbdc1482b3855621b7df7c332c63a1dc081a9fc8769e8ea7dd80e46b7`; it is not active evidence.

### 006/S06 — phone P2 closed

- Current formal SHA-256: `f5681f85197e05004527028eb3752087183ed0f3c3e29b8aa9930cb0dfbde5b8`.
- Selected H source: `base/HC20260810-006-v01-S06-candidate-h-phone-adjudication-selected-source.png`, SHA-256 `524c31499a80ba096d14e8bf7b43d4e59d401f8e0493a895023607cd880a191c`.
- Independent original-resolution adjudication recorded by episode QA: outer body approximately `2.05`; screen approximately `2.12`. Both pass the accepted P2 range `2.05–2.15` and the base contract `2.0–2.2`. The deep-teal screen is visually uniform, bezel/corners are complete, and the pointing finger remains outside the screen.
- Historical repair record only: prior E had screen `~2.02` and outer body `~1.99`; it was archived at `_rejected/...S06-old-formal-e-replaced-by-adjudicated-h.png`, SHA-256 `e0f097fefb3694fd730ecfcd4494d78132d5afa69fd237230838170c48de7657`. It is not the current formal and its former lower-bound P2 concern is closed, not carried as an active batch residual.

### Five deterministic preview safe-zone repairs closed

Only the copy-board placement changed; the corresponding formal image hashes remained unchanged.

| Shot | Current preview SHA-256 | Board placement | Current result |
|---|---|---|---|
| 001/S04 | `22c785e1ce08cd01eb52406fb6043f70c3283558a927101ffbe9b1fdb9b13a8b` | `(54,96)-(400,396)`, compact top-left | face, hand, spoon and plate clear |
| 001/S05 | `a3f85dcec6e2b81bd52bc189811c5da1d8420e330112e02a927a2e83d1f906cd` | `(54,520)-(390,820)`, left background/window | walking action and body clear |
| 001/S09 | `950135c5cef3cf1b42e2f46143e14824d4177c24496df7485ca093870e0e749e` | `(54,560)-(410,860)`, left background | face, hand, key, tray and feet clear |
| 009/S04 | `9d400e9689280451db2fa0a0bd2e6de02dc63c0d03aac0c4949d3381418576e4` | `(580,96)-(1026,400)`, compact top-right | face, hands, monitor and sit-up action clear |
| 009/S09 | `a6c1175fca3c61264bd68350abffafa625c9d85c9dc63f996f9dc42739f1675b` | `(54,96)-(550,420)`, compact top-left | face, hands, monitor and gaze shift clear |

All five refreshed batch rows now carry `PASS-remediated-preview-layout;copy-contained;subject-and-action-clear`.

## Phone montage index and restrictions

`HC20260810-B01-phone-ratio-review-v01.png` is row-major in this exact order:

1. 001/S06, 001/S07, 004/S07, 005/S05
2. 006/S01, 006/S03, 006/S05, 006/S06
3. 006/S08, 007/S05, 007/S06, 008/S06
4. 010/S02

The montage was opened after rebuild. Current 004/S07 and 006/S06 are present, not their archived predecessors. 010/S02 shows only the phone back. It is restricted to a static prop/composition role: it is not evidence for a visible screen, phone ratio, UI replacement, four-corner screen tracking, or animated screen content.

## Visual-review method and result

- The current official 25% formal and preview sheets were inspected at their native 2780x4880 resolution through four non-resampled 1390x2440 quadrants per sheet. This preserves the official 270x480 cell review scale.
- The formal quadrants containing 004/S01, 004/S07 and 006/S06 were reopened after the final batch rebuild. The repaired 004/S01 posture sequence is readable at the official 25% scale; the two repaired phone shots visually match the current episode evidence and regenerated phone montage.
- The preview quadrants containing 001/S04, 001/S05, 001/S09, 009/S04 and 009/S09 were reopened after rebuild; the five deterministic boards are visibly clear of the named subject/action anchors.
- The 13-shot phone montage was reopened at original resolution. No stale prior-E 006/S06 image was observed, and 010/S02 remains visibly back-only.
- Contact-sheet review is a batch-scale check, not a substitute for full-resolution individual approval of all 200 layers. Non-remediated preview rows retain their existing episode/batch review status and are not silently upgraded.

## Residual risks and boundaries

- **010/S02:** static phone-back prop only; no screen/UI/ratio/tracking claim is permitted.
- **004/S07:** its phone ratio is inside the contract but close to the upper bound; any downstream motion or compositing must preserve aspect ratio and must not stretch the phone vertically.
- A 25% batch contact sheet cannot prove every fine hand/finger defect, tiny watermark, or edge artifact at 1080x1920. Full-resolution final visual review remains a separate authorization gate.
- Candidate counts, hashes, dimensions, and layer separation are mechanically verified. Medical/factual correctness, platform compliance, Grok motion continuity, and publishing safety belong to later tasks.

## R3 batch gate

**PASS for current Task 6 batch evidence refresh.** The active batch evidence is bound to the current 004/S01, 004/S07 and 006/S06 hashes, the five repaired preview hashes, 201 audit-adjusted independent candidate sources, and the two current official 25% sheets. The former 004/S01 posture ambiguity and former active 006/S06 `~1.99` phone-ratio residual are closed and retained only in repair history. Independent R3 review and downstream gates remain required before release.
