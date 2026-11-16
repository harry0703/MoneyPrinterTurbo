# Streamlit charts & data

Present data clearly.

## Contents

- [Accessible names (alt)](#accessible-names-alt)
- [Native charts first](#native-charts-first)
- [Human-readable labels](#human-readable-labels)
- [Altair for complex charts](#altair-for-complex-charts)
- [Apache ECharts](#apache-echarts)
- [Deprecated: use_container_width](#deprecated-use_container_width)
- [Dataframe column configuration](#dataframe-column-configuration)
- [Markdown in dataframe cells](#markdown-in-dataframe-cells)
- [Colored badges with MultiselectColumn](#colored-badges-with-multiselectcolumn)
- [Row actions with ButtonColumn](#row-actions-with-buttoncolumn)
- [Choosing the right data widget](#choosing-the-right-data-widget)
- [Description and key-value lists](#description-and-key-value-lists)
- [Pandas Styler: formatting vs coloring](#pandas-styler-formatting-vs-coloring)
- [Editing data with st.data_editor](#editing-data-with-stdata_editor)
- [Row, column and cell selections](#row-column-and-cell-selections)
- [Empty DataFrames](#empty-dataframes)
- [Pinned columns](#pinned-columns)
- [Sparklines in metrics](#sparklines-in-metrics)
- [References](#references)

## Accessible names (`alt`)

Pass keyword-only `alt=` on charts, maps, tables, and grids so assistive technologies can name them. Write a short, plain-text accessible name (about one sentence); Markdown syntax is announced literally. Prefer the chart's takeaway, the map's subject, or the table's purpose — not a data dump and not a paste of the dataframe.

```python
st.bar_chart(
    df, x="category", y="revenue", alt="Revenue by product line, highest for Enterprise"
)
st.dataframe(df, alt="Top 20 customers by revenue")
st.table(summary, alt="Quarterly KPI summary")
```

- Charts and maps (`st.line_chart`, `st.bar_chart`, `st.area_chart`, `st.scatter_chart`, `st.altair_chart`, `st.vega_lite_chart`, `st.plotly_chart`, `st.graphviz_chart`, `st.map`, `st.pydeck_chart`, `st.mermaid_chart`): describe the chart's takeaway or the map's subject, not the chart type or a data dump.
- **`st.echarts_chart`:** `alt` replaces the description ECharts generates from the data, so a vague name is worse than passing none.
- **`st.dataframe` / `st.data_editor` / `st.table`:** name the grid or table; do not paste cell values into `alt`.
- A whitespace-only `alt` is ignored (same as not passing `alt`) and logged on every command. Empty `alt=""` is decorative only on `st.image` / `st.pyplot` (see [media-display.md](media-display.md)).

## Native charts first

Prefer Streamlit's native charts for simple cases.

```python
st.line_chart(df, x="date", y="revenue", alt="Monthly revenue trend")
st.bar_chart(df, x="category", y="count", alt="Order count by category")
st.scatter_chart(df, x="age", y="salary", alt="Salary versus age")
st.area_chart(df, x="date", y="value", alt="Value over time")
```

Native charts support additional parameters: `color` for series grouping, `stack` for bar/area stacking, `size` for scatter point sizing, `horizontal` for horizontal bars. See the [chart API reference](https://docs.streamlit.io/develop/api-reference/charts) for full options.

## Human-readable labels

Use clear labels—not column names or abbreviations. Skip `x_label`/`y_label` if the column names are already readable.

```python
# BAD: cryptic column names without labels
st.line_chart(df, x="dt", y="rev")

# GOOD: readable columns, no labels needed
st.line_chart(df, x="date", y="revenue", alt="Monthly revenue trend")

# GOOD: cryptic columns, add labels
st.line_chart(
    df, x="dt", y="rev", x_label="Date", y_label="Revenue", alt="Monthly revenue trend"
)
```

## Altair for complex charts

Use Altair when you need more control. Altair is bundled with Streamlit (no extra install), while Plotly requires an additional package. Pick one and stay consistent throughout your app.

```python
import altair as alt

chart = (
    alt.Chart(df)
    .mark_line()
    .encode(
        x=alt.X("date:T", title="Date"),
        y=alt.Y("revenue:Q", title="Revenue ($)"),
        color="region:N",
    )
)
st.altair_chart(chart, alt="Revenue by region over time")
```

**When to use Altair:**

- Custom axis formatting
- Multiple series with legends
- Interactive tooltips
- Layered visualizations

## Apache ECharts

Use `st.echarts_chart` when you already have an Apache ECharts option dict, a JSON string, or a `pyecharts` chart. Don't add a third-party ECharts component for this. Prefer Vega-based charts unless the spec is already ECharts-native.

Pass JSON-compatible options only. JavaScript callbacks (`formatter` functions, `JsCode`, `custom` series), GeoJSON map registration, and ECharts GL / 3D charts are not supported.

```python
st.echarts_chart(
    {
        "xAxis": {"type": "category", "data": ["Mon", "Tue", "Wed"]},
        "yAxis": {"type": "value"},
        "series": [{"type": "bar", "data": [120, 200, 150]}],
    },
    alt="Weekday traffic, peak on Tuesday",
)
```

## Deprecated: `use_container_width`

**Do not use `use_container_width`.** It is deprecated. Dataframes and most charts stretch to fill their container by default. Use the `width` parameter instead: `width="stretch"` (equivalent to `use_container_width=True`) or `width="content"` (equivalent to `use_container_width=False`). Remove `use_container_width` when you see it, and never add it to new code.

```python
# BAD: deprecated parameter
st.dataframe(df, use_container_width=True)
st.altair_chart(chart, use_container_width=True)

# GOOD: just omit it — stretch is the default
st.dataframe(df)
st.altair_chart(chart)

# GOOD: explicitly set width when you need content-sized (non-stretching)
st.dataframe(df, width="content")
```

## Dataframe column configuration

Use `column_config` where it adds value—formatting currencies, showing progress bars, displaying links or images. Don't add config just for labels or tooltips that don't meaningfully improve readability. Works with both `st.dataframe` and `st.data_editor`.

Before configuring a column, proactively inspect the relevant column type's current docstring with `streamlit docs <command>` (for example, `streamlit docs st.column_config.NumberColumn`) to confirm its parameters, supported formats, and behavior.

```python
st.dataframe(
    df,
    column_config={
        "revenue": st.column_config.NumberColumn("Revenue", format="$%.2f"),
        "completion": st.column_config.ProgressColumn(
            "Progress", min_value=0, max_value=100
        ),
        "url": st.column_config.LinkColumn("Website"),
        "logo": st.column_config.ImageColumn("Logo"),
        "created_at": st.column_config.DatetimeColumn("Created", format="MMM DD, YYYY"),
        "internal_id": None,  # Hide non-essential columns
    },
    hide_index=True,
)
```

**Note on hiding columns:** Setting a column to `None` hides it from the UI, but the data is still sent to the frontend. For truly sensitive data, pre-filter the DataFrame before displaying.

**Dataframe best practices:**

- **Hide useless index:** `hide_index=True`
- **Or make index meaningful:** `df = df.set_index("customer_name")` before displaying
- **Hide internal/technical columns:** Set column to `None` in config (but pre-filter for sensitive data)
- **Use visual column types where they help:** sparklines for trends, progress bars for completion, images for logos

**Column types:**

- `AreaChartColumn` → Area sparklines
- `AudioColumn` → Audio playback
- `BarChartColumn` → Bar sparklines
- `ButtonColumn` → Clickable buttons that trigger callbacks
- `CheckboxColumn` → Boolean as checkbox
- `DateColumn` → Date only (no time)
- `DatetimeColumn` → Dates with formatting
- `ImageColumn` → Images
- `JsonColumn` → Display JSON objects
- `LineChartColumn` → Sparkline charts
- `LinkColumn` → Clickable links
- `ListColumn` → Display lists/arrays
- `MarkdownColumn` → Raw Markdown text with a rendered detail overlay
- `MultiselectColumn` → Multi-value selection or colored badges in read-only dataframes
- `NumberColumn` → Numbers with formatting
- `ProgressColumn` → Progress bars
- `SelectboxColumn` → Editable dropdown
- `TextColumn` → Text with formatting
- `TimeColumn` → Time only (no date)
- `VideoColumn` → Video playback

## Markdown in dataframe cells

Unlike `st.table`, `st.dataframe` and `st.data_editor` cannot render Markdown directly inside cells. Use `st.table` when a small, static table needs visible Markdown formatting in its cells, index labels, or headers.

`MarkdownColumn` does not change the inline cell rendering: the cell still shows the raw Markdown source string. When a user clicks the cell, a detail overlay opens and renders the Markdown. Use `MarkdownColumn` only when showing the raw source in the table and the rendered content on demand is acceptable.

## Colored badges with MultiselectColumn

Use `MultiselectColumn` in a read-only `st.dataframe` to render list values as compact colored badges. This works well for categories, tags, roles, and statuses. Use `color="auto"` for theme-aware categorical colors, a single color for all badges, or a list of colors mapped to `options`.

```python
df = pd.DataFrame(
    {
        "project": ["Atlas", "Beacon", "Comet"],
        "tags": [["Python", "Data"], ["Frontend"], ["Python", "AI"]],
    }
)

st.dataframe(
    df,
    column_config={
        "tags": st.column_config.MultiselectColumn(
            "Tags",
            options=["Python", "Data", "Frontend", "AI"],
            color="auto",
        ),
    },
    hide_index=True,
)
```

## Row actions with ButtonColumn

Use `ButtonColumn` for clickable, per-row actions in `st.dataframe` or `st.data_editor`. The cell value is the button label (supports `:material/...:` icons). A cell holding a **list** renders a dropdown menu of multiple actions.

Prefer `ButtonColumn` over `st.dataframe` row selection when a click should trigger a one-off action for a specific row, such as opening a dialog, showing details, or running an operation. Button clicks are transient and reset after the click-triggered rerun. Row selection represents ongoing state and persists across reruns until the selection is changed or cleared, so reserve it for cases where the app needs to keep track of selected rows.

```python
df = pd.DataFrame(
    {
        "name": ["Alice", "Bob"],
        "actions": [
            [":material/edit: Edit", ":material/delete: Delete"],
            [":material/edit: Edit"],
        ],
    }
)


def handle_action():
    click = st.session_state.row_action  # dict-like: click.row, click.label
    st.toast(f"{click.label} on row {click.row}")


st.dataframe(
    df,
    column_config={
        "actions": st.column_config.ButtonColumn(
            "Actions", on_click=handle_action, key="row_action"
        ),
    },
)
```

**Key points:**

- **`key` is required** to enable clicks/callbacks. Click info lives in `st.session_state[key]` as a dict-like object with `row` and `label` attributes (also supports key access) — only during the click rerun, then resets to `None`.
- Import `ButtonColumnClickState` from `streamlit.typing` when annotating this click value.
- Use `on_click` (with optional `args`/`kwargs`) for the action; read the clicked row/label inside the callback.
- Always **read-only** — even in `st.data_editor`, the cell values can't be edited, but clicks still fire.
- Style with `type="primary" | "secondary" | "tertiary"` and `alignment`.

## Choosing the right data widget

| Widget           | Use When                                                                      |
| ---------------- | ----------------------------------------------------------------------------- |
| `st.dataframe`   | Large datasets, interactive exploration, sorting, filtering, row selection    |
| `st.data_editor` | Users need to modify data (edit cells, add/delete rows)                       |
| `st.table`       | Small static tables and key-value lists; Markdown and extended Pandas Styler support |

Use `st.dataframe` with `on_select` for row selection — do **not** use `st.data_editor` with a checkbox column for selection-only use cases.

## Description and key-value lists

`st.table` is a great fit for description lists and compact key-value summaries. Pass a mapping of keys to **scalar** values: keys become the row index (shown by default), and Streamlit auto-hides the generated `value` header. A dict of lists is treated as a columnar table instead (headers shown).

Use `border="horizontal"` and `width="content"` for a compact list. Leave `hide_index` and `hide_header` unset unless you need to override the auto-show-keys and auto-hide-header behavior.

```python
st.table(
    {
        ":material/folder: Project": "**Streamlit** - The fastest way to build data apps",
        ":material/code: Repository": "[github.com/streamlit/streamlit](https://github.com/streamlit/streamlit)",
        ":material/license: License": ":green-badge[Apache 2.0]",
    },
    border="horizontal",
    width="content",
)
```

## Pandas Styler: formatting vs coloring

For `st.dataframe` and `st.data_editor`, use `column_config` for **all value formatting** (numbers, dates, percentages). With these commands, only use Pandas Styler for **coloring** (background gradients, highlights).

`st.table` does not have a `column_config` parameter. For small, static tables, pass a Pandas Styler to `st.table` for more extensive formatting and styling.

```python
# BAD: Styler for formatting with st.dataframe — AI tends to overuse this
styled = df.style.format({"revenue": "${:.2f}", "growth": "{:.1%}"})
st.dataframe(styled)

# GOOD: column_config for formatting with st.dataframe
st.dataframe(
    df,
    column_config={
        "revenue": st.column_config.NumberColumn(format="$%.2f"),
        "growth": st.column_config.NumberColumn(format="percent"),
        "created": st.column_config.DatetimeColumn(format="MMM DD, YYYY"),
    },
)

# GOOD: Styler for colors only + column_config for formatting
styled = df.style.background_gradient(subset=["revenue"], cmap="Greens")
st.dataframe(
    styled,
    column_config={
        "revenue": st.column_config.NumberColumn(format="$%.2f"),
    },
)
```

**Percentage formatting:** Use `NumberColumn(format="percent")` for 0-1 values, or `format="%.2f%%"` for already-multiplied values.

## Editing data with st.data_editor

```python
edited_df = st.data_editor(
    df,
    key="my_editor",
    num_rows="dynamic",  # allow adding/deleting rows
    disabled=["id", "created"],  # lock specific columns
)
```

Access edit details via `st.session_state["my_editor"]["edited_rows"]`.

Import `DataEditorState` from `streamlit.typing` when annotating the pending edit state stored at this Session State key.

**Preserving edits on data refresh** — With a `key` and `num_rows="fixed"`, edits are kept when the data's *values* change and only reset when its structure changes (columns, dtypes, row count, or index labels). An edit is dropped once its value matches the new data. Edits are matched by row position, so use a meaningful index if edits should follow specific rows when the data is reordered. Omit `key` to reset edits on every data change.

**Double-input anti-pattern** — assigning the result back to the same session state used as input causes every other edit to disappear:

```python
# BAD: creates feedback loop — edits disappear on every other interaction
st.session_state.df = st.data_editor(st.session_state.df)
st.session_state.df["total"] = st.session_state.df["qty"] * st.session_state.df["price"]

# GOOD: use key parameter, compute from the returned value
edited = st.data_editor(df, key="editor")
edited["total"] = edited["qty"] * edited["price"]
st.dataframe(edited)
```

## Row, column and cell selections

Use `st.dataframe` (not `st.data_editor`) for selection:

```python
event = st.dataframe(df, on_select="rerun", selection_mode="multi-row")
selected_indices = event.selection.rows
selected_data = df.iloc[selected_indices]
```

Selection modes: `"single-row"`, `"multi-row"`, `"single-column"`, `"multi-column"`, `"single-cell"`, `"multi-cell"`.

Import `DataframeState` from `streamlit.typing` when annotating the returned event. The same public namespace exposes `PlotlyState`, `VegaLiteState`, and `PydeckState` for selection events from `st.plotly_chart`, `st.altair_chart`/`st.vega_lite_chart`, and `st.pydeck_chart`, respectively. Do not import these types from Streamlit's internal modules.

## Empty DataFrames

When creating an empty DataFrame for `st.data_editor`, set explicit dtypes to avoid type inference issues:

```python
df = pd.DataFrame(
    {
        "label": pd.Series(dtype="string"),
        "amount": pd.Series(dtype="float"),
    }
)
st.data_editor(df)
```

## Pinned columns

Keep important columns visible while scrolling horizontally:

```python
st.dataframe(
    df,
    column_config={
        "Title": st.column_config.TextColumn(pinned=True),  # Always visible
        "Rating": st.column_config.ProgressColumn(min_value=0, max_value=10),
    },
    hide_index=True,
)
```

## Sparklines in metrics

Add `chart_data` and `chart_type` to metrics for visual context.

```python
values = [700, 720, 715, 740, 762, 755, 780]

st.metric(
    label="Developers",
    value="762k",
    delta="-7.42% (MoM)",
    delta_color="inverse",
    chart_data=values,
    chart_type="line",  # or "bar" or "area"
)
```

**Zero deltas:** Streamlit treats numeric zeros and the string `"0"` as zero. It does not parse other string deltas as numbers to choose the arrow and color, so `"0%"` gets a green up-arrow. For a flat period, pass the number `0` as `delta` and put the qualifier text in `delta_description`.

**Note:** Sparklines only show y-values and ignore x-axis spacing. Use them for evenly-spaced data (like daily or weekly snapshots). For irregularly-spaced time series, use a proper chart instead.

See `dashboards.md` for composing metrics into dashboard layouts.

## References

- [st.dataframe](https://docs.streamlit.io/develop/api-reference/data/st.dataframe)
- [st.table](https://docs.streamlit.io/develop/api-reference/data/st.table)
- [st.column_config](https://docs.streamlit.io/develop/api-reference/data/st.column_config)
- [st.metric](https://docs.streamlit.io/develop/api-reference/data/st.metric)
- [st.line_chart](https://docs.streamlit.io/develop/api-reference/charts/st.line_chart)
- [st.bar_chart](https://docs.streamlit.io/develop/api-reference/charts/st.bar_chart)
- [st.altair_chart](https://docs.streamlit.io/develop/api-reference/charts/st.altair_chart)
- [st.echarts_chart](https://docs.streamlit.io/develop/api-reference/charts/st.echarts_chart)
