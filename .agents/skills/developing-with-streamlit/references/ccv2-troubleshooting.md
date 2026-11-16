## Troubleshooting CCv2 components

## Contents

- **v1 contamination (most common failure)**
- Packaged assets and manifests (`asset_dir`, component key)
- Renamed project/package still shows old template names
- Inline strings vs file-backed assets (path heuristic)
- Globs (0 matches or multiple matches)
- Defaults, callbacks, and missing result attributes
- Keys (Python `key=` vs frontend `key`)
- Shadow DOM / `isolate_styles` surprises
- Frontend build gotchas
- DOM clobbering (overwriting injected HTML/CSS)

### v1 contamination (most common failure)

The single most common cause of broken CCv2 components is accidentally mixing in **v1 APIs** from outdated examples, blog posts, or training data. v1 APIs don’t work inside a v2 component.

Symptoms:
- Component renders as blank/empty iframe
- `Streamlit is not defined` errors in browser console
- `setComponentValue is not a function` errors
- Component never communicates back to Python

Check your code for these **banned patterns** and replace them:

| Banned (v1)                              | Correct (v2)                                          |
|------------------------------------------|-------------------------------------------------------|
| `st.components.v1`                       | `st.components.v2.component(...)`                     |
| `components.declare_component()`         | `st.components.v2.component(...)`                     |
| `components.html()`                      | `st.iframe()` / `st.html()` for static HTML, or `st.components.v2.component(...)` with `html=` when it needs events |
| `Streamlit.setComponentValue(val)`       | `setStateValue("key", val)` or `setTriggerValue(...)` |
| `Streamlit.setFrameHeight()`             | Remove entirely (v2 handles sizing)                   |
| `Streamlit.setComponentReady()`          | Remove entirely (v2 has no ready signal)              |
| `window.Streamlit`                       | Use destructured args from `export default function`  |
| `window.parent.postMessage(...)`         | Use `setStateValue` / `setTriggerValue`               |
| `streamlit-component-lib` (npm)          | `@streamlit/component-v2-lib` (if types needed)       |
| `function sendMessageToStreamlitClient`  | Remove entirely; use v2 callback args                 |

Fix: search all `.py` and `.js`/`.ts`/`.tsx` files for these patterns. If any are found, rewrite using the v2 equivalents above. The cookiecutter template generates correct v2 code — if you started from the template, the contamination is in your customizations.

### Packaged assets and manifests (`asset_dir`, component key)

#### “Component '<name>' must be declared in pyproject.toml with asset_dir to use file-backed js/css.”

You passed a **path-like** `js=`/`css=` string (like `index-*.js` or `assets/index-*.js`) but Streamlit can’t find an `asset_dir` for this component key.

Fix:

- If you want **inline JS/CSS**, pass a **multi-line** string with the actual code (not a path).
- If you want **packaged assets**, ensure:
  - Your wheel includes a `pyproject.toml` with `[[tool.streamlit.component.components]] ... asset_dir = ...`
  - You call `st.components.v2.component("<project>.<component>", js="...", css="...")` with the matching fully-qualified key.

Important context:

- This error is expected if you test packaged wrappers via plain Python import in some environments.
- Prefer `streamlit run ...` for packaged verification because manifest discovery is part of Streamlit runtime initialization.

### Inline strings vs file-backed assets (path heuristic)

CCv2 uses a heuristic: strings that “look like” paths are treated as file references. A string with a line break inside it is always treated as inline content. Leading and trailing newlines are stripped first, so they don't count.

Fix:

- Prefer triple-quoted multi-line strings for inline `html`/`css`/`js`.
- Avoid single-line minified JS/CSS in `js=`/`css=`; if you must use it, put a line break inside the code.

### Globs (0 matches or multiple matches)

Globs must match **exactly one** file under `asset_dir`.

Fix:

- Clean the build output directory before rebuilding.
- Make your bundler output a predictable `index-<hash>.js` / `index-<hash>.css` (or `assets/index-<hash>...` if you emit into an `assets/` subdir).
- If you started from Streamlit’s `component-template`, run `npm run clean` from your `frontend/` directory to clear the `build/` output so `index-*.js` matches exactly one file.

### Renamed project/package still shows old template names

Symptoms:

- Old names like `streamlit-component-x` / `streamlit_component_x` remain in paths or metadata.
- Imports, manifest component keys, and registration keys no longer align.

Fix:

- Rename/update all related surfaces together:
  - root `pyproject.toml` project name
  - import package folder and `MANIFEST.in` paths
  - `[tool.setuptools.packages.find]` and `[tool.setuptools.package-data]`
  - in-package manifest (`<import_name>/pyproject.toml`)
  - wrapper registration key (`"<project.name>.<component.name>"`)
  - README/example imports and install commands
- Rebuild frontend and reinstall editable package after rename.

### Defaults, callbacks, and missing result attributes

#### `default={...}` raises "is not a valid state name" / missing result attributes

Defaults only apply to **state keys**, and Streamlit expects those keys to be declared via `on_<key>_change` callback parameters at mount time.

Fix:

- If you pass `default={"value": ...}`, also pass `on_value_change=lambda: None`.
- For triggers, don’t expect defaults; triggers are transient and default to `None`.

#### Trigger never fires inside `st.form`

`setTriggerValue` is ignored when the component is inside `st.form`; the browser console logs a warning instead. Inside a form, use `setStateValue` and let the form’s submit button commit it.

### Keys (Python `key=` vs frontend `key`)

- Python `key=` is the user-visible Streamlit element key.
- The frontend also receives a `key` string that is **generated by Streamlit** and is not the same as the Python `key` unless you explicitly pass the user key through `data`.

Fix:

- If your frontend needs a stable identifier, pass it in `data={"user_key": key, ...}`.

### Shadow DOM / `isolate_styles` surprises

#### Shadow DOM (`isolate_styles=True`) surprises

With `isolate_styles=True` (default):

- Your component is mounted in a **shadow root**.
- `parentElement` is a `ShadowRoot`.
- Global CSS (like Tailwind injected into the document) won’t automatically style your component.

Fix:

- Keep `isolate_styles=True` for safety and use CSS variables and component-local styles.
- Use `isolate_styles=False` only when you intentionally need global styling behavior.

### Frontend build gotchas (Vite)

If you deviate from the template’s Vite config (or you’re wiring Vite into an existing repo), these are the common footguns:

- **Missing `base: "./"`**: relative asset URLs can break when served from Streamlit’s component URL path.
- **Stale build artifacts**: Vite outputs hashed filenames; if you keep old builds around, `index-*.js` can match multiple files. Clean the build dir before rebuilding.

### DOM clobbering (overwriting injected HTML/CSS)

#### Accidentally overwriting your component DOM

If you directly set `parentElement.innerHTML = ...`, you can overwrite the HTML/CSS that Streamlit injected from your `html=`/`css=` arguments.

Fix:

- Prefer `querySelector` + modifying children.
- If you need dynamic HTML, create a new child element and set **that** element’s `innerHTML`.
