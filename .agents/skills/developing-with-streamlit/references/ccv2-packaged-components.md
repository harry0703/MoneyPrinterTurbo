## Packaged CCv2 components (template-only, mandatory)

For packaged CCv2 components, agents **MUST** use Streamlit's official template as the starting point for every new component project.

- [Streamlit component-template](https://github.com/streamlit/component-template)

Never hand-scaffold the package/manifest/build layout and never copy/paste a packaged component scaffold from blog posts, gists, docs, or other internet sources.

If a request starts from a non-template scaffold, stop and regenerate from the template first, then port logic into the generated project.

Follow your generated project's README. **Only keep reading if you need to debug template wiring or customize behavior after template generation.**

## Contents

- Agent policy: template-only (mandatory)
- Prerequisites (packaged components)
- Start inline, then graduate to packaged
- Frontend framework note (React is optional)
- TypeScript support (recommended)
- Generate a new CCv2 component project
- Dev loop (template default)
- Packaged component workflow (copy/paste checklist)
- Verify the build output (prevents most load failures)
- React template data flow (critical — don't skip `index.tsx`)
- Template invariants (don’t break these)
- Rename checklist (avoid placeholder-name drift)
- Allowed customizations (after template generation only)
- Verification recommendation

### Agent policy: template-only (mandatory)

If the request is for a packaged CCv2 component:

- Start from the official template first (no exceptions).
- Never manually scaffold a custom package/manifest/build layout before template generation.
- Never copy a packaged component scaffold from the internet, even as a "starting point."
- If given existing non-template scaffolding, regenerate from the template and migrate code into it.
- Customize only after generation so you retain known-good packaging defaults.
- **NEVER introduce v1 APIs when customizing the template.** The template generates correct v2 code. When you modify `__init__.py`, JS/TS files, or `example.py`, use ONLY v2 APIs (`st.components.v2.component`, `setStateValue`, `setTriggerValue`, `parentElement`, `data`). Do NOT import `st.components.v1`, do NOT use `declare_component()`, do NOT use `Streamlit.setComponentValue()` or any v1 JavaScript globals. See "v1 contamination" in [ccv2-troubleshooting.md](ccv2-troubleshooting.md) for the full banned list.

### Prerequisites (packaged components)

- **Python build tooling**: `uv` (recommended) + `cookiecutter`.
- **Frontend build tooling**: Node.js + npm.

### Start inline, then graduate to packaged

Inline components are great for getting started quickly. Move to a packaged component when you hit any of these:

- You need **multiple frontend files** (components/modules) instead of one big string.
- You want to pull in **frontend libraries** (npm deps) and run a bundler.
- You need **tests**, CI, versioning, or distribution (PyPI/private index).

### Frontend framework note (React is optional)

The official Streamlit `component-template` v2 supports both **React + TypeScript (Vite)** and **Pure TypeScript (Vite)** (no React). CCv2 also works with **any frontend framework that compiles to JavaScript** (Svelte, Vue, Angular, vanilla TS/JS, etc.).

The only requirement is that you produce JS/CSS assets into your component’s `asset_dir`, then register them from Python via `js="..."` and `css="..."` using **asset-dir-relative** paths/globs. `html=` is always inline markup, never a path: `html="index.html"` renders the literal text.

### TypeScript support (recommended)

For end-to-end type safety while authoring the frontend, install `@streamlit/component-v2-lib`:

- [npm package](https://www.npmjs.com/package/@streamlit/component-v2-lib)
- [docs](https://docs.streamlit.io/develop/api-reference/custom-components/component-v2-lib)

It provides TypeScript types like `FrontendRenderer` / `FrontendRendererArgs` so your `export default` renderer gets a **typed** `data` payload and typed state/trigger keys via generics.

### Generate a new CCv2 component project

This command is the required starting point for every packaged CCv2 component:

```bash
uvx --from cookiecutter cookiecutter gh:streamlit/component-template --directory cookiecutter/v2
```

If you run this non-interactively, pass explicit cookiecutter values (do not rely on defaults):

Template keys:

- `author_name`
- `author_email`
- `project_name`
- `package_name`
- `import_name`
- `description`
- `open_source_license`
- `framework`

Recommended non-interactive invocation:

This sample uses a **hypothetical breadcrumb component** name so the values are concrete and meaningful:

```bash
uvx --from cookiecutter cookiecutter gh:streamlit/component-template \
  --directory cookiecutter/v2 \
  --no-input \
  author_name="Your Name" \
  author_email="you@example.com" \
  project_name="Streamlit Breadcrumbs" \
  package_name="streamlit-breadcrumbs" \
  import_name="streamlit_breadcrumbs" \
  description="Packaged Streamlit CCv2 breadcrumb component" \
  open_source_license="Apache-2.0" \
  framework="React + Typescript"
```

Notes:

- Choice values must match template options exactly (`framework` is `"React + Typescript"` or `"Pure Typescript"`).
- Passing all keys avoids template placeholder names and post-generation rename churn.

Offline/airgapped:

```bash
uvx --from cookiecutter cookiecutter /path/to/component-template --directory cookiecutter/v2
```

### Dev loop (template default)

From the generated project:

1. Activate the target project environment before Python/uv commands:

   ```bash
   source /path/to/project/.venv/bin/activate
   ```

2. Build the frontend assets (from `<import_name>/frontend`):

   ```bash
   npm i
   npm run build
   ```

3. Editable install (project root containing `pyproject.toml`):

   ```bash
   uv pip install -e . --force-reinstall
   ```

4. Run the example app with Streamlit:

   ```bash
   streamlit run example.py
   ```

Why this order:

- Building first ensures `asset_dir` contains the expected files before install/use.
- Reinstalling editable after key renames keeps metadata and import paths in sync.

### Packaged component workflow (copy/paste checklist)

Use this when debugging or customizing after generation; it's designed to prevent the common "built assets exist but Streamlit can't load them" failure modes.

```
Packaged CCv2 checklist
- [ ] Generate project from `component-template` v2
- [ ] Confirm this is template-generated (not hand-scaffolded, not copied from internet snippets)
- [ ] Activate the target project environment before Python/uv commands
- [ ] Rename template defaults (`streamlit-component-x`, `streamlit_component_x`, etc.) if needed
- [ ] Build frontend assets into the manifest’s `asset_dir` (template: `frontend/build/`)
- [ ] Editable install the Python package (`uv pip install -e . --force-reinstall`)
- [ ] Verify `js=`/`css=` globs match exactly one file each under `asset_dir`
- [ ] Run via `streamlit run ...` and confirm the component renders/events work
- [ ] If something breaks: read `ccv2-troubleshooting.md`, fix, rebuild, re-verify glob uniqueness
```

### Verify the build output (prevents most load failures)

- Ensure the manifest’s `asset_dir` exists and contains the built assets.
- Ensure each glob you register from Python matches **exactly one** file under `asset_dir`:
  - Typical: `js="index-*.js"` and `css="index-*.css"`
  - If multiple matches: clean the build output (template: `npm run clean`) and rebuild.

### React template data flow (critical — don't skip `index.tsx`)

The React cookiecutter template has a **three-file data flow**. When you pass `data={...}` from Python, it flows through all three files before reaching the rendered component:

1. **`__init__.py`** — Python wrapper sends `data={"name": name, "testId": test_id, ...}` to the frontend
2. **`index.tsx`** — the bridge file that destructures `data` and passes props to the React component: `const { name, testId } = data;` → `<MyComponent name={name} testId={testId} />`
3. **`MyComponent.tsx`** — receives props and renders the UI: `<button data-testid={testId}>...</button>`

**You MUST edit all three files** when adding new data fields. The most common mistake is editing `__init__.py` and `MyComponent.tsx` but forgetting `index.tsx`. If you skip `index.tsx`, your new data fields are sent from Python but never reach the React component — props will be `undefined`.

**`data-testid` propagation**: When adding `data-testid` attributes for QA/testing, ensure the test ID value flows through the entire chain:
- Python sends it via `data={"testId": "my-button"}`
- `index.tsx` extracts it: `const { testId } = data;` and passes it: `<MyComponent testId={testId} />`
- `MyComponent.tsx` renders it: `<button data-testid={testId}>...</button>`

If any layer is missing, the `data-testid` won't appear on the rendered element.

### Template invariants (don't break these)

You typically shouldn't need to touch these, but they explain most "why won't this load?" failures:

- **Component key**: the Python registration key must match the manifest: `"<project.name>.<component.name>"`. **Do NOT change the component name that the template generates** — the template wires the fully-qualified name correctly across `__init__.py`, the inner `pyproject.toml` manifest, and the `MANIFEST.in`. Changing it in one place without updating all others will cause `StreamlitAPIException: Component '...' must be declared in pyproject.toml with asset_dir to use file-backed js`.
- **Manifest must ship inside the Python package**: the template places a minimal CCv2 manifest at `<import_name>/pyproject.toml` with `asset_dir = "frontend/build"`. Do NOT rename `[[tool.streamlit.component.components]]` to anything else — this exact TOML key is required.
- **Asset paths are asset-dir-relative strings**: `js="index-*.js"` (template default output) or `js="assets/index-*.js"` (if you configured an `assets/` subdir).
- **Globs must match exactly one file**: if `index-*.js` matches multiple hashed builds, clean the build output (`npm run clean`) and rebuild.

### Rename checklist (avoid placeholder-name drift)

Template defaults like `streamlit-component-x` / `streamlit_component_x` should be replaced everywhere early.

Rename all of these together:

- Root folder name (optional but recommended for clarity).
- Distribution name (`[project].name`) in root `pyproject.toml`.
- Import package directory (`streamlit_<real_name>`).
- In-package manifest file and contents (`<import_name>/pyproject.toml`).
- Wrapper registration key:
  - `st.components.v2.component("<project.name>.<component.name>", ...)`
- `MANIFEST.in` and `[tool.setuptools.*]` references.
- README/example imports and frontend package name.

### Allowed customizations (after template generation only)

Keep the blast radius small:

- If you change output layout, update only the `js=`/`css=` asset-dir-relative globs in the Python wrapper.
- For Vite, keep `base: "./"` so relative URLs work when served from Streamlit’s component URLs.

### Verification recommendation

Validate packaged components with `streamlit run ...`, not plain `python -c "import ..."` checks.

- Streamlit discovers component manifests as part of runtime setup.
- Plain import checks can report false-negative `asset_dir` registration errors for otherwise-correct packaged components.
