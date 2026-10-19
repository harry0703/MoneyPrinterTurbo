# Connected compositions

Make every scene and reusable element a connected composition:

1. Export it with `Interactive.create()`. Set `layout: 'absolute-fill'` for a scene or `layout: 'none'` for a bounded element.
2. Render the exported component directly inside a named `Track`, with inline timing and props.
3. Register that same reference in `<Composition component={...}>`, alongside the parent video. Keep metadata and representative `defaultProps` inline.

Follow the complete [Track + connected compositions example](../remotion-interactivity/timeline-structure.md), including `Title.tsx`, `Chapter.tsx`, `MyVideo.tsx`, and `Root.tsx`.

Double-clicking an instance opens its connected composition. Editing the shared
component updates both views. Registration defaults do not automatically apply
to the instances in the parent.

## Make the component independent of its parent

The parent is not mounted when the connected composition opens on its own.
Keep required typography in the component and supply background and alignment
in its inline registration defaults. Load fonts in its module or an imported
shared module; see [Google fonts](google-fonts.md) and [local fonts](local-fonts.md).

Verify the component by opening its standalone composition. Keep its fps and
dimensions consistent with the parent unless a difference is intentional.
