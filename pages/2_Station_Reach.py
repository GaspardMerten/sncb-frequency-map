"""Station Reach Analysis page.

For each station, computes how many other stations are reachable within a
user-specified time budget (including transfers), then visualizes connectivity
on a map with aggregated stats by province and region.
"""

import pandas as pd
import numpy as np
import folium
import streamlit as st
from streamlit_folium import st_folium
from collections import defaultdict

from logic.shared import CUSTOM_CSS, render_sidebar_filters, load_all_data
from logic.geo import get_province, PROVINCE_TO_REGION, haversine_km
from logic.gtfs import compute_segment_frequencies
from logic.matching import map_frequencies_to_infra, build_infra_graph
from logic.reachability import (
    build_timetable_graph, compute_reachability_single, compute_all_reachability,
)
from logic.rendering import PALETTE

st.set_page_config(page_title="Station Reach Analysis", layout="wide", page_icon="🚆")
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

# ── Sidebar: shared filters + reach-specific controls ────────────────────────

with st.sidebar:
    st.markdown('<p class="sidebar-section">Reach settings</p>', unsafe_allow_html=True)
    max_hours = st.number_input("Time budget (hours)", min_value=0.5, max_value=6.0,
                                value=1.5, step=0.5, format="%.1f")
    departure_hour = st.slider("Departure hour", 0, 23, 8)
    transfer_penalty = st.slider("Min transfer time (min)", 0, 15, 5)

filters = render_sidebar_filters()
data = load_all_data(filters)

# ── Build timetable graph ────────────────────────────────────────────────────

with st.spinner("Building timetable graph..."):
    station_departures = build_timetable_graph(
        data["gtfs"], data["service_ids"], filters["hour_filter"],
    )

station_ids = list(data["stop_lookup"].keys())
n_stations = len(station_ids)

st.caption(
    f"**{filters['start_date'].strftime('%d %b %Y')} – {filters['end_date'].strftime('%d %b %Y')}** "
    f"— {filters['day_count']} days — Departure {departure_hour}:00 — Budget {max_hours}h"
)

# ── Compute reachability for all stations ────────────────────────────────────

with st.spinner(f"Computing reachability for {n_stations} stations..."):
    reach_df = compute_all_reachability(
        station_ids, station_departures, max_hours,
        data["stop_lookup"], data["prov_geo"],
        transfer_penalty_min=transfer_penalty,
        departure_hour=departure_hour,
    )

if reach_df.empty:
    st.warning("No reachability data computed.")
    st.stop()

# ── Metrics ──────────────────────────────────────────────────────────────────

c1, c2, c3, c4 = st.columns(4)
c1.metric("Stations analyzed", f"{len(reach_df):,}")
c2.metric("Max reachable", f"{reach_df['reachable_count'].max()}")
c3.metric("Avg reachable", f"{reach_df['reachable_count'].mean():.1f}")
c4.metric("Median reachable", f"{reach_df['reachable_count'].median():.0f}")

# ── Map: station circles colored by reachability ─────────────────────────────

st.subheader("Reachability Map")
st.markdown("Click a station to highlight its reachable connections.")

# Check if user clicked a station (via session state)
if "selected_station" not in st.session_state:
    st.session_state.selected_station = None

# Build the map
m = folium.Map(location=[50.5, 4.35], zoom_start=8, tiles="cartodbpositron")

max_reach = reach_df["reachable_count"].max()
min_reach = reach_df["reachable_count"].min()
reach_spread = max(max_reach - min_reach, 1)


def _reach_color(count):
    """Map reachable count to a blue gradient color."""
    ratio = (count - min_reach) / reach_spread
    r = int(184 + (8 - 184) * ratio)
    g = int(212 + (69 - 212) * ratio)
    b = int(240 + (148 - 240) * ratio)
    return f"#{r:02x}{g:02x}{b:02x}"


# Add station markers
for _, row in reach_df.iterrows():
    ratio = (row["reachable_count"] - min_reach) / reach_spread
    radius = 4 + 10 * ratio
    color = _reach_color(row["reachable_count"])

    folium.CircleMarker(
        location=[row["lat"], row["lon"]],
        radius=radius,
        color=color,
        fill=True,
        fill_color=color,
        fill_opacity=0.8,
        weight=1.5,
        tooltip=(
            f"<b>{row['station_name']}</b><br/>"
            f"Reachable: {row['reachable_count']} stations<br/>"
            f"Avg travel: {row['avg_travel_time']:.0f} min"
        ),
        popup=folium.Popup(
            f"<b>{row['station_name']}</b><br/>"
            f"Reachable: {row['reachable_count']}<br/>"
            f"Click button below to highlight.",
            max_width=200,
        ),
    ).add_to(m)

# Station selector for highlighting
selected = st.selectbox(
    "Highlight station connections",
    options=["(none)"] + list(reach_df.sort_values("reachable_count", ascending=False)["station_name"]),
    index=0,
)

if selected != "(none)":
    sel_row = reach_df[reach_df["station_name"] == selected].iloc[0]
    sel_id = sel_row["station_id"]

    # Compute reachability for selected station
    reachable = compute_reachability_single(
        sel_id, station_departures, max_hours * 60,
        transfer_penalty_min=transfer_penalty,
        departure_hour=departure_hour,
    )

    # Highlight the origin station
    folium.CircleMarker(
        location=[sel_row["lat"], sel_row["lon"]],
        radius=14, color="#e31a1c", fill=True, fill_color="#e31a1c",
        fill_opacity=0.9, weight=2,
        tooltip=f"<b>{sel_row['station_name']}</b> (ORIGIN)",
    ).add_to(m)

    # Draw lines to all reachable stations
    for r_id, r_info in reachable.items():
        r_lookup = data["stop_lookup"].get(r_id)
        if not r_lookup:
            continue

        travel_min = r_info["travel_time"]
        # Color by travel time: green (fast) to orange (slow)
        time_ratio = min(travel_min / (max_hours * 60), 1.0)
        r_val = int(34 + (255 - 34) * time_ratio)
        g_val = int(139 + (140 - 139) * time_ratio)
        b_val = int(34 + (0 - 34) * time_ratio)
        line_color = f"#{r_val:02x}{g_val:02x}{b_val:02x}"

        # Draw connection line
        folium.PolyLine(
            locations=[
                [sel_row["lat"], sel_row["lon"]],
                [r_lookup["lat"], r_lookup["lon"]],
            ],
            color=line_color,
            weight=2,
            opacity=0.6,
            tooltip=f"→ {r_lookup['name']}: {travel_min:.0f} min, {r_info['transfers']} transfer(s)",
        ).add_to(m)

        # Mark reachable station
        folium.CircleMarker(
            location=[r_lookup["lat"], r_lookup["lon"]],
            radius=5, color=line_color, fill=True, fill_color=line_color,
            fill_opacity=0.7, weight=1,
            tooltip=f"{r_lookup['name']}: {travel_min:.0f} min",
        ).add_to(m)

    st.info(f"**{sel_row['station_name']}** can reach **{len(reachable)}** stations within {max_hours}h.")

map_data = st_folium(m, use_container_width=True, height=700, key="reach_map")

# ── Station data table ───────────────────────────────────────────────────────

st.subheader("Station Reachability Table")
display_df = reach_df[["station_name", "reachable_count", "avg_travel_time", "province", "region"]].copy()
display_df.columns = ["Station", "Reachable Stations", "Avg Travel Time (min)", "Province", "Region"]
st.dataframe(display_df, use_container_width=True, height=400)

# ── Aggregated stats by province and region ──────────────────────────────────

st.subheader("Aggregated by Province")

prov_agg = reach_df.groupby("province").agg(
    avg_reachable=("reachable_count", "mean"),
    avg_travel_time=("avg_travel_time", "mean"),
    station_count=("station_id", "count"),
).round(1).sort_values("avg_reachable", ascending=False)

col_p1, col_p2 = st.columns(2)
with col_p1:
    st.markdown("**Avg reachable stations**")
    st.bar_chart(prov_agg["avg_reachable"], color="#2171b5")
with col_p2:
    st.markdown("**Avg travel time (min)**")
    st.bar_chart(prov_agg["avg_travel_time"], color="#4a90c4")

st.dataframe(prov_agg, use_container_width=True)

st.subheader("Aggregated by Region")

region_agg = reach_df.groupby("region").agg(
    avg_reachable=("reachable_count", "mean"),
    avg_travel_time=("avg_travel_time", "mean"),
    station_count=("station_id", "count"),
).round(1).sort_values("avg_reachable", ascending=False)

col_r1, col_r2 = st.columns(2)
with col_r1:
    st.markdown("**Avg reachable stations**")
    st.bar_chart(region_agg["avg_reachable"], color="#2171b5")
with col_r2:
    st.markdown("**Avg travel time (min)**")
    st.bar_chart(region_agg["avg_travel_time"], color="#4a90c4")

st.dataframe(region_agg, use_container_width=True)

# Footer
st.markdown(
    '<div class="footer-credit">Powered by <strong>MobilityTwin.Brussels</strong> (ULB)</div>',
    unsafe_allow_html=True,
)
