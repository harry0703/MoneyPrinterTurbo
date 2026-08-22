# HC20260810-001 first-frame QA v01

## Closeout status

- Formal inputs: 10/10, S01-S10 continuous, all mechanically verified at 1080x1920 PNG.
- Review previews: 10/10, stored only under storyboard_with_copy/, all mechanically verified at 1080x1920.
- Candidate files: base=10, _rejected=8. Independent-byte counts are recorded per shot in asset-inventory-v01.csv.
- Contact sheets: firstframes-contactsheet-v01.png and storyboard-with-copy-contactsheet-v01.png were rebuilt as deterministic 5x2 sheets and visually inspected.
- Isolation: the formal Grok-input root contains only text-free formal images; Chinese copy remains in the review-preview layer.
- Scope: this closeout records verified filesystem facts and sampled/contact-sheet visual review. It does not invent historical candidate decisions or claim that every candidate was newly inspected.

## Per-shot mechanical record

| Shot | Formal dimensions | Formal SHA-256 | Candidate files | Independent bytes | Selected-source record | Result |
|---|---|---|---:|---:|---|---|
| S01 | 1080x1920 | b3c852ff963fd4abbfb187b6ba1d59fab1de01d83c2101125aac671a0e681394 | 2 | 2 | base/HC20260810-001-v01-S01-candidate-a.png | mechanical PASS |
| S02 | 1080x1920 | 3216d4be1eac7717e2d0eff24b6bc8926027ea58aacb2ec110e58772fe104870 | 2 | 2 | base/HC20260810-001-v01-S02-candidate-b.png | mechanical PASS |
| S03 | 1080x1920 | 0227b931e1253e161a2b4b67f21e34ff8875a4a0a3b58da3c1289be7b89efe58 | 1 | 1 | base/HC20260810-001-v01-S03-candidate-a.png | mechanical PASS |
| S04 | 1080x1920 | 47a195c23d5317a9c78173621fa11f5f7216ba55e4edafc79d199cd1c45c436b | 2 | 2 | base/HC20260810-001-v01-S04-candidate-b.png | mechanical PASS |
| S05 | 1080x1920 | dff77f067c2c0efa0302617c9e39ab3086f96db7819bd1c6327ebbaa7444811d | 2 | 2 | base/HC20260810-001-v01-S05-candidate-a.png | mechanical PASS |
| S06 | 1080x1920 | fe7abb38c27bd634d9df083217496f8093a3fcb79575724365e58ca7aa7e2c8b | 2 | 2 | base/HC20260810-001-v01-S06-candidate-b.png | mechanical PASS |
| S07 | 1080x1920 | c398e1370f6237b6de9104aa0c42377c45e1e4275a4f544d1f1cf3a80cdd3c91 | 2 | 2 | base/HC20260810-001-v01-S07-candidate-b.png | mechanical PASS |
| S08 | 1080x1920 | 082cc1c38ad7f81ebd982c68c9234daa744d35da476fb74ed521d8aeb75f70f1 | 1 | 1 | base/HC20260810-001-v01-S08-candidate-a.png | mechanical PASS |
| S09 | 1080x1920 | b51e031d10ddc622459079fa4df77b52fa9e48a813203a645834a8cd93d420ef | 2 | 2 | base/HC20260810-001-v01-S09-candidate-b.png | mechanical PASS |
| S10 | 1080x1920 | a8f85b8463f4443994e585409aeda160aa3ede74725c0bd643bcc96979f2bae4 | 2 | 2 | base/HC20260810-001-v01-S10-candidate-b.png | mechanical PASS |

## Visual-review record

- Formal and review contact sheets were opened with view_image after the final deterministic rebuild.
- At least S01 and S10 formal frames were independently sampled for this episode; additional risk shots were sampled where the audit found a visible concern.
- No additional one-ticket issue was observed in the sampled formal frames and final contact sheets; this closeout does not claim a fresh individual inspection of every candidate.
- Candidate-quality statements from older QA files are retained only where they already existed; newly created closeout documents do not retrofit unobserved rejection reasons.

## Targeted review-preview safe-zone remediation (2026-08-14)

- Scope is limited to deterministic review previews S04, S05 and S09. Their formal Grok-input images were not edited.
- S04: compact left-top board at `(54,96)-(400,396)`, 300 px high (15.6% of canvas). It remains left of the face/hair and above the hand, spoon, plate and food action area.
- S05: compact left-side board at `(54,520)-(390,820)`, 300 px high (15.6%). It occupies background/window space and does not cover the face, hands, feet or walking-action path.
- S09: compact left-side board at `(54,560)-(410,860)`, 300 px high (15.6%). It remains clear of the face, hand, key/tray action and walking feet.
- Every board keeps at least the 5% horizontal/vertical canvas margin where it approaches an outer edge; all copy remains legible in the rebuilt 25% contact sheet.
- The three revised 1080x1920 previews and both 1446x1008 contact sheets were opened with `view_image` after rebuild. No formal-frame SHA-256 changed in this remediation.

## Gate

**DOCUMENTATION COMPLETE WITH DISCLOSED RISKS.** This is a first-frame documentation/preview closeout only. It is not Task 8 factual approval, final QA authorization, Grok-video completion, or platform release approval.
