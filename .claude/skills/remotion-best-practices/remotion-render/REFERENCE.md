---
name: remotion-render
description: Export a Remotion video
version: 4.0.536
---

## General rendering strategy

Render a video using:

```
npx remotion render
```

Full list of options: https://www.remotion.dev/docs/cli/render.md

Render a still using:

```
npx remotion still
```

Full list of options: https://www.remotion.dev/docs/cli/still.md

To render several frames as images in one call, use `render --frames`:

```
npx remotion render [composition-id] out/frames --frames=0,30,90 --image-format=png
```

See https://www.remotion.dev/docs/cli/render.md#--frames for more options.

## Transparent videos

See [Transparent videos](./transparent-videos.md) for rendering out a video with transparency.
