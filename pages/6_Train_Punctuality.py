"""Train Punctuality page.

Shows average delay per station over the day with an animated map
showing how delays evolve in 15-minute steps with a moving window average.
"""

import os
import json
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import folium
import streamlit as st
from streamlit_folium import st_folium
from folium.plugins import TimestampedGeoJson
from dotenv import load_dotenv

from logic.shared import CUSTOM_CSS, render_footer, load_provinces_geojson, noon_timestamp
from logic.api import fetch_punctuality, fetch_operational_points, punctuality_ts

load_dotenv()

st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

TOKEN = os.getenv("BRUSSELS_MOBILITY_TWIN_KEY", "")

# ── Sidebar ────────────────────────────────────────────────────────────────��─

with st.sidebar:
    token = TOKEN
    if not token:
        token = st.text_input("API Token", type="password",
                              help="Bearer token for api.mobilitytwin.brussels")
    if not token:
        st.info("Set `BRUSSELS_MOBILITY_TWIN_KEY` in `.env` or enter a token above.")
        st.stop()

    st.markdown('<p class="sidebar-section">View</p>', unsafe_allow_html=True)
    view_mode = st.radio("Display", ["Stations", "Animation"],
                         label_visibility="collapsed", horizontal=True)

    st.markdown('<hr class="sidebar-divider"/>', unsafe_allow_html=True)
    st.markdown('<p class="sidebar-section">Date</p>', unsafe_allow_html=True)
    selected_date = st.date_input(
        "Day to analyse",
        value=date.today() - timedelta(days=2),
        min_value=date(2024, 8, 21),
        max_value=date.today(),
    )

    st.markdown('<hr class="sidebar-divider"/>', unsafe_allow_html=True)
    st.markdown('<p class="sidebar-section">Filters</p>', unsafe_allow_html=True)
    delay_type = st.radio("Delay metric", ["Departure", "Arrival"], horizontal=True)
    hour_range = st.slider("Hour window", 0, 24, (5, 24), step=1)
    min_trains = st.slider("Min trains per station", 1, 50, 5,
                           help="Exclude stations with fewer stops to reduce noise.")

    col_min, col_max = st.columns(2)
    with col_min:
        delay_floor = st.number_input(
            "Min delay (min)", value=2.0, step=1.0,
            help="Threshold for small delays.",
        )
    with col_max:
        delay_cap = st.number_input(
            "Max delay (min)", value=30.0, step=1.0,
            help="Threshold for large delays.",
        )
    exclude_outliers = st.toggle(
        "Exclude out-of-range", value=False,
        help="**ON**: drop records below min or above max. "
             "**OFF** (default): clamp below-min to 0 and above-max to max.",
    )

    if view_mode == "Animation":
        st.markdown('<hr class="sidebar-divider"/>', unsafe_allow_html=True)
        st.markdown('<p class="sidebar-section">Animation</p>', unsafe_allow_html=True)
        window_min = st.slider("Moving window (min)", 15, 120, 30, step=15,
                               help="Size of the rolling window centred on each time step.")

    # Placeholder for operator filter (populated after data loads)
    operator_placeholder = st.empty()

    st.markdown('<hr class="sidebar-divider"/>', unsafe_allow_html=True)
    st.markdown(
        '<div class="footer-credit">Powered by<br/><strong>MobilityTwin.Brussels</strong><br/>(ULB)</div>',
        unsafe_allow_html=True,
    )

# ── Load data ────────────────────────────────────────────────────────────────

ts_infra = noon_timestamp(selected_date.year, selected_date.month, selected_date.day)
ts_punct = punctuality_ts(selected_date)


@st.cache_data(show_spinner="Building station coordinates...", ttl=3600)
def _build_station_coords(op_points_json):
    """Build name -> (lat, lon) lookup from operational points."""
    coords = {}
    for feat in op_points_json["features"]:
        props = feat["properties"]
        name = props.get("longnamedutch", "").strip().upper()
        if not name:
            continue
        pt = props.get("geo_point_2d") or {}
        lat, lon = pt.get("lat"), pt.get("lon")
        if lat and lon:
            coords[name] = (lat, lon)
    return coords


op_points = fetch_operational_points(ts_infra, token)
station_coords = _build_station_coords(op_points)

raw = fetch_punctuality(ts_punct, token)
if not raw:
    st.warning("No punctuality data returned for this date.")
    st.stop()

df = pd.DataFrame(raw)

# Operator filter (populated now that data is available)
available_operators = sorted(df["train_serv"].dropna().unique())
with operator_placeholder:
    selected_operators = st.multiselect(
        "Operators", available_operators, default=available_operators,
        help="Filter by train operator.",
    )

if selected_operators:
    df = df[df["train_serv"].isin(selected_operators)]
else:
    st.warning("Select at least one operator.")
    st.stop()

# Pick delay column
delay_col = "delay_dep" if delay_type == "Departure" else "delay_arr"
time_col = "planned_time_dep" if delay_type == "Departure" else "planned_time_arr"

df["delay_sec"] = pd.to_numeric(df[delay_col], errors="coerce")
df = df.dropna(subset=["delay_sec"])
df["delay_min"] = df["delay_sec"] / 60.0
df["station"] = df["ptcar_lg_nm_nl"].str.strip().str.upper()

# Parse time as total minutes for finer-grained binning
time_parts = df[time_col].astype(str).str.split(":", expand=True)
df["time_hour"] = pd.to_numeric(time_parts[0], errors="coerce").fillna(-1).astype(int)
df["time_minute"] = pd.to_numeric(time_parts[1], errors="coerce").fillna(0).astype(int)
df["time_total_min"] = df["time_hour"] * 60 + df["time_minute"]

# Apply hour filter
df = df[(df["time_hour"] >= hour_range[0]) & (df["time_hour"] < hour_range[1])]

# Apply delay range handling
if exclude_outliers:
    # Drop records outside [delay_floor, delay_cap]
    df = df[(df["delay_min"] >= delay_floor) & (df["delay_min"] <= delay_cap)]
else:
    # Clamp: below floor -> 0, above cap -> cap
    df["delay_min"] = df["delay_min"].where(df["delay_min"] >= delay_floor, 0.0)
    df["delay_min"] = df["delay_min"].clip(upper=delay_cap)

if df.empty:
    st.warning("No data matches the selected filters.")
    st.stop()

# Match stations to coordinates
df["lat"] = df["station"].map(lambda s: station_coords.get(s, (None, None))[0])
df["lon"] = df["station"].map(lambda s: station_coords.get(s, (None, None))[1])
df_geo = df.dropna(subset=["lat", "lon"])

# ── Compute station-level daily stats ────────────────────────────────────────

station_stats = df_geo.groupby("station").agg(
    avg_delay=("delay_min", "mean"),
    median_delay=("delay_min", "median"),
    max_delay=("delay_min", "max"),
    n_trains=("delay_min", "count"),
    pct_late=("delay_min", lambda x: (x > 1).mean() * 100),
    lat=("lat", "first"),
    lon=("lon", "first"),
).reset_index()

station_stats = station_stats[station_stats["n_trains"] >= min_trains]

if station_stats.empty:
    st.warning("No stations have enough trains with the current filters.")
    st.stop()

# ── Header ─────────────────────────────��────────────────────────────────────��

st.caption(
    f"**{selected_date.strftime('%A %d %b %Y')}** — "
    f"{delay_type} delays — {hour_range[0]}h–{hour_range[1]}h — "
    f"Min {min_trains} trains/station"
)

with st.expander("How is this computed?"):
    st.markdown(f"""
**Data source**: Infrabel real-time punctuality records via MobilityTwin API.

**Delay**: Difference between actual and planned {delay_type.lower()} time at each stop,
in seconds (converted to minutes). Negative = early, positive = late.

**Delay range** (min {delay_floor}, max {delay_cap}):
- *Exclude out-of-range OFF* (default): delays below {delay_floor} min are clamped to 0,
  delays above {delay_cap} min are clamped to {delay_cap}. All records are kept.
- *Exclude out-of-range ON*: records outside [{delay_floor}, {delay_cap}] are dropped entirely.

**Circle size**: Proportional to the number of trains at the station (more trains = bigger dot).

**Circle colour**: Average delay (green = on time, red = very late).

**Animation**: Steps every 15 minutes. At each step, a **moving window** (configurable,
default 30 min) centred on the current time is used to compute the average delay
and train count per station.
""")

# Metrics
c1, c2, c3, c4 = st.columns(4)
c1.metric("Stations", len(station_stats))
c2.metric("Avg delay", f"{station_stats['avg_delay'].mean():.1f} min")
c3.metric("Median delay", f"{station_stats['median_delay'].median():.1f} min")
late_pct = (station_stats["avg_delay"] > 1).mean() * 100
c4.metric("Stations >1min late", f"{late_pct:.0f}%")


# ── Color helper ────────────────────────────────────────────────────────���────

def delay_color(delay_min, max_delay):
    """Green (on time / early) -> yellow -> red (very late)."""
    if delay_min <= 0:
        return "#22b422"
    ratio = min(delay_min / max(max_delay, 0.1), 1.0)
    if ratio < 0.5:
        r2 = ratio * 2
        r = int(34 + (255 - 34) * r2)
        g = int(180 - 40 * r2)
        b = int(34 - 30 * r2)
    else:
        r2 = (ratio - 0.5) * 2
        r = int(255 - 35 * r2)
        g = int(140 - 120 * r2)
        b = int(4 + 30 * r2)
    return f"#{max(0,min(255,r)):02x}{max(0,min(255,g)):02x}{max(0,min(255,b)):02x}"


# ── Station view ─────────────────────────────────────────────────────────────

if view_mode == "Stations":
    max_delay = station_stats["avg_delay"].quantile(0.95)
    max_trains = station_stats["n_trains"].max()

    m = folium.Map(location=[50.5, 4.35], zoom_start=8, tiles="cartodbpositron")

    for _, row in station_stats.iterrows():
        d = row["avg_delay"]
        n = row["n_trains"]
        color = delay_color(d, max_delay)
        train_ratio = n / max(max_trains, 1)
        radius = 3 + 12 * train_ratio

        folium.CircleMarker(
            location=[row["lat"], row["lon"]],
            radius=radius,
            color=color, fill=True, fill_color=color,
            fill_opacity=0.8, weight=1,
            tooltip=(
                f"<b>{row['station']}</b><br/>"
                f"Avg delay: {d:+.1f} min<br/>"
                f"Median: {row['median_delay']:+.1f} min<br/>"
                f"Max: {row['max_delay']:+.1f} min<br/>"
                f"Trains: {int(n)}<br/>"
                f"Late (>1min): {row['pct_late']:.0f}%"
            ),
        ).add_to(m)

    import branca.colormap as cm
    cmap = cm.LinearColormap(
        colors=["#22b422", "#ffcc00", "#dd2020"],
        vmin=0, vmax=round(max_delay, 1),
        caption="Average delay (min) — dot size = number of trains",
    )
    cmap.add_to(m)

    st_folium(m, width="stretch", height=650, key="punct_stations")

    # Top delayed stations table
    st.subheader("Most delayed stations")
    top = station_stats.nlargest(20, "avg_delay")[
        ["station", "avg_delay", "median_delay", "max_delay", "n_trains", "pct_late"]
    ].copy()
    top.columns = ["Station", "Avg Delay (min)", "Median (min)", "Max (min)", "Trains", "% Late"]
    top = top.round(1).reset_index(drop=True)
    top.index = top.index + 1
    st.dataframe(top, width="stretch")

# ── Animation view (15-min steps, moving window average) ─────────────────────

elif view_mode == "Animation":
    half_window = window_min / 2.0

    # Build 15-minute time steps within the hour range
    start_total = hour_range[0] * 60
    end_total = hour_range[1] * 60
    time_steps = list(range(start_total, end_total, 15))

    if not time_steps:
        st.warning("No time steps in the selected hour range.")
        st.stop()

    # Pre-extract station coords
    station_coord_map = {}
    for station in df_geo["station"].unique():
        subset = df_geo[df_geo["station"] == station].iloc[0]
        station_coord_map[station] = (float(subset["lat"]), float(subset["lon"]))

    # For each time step, compute moving-window average per station
    window_data = []
    for t_min in time_steps:
        w_start = t_min - half_window
        w_end = t_min + half_window
        window_df = df_geo[(df_geo["time_total_min"] >= w_start) &
                           (df_geo["time_total_min"] < w_end)]
        if window_df.empty:
            continue
        agg = window_df.groupby("station")["delay_min"].agg(["mean", "count"]).reset_index()
        agg.columns = ["station", "avg_delay", "n_trains"]
        agg["time_step"] = t_min
        window_data.append(agg)

    if not window_data:
        st.warning("No data for animation.")
        st.stop()

    windowed = pd.concat(window_data, ignore_index=True)
    min_trains_window = max(1, min_trains // 4)
    windowed = windowed[windowed["n_trains"] >= min_trains_window]

    if windowed.empty:
        st.warning("Not enough data after filtering.")
        st.stop()

    max_delay = windowed["avg_delay"].quantile(0.95)
    max_trains_w = windowed["n_trains"].max()

    # Build TimestampedGeoJson features
    features = []
    for _, row in windowed.iterrows():
        station = row["station"]
        if station not in station_coord_map:
            continue
        lat, lon = station_coord_map[station]

        d = float(row["avg_delay"])
        n = int(row["n_trains"])
        color = delay_color(d, max_delay)
        train_ratio = n / max(max_trains_w, 1)
        radius = max(3, 3 + 12 * train_ratio)

        t_min = int(row["time_step"])
        h, m_part = divmod(t_min, 60)
        time_str = f"{selected_date.isoformat()}T{h:02d}:{m_part:02d}:00"

        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [lon, lat],
            },
            "properties": {
                "time": time_str,
                "popup": (
                    f"<b>{station}</b><br/>"
                    f"{h:02d}:{m_part:02d} ({window_min}min window)<br/>"
                    f"Avg delay: {d:+.1f} min<br/>"
                    f"Trains: {n}"
                ),
                "icon": "circle",
                "iconstyle": {
                    "fillColor": color,
                    "fillOpacity": 0.8,
                    "stroke": "true",
                    "color": color,
                    "weight": 1,
                    "radius": radius,
                },
            },
        })

    if not features:
        st.warning("Not enough data for animation.")
        st.stop()

    m = folium.Map(location=[50.5, 4.35], zoom_start=8, tiles="cartodbpositron")

    TimestampedGeoJson(
        {"type": "FeatureCollection", "features": features},
        period="PT15M",
        add_last_point=False,
        auto_play=True,
        loop=True,
        max_speed=2,
        loop_button=True,
        date_options="HH:mm",
        time_slider_drag_update=True,
        duration="PT15M",
    ).add_to(m)

    import branca.colormap as cm
    cmap = cm.LinearColormap(
        colors=["#22b422", "#ffcc00", "#dd2020"],
        vmin=0, vmax=round(max_delay, 1),
        caption=f"Avg delay (min) — {window_min}min moving window — dot size = trains",
    )
    cmap.add_to(m)

    st_folium(m, width="stretch", height=650, key="punct_anim")

    # Hourly summary chart
    st.subheader("Average delay by hour")
    hourly_avg = df_geo.groupby("time_hour")["delay_min"].agg(["mean", "count"]).reset_index()
    hourly_avg.columns = ["Hour", "Avg Delay (min)", "Train Stops"]
    hourly_avg = hourly_avg[(hourly_avg["Hour"] >= hour_range[0]) &
                            (hourly_avg["Hour"] < hour_range[1])]

    import plotly.graph_objects as go
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=hourly_avg["Hour"],
        y=hourly_avg["Avg Delay (min)"],
        marker_color=[delay_color(d, max_delay) for d in hourly_avg["Avg Delay (min)"]],
        text=hourly_avg["Avg Delay (min)"].round(1),
        textposition="outside",
        hovertext=[
            f"Hour: {int(h)}h<br>Avg delay: {d:.1f} min<br>Stops: {int(n)}"
            for h, d, n in zip(hourly_avg["Hour"], hourly_avg["Avg Delay (min)"], hourly_avg["Train Stops"])
        ],
        hoverinfo="text",
    ))
    fig.update_layout(
        xaxis_title="Hour of day",
        yaxis_title="Average delay (min)",
        height=350,
        margin=dict(t=20, b=40),
        xaxis=dict(dtick=1),
    )
    st.plotly_chart(fig, use_container_width=True)

render_footer()
