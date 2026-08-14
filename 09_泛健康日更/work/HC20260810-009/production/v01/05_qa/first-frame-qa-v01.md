# HC20260810-009 first-frame QA v01

## Closeout status

- Formal inputs: 10/10, S01-S10 continuous, all mechanically verified as 1080x1920 PNG.
- Review previews: 10/10, stored only under `storyboard_with_copy/`, all mechanically verified as separate PNG assets.
- Candidate archive: `base/` = 10 files, `_rejected/` = 7 files; 17 files produce 17 distinct SHA-256 values.
- Candidate contract: the batch pre-generation matrix requires 16 independent candidates for this episode; the episode-local matrix is stricter at 17 because S07 is also held to two candidates. Both thresholds are satisfied.
- Contact sheets exist at `05_qa/firstframes-contactsheet-v01.png` and `05_qa/storyboard-with-copy-contactsheet-v01.png`.
- Isolation: formal Grok inputs contain no deterministic copy layer; Chinese copy remains only under `storyboard_with_copy/`.
- Scope: this record distinguishes mechanical facts from contact-sheet visual review. Historical qualitative selection/rejection reasons were absent; the 2026-08-14 section below records a new original-resolution candidate audit based only on currently visible evidence.

## Per-shot mechanical record

| Shot | Formal dimensions | Formal SHA-256 | Local minimum | Candidate files | Independent bytes | Selected-source record | Result |
|---|---|---|---:|---:|---:|---|---|
| S01 | 1080x1920 | a7478087be87307fb311fdf9c9cf38b2ca0edd390c7855b5f255def244be9f29 | 2 | 2 | 2 | base/HC20260810-009-v01-S01-candidate-01-source.png | mechanical PASS / candidate PASS |
| S02 | 1080x1920 | c3dd0d51f8c94117ab0a3edf1d83f5a3de52b2f0f17ef7cb2a4742ae4448361c | 1 | 1 | 1 | base/HC20260810-009-v01-S02-candidate-01-source.png | mechanical PASS / candidate PASS |
| S03 | 1080x1920 | 86fc24aa09c3af1a6f29257659c3da062814161bfd49dd1289dee85b130eef6e | 2 | 2 | 2 | base/HC20260810-009-v01-S03-candidate-02-source.png | mechanical PASS / candidate PASS |
| S04 | 1080x1920 | 1b607d4b6c9f4d2fe3d9f9f3a4e5bac70d9b76738ec25fd922a7c4bfdce5d92a | 2 | 2 | 2 | base/HC20260810-009-v01-S04-candidate-02-source.png | mechanical PASS / candidate PASS |
| S05 | 1080x1920 | 16602795c6cf4c78470b357a70d923d111655177e89e779ea7a46e4127eda738 | 2 | 2 | 2 | base/HC20260810-009-v01-S05-candidate-02-source.png | mechanical PASS / candidate PASS |
| S06 | 1080x1920 | f90c94131ea232d5ef63d6a80f82fba8c628440a40827131bb28e6925b2d622f | 2 | 2 | 2 | base/HC20260810-009-v01-S06-candidate-01-source.png | mechanical PASS / candidate PASS |
| S07 | 1080x1920 | f024a4eecb0aed79318f74d3f84ecfacd3ab1df7b9acc5e47beeb18484cb91ad | 2 | 2 | 2 | base/HC20260810-009-v01-S07-candidate-01-source.png | mechanical PASS / candidate PASS |
| S08 | 1080x1920 | 02814fc8681c0301fde040fe307a99767d8597c085a5f5f8583fd9a46ddcabd4 | 1 | 1 | 1 | base/HC20260810-009-v01-S08-candidate-01-source.png | mechanical PASS / candidate PASS |
| S09 | 1080x1920 | 02910c7d2ff8c6cc44f41d6c28693a6d86c5e31a697c76558262c6369020d144 | 2 | 2 | 2 | base/HC20260810-009-v01-S09-candidate-01-source.png | mechanical PASS / candidate PASS |
| S10 | 1080x1920 | 58315c7deb5b976a3594bcc4864ad7b918bd7f76a756347e6c8b6a8db3490c21 | 1 | 1 | 1 | base/HC20260810-009-v01-S10-candidate-01-source.png | mechanical PASS / candidate PASS |

## Per-shot visual fields

| Shot | Action clarity | Character consistency | Hand/object count | Safe zone | Text/Logo/watermark | Paper/pen/notebook | Medical signal | Phone ratio |
|---|---|---|---|---|---|---|---|---|
| S01 | PASS at 25% contact sheet | PASS at 25% contact sheet | PASS at 25% contact sheet | review copy contained; subject overlap requires final review | no obvious forbidden mark in formal contact sheet | none obvious | none obvious | N/A - no phone |
| S02 | PASS at 25% contact sheet | N/A - deterministic board | N/A - deterministic board | review copy contained | no obvious forbidden mark in formal contact sheet | none obvious | none obvious | N/A - no phone |
| S03 | PASS at 25% contact sheet | PASS at 25% contact sheet | PASS at 25% contact sheet | review copy contained; subject overlap requires final review | no obvious forbidden mark in formal contact sheet | none obvious | none obvious | N/A - no phone |
| S04 | PASS at 25% contact sheet | PASS at 25% contact sheet | PASS at 25% contact sheet | PASS; compact top-right board stays clear of face, hands, monitor and sit-up action | no obvious forbidden mark in formal contact sheet | none obvious | none obvious | N/A - no phone |
| S05 | PASS at 25% contact sheet | PASS at 25% contact sheet | PASS at original-resolution candidate audit; both hands are visible and naturally joined on the lap | review copy contained; subject overlap requires final review | no obvious forbidden mark in formal contact sheet | none obvious | none obvious | N/A - no phone |
| S06 | PASS at 25% contact sheet | PASS at 25% contact sheet | PASS at 25% contact sheet | review copy contained; subject overlap requires final review | no obvious forbidden mark in formal contact sheet | none obvious | none obvious | N/A - no phone |
| S07 | PASS at 25% contact sheet | PASS at 25% contact sheet | PASS at 25% contact sheet | review copy contained; subject overlap requires final review | no obvious forbidden mark in formal contact sheet | none obvious | none obvious | N/A - no phone |
| S08 | PASS at 25% contact sheet | N/A - deterministic board | N/A - deterministic board | review copy contained | no obvious forbidden mark in formal contact sheet | none obvious | none obvious | N/A - no phone |
| S09 | PASS at 25% contact sheet | PASS at 25% contact sheet | PASS at 25% contact sheet | PASS; compact top-left board stays clear of face, hands, monitor and gaze-shift action | no obvious forbidden mark in formal contact sheet | none obvious | none obvious | N/A - no phone |
| S10 | PASS at 25% contact sheet | N/A - deterministic board | N/A - deterministic board | review copy contained | no obvious forbidden mark in formal contact sheet | none obvious | none obvious | N/A - no phone |

## Visual-review record

- The S01-S10 row was inspected in the rebuilt batch formal and storyboard-with-copy contact sheets at 270x480 pixels per cell, exactly 25% of the 1080x1920 source dimensions.
- At that scale, the recurring woman remains consistent in age, face, shoulder-length black hair, beige cardigan, muted-blue top and navy trousers; S02, S08 and S10 remain clearly separated deterministic boards.
- No obvious large text, Logo, watermark, paper/notebook, medical equipment, clinician cue or generated UI was seen in the formal row.
- The deterministic review-copy panels remain inside the canvas. The targeted S04 and S09 panels were rebuilt into empty top corners and no longer cover the subject or action area; other shots retain their existing review status.
- Exact finger anatomy, tiny marks and pixel-level screen geometry cannot be certified from a 25% contact sheet. This report does not relabel that limitation as a full-resolution pass.

## Full-resolution candidate decision audit (2026-08-14)

The approved character reference and all 12 selected/rejected candidate files for S01/S03/S04/S05/S06/S09 were opened individually at original resolution with `view_image`. The following records visible present-day evidence; it does not reconstruct an unknown historical rationale or infer quality from filenames.

| Shot | Why selected | Why the independent candidate is rejected | Result |
|---|---|---|---|
| S01 | Candidate 01 keeps the reference face/hair/clothes in a closer frame; face, both hands, one keyboard and one blank dark monitor remain legible, so “stuck before starting” survives thumbnail scale. | Candidate 02 is a wider view that makes the character, hands and input devices smaller, weakening the single action and safe-area readability. | selected PASS |
| S03 | Candidate 02 looks directly at one solid blank screen with the right hand clearly on the trackpad and sufficient screen space for the later drag animation. | Candidate 01 looks toward the camera and the trackpad finger reads more like pointing than beginning a drag. | selected PASS |
| S04 | Candidate 02 is upright with both hands visibly lowered away from the work surface, making “stop working and sit up” a clean single beat. | Candidate 01 keeps both hands suspended near the desk edge, so it can still read as an unfinished work gesture. | selected PASS |
| S05 | Candidate 02 is the closer three-quarter view, preserves the reference character, directs the gaze to the window and shows both hands naturally joined on the lap. | Candidate 01 is wider; the character and hands are smaller and the hands sit lower in frame, reducing action clarity at thumbnail scale. | selected PASS |
| S06 | Candidate 01 clearly shows the reference-consistent profile and both hands withdrawing above one keyboard. | Candidate 02 uses a rear three-quarter view that makes the hands and withdrawal gesture smaller and less legible. | selected PASS |
| S09 | Candidate 01 shows both hands together at the desk edge after input stops, gaze turning toward the window, with one keyboard and one mouse still visible. | Candidate 02 places the hands lower and partly behind the desk while the monitor occupies more area, weakening the link between stopping input and looking away. | selected PASS |

Across these six decisions, the selected frames preserve the approved character, coherent visible hands/object counts and usable 9:16 action space. No visible text, logo, watermark, paper, pen, notebook, phone UI or medical-device prop was observed in the 12 candidates; phone-ratio review is not applicable because these shots contain no phone. Full Chinese per-shot reasons are stored in the corresponding `decision_record` fields of `03_first_frames/asset-inventory-v01.csv`.

This candidate audit did not edit any image or preview. The targeted S04/S09 preview hashes, board coordinates and safe-zone conclusions below remain the output of the separate preview remediation.

## Targeted review-preview safe-zone remediation (2026-08-14)

- Scope is limited to deterministic review previews S04 and S09. Their formal Grok-input images were not edited.
- S04: top-right board at `(580,96)-(1026,400)`, 304 px high (15.8% of canvas), separated from the face at left and monitor below; the hands and seated-action area remain unobscured.
- S09: top-left board at `(54,96)-(550,420)`, 324 px high (16.9%), separated from the face at right and monitor below; the hands and gaze-shift action remain unobscured.
- Both layouts keep a minimum 5% outer canvas margin, use a clear two-level type hierarchy, and remain legible in the rebuilt 25% review contact sheet.
- The two revised 1080x1920 previews and both 1446x1008 contact sheets were opened with `view_image` after rebuild. No formal-frame SHA-256 changed in this remediation.

## Traceability and gate

- Selected and rejected paths, actual hashes, dimensions and preview hashes are recorded in `03_first_frames/asset-inventory-v01.csv`.
- Historical qualitative selection/rejection reasons were not present in the source artifacts. The new original-resolution audit records current visible selection/rejection evidence without representing it as historical intent.
- Local mechanical gate: PASS.
- Candidate gate: PASS (17 independent bytes; batch minimum 16; local stricter minimum 17; visible selected/rejected rationale closed for S01/S03/S04/S05/S06/S09).
- Contact-sheet visual gate: PASS with the disclosed safe-zone limitation.
- Independent final QA: PENDING.
- This is Task 6 first-frame evidence only; it is not a claim that video production or platform publishing is complete.
