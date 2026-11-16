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

"""Seattle Weather dashboard exploring the classic Altair case study dataset."""

import altair as alt
import pandas as pd
import vega_datasets

import streamlit as st

st.set_page_config(
    # Title and icon for the browser's tab bar:
    page_title="Seattle Weather",
    page_icon=":material/wb_sunny:",
    # Make the content take up the width of the page:
    layout="wide",
)


@st.cache_data(show_spinner="Loading weather data...")
def load_weather_data() -> pd.DataFrame:
    df: pd.DataFrame = vega_datasets.data("seattle_weather")
    return df


full_df = load_weather_data()

"""
# Seattle Weather

Let's explore the [classic Seattle Weather
dataset](https://altair-viz.github.io/case_studies/exploring-weather.html)!
"""

st.space("medium")

"""
## 2015 Summary
"""

st.space("small")

df_2015 = full_df[full_df["date"].dt.year == 2015]
df_2014 = full_df[full_df["date"].dt.year == 2014]

max_temp_2015 = df_2015["temp_max"].max()
max_temp_2014 = df_2014["temp_max"].max()

min_temp_2015 = df_2015["temp_min"].min()
min_temp_2014 = df_2014["temp_min"].min()

max_wind_2015 = df_2015["wind"].max()
max_wind_2014 = df_2014["wind"].max()

min_wind_2015 = df_2015["wind"].min()
min_wind_2014 = df_2014["wind"].min()

max_prec_2015 = df_2015["precipitation"].max()
max_prec_2014 = df_2014["precipitation"].max()

min_prec_2015 = df_2015["precipitation"].min()
min_prec_2014 = df_2014["precipitation"].min()


with st.container(horizontal=True, gap="medium"):
    cols = st.columns(2, gap="medium", width=300)

    with cols[0]:
        st.metric(
            "Max temperature",
            f"{max_temp_2015:0.1f}C",
            delta=f"{max_temp_2015 - max_temp_2014:0.1f}C",
            width="content",
        )

    with cols[1]:
        st.metric(
            "Min temperature",
            f"{min_temp_2015:0.1f}C",
            delta=f"{min_temp_2015 - min_temp_2014:0.1f}C",
            width="content",
        )

    cols = st.columns(2, gap="medium", width=300)

    with cols[0]:
        st.metric(
            "Max precipitation",
            f"{max_prec_2015:0.1f}mm",
            delta=f"{max_prec_2015 - max_prec_2014:0.1f}mm",
            width="content",
        )

    with cols[1]:
        st.metric(
            "Min precipitation",
            f"{min_prec_2015:0.1f}mm",
            delta=f"{min_prec_2015 - min_prec_2014:0.1f}mm",
            width="content",
        )

    cols = st.columns(2, gap="medium", width=300)

    with cols[0]:
        st.metric(
            "Max wind",
            f"{max_wind_2015:0.1f}m/s",
            delta=f"{max_wind_2015 - max_wind_2014:0.1f}m/s",
            width="content",
        )

    with cols[1]:
        st.metric(
            "Min wind",
            f"{min_wind_2015:0.1f}m/s",
            delta=f"{min_wind_2015 - min_wind_2014:0.1f}m/s",
            width="content",
        )

    weather_icons = {
        "sun": "sunny",
        "snow": "weather_snowy",
        "rain": "rainy",
        "fog": "foggy",
        "drizzle": "rainy",
    }

    cols = st.columns(2, gap="large")

    with cols[0]:
        weather_name = (
            full_df["weather"].value_counts().head(1).reset_index()["weather"][0]
        )
        st.metric(
            "Most common weather",
            f":material/{weather_icons[weather_name]}: {weather_name.upper()}",
        )

    with cols[1]:
        weather_name = (
            full_df["weather"].value_counts().tail(1).reset_index()["weather"][0]
        )
        st.metric(
            "Least common weather",
            f":material/{weather_icons[weather_name]}: {weather_name.upper()}",
        )

st.space("medium")

"""
## Compare different years
"""

YEARS = full_df["date"].dt.year.unique()
selected_years = st.pills(
    "Years to compare", YEARS, default=YEARS, selection_mode="multi"
)

if not selected_years:
    st.warning("You must select at least 1 year.", icon=":material/warning:")
    st.stop()

df = full_df[full_df["date"].dt.year.isin(selected_years)]

cols = st.columns([3, 1])

with cols[0].container(border=True, height="stretch"):
    "### :material/thermostat: Temperature"

    st.altair_chart(
        alt.Chart(df)
        .mark_bar(width=1)
        .encode(
            alt.X("monthdate(date):T").title("date"),
            alt.Y("temp_max:Q").title("temperature range (C)"),
            alt.Y2("temp_min:Q"),
            alt.Color("year(date):N").title("year"),
            alt.XOffset("year(date):N"),
            tooltip=[
                alt.Tooltip("monthdate(date):T", title="Date"),
                alt.Tooltip("temp_max:Q", title="Max Temp (C)"),
                alt.Tooltip("temp_min:Q", title="Min Temp (C)"),
                alt.Tooltip("year(date):N", title="Year"),
            ],
        )
        .configure_legend(orient="bottom"),
        alt="Daily high and low temperatures by year",
    )

with cols[1].container(border=True, height="stretch"):
    "### Weather distribution"

    st.altair_chart(
        alt.Chart(df)
        .mark_arc()
        .encode(
            alt.Theta("count()"),
            alt.Color("weather:N"),
        )
        .configure_legend(orient="bottom"),
        alt="Share of days by weather type",
    )


cols = st.columns(2)

with cols[0].container(border=True, height="stretch"):
    "### :material/air: Wind"

    # Prepare data for st.line_chart - pivot by year
    wind_df = df.copy()
    wind_df["month_day"] = wind_df["date"].dt.strftime("%m-%d")
    wind_df["year"] = wind_df["date"].dt.year

    # Pivot to one column per year (mean wind per calendar day)
    wind_pivot = wind_df.pivot_table(
        index="month_day", columns="year", values="wind", aggfunc="mean"
    ).sort_index()

    st.line_chart(wind_pivot, height=300, alt="Average wind speed by day of year")

with cols[1].container(border=True, height="stretch"):
    "### :material/water_drop: Precipitation"

    st.altair_chart(
        alt.Chart(df)
        .mark_bar()
        .encode(
            alt.X("month(date):O").title("month"),
            alt.Y("sum(precipitation):Q").title("precipitation (mm)"),
            alt.Color("year(date):N").title("year"),
            tooltip=[
                alt.Tooltip("month(date):O", title="Month"),
                alt.Tooltip("sum(precipitation):Q", title="Precipitation (mm)"),
                alt.Tooltip("year(date):N", title="Year"),
            ],
        )
        .configure_legend(orient="bottom"),
        alt="Monthly precipitation totals by year",
    )

cols = st.columns(2)

with cols[0].container(border=True, height="stretch"):
    "### :material/calendar_month: Monthly weather breakdown"

    st.altair_chart(
        alt.Chart(df)
        .mark_bar()
        .encode(
            alt.X("month(date):O", title="month"),
            alt.Y("count():Q", title="days", stack="normalize"),
            alt.Color("weather:N"),
        )
        .configure_legend(orient="bottom"),
        alt="Monthly mix of weather types",
    )

with cols[1].container(border=True, height="stretch"):
    "### :material/table: Raw data"

    st.dataframe(df, hide_index=True, alt="Seattle weather observations")
