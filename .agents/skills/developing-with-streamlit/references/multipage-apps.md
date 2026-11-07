
# Streamlit multi-page apps

Structure and navigation for apps with multiple pages.

## Directory structure

```
streamlit_app.py          # Main entry point
app_pages/
    home.py
    analytics.py
    settings.py
```

**Important:** Name your pages directory `app_pages/` (not `pages/`). Using `pages/` conflicts with Streamlit's old auto-discovery API and can cause unexpected behavior.

## Main module

Give every `st.Page` a context-appropriate Material Symbols icon (`:material/icon_name:`) so navigation is easy to scan. Choose a name from the [supported icon list](https://raw.githubusercontent.com/streamlit/streamlit/refs/heads/develop/lib/streamlit/material_icon_names.py) because unsupported names raise an error.

```python
# streamlit_app.py
import streamlit as st

# Initialize user-specific state (shared across pages)
if "selected_project" not in st.session_state:
    st.session_state.selected_project = None

# Define navigation
page = st.navigation(
    [
        st.Page("app_pages/home.py", title="Home", icon=":material/home:"),
        st.Page(
            "app_pages/analytics.py", title="Analytics", icon=":material/bar_chart:"
        ),
        st.Page("app_pages/settings.py", title="Settings", icon=":material/settings:"),
    ]
)

# App-level UI runs before page content
# Useful for shared elements like titles
st.title(page.title, icon=page.icon)

page.run()
```

**Note:** When you handle titles in `streamlit_app.py`, individual pages should NOT use `st.title` again.

## Navigation position

**Few pages (3-7) → Top navigation:**

```python
page = st.navigation(
    [
        st.Page("app_pages/home.py", title="Home", icon=":material/home:"),
        st.Page(
            "app_pages/analytics.py", title="Analytics", icon=":material/bar_chart:"
        ),
        st.Page("app_pages/settings.py", title="Settings", icon=":material/settings:"),
    ],
    position="top",
)
```

Creates a clean horizontal menu. Great for simple apps. Sections are supported too—they appear as dropdowns in the top nav.

**Many pages or nested sections → Sidebar:**

```python
page = st.navigation(
    {
        "Main": [
            st.Page("app_pages/home.py", title="Home", icon=":material/home:"),
            st.Page(
                "app_pages/analytics.py",
                title="Analytics",
                icon=":material/bar_chart:",
            ),
        ],
        "Admin": [
            st.Page(
                "app_pages/settings.py", title="Settings", icon=":material/settings:"
            ),
            st.Page("app_pages/users.py", title="Users", icon=":material/group:"),
        ],
    },
    position="sidebar",
)
```

**Mixed: Some pages ungrouped:**

Use an empty string key `""` for pages that shouldn't be in a section. These ungrouped pages always appear first, before any named groups. Put all ungrouped pages in a single `""` key:

```python
page = st.navigation(
    {
        "": [
            st.Page("app_pages/home.py", title="Home", icon=":material/home:"),
            st.Page("app_pages/about.py", title="About", icon=":material/info:"),
        ],
        "Analytics": [
            st.Page(
                "app_pages/dashboard.py",
                title="Dashboard",
                icon=":material/dashboard:",
            ),
            st.Page(
                "app_pages/reports.py",
                title="Reports",
                icon=":material/description:",
            ),
        ],
    },
    position="top",
)
```

## Page modules

```python
# app_pages/analytics.py
import streamlit as st

# Access shared state
project = st.session_state.selected_project
user = st.session_state.user

# Page-specific content (title is handled in streamlit_app.py)
data = fetch_analytics(user.id, project)
st.line_chart(data)
```

## Global state

Initialize state in the main module only if it's needed across multiple pages. Pages run in their own namespace, so a function defined in `streamlit_app.py` isn't visible to them; put shared cached helpers in a module and import them where needed:

```python
# utils/clients.py — shared resources: use @st.cache_resource, NOT session_state
@st.cache_resource
def get_api_client():
    return init_client()
```

```python
# streamlit_app.py — user-specific state: use session_state
st.session_state.user = get_user()
st.session_state.settings = load_settings()
```

**Why main module (for global state):**
- Runs before every page
- Ensures state is initialized
- Single source of truth

**Use `@st.cache_resource` for shared resources** (API clients, DB connections, ML models). Use `st.session_state` only for per-user data (selections, form inputs, preferences).

## Page-specific state

Use prefixed keys for page-specific state:

```python
# app_pages/analytics.py
if "analytics_date_range" not in st.session_state:
    st.session_state.analytics_date_range = default_range()
```

## Conditional pages

Show different pages based on user role, authentication, or any other condition by building the pages list dynamically:

```python
# streamlit_app.py
import streamlit as st

pages = [st.Page("app_pages/home.py", title="Home", icon=":material/home:")]

if st.user.is_logged_in:
    pages.append(
        st.Page(
            "app_pages/dashboard.py", title="Dashboard", icon=":material/bar_chart:"
        )
    )

if st.session_state.get("is_admin"):
    pages.append(
        st.Page("app_pages/admin.py", title="Admin", icon=":material/settings:")
    )

page = st.navigation(pages)
page.run()
```

Common conditions for showing/hiding pages:
- `st.user.is_logged_in` for authenticated users
- `st.session_state` flags (roles, permissions, feature flags)
- Environment variables or secrets
- Time-based access (e.g., beta features)

## Imports from pages

When importing from page files in `app_pages/`, always import from the root directory perspective:

```python
# app_pages/dashboard.py - GOOD
from utils.data import load_sales_data

# app_pages/dashboard.py - BAD (don't use relative imports)
from ..utils.data import load_sales_data
```

## References

- [st.navigation](https://docs.streamlit.io/develop/api-reference/navigation/st.navigation)
- [st.Page](https://docs.streamlit.io/develop/api-reference/navigation/st.page)
- [st.session_state](https://docs.streamlit.io/develop/api-reference/caching-and-state/st.session_state)
