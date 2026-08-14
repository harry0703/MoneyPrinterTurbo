# HC20260810-010 first-frame QA v01

## Closeout status

- Formal inputs: 10/10, S01-S10 continuous, all mechanically verified at 1080x1920 PNG.
- Review previews: 10/10, stored only under storyboard_with_copy/, all mechanically verified at 1080x1920.
- Candidate files: base=10, _rejected=5. Independent-byte counts are recorded per shot in asset-inventory-v01.csv.
- Contact sheets: firstframes-contactsheet-v01.png and storyboard-with-copy-contactsheet-v01.png were rebuilt as deterministic 5x2 sheets and visually inspected.
- Isolation: the formal Grok-input root contains only text-free formal images; Chinese copy remains in the review-preview layer.
- Scope: this closeout records verified filesystem facts and sampled/contact-sheet visual review. The 2026-08-14 candidate audit below is a fresh original-resolution inspection of only S01/S02/S04 selected and independently rejected candidates; no fresh inspection is claimed for other shots.

## Per-shot mechanical record

| Shot | Formal dimensions | Formal SHA-256 | Candidate files | Independent bytes | Selected-source record | Result |
|---|---|---|---:|---:|---|---|
| S01 | 1080x1920 | fa3fc013426f3ca11f9fde3b943d91655d00a4fb4820dc329274f1b142424a7e | 2 | 2 | base/S01-candidate-B.png | mechanical PASS |
| S02 | 1080x1920 | 594b0065fbbbbc7869e7aa31f758b04b83177a60323d1fca75b9a7a5c5cad0c1 | 2 | 2 | base/S02-candidate-B.png | mechanical PASS |
| S03 | 1080x1920 | 5ec322b7b2feb1cec215a656a5acd514c10b1a2db569273f87971fc4d74464c0 | 1 | 1 | base/S03-candidate-A.png | mechanical PASS |
| S04 | 1080x1920 | 8eec1b6dbbaa62c6f3d9109028124f9a93fbcd4d07ace5391b900ad9cb15ff78 | 2 | 2 | base/S04-candidate-A.png | mechanical PASS |
| S05 | 1080x1920 | 9d966931dde8e51774459f557e79c402888f9959826b4bc149bbd47ca1553d44 | 2 | 2 | base/S05-candidate-B.png | mechanical PASS |
| S06 | 1080x1920 | 6132c3cf3daeb2404c80e5054de3efed11d42a840d5c5d10971923bd67e713ef | 1 | 1 | base/S06-candidate-A.png | mechanical PASS |
| S07 | 1080x1920 | 63898baefb20187b17e2a7c51e04f9673d689355ea521dc0d98b27495fec4fc2 | 1 | 1 | base/S07-candidate-A.png | mechanical PASS |
| S08 | 1080x1920 | 8fa77c5df83c0d313e3a49bc9bfc634753a9fe6dc0bab6b68294ac53579c8d6e | 2 | 2 | base/S08-candidate-A.png | mechanical PASS |
| S09 | 1080x1920 | 806b7b7abb78a053c2c3543c1e66a8475d7d81abacad7b05ff7ee436c76e031e | 1 | 1 | base/S09-candidate-A.png | mechanical PASS |
| S10 | 1080x1920 | e77ea8650f7b03ed5dbf3b924fa356f9b056b6aaca65894f60c177d3b8ec13b1 | 1 | 1 | base/S10-candidate-A.png | mechanical PASS |

## Visual-review record

- Formal and review contact sheets were opened with view_image after the final deterministic rebuild.
- At least S01 and S10 formal frames were independently sampled for this episode; additional risk shots were sampled where the audit found a visible concern.
- No additional one-ticket issue was observed in the sampled formal frames and final contact sheets; this closeout does not claim a fresh individual inspection of every candidate.
- Candidate-quality statements from older QA files are retained only where they already existed; newly created closeout documents do not retrofit unobserved rejection reasons.

## Candidate visual decision audit (2026-08-14)

Character reference was reopened at original resolution before this audit. Every selected source and every independent rejected source named below was reopened individually with `view_image`; conclusions are based on visible content rather than filenames or presumed historical intent.

| Shot | Why selected | Why rejected | Candidate result |
|---|---|---|---|
| S01 | B has six identical teal blocks inside the ring plus one salmon block outside, so repetition and one exception are immediately separable; all seven objects fit the safe area. | A keeps seven mixed-color blocks inside one ring, implying several categories without an isolated exception. | selected PASS |
| S02 | B matches the reference character, keeps both feet grounded and both complete hands naturally on a single phone; the phone is the only active prop. | A crosses the legs, adds a mug and makes the phone smaller, diluting the single relaxed-phone action. | selected PASS for pose/composition only; both images show only the phone back, so neither is evidence of screen/UI or outer-ratio compliance |
| S04 | A shows the reference character mid-step with two complete hands holding one front-readable plate and both feet visible. | B is a more lateral walk with the plate nearly edge-on and smaller, weakening object/action clarity at thumbnail scale. | selected PASS |

Across these 3 shots, visible hands/object counts and 9:16 safety are coherent, and no text, logo, watermark, paper, pen, notebook or medical-device prop was observed. The S02 phone-back limitation is explicitly retained. Full Chinese reasons are recorded in `asset-inventory-v01.csv`; no image was changed by this audit.

## Gate

**DOCUMENTATION COMPLETE WITH DISCLOSED RISKS.** This is a first-frame documentation/preview closeout only. It is not Task 8 factual approval, final QA authorization, Grok-video completion, or platform release approval.
