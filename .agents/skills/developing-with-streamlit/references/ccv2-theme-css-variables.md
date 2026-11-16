## Streamlit theme CSS variables for CCv2 components (`--st-*`)

Streamlit injects a set of `--st-*` CSS custom properties into CCv2 components so your component can match the app’s active theme from within your component CSS (including when `isolate_styles=True` and you’re rendering inside a shadow root).

**Recommendation:** Prefer `var(--st-…)` over hard-coded colors and sizes. These variables automatically adapt to a user's current Streamlit theme (light/dark/custom), so most components **do not** need separate “dark mode vs light mode” styling.

## Contents

- Quick start
- Gotchas: serialization + fallbacks
- Cheat sheet: the 90% variables (intent → `--st-*`)
- Foundation tokens (surfaces, text, borders, shape)
- Typography tokens
- Data display tokens (dataframes/tables)
- Data visualization tokens (chart palettes)
- Semantic/status palette (red/green/etc.)
- Appendix: full variable index (alphabetical)

### Quick start

Use them like any CSS variable:

```css
.card {
  background: var(--st-secondary-background-color);
  color: var(--st-text-color);
  border: 1px solid var(--st-border-color);
  border-radius: var(--st-base-radius);
}

.primaryButton {
  background: var(--st-primary-color);
  color: var(--st-background-color);
  border-radius: var(--st-button-radius);
}
```

### Gotchas: serialization rules + safe fallbacks

These variables originate from Streamlit’s theme object and are serialized into strings:

- **Strings**: passed through (e.g. `--st-primary-color: #ff4b4b`).
- **Numbers**: stringified (e.g. `--st-base-font-weight: 400`).
- **Booleans**: become `"1"` or `"0"` (e.g. `--st-link-underline`).
- **Arrays**: become a comma-joined string (e.g. `--st-heading-font-sizes: 2.75rem,2.25rem,...`).
  - If you need individual items in JS, split on `","`.
- **Missing values (`null` / `undefined`)**: become `unset` so consumers fall back to initial/inherited CSS behavior.

### Cheat sheet: the 90% variables (intent → `--st-*`)

Use this section as your starting point. It covers what most components need most of the time.

| Intent                    | Variables                                                              |
| ------------------------- | ---------------------------------------------------------------------- |
| App/page background       | `--st-background-color`                                                |
| Panel/card background     | `--st-secondary-background-color`                                      |
| Body text                 | `--st-text-color`                                                      |
| Headings                  | `--st-heading-color`, `--st-heading-font`                              |
| Primary accent / emphasis | `--st-primary-color`                                                   |
| Links                     | `--st-link-color`, `--st-link-underline`                               |
| Borders / dividers        | `--st-border-color`, `--st-border-color-light`                         |
| Widget outline borders    | `--st-widget-border-color`                                             |
| Corner radius             | `--st-base-radius`, `--st-button-radius`                               |
| Code blocks               | `--st-code-background-color`, `--st-code-text-color`, `--st-code-font` |

### Foundation tokens (surfaces, text, borders, shape)

#### Surfaces and content colors

- `--st-background-color` (page background)
- `--st-secondary-background-color` (panels, cards, containers)
- `--st-text-color` (default text)
- `--st-heading-color` (derived heading color)
- `--st-primary-color` (brand / accent)
- `--st-link-color` (link color)
- `--st-link-underline` (boolean serialized to `"1"` / `"0"`)

#### Borders and separators

- `--st-border-color` (default borders/dividers)
- `--st-border-color-light` (derived lighter border)
- `--st-widget-border-color` (widget borders)

#### Shape (radii)

- `--st-base-radius`
- `--st-button-radius`

#### Code block colors

- `--st-code-background-color`
- `--st-code-text-color`

### Typography tokens

#### Font families

- `--st-font` (body font)
- `--st-heading-font`
- `--st-code-font`

#### Body sizing and weights

- `--st-base-font-size`
- `--st-base-font-weight` (number)

#### Headings (H1–H6)

Arrays (comma-joined):

- `--st-heading-font-sizes` (array; typically 6 values for H1–H6)
- `--st-heading-font-weights` (array; typically 6 values for H1–H6)

Per-level convenience variables:

- `--st-heading-font-size-1`
- `--st-heading-font-size-2`
- `--st-heading-font-size-3`
- `--st-heading-font-size-4`
- `--st-heading-font-size-5`
- `--st-heading-font-size-6`
- `--st-heading-font-weight-1` (number)
- `--st-heading-font-weight-2` (number)
- `--st-heading-font-weight-3` (number)
- `--st-heading-font-weight-4` (number)
- `--st-heading-font-weight-5` (number)
- `--st-heading-font-weight-6` (number)

#### Code typography

- `--st-code-font-size`
- `--st-code-font-weight` (number)

#### Metric value

- `--st-metric-value-font-size`
- `--st-metric-value-font-weight` (number)

### Data display tokens (dataframes/tables)

- `--st-dataframe-border-color`
- `--st-dataframe-header-background-color`
- `--st-dataframe-header-text-color`

### Data visualization tokens (chart palettes)

Chart palette variables are **arrays serialized as comma-joined strings**:

- `--st-chart-categorical-colors` (discrete series)
- `--st-chart-sequential-colors` (low → high)
- `--st-chart-diverging-colors` (negative ↔ positive around a midpoint)

If you need the palette values in JS, split on commas:

```js
export default function (component) {
  const { parentElement } = component;

  const host = parentElement.host ?? parentElement;
  const raw = getComputedStyle(host)
    .getPropertyValue('--st-chart-categorical-colors')
    .trim();
  const palette = raw ? raw.split(',') : [];
}
```

### Semantic/status palette

These are best for status UI (badges, alerts, validation messages), not for primary layout surfaces.

Each “family” typically comes in three variants:

- **Base**: `--st-<name>-color`
- **Background**: `--st-<name>-background-color`
- **Text**: `--st-<name>-text-color`

Families:

- Red: `--st-red-color`, `--st-red-background-color`, `--st-red-text-color`
- Orange: `--st-orange-color`, `--st-orange-background-color`, `--st-orange-text-color`
- Yellow: `--st-yellow-color`, `--st-yellow-background-color`, `--st-yellow-text-color`
- Blue: `--st-blue-color`, `--st-blue-background-color`, `--st-blue-text-color`
- Green: `--st-green-color`, `--st-green-background-color`, `--st-green-text-color`
- Violet: `--st-violet-color`, `--st-violet-background-color`, `--st-violet-text-color`
- Gray: `--st-gray-color`, `--st-gray-background-color`, `--st-gray-text-color`

### Appendix: full variable index (alphabetical)

- `--st-background-color`
- `--st-base-font-size`
- `--st-base-font-weight`
- `--st-base-radius`
- `--st-blue-background-color`
- `--st-blue-color`
- `--st-blue-text-color`
- `--st-border-color`
- `--st-border-color-light`
- `--st-button-radius`
- `--st-chart-categorical-colors`
- `--st-chart-diverging-colors`
- `--st-chart-sequential-colors`
- `--st-code-background-color`
- `--st-code-font`
- `--st-code-font-size`
- `--st-code-font-weight`
- `--st-code-text-color`
- `--st-dataframe-border-color`
- `--st-dataframe-header-background-color`
- `--st-dataframe-header-text-color`
- `--st-font`
- `--st-gray-background-color`
- `--st-gray-color`
- `--st-gray-text-color`
- `--st-green-background-color`
- `--st-green-color`
- `--st-green-text-color`
- `--st-heading-color`
- `--st-heading-font`
- `--st-heading-font-size-1`
- `--st-heading-font-size-2`
- `--st-heading-font-size-3`
- `--st-heading-font-size-4`
- `--st-heading-font-size-5`
- `--st-heading-font-size-6`
- `--st-heading-font-sizes`
- `--st-heading-font-weight-1`
- `--st-heading-font-weight-2`
- `--st-heading-font-weight-3`
- `--st-heading-font-weight-4`
- `--st-heading-font-weight-5`
- `--st-heading-font-weight-6`
- `--st-heading-font-weights`
- `--st-link-color`
- `--st-link-underline`
- `--st-metric-value-font-size`
- `--st-metric-value-font-weight`
- `--st-orange-background-color`
- `--st-orange-color`
- `--st-orange-text-color`
- `--st-primary-color`
- `--st-red-background-color`
- `--st-red-color`
- `--st-red-text-color`
- `--st-secondary-background-color`
- `--st-text-color`
- `--st-violet-background-color`
- `--st-violet-color`
- `--st-violet-text-color`
- `--st-widget-border-color`
- `--st-yellow-background-color`
- `--st-yellow-color`
- `--st-yellow-text-color`
