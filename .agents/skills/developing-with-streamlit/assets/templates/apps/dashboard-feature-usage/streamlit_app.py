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

"""API usage dashboard template.

Demonstrates:
- Segmented control for category selection
- Multiselect for endpoint filtering
- Starter kits / presets for quick selection
- Time series visualization with normalization
- Metric cards with 28-day deltas
- Rolling average options
- ``@st.cache_data(ttl=...)`` loader to keep data fresh and bounded
- Conditional rendering: the collapsed "Raw data" expander only computes and
  sends its dataframe to the browser when it is open (``on_change="rerun"``)

This template uses synthetic data. Replace ``generate_api_data()`` with your
actual data source (e.g., Snowflake queries, APIs, etc.).
"""

from datetime import date, timedelta

import altair as alt
import numpy as np
import pandas as pd

import streamlit as st

st.set_page_config(
    page_title="API Usage Dashboard",
    page_icon=":material/api:",
    layout="wide",
)


# =============================================================================
# Synthetic Data Generation (Replace with your data source)
# =============================================================================

# API categories and their endpoints
API_CATEGORIES = {
    "Users": [
        "/users",
        "/users/{id}",
        "/users/me",
        "/users/search",
        "/users/bulk",
        "/users/export",
    ],
    "Orders": [
        "/orders",
        "/orders/{id}",
        "/orders/create",
        "/orders/cancel",
        "/orders/refund",
        "/orders/status",
    ],
    "Products": [
        "/products",
        "/products/{id}",
        "/products/search",
        "/products/categories",
        "/products/inventory",
    ],
    "Analytics": [
        "/analytics/events",
        "/analytics/metrics",
        "/analytics/reports",
        "/analytics/dashboards",
    ],
}

# Starter kits - predefined endpoint selections
STARTER_KITS = {
    "None": [],
    "Core CRUD": ["/users", "/users/{id}", "/orders", "/orders/{id}"],
    "Search": ["/users/search", "/products/search", "/products/categories"],
    "Analytics": ["/analytics/events", "/analytics/metrics", "/analytics/reports"],
    "High Volume": ["/users", "/products", "/orders", "/analytics/events"],
}

ROLLING_OPTIONS = {"Raw": 1, "7-day average": 7, "28-day average": 28}


def generate_api_data(
    endpoints: list[str],
    start_date: date,
    end_date: date,
) -> pd.DataFrame:
    """Generate synthetic API usage data.

    Replace this function with your actual data source.
    """
    rng = np.random.default_rng(42)

    dates = pd.date_range(start=start_date, end=end_date, freq="D")
    records = []

    for endpoint in endpoints:
        # Each endpoint has different base traffic and growth
        base = rng.integers(1000, 50000)
        growth = rng.uniform(0.0005, 0.003)

        for i, dt in enumerate(dates):
            # Base trend with growth
            trend = base * (1 + growth) ** i

            # Weekly seasonality (lower on weekends)
            if dt.dayofweek >= 5:
                trend *= 0.4

            # Random noise
            value = trend * rng.uniform(0.85, 1.15)

            records.append(
                {
                    "date": dt,
                    "endpoint": endpoint,
                    "request_count": int(value),
                }
            )

    return pd.DataFrame(records)


@st.cache_data(ttl="1h", show_spinner="Loading API usage data...")
def load_api_data() -> pd.DataFrame:
    """Load all API usage data (cached). Replace with your data source."""
    end_date = date.today() - timedelta(days=1)
    start_date = end_date - timedelta(days=365)

    all_endpoints = []
    for endpoints in API_CATEGORIES.values():
        all_endpoints.extend(endpoints)

    return generate_api_data(all_endpoints, start_date, end_date)


def apply_rolling_average(df: pd.DataFrame, window: int) -> pd.DataFrame:
    """Apply rolling average to request data."""
    if window == 1:
        return df

    result = df.copy()
    result["request_count"] = result.groupby("endpoint")["request_count"].transform(
        lambda x: x.rolling(window, min_periods=1).mean()
    )
    return result


def normalize_data(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize request counts to percentages (share of total per day)."""
    result = df.copy()
    daily_totals = result.groupby("date")["request_count"].transform("sum")
    result["request_count"] /= daily_totals
    return result


def calculate_delta(df: pd.DataFrame, endpoint: str) -> tuple[float, float | None]:
    """Calculate 28-day delta for an endpoint."""
    endpoint_data = df[df["endpoint"] == endpoint].sort_values("date")

    if len(endpoint_data) < 2:
        return endpoint_data["request_count"].iloc[-1], None

    latest = endpoint_data["request_count"].iloc[-1]

    if len(endpoint_data) > 28:
        previous = endpoint_data["request_count"].iloc[-29]
    else:
        previous = endpoint_data["request_count"].iloc[0]

    delta = latest - previous
    return latest, delta


# =============================================================================
# Page Layout
# =============================================================================

# Load data
raw_data = load_api_data()

# Header
st.markdown("# API Usage :material/api:")
st.caption("Select an API category to explore endpoint usage over time.")

# Category selection (not centered)
category = st.segmented_control(
    "Select category",
    options=[
        ":material/person: Users",
        ":material/shopping_cart: Orders",
        ":material/inventory_2: Products",
        ":material/analytics: Analytics",
    ],
    default=":material/person: Users",
    label_visibility="collapsed",
)

if not category:
    st.warning("Please select a category above.", icon=":material/warning:")
    st.stop()

# Map display name to category key
category_map = {
    ":material/person: Users": "Users",
    ":material/shopping_cart: Orders": "Orders",
    ":material/inventory_2: Products": "Products",
    ":material/analytics: Analytics": "Analytics",
}
selected_category = category_map[category]

st.subheader(f"{category} endpoints")

# Layout: filters on left, chart on right
filter_col, chart_col = st.columns([1, 2])

with filter_col:
    # Metric selection
    with st.expander("Metric", expanded=True, icon=":material/analytics:"):
        rolling_label = st.segmented_control(
            "Time aggregation",
            list(ROLLING_OPTIONS.keys()),
            default="7-day average",
            label_visibility="collapsed",
        )

        if rolling_label is None:
            st.caption("Please select a time aggregation.")
            st.stop()

        rolling_window = ROLLING_OPTIONS[rolling_label]

        normalize = st.toggle(
            "Normalize",
            value=False,
            help="Normalize to show percentage share of total requests",
        )

    # Starter kits
    with st.expander("Starter kits", expanded=True, icon=":material/auto_awesome:"):
        starter_kit = st.pills(
            "Quick select",
            options=list(STARTER_KITS.keys()),
            default="None",
            label_visibility="collapsed",
        )

    # Endpoint selection
    available_endpoints = API_CATEGORIES[selected_category]

    # Determine default selection based on starter kit
    if starter_kit and starter_kit != "None":
        default_endpoints = [
            e for e in STARTER_KITS[starter_kit] if e in available_endpoints
        ]
    else:
        default_endpoints = available_endpoints[:4]  # First 4 endpoints

    with st.expander("Endpoints", expanded=True, icon=":material/checklist:"):
        selected_endpoints = st.multiselect(
            "Select endpoints",
            options=available_endpoints,
            default=default_endpoints,
            label_visibility="collapsed",
        )

# Filter and process data
if not selected_endpoints:
    with chart_col:
        st.info(
            "Select at least one endpoint to view usage data.", icon=":material/info:"
        )
    st.stop()

filtered_data = raw_data[raw_data["endpoint"].isin(selected_endpoints)].copy()
filtered_data = apply_rolling_average(filtered_data, rolling_window)

if normalize:
    filtered_data = normalize_data(filtered_data)

with chart_col:
    # Latest metrics
    with st.expander("Latest numbers", expanded=True, icon=":material/numbers:"):
        metrics_row = st.container(horizontal=True)

        for endpoint in selected_endpoints:
            latest, delta = calculate_delta(filtered_data, endpoint)

            if normalize:
                value_str = f"{latest:.2%}"
                delta_str = f"{delta:+.2%}" if delta is not None else None
            else:
                value_str = f"{latest:,.0f}"
                delta_str = f"{delta:+,.0f}" if delta is not None else None

            metrics_row.metric(
                label=endpoint,
                value=value_str,
                delta=delta_str,
                border=True,
            )

    # Time series chart
    with st.expander("Time series", expanded=True, icon=":material/show_chart:"):
        y_format = ".1%" if normalize else ",.0f"
        y_title = "Share of requests" if normalize else "Request count"

        chart = (
            alt.Chart(filtered_data)
            .mark_line()
            .encode(
                x=alt.X("date:T", title="Date"),
                y=alt.Y(
                    "request_count:Q", title=y_title, axis=alt.Axis(format=y_format)
                ),
                color=alt.Color(
                    "endpoint:N", title="Endpoint", legend=alt.Legend(orient="bottom")
                ),
                tooltip=[
                    alt.Tooltip("date:T", title="Date", format="%Y-%m-%d"),
                    alt.Tooltip("endpoint:N", title="Endpoint"),
                    alt.Tooltip("request_count:Q", title="Requests", format=y_format),
                ],
            )
            .properties(height=450)
            .interactive()
        )

        st.altair_chart(
            chart,
            alt=(
                f"{rolling_label} share of requests by endpoint over time"
                if normalize
                else f"{rolling_label} request count by endpoint over time"
            ),
        )

# Raw data section. The expander is collapsed by default, so guard the
# dataframe behind `.open` (enabled by `on_change="rerun"`) to avoid building
# and sending it to the browser until the user actually opens the section.
raw_data_section = st.expander(
    "Raw data", expanded=False, icon=":material/table:", on_change="rerun"
)
if raw_data_section.open:
    with raw_data_section:
        display_df = filtered_data.copy()
        column_config = {}
        if normalize:
            column_config["request_count"] = st.column_config.NumberColumn(
                "Requests", format="percent"
            )
        st.dataframe(
            display_df,
            hide_index=True,
            column_config=column_config or None,
            alt="Filtered endpoint request data",
        )
