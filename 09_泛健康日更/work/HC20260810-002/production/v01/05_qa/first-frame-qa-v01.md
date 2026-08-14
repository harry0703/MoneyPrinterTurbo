# HC20260810-002 first-frame QA v01

## Closeout status

- Formal inputs: 10/10, S01-S10 continuous, all mechanically verified at 1080x1920 PNG.
- Review previews: 10/10, stored only under storyboard_with_copy/, all mechanically verified at 1080x1920.
- Candidate files: selected raster sources in base=10, editable SVG sources=1, rejected candidate evidence=11, archived superseded formals=2. Revised-shot candidate counts and paths are recorded in asset-inventory-v01.csv.
- Contact sheets: firstframes-contactsheet-v01.png and storyboard-with-copy-contactsheet-v01.png were rebuilt as deterministic 5x2 sheets and visually inspected.
- Isolation: the formal Grok-input root contains only text-free formal images; Chinese copy remains in the review-preview layer.
- Scope: this closeout records verified filesystem facts and sampled/contact-sheet visual review. It does not invent historical candidate decisions or claim that every candidate was newly inspected.

## Per-shot mechanical record

| Shot | Formal dimensions | Formal SHA-256 | Candidate files | Independent bytes | Selected-source record | Result |
|---|---|---|---:|---:|---|---|
| S01 | 1080x1920 | c849d17c006db022a3b15a89897af3e5a301e54b21d30ce3d9e461b63d4b1c6e | 4 | 4 | base/HC20260810-002-v01-S01-candidate-c-v02-selected-source.png | visual + mechanical PASS |
| S02 | 1080x1920 | e6059ff3ef10e7cd9c0e7c062ef7ed792f7575c37552ab42ea0013863b9e8dd4 | 1 | 1 | base/HC20260810-002-v01-S02-candidate-a.png | mechanical PASS |
| S03 | 1080x1920 | 333ddb73f1db1e5874491469ea43911994fe92919c83e69a33440eab7f44d4b5 | 2 | 2 | base/HC20260810-002-v01-S03-candidate-b.png | mechanical PASS |
| S04 | 1080x1920 | 262f918aa070df29b4ace913fb544b26baa7ce389d03dac8b18ee1055e082e5f | 3 | 3 | base/HC20260810-002-v01-S04-candidate-a.png | mechanical PASS |
| S05 | 1080x1920 | 5b0959d59261470776f1fc05c7a232627f380d946e6e17bdce95c442568136f7 | 2 | 2 | base/HC20260810-002-v01-S05-candidate-a.png | mechanical PASS |
| S06 | 1080x1920 | f21bf18c41201bcaf38a2e54fcf2fe397aa8b5a4f3e983fb6d4ca1d190a26464 | 2 | 2 | base/HC20260810-002-v01-S06-candidate-b.png | mechanical PASS |
| S07 | 1080x1920 | aa06cd2a24c4e2c580eb1c1e4c9808b5bf68a8f2bcf057148e959dd4db1fe8ff | 2 | 2 | base/HC20260810-002-v01-S07-candidate-a.png | mechanical PASS |
| S08 | 1080x1920 | 5458290eec7c0119317a116aba0ca67554220a8846ae6bbe2c3fee45d804af37 | 1 | 1 | base/HC20260810-002-v01-S08-candidate-a.png | mechanical PASS |
| S09 | 1080x1920 | a38c6d60bc0257428feb14fff2addc0943f59f04042c8dcde74370e682814023 | 2 | 2 | base/HC20260810-002-v01-S09-candidate-b.png | mechanical PASS |
| S10 | 1080x1920 | c5e69bf794b63cd36ac941c0d08f35871ce9e8135e0b6540a7b44d4da7f28d23 | 2 | 2 | base/HC20260810-002-v01-S10-candidate-b-v02.png | visual + mechanical PASS |

## Visual-review record

- Formal and review contact sheets were opened with view_image after the final deterministic rebuild.
- At least S01 and S10 formal frames were independently sampled for this episode; additional risk shots were sampled where the audit found a visible concern.
- S01 remediation was opened at original resolution: both panels now use the same woman, same beige lunch box, the same carrot/broccoli/rice positions and quantities, and the same type of chopsticks; only brisk versus calm action changes. No text, logo, paper, notebook or medical UI is present in the formal.
- S10 remediation was opened at original resolution: the editable-SVG render is a warm-cream board with a centered deep-teal double vertical pause symbol and no formal-layer text. It is deterministic and does not require Grok.
- The rebuilt formal and storyboard-with-copy 5x2 sheets were opened after replacement. Existing Chinese review copy remains “同份午餐 / 两种速度” and “中途停顿 / 下顿再试”; formal files remain text-free.
- Candidate-quality statements from older QA files are retained only where they already existed; newly created closeout documents do not retrofit unobserved rejection reasons.

## Remediation archive record

- S01 superseded formal: `_rejected/HC20260810-002-v01-S01-old-formal-object-drift.png`, SHA-256 `00d10801894a3bb40d4acc714d667e872d376e8400fd7c67e944a858b1de51bc`; retired source: `_rejected/HC20260810-002-v01-S01-candidate-a-retired-object-drift.png`.
- S10 superseded formal: `_rejected/HC20260810-002-v01-S10-old-formal-missing-pause.png`, SHA-256 `b244c1b193458713e48601dce1c0df5dfb8f2ace8a4050749aad5d197a2f8e5e`; retired source: `_rejected/HC20260810-002-v01-S10-candidate-a-retired-missing-pause.png`.

## Gate

**FIRST-FRAME REMEDIATION DOCUMENTED AND VERIFIED.** This is a first-frame documentation/preview closeout only. It is not Task 8 factual approval, final QA authorization, Grok-video completion, or platform release approval.
