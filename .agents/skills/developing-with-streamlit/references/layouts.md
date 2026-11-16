# Streamlit layout

How you structure your app affects usability more than you think.

## Layout container overview

| Container         | Use when                                                                                                                                                                                                                                                                                    |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `st.container`    | You need a general-purpose group of elements, a bordered section, a horizontal row, custom alignment, fixed height, scrolling, or out-of-order insertion of multiple elements.                                                                                                              |
| `st.columns`      | You need a simple proportional grid, such as two-column comparisons or up to four KPI cards.                                                                                                                                                                                                |
| `st.sidebar`      | You need app-level navigation, global filters, settings, or small app metadata that should stay separate from the main content.                                                                                                                                                             |
| `st.tabs`         | You need multiple peer views of related content, and users should switch between them without leaving the page. All tab content is computed by default; for lazy execution where only the selected tab runs, use `on_change="rerun"` (or a callable) or `bind="query-params"` (with `key`), then check each tab's `.open` property. |
| `st.expander`     | You need optional details, advanced settings, explanations, or diagnostic output that should not dominate the main view.                                                                                                                                                                    |
| `st.status`       | You need to show progress, logs, or multi-step work in a collapsible status block that can update from running to complete or error.                                                                                                                                                        |
| `st.popover`      | You need compact on-demand controls or filters without changing page layout. For a button that opens a short list of one-shot actions, use `st.menu_button` instead.                                                                                                                        |
| `@st.dialog`      | You need a focused modal flow (dialog or side drawer), such as confirmation, short editing, details, or settings that should temporarily interrupt the main page.                                                                                                                            |
| `st.form`         | You need to batch multiple widget inputs and rerun only when the user submits.                                                                                                                                                                                                              |
| `st.empty`        | You need a placeholder that can be filled, replaced, or cleared later, including inserting elements out of order.                                                                                                                                                                           |
| `st.skeleton`     | You need an animated loading placeholder that reserves space while content loads. Use it standalone like `st.empty` (replace it with content later) or as a context manager like `st.spinner` (auto-clears when the block exits).                                                           |
| `st.chat_message` | You need a message container with chat-specific styling and avatars. See `chat-ui.md` for chat interface patterns.                                                                                                                                                                          |
| `st.bottom`       | You need content pinned to the bottom of the main app area, commonly persistent chat input or bottom action controls.                                                                                                                                                                       |
| `st.space`        | You need explicit vertical or horizontal spacing inside the current layout direction.                                                                                                                                                                                                       |

## Sidebar: navigation + global filters only

The sidebar should only contain navigation and app-level filters. Main content goes in the main area.

```python
# GOOD
with st.sidebar:
    date_range = st.date_input("Date range")
    region = st.selectbox("Region", ["All", "US", "EU", "APAC"])
    st.caption("App v1.2.3")
```

```python
# BAD: Too much content in sidebar
with st.sidebar:
    st.title("Dashboard")
    st.dataframe(df)  # Don't put main content here
    st.bar_chart(data)
```

**What goes in sidebar:**

- Global filters (date range, user selection, region)
- App info (version, feedback link)

**What stays out:**

- Main content, charts, tables, results

## Columns: max 4, set alignment

Don't use too many columns for content layouts—they get cramped. By default
(`wrap=True`), columns stack vertically when the viewport is at most `640px`
wide. Pass `wrap=False` to keep columns in one row: they shrink to a usable
minimum width, then the column group scrolls horizontally instead of stacking.

```python
# GOOD
col1, col2 = st.columns(2)

# OK: Bottom-align to line up buttons with labeled inputs
cols = st.columns(4, vertical_alignment="bottom")

# OK: Compact grid that must stay in one row (e.g. thumbnails)
thumbnail_columns = st.columns(6, gap="xsmall", wrap=False)

# BAD: Too many content columns (cramped on desktop, awkward when stacked)
col1, col2, col3, col4, col5, col6 = st.columns(6)
```

Controls placed directly in a column use the default `wrap=None`, which
Streamlit resolves to no-wrap: labels ellipsize and option groups stay on one
row (`st.button`, `st.pills`, `st.multiselect`, `st.checkbox`, and similar).
Nested layout containers such as a vertical `st.container`, expander, tab, or
form reset this, so inner controls wrap as usual. Pass `wrap=True` on a control
to wrap even in a column.

## Horizontal containers for button groups

Use `st.container(horizontal=True)` instead of columns for button groups.
Buttons and similar controls inside a horizontal container also stay on one
row by default (the same auto `wrap` as direct column children). Pass
`wrap=False` on the container to keep its child elements in one scrollable
row instead of wrapping onto additional rows:

```python
with st.container(horizontal=True):
    st.button("Cancel")
    st.button("Save")
    st.button("Submit")

# Toolbar that must stay on one row
with st.container(horizontal=True, wrap=False):
    st.button("Edit")
    st.button("Duplicate")
    st.button("Archive")
    st.button("Delete")
```

## Aligning elements

Use `horizontal_alignment` on containers to position elements:

```python
# Center elements
with st.container(horizontal_alignment="center"):
    st.image("logo.png", width=200)
    st.title("Welcome")

# Right-align elements
with st.container(horizontal_alignment="right"):
    st.button("Settings", icon=":material/settings:")

# Distribute evenly (great for button groups)
with st.container(horizontal=True, horizontal_alignment="distribute"):
    st.button("Cancel")
    st.button("Save")
    st.button("Submit")
```

Options: `"left"` (default), `"center"`, `"right"`, `"distribute"`

## Aligning elements side by side

Rows look off when neighboring elements have different heights. Know the default sizes, then align the row deliberately.

**Default heights:**

- Buttons (`st.button`, `st.download_button`, `st.link_button`, `st.popover`, `st.menu_button`) and unlabeled input fields share one height.
- A visible label adds the same extra height to every input field (`st.text_input`, `st.number_input`, `st.selectbox`, `st.multiselect`, date and time inputs, `st.color_picker`, sliders). `label_visibility="hidden"` keeps that space; `"collapsed"` removes it.
- Shorter: `st.checkbox`, `st.toggle`, and `st.feedback`. `st.pills` and `st.segmented_control` are slightly shorter than input fields.
- Taller: `st.file_uploader` and `st.audio_input` share one height (the uploader grows in narrow columns). `st.text_area` defaults to three lines; at its minimum `height` with a collapsed label, it matches them.
- `st.metric` grows with `delta`, and grows more with `chart_data`.

**Widget rows:**

- For labeled inputs next to buttons, checkboxes, or toggles, use `vertical_alignment="bottom"` on `st.columns` or a horizontal container. Checkboxes and toggles are then centered on the input field. `"center"` centers each element or column, label included, so the controls don't line up.
- For toolbars, collapse the input labels and use `st.container(horizontal=True, vertical_alignment="center")`.
- If a column has content below its input, such as a caption, top-align instead: put `st.space("small")` above the neighboring button or unlabeled widget. With the default gap, it takes up exactly a label's height. `st.space` only adds vertical space in vertical layouts like columns.

```python
# Labeled inputs, a toggle, and a button on one line
with st.container(horizontal=True, vertical_alignment="bottom"):
    st.text_input("Customer")
    st.selectbox("Region", regions)
    st.toggle("Active only")
    st.button("Search", type="primary")

# Toolbar with collapsed labels
with st.container(horizontal=True, vertical_alignment="center"):
    st.text_input("Search", label_visibility="collapsed", placeholder="Search")
    st.segmented_control("View", ["Table", "Chart"], label_visibility="collapsed")
    st.toggle("Live")
    st.button("Export", icon=":material/download:")

# Top-align a button with a labeled input that has a caption below
key_col, button_col = st.columns(2)
with key_col:
    st.text_input("API key", type="password")
    st.caption("Find your key in the account settings.")
with button_col:
    st.space("small")
    st.button("Connect")
```

**Equal-height cards:**

Sibling cards with different content (for example, one `st.metric` without `delta` or `chart_data`) end up with uneven heights.

- Prefer consistent cards: give all sibling metrics a `delta` and `chart_data`, or none, and use the same header elements in every card.
- When content must differ, pass `height="stretch"` to each metric or bordered container so it matches the tallest card in its row. `st.columns(n, border=True)` also gives equal-height bordered columns.
- In horizontal containers, a metric's width depends on its content, so metrics with different parts get uneven widths. Use `st.columns` when cards should share a width.
- Pin a card's trailing button to the bottom with `st.space("stretch")`.

```python
# Equal-height KPI cards with mixed content
revenue_col, users_col, orders_col = st.columns(3)
revenue_col.metric(
    "Revenue", "$1.2M", "+8%", chart_data=revenue_trend, border=True, height="stretch"
)
users_col.metric(
    "Users", "762k", "+12%", chart_data=user_trend, border=True, height="stretch"
)
orders_col.metric("Orders", "1.4k", border=True, height="stretch")

# Equal-height cards with buttons pinned to the bottom
for col, (plan, features) in zip(st.columns(3), plans.items()):
    with col.container(border=True, height="stretch"):
        st.subheader(plan)
        for feature in features:
            st.markdown(f":material/check: {feature}")
        st.space("stretch")
        st.button("Choose", key=f"choose_{plan}", width="stretch")
```

## Bordered containers

Use `border=True` on containers for visual grouping. See `dashboards.md` for dashboard-specific patterns like KPI cards.

```python
with st.container(border=True):
    st.subheader("Section title")
    st.write("Grouped content here")
```

## Placeholders with st.empty or st.skeleton

Use a placeholder when you need to reserve a slot and fill it later, replace one element with another, clear an element, or insert content out of order. Both return a single-element container; to replace a group of elements, put a child `st.container()` inside the placeholder.

- `st.empty()` — a blank slot that shows nothing until you fill it.
- `st.skeleton()` — an animated loading placeholder that reserves space and signals that content is loading.

### st.empty

```python
dataframe_slot = st.empty()

rows_per_page = 25
num_pages = max(1, (len(df) + rows_per_page - 1) // rows_per_page)

with st.container(horizontal_alignment="right"):
    page = st.pagination(num_pages, key="results_page")

start = (page - 1) * rows_per_page
end = start + rows_per_page
dataframe_slot.dataframe(df.iloc[start:end], width="stretch")
```

This is useful when a control should appear below an element but the control's value is needed before that element renders, such as pagination below a dataframe. It also works for progress updates, temporary status messages, wizard-like flows, and cases where later code needs to render above content that has already been written. For persistent multi-element sections that do not need replacement, use `st.container()` instead.

### st.skeleton

`st.skeleton()` works like `st.empty()` but shows an animated loading placeholder. It can be used in two modes.

Standalone (like `st.empty`): the skeleton appears immediately and is replaced when you call a method on the returned placeholder.

```python
placeholder = st.skeleton(height=200)
data = load_data()  # Expensive work
placeholder.dataframe(data)  # Replaces the skeleton with content
```

Context manager (like `st.spinner`, **recommended**): the skeleton appears while the `with` block runs (after a short delay) and clears automatically when the block exits. Any `st.*` calls inside the block render in the parent container and remain visible after the skeleton clears.

```python
with st.skeleton(height=200):
    data = expensive_operation()
st.success("Data loaded!")
```

Prefer context manager mode; use standalone mode only when you need to reserve a slot and fill it later (like `st.empty`).

By default (`height=None`), the skeleton uses the standard element height. Pass an integer for a fixed pixel height, or `"stretch"` to fill a parent container with a bounded height.

## Dialogs for focused interactions

Use `@st.dialog` for UI that doesn't need to be always visible:

```python
@st.dialog("Confirm deletion")
def confirm_delete(item_name):
    st.write(f"Are you sure you want to delete **{item_name}**?")
    if st.button("Delete", type="primary"):
        delete_item(item_name)
        st.rerun()


if st.button("Delete item"):
    confirm_delete("My Document")
```

`position="left"` / `"right"` shows the dialog as a user-resizable full-height modal side drawer. Dismissal and other parameters work the same way.

**When to use dialogs:**

- Confirmation prompts
- Settings panels
- Forms that don't need to be always visible
- Drill-down into details (for example, a `ButtonColumn` click that opens a side drawer to inspect that row)

## Spacing

Control spacing between elements with `gap` on containers:

```python
# Remove spacing for tight list-like UIs
with st.container(gap=None, border=True):
    for item in items:
        st.checkbox(item.text)

# Explicit gap sizes
with st.container(gap="small"):
    ...
```

Add vertical space with `st.space`:

```python
st.space("small")  # Small gap
st.space("medium")  # Medium gap
st.space("large")  # Large gap
st.space(50)  # Custom pixels
```

## Width and height

Control element sizing (for equal-height cards, see "Aligning elements side by side" above):

```python
# Shrink to content size
st.container(width="content")

# Fixed pixel sizes
st.container(height=300)
```

## References

- [Using layouts and containers](https://docs.streamlit.io/develop/concepts/design/layouts-and-containers)
- [st.container](https://docs.streamlit.io/develop/api-reference/layout/st.container)
- [st.columns](https://docs.streamlit.io/develop/api-reference/layout/st.columns)
- [st.sidebar](https://docs.streamlit.io/develop/api-reference/layout/st.sidebar)
- [st.tabs](https://docs.streamlit.io/develop/api-reference/layout/st.tabs)
- [st.expander](https://docs.streamlit.io/develop/api-reference/layout/st.expander)
- [st.status](https://docs.streamlit.io/develop/api-reference/status/st.status)
- [st.popover](https://docs.streamlit.io/develop/api-reference/layout/st.popover)
- [st.dialog](https://docs.streamlit.io/develop/api-reference/execution-flow/st.dialog)
- [st.form](https://docs.streamlit.io/develop/api-reference/execution-flow/st.form)
- [st.empty](https://docs.streamlit.io/develop/api-reference/layout/st.empty)
- [Insert elements out of order](https://docs.streamlit.io/knowledge-base/using-streamlit/insert-elements-out-of-order)
- [st.chat_message](https://docs.streamlit.io/develop/api-reference/chat/st.chat_message)
- [Chat UI reference](chat-ui.md)
- [st.bottom](https://docs.streamlit.io/develop/api-reference/layout/st.bottom)
- [st.space](https://docs.streamlit.io/develop/api-reference/layout/st.space)
