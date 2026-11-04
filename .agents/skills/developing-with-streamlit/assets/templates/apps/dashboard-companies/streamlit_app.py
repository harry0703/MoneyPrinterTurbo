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

"""Company analytics dashboard template.

Demonstrates:
- Interactive dataframe with sparkline columns
- Segmented control for ranking (top spenders, gainers, shrinkers)
- Multi-select pills for account type filtering
- Time window filtering
- Growth score calculation
- Dialog popup for company details
- ``@st.cache_data(ttl=...)`` loader with a custom spinner message

This template uses synthetic data. Replace ``generate_company_data()`` with
your actual data source (e.g., Snowflake queries, CRM APIs, etc.).
"""

from datetime import date, timedelta

import numpy as np
import pandas as pd

import streamlit as st

st.set_page_config(
    page_title="Company Analytics",
    page_icon=":material/business:",
    layout="wide",
)


# =============================================================================
# Synthetic Data Generation (Replace with your data source)
# =============================================================================

COMPANY_NAMES = [
    "Acme Corp",
    "TechFlow Inc",
    "DataDriven Co",
    "CloudFirst Ltd",
    "InnovateTech",
    "ScaleUp Systems",
    "PrimeData Inc",
    "FutureStack",
    "ByteWise Corp",
    "StreamLine Co",
    "Quantum Labs",
    "NexGen Solutions",
    "AlphaMetrics",
    "BetaAnalytics",
    "GammaInsights",
    "DeltaData",
    "OmegaTech",
    "SigmaSoft",
    "ThetaCloud",
    "ZetaDigital",
]

ACCOUNT_TYPES = ["Enterprise", "Growth", "Startup", "Trial", "Internal"]
REGIONS = ["North America", "EMEA", "APAC", "LATAM"]
SEGMENTS = ["Technology", "Finance", "Healthcare", "Retail", "Manufacturing"]


def generate_company_data(days: int = 90) -> pd.DataFrame:
    """Generate synthetic company usage data.

    Replace this function with your actual data source. Caching happens in
    ``load_company_data`` so the data is fetched once and reused across reruns.
    """
    rng = np.random.default_rng(42)

    end_date = date.today() - timedelta(days=1)
    start_date = end_date - timedelta(days=days)
    dates = pd.date_range(start=start_date, end=end_date, freq="D")

    records = []

    for company in COMPANY_NAMES:
        # Assign static attributes
        account_type = rng.choice(ACCOUNT_TYPES, p=[0.3, 0.25, 0.2, 0.15, 0.1])
        region = rng.choice(REGIONS)
        segment = rng.choice(SEGMENTS)

        # Generate usage pattern
        base_usage = rng.integers(100, 10000)
        growth = rng.uniform(-0.005, 0.01)  # Some companies shrink

        for i, dt in enumerate(dates):
            # Base trend
            trend = base_usage * (1 + growth) ** i

            # Weekly seasonality
            if dt.dayofweek >= 5:
                trend *= 0.3

            # Random noise
            daily_credits = max(0, trend * rng.uniform(0.7, 1.3))

            records.append(
                {
                    "company_name": company,
                    "date": dt,
                    "daily_credits": daily_credits,
                    "account_type": account_type,
                    "region": region,
                    "segment": segment,
                }
            )

    return pd.DataFrame(records)


@st.cache_data(ttl="1h", show_spinner="Loading company data...")
def load_company_data() -> pd.DataFrame:
    """Load all company data (cached). Replace with your data source."""
    return generate_company_data(days=90)


def _calc_growth(trend: list[float]) -> float:
    """Return second-half vs first-half delta (rough trend indicator)."""
    if not trend or len(trend) < 2:
        return 0
    mid = len(trend) // 2
    first_half = sum(trend[:mid]) if mid > 0 else 0
    second_half = sum(trend[mid:])
    return second_half - first_half


def _to_list(val: object) -> list[object]:
    """Wrap a scalar in a single-element list for MultiselectColumn display."""
    return [val] if pd.notna(val) else []  # type: ignore[call-overload]  # ty: ignore[no-matching-overload]


def aggregate_companies(
    df: pd.DataFrame,
    days: int | None = None,
    account_types: list[str] | None = None,
    sort_by: str = "total_credits",
) -> pd.DataFrame:
    """Filter and aggregate company data."""
    result = df.copy()

    # Filter by time window
    if days:
        cutoff = pd.Timestamp.now() - pd.Timedelta(days=days)
        result = result[result["date"] >= cutoff]

    # Filter by account type
    if account_types:
        result = result[result["account_type"].isin(account_types)]

    if result.empty:
        return pd.DataFrame()

    # Aggregate to company level
    agg = (
        result.groupby("company_name")
        .agg(
            total_credits=("daily_credits", "sum"),
            active_days=("date", "nunique"),
            account_type=("account_type", "first"),
            region=("region", "first"),
            segment=("segment", "first"),
        )
        .reset_index()
    )

    # Calculate daily average
    agg["daily_avg"] = agg["total_credits"] / agg["active_days"]

    # Build sparkline data (list of daily values).
    # `include_groups=False` silences a pandas 2.2+ FutureWarning about
    # groupby keys being included in the applied function's input frame.
    sparklines = (
        result.groupby("company_name")  # ty: ignore[no-matching-overload]
        .apply(
            lambda x: x.sort_values("date")["daily_credits"].tolist(),
            include_groups=False,  # type: ignore[call-overload]
        )
        .reset_index()
    )
    sparklines.columns = ["company_name", "usage_trend"]
    agg = agg.merge(sparklines, on="company_name")

    agg["growth_score"] = agg["usage_trend"].apply(_calc_growth)

    # Sort
    if sort_by == "growth_asc":
        agg = agg.sort_values("growth_score", ascending=True)
    elif sort_by == "growth_desc":
        agg = agg.sort_values("growth_score", ascending=False)
    else:
        agg = agg.sort_values("total_credits", ascending=False)

    return agg


def render_company_dialog(
    company_name: str, company_row: pd.Series, df: pd.DataFrame
) -> None:
    """Render company details inside a dialog."""
    company_data = df[df["company_name"] == company_name].sort_values("date")

    if company_data.empty:
        st.warning("No data available for this company.")
        return

    # Company info badges - extract from list format back to single value
    account_type = (
        company_row["account_type"][0] if company_row["account_type"] else "Unknown"
    )
    region = company_row["region"][0] if company_row["region"] else "Unknown"
    segment = company_row["segment"][0] if company_row["segment"] else "Unknown"
    total_credits = company_row["total_credits"]

    st.markdown(
        f":blue-badge[{account_type}] "
        f":violet-badge[{region}] "
        f":orange-badge[{segment}] "
        f":green-badge[{total_credits:,.0f} credits]"
    )

    # Summary metrics
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total Credits", f"{total_credits:,.0f}")
    with col2:
        st.metric("Active Days", f"{company_row['active_days']:,}")
    with col3:
        growth = company_row["growth_score"]
        st.metric("Growth Score", f"{growth:+,.0f}")

    # Charts
    col1, col2 = st.columns(2)

    with col1:
        with st.container(border=True):
            st.markdown("**Daily usage**")
            st.line_chart(
                company_data,
                x="date",
                y="daily_credits",
                height=250,
                alt="Daily credit usage over time",
            )

    with col2:
        with st.container(border=True):
            st.markdown("**Cumulative usage**")
            chart_data = company_data.copy()
            chart_data["cumulative"] = chart_data["daily_credits"].cumsum()
            st.area_chart(
                chart_data,
                x="date",
                y="cumulative",
                height=250,
                alt="Cumulative credit usage over time",
            )


# =============================================================================
# Page Layout
# =============================================================================

st.markdown("# :material/business: Company Analytics")
st.caption("Track company adoption - usage, growth trends, and account details.")

# Filters
with st.container(border=True):
    st.markdown("**Filters**")

    # Company selection mode
    sort_mode = st.segmented_control(
        "Sort by",
        options=[
            "All companies",
            ":material/military_tech: Top spenders",
            ":material/trending_down: Top shrinkers",
            ":material/trending_up: Top gainers",
        ],
        default="All companies",
    )

    # Time window
    timeframe_options = {
        "All time": None,
        "Last 28 days": 28,
        "Last 7 days": 7,
    }
    timeframe = st.segmented_control(
        "Time window",
        options=list(timeframe_options.keys()),
        default="Last 28 days",
    )
    days_filter = timeframe_options.get(timeframe or "Last 28 days")

    # Account types
    account_types = st.pills(
        "Account types",
        options=ACCOUNT_TYPES,
        default=["Enterprise", "Growth", "Startup"],
        selection_mode="multi",
    )

# Determine sort order
if "Top shrinkers" in (sort_mode or ""):
    sort_by = "growth_asc"
elif "Top gainers" in (sort_mode or ""):
    sort_by = "growth_desc"
else:
    sort_by = "total_credits"

# Companies dataframe
with st.container(border=True):
    # Guard against None: segmented_control returns None when deselected.
    timeframe_text = (
        timeframe.lower() if timeframe and timeframe != "All time" else "all time"
    )
    st.markdown(f"**Companies — {timeframe_text}**")

    all_data = load_company_data()
    leaderboard = aggregate_companies(
        all_data,
        days=days_filter,
        account_types=account_types,
        sort_by=sort_by,
    )

    if leaderboard.empty:
        st.warning("No company data found for the selected filters.")
        st.stop()

    # Convert columns to lists for MultiselectColumn display (colored chips)
    for col in ["account_type", "region", "segment"]:
        leaderboard[col] = leaderboard[col].apply(_to_list)

    # Selection dataframe with cell-click support
    selection = st.dataframe(
        leaderboard,
        column_config={
            "company_name": st.column_config.TextColumn(
                "Company (click to view details)",
                width="medium",
            ),
            "account_type": st.column_config.MultiselectColumn(
                "Type",
                options=ACCOUNT_TYPES,
                color="auto",
                width="small",
            ),
            "total_credits": st.column_config.NumberColumn(
                "Credits",
                format="%.0f",
            ),
            "growth_score": st.column_config.NumberColumn(
                "Growth",
                format="%+.0f",
                help="Credit change: second half vs first half of period",
            ),
            "usage_trend": st.column_config.LineChartColumn(
                "Trend",
                width="medium",
            ),
            "daily_avg": st.column_config.NumberColumn(
                "Daily Avg",
                format="%.1f",
            ),
            "active_days": st.column_config.NumberColumn(
                "Active Days",
                format="%d",
            ),
            "region": st.column_config.MultiselectColumn(
                "Region",
                options=REGIONS,
                color="auto",
            ),
            "segment": st.column_config.MultiselectColumn(
                "Segment",
                options=SEGMENTS,
                color="auto",
            ),
        },
        column_order=[
            "company_name",
            "account_type",
            "total_credits",
            "growth_score",
            "usage_trend",
            "daily_avg",
            "region",
            "segment",
        ],
        hide_index=True,
        on_select="rerun",
        selection_mode="single-cell",
        key="company_leaderboard",
        alt="Company usage leaderboard",
    )

# Company drill-down via dialog when Company column cell is clicked
if selection.selection.cells:
    cell = selection.selection.cells[0]  # tuple: (row_index, column_name)
    row_idx, col_name = cell
    # Check if the clicked cell is in the company_name column
    if col_name == "company_name":
        selected_company = leaderboard.iloc[row_idx]["company_name"]
        company_row = leaderboard.iloc[row_idx]

        @st.dialog(f"{selected_company}", width="large")
        def show_company_dialog() -> None:
            render_company_dialog(
                selected_company,
                company_row=company_row,
                df=all_data,
            )

        show_company_dialog()
