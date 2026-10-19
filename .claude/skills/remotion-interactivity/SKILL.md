---
name: remotion-interactivity
description: Structure Remotion markup for interactivity
version: 4.0.536
---

By writing Remotion markup in a specific way, the Remotion Studio is able to recognize the structure of the code and makes it interactive:

- Allowing items to be selected by clicking on them
- Allowing drag+drop, resizing and rotation
- Editing the CSS styles
- Making keyframes and easing values editable

If the markup is too complex for the Studio to make it interactive, then the values become grayed out.

## Prefer interactive components with their own timelines

Build new compositions with `Track`, connected compositions, and `Interactive.create()`.

Set `layout` explicitly to `'absolute-fill'` for scenes or `'none'` for bounded elements. Register the same exported scene and reusable element components with `Composition`.

Start with the complete [Track + connected compositions example](timeline-structure.md).
It includes the element, scene, parent timeline, and root registrations.

```tsx title="MyVideo.tsx"
import {Track, useVideoConfig} from 'remotion';
import {Chapter} from './Chapter';

export const MyVideo = () => {
  const {fps} = useVideoConfig();

  return (
    <Track name="Chapters">
      <Chapter
        name="Opening"
        durationInFrames={3 * fps}
        title="Introduction"
      />
      <Chapter
        name="Feature"
        from={3 * fps}
        durationInFrames={4 * fps}
        title="New features"
      />
    </Track>
  );
};
```

Put background and alignment styles on each scene instance, as shown in the
complete example. Keep layout-only containers as plain HTML.

### Choose schema fields

Each key in the schema is a prop that Studio can read and edit at the call site.
Props that are not in the schema still work, but are not editable in Studio.
Keys may use dot notation, such as `style.color`.

| Type                                                                         | Use for                                                      | Keyframable   |
| ---------------------------------------------------------------------------- | ------------------------------------------------------------ | ------------- |
| `string`                                                                     | Strings, such as a title, prompt, or code snippet            | No            |
| `number`                                                                     | Numbers, with optional `min`, `max`, `step`, `integer`       | Yes           |
| `boolean`                                                                    | On/off switches                                              | Yes (hold)    |
| `color`                                                                      | CSS color strings                                            | Yes           |
| `enum`                                                                       | A choice between `variants`, each with its own nested schema | Opt-in (hold) |
| `array`                                                                      | Lists of numbers, colors, enums and more                     | No            |
| `asset`                                                                      | Media sources, with optional `assetType`                     | No            |
| `font-family`                                                                | CSS font family                                              | No            |
| `font-weight`                                                                | Font weight                                                  | Yes           |
| `translate`, `scale`, `rotation-css`, `rotation-degrees`, `transform-origin` | Transforms                                                   | Yes           |
| `uv-coordinate`                                                              | A normalized `[x, y]` point on the element                   | Yes           |
| `svg-path`                                                                   | SVG path data                                                | Yes           |
| `remotion-captions`                                                          | `Caption[]` data                                             | No            |
| `hidden`                                                                     | A value kept out of the controls                             | —             |

Every field needs a `default` and should have a `description`, which Studio shows as the label.
Set `keyframable: false` to show a static control.

Expose content and per-instance appearance, such as the text and an accent color.
Do not add fields for `style.translate`, `style.scale`, `style.rotate`, `style.transformOrigin` and `style.opacity`: `Interactive.create()` adds them automatically.

To make CSS properties of the root editable per instance, spread the built-in schema fragments:

```tsx
const cardSchema = {
  ...Interactive.textSchema, // style.color, style.fontSize, style.fontWeight, ...
  ...Interactive.backgroundSchema, // style.backgroundColor
  ...Interactive.borderRadiusSchema, // style.borderRadius, ...
} as const satisfies InteractivitySchema;
```

Also available: `Interactive.borderSchema`, and `Interactive.captionsSchema` for components that accept captions.
For components that accept `React.ReactNode` children, add `...Interactive.childrenSchema`.
It provides controls for children content and may evolve to support richer content.
Currently, it uses a string field labeled "Text" with a default of `''`.
If a component requires string-only children, declare an explicit `children` field with `type: 'string'` instead.
`Interactive.textSchema` controls typography styles; `childrenSchema` controls content.
The children fragment is not included in `baseSchema` or automatically added to custom components.
Nested markup and computed children are currently read-only.
`text-content` is a deprecated alias for the `string` field type.
See [`InteractivitySchema`](https://www.remotion.dev/docs/interactivity-schema) for all options.

### Register reusable components as connected compositions

Register scenes and reusable elements as standalone compositions. Studio calls
these **connected compositions**: they can be opened in their own timeline while
sharing the same component implementation with the parent video.

Define required styles and load fonts inside the component so it works without
its parent. See
parent independence.

Register the same exported component reference that the parent renders. For the
example above, use `component={Chapter}`, not `ChapterInner` or an inline wrapper.
`Interactive.create()` provides the sequence, so no extra `<Sequence>` is needed for the connection.

```tsx title="src/Root.tsx"
import {Composition} from 'remotion';
import {Chapter} from './Chapter';

export const RemotionRoot = () => (
  <Composition
    id="Chapter"
    component={Chapter}
    width={1280}
    height={720}
    fps={30}
    durationInFrames={90}
    defaultProps={{
      title: 'A new perspective',
      style: {
        backgroundColor: '#111111',
        justifyContent: 'center',
        alignItems: 'center',
      },
    }}
  />
);
```

Choose a unique ID, representative inline defaults, and dimensions, fps, and
duration suitable for previewing the component. Registration defaults do not
automatically copy props from a parent instance. See
connected compositions for
registration and extraction details.

### Put timing directly on the component

Avoid a separate `<Sequence>` around one component that already accepts timing
props. Built-in interactive components and custom components made with
`Interactive.create()` can receive `name`, `from`, `durationInFrames`,
`trimBefore`, and `playbackRate` directly.

```tsx
<Chapter
  name="Opening scene"
  from={30}
  durationInFrames={90}
  style={{opacity: 0.9}}
  title="A new perspective"
/>
```

For shared scene timing, group the content in a component made with
`Interactive.create()` and time that instance. Managed roots also accept
`width` and `height` for `useVideoConfig()`.

Use `<Track>` to put items on the same Studio timeline row.
Use `<TransitionSeries>` when scenes are sequential.

## Give every independently editable item its own JSX node

The Studio edits the JSX source node that created an item. If multiple runtime
items come from the same JSX node, they share one source-editing target.

For every composition registration, clip, scene, layer or sequence that should
be editable on its own, write a separate JSX node and keep its editable props
on that node. This applies to `<Composition>`, `<Still>`, built-in media
components, `<Sequence>`, `<TransitionSeries.Sequence>`
and custom components.

For example, author an editable timeline like this:

```tsx title="Separate source nodes"
import { Track } from "remotion";

<Track name="Scenes">
  <Introduction name="Introduction" durationInFrames={90} />
  <Demo name="Demo" from={90} durationInFrames={150} />
</Track>
```

A `.map()` or another programmatic loop would create multiple runtime items
from one JSX source node. That is appropriate for repeated output that is
intentionally controlled as one template, such as visualization bars or
particles. It is not appropriate when the instances need independent IDs or
names, props, metadata, timing, ordering, deletion or duplication in the
Studio.

## Make an HTML element interactive using `Interactive`

Every HTML and SVG element (except `<Img>`, it already is interactive) such as `<div>` can be turned interactive using `Interactive`:

```tsx title="Interactive elements"
<Interactive.Div
  name="Greeting card"
  style={{fontSize: 80, padding: 24}}
>
  Hello
</Interactive.Div>
```

This allows styles and keyframes to be set in the Studio. Be sensible, if a component has many elements, the timeline might get messy.

## Prefer inline text

If text is fixed and only used once, write it directly inside the interactive element instead of extracting it into a constant.

```tsx title="Inline text"
// 👍 Fixed copy stays editable
<Interactive.Div name="Title">
  Remotion Best Practices
</Interactive.Div>
```

Use a prop or variable only when the text is dynamic or reused.

## Give interactive elements a descriptive name

Add a `name` prop to elements to make them easily identifyable.
Avoid computed names, hardcode them.

```tsx title="Interactive names"
<>
  <Interactive.Div name="Hero title" style={{fontSize: 80}}>
    Launch day
  </Interactive.Div>
  <Img name="Avatar" src="https://remotion.media/image.jpeg" />
  <Video name="Background" src="https://remotion.media/video.mp4" />
  <Interactive.Div name="Title">
    Launch day
  </Interactive.Div>
</>
```

## Keep all CSS styles inline

The best way is to just pass a plain object to `style` - no referring to constants, no object spreading, no math.

```tsx title="Interactive example"
<Interactive.Div
  style={{
    fontSize: 80,
    color: 'red',
  }}
>
  Hello World!
</Interactive.Div>
```

```tsx title="❌ Bad for interactivity"
const baseStyle = useMemo(() => {
  return {
    fontSize: 12 // ❌ Non-inline styles are not supported
  }
}, []);

<Interactive.Div
  style={{
    ...baseStyle, // ❌ Spreading is not supported
    color: RED, // ❌ Referring to constants is not supported
    scale: frame * 10 // ❌ Math is not supported
  }}
>
  Hello World!
</Interactive.Div>
```

## Animate using `interpolate()`

Write animations as inline `interpolate()` calls on the property that changes.  
The output range, easing, extrapolation and `output` property should use hardcoded values.

The input range may additionally use `durationInFrames`, `fps`, `width` and `height` destructured directly from `useVideoConfig()`. Bare identifiers such as `durationInFrames`, multiplication with a number such as `2 * fps` or `fps * 2`, and subtraction of a number such as `durationInFrames - 1` are supported.

```tsx title="Inline values"
const {fps, durationInFrames} = useVideoConfig();

// 👍 Inline values can be standardized and keyframed
<Interactive.Div
  name="Product card"
  style={{
    color: 'white',
    fontSize: 80,
    scale: interpolate(frame, [0, fps], [0, 1], {
      easing: Easing.spring({damping: 200}),
      output: 'perceptual-scale',
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp'
    }),
    rotate: interpolate(frame, [0, 1 * fps], ['0deg', '20deg'], {
      easing: Easing.spring({damping: 200}),
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp'
    }),
    translate: interpolate(
      frame,
      [durationInFrames - 30, durationInFrames],
      ['0px 0px', '0px 120px'],
      {
        easing: Easing.spring({damping: 200}),
        output: 'perceptual-scale',
        extrapolateLeft: 'clamp',
        extrapolateRight: 'clamp'
      }
    ),
  }}
/>
```

```tsx title="❌ Bad interactivity"
const translateY = interpolate(frame, [0, 30], [0, 120]); // ❌ Math should be directly in the markup

<Interactive.Div
  name="Product card"
  style={{
    translate: translateY, // ❌ Only inline interpolate() calls are supported,
    rotate: interpolate(frame, [start, start + 10], [0, Math.PI]), // ❌ Cannot use math with arbitrary variables, cannot use constants
    scale: interpolate(anyVariable, [0, 30], [0, 1]) // ❌ Can only interpret the `frame` variable.
  }}
/>
```

## Keep SVG paths editable with `Interactive.Path`

Use `<Interactive.Path>` from `remotion` instead of `<path>` inside an SVG to make the path visually editable.

Install `@remotion/paths` for path interpolation and Studio path keyframes:

```sh
bunx remotion add @remotion/paths
```

If the geometry is meant to be static, put the path string directly in the `d` prop. Do not extract it into a constant.

```tsx title="Editable static path"
import {Interactive} from 'remotion';

<Interactive.Svg width={300} height={300} viewBox="0 0 300 300">
  <Interactive.Path
    name="Triangle"
    d="M 40 40 L 260 40 L 150 260 Z"
    fill="#0b84f3"
  />
</Interactive.Svg>
```

### Morph paths using inline `interpolatePaths()`

Use `interpolatePaths()` from `@remotion/paths` directly in `d`.  
It accepts a frame, an input range, an equally sized array of path strings, and options for easing, extrapolation, and posterization.
Keep the output paths, ranges, and options inline, following the same input-range rules as `interpolate()` above.  
Do not use `interpolatePath()` API or extract the interpolated result into a variable when the path keyframes should remain editable in Studio.

```tsx title="Editable path keyframes"
import {interpolatePaths} from '@remotion/paths';
import {Easing, Interactive, useCurrentFrame} from 'remotion';

export const MorphingPath = () => {
  const frame = useCurrentFrame();

  return (
    <Interactive.Svg width={300} height={300} viewBox="0 0 300 300">
      <Interactive.Path
        name="Morphing triangle"
        d={interpolatePaths(
          frame,
          [0, 30, 60],
          [
            'M 40 40 L 260 40 L 150 260 Z',
            'M 40 150 L 150 40 L 260 150 Z',
            'M 40 260 L 150 40 L 260 260 Z',
          ],
          {
            easing: Easing.bezier(0.42, 0, 0.58, 1),
            extrapolateLeft: 'clamp',
            extrapolateRight: 'clamp',
          },
        )}
        fill="#0b84f3"
      />
    </Interactive.Svg>
  );
};
```

Studio can edit the path at the current frame, add or move keyframes, and adjust their easing.  
Use `strokeDasharray` and `strokeDashoffset` to evolve paths.

## Use `scale`, `translate`, `rotate` CSS properties

Avoid the `transform` CSS property.  
If possible, use `scale`, `rotate` and `translate` instead because only they are interactively editable.

## Keep composition metadata inline

When scaffolding a composition, use a JSX string literal for `id`, keep `width`, `height`, `fps`, `durationInFrames` and `defaultProps` inline and make no type assertions.

The Props editor can save visual edits back to your code when `defaultProps` is an inline object literal on `<Composition>` or `<Still>`.

```tsx
// 👍 Static values are in <Composition>, dynamic values are in calculateMetadata()
const calculateMetadata = useMemo(async () => {
  const dimensions = await getDimensions(); // just an example
  return {width: dimensions.width, height: dimensions.height};
});

<Composition
  id="my-video"
  component={MyComponent}
  durationInFrames={150}
  fps={30}
  calculateMetadata={calculateMetadata}
  defaultProps={{title: 'Hello', color: '#0b84ff'}}
/>
```

```tsx title="Negative examples"
const defaultProps = {title: 'Hello', color: '#0b84ff'}; // ❌ Don't extract defaultProps, must be inline
const calculateMetadata = useMemo(() => {
  // ❌ Unnecessary because no calculation is being done,
  return {durationInFrames: 150, fps: 30, width: 1920, height: 1080};
});

<Composition
  id="my-video"
  component={MyComponent}
  calculateMetadata={calculateMetadata}
  defaultProps={{
    title: 'Hello',
  } as Props} // ❌ Don't have type assertions, instead type MyComponent correctly
/>
```

Use only `calculateMetadata()` for the part of the metadata that is dynamic.

## Effects should be inline too

Keep effect arrays and parameters inline so their shape and keyframes remain editable. See [Inline effects](./inline-effects.md) for examples.

## Making your own component interactive

To make a custom userland component interactive, use:
[Make a component interactive](https://www.remotion.dev/docs/studio/make-component-interactive.md)

## Video editing

If a Remotion component mainly consists of video and audio clips, see Video editing for best practices on how to structure Remotion markup so the clips are interactively editable in the timeline.
