
# Using Streamlit session state

Streamlit reruns scripts top-to-bottom on every interaction. Without session state, variables reset each time. Use `st.session_state` to persist values across reruns.

## Basic usage

Session state is a dictionary-like object supporting attribute and bracket notation:

```python
# Initialize with setdefault (preferred)
st.session_state.setdefault("count", 0)

# Alternative: check before setting
if "count" not in st.session_state:
    st.session_state.count = 0

# Read
current = st.session_state.count

# Update
st.session_state.count += 1
st.session_state["count"] = 5  # Bracket notation also works

# Delete
del st.session_state.count
```

**Accessing uninitialized keys raises an error:** `KeyError` for `st.session_state["key"]` and `AttributeError` for `st.session_state.key`. Use `st.session_state.get("key", default)` for safe access.

## Widget-state association

Every widget with a `key` parameter automatically syncs to session state:

```python
name = st.text_input("Name", key="user_name")
# st.session_state.user_name contains the same value as `name`
```

## Syncing a widget to the URL (shareable links)

To make a widget's value shareable through the page URL, pass `bind="query-params"` together with `key=`. Streamlit writes the value to the URL query string when it changes and restores it from the URL on load and on browser back/forward — **don't hand-roll `st.query_params`** for this. The `key=` becomes the query-parameter name.

```python
# GOOD: one widget, automatic URL sync. Picking "Newest" -> ?sort=Newest;
# loading ?sort=Price reopens with "Price" selected.
sort = st.selectbox(
    "Sort order",
    ["Relevance", "Newest", "Price"],
    key="sort",  # REQUIRED with bind=; becomes the URL param name (?sort=...)
    bind="query-params",  # exact string, with a hyphen
)
st.write(f"Sorting by: {sort}")
```

```python
# BAD: hand-rolled plumbing. More code, an extra rerun to guard, it conflicts
# with bind= (a bound param can't be set/deleted via st.query_params), and it
# crashes on an unexpected URL value — .index(default) raises ValueError if a
# user opens ?sort=Foo. With bind="query-params", an unknown URL value just
# falls back to the default instead of raising.
default = st.query_params.get("sort", "Relevance")
sort = st.selectbox(
    "Sort order",
    ["Relevance", "Newest", "Price"],
    index=["Relevance", "Newest", "Price"].index(default),
)
st.query_params["sort"] = sort  # don't do this when bind= handles sync
```

Notes:
- `bind="query-params"` requires `key=`. The only valid value is the exact string `"query-params"` (hyphen, not `"query_params"`); anything else is invalid. Not supported with `st.text_input(type="password")`.
- Browser back/forward restores the bound value from the URL (or the widget default if the param is missing). That restore does not fire `on_change`. A missing param on history navigation also overrides a value assigned in `st.session_state` before the widget call; initial load leaves that assignment in place.
- When the value equals the default, the param is dropped from the URL to keep it clean.
- A bound param can't be set or deleted through `st.query_params` — change it programmatically by assigning to `st.session_state[key]` *before* the widget renders, or from an `on_change` callback. Assigning after the widget has already rendered on the same run raises `StreamlitWidgetAlreadyInstantiatedError` (see [Modifying state after widget creation](#modifying-state-after-widget-creation)). Do not mix `bind=` with manual `st.query_params` reads/writes.
- Still render the value (e.g. `st.write(f"Sorting by: {sort}")`) if the app needs to show the current selection.
- Works on input widgets generally. It's **not** supported on trigger/button widgets (`st.button`, `st.download_button`, `st.form_submit_button`, `st.menu_button`), file and media inputs (`st.file_uploader`, `st.camera_input`, `st.audio_input`), `st.chat_input`, `st.feedback`, or `st.data_editor`, nor on selections from `st.dataframe`/charts — assume any other input widget supports it. (Listing the exceptions rather than every supported widget keeps this from going stale as new widgets ship.)
- Multi-page apps: query params belong to the app URL, not an individual page, so a bound value persists in the URL across `st.navigation` page switches and is shared app-wide. If two pages bind widgets to the same `key=`, they share that value — use distinct keys per page when you don't want it to carry over.
- To keep a value across reruns or page switches *without* exposing it in the URL, use `persist_state` instead (see [Persisting widget values](#persisting-widget-values-persist_state)); when both are set, `bind` takes precedence.

## Widget input constraints are mostly client-side

Most widget input constraints—`options` allow-lists (`st.selectbox`, `st.multiselect`, `st.radio`), `min_value`/`max_value` (`st.slider`, `st.number_input`), `max_chars` / `validate` (`st.text_input`), `required` (`st.text_input`, `st.number_input`), `disabled`, and `st.data_editor` column `validate`/`num_rows`—are primarily enforced in the browser for UX. Treat them as guardrails for normal users, **not** as a security boundary: a widget's return value (and its `st.session_state` entry) reflects what the client sent, and a modified or malicious client can submit values outside those constraints.

For any security-relevant or sensitive decision—authorization/role checks, database writes, file paths, spending or quota limits, or anything that must not exceed a declared bound—re-validate the value in your own script before acting on it:

```python
ALLOWED_ROLES = ["viewer", "editor"]
role = st.selectbox("Role", ALLOWED_ROLES, key="role")

# Don't rely on the widget's options as a security check.
if role not in ALLOWED_ROLES:
    st.error("Invalid role.")
    st.stop()
grant_access(role)
```

## Persisting widget values (`persist_state`)

By default, a keyed widget's value is lost when the widget stops being rendered (for example, when it's conditionally hidden or the user switches pages). Set the keyword-only `persist_state` parameter to keep the value:

- `None` (default): the value is dropped when the widget isn't rendered.
- `"page"`: the value is preserved while the user stays on the page where the widget is defined (e.g., while it's conditionally hidden); it's discarded on a page switch.
- `"session"`: the value is preserved for the whole session, including across page switches, so it returns when the user navigates back.

```python
st.text_input("Name", key="name", persist_state="session")
```

`persist_state` requires a `key` and is available on most widgets that support `bind="query-params"` (not yet on `st.tabs`). When both are set, `bind` takes precedence, so the value lives in the URL and persists across page switches regardless of the `persist_state` scope.

## Callbacks

Callbacks execute **before** the script reruns, allowing immediate state changes. Use `on_change` or `on_click` with optional `args` and `kwargs`:

```python
def increment(amount):
    st.session_state.count += amount


st.button("Add 5", on_click=increment, args=(5,))
```

Access a widget's value in its own callback via `st.session_state.key`, not the return variable.

Calling `st.rerun()` or `st.switch_page()` inside a callback ends that callback immediately (statements after the call don't run). Streamlit still runs the interaction's other callbacks before performing the rerun or navigation.

`on_change` can also be `"ignore"` or `"rerun"` instead of a callback on some widgets. `"ignore"` updates the widget without a rerun; see [Skip reruns on individual widgets](performance.md#skip-reruns-on-individual-widgets-advanced).

## Initialization patterns

Initialize all state at the top of your app for clarity:

```python
st.session_state.setdefault("user", None)
st.session_state.setdefault("page", "home")
st.session_state.setdefault("filters", {})
```

## Multipage state

By default, widgets are NOT stateful across pages—their values reset when navigating between pages. To keep a widget's value across page switches, set `persist_state="session"` (see [Persisting widget values](#persisting-widget-values-persist_state) above).

### Sharing state

Use session state variables (not widget keys) to share data:

```python
# Page 1: Store value
st.session_state.selected_user = st.selectbox("User", users)

# Page 2: Read stored value
if "selected_user" in st.session_state:
    st.write(f"Selected: {st.session_state.selected_user}")
```

### Shared widgets pattern

Put common widgets in the entrypoint file (before `nav.run()`):

```python
# app.py (entrypoint)
with st.sidebar:
    st.session_state.theme = st.selectbox("Theme", ["Light", "Dark"])

nav = st.navigation(pages)
nav.run()
```

## Common mistakes

### Module-level mutable state

```python
# BAD: In imported modules, this is shared across ALL users
# utils.py
cache = {}  # Persists across reruns AND users!

# GOOD: Use session state for per-user data
st.session_state.setdefault("cache", {})
```

### Modifying state after widget creation

You cannot assign to a widget's session state key after that widget has been instantiated on the current run. This raises `StreamlitWidgetAlreadyInstantiatedError`.

```python
st.slider("Value", key="my_slider")
st.session_state["my_slider"] = 50  # Raises StreamlitWidgetAlreadyInstantiatedError
```

Assign the value **before** creating the widget:

```python
st.session_state.setdefault("my_slider", 50)
st.slider("Value", key="my_slider")
```

Or from an `on_change` / `on_click` callback (callbacks run before widgets are instantiated):

```python
def reset_slider():
    st.session_state["my_slider"] = 50


st.button("Reset", on_click=reset_slider)
st.slider("Value", key="my_slider")
```

For widgets whose keys are read-only (see [Read-only widget keys](#read-only-widget-keys)), store values in a different session state key.

### Read-only widget keys

Some widgets are read-only in session state (buttons and button-like triggers, file and media inputs, `st.data_editor`, `st.form` keys, and chart or `ButtonColumn` selections). Creating one after assigning to its key raises `StreamlitValueAssignmentNotAllowedError`. Keep that key read-only and store values you need to set in a **different** session state key:

```python
def mark_done():
    st.session_state["done"] = True


st.button("Done", key="done_btn", on_click=mark_done)
```

### Mixing `value` parameter and session state

Don't set both—it causes warnings:

```python
# BAD: Conflicting sources
st.session_state.setdefault("name", "Alice")
st.text_input("Name", value="Bob", key="name")  # Warning!

# GOOD: Use one or the other
st.session_state.setdefault("name", "Alice")
st.text_input("Name", key="name")
```

## Session characteristics

- **Per-user, per-tab**: Each browser tab has its own session
- **Temporary**: Lost when tab closes or server restarts
- **Not suitable for persistence**: Use databases for permanent storage

## References

- [st.session_state API](https://docs.streamlit.io/develop/api-reference/caching-and-state/st.session_state)
- [Session State concepts](https://docs.streamlit.io/develop/concepts/architecture/session-state)
- [Widget behavior](https://docs.streamlit.io/develop/concepts/architecture/widget-behavior)
