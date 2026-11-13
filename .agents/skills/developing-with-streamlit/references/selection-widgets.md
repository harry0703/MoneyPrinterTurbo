
# Streamlit selection widgets

The right selection widget for the job. Streamlit has evolved—many old patterns are now anti-patterns.

## When to use what

Use `st.segmented_control` or `st.pills` when you want all options visible at once. Use `st.selectbox` or `st.multiselect` when options should be hidden in a dropdown.

| Widget | Best For |
|--------|----------|
| `st.segmented_control` | 2-5 options, single select, all visible |
| `st.pills` | 2-5 options, multi-select, all visible |
| `st.selectbox` | Many options, single select, dropdown |
| `st.multiselect` | Many options, multi-select, dropdown |
| `st.feedback` | Ratings: thumbs up/down, faces, or stars |

For thousands of values, see [High-cardinality options](#high-cardinality-options).

## Segmented control (options visible, single select)

```python
# BAD
status = st.radio("Status", ["Draft", "Published"], horizontal=True)

# GOOD
status = st.segmented_control("Status", ["Draft", "Published"])
```

For vertical layouts, `st.radio(..., horizontal=False)` is still a great choice.

Cleaner, more modern look than horizontal radio buttons.

## Pills (options visible, multi-select)

```python
# Multi-select with few options
selected = st.pills(
    "Tags", ["Python", "SQL", "dbt", "Streamlit"], selection_mode="multi"
)
```

Can also be used to mimic an "example" widget, especially with `label_visibility="collapsed"`:
```python
st.pills(
    "Examples", ["Show me sales data", "Top customers"], label_visibility="collapsed"
)
```

More visual and easier to use than `st.multiselect` for small option sets.

## Selectbox (many options, single select)

```python
country = st.selectbox(
    "Select a country", ["USA", "UK", "Canada", "Germany", "France", ...]
)
```

Dropdowns scale better than radio/pills for long lists, but the whole option list still travels to the browser. Past a few thousand values, see [High-cardinality options](#high-cardinality-options).

## Multiselect (many options, multi-select)

```python
countries = st.multiselect(
    "Select countries", ["USA", "UK", "Canada", "Germany", "France", ...]
)
```

## Feedback (ratings)

Use `st.feedback` for thumbs, faces, or star ratings instead of building one from buttons or `st.segmented_control`. It returns an integer while an option is selected (including a `default` before any click) and `None` otherwise. Higher is more positive:

- `"thumbs"`: `1` is thumbs-up and `0` is thumbs-down, even though thumbs-up is shown first.
- `"faces"`: `0` (least satisfied) through `4` (most satisfied).
- `"stars"`: `0` through `4`. The displayed star count is the value plus one.

Check `rating is not None`, not `if rating`: `0` is a real selection, so a truthiness check skips it.

```python
rating = st.feedback("stars")
if rating is not None:
    st.caption(f"Thanks for the {rating + 1}-star rating!")
```

## Keep options on one row with `wrap`

`st.pills`, `st.segmented_control`, and `st.multiselect` accept `wrap`. The
default `None` stays on one row (and scrolls if needed) inside a horizontal
container or when the widget is placed directly in a column, and wraps onto
additional rows otherwise. Nested layout containers such as a form, expander,
or vertical `st.container` reset this. Pass `wrap=False` to always keep a
single row, or `wrap=True` to always wrap.

```python
# Directly in a column: stays one row by default
col1, col2 = st.columns(2)
with col1:
    tags = st.pills("Tags", ["Python", "SQL", "dbt"], selection_mode="multi")

# Nested in a form: wrap unless you opt out
with st.form("filters"):
    tags = st.pills(
        "Tags", ["Python", "SQL", "dbt"], selection_mode="multi", wrap=False
    )
    st.form_submit_button("Apply")
```

## High-cardinality options

Keep option lists in the low thousands. Every option is serialized into the widget's message and matched client-side on each keystroke; a million 16-character labels is roughly 16 MB.

Don't fetch a table to derive options: query the distinct values with a bound, precomputing them into their own table when the base table is large. If the domain outgrows the bound, search it rather than truncate:

```python
conn = st.connection("sql")

# BAD: pulls every row into the app for one dropdown; can exhaust app memory
df = conn.query("select * from orders")
customer = st.selectbox("Customer", df["customer"].unique())

# GOOD: the database does the work and returns a bounded list
customer = st.selectbox(
    "Customer",
    conn.query(
        "select distinct customer from orders order by customer limit 1000", ttl=3600
    )["customer"],
)
```

Past a few thousand, search:

```python
conn = st.connection("sql")


def like_pattern(text: str) -> str:
    """Return a contains-style LIKE pattern that treats user input literally."""
    for char in ("!", "%", "_"):
        text = text.replace(char, "!" + char)
    return f"%{text}%"


term = st.text_input(
    "Customer", type="search", live="300ms", placeholder="Type to search…"
)
customer = None
if len(term) >= 2:
    # Query a precomputed distinct-value table, not the base orders table.
    matches = conn.query(
        "select customer from customers where customer like :term escape '!'"
        " order by customer limit 50",
        params={"term": like_pattern(term)},
        ttl=60,
    )["customer"]
    customer = st.selectbox(
        "Matches", matches, index=None, label_visibility="collapsed"
    )
```

- `live="300ms"` debounces, so typing doesn't hit the database on every keystroke, and `index=None` keeps the first match from applying before the user picks.
- Escape `%` and `_` and declare an `escape` character, or a typed `%` matches far more than the user asked for.
- Pass `ttl` as a number: `conn.query` caches forever by default and takes no `max_entries`.
- `st.connection("sql")` binds `:name`; Snowflake binds `?` and uppercases unquoted columns.
- When the rest of the app is expensive, wrap this in `@st.fragment` (see `performance.md`), publish the choice through Session State, and `st.rerun()` on change, or dependents keep showing the old value.

## Toggle vs checkbox

Use `st.toggle` for settings that trigger changes in the app. Reserve `st.checkbox` for forms.

```python
# GOOD: Toggle for app settings
dark_mode = st.toggle("Dark mode")
show_advanced = st.toggle("Show advanced options")

# GOOD: Checkbox in forms
with st.form("signup"):
    agree = st.checkbox("I agree to the terms")
    st.form_submit_button("Sign up")
```

## Forms with border=False

Remove the default form border for cleaner inline forms. Keep the border for longer forms where visual grouping helps.

```python
# Inline form without border
with st.form(key="add_item", border=False):
    with st.container(horizontal=True, vertical_alignment="bottom"):
        st.text_input("New item", label_visibility="collapsed", placeholder="Add item")
        st.form_submit_button("Add", icon=":material/add:")

# Longer form - keep the border for visual grouping
with st.form("signup"):
    st.text_input("Name")
    st.text_input("Email")
    st.selectbox("Role", ["Admin", "User"])
    st.form_submit_button("Submit")
```

## Custom options in selectbox and multiselect

Allow users to add their own options with `accept_new_options`:

```python
# Works with multiselect
tickers = st.multiselect(
    "Stock tickers",
    options=["AAPL", "MSFT", "GOOGL", "NVDA"],
    default=["AAPL"],
    accept_new_options=True,
    placeholder="Choose stocks or type your own",
)

# Also works with selectbox
country = st.selectbox(
    "Country",
    options=["USA", "UK", "Canada"],
    accept_new_options=True,
    placeholder="Select or type a country",
)
```

## References

- [st.segmented_control](https://docs.streamlit.io/develop/api-reference/widgets/st.segmented_control)
- [st.pills](https://docs.streamlit.io/develop/api-reference/widgets/st.pills)
- [st.selectbox](https://docs.streamlit.io/develop/api-reference/widgets/st.selectbox)
- [st.multiselect](https://docs.streamlit.io/develop/api-reference/widgets/st.multiselect)
- [st.feedback](https://docs.streamlit.io/develop/api-reference/widgets/st.feedback)
- [st.toggle](https://docs.streamlit.io/develop/api-reference/widgets/st.toggle)
- [st.checkbox](https://docs.streamlit.io/develop/api-reference/widgets/st.checkbox)
- [st.form](https://docs.streamlit.io/develop/api-reference/execution-flow/st.form)
