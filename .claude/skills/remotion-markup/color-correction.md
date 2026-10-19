---
name: color-correction
description: Correct exposure, white balance, and tone, and apply 3D Cube LUTs to footage.
metadata:
  tags: color-correction, color-grading, lut, cube, exposure, white-balance
---

# Color correction

Apply color adjustments through the `effects` prop of `<Video>` from `@remotion/media`, or other supported components.  
See [effects.md](effects.md) for more context on effects.

## Primary adjustments

Prefer [`colorCorrection()`](https://www.remotion.dev/docs/effects/color-correction) when combining adjustments.  
It performs them in one WebGL pass and exposes controls in the Studio.

| Control                 | Meaning and range                                                         | Neutral value |
| ----------------------- | ------------------------------------------------------------------------- | ------------- |
| `exposure`              | Stops, from `-5` to `5`; positive values brighten                         | `0`           |
| `temperature`           | From `-1` (cooler) to `1` (warmer)                                        | `0`           |
| `tint`                  | From `-1` (greener) to `1` (more magenta)                                 | `0`           |
| `shadows`, `highlights` | From `-1` to `1`; negative values darken, positive values lift the region | `0`           |
| `blacks`, `whites`      | From `-1` to `1`; target narrower regions near black and white            | `0`           |
| `contrast`              | Non-negative multiplier around `pivot` (`0` to `1`, default `0.5`)        | `1`           |
| `saturation`            | Non-negative multiplier; `0` is grayscale                                 | `1`           |
| `vibrance`              | From `-1` to `1`; positive values emphasize muted colors                  | `0`           |

```tsx
import {colorCorrection} from '@remotion/effects/color-correction';
import {Video} from '@remotion/media';
import {staticFile} from 'remotion';

export const CorrectedVideo = () => {
  return (
    <Video
      src={staticFile('footage.mp4')}
      effects={[
        colorCorrection({
          exposure: 0.25,
          temperature: 0.1,
          tint: -0.03,
          shadows: 0.15,
          highlights: -0.1,
          contrast: 1.1,
          saturation: 1.05,
          vibrance: 0.15,
        }),
      ]}
    />
  );
};
```

Internally, `colorCorrection()` applies exposure, white balance, tonal regions,
contrast, saturation, then vibrance. Omitted controls use their neutral values.
Keep everything inline on the target's `effects` prop.

Standalone effects are also available when a different order or an additional
adjustment is needed: `exposure()`, `whiteBalance()`, `shadowsHighlights()`,
`contrast()`, `saturation()`, and `vibrance()`. See [effects](effects.md)

## LUTs and combining effects

A LUT (lookup table) maps input RGB colors to output colors. Use
[`lut()`](https://www.remotion.dev/docs/effects/lut) to apply a 3D `.cube` LUT.  
Its `content` parameter takes the complete file contents as a string.

This example uses a small warm LUT inline:

```tsx
import {colorCorrection} from '@remotion/effects/color-correction';
import {lut} from '@remotion/effects/lut';
import {Video} from '@remotion/media';
import {staticFile} from 'remotion';

export const GradedVideo = () => {
  return (
    <Video
      src={staticFile('footage.mp4')}
      effects={[
        colorCorrection({exposure: 0.25, contrast: 1.1}),
        lut({
          content: `TITLE "Warm"
LUT_3D_SIZE 2
0 0 0
1 0.1 0
0 0.9 0.1
1 0.9 0.1
0 0.1 0.8
1 0.2 0.7
0 0.9 0.8
1 0.9 0.8`,
        }),
      ]}
    />
  );
};
```

### Supported format and limitations

- Only 3D `.cube` LUTs are supported. `LUT_3D_SIZE` must be an integer from `2`
  to `256`, followed by exactly `size ** 3` RGB rows. 1D LUTs are unsupported.
- Optional `TITLE`, `DOMAIN_MIN`, `DOMAIN_MAX`, blank lines, and `#` comments are
  supported. Other LUT formats need conversion before use.
- `lut()` has no `src` or strength/amount parameter. Use `disabled: true` to
  bypass it.

## Studio workflow

Put `.cube` files in `public/` to preview them in the Assets panel.  
The user can drag a 3D `.cube` file from the computer or Assets panel onto a
video in the canvas or timeline to apply the LUT effect.

## See also

- [Color correction documentation](https://www.remotion.dev/docs/color-correction)
