# AI Video Autopilot: baseline evaluation

Use this worksheet before enabling scene-directed rendering. Existing outputs are preferred so baseline collection does not spend new provider credits. No scores are recorded yet because this checkout contains no completed task videos.

## Sample set

Collect 10–20 outputs from the current pipeline. Include at least one output for each condition below; the same video may cover more than one condition.

| Condition | What to inspect |
| --- | --- |
| Technology topic with abundant stock | Footage matches each spoken concept |
| Technical topic with scarce stock | Generic footage does not pretend to explain a specific mechanism |
| Multi-step explanation | Shot order follows the narration |
| Several similar search terms | Repeated subject and repeated source clip |
| Fast hook | First scene duration and timing |
| Slow technical sentence | Enough reading/viewing time |
| Portrait crop of landscape footage | Subject remains visible |
| Generated image or video | Style consistency and factual labels |
| Custom narration audio | Subtitle and shot alignment |
| Missing or imperfect subtitles | Legibility and safe area |
| Music enabled | Narration intelligibility |
| Provider failure or fallback | Visible failure and final output state |

## Record for each video

Record the task ID, script, final MP4 path, creation date, duration, provider choices, and whether the output was already published. Keep the video and source metadata private if license or account terms require it. For each scene, record narration span, start/end time, source asset, and these ratings:

- **Visual relevance (0–4):** 0 unrelated; 1 merely topical; 2 plausible but generic; 3 matches the spoken subject; 4 illustrates the specific claim or action.
- **Visual continuity (0–4):** 0 jarring change in style; 4 coherent sequence.
- **Subtitle legibility (0–4):** 0 unreadable/hidden; 4 readable on a phone inside the safe area.
- **Timing (0–4):** 0 speech/visual conflict; 4 sufficient duration with natural cuts.
- **Factual risk:** list the spoken claim and reason for concern; leave blank if none identified. A reviewer should not infer truth from a visual score.
- **Render defects:** count black frames, clipping, silence, audio imbalance, and visible glitches.

At video level, record distinct source clips, clip reuse count, generation time, and actual provider charges if available. Mark unavailable cost as `unknown`, not `$0`.

## Comparison protocol

Run the same scripts through the first scene-directed MVP with the same aspect ratio, voice, provider availability, and output settings. Two reviewers score baseline and new renders without seeing which mode made each video. Compare median scene relevance, proportion of scenes rated at least 3, repeated-source rate, timing, subtitle legibility, render defects, runtime, and known cost. Keep both the raw scores and disagreements; do not claim improvement from a model's self-score alone.

## Exit gate

Phase 0 evaluation is complete when 10–20 real baseline videos and their scoring sheets are saved in a location the team can access. The contract and tests can be completed separately; this document is a rubric, not fabricated baseline evidence.
