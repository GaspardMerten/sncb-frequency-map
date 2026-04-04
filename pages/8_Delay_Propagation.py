"""Delay Propagation Analysis page.

Identifies stations and segments where delays are introduced by comparing
consecutive stops along each train journey across multiple days.
"""

import os
from datetime import date, timedelta

import numpy as np
import pandas as pd
import folium
import streamlit as st
from streamlit_folium import st_folium
import branca.colormap as cm
from dotenv import load_dotenv

from logic.shared import CUSTOM_CSS, render_footer, noon_timestamp
from logic.api import fetch_punctuality_range, fetch_operational_points

load_dotenv()

st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

TOKEN = os.getenv("BRUSSELS_MOBILITY_TWIN_KEY", "")

# ── Sidebar ──────────────────────────────────────────────────────────────────

with st.sidebar:
    token = TOKEN
    if not token:
        token = st.text_input("API Token", type="password",
                              help="Bearer token for api.mobilitytwin.brussels")
    if not token:
        st.info("Set `BRUSSELS_MOBILITY_TWIN_KEY` in `.env` or enter a token above.")
        st.stop()

    st.markdown('<p class="sidebar-section">View</p>', unsafe_allow_html=True)
    view_mode = st.radio("Display", ["Stations", "Segments"],
                         label_visibility="collapsed", horizontal=True)

    st.markdown('<hr class="sidebar-divider"/>', unsafe_allow_html=True)
    st.markdown('<p class="sidebar-section">Date range</p>', unsafe_allow_html=True)
    today = date.today()
    dc1, dc2 = st.columns(2)
    with dc1:
        start_date = st.date_input("From", value=today - timedelta(days=7),
                                   min_value=date(2024, 8, 21), max_value=today,
                                   key="prop_from")
    with dc2:
        end_date = st.date_input("To", value=today - timedelta(days=1),
                                 min_value=start_date, max_value=today,
                                 key="prop_to")
    n_days = (end_date - start_date).days + 1
    if n_days > 30:
        st.error("Max 30 days.")
        st.stop()
    st.caption(f"{n_days} day(s) selected")

    st.markdown('<hr class="sidebar-divider"/>', unsafe_allow_html=True)
    st.markdown('<p class="sidebar-section">Filters</p>', unsafe_allow_html=True)
    hour_range = st.slider("Hour window", 0, 24, (5, 24), step=1, key="prop_hr")
    threshold_sec = st.number_input("Min delay increase (sec)", value=60, step=30,
                                    help="Only count a segment if delay increased by more than this.")
    min_incidents = st.slider("Min incidents", 1, 50, 3,
                              help="Exclude stations/segments with fewer delay events.")

    st.markdown('<hr class="sidebar-divider"/>', unsafe_allow_html=True)
    st.markdown('<p class="sidebar-section">Delay range</p>', unsafe_allow_html=True)
    col_min, col_max = st.columns(2)
    with col_min:
        delay_floor = st.number_input("Min delay (min)", value=0.0, step=1.0,
                                      key="prop_floor",
                                      help="Threshold for small delays.")
    with col_max:
        delay_cap = st.number_input("Max delay (min)", value=30.0, step=1.0,
                                    key="prop_cap",
                                    help="Threshold for large delays.")
    exclude_outliers = st.toggle(
        "Exclude out-of-range", value=False, key="prop_excl",
        help="**ON**: drop records outside [min, max]. "
             "**OFF** (default): clamp below-min to 0, above-max to max.",
    )

    operator_placeholder = st.empty()

    st.markdown('<hr class="sidebar-divider"/>', unsafe_allow_html=True)
    st.markdown(
        '<div class="footer-credit">Powered by<br/><strong>MobilityTwin.Brussels</strong><br/>(ULB)</div>',
        unsafe_allow_html=True,
    )

# ── Load data ────────────────────────────────────────────────────────────────

all_dates = [start_date + timedelta(days=i) for i in range(n_days)]

cache_key = (tuple(all_dates), token)
if st.session_state.get("_prop_raw_key") == cache_key:
    df = st.session_state["_prop_raw"]
else:
    progress = st.progress(0, text="Loading punctuality data...")

    def _on_progress(i, total, d):
        progress.progress(i / max(total, 1),
                          text=f"Fetching {d.strftime('%d %b %Y')} ({i+1}/{total})...")

    records = fetch_punctuality_range(all_dates, token, progress_cb=_on_progress)
    progress.progress(1.0, text="Done!")
    progress.empty()

    if not records:
        st.warning("No punctuality data for the selected range.")
        st.stop()

    df = pd.DataFrame(records)
    st.session_state["_prop_raw_key"] = cache_key
    st.session_state["_prop_raw"] = df

# Operator filter
available_operators = sorted(df["train_serv"].dropna().unique())
with operator_placeholder:
    selected_operators = st.multiselect(
        "Operators", available_operators, default=available_operators,
        key="prop_ops",
    )
if selected_operators:
    df = df[df["train_serv"].isin(selected_operators)]
if df.empty:
    st.warning("No data after operator filter.")
    st.stop()

# Station coordinates
ts_infra = noon_timestamp(start_date.year, start_date.month, start_date.day)
op_points = fetch_operational_points(ts_infra, token)


@st.cache_data(show_spinner=False, ttl=3600)
def _build_station_coords(op_json):
    coords = {}
    for feat in op_json["features"]:
        props = feat["properties"]
        name = props.get("longnamedutch", "").strip().upper()
        if not name:
            continue
        pt = props.get("geo_point_2d") or {}
        lat, lon = pt.get("lat"), pt.get("lon")
        if lat and lon:
            coords[name] = (lat, lon)
    return coords


station_coords = _build_station_coords(op_points)

# ── Compute delay propagation ────────────────────────────────────────────────

delay_floor_sec = delay_floor * 60
delay_cap_sec = delay_cap * 60


@st.cache_data(show_spinner="Analysing delay propagation...", ttl=3600)
def _compute_propagation(df_records, threshold, h_range,
                         floor_sec, cap_sec, exclude):
    df = pd.DataFrame(df_records)
    df["delay_dep_sec"] = pd.to_numeric(df["delay_dep"], errors="coerce")
    df["station"] = df["ptcar_lg_nm_nl"].str.strip().str.upper()

    # Parse departure time as minutes
    parts = df["planned_time_dep"].astype(str).str.split(":", expand=True)
    df["dep_h"] = pd.to_numeric(parts[0], errors="coerce").fillna(-1).astype(int)
    df["dep_m"] = pd.to_numeric(parts[1], errors="coerce").fillna(0).astype(int)
    df["dep_total"] = df["dep_h"] * 60 + df["dep_m"]

    # Hour filter
    df = df[(df["dep_h"] >= h_range[0]) & (df["dep_h"] < h_range[1])]
    df = df.dropna(subset=["delay_dep_sec"])

    # Delay range filter
    if exclude:
        df = df[(df["delay_dep_sec"] >= floor_sec) & (df["delay_dep_sec"] <= cap_sec)]
    else:
        df["delay_dep_sec"] = df["delay_dep_sec"].where(
            df["delay_dep_sec"] >= floor_sec, 0.0)
        df["delay_dep_sec"] = df["delay_dep_sec"].clip(upper=cap_sec)

    results = []
    for (train_no, datdep), grp in df.groupby(["train_no", "datdep"]):
        journey = grp.sort_values("dep_total")
        delays = journey["delay_dep_sec"].values
        stations = journey["station"].values
        relations = journey["relation"].values

        for i in range(1, len(delays)):
            increase = delays[i] - delays[i - 1]
            if increase > threshold:
                results.append({
                    "from_station": stations[i - 1],
                    "to_station": stations[i],
                    "station": stations[i],
                    "delay_increase_sec": float(increase),
                    "train_no": train_no,
                    "relation": relations[i],
                    "datdep": datdep,
                })

    if not results:
        return pd.DataFrame(), pd.DataFrame()

    prop_df = pd.DataFrame(results)

    station_agg = prop_df.groupby("station").agg(
        total_delay_min=("delay_increase_sec", lambda x: x.sum() / 60),
        avg_increase_min=("delay_increase_sec", lambda x: x.mean() / 60),
        n_incidents=("delay_increase_sec", "count"),
        n_trains=("train_no", "nunique"),
        n_days=("datdep", "nunique"),
        top_relation=("relation", lambda x: x.value_counts().index[0]),
    ).reset_index()

    segment_agg = prop_df.groupby(["from_station", "to_station"]).agg(
        total_delay_min=("delay_increase_sec", lambda x: x.sum() / 60),
        avg_increase_min=("delay_increase_sec", lambda x: x.mean() / 60),
        n_incidents=("delay_increase_sec", "count"),
        n_trains=("train_no", "nunique"),
    ).reset_index()

    return station_agg, segment_agg


station_agg, segment_agg = _compute_propagation(
    df.to_dict("records"), threshold_sec, tuple(hour_range),
    delay_floor_sec, delay_cap_sec, exclude_outliers,
)

if station_agg.empty:
    st.warning("No delay propagation events found with current settings.")
    st.stop()

station_agg = station_agg[station_agg["n_incidents"] >= min_incidents]
segment_agg = segment_agg[segment_agg["n_incidents"] >= min_incidents]

# ── Header ───────────────────────────────────────────────────────────────────

st.caption(
    f"**{start_date.strftime('%d %b')} – {end_date.strftime('%d %b %Y')}** — "
    f"{hour_range[0]}h–{hour_range[1]}h — "
    f"Threshold: {threshold_sec}s — Min incidents: {min_incidents} — "
    f"Delay range: {delay_floor}–{delay_cap} min"
)

with st.expander("How is this computed?"):
    st.markdown(f"""
**Goal**: Identify where delays are *introduced* into the network.

**Algorithm**:
1. For each day in the range, punctuality data is fetched from Infrabel.
2. Each train journey (grouped by train number + date) is sorted by planned departure.
3. For each consecutive pair of stops, the **delay increase** is computed:
   `increase = delay_dep[next_stop] - delay_dep[current_stop]`
4. If the increase exceeds **{threshold_sec} seconds**, the destination station
   (or the segment) is flagged as introducing delay.
5. Results are aggregated across all trains and days.

**Delay range** ({delay_floor}–{delay_cap} min):
- *Exclude OFF*: delays below {delay_floor} min clamped to 0, above {delay_cap} min clamped to {delay_cap}.
- *Exclude ON*: records outside range are dropped.
""")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Stations", len(station_agg))
total_hours = station_agg["total_delay_min"].sum() / 60
c2.metric("Total delay introduced", f"{total_hours:.1f} h")
if not station_agg.empty:
    worst = station_agg.nlargest(1, "total_delay_min").iloc[0]
    c3.metric("Worst station", worst["station"])
    c4.metric("Avg increase", f"{station_agg['avg_increase_min'].mean():.1f} min")

# ── Station view ─────────────────────────────────────────────────────────────

if view_mode == "Stations":
    station_agg["lat"] = station_agg["station"].map(
        lambda s: station_coords.get(s, (None, None))[0])
    station_agg["lon"] = station_agg["station"].map(
        lambda s: station_coords.get(s, (None, None))[1])
    geo = station_agg.dropna(subset=["lat", "lon"])

    if geo.empty:
        st.warning("No stations could be matched to coordinates.")
        st.stop()

    max_total = geo["total_delay_min"].quantile(0.95)
    max_avg = geo["avg_increase_min"].quantile(0.95)

    m = folium.Map(location=[50.5, 4.35], zoom_start=8, tiles="cartodbpositron")

    for _, row in geo.iterrows():
        total = row["total_delay_min"]
        avg = row["avg_increase_min"]
        size_ratio = min(total / max(max_total, 0.1), 1.0)
        radius = 3 + 14 * size_ratio

        color_ratio = min(avg / max(max_avg, 0.1), 1.0)
        if color_ratio < 0.5:
            r2 = color_ratio * 2
            r = int(34 + (255 - 34) * r2)
            g = int(180 - 40 * r2)
            b = int(34 - 30 * r2)
        else:
            r2 = (color_ratio - 0.5) * 2
            r = int(255 - 35 * r2)
            g = int(140 - 120 * r2)
            b = int(4 + 30 * r2)
        color = f"#{max(0,min(255,r)):02x}{max(0,min(255,g)):02x}{max(0,min(255,b)):02x}"

        folium.CircleMarker(
            location=[row["lat"], row["lon"]],
            radius=radius,
            color=color, fill=True, fill_color=color,
            fill_opacity=0.8, weight=1,
            tooltip=(
                f"<b>{row['station']}</b><br/>"
                f"Total delay introduced: {total:.0f} min<br/>"
                f"Avg increase: {avg:.1f} min<br/>"
                f"Incidents: {int(row['n_incidents'])}<br/>"
                f"Trains: {int(row['n_trains'])}<br/>"
                f"Top relation: {row['top_relation']}"
            ),
        ).add_to(m)

    cmap = cm.LinearColormap(
        colors=["#22b422", "#ffcc00", "#dd2020"],
        vmin=0, vmax=round(max_avg, 1),
        caption="Avg delay increase (min) — dot size = total delay introduced",
    )
    cmap.add_to(m)
    st_folium(m, width="stretch", height=650, key="prop_stations")

    st.subheader("Worst delay-introducing stations")
    top = geo.nlargest(25, "total_delay_min")[
        ["station", "total_delay_min", "avg_increase_min", "n_incidents",
         "n_trains", "n_days", "top_relation"]
    ].copy()
    top.columns = ["Station", "Total Delay (min)", "Avg Increase (min)",
                   "Incidents", "Trains", "Days", "Top Relation"]
    top = top.round(1).reset_index(drop=True)
    top.index = top.index + 1
    st.dataframe(top, width="stretch")

# ── Segment view ─────────────────────────────────────────────────────────────

elif view_mode == "Segments":
    if segment_agg.empty:
        st.warning("No segments found.")
        st.stop()

    segment_agg["from_lat"] = segment_agg["from_station"].map(
        lambda s: station_coords.get(s, (None, None))[0])
    segment_agg["from_lon"] = segment_agg["from_station"].map(
        lambda s: station_coords.get(s, (None, None))[1])
    segment_agg["to_lat"] = segment_agg["to_station"].map(
        lambda s: station_coords.get(s, (None, None))[0])
    segment_agg["to_lon"] = segment_agg["to_station"].map(
        lambda s: station_coords.get(s, (None, None))[1])

    geo = segment_agg.dropna(subset=["from_lat", "from_lon", "to_lat", "to_lon"])

    if geo.empty:
        st.warning("No segments matched to coordinates.")
        st.stop()

    max_total = geo["total_delay_min"].quantile(0.95)
    max_avg = geo["avg_increase_min"].quantile(0.95)

    m = folium.Map(location=[50.5, 4.35], zoom_start=8, tiles="cartodbpositron")

    for _, row in geo.iterrows():
        total = row["total_delay_min"]
        avg = row["avg_increase_min"]
        ratio = min(avg / max(max_avg, 0.1), 1.0)
        weight = max(2, min(10, 2 + 8 * min(total / max(max_total, 0.1), 1.0)))

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
        color = f"#{max(0,min(255,r)):02x}{max(0,min(255,g)):02x}{max(0,min(255,b)):02x}"

        folium.PolyLine(
            locations=[
                [row["from_lat"], row["from_lon"]],
                [row["to_lat"], row["to_lon"]],
            ],
            color=color,
            weight=weight,
            opacity=0.8,
            tooltip=(
                f"<b>{row['from_station']} -> {row['to_station']}</b><br/>"
                f"Total delay: {total:.0f} min<br/>"
                f"Avg increase: {avg:.1f} min<br/>"
                f"Incidents: {int(row['n_incidents'])}"
            ),
        ).add_to(m)

    cmap = cm.LinearColormap(
        colors=["#22b422", "#ffcc00", "#dd2020"],
        vmin=0, vmax=round(max_avg, 1),
        caption="Avg delay increase (min) — line thickness = total delay",
    )
    cmap.add_to(m)
    st_folium(m, width="stretch", height=650, key="prop_segments")

    st.subheader("Worst delay-introducing segments")
    top = geo.nlargest(25, "total_delay_min")[
        ["from_station", "to_station", "total_delay_min", "avg_increase_min",
         "n_incidents", "n_trains"]
    ].copy()
    top.columns = ["From", "To", "Total Delay (min)", "Avg Increase (min)",
                   "Incidents", "Trains"]
    top = top.round(1).reset_index(drop=True)
    top.index = top.index + 1
    st.dataframe(top, width="stretch")

render_footer()
