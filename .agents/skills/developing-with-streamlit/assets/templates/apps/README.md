# Streamlit Dashboard App Templates

This directory contains ready-to-use dashboard templates for Streamlit. Each template demonstrates best practices for building data-driven dashboards with modern UI patterns.

## Available Templates

### Public Demo Templates

These templates are based on official Streamlit demo apps and work out of the box:

| Template | Description | Key Features |
|----------|-------------|--------------|
| **dashboard-seattle-weather** | Weather data exploration dashboard | `st.metric`, `st.pills`, `st.altair_chart`, year comparison |
| **dashboard-stock-peers** | Stock peer analysis and comparison | `st.multiselect`, normalized charts, peer average calculation |

### Analytics Dashboard Templates

These templates demonstrate common dashboard patterns with synthetic data. Replace the data generation functions with your actual data sources:

| Template | Description | Key Features |
|----------|-------------|--------------|
| **dashboard-metrics** | Core metrics dashboard with KPIs | `st.metric` KPI row with sparklines, `@st.fragment(parallel=True)` cards with `st.skeleton`, chart/table toggle, `st.popover` filters, TIME_RANGES (1M/6M/1Y/QTD/YTD/All) |
| **dashboard-feature-usage** | API endpoint usage analytics | Segmented control, starter kits, normalization toggle, rolling averages, conditional "Raw data" expander (`on_change="rerun"`) |
| **dashboard-companies** | Company leaderboard with drill-down | Interactive dataframe, sparkline columns, growth scores, custom cache spinner |
| **dashboard-compute** | Resource consumption monitoring | `@st.fragment(parallel=True)` with `st.skeleton`, `st.popover` filters, TIME_RANGES, line/bar toggle |

## Quick Start

### Run a Template Locally

```bash
# Navigate to a template directory
cd assets/templates/apps/dashboard-metrics

# Sync dependencies from pyproject.toml
uv sync

# Run the app
uv run streamlit run streamlit_app.py
```

## Template Structure

Each template follows this structure:

```
dashboard-{name}/
├── streamlit_app.py    # Main application code
└── pyproject.toml      # Dependencies and metadata
```

## Canonical Patterns

When creating new templates or adapting existing ones, follow these patterns for consistency.

### Page Configuration

Set page config near the top of the script, with `layout="wide"` and a Material icon:

```python
st.set_page_config(
    page_title="My Dashboard",
    page_icon=":material/monitoring:",
    layout="wide",
)
```

### Constants

Use these standard constant names:

```python
TIME_RANGES = ["1M", "6M", "1Y", "QTD", "YTD", "All"]
CHART_HEIGHT = 300  # Standard chart height in pixels
```

### Time Range Filtering

All dashboard templates that support time filtering use the same `filter_by_time_range` function:

```python
def filter_by_time_range(df: pd.DataFrame, x_col: str, time_range: str) -> pd.DataFrame:
    """Filter dataframe by time range."""
    if time_range == "All" or df.empty:
        return df

    df = df.copy()
    df[x_col] = pd.to_datetime(df[x_col])
    max_date = df[x_col].max()

    if time_range == "1M":
        min_date = max_date - timedelta(days=30)
    elif time_range == "6M":
        min_date = max_date - timedelta(days=180)
    elif time_range == "1Y":
        min_date = max_date - timedelta(days=365)
    elif time_range == "QTD":
        quarter_month = ((max_date.month - 1) // 3) * 3 + 1
        min_date = pd.Timestamp(date(max_date.year, quarter_month, 1))
    elif time_range == "YTD":
        min_date = pd.Timestamp(date(max_date.year, 1, 1))
    else:
        return df

    filtered: pd.DataFrame = df[df[x_col] >= min_date]
    return filtered
```

### Popover Filters

Compact filter controls using `st.popover`:

```python
with st.popover("Filters", type="tertiary"):
    line_options = st.pills("Lines", ["Daily", "7-day MA"], selection_mode="multi")
    time_range = st.segmented_control("Time range", TIME_RANGES, default="All")
```

### Page Header with Reset Button

```python
def render_page_header(title: str):
    """Render page header with title and reset button."""
    with st.container(
        horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"
    ):
        st.markdown(title)
        if st.button(":material/restart_alt: Reset", type="tertiary"):
            st.session_state.clear()
            st.rerun()
```

### Independent and parallel card updates with @st.fragment

Wrap each card in `@st.fragment` so widget interactions rerun only that card,
not the whole page. If a dashboard has multiple cards with independent,
compute-intensive data loads, add `parallel=True` so those cards run
concurrently on a full app rerun. Wrap the loading body in `st.skeleton` so each
card shows a placeholder until its data is ready:

```python
@st.fragment(parallel=True)
def metric_card(metric_name: str):
    with st.container(border=True):
        st.markdown(f"**{metric_name}**")  # Stays stable while the body loads
        with st.skeleton(height=300):
            data = load_metric(metric_name)  # Cached; loads in parallel
            st.line_chart(data, alt=f"{metric_name} over time")
```

Keep `st.dialog` / `st.switch_page` and writes to containers created *outside*
the fragment out of parallel fragments — gate those behind a widget interaction
instead, where the fragment reruns sequentially.

### Data Loading with Caching

Cache the expensive load and bound it with a `ttl` (and/or `max_entries`) so the
cache stays fresh and doesn't grow without limit. Use a custom spinner message
for loaders that run directly in the page. Use `show_spinner=False` only when a
surrounding loading UI, such as `st.skeleton`, already provides feedback:

```python
@st.cache_data(ttl="1h", show_spinner="Loading metric data...")
def load_metric_data() -> pd.DataFrame:
    """Load metric data. Replace with your actual data source."""
    # Replace this with:
    # - API call
    # - Database query
    # - Data warehouse query via st.connection
    return generate_synthetic_data()
```

Guidelines: real-time data → `ttl="1m"`; metrics/reports → `ttl="5m"`–`"15m"`;
reference data → `ttl="1h"` or more; static data → no TTL. Use `max_entries` for
parameterized loaders so per-argument entries stay bounded.

## Dependencies

All templates require Python >=3.11 and use:
- `streamlit`
- `altair>=5.5.0`
- `pandas>=2.2.3`
- `numpy>=1.26.0` (most templates)
