---
name: remotion-markup
description: Content, animation and effects best practices
version: 4.0.536
---

This is guidance for writing Remotion React Markup.
If this is not relevant, load [Remotion Best Practices](../SKILL.md) instead.

## Preserve user changes

Users may make edits in the code outside of the conversation.

If you detect a surprising change made in the meanwhile, don't overwrite it, assume it was intentional or ask for confirmation.

## General rules

Inside a composition or scene component, get `fps` from `useVideoConfig()` for
all seconds-to-frames calculations, including timing props such as `from`,
`trimBefore` and `durationInFrames`. Keeping the expression on
the JSX node, such as `trimBefore={4 * fps}`, lets Studio edit the timing and
keeps it correct if the composition frame rate changes.

Drive animations using `useCurrentFrame()` and `interpolate()`.  
CSS `transition` or `animation` will not render correctly, they need to refactored.  
Tailwind animation class will not render correctly, they need to be refactored.

Use `Easing.bezier()` and `Easing.spring()` to customize timing.

Use `Track` for successive scenes. Make scenes and reusable elements with
`Interactive.create()`, setting `layout` explicitly to `'absolute-fill'` or
`'none'`, and register them as connected compositions. Put timing directly on
each instance. Follow the complete
[Track + connected compositions example](../remotion-interactivity/timeline-structure.md).
See [Remotion Interactivity](../remotion-interactivity/REFERENCE.md) for editable props
and keyframes.

The Studio edits the JSX source node that created an item. Author every composition registration, clip, scene, layer and sequence that should be editable independently as its own JSX node, with its editable props inline.
Programmatic loops are suitable when the generated instances are intentionally controlled as one source template, not when users need to edit the instances
separately.

```tsx
import { useCurrentFrame, useVideoConfig, Easing, interpolate, Interactive } from "remotion";

export const FadeIn = () => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();

  return (
    <Interactive.Div
      name="Title"
      style={{
        opacity: interpolate(frame, [0, 2 * fps], [0, 1], {
          extrapolateRight: "clamp",
          extrapolateLeft: "clamp",
          easing: Easing.bezier(0.16, 1, 0.3, 1),
        }),
      }}
    >
      Hello World!
    </Interactive.Div>
  );
};
```

Keep the `interpolate()` call inline in the `style` prop.
Use `scale`, `translate`, `rotate` CSS properties over `transform`.

```tsx
// 👍 Inline editable keyframes and transform shorthands
style={{
  scale: interpolate(frame, [0, 100], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.spring({damping: 200}),
    output: 'perceptual-scale' // For `scale` animations, use "output: 'perceptual-scale'"
  }),
  translate: interpolate(frame, [0, 100], ["0px 0px", "100px 100px"], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.spring({damping: 200}),
  }),
  rotate: interpolate(frame, [0, 100], ["20deg", "90deg"], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.spring({damping: 200}),
  }),
}}

// 👎 Non-inline values and transform strings become harder to edit in Studio
const scale = interpolate(frame, [0, 100], [0, 1]);

style={{
  transform: `scale(${scale})`,
}}
```

## Assets

Place assets in the `public/` folder at your project root.
Use `staticFile()` to reference files from the `public/` folder.

## Media components

Add video and audio using `<Video>` and `<Audio>` from `@remotion/media`.  
Add images using the `<CanvasImage>` component.
Add animated GIFs, APNG, WebP or AVIF images using `<AnimatedImage>`, use `@remotion/gif` if not using Chrome.
Use `staticFile()` for files in `public/` or pass a remote URL directly:

```tsx
import { Audio, Video } from "@remotion/media";
import { staticFile, CanvasImage, AnimatedImage } from "remotion";

export const MyComposition = () => {
  return (
    <>
      <Video src={staticFile("video.mp4")} style={{ opacity: 0.5 }} />
      <Audio src={staticFile("audio.mp3")} />
      <CanvasImage
        src={staticFile("logo.png")}
        style={{ width: 100, height: 100 }}
      />
      <Video src="https://remotion.media/video.mp4" />
      <AnimatedImage src={staticFile('nyancat.gif')} />
    </>
  );
};
```

If the composition is primarily a timeline of video or audio clips, read
[video-editing.md](video-editing.md) before choosing its source structure.

## Example scene

A background video with a lower third.
The lower third is an interactive component with its own timeline, registered as a [connected composition](connected-compositions.md).
Its text is passed as `children` and `accentColor` is an editable prop.
The fade-in is keyframed inline at the call site.

```tsx
// MyScene.tsx
import { Video } from "@remotion/media";
import { Easing, Interactive, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { LowerThird } from "./LowerThird";

const MySceneInner = () => {
  const { fps } = useVideoConfig();
  const frame = useCurrentFrame();

  return (
    <>
      <Video
        name="Background"
        src="https://remotion.media/video.mp4"
        objectFit="cover"
        style={{
          position: "absolute",
          width: "100%",
          height: "100%",
        }}
      />
      <LowerThird
        name="Lower third"
        from={1 * fps}
        accentColor="#0b84f3"
        style={{
          opacity: interpolate(frame, [1 * fps, 2 * fps], [0, 1], {
            extrapolateRight: "clamp",
            extrapolateLeft: "clamp",
            easing: Easing.bezier(0.16, 1, 0.3, 1),
          }),
        }}
      >
        Jane Doe, Product Designer
      </LowerThird>
    </>
  );
};

export const MyScene = Interactive.create({
  Component: MySceneInner,
  layout: "absolute-fill",
});
```

```tsx
// LowerThird.tsx
import type React from "react";
import { Interactive, type InteractivitySchema } from "remotion";

type LowerThirdProps = {
  readonly children: React.ReactNode;
  readonly accentColor: string;
  readonly style?: React.CSSProperties;
};

const LowerThirdInner: React.FC<LowerThirdProps> = ({
  children,
  accentColor,
  style,
}) => {
  return (
    <div
      style={{
        position: "absolute",
        left: 80,
        bottom: 80,
        display: "flex",
        alignItems: "center",
        gap: 20,
        backgroundColor: "white",
        borderRadius: 16,
        padding: "20px 32px",
        color: "black",
        fontFamily: "Helvetica, Arial, sans-serif",
        fontSize: 48,
        fontWeight: 600,
        ...style,
      }}
    >
      <div
        style={{
          width: 8,
          alignSelf: "stretch",
          borderRadius: 4,
          backgroundColor: accentColor,
        }}
      />
      {children}
    </div>
  );
};

const lowerThirdSchema = {
  ...Interactive.childrenSchema,
  ...Interactive.textSchema,
  accentColor: {
    type: "color",
    default: "#0b84f3",
    description: "Accent color",
  },
} as const satisfies InteractivitySchema;

export const LowerThird = Interactive.create({
  Component: LowerThirdInner,
  layout: "none",
  schema: lowerThirdSchema,
});
```

```tsx title="src/Root.tsx"
import { Composition } from "remotion";
import { LowerThird } from "./LowerThird";
import { MyScene } from "./MyScene";

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="MyScene"
        component={MyScene}
        durationInFrames={60}
        fps={30}
        width={1280}
        height={720}
      />
      <Composition
        id="LowerThird"
        component={LowerThird}
        durationInFrames={30}
        fps={30}
        width={1280}
        height={720}
        defaultProps={{
          children: "Jane Doe, Product Designer",
          accentColor: "#0b84f3",
        }}
      />
    </>
  );
};
```

## Delaying, trimming

Put timing directly on components that support it. See [Timing props](./timing-props.md) for the supported props, examples, and order of operations.

## Maps

See [Remotion Maps](./remotion-maps/REFERENCE.md) if wanting to include maps in the video.

## Text highlights and annotations

See [text-highlights.md](text-highlights.md) for text highlights (highlight markers), circles, underlines, strike-throughs, crossed-off text, boxes.

## Multi-scene videos

See [multi-scene-video.md](multi-scene-video.md) if planning to make a video with multiple subsequent scenes.

## Connected compositions

When a scene or group of layers deserves its own editable timeline, follow [connected-compositions.md](connected-compositions.md). Prefer this structure for substantial scenes in a multi-scene video.

### Pre-compose action

For a Studio request such as `Pre-compose Ambient glow (src/BarChart.tsx:134)`, find the selected sequence markup at the given location. Make a connected composition, following [connected-compositions.md](connected-compositions.md): extract the markup into a named component, preferably make it interactive with `Interactive.create()`, and register the same exported component reference with a unique `<Composition>` in the root. Render the interactive component directly with its timing props, or as the only child of a sequence when that wrapper has a purpose. If the selected node is already a sequence, keep its props and extract its children. The registration needs dimensions, fps, duration, and `defaultProps` equivalent to its parent use. A component extraction without a registered composition does not complete a pre-compose request.

Carry inherited styles such as `fontFamily` and font loading into the extracted
component; see [parent independence](connected-compositions.md#make-the-component-independent-of-its-parent).

## Voiceover

See [voiceover.md](voiceover.md) for adding an AI-generated voiceover to Remotion compositions using ElevenLabs TTS.

## Embedding Videos

See [embedding-videos.md](embedding-videos.md) for advanced knowledge about embedding videos - trimming, volume, speed, looping, pitch.

## Embedding Audio

See [audio.md](audio.md) for advanced audio features like trimming, volume, speed, pitch.

## Cropping

See [cropping.md](cropping.md) if needing to crop the visible rectangle of a component.

## Transitions

See [transitions.md](transitions.md) for scene transition patterns.

## Motion blur

When adding motion blur or a movement trail, read [motion-blur.md](motion-blur.md) for the preferred HTML-in-canvas approach, preview requirements, and alternatives.

## Visual and pixel effects

When adding a visual effect, first identify the element or group it should affect.
If the target component supports `effects` and a built-in effect below matches the
request, prefer that effect over a CSS approximation. For example, apply
`vignette()` directly to a `<Video>`'s `effects` prop when the vignette should
affect that video.

These components accept `effects` directly:

| Import from        | Components                                                                                                                    |
| ------------------ | ----------------------------------------------------------------------------------------------------------------------------- |
| `remotion`         | `<Img>`, `<CanvasImage>`, `<AnimatedImage>`, `<Solid>`, `<HtmlInCanvas>`                                                      |
| `@remotion/media`  | `<Video>`                                                                                                                     |
| `@remotion/gif`    | `<Gif>`                                                                                                                       |
| `@remotion/rive`   | `<RemotionRiveCanvas>`                                                                                                        |
| `@remotion/shapes` | `<Arrow>`, `<Callout>`, `<Circle>`, `<Ellipse>`, `<Heart>`, `<Pie>`, `<Polygon>`, `<Rect>`, `<Spark>`, `<Star>`, `<Triangle>` |

Ordinary HTML elements, `<Interactive.*>` DOM wrappers, `<AbsoluteFill>`, and
`<Sequence>` do not accept `effects` directly. To apply effects to their content,
wrap them in `<HtmlInCanvas>` and put the `effects` prop on the wrapper.

For other elements, prefer regular HTML and CSS where suitable. Consider wrapping
a group in [`<HtmlInCanvas>`](html-in-canvas.md) when post-processing the whole
group is appropriate and the environment supports it.

Read [effects.md](effects.md) before applying an effect for imports, parameters,
and setup. It also covers reusable custom effects with `createEffect()` when no
built-in effect matches.

### Available effects

Built-in effects from `@remotion/effects`:

- Color and tone: `brightness()`, `colorCorrection()`, `colorKey()`, `contrast()`, `duotone()`, `exposure()`, `grayscale()`, `hue()`, `invert()`, `levels()`, `linearGradient()`, `linearGradientTint()`, `lut()`, `saturation()`, `shadowsHighlights()`, `thermalVision()`, `tint()`, `vibrance()`, `whiteBalance()`.
- Blur and trails: `blur()`, `lightTrail()`, `linearProgressiveBlur()`, `radialProgressiveBlur()`, `regionBlur()`, `zoomBlur()`.
- Lighting: `dropShadow()`, `glow()`, `lightLeak()`, `shine()`, `starburst()`, `vignette()`.
- Distortion and transforms: `barrelDistortion()`, `chromaticAberration()`, `cornerPin()`, `fisheye()`, `mirror()`, `noiseDisplacement()`, `scale()`, `skew()`, `tile()`, `uvTranslate()`, `wave()`, `xyTranslate()`.
- Textures and patterns: `burlap()`, `checkerboard()`, `contourLines()`, `dotGrid()`, `emboss()`, `flannel()`, `gridlines()`, `halftone()`, `halftoneLinearGradient()`, `lines()`, `liquidContours()`, `noise()`, `paper()`, `pattern()`, `rings()`, `scanlines()`, `speckle()`, `tvSignalOff()`, `waves()`, `whiteNoise()`, `zigzag()`.
- Edges: `outline()`, `roughenEdges()`, `shrinkwrap()`, `tear()`.
- Pixelation and transitions: `evolve()`, `linearProgressivePixelate()`, `pixelate()`, `pixelDissolve()`, `radialProgressivePixelate()`, `venetianBlinds()`.

## Color correction

Read [color-correction.md](color-correction.md) for how to apply color correction, either using the `colorCorrection()` effect or `lut()` to apply a 3D `.cube` color grade.

## 3D content

See [./3d.md](./3d.md) for 3D content in Remotion using Three.js and React Three Fiber.

## Sound effects

When needing to use sound effects, load the [./sfx.md](./sfx.md) file for more information.

## Audio visualization

When needing to visualize audio (spectrum bars, waveforms, bass-reactive effects), load the [./audio-visualization.md](./audio-visualization.md) file for more information.

## Maps

For static maps, animated routes and markers, geographic explainers, Mapbox, MapLibre, MapTiler, GeoJSON, or 3D geographic flyovers, load [Remotion Maps](./remotion-maps/REFERENCE.md).

## Captions

When dealing with captions or subtitles, load the [Remotion Captions](../remotion-captions/REFERENCE.md) skill for more information.

## Google Fonts

Is the recommended way to load fonts in Remotion. See [google-fonts.md](google-fonts.md) for how to load Google Fonts.

## Local fonts

See [local-fonts.md](local-fonts.md) for how to load local fonts.

## GIFs

See [gifs.md](gifs.md) for how to display GIFs synchronized with Remotion's timeline.

## Advanced Images

See [images.md](images.md) for sizing and positioning images, dynamic image paths, and getting image dimensions.

## Lottie animations

See [lottie.md](lottie.md) for embedding Lottie animations in Remotion.

## Timing

See [timing.md](timing.md) for more timing techniques for `interpolate()`.

## Parameterized videos

See [parameters.md](parameters.md) for making a composition parametrizable by adding a Zod schema.

## Measuring DOM nodes

See [measuring-dom-nodes.md](measuring-dom-nodes.md) for measuring DOM element dimensions in Remotion.

## Measuring text

See [measuring-text.md](measuring-text.md) for measuring text dimensions, fitting text to containers, and checking overflow.

## Using FFmpeg

For some video operations, such as trimming videos or detecting silence, FFmpeg should be used. Load the [./ffmpeg.md](./ffmpeg.md) file for more information.

## Silence detection

When needing to detect and trim silent segments from video or audio files, load the [./silence-detection.md](./silence-detection.md) file.

## Dynamic duration, dimensions and data

See [calculate-metadata.md](calculate-metadata.md) for dynamically set composition duration, dimensions, and props.

## Compositions and stills

Before registering `<Composition>` or `<Still>` elements, read [compositions.md](compositions.md) for source-editable registrations, folders, default props and nesting. For Studio navigation into a scene's own timeline, use [connected compositions](connected-compositions.md).

## Advanced sequencing

See [sequencing.md](sequencing.md) for more sequencing patterns - delay, trim, limit duration of items.

## Install modules

Use `npx remotion add` to add new packages with the right version:

```
npx remotion add @remotion/media
```

This goes for `@remotion/*` packages, `mediabunny`, `@mediabunny/*`, `zod`, and `@huggingface/transformers`.

## Visual checks

When a visual check is useful, open the [Remotion Studio](../remotion-studio/REFERENCE.md) for an interactive preview.

You can also use [Rendering](../remotion-render/REFERENCE.md) to inspect one or several frames as images.
