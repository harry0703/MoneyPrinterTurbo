---
name: developing-with-streamlit
description: "**[REQUIRED]** Use for ALL Streamlit tasks: creating, editing, debugging, beautifying, styling, theming, or optimizing Streamlit applications. Also required for building custom components (inline or packaged), using st.components.v2, or any HTML/JS/CSS component work. Triggers: streamlit, st., dashboard, app.py, beautify, style, CSS, color, background, theme, button, widget styling, custom component, st.components, packaged component, pyproject.toml, asset_dir, CCv2, HTML/JS component."
---

# Developing with Streamlit

This is a **routing skill** that directs you to specialized references for Streamlit development.

## When to Use

Invoke this skill when the user's request involves:
- Creating a new Streamlit app
- Editing or modifying an existing Streamlit app
- Debugging Streamlit issues (errors, session state bugs, performance problems)
- Beautifying or improving the visual design of a Streamlit app
- Optimizing Streamlit performance (caching, fragments, reruns)
- Building and running Streamlit apps
- Building chat, conversational, or agentic UIs (AI assistants, thinking expanders, chain-of-thought, tool-call timelines)
- Styling widgets (button colors, backgrounds, CSS customization)
- Advanced server configuration with `st.App`, ASGI, Starlette, FastAPI integration, custom routes, middleware, or lifespan hooks
- Any question about Streamlit widgets, layouts, or components

**Trigger phrases:** "streamlit", "st.", "st.App", "dashboard", "app.py", "beautify app", "make it look better", "style", "CSS", "color", "background", "theme", "button", "slow rerun", "session state", "performance", "faster", "cache", "chat", "agentic", "chain of thought"

## Best practices quick reference

**IMPORTANT — `use_container_width` is deprecated.** Never add `use_container_width` to new code. Use `width="stretch"` or `width="content"` instead. Dataframes and most charts stretch to fill their container by default, but buttons, including `st.button`, `st.download_button`, `st.form_submit_button`, `st.link_button`, and `st.page_link`, default to `width="content"`; pass `width="stretch"` to make one fill its container. Remove `use_container_width` when you encounter it.

Apply these defaults unless the user's app or request clearly needs a different approach. For examples, read `references/best-practices.md`.
- Do not use `use_container_width`; use `width="stretch"` or `width="content"` instead.
- Prefer native Streamlit elements over recreating UI with custom HTML. This includes UI created with `st.html`, `st.markdown(..., unsafe_allow_html=True)`, or deprecated `st.components.v1.html`. Use custom HTML only when no native element provides the required UI or behavior.
- Do not use the deprecated `st.components.v1.html` or `st.components.v1.iframe` commands. Use `st.iframe` for iframe-based rendering of URLs or HTML, and use `st.html` for HTML/CSS that should render directly in the app; `st.html` ignores JavaScript by default unless `unsafe_allow_javascript=True`.
- Do not apply CSS to style the app unless the user actively requests it. Use native Streamlit features and `.streamlit/config.toml` to customize the appearance; see the [theming reference](references/theme.md).
- Prefer Material Symbols icons (`:material/icon_name:`) over emojis for navigation, buttons, and labels. Use emojis sparingly, only when they add a special touch.
- Prefer sentence casing over title casing, including titles and widget labels.
- Do not use empty widget labels; use `label_visibility="collapsed"` or `label_visibility="hidden"` when a visible label is not desired.
- When an alert (`st.info`, `st.success`, `st.warning`, or `st.error`) needs a headline, pass keyword-only `title=` instead of bolding the first line of the body or adding a heading above it.
- Pass keyword-only `alt=` on images, charts, maps, media, iframes, PDFs, tables, dataframes, and data editors so assistive technologies can name them. Keep it short; decorative `alt=""` is only for `st.image` / `st.pyplot`. See `references/media-display.md` and `references/data-display.md`.
- Use `st.container(border=True)` for simple visual grouping. Prefer `st.container(horizontal=True)` over `st.columns` for responsive row layouts; use `st.columns` for fixed grids, precise width ratios, or side-by-side cards that must share a width.
- Align elements placed side by side: use `vertical_alignment="bottom"` for rows that mix labeled inputs with buttons, checkboxes, or toggles, and give sibling cards consistent content (for example, all metrics with or all without `delta`) or `height="stretch"`. See "Aligning elements side by side" in `references/layouts.md`.
- Prefer `st.navigation` and `st.Page` with an `app_pages/` folder over the legacy `pages/` directory, `st.page_link`, or other multipage-app v1 patterns.
- Always cache compute-intensive or expensive data-loading code. Use `st.cache_data` for serializable data and `st.cache_resource` for shared resources like API clients, raw connectors, and models; do not wrap `st.connection`, which is already cached. Include appropriate `ttl` and/or `max_entries` limits to prevent unbounded growth. Cache the expensive source data, then apply cheap interactive filters outside the cached function.
- Order scripts so fast UI (titles, layout, widgets) renders before slow computation. Streamlit streams elements top to bottom and temporarily greys out (marks stale) not-yet-redrawn elements from the previous run while a slow step is in progress, clearing each as the new run recreates it; put slow work last, reserve output slots with `st.container()`, or isolate slow sections in fragments.
- Use `st.fragment` for independent sections that should rerun separately from the rest of the app, such as auto-refreshing charts or controls that do not need to rerun the full page.
- Use `st.form` to batch related inputs and rerun only on submit, especially when intermediate widget changes would trigger expensive work. If some inputs must rerun to update others (for example, dependent options), use `on_change="ignore"` on the remaining inputs instead of a form (advanced; see "Skip reruns on individual widgets" in `references/performance.md`).
- Do not put expensive work unguarded inside `st.tabs`, `st.expander`, or `st.popover`: hidden, collapsed, or closed content still computes on every rerun, and caching doesn't change that. Pass `on_change="rerun"` and render each body only when the container's `.open` is `True`, or switch to `st.segmented_control` or `st.toggle` with an `if`.
- Use `st.secrets` for credentials. Never hard-code secrets in app code, never commit `.streamlit/secrets.toml`, and use parameterized queries for user-provided values.
- Prefer Vega-based charts (`st.altair_chart`, `st.line_chart`, `st.area_chart`, `st.scatter_chart`, `st.bar_chart`, `st.vega_lite_chart`) over `st.pyplot` and Plotly. Use `st.echarts_chart` when you already have an Apache ECharts option or a `pyecharts` chart.
- Prefer `st.segmented_control` over `st.radio(..., horizontal=True)`.
- For about 2–5 options, keep them visible instead of in a dropdown: `st.segmented_control` for a single choice and `st.pills(..., selection_mode="multi")` for several. Use `st.selectbox` or `st.multiselect` for longer lists.
- Use `st.menu_button` for a button that opens a short list of one-shot actions. Do not build one from `st.popover` with buttons or from `st.selectbox`.
- Initialize `st.session_state` in one clear place, avoid module-level mutable state for per-user data, and set widget `key` values when widgets repeat, parameters change dynamically, or code needs programmatic access.
- Keep page files as direct scripts; do not wrap page bodies in functions. Move shared business logic into modules.

## Proactively Look Up API Details

When selecting a Streamlit command, discovering functionality that may be newer than the agent's knowledge cutoff, validating available functionality, or using unfamiliar parameters, proactively look up the relevant local docs before coding:

```bash
streamlit docs st.<command>
```

Run this with the Streamlit installation relevant to the app being edited. Use `references/api-reference.md` to discover available public `st` commands and namespaces, then use `streamlit docs st.<command>` for exact signatures, parameters, and docstrings.

When annotating Streamlit-owned values returned by commands or stored in Session State, import the curated public types from `streamlit.typing` (also available as `st.typing`) instead of their internal implementation modules. See `references/api-reference.md` for the available types.

## Workflow

```
Step 1: Locate the Streamlit source code
    ↓
Step 2: Identify task type and load appropriate reference(s)
    ↓
Step 3: Apply guidance from reference to edit code
    ↓
Step 4: Check if app is running and offer to run it
```

### Step 1: Locate the Streamlit Source Code (if needed)

**Goal:** Identify the app file(s) to edit. **Skip this step if already clear from context.**

**When to skip:**
- User mentioned a specific file path (e.g., "edit `src/app.py`")
- User has file(s) already in conversation context
- Working directory has an obvious single entry point (`app.py`, `streamlit_app.py`)

**When to search:**
- User says "my streamlit app" without specifying which file
- Multiple Python files exist and it's unclear which is the entry point

**If searching is needed:**

1. **Quick scan** for Streamlit files:
   ```bash
   grep -rl 'import streamlit\|from streamlit' --include='*.py' . 2>/dev/null | head -10
   ```

2. **Apply entry point heuristics** (in priority order):
   - `streamlit_app.py` at root → **this is the entry point** (canonical name)
   - `app.py` at root → likely entry point
   - File using `st.navigation` → entry point for multi-page apps
   - Single `.py` file at root with streamlit import → entry point
   - Files in `pages/` or `app_pages/` subdirectory → **NOT entry points** (these are sub-pages)

3. **If entry point is obvious** → use it, no confirmation needed

   Example: Found `streamlit_app.py` and `pages/metrics.py` → use `streamlit_app.py`

4. **Only ask if genuinely ambiguous** (e.g., multiple root-level candidates, none named `streamlit_app.py`):
   ```
   Found multiple potential entry points:
   - dashboard.py
   - main.py

   Which is your main app?
   ```

**Output:** Path to the main Streamlit source file(s)

### Step 2: Identify Task Type and Route to Reference

**Goal:** Determine what the user needs and load the appropriate guidance.

### Reference routing table

Use this routing table to select reference(s). **Always read the reference file** before making changes.

> All file paths below are relative to this skill's directory (`streamlit/.agents/skills/developing-with-streamlit/`).

| User Need | Reference to Read |
|-----------|-------------------|
| **General Streamlit best practices, app code review, or examples for recommended patterns and anti-patterns** — styling, layout, navigation, caching, fragments, forms, charts, widgets, accessible `alt=` names, session state, secrets, and page organization | read `references/best-practices.md` |
| **App is slow, reruns take too long, data loads repeatedly, or work is recomputed unnecessarily** — caching strategies (`st.cache_data`, `st.cache_resource`), `st.fragment` for partial reruns, (optionally) `parallel=True` when independent fragments can run concurrently, `on_change="ignore"` to update a widget without a rerun, and client-side validation and limits that catch bad input in the browser | read `references/performance.md` |
| **Building a dashboard with KPIs, metrics, and charts** — composing `st.metric`, charts, and data tables into clean dashboard layouts with columns and containers | read `references/dashboards.md` |
| **Making an app look polished** — brand colors, light/dark, page padding, icons (Material Symbols), spacing, visual hierarchy, and small design touches that elevate quality | read `references/theme.md` first, then `references/design.md` |
| **Choosing the right selection widget** — when to use `st.selectbox` vs `st.radio` vs `st.pills` vs `st.segmented_control` vs `st.multiselect` vs `st.feedback` (ratings), including modern replacements for deprecated patterns, and how to filter high-cardinality values (thousands+) without sending them all to the browser | read `references/selection-widgets.md` |
| **Custom themes, colors, padding, or styling requests** — configuring `.streamlit/config.toml` (including light/dark, sidebar, and `paddingTop`/`paddingBottom`), reading the active theme at runtime via `st.context.theme`, and the CSS pattern to use only when the user explicitly asks for CSS | read `references/theme.md` |
| **Page structure and layout** — `st.columns`, `st.tabs`, `st.sidebar`, `st.container`, `st.expander`, responsive layout patterns, when to use each container type, and aligning side-by-side elements (widget heights, `vertical_alignment`, equal-height cards) | read `references/layouts.md` |
| **Displaying or editing tabular data** — `st.dataframe` column configuration, `st.data_editor` for editable tables, `st.table` for small static tables and key-value/description lists, chart selection, accessible `alt=` names, and best practices for large datasets | read `references/data-display.md` |
| **Apache ECharts or pyecharts** — render an existing ECharts option dict, JSON string, or `pyecharts` chart with native `st.echarts_chart` rather than a third-party component (pass `alt=` carefully — it replaces the generated description) | read `references/data-display.md` |
| **Multi-page app architecture** — `st.navigation`, `st.Page`, page routing, shared state across pages, and structuring apps with multiple views | read `references/multipage-apps.md` |
| **Persisting values across reruns** — `st.session_state`, widget keys, callbacks (`on_change`, `on_click`), and patterns for stateful interactions | read `references/session-state.md` |
| **Making a selection shareable via URL / syncing a widget to a query param** — `bind="query-params"` + `key=` for automatic URL sync (don't hand-roll `st.query_params`) | read `references/session-state.md` |
| **Discovering available Streamlit public APIs, looking up `st.<command>` commands, exact parameters, docstrings, signatures, public annotation types, or choosing the right top-level command** — quick table of public `st` commands, related public objects, and `streamlit.typing` exports plus CLI instructions for inspecting local docstrings | read `references/api-reference.md` |
| **Rich text formatting** — Markdown in `st.markdown` and widget labels, colored text (`:red[...]`), badges, Material Symbols icons (`:material/icon_name:`), LaTeX math, and Mermaid diagrams | read `references/markdown.md` |
| **Displaying text** — headings (`st.title`/`st.header`/`st.subheader`), `st.markdown`, `st.caption`, `st.code`, `st.text`, `st.badge`, and streaming text via `st.write_stream`; prefer explicit elements over `st.write`/magic | read `references/text-display.md` |
| **Displaying media** — images, video, audio, and PDFs (`st.image`, `st.video`, `st.audio`, `st.pdf`) via the native viewers instead of raw HTML embeds; keyword-only `alt=` for accessible names | read `references/media-display.md` |
| **Chat, conversational, and agentic UIs** — `st.chat_message`, `st.chat_input`, streaming responses with `st.write_stream`, compact thinking expanders with `type="compact"`, chain-of-thought / tool-call timelines with `type="step"` (including nesting steps inside a compact expander), and building AI assistant interfaces | read `references/chat-ui.md` |
| **Connecting to Snowflake** — `st.connection("snowflake")`, secrets configuration, querying data, and Snowflake-specific patterns | read `references/snowflake-connection.md` |
| **Building or packaging a custom component, triggering events back to Python from JS/HTML, custom HTML/JS with event handling (CCv2), OR any UI element that doesn't exist as a native Streamlit widget** (e.g., drag-and-drop, custom interactive visualization, canvas drawing) | read `references/custom-components-v2.md` — **IMPORTANT: Never use `st.components.v1` for new components; always use `st.components.v2.component()`.** (`st.components.v1.html` and `st.components.v1.iframe` are deprecated in favor of `st.iframe`.) |
| **Using third-party community components** — `streamlit-extras` (annotated text), `streamlit-pivot-table`, and other popular packages that extend Streamlit's built-in capabilities | read `references/third-party-components.md` |
| **Structuring app code** — when to split into modules vs keep in one file, helper functions, and clean project organization patterns | read `references/code-organization.md` |
| **Environment and dependency setup** — Python environment management, installing packages, and configuring the development environment for Streamlit apps | read `references/environment-setup.md` |
| **Streamlit CLI and configuration** — `streamlit run`, `streamlit config`, looking up docstrings (`streamlit docs <command>`), `.streamlit/config.toml` (script-level and project-level), port settings, and server options | read `references/cli.md` |
| **Advanced server configuration** — `st.App`, ASGI entry points, custom HTTP routes, middleware, lifespan hooks, programmatic secrets, exception handlers, and FastAPI/Starlette mounting | read `references/server-asgi.md` |
| **Requiring users to sign in** — `st.login`/`st.logout`/`st.user` with OIDC, gating on `st.user.is_logged_in`, and `[auth]` secrets configuration (not a hand-rolled password gate) | read `references/authentication.md` |
| **Writing automated tests for an app** — `st.testing.v1.AppTest` for headless, in-process tests (simulate widgets, assert on elements) instead of launching a browser/server | read `references/testing.md` |

**Fallback — "this widget doesn't exist in Streamlit":**

If the user asks for a UI element or interaction that **has never been part of Streamlit's API** and cannot be built with any combination of native widgets (e.g., drag-and-drop, canvas drawing, custom interactive visualizations), **route to the CCv2 reference** (`references/custom-components-v2.md`). **Do not** route to CCv2 for UI that Streamlit already provides (e.g., `st.segmented_control`, `st.menu_button`, `st.echarts_chart`); check `references/api-reference.md` first. If the native command is newer than the app's installed Streamlit, suggest upgrading.

**Common combinations:**

For **beautifying/improving an app**, read in order:
1. `references/theme.md` — brand colors, light/dark, sidebar, padding (prefer config over CSS)
2. `references/design.md` — icons, hierarchy, micro-polish
3. `references/layouts.md`
4. `references/selection-widgets.md`

Configure themes via `.streamlit/config.toml` (not CSS unless the user asks). Follow the decision table and key-placement rules in `references/theme.md`.

For **building a dashboard**, read:
1. `references/dashboards.md`
2. `references/data-display.md`
3. `references/theme.md` — when the user wants a branded or polished look, pair with a theme (`theme.base` for a shared brand file/URL; `dense-dashboard` when the app should keep the appearance toggle and use compact padding)

**IMPORTANT - Use templates:**

When creating a **new dashboard app**, prefer starting from a template in `assets/templates/apps/`:
- If a template closely matches the request, copy it and adapt:
  - `dashboard-metrics` — KPI cards with time-series charts
  - `dashboard-companies` — company/entity comparison
  - `dashboard-compute` — resource/credit monitoring
  - `dashboard-feature-usage` — API endpoint usage analytics
  - `dashboard-seattle-weather` — public dataset exploration
  - `dashboard-stock-peers` — financial peer analysis
- If no template is a close match, start from scratch but borrow relevant patterns from the templates (e.g., caching with `@st.cache_data`, `filter_by_time_range()`, `st.set_page_config()`, chart utilities, layout structure)
- When the user wants a branded or polished look, pair the dashboard with a theme from `assets/templates/themes/configs/` (`dense-dashboard` only if the app should keep the appearance toggle and use compact padding), or point `theme.base` at an existing shared brand file or URL
- See `assets/templates/apps/README.md` for template descriptions

When **editing an existing app**, use templates as reference for best practices:
- Check `assets/templates/apps/` for caching patterns, layout structure, and data-loading patterns
- Apply consistent patterns from templates to improve the existing code

When applying a **custom theme**, use a config from `assets/templates/themes/configs/`:
- Prefer `theme.base` (shared corporate/brand TOML or URL) when several apps should inherit the same brand tokens, then override per app for layout-specific tweaks
- Choose **single-mode** (dracula, financial-dashboard, fluent, jupyter, material-ui, minimal, nord, one-dark-pro, shadcn, solarized-light, ubuntu, vscode) for a locked look
- Choose **dual-mode** (`shadcn-dual`, `dense-dashboard`) only when the settings appearance toggle should stay available
- Copy the chosen file to the app's `.streamlit/config.toml` (or point `theme.base` at a shared file)
- Themes include custom fonts via Google Fonts
- See `assets/templates/themes/README.md` for the theme list

For **performance optimization**, read:
1. `references/performance.md`

### Step 3: Apply Guidance to Edit Code

**Goal:** Make changes to the Streamlit app following reference best practices.

**Actions:**

1. Apply the patterns and recommendations from the loaded reference(s)
2. Make edits to the source file(s) identified in Step 1
3. Preserve existing functionality while adding improvements

### Step 4: Check Running Apps and Offer to Run

**Goal:** Help the user see their changes by checking if their app is running.

**Actions:**

1. **Check** for running Streamlit apps on ports 850*:
   ```bash
   lsof -nP -iTCP -sTCP:LISTEN 2>/dev/null | grep -i python | awk '{print $2, $9}' | grep ':85' || echo "No Streamlit apps detected on ports 850*"
   ```

2. **Present** findings to user:

   **If app is running:**
   ```
   Found Streamlit app running:
   - PID: [pid] at http://localhost:[port]

   Your changes should be visible after a page refresh (Streamlit hot-reloads on file save).
   ```

   **If no app is running:**
   ```
   No Streamlit app detected on ports 850*.

   Would you like me to run the app? I can start it with:
     streamlit run [app_file.py]
   ```

3. **If user wants to run the app**, start it:
   ```bash
   streamlit run [path/to/app.py] --server.port 8501
   ```

## Stopping Points

- **Step 4**: Ask before starting the Streamlit app

## Resources

- [Streamlit API Reference](https://docs.streamlit.io/develop/api-reference)
- [Streamlit Gallery](https://streamlit.io/gallery)
