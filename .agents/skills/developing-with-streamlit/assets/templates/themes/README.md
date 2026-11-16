# Streamlit theme templates

Ready-to-use theme configs. Each file in `configs/` is a complete theme
block — paste into your app's `.streamlit/config.toml`, or adapt into a
shared brand file and point each app’s `theme.base` at it.

When several apps share a brand, put cross-app brand keys (colors, fonts,
radii, borders, chart/dataframe palettes) in one `theme.base` file and
override per app. Keep app-specific layout tweaks (padding, denser
sidebar, one-off primary) in each app’s `config.toml`. Streamlit resolves
a relative `theme.base` path from the `streamlit run` working directory,
not from `config.toml`. For a single app, copy a template straight into
`.streamlit/config.toml`. Choose single or dual mode from the goal below;
use dual mode only when users should control appearance.

| Goal | Approach |
|------|----------|
| Same brand across many apps | Shared TOML/URL via `theme.base`; tweak in each app’s `config.toml` |
| Locked single look | Single-mode template or `[theme]` only |
| User can toggle light/dark | Dual-mode template (`shadcn-dual`, `dense-dashboard`) |

## Dual-mode (settings toggle stays available)

| Theme | Modes | Primary | Notes |
|-------|-------|---------|-------|
| **shadcn-dual** | Light + dark | `#18181B` / `#71717A` | Neutral brand look with per-mode sidebars |
| **dense-dashboard** | Light + dark | `#1D4ED8` / `#2563EB` | Compact `paddingTop`/`paddingBottom` for KPI dashboards |

## Single-mode (locked appearance)

| Theme | Base | Primary color | Fonts |
|-------|------|---------------|-------|
| **dracula** | Dark | `#BD93F9` (purple) | Fira Sans, JetBrains Mono |
| **financial-dashboard** | Dark | `#60A5FA` (blue) | Inter, JetBrains Mono |
| **fluent** | Light | `#0078D4` (blue) | Segoe UI, Cascadia Code |
| **jupyter** | Light | `#F37626` (orange) | Source Sans 3, Source Code Pro |
| **material-ui** | Light | `#6750A4` (violet) | Roboto, Roboto Mono |
| **minimal** | Dark | `#6366F1` (indigo) | Inter, JetBrains Mono |
| **nord** | Dark | `#88C0D0` (frost blue) | Inter, JetBrains Mono |
| **one-dark-pro** | Dark | `#61AFEF` (blue) | IBM Plex Sans, JetBrains Mono |
| **shadcn** | Light | `#18181B` (zinc) | Inter, JetBrains Mono |
| **solarized-light** | Light | `#268BD2` (blue) | Source Sans 3, Source Code Pro |
| **ubuntu** | Light | `#E95420` (orange) | Ubuntu, Ubuntu Mono |
| **vscode** | Dark | `#0078D4` (blue) | Segoe UI, Fira Code |

All themes load [Google Fonts](https://fonts.google.com/) via the
`font = "<family>:<stylesheet_url>"` syntax — no local font files required.

See `references/theme.md` for shared `theme.base` inheritance, light/dark
sections, padding, and the full theming guide.
