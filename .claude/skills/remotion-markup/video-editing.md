# Editable video timelines

The Studio edits the JSX source node that created a timeline item. Every clip
that should be trimmed, moved, renamed, reordered, duplicated or deleted on its
own therefore needs its own authored JSX node, with its editable timing props
written directly on that node.

This source structure is intentional repetition: It gives every runtime clip a
separate source-editing target. A `.map()` or another programmatic loop instead
creates multiple runtime clips from one JSX node. Use that only when the
instances are intentionally controlled as one template and do not need
independent editing.

Choose the timeline structure based on the editing behavior:

- Use independently positioned clips when moving or resizing one clip should
  not affect any other clip.
- Use `<TransitionSeries>` for consecutive clips when changing one clip's
  duration should reposition every later clip. It also supports transitions
  and overlays.

Use `const {fps} = useVideoConfig()` in the enclosing composition.
For trims and other timing props expressed in seconds, use that `fps`
directly in each clip's JSX, for example `trimBefore={4 * fps}`. Do not use a
separate fixed `FPS` constant: Studio must be able to update each clip's source
expression when the user trims or splits it.

## Clips with synchronized captions or overlays

For a clip with synchronized captions or overlays, make a shared timing group
the editable timeline item. Keep the video and its synchronized layers inside
one `<Sequence>` for independently positioned clips, or inside the same
`<TransitionSeries.Sequence>` for consecutive clips.

Put the clip's `trimBefore`, `durationInFrames`, and `playbackRate` on that
shared parent, plus `from` when using an independently positioned `<Sequence>`.
Apply the shared timing once, rather than repeating it on the children.
Moving, trimming, changing the speed, reordering, or deleting the group then
affects all its layers together. A shared wrapper has a purpose here even
though the children accept timing props themselves.

Keep each clip's captions in an inline array on its own `<BasicCaptions>` node,
with timestamps relative to the original media file. Do not put a combined
caption overlay outside the clip groups. See
Displaying captions alongside video content
for the complete example.

## Independently positioned clips

For clips without synchronized captions or overlays, place each `<Video>`
directly in the composition and write its timing props on the JSX node.
Use literal frame counts when they are already known;
`from={0}` may be omitted:

```tsx
<Video
  name="Opening"
  src="https://remotion.media/video.mp4"
  trimBefore={0}
  durationInFrames={78}
/>
<Video
  name="Interview"
  src="https://remotion.media/video.webm"
  trimBefore={12}
  from={78}
  durationInFrames={66}
/>
<Video
  name="Closing"
  src="https://remotion.media/video.mp4"
  trimBefore={72}
  from={144}
  durationInFrames={90}
/>
```

- `from` is the clip's absolute start frame in its parent timeline.
- `durationInFrames` is how many source frames are shown, starting at `trimBefore`. At the default `playbackRate`, this is how long the clip remains visible.
- `trimBefore` is how many source frames are skipped before playback begins.
- Keep `name`, `from`, `durationInFrames` and `trimBefore` inline on each clip.
- Import `<Video>` from `@remotion/media`.

Moving or resizing one of these clips does not reposition later clips. Gaps and
overlaps are therefore allowed.

## Consecutive clips with `TransitionSeries`

Use `<TransitionSeries>` when the clips should remain adjacent. No transition
components are needed for consecutive playback. The example below has no
synchronized captions; for captioned clips, put the captions inside each
sequence and move the video's trim to that shared sequence as described above:

```tsx
import { TransitionSeries } from "@remotion/transitions";

<TransitionSeries>
  <TransitionSeries.Sequence name="Opening" durationInFrames={78}>
    <Video
      src="https://remotion.media/video.mp4"
      trimBefore={0}
    />
  </TransitionSeries.Sequence>
  <TransitionSeries.Sequence name="Interview" durationInFrames={66}>
    <Video
      src="https://remotion.media/video.webm"
      trimBefore={12}
    />
  </TransitionSeries.Sequence>
  <TransitionSeries.Sequence name="Closing" durationInFrames={90}>
    <Video
      src="https://remotion.media/video.mp4"
      trimBefore={72}
    />
  </TransitionSeries.Sequence>
</TransitionSeries>
```

The `<TransitionSeries.Sequence>` is the editable clip row. Changing its
`durationInFrames` repositions every later sequence. Do not set `from` on a
`<TransitionSeries.Sequence>`; the series calculates each start frame.

Keep every sequence as a separate JSX node with a hardcoded `name` and
`durationInFrames`. The child may also be a custom clip or scene component:

```tsx
<TransitionSeries.Sequence name="Product demo" durationInFrames={150}>
  <ProductDemo />
</TransitionSeries.Sequence>
```

## Consecutive clips with transitions

Use `<TransitionSeries>` when the timeline needs transitions or overlays.
Preserve the same one-source-node-per-clip structure. Put a clip's synchronized
captions inside its sequence and apply shared timing to that parent:

```tsx
<TransitionSeries name="Video timeline">
  <TransitionSeries.Sequence name="Opening" durationInFrames={78}>
    <Video
      src="https://remotion.media/video.mp4"
      trimBefore={0}
    />
  </TransitionSeries.Sequence>
  <TransitionSeries.Transition
    presentation={fade()}
    timing={linearTiming({durationInFrames: 12})}
  />
  <TransitionSeries.Sequence name="Interview" durationInFrames={66}>
    <Video
      src="https://remotion.media/video.webm"
      trimBefore={12}
    />
  </TransitionSeries.Sequence>
</TransitionSeries>
```

The `<TransitionSeries.Sequence>` is the editable clip row. Do not set `from`
on it; the series calculates the start frame and accounts for transition
overlaps.

Read [transitions.md](transitions.md) for transition types, imports,
installation instructions and composition-duration calculation. Import
`<Video>` from `@remotion/media`, and keep the parent composition's
`durationInFrames` as an inline literal after accounting for all clip durations
and transition overlaps.
