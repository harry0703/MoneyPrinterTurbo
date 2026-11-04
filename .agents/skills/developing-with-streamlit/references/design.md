
# Streamlit visual design

Small touches that make apps feel polished.

Visual design works hand-in-hand with other references:
- `selection-widgets.md` — Choosing the right widget (segmented control, pills, toggle)
- `data-display.md` — Column config, sparklines, bordered metrics
- `layouts.md` — Containers, alignment, dashboard cards
- `theme.md` — Colors, fonts, and borders via `config.toml`

## Colors and theming

Do not use custom CSS to polish an app unless the user explicitly asks for it. Set colors, fonts, and borders in `.streamlit/config.toml` instead. Native theming applies consistently across every element and survives Streamlit upgrades; CSS selectors target internal class names that can change.

```python
# BAD: Injected CSS for a brand color
st.html("<style>.stButton button { background: #0969da; }</style>")
```

```toml
# GOOD: Configure theme tokens in .streamlit/config.toml
[theme]
primaryColor = "#0969da"
```

Read `theme.md` for the full option set, ready-made theme configs, and the narrow escape hatch for when the user explicitly asks for CSS.

## Page config

Set browser tab title, icon, and layout. Place this at the top of your script to avoid visual blinking:

```python
st.set_page_config(
    page_title="My Dashboard",
    page_icon=":material/analytics:",
    layout="wide",  # Use "wide" for dashboards with lots of data
)
```

**Layout options:**
- `layout="centered"` (default) → Best for most apps, content is constrained to a readable width
- `layout="wide"` → Full-width, good for dashboards and data-heavy apps

## App logo

Add a logo to the sidebar/header:

```python
st.logo("logo.png")
```

## Icons over emojis

Use Material Symbols for a cleaner, more professional look. Streamlit uses the [Material Symbols](https://fonts.google.com/icons) icon set (not the older Material Icons).

```python
# GOOD: Material Symbols
st.markdown(":material/settings:")
st.markdown(":material/calendar_today:")
st.markdown(":material/dashboard:")
st.markdown(":material/person:")

# SPARINGLY: Emojis for special occasions
st.markdown("Celebration! 🎉")
```

Format: `:material/icon_name:`

Find icons: https://fonts.google.com/icons

Full list of icons available in Streamlit: [material_icon_names.py](https://raw.githubusercontent.com/streamlit/streamlit/refs/heads/develop/lib/streamlit/material_icon_names.py)

**Popular icons by category:**

| Category | Icons |
|----------|-------|
| Navigation | `home`, `arrow_back`, `menu`, `settings`, `search` |
| Actions | `send`, `play_arrow`, `refresh`, `download`, `upload`, `save`, `delete`, `edit` |
| Status | `check_circle`, `error`, `warning`, `info`, `pending` |
| Data | `table_chart`, `bar_chart`, `analytics`, `query_stats`, `database` |
| Content | `chat`, `code`, `description`, `article`, `folder` |
| UI | `visibility`, `build`, `tune`, `filter_list` |

## Badges for status

For standalone badges:
```python
st.badge("Active", icon=":material/check:", color="green")
st.badge("Pending", icon=":material/schedule:", color="orange")
st.badge("Deprecated", color="red")
```

For inline badges in text:
```python
st.markdown("""
:green-badge[Active] :orange-badge[Pending] :red-badge[Deprecated] :blue-badge[New]
""")
```

Avoid the old verbose syntax:
```python
# OLD (still works but cluttered)
st.markdown(":orange-background[:orange[Pending]]")
```

## Spacing: remove dividers

Dividers (`st.divider()` or `---`) look heavy. Just remove them—Streamlit's default spacing is usually enough.

```python
# BAD
st.header("Section 1")
st.write("Content")
st.divider()  # Too heavy
st.header("Section 2")

# GOOD
st.header("Section 1")
st.write("Content")
st.header("Section 2")
```

If you genuinely need spacing:
```python
st.space("small")  # Small gap
st.space("medium")  # Medium gap
st.space("large")  # Large gap
st.space(50)  # Custom pixels for fine-tuning
```

**Don't** systematically replace dividers with `st.space()`—it can look weird too.

## Sentence casing

Use sentence casing for titles and labels. Title Case Feels Shouty.

```python
# GOOD
st.title("Upload your data")
st.selectbox("Select a region", options)
st.button("Save changes")

# BAD
st.title("Upload Your Data")
st.selectbox("Select A Region", options)
```

## Caption over info

`st.info()` is too heavy for simple informational text.

```python
# GOOD: Lighter
st.caption("Data last updated 5 minutes ago")

# BAD: Too heavy
st.info("Data last updated 5 minutes ago")
```

**When to use what:**
- `st.caption` → Simple info, metadata, timestamps
- `st.info` → Important instructions
- `st.warning` → Caution, potential issues
- `st.error` → Errors that block progress
- `st.success` → Confirmation of action
- `st.toast` → Lightweight confirmation that auto-dismisses

## Text alignment

Use `text_alignment` for text elements:

```python
st.title("Centered title", text_alignment="center")
st.markdown("Right aligned", text_alignment="right")
st.caption("Justified text", text_alignment="justify")
```

Options: `"left"` (default), `"center"`, `"right"`, `"justify"`

**Note:** `horizontal_alignment` on containers positions elements but also sets their `text_alignment`. If you need different text alignment within a horizontally-aligned container, override `text_alignment` on the text element itself.

## Icons in headings, callouts, and expanders

Material Symbols can make headings, callouts, and expanders look nicer:

```python
st.title("Dashboard", icon=":material/dashboard:")
st.header("Sales overview", icon=":material/bar_chart:")
st.subheader("Recent orders", icon=":material/receipt_long:")

st.info("Processing complete", icon=":material/check_circle:")
st.warning("Rate limit approaching", icon=":material/warning:")
st.error("Connection failed", icon=":material/error:")
st.success("Saved!", icon=":material/thumb_up:")

with st.expander("Settings", icon=":material/settings:"):
    st.write("Configure your preferences")
```

Other elements like `st.button` and `st.tabs` also support icons—worth considering when it adds clarity.

## References

- [st.set_page_config](https://docs.streamlit.io/develop/api-reference/configuration/st.set_page_config)
- [st.logo](https://docs.streamlit.io/develop/api-reference/media/st.logo)
- [st.badge](https://docs.streamlit.io/develop/api-reference/text/st.badge)
- [st.space](https://docs.streamlit.io/develop/api-reference/layout/st.space)
- [st.markdown](https://docs.streamlit.io/develop/api-reference/text/st.markdown)
- [st.toast](https://docs.streamlit.io/develop/api-reference/status/st.toast)
- [Theming](https://docs.streamlit.io/develop/concepts/configuration/theming)
