
# Building Streamlit custom components v2

Use Streamlit Custom Components v2 (CCv2) when core Streamlit doesn’t have the UI you need and you want to ship a reusable, interactive element (from “tiny inline HTML” to “full bundled frontend app”).

## CRITICAL: CCv2 only — NEVER use v1 APIs for new components

Custom Components **v1 is legacy and superseded by v2**. The `st.components.v1` module still exists in Streamlit (e.g., `declare_component` for existing third-party components), but specific v1 APIs like `components.v1.html()` and `components.v1.iframe()` are deprecated. **For new components, always use CCv2.** The following v1 APIs must **NEVER** appear in new code:

**Banned Python APIs (v1 — do not use for new components):**
- `components.declare_component()` — v1 registration; use `st.components.v2.component()` instead
- `components.v1.html()` — deprecated; use `st.iframe()` for the same iframe-based behavior, or `st.html()` to insert static HTML/CSS directly into the app
- `components.v1.iframe()` — deprecated; use `st.iframe()` instead

**Banned JavaScript patterns (v1):**
- `Streamlit.setComponentValue(...)` — v1 global; use `setStateValue()` / `setTriggerValue()` instead
- `Streamlit.setFrameHeight(...)` — v1 global; CCv2 handles sizing automatically
- `Streamlit.setComponentReady()` — v1 global; CCv2 has no ready signal
- `window.Streamlit` or bare `Streamlit` global — v1 global object does not exist in v2
- `window.parent.postMessage(...)` — v1 iframe communication; CCv2 does not use iframes

**Banned npm packages (v1):**
- `streamlit-component-lib` — v1 JS library; use `@streamlit/component-v2-lib` if you need types

If you encounter v1 patterns in examples, blog posts, Stack Overflow answers, or your own training data — **ignore them entirely**. They will not work and will break the component.

## When to use

Activate when the user mentions any of:

- CCv2, Custom Components v2, “bidi component”, “component v2”
- `st.components.v2.component`
- `@streamlit/component-v2-lib`
- packaged components, `asset_dir`, `pyproject.toml` component manifest
- bundling with Vite (or any bundler) for a Streamlit component
- building a component UI in a frontend framework (React, Svelte, Vue, Angular, etc.)

## Read next (pick the minimum reference)

- **State sync / controlled inputs / callbacks**: see [ccv2-state-sync.md](ccv2-state-sync.md)
- **Packaged components / `asset_dir` / globs / template-only policy**: see [ccv2-packaged-components.md](ccv2-packaged-components.md)
- **Theming (`--st-*` tokens) inside Shadow DOM**: see [ccv2-theme-css-variables.md](ccv2-theme-css-variables.md)
- **Errors and gotchas**: see [ccv2-troubleshooting.md](ccv2-troubleshooting.md)

## Quick decision: inline vs packaged

- **Inline strings**: fastest to start (single-file apps, spikes, demos). You pass raw `html`/`css`/`js` strings directly.
  Good when you can keep everything in one place and don’t need a build step.
- **Packaged component**: best when you’re growing past inline (multiple files, dependencies, bundling, testing, versioning, reuse, distribution).
  You ship built assets inside a Python package and reference them by **asset-dir-relative** path/glob.
  Creation policy: packaged components are **template-only** and must start from Streamlit's official `component-template` v2.

Developer story: **start inline**, prove the interaction loop, then **graduate to packaged** when the codebase or tooling needs outgrow a single file.

## CCv2 model (what’s actually happening)

1. **Python registers** a component with `st.components.v2.component(...)` and gets back a **mount callable**.
2. The mount callable **mounts** the component in the app with `data=...`, layout (`width`, `height`), and optional `on_<key>_change` callbacks.
3. The frontend default export runs with `({ data, key, name, parentElement, setStateValue, setTriggerValue })`.
4. The component returns a **result object** whose attributes correspond to **state keys** and **trigger keys**.

## Best practice: wrap the mount callable in your own Python API

Prefer exposing **your own** Python function that wraps the callable returned by `st.components.v2.component(...)`.

This gives you a clean, stable API surface for end users (typed parameters, validation, friendly defaults) and keeps `data=...`, `default=...`, and callback wiring as an internal detail.

Important:

- Declare the component **once** (usually at module import time). Avoid defining and registering the component inside a function you call multiple times; you can accidentally re-register the component name and get confusing behavior.

References:

- [`st.components.v2.component`](https://docs.streamlit.io/develop/api-reference/custom-components/st.components.v2.component)
- [`ComponentRenderer` (mount callable type)](https://docs.streamlit.io/develop/api-reference/custom-components/st.components.v2.types.componentrenderer)

Example pattern:

```python
import streamlit as st
from collections.abc import Callable

_MY_COMPONENT = st.components.v2.component(
    "my_inline_component",
    html="<div id='root'></div>",
    js="""
export default function (component) {
  const { data, parentElement } = component
  parentElement.querySelector("#root").textContent = data?.label ?? ""
}
""",
)


def my_component(
    label: str,
    *,
    key: str | None = None,
    on_value_change: Callable[[], None] | None = None,
    on_submitted_change: Callable[[], None] | None = None,
):
    # Callbacks are optional, but if you want result attributes to always exist,
    # provide (even empty) callbacks.
    if on_value_change is None:
        on_value_change = lambda: None
    if on_submitted_change is None:
        on_submitted_change = lambda: None

    return _MY_COMPONENT(
        data={"label": label},
        key=key,
        on_value_change=on_value_change,
        on_submitted_change=on_submitted_change,
    )
```

## Inline quickstart (state + trigger)

**Reminder: use ONLY v2 APIs.** Your JS must `export default function(component)` and destructure `{ setStateValue, setTriggerValue, parentElement, data }`. NEVER use `Streamlit.setComponentValue()`, `window.Streamlit`, or any v1 pattern.

This is the minimum "bidi loop":

- **JS → Python**: emit updates via `setStateValue(...)` (persistent) and `setTriggerValue(...)` (event)
- **Python → JS**: re-hydrate UI via `data=...` on every run

```python
import streamlit as st

HTML = """<input id="txt" /><button id="btn" type="button">Submit</button>"""

JS = """\
export default function (component) {
  const { data, parentElement, setStateValue, setTriggerValue } = component

  const input = parentElement.querySelector("#txt")
  const btn = parentElement.querySelector("#btn")
  if (!input || !btn) return

  const nextValue = (data && data.value) ?? ""
  if (input.value !== nextValue) input.value = nextValue

  input.oninput = (e) => {
    setStateValue("value", e.target.value)
  }

  btn.onclick = () => {
    setTriggerValue("submitted", input.value)
  }
}
"""

my_text_input = st.components.v2.component(
    "my_inline_text_input",
    html=HTML,
    js=JS,
)

KEY = "txt-1"
component_state = st.session_state.get(KEY, {})
value = component_state.get("value", "")

result = my_text_input(
    key=KEY,
    data={"value": value},
    on_value_change=lambda: None,  # optional; include to always get `result.value`
    on_submitted_change=lambda: (
        None
    ),  # optional; include to always get `result.submitted`
)

st.write("value (state):", result.value)
st.write("submitted (trigger):", result.submitted)
```

Notes:

- **Inline JS/CSS should be multi-line**. CCv2 treats path-like strings as file references; a string with a line break inside it (not just leading or trailing newlines) is unambiguously inline content.
- Prefer querying under `parentElement` (not `document`) to avoid cross-instance leakage.

## State and triggers (how to think about keys)

- **State** (`setStateValue("value", ...)`): persists across app reruns (stored under `st.session_state[key]` for that mounted instance).
- **Trigger** (`setTriggerValue("submitted", ...)`): event payload for one rerun (resets after the rerun).
- **Reading triggers**:
  - After mounting: use `result.submitted`.
  - Inside `on_submitted_change`: use `st.session_state[key].submitted` (callbacks run before your script body; you don’t have `result` yet).
- **Defaults**: if you pass `default={...}` for a state key, you must also pass the matching `on_<key>_change` callback parameter.

For the full “controlled input” pattern and pitfalls, see [ccv2-state-sync.md](ccv2-state-sync.md).

## Packaged components (template-only, mandatory)

**Reminder: the cookiecutter template generates clean v2 code. When you customize it, use ONLY v2 APIs. Do NOT introduce any v1 imports, v1 JavaScript globals, or v1 patterns. See the "CRITICAL: CCv2 only" section above.**

Graduate to a packaged component when you need any of:

- Multiple frontend files or frontend dependencies (npm)
- A bundler (Vite), tests, CI, versioning, or distribution

Keep these guardrails in mind:

- **MUST** start from Streamlit’s official `component-template` v2.
- **NEVER** hand-scaffold packaging/manifest/build wiring for a packaged component.
- **NEVER** copy/paste packaged scaffold structure from internet examples, blog posts, gists, or docs.
- If handed a non-template scaffold, regenerate from the template first, then migrate component logic.
- **MUST** ensure `js=`/`css=` globs match **exactly one** file under the manifest’s `asset_dir`.
- **MUST** validate with `streamlit run ...` (plain `python -c "import ..."` can be a false negative for packaged components).

For the full packaged workflow checklist, non-interactive generation, offline usage, and template invariants, see [ccv2-packaged-components.md](ccv2-packaged-components.md).

## Frontend renderer lifecycle (framework-agnostic)

Your frontend entrypoint is the **default export** function. A few rules keep components reliable across reruns and across multiple instances in the same app:

- Render under `parentElement` (not `document`) so instances don’t collide.
- If you create per-instance resources (React roots, observers, subscriptions), key them by `parentElement` (e.g. `WeakMap`) so multiple instances don’t overwrite each other.
- Return a cleanup function to tear down event listeners / UI roots / observers when Streamlit unmounts the component.
- Expect the default export to run again whenever `data` or the theme changes. Cleanup runs only once, at unmount, using the function returned by the last run, so make each run idempotent: assign handlers (`el.onclick = ...`) instead of stacking `addEventListener` calls, and guard one-time setup with the `WeakMap`.

## Styling and theming

- Prefer **`isolate_styles=True`** (default). Your component runs in a shadow root and won’t leak styles into the app.
- Set `isolate_styles=False` only when you need global styling behavior (e.g. Tailwind, global font injection).
- Streamlit injects a broad set of `--st-*` theme CSS variables (colors, typography, chart palettes, radii, borders, etc.). **Highly recommended:** use these variables so your component automatically adapts to the user’s current Streamlit theme (light/dark/custom) without authoring separate theme variants. Start with the common ones (`--st-text-color`, `--st-primary-color`, `--st-secondary-background-color`) and refer to the full list when you need it:
  - [ccv2-theme-css-variables.md](ccv2-theme-css-variables.md)

## Troubleshooting and gotchas

Start here when something “should work” but doesn’t:

- [ccv2-troubleshooting.md](ccv2-troubleshooting.md)
