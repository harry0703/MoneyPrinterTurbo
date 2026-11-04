# Copyright (c) Streamlit Inc. (2018-2022) Snowflake Inc. (2022-2026)
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Metrics dashboard template.

Demonstrates:
- KPI row of bordered ``st.metric`` values with deltas and sparklines
- Time series visualization with Altair (line, area, bar, point charts)
- Metric cards with chart/table toggle and popover filters
- Time range filtering (1M, 6M, 1Y, QTD, YTD, All)
- Line options (Daily, 7-day MA)
- ``@st.cache_data(ttl=...)`` per-metric loaders to keep data fresh and bounded
- ``@st.fragment(parallel=True)`` cards that load concurrently on full reruns
  and rerun in isolation on widget interactions
- ``st.skeleton`` placeholders so each card fills in as soon as its data is ready

This template uses synthetic data. Replace the ``generate_*_data()`` functions
with your own data sources (e.g., Snowflake queries, APIs, etc.).
"""

import hashlib
from datetime import date, timedelta

import altair as alt
import numpy as np
import pandas as pd

import streamlit as st

st.set_page_config(
    page_title="Metrics Dashboard",
    page_icon=":material/monitoring:",
    layout="wide",
)


# =============================================================================
# Constants
# =============================================================================

TIME_RANGES = ["1M", "6M", "1Y", "QTD", "YTD", "All"]
CHART_HEIGHT = 300
KPI_HEIGHT = 215  # Approximate height of a bordered st.metric with a sparkline

# Per-metric generation settings. Replace with the metrics you actually track.
METRIC_CONFIG: dict[str, dict[str, float]] = {
    "users": {"base_value": 5000, "growth_rate": 0.002},
    "sessions": {"base_value": 15000, "growth_rate": 0.003},
    "revenue": {"base_value": 50000, "growth_rate": 0.001},
    "conversions": {"base_value": 500, "growth_rate": 0.0015},
}


# =============================================================================
# Synthetic Data Generation (Replace with your data source)
# =============================================================================


def generate_metric_data(
    metric_name: str,
    start_date: date,
    end_date: date,
    base_value: float = 1000,
    growth_rate: float = 0.001,
    noise_factor: float = 0.1,
) -> pd.DataFrame:
    """Generate synthetic time series data for a metric.

    Replace this function with your actual data source, e.g.:
    - Snowflake query
    - API call
    - Database query
    """
    seed = int(hashlib.sha256(metric_name.encode()).hexdigest(), 16) % 2**32
    rng = np.random.default_rng(seed)

    dates = pd.date_range(start=start_date, end=end_date, freq="D")
    n_days = len(dates)

    # Base trend with growth
    trend = base_value * (1 + growth_rate) ** np.arange(n_days)

    # Add weekly seasonality (lower on weekends)
    day_of_week = dates.dayofweek
    seasonality = np.where(day_of_week >= 5, 0.7, 1.0)
    trend *= seasonality

    # Add noise
    noise = rng.normal(1, noise_factor, n_days)
    values = trend * noise

    # Calculate rolling averages
    df = pd.DataFrame(
        {
            "ds": dates,
            "daily_value": values,
        }
    )
    df["value_7d_ma"] = df["daily_value"].rolling(7, min_periods=1).mean()

    return df


@st.cache_data(ttl="1h", show_spinner=False)
def load_metric(metric_name: str) -> pd.DataFrame:
    """Load a single metric's time series (cached per metric).

    Each metric is cached on its own so the metric cards can load
    concurrently as parallel fragments. Replace the body with your data
    source (Snowflake query, API call, etc.). The ``ttl`` keeps the cache
    fresh; add ``max_entries`` if the set of metric names can grow large so
    the cache stays bounded.
    """
    end_date = date.today() - timedelta(days=1)
    start_date = end_date - timedelta(days=730)  # 2 years of data
    config = METRIC_CONFIG[metric_name]
    return generate_metric_data(metric_name, start_date, end_date, **config)


# =============================================================================
# Chart Utilities
# =============================================================================


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


def _melt_chart_data(
    df: pd.DataFrame, x_col: str, y_cols: list[str], labels: list[str]
) -> pd.DataFrame:
    """Melt wide data into long form and re-label the series column."""
    melted = df.melt(
        id_vars=[x_col],
        value_vars=y_cols,
        var_name="series",
        value_name="value",
    )
    label_map = dict(zip(y_cols, labels, strict=True))
    melted["series"] = melted["series"].map(label_map)
    return melted


def _chart_tooltip(x_col: str, x_title: str = "Date") -> list[alt.Tooltip]:
    """Standard tooltip for melted chart data."""
    return [
        alt.Tooltip(f"{x_col}:T", title=x_title, format="%Y-%m-%d"),
        alt.Tooltip("series:N", title="Series"),
        alt.Tooltip("value:Q", title="Value", format=",.0f"),
    ]


def render_line_chart(
    df: pd.DataFrame,
    x_col: str,
    y_cols: list[str],
    labels: list[str],
    height: int = CHART_HEIGHT,
) -> alt.Chart:
    """Render a multi-line chart."""
    melted = _melt_chart_data(df, x_col, y_cols, labels)

    chart: alt.Chart = (
        alt.Chart(melted)
        .mark_line()
        .encode(
            x=alt.X(f"{x_col}:T", title=None),
            y=alt.Y("value:Q", title=None, scale=alt.Scale(zero=False)),
            color=alt.Color("series:N", title=None, legend=alt.Legend(orient="bottom")),
            strokeDash=alt.condition(
                alt.datum.series == "7-day MA",
                alt.value([5, 5]),
                alt.value([0]),
            ),
            tooltip=_chart_tooltip(x_col),
        )
        .properties(height=height)
    )
    return chart


def render_area_chart(
    df: pd.DataFrame,
    x_col: str,
    y_cols: list[str],
    labels: list[str],
    height: int = CHART_HEIGHT,
) -> alt.Chart:
    """Render a stacked area chart."""
    melted = _melt_chart_data(df, x_col, y_cols, labels)

    chart: alt.Chart = (
        alt.Chart(melted)
        .mark_area(opacity=0.6, line=True)
        .encode(
            x=alt.X(f"{x_col}:T", title=None),
            y=alt.Y("value:Q", title=None, scale=alt.Scale(zero=False)),
            color=alt.Color("series:N", title=None, legend=alt.Legend(orient="bottom")),
            tooltip=_chart_tooltip(x_col),
        )
        .properties(height=height)
    )
    return chart


def render_bar_chart(
    df: pd.DataFrame,
    x_col: str,
    y_cols: list[str],
    labels: list[str],
    height: int = CHART_HEIGHT,
) -> alt.Chart:
    """Render a bar chart (weekly aggregation for readability)."""
    df = df.copy()
    df[x_col] = pd.to_datetime(df[x_col])
    df["week"] = df[x_col].dt.to_period("W").dt.start_time

    agg_df = df.groupby("week")[y_cols].mean().reset_index()
    melted = _melt_chart_data(agg_df, "week", y_cols, labels)

    chart: alt.Chart = (
        alt.Chart(melted)
        .mark_bar(opacity=0.8)
        .encode(
            x=alt.X("week:T", title=None),
            y=alt.Y("value:Q", title=None, scale=alt.Scale(zero=False)),
            color=alt.Color("series:N", title=None, legend=alt.Legend(orient="bottom")),
            xOffset="series:N",
            tooltip=_chart_tooltip("week", x_title="Week"),
        )
        .properties(height=height)
    )
    return chart


def render_point_chart(
    df: pd.DataFrame,
    x_col: str,
    y_cols: list[str],
    labels: list[str],
    height: int = CHART_HEIGHT,
) -> alt.Chart:
    """Render a scatter/point chart with a dashed trend line for the 7-day MA."""
    melted = _melt_chart_data(df, x_col, y_cols, labels)

    points = (
        alt.Chart(melted)
        .mark_point(opacity=0.5, size=20)
        .encode(
            x=alt.X(f"{x_col}:T", title=None),
            y=alt.Y("value:Q", title=None, scale=alt.Scale(zero=False)),
            color=alt.Color("series:N", title=None, legend=alt.Legend(orient="bottom")),
            tooltip=_chart_tooltip(x_col),
        )
    )

    trend = (
        alt.Chart(melted[melted["series"] == "7-day MA"])
        .mark_line(strokeDash=[5, 5], strokeWidth=2)
        .encode(
            x=alt.X(f"{x_col}:T"),
            y=alt.Y("value:Q"),
            color=alt.Color("series:N"),
        )
    )

    chart: alt.Chart = (points + trend).properties(height=height)
    return chart


# =============================================================================
# KPI Card Component
# =============================================================================


@st.fragment(parallel=True)
def kpi_card(label: str, metric_name: str) -> None:
    """Display a bordered KPI card: the latest 7-day average and its 4-week change.

    Like the metric cards, each KPI is a parallel fragment that loads its own
    (cached) data inside ``st.skeleton``.
    """
    with st.skeleton(height=KPI_HEIGHT):
        # The last 4 weeks (29 daily points) of the 7-day average: the value is
        # the latest point, the delta compares it to the first one.
        trend = load_metric(metric_name)["value_7d_ma"].tail(29)
        change = round(trend.iloc[-1] / trend.iloc[0] - 1, 3)
        st.metric(
            label,
            f"{trend.iloc[-1]:,.0f}",
            # String deltas like "+0.0%" still get an arrow; pass 0 when flat.
            f"{change:+.1%}" if change else 0,
            delta_description="vs. 4 weeks ago",
            help="7-day average",
            chart_data=trend,
            border=True,
        )


# =============================================================================
# Metric Card Component
# =============================================================================


@st.fragment(parallel=True)
def metric_card(
    title: str,
    metric_name: str,
    chart_type: str = "line",
) -> None:
    """Display a metric card with chart/table toggle and popover filters.

    The card is a parallel fragment: on a full app rerun every card loads its
    own data concurrently, and on widget interactions (view toggle, filters)
    only this card reruns. The card's data is loaded inside ``st.skeleton`` so
    the title and controls stay stable while the chart fills in.

    Parameters
    ----------
    title : str
        Card title.
    metric_name : str
        Key into ``METRIC_CONFIG`` used to load this card's data and namespace
        this card's widget state.
    chart_type : str
        One of ``"line"``, ``"area"``, ``"bar"``, ``"point"``.
    """
    chart_renderers = {
        "line": render_line_chart,
        "area": render_area_chart,
        "bar": render_bar_chart,
        "point": render_point_chart,
    }
    render_chart = chart_renderers.get(chart_type, render_line_chart)

    with st.container(border=True):
        # Header row with title, view toggle, and filters. Keep it outside the
        # skeleton so the controls stay put while the chart loads.
        with st.container(
            horizontal=True,
            horizontal_alignment="distribute",
            vertical_alignment="center",
        ):
            st.markdown(f"**{title}**")

            view_mode = st.segmented_control(
                "View",
                options=[":material/show_chart:", ":material/table:"],
                default=":material/show_chart:",
                key=f"{metric_name}_view",
                label_visibility="collapsed",
            )

            with st.popover("Filters", type="tertiary"):
                line_options = st.pills(
                    "Lines",
                    options=["Daily", "7-day MA"],
                    default=["Daily", "7-day MA"],
                    selection_mode="multi",
                    key=f"{metric_name}_lines",
                )
                time_range = st.segmented_control(
                    "Time range",
                    options=TIME_RANGES,
                    default="All",
                    key=f"{metric_name}_time",
                )

        # Load this card's data and render inside a skeleton placeholder. The
        # skeleton shows while the (cached) loader runs, then clears once the
        # chart or table is rendered.
        with st.skeleton(height=CHART_HEIGHT):
            df = load_metric(metric_name)

            # Apply filters
            line_options = line_options or ["7-day MA"]
            filtered_df = filter_by_time_range(df, "ds", time_range or "All")

            # Determine which columns to show
            y_cols = []
            labels = []
            if "Daily" in line_options:
                y_cols.append("daily_value")
                labels.append("Daily")
            if "7-day MA" in line_options:
                y_cols.append("value_7d_ma")
                labels.append("7-day MA")

            # Render view
            if "table" in (view_mode or ""):
                st.dataframe(
                    filtered_df,
                    height=CHART_HEIGHT,
                    hide_index=True,
                    alt=f"{title} data",
                )
            elif y_cols:
                st.altair_chart(
                    render_chart(filtered_df, "ds", y_cols, labels),
                    alt=f"{title} over time",
                )
            else:
                st.info("Select at least one line option.")


# =============================================================================
# Page Header Component
# =============================================================================


def render_page_header(title: str) -> None:
    """Render page header with title and reset button."""
    with st.container(
        horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"
    ):
        st.markdown(title)
        if st.button(":material/restart_alt: Reset", type="tertiary"):
            st.session_state.clear()
            st.rerun()


# =============================================================================
# Page Layout
# =============================================================================

# Page header
render_page_header("# :material/monitoring: Metrics Dashboard")

# Each KPI and card loads its own data; as parallel fragments they load
# concurrently on the first run instead of blocking on each other.

# KPI row: horizontal containers wrap on narrow screens.
with st.container(horizontal=True):
    kpi_card("Active users", "users")
    kpi_card("Sessions", "sessions")
    kpi_card("Revenue", "revenue")
    kpi_card("Conversions", "conversions")

# Row 1: Users and Sessions
row1 = st.columns(2)

with row1[0]:
    metric_card("Active users", "users", chart_type="line")

with row1[1]:
    metric_card("Sessions", "sessions", chart_type="area")

# Row 2: Revenue and Conversions
row2 = st.columns(2)

with row2[0]:
    metric_card("Revenue", "revenue", chart_type="bar")

with row2[1]:
    metric_card("Conversions", "conversions", chart_type="point")
