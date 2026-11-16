## State sync patterns (JS ↔ Python)

This reference shows the canonical CCv2 “controlled component” loop and the most common pitfalls when syncing state between JavaScript and Python.

## Contents

- Mental model
- Canonical pattern: controlled text input
  - JavaScript (hydrate from `data`, emit via `setStateValue`)
  - Python wrapper (feed state back down via `data`)
- Defaults: when to use `default=...` (and why it fails)
- Python → JS hydration: initial-only vs true sync
- Session State timing: don’t mutate after mount
- Troubleshooting checklist

### Mental model

- **Frontend state emission (JS → Python)**: you explicitly call `setStateValue(key, value)` or `setTriggerValue(key, value)`.
- **Frontend state hydration (Python → JS)**: your JS reads `component.data` and updates the DOM accordingly.
- There is no built-in “two-way binding”: you must implement both sides.

### Canonical pattern: controlled text input

This is modeled after Streamlit’s own CCv2 e2e example.

#### JavaScript (hydrate from `data`, emit via `setStateValue`)

Key guideline: only assign to the input when it’s different, or you’ll fight the user’s cursor.

```js
export default function (component) {
  const { parentElement, data, setStateValue } = component

  const label = parentElement.querySelector("label")
  const input = parentElement.querySelector("input")
  if (!label || !input) return

  label.innerText = data.label

  const nextValue = data.value ?? ""
  if (input.value !== nextValue) {
    input.value = nextValue
  }

  input.onkeydown = e => {
    if (e.key === "Enter") {
      setStateValue("value", e.target.value)
    }
  }
}
```

#### Python wrapper (feed state back down via `data`)

```python
import streamlit as st

_COMPONENT = st.components.v2.component(
    "interactive_text_input",
    html="""
    <label for="txt">Enter text:</label>
    <input id="txt" type="text" />
    """,
    js=JS,  # inline JS string from above
)


def interactive_text_input(*, label: str, initial_value: str, key: str):
    # 1) Read current component state from Session State (if it exists)
    component_state = st.session_state.get(key, {})

    # 2) Compute the value you want the UI to display
    value = component_state.get("value", initial_value)

    # 3) Send it down to the frontend via `data`
    return _COMPONENT(
        key=key,
        data={"label": label, "value": value},
    )


KEY = "my_text_input"

if st.button("Make it say Hello World"):
    st.session_state.setdefault(KEY, {})["value"] = "Hello World"

interactive_text_input(label="Enter something", initial_value="Initial Text", key=KEY)
```

### Defaults: when to use `default=...` (and why it fails)

`default={...}` is optional. Use it when you want Streamlit to initialize missing state keys for a mounted instance.

Rules:

- Defaults apply only to **state** keys (not triggers).
- Every key in `default` must have a corresponding `on_<key>_change` callback parameter when mounting, or Streamlit raises.

Pattern:

```python
result = _COMPONENT(
    key=key,
    data={"value": value},
    default={"value": value},
    on_value_change=lambda: None,  # required if using default["value"]
)
```

### Python → JS hydration: initial-only vs true sync

You’ll see two patterns in the wild:

- **Initial-only hydration**: JS reads `data.initialX` on first mount only. This is useful for *initialization* but it will **not** reflect later Python changes.
- **True sync (controlled)**: JS reconciles its UI from `data.value` on every render, and only writes when changed.

Initial-only example (pitfall for sync):

```js
// If you guard hydration with hasMounted, Python changes won't propagate.
if (typeof data?.initialText !== "undefined" && !hasMountedForKey) {
  input.value = String(data.initialText)
}
hasMounted[key] = true
```

True sync approach (recommended when Python can update the UI):

```js
const nextValue = data.value ?? ""
if (input.value !== nextValue) input.value = nextValue
```

### Session State timing: don’t mutate after mount

Streamlit may raise if you modify `st.session_state.<key>.<field>` **after** the component with that key has been instantiated in the same run.

Safe patterns:

- Update `st.session_state[key][...]` **before** mounting the component (e.g., in a button handler placed above the mount call).
- Or update state in a different run (trigger a rerun after setting state).
- If the mount passes any `on_<name>_change` callback, Streamlit silently ignores Python writes to state keys that lack a matching `on_<key>_change` callback. Pass a no-op callback (for example, `on_value_change=lambda: None`) for every state key you set from Python.

### Troubleshooting checklist

- **Cursor jumps / typing feels broken**: ensure your JS only assigns `input.value` when it differs from the `data` value.
- **Python updates don’t reflect in UI**: confirm you pass the updated values via `data` every run; avoid initial-only hydration guards if you want true sync.
- **`default` raises**: ensure every default key has a corresponding `on_<key>_change` callback parameter.
- **Session state mutation error**: move `st.session_state[key][...] = ...` earlier in the script (before mount), or restructure into a two-run flow (set state then rerun).
- **Python write to component state has no effect**: if the mount passes any `on_<name>_change` callback, also pass one (a no-op is fine) for each state key you set from Python.
