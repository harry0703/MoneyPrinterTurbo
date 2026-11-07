# Streamlit API reference

Use this as a quick orientation for the public top-level `st` API. The table below covers the public `st.<command>(...)` commands, common top-level objects, `st.column_config` helpers, and public namespaces exposed by the local Streamlit namespace when this reference was written.

Treat summaries as starting points, not complete usage docs. Before using unfamiliar parameters, deprecated options, return values, or command-specific edge cases, inspect the local docstring and signature.

## Inspecting local docs from the CLI

Use `streamlit docs <COMMAND>` to print the signature and docstring for a public Streamlit command from the relevant Streamlit installation:

```bash
streamlit docs st.button
```

It also supports public nested namespace members:

```bash
streamlit docs st.column_config.NumberColumn
streamlit docs st.cache_data.clear
```

For container usage, look up the same top-level command because container methods share the same public element docs:

```bash
streamlit docs st.button
# Applies to st.button(...), st.sidebar.button(...), and buttons in other containers.
```

Run this command with the Streamlit installation relevant to the code being edited. For example, use the active virtual environment, the project's package runner, or the repo's development environment so the docs match that Streamlit version. If `COMMAND` is omitted, `streamlit docs` opens the documentation website in a browser instead of printing command docs.

## Public `st` API

| API | Summary |
|-----|---------|
| **Top-level commands** | |
| `st.App` | ASGI-compatible Streamlit application. Use it for advanced server configuration, including custom routes, startup and shutdown lifecycle hooks, custom middleware, custom exception handlers, FastAPI integration, and programmatic secrets. |
| `st.Page` | Configure a page for `st.navigation` in a multipage app. It creates a page object from a Python file or callable with optional title, icon, URL path, default status, and visibility. |
| `st.altair_chart` | Display a chart using the Vega-Altair library. Use it when native charts are not expressive enough and you need Altair's encodings, layers, tooltips, or interactions. |
| `st.area_chart` | Display an area chart. Use it for common area-chart cases with Streamlit-managed rendering. |
| `st.audio` | Display an audio player. Accepts common audio data sources such as files, URLs, bytes, and arrays. |
| `st.audio_input` | Display a widget that returns an audio recording from the user's microphone. Use it when an app needs recorded audio as input. |
| `st.badge` | Display a colored badge with an icon and label. Useful for compact status, category, or metadata indicators. |
| `st.balloons` | Draw celebratory balloons. Use sparingly for success moments or lightweight feedback. |
| `st.bar_chart` | Display a bar chart. Use it for straightforward categorical or binned comparisons. |
| `st.button` | Display a button widget. It returns `True` on the script rerun triggered by a click. |
| `st.cache_data` | Cache the return value of a function. Use it for expensive computations or data-loading steps that return serializable data; each caller receives a copy of the cached value. |
| `st.cache_resource` | Cache a shared resource returned by a function. Use it for global objects such as database connections, ML models, or clients that should be reused across reruns and sessions. |
| `st.camera_input` | Display a widget that returns pictures from the user's webcam. It returns an `UploadedFile` with the captured image when the user takes a picture, and `None` before then. |
| `st.caption` | Display text in small font. Use it for secondary text, notes, or metadata beneath primary content. |
| `st.chat_input` | Display a chat input widget. It is designed for conversational apps and returns the submitted message or uploaded files depending on configuration. |
| `st.chat_message` | Insert a chat message container. Use it to render messages from users, assistants, or named speakers. |
| `st.checkbox` | Display a checkbox widget. It returns a boolean value. |
| `st.code` | Display a code block with optional syntax highlighting. Use it for source code, commands, logs, and other preformatted text. |
| `st.color_picker` | Display a color picker widget. It returns the selected color as a hex string. |
| `st.columns` | Insert containers laid out as side-by-side columns. Use it for horizontal layouts and place elements into returned column containers. |
| `st.connection` | Create or retrieve a connection to a data store or API. Use connection classes and secrets to centralize external service access. |
| `st.container` | Insert a multi-element container. Use it to group elements, control layout, or append content to a specific location. |
| `st.data_editor` | Display a data editor widget. Use it when users need to edit rows or cells and the app needs the edited data back in Python. |
| `st.dataframe` | Display a dataframe as an interactive table. Supports column configuration, selection, sizing, sorting, and efficient data exploration. |
| `st.date_input` | Display a date input widget. It can return a single date or a date range depending on the initial value. |
| `st.datetime_input` | Display a date and time input widget. Use it when users need to choose precise timestamps rather than dates alone. |
| `st.dialog` | Function decorator to create a modal dialog or a modal side drawer. Use it to isolate short workflows while preserving Streamlit's rerun model. |
| `st.divider` | Display a horizontal rule. Use it to separate sections without adding a heavy layout container. |
| `st.download_button` | Display a download button widget. Use it for generated files, reports, transformed data, or other app outputs. |
| `st.echarts_chart` | Display an interactive Apache ECharts chart. Use it for ECharts-native visualizations. |
| `st.echo` | Use in a `with` block to draw some code on the app, then execute it. Useful for tutorials, examples, and educational apps. |
| `st.empty` | Insert a single-element container. Use it as a placeholder when you need to replace, update, or clear one element later. |
| `st.error` | Display error message. Use it for failures or blocking conditions that require user attention. |
| `st.exception` | Display an exception. Use it to surface caught exceptions and traceback information during debugging or diagnostics. |
| `st.expander` | Insert a multi-element container that can be expanded/collapsed. Use it for optional details that should not dominate the main page. |
| `st.feedback` | Display a feedback widget. It supports compact user reactions such as thumbs, faces, or stars depending on configuration. |
| `st.file_uploader` | Display a file uploader widget. It returns uploaded file objects and can support multiple files and type filtering. |
| `st.form` | Create a form that batches elements together with a "Submit" button. Use it when several inputs should update the app together instead of on every widget change. Every form must contain at least one `st.form_submit_button`, otherwise it's non-functional. |
| `st.form_submit_button` | Display a form submit button. It must be used inside `st.form` and triggers the form's batched submission. A form needs at least one submit button to be functional. |
| `st.fragment` | Decorator to turn a function into a fragment which can rerun independently of the full app. Use it to reduce rerun cost for isolated interactive sections or run independent, slow sections in parallel during full app reruns. |
| `st.get_option` | Return the current value of a given Streamlit configuration option. Use it for runtime-aware behavior that depends on configured settings. |
| `st.graphviz_chart` | Display a graph using the d3-graphviz library and Graphviz WASM. Use it for directed graphs, diagrams, and node-edge visualizations. |
| `st.header` | Display text in header formatting. Use it for major sections below the page title. |
| `st.help` | Display help and other information for a given object. It renders docstrings, signatures, and related information inside the app. |
| `st.html` | Insert HTML into your app. JavaScript is ignored by default; for interactive components that exchange data with Python, use `st.components.v2.component()` instead. |
| `st.iframe` | Embed content in an iframe. Use it to show an external page or embedded resource in a bounded frame. |
| `st.image` | Display an image or list of images. Accepts paths, URLs, bytes, arrays, and image-like objects. |
| `st.info` | Display an informational message. Use it for neutral guidance, context, or non-blocking status. |
| `st.json` | Display an object or string as a pretty-printed, interactive JSON string. Use it for structured debug output or data inspection. |
| `st.latex` | Display mathematical expressions formatted as LaTeX. Use it for equations and scientific notation. |
| `st.line_chart` | Display a line chart. Use it for trends, time series, and ordered numeric values. |
| `st.link_button` | Display a link button element. Use it when the action is navigation to another URL. |
| `st.login` | Initiate the login flow for the given provider. Use it with configured auth settings and inspect the local docs for provider-specific behavior. |
| `st.logo` | Renders a logo in the upper-left corner of your app and its sidebar. Use it for app branding and optional navigation link behavior. |
| `st.logout` | Logout the current user. Use it with Streamlit's authentication support. |
| `st.map` | Display a map with a scatterplot overlaid onto it. Use it for latitude/longitude data when a simple geographic visualization is enough. |
| `st.markdown` | Display string formatted as Markdown. It supports Streamlit-specific extensions such as colored text, badges, icons, and limited HTML when enabled. |
| `st.menu_button` | Display a button that opens a short menu of one-shot actions. Like `st.button`, it returns the chosen option only on the rerun the click triggers. |
| `st.mermaid_chart` | Display a Mermaid diagram. Use it for text-based diagram definitions such as flowcharts, sequence diagrams, class diagrams, and state diagrams. |
| `st.metric` | Display a metric in big bold font, with an optional indicator of how the metric changed. Use it for KPIs, headline numbers, optional inline sparklines, and dashboard summaries. |
| `st.multiselect` | Display a multiselect widget. Use it when users can choose multiple items from a list, optionally including new options they enter. |
| `st.navigation` | Configure the available pages in a multipage app and where the navigation menu appears. It returns the currently selected page object, which the app should run. |
| `st.number_input` | Display a numeric input widget. It supports integer and floating-point values, bounds, steps, and formatting. |
| `st.page_link` | Display a link to another page in a multipage app or to an external page. Use it for explicit navigation elements. |
| `st.pagination` | Display a pagination widget for navigating through pages of content. Use it when a dataset or workflow is split across numbered pages. |
| `st.pdf` | Display a PDF viewer. Use it to render PDF files or bytes directly in the app. |
| `st.pills` | Display a pills widget. Use it for compact single- or multi-select choices with pill-shaped options. |
| `st.plotly_chart` | Display an interactive Plotly chart. Use it when Plotly is already available or chart interactions/customization require Plotly. |
| `st.popover` | Insert a popover container. Use it for compact controls or details that should appear on demand without occupying page space. |
| `st.progress` | Display a progress bar. Use it to communicate completion state for running tasks or staged workflows. |
| `st.pydeck_chart` | Draw a chart using the PyDeck library. Use it for deck.gl-powered maps and geospatial visualizations. |
| `st.pyplot` | Display a matplotlib.pyplot figure. Use it for existing Matplotlib visualizations or libraries that produce Matplotlib figures. |
| `st.radio` | Display a radio button widget. Use it when users should choose exactly one option from a small visible set. |
| `st.rerun` | Rerun the app or current fragment immediately. Use it to force a rerun after state changes or navigation-like actions. |
| `st.scatter_chart` | Display a scatterplot chart. Use it for relationships between numeric variables, optionally with size and color encodings. |
| `st.segmented_control` | Display a segmented control widget. Use it for compact mutually exclusive choices, especially mode or view switching. |
| `st.select_slider` | Display a slider widget to select items from a list. Use it when options are ordered but not necessarily numeric. |
| `st.selectbox` | Display a select widget. Use it for selecting one item from a medium or large set. |
| `st.set_option` | Set a configuration option. Use sparingly because not all options are safe or meaningful to change after startup. |
| `st.set_page_config` | Configure the default settings of the page. Prefer calling it near the top of the script; repeated calls are additive and override only the parameters you specify. |
| `st.skeleton` | Display a skeleton loading placeholder. Use it standalone (like `st.empty`) to reserve space and replace it with content later, or as a context manager (like `st.spinner`) to show a temporary placeholder while a block runs. |
| `st.slider` | Display a slider widget. Use it for numeric ranges, dates, times, or other ordered values. |
| `st.snow` | Draw celebratory snowfall. Use sparingly for lightweight success or celebration effects. |
| `st.space` | Add vertical or horizontal space. Use it for small layout adjustments instead of empty Markdown strings. |
| `st.spinner` | Display a loading spinner while executing a block of code. Use it as a context manager around work that may take noticeable time. |
| `st.status` | Insert a status container to display output from long-running tasks. Use it to show progress, intermediate output, and final state for multi-step operations. |
| `st.stop` | Stops execution immediately. Use it to halt rendering after validation failures, missing inputs, or intentional early exits. |
| `st.subheader` | Display text in subheader formatting. Use it for subsections under headers. |
| `st.success` | Display a success message. Use it for completed actions or positive status. |
| `st.switch_page` | Programmatically switch the current page in a multipage app. Use it for navigation triggered by app logic. |
| `st.table` | Display data in a static table. Use it for small, styled tables such as key-value summaries, confusion matrices, or leaderboards, including cells with supported Markdown, when users do not need interactive exploration. |
| `st.tabs` | Insert containers separated into tabs. Use tabs to switch between related views while rendering all tab content in the same run. |
| `st.text` | Write text without Markdown or HTML parsing. Use it for unformatted output. |
| `st.text_area` | Display a multi-line text input widget. Use it for comments, prompts, notes, and longer free-form input. |
| `st.text_input` | Display a single-line text input widget. Use it for short free-form input such as names, filters, IDs, or search text. |
| `st.time_input` | Display a time input widget. Use it when users need to choose a time of day. |
| `st.title` | Display text in title formatting. Use it for the main page title. |
| `st.toast` | Display a short message, known as a notification "toast". It appears in the app's top-right corner and disappears after four seconds. |
| `st.toggle` | Display a toggle widget. Use it for boolean settings that behave like on/off switches. |
| `st.vega_lite_chart` | Display a chart using the Vega-Lite library. Use it for direct Vega-Lite specifications or when you already have Vega-Lite JSON. |
| `st.video` | Display a video player. Accepts common video data sources such as files, URLs, bytes, and arrays. |
| `st.warning` | Display warning message. Use it for cautionary or recoverable conditions that need attention. |
| `st.write` | Displays arguments in the app. Use it for quick output, mixed content, and exploratory apps. |
| `st.write_stream` | Stream a generator, iterable, or stream-like sequence to the app. Use it for token streams, incremental text, or progressively produced output. |
| **Top-level objects** | |
| `st.bottom` | Bottom-pinned container for the main app area. Use it as a container object, not as a function. |
| `st.context` | Read-only access to user session context. Exposes `headers`, `cookies`, `theme` (`theme.type`), `timezone`, `timezone_offset`, `locale`, `url`, `ip_address`, and `is_embedded`. Attribute and bracket access are equivalent (`st.context.timezone` and `st.context["timezone"]`), but it is not a dict: no `.get()`, `.keys()`, or iteration. |
| `st.query_params` | Mutable mapping for the browser URL query parameters. Use it to read or update URL state; to sync a widget's value to the URL, bind the widget to query params instead. |
| `st.secrets` | Dict-like access to secrets loaded from `secrets.toml`. Use it for credentials and configuration that should not be hard-coded. |
| `st.session_state` | Per-session mutable mapping for app state. Use it to persist values across reruns and share state between widgets and app logic. |
| `st.sidebar` | Sidebar container that exposes most element methods as `st.sidebar.<command>()` and supports `with st.sidebar:` blocks. |
| `st.user` | Read-only dict-like object for current user information. Values depend on the hosting and authentication configuration. |
| **`st.column_config` helpers** | |
| `st.column_config.AreaChartColumn` | Configure an area chart column in `st.dataframe` or `st.data_editor`. Use it for compact per-row trends where filled areas are clearer than plain numbers. |
| `st.column_config.AudioColumn` | Configure an audio column in `st.dataframe` or `st.data_editor`. Use it for audio URLs, paths, or media values that users should be able to play inline. |
| `st.column_config.BarChartColumn` | Configure a bar chart column in `st.dataframe` or `st.data_editor`. Use it for compact per-row comparisons or small sequences of numeric values. |
| `st.column_config.ButtonColumn` | Configure a button column in `st.dataframe` or `st.data_editor`. Use it when each row needs an action trigger. |
| `st.column_config.CheckboxColumn` | Configure a checkbox column in `st.dataframe` or `st.data_editor`. Use it for boolean values, especially editable true/false fields. |
| `st.column_config.Column` | Configure a generic column in `st.dataframe` or `st.data_editor`. Use it for label, width, help text, visibility, disabled state, pinned state, and other shared column metadata. |
| `st.column_config.DateColumn` | Configure a date column in `st.dataframe` or `st.data_editor`. Use it for date-only display or editing with optional formatting and bounds. |
| `st.column_config.DatetimeColumn` | Configure a datetime column in `st.dataframe` or `st.data_editor`. Use it for timestamp display or editing with optional formatting, timezone-aware values, and bounds. |
| `st.column_config.ImageColumn` | Configure an image column in `st.dataframe` or `st.data_editor`. Use it for image URLs, paths, or image-like values that should display visually instead of as text. |
| `st.column_config.JsonColumn` | Configure a JSON column in `st.dataframe` or `st.data_editor`. Use it for dictionaries, lists, or JSON strings that need structured display. |
| `st.column_config.LineChartColumn` | Configure a line chart column in `st.dataframe` or `st.data_editor`. Use it for compact per-row trends without the filled area of an area chart. |
| `st.column_config.LinkColumn` | Configure a link column in `st.dataframe` or `st.data_editor`. Use it for URLs, optionally with validation and display text behavior. |
| `st.column_config.ListColumn` | Configure a list column in `st.dataframe` or `st.data_editor`. Use it for arrays or repeated values that should render as structured list content. |
| `st.column_config.MarkdownColumn` | Configure a markdown column in `st.dataframe` or `st.data_editor`. Cells show plain text, and clicking a cell opens an overlay that renders the Markdown. |
| `st.column_config.MultiselectColumn` | Configure a multiselect column in `st.dataframe` or `st.data_editor`. Use it when each row can contain multiple choices from a known set. |
| `st.column_config.NumberColumn` | Configure a number column in `st.dataframe` or `st.data_editor`. Use it for integers, floats, currencies, percentages, min/max bounds, step sizes, and numeric formatting. |
| `st.column_config.ProgressColumn` | Configure a progress column in `st.dataframe` or `st.data_editor`. Use it for percentages, completion values, scores, or bounded progress-like quantities. |
| `st.column_config.SelectboxColumn` | Configure a selectbox column in `st.dataframe` or `st.data_editor`. Use it when each row should choose exactly one option from a known set. |
| `st.column_config.TextColumn` | Configure a text column in `st.dataframe` or `st.data_editor`. Use it for strings with optional validation, length bounds, and text-specific display or editing behavior. |
| `st.column_config.TimeColumn` | Configure a time column in `st.dataframe` or `st.data_editor`. Use it for time-of-day display or editing with optional formatting and bounds. |
| `st.column_config.VideoColumn` | Configure a video column in `st.dataframe` or `st.data_editor`. Use it for video URLs, paths, or media values that users should be able to play inline. |
| **Public namespaces** | |
| `st.column_config` | Namespace of column configuration helpers for `st.dataframe` and `st.data_editor`. See the `st.column_config` helper rows above and inspect helpers such as `st.column_config.NumberColumn` for exact parameters. |
| `st.components` | Namespace for custom components. Prefer `st.components.v2.component()` for new HTML/JS components; `st.components.v1` is deprecated for new work. |
| `st.typing` | Curated namespace of public Streamlit-owned types for annotations. Prefer imports from `streamlit.typing` over internal implementation modules. |

## Public annotation types

Import Streamlit-owned return and state types from `streamlit.typing`, not from modules under `streamlit.elements` or `streamlit.runtime`:

```python
from streamlit.typing import DataframeState, UploadedFile
```

| Type | Produced by |
|------|-------------|
| `UploadedFile` | `st.file_uploader`, `st.camera_input`, `st.audio_input`, and file/audio fields from `st.chat_input` |
| `ChatInputValue` | `st.chat_input` when file or audio input is enabled |
| `DataframeState` | `st.dataframe` when selection events are enabled |
| `PlotlyState` | `st.plotly_chart` when selection events are enabled |
| `VegaLiteState` | `st.altair_chart` and `st.vega_lite_chart` when selection events are enabled |
| `PydeckState` | `st.pydeck_chart` when selection events are enabled |
| `DataEditorState` | Session State for a keyed `st.data_editor` |
| `ButtonColumnClickState` | Session State for a keyed `st.column_config.ButtonColumn` click |

These are the runtime classes returned by Streamlit, so they work in annotations and `isinstance` checks. Obtain their values from the corresponding command or Session State entry instead of constructing them directly.
