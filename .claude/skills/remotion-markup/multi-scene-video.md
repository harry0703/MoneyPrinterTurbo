# Multi-scene videos

Put successive scenes in a named `Track`. Make each scene with
`Interactive.create({layout: 'absolute-fill'})` and register it as a connected
composition. Write each instance separately with inline timing and props.

```tsx title="MyVideo.tsx"
import {Track, useVideoConfig} from 'remotion';
import {OpeningScene} from './OpeningScene';
import {FeatureScene} from './FeatureScene';

export const MyVideo = () => {
  const {fps} = useVideoConfig();

  return (
    <Track name="Scenes">
      <OpeningScene name="Opening" durationInFrames={3 * fps} />
      <FeatureScene name="Feature" from={3 * fps} durationInFrames={4 * fps} />
    </Track>
  );
};
```

Follow the complete Track + connected compositions example
for scene definitions and `Root.tsx`. Register `OpeningScene`, `FeatureScene`,
and `MyVideo` using those same exported component references, with representative
inline defaults. At 30 fps, this parent lasts 210 frames.

When adding overlapping transitions, use
[`TransitionSeries`](transitions.md) instead of `Track`. Keep each scene as the
only child of its `TransitionSeries.Sequence`, and subtract transition overlaps
from the parent duration.
