"""Station Reach Analysis page.

For each station, computes how many other stations are reachable within a
user-specified time budget (including transfers), then visualizes connectivity.
"""

import pandas as pd
import folium
import streamlit as st
from streamlit_folium import st_folium

from logic.shared import CUSTOM_CSS, render_sidebar_filters, load_all_data
from logic.geo import build_region_geojson, PROVINCE_TO_REGION
from logic.reachability import (
    build_timetable_graph, compute_reachability_single, compute_all_reachability,
)
from logic.rendering import make_step_colormap, render_reach_choropleth

st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

# ── Sidebar ──────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown('<p class="sidebar-section">View</p>', unsafe_allow_html=True)
    view_mode = st.radio("Display", ["Stations", "Provinces", "Regions"],
                         label_visibility="collapsed", horizontal=True)
    st.markdown('<hr class="sidebar-divider"/>', unsafe_allow_html=True)
    st.markdown('<p class="sidebar-section">Reach settings</p>', unsafe_allow_html=True)
    max_hours = st.number_input("Time budget (hours)", min_value=0.5, max_value=6.0,
                                value=1.5, step=0.5, format="%.1f")
    departure_hour = st.slider("Departure hour", 0, 23, 8)
    transfer_penalty = st.slider("Min transfer time (min)", 0, 15, 5)

filters = render_sidebar_filters()
data = load_all_data(filters)

# ── Cached heavy computations ────────────────────────────────────────────────

@st.cache_data(show_spinner="Building timetable graph...", ttl=3600)
def _cached_timetable(gtfs_stops, gtfs_stop_times, gtfs_trips, gtfs_calendar,
                      gtfs_calendar_dates, service_ids_tuple, hour_filter):
    """Cache timetable graph build (keyed on immutable inputs)."""
    gtfs = {
        "stops": gtfs_stops, "stop_times": gtfs_stop_times,
        "trips": gtfs_trips, "calendar": gtfs_calendar,
        "calendar_dates": gtfs_calendar_dates,
    }
    return build_timetable_graph(gtfs, set(service_ids_tuple), hour_filter)


@st.cache_data(show_spinner="Computing station reachability...", ttl=3600)
def _cached_reachability(station_ids_tuple, _station_departures, max_hours,
                          _stop_lookup, _prov_geo, transfer_penalty, departure_hour):
    """Cache full reachability computation."""
    return compute_all_reachability(
        list(station_ids_tuple), _station_departures, max_hours,
        _stop_lookup, _prov_geo,
        transfer_penalty_min=transfer_penalty,
        departure_hour=departure_hour,
    )


# Build timetable (cached)
gtfs = data["gtfs"]
station_departures = _cached_timetable(
    gtfs.get("stops"), gtfs.get("stop_times"), gtfs.get("trips"),
    gtfs.get("calendar"), gtfs.get("calendar_dates"),
    tuple(sorted(data["service_ids"])),
    filters["hour_filter"],
)

station_ids = list(data["stop_lookup"].keys())

# Compute reachability for all stations (cached)
reach_df = _cached_reachability(
    tuple(sorted(station_ids)), station_departures, max_hours,
    data["stop_lookup"], data["prov_geo"],
    transfer_penalty, departure_hour,
)

if reach_df.empty:
    st.warning("No reachability data computed.")
    st.stop()

# ── Header ───────────────────────────────────────────────────────────────────

st.caption(
    f"**{filters['start_date'].strftime('%d %b %Y')} – {filters['end_date'].strftime('%d %b %Y')}** "
    f"— {filters['day_count']} days — Departure {departure_hour}:00 — Budget {max_hours}h"
)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Stations", f"{len(reach_df):,}")
c2.metric("Max reachable", f"{reach_df['reachable_count'].max()}")
c3.metric("Avg reachable", f"{reach_df['reachable_count'].mean():.1f}")
c4.metric("Median reachable", f"{reach_df['reachable_count'].median():.0f}")

# ── Shared color scaling ─────────────────────────────────────────────────────

max_reach = reach_df["reachable_count"].max()
min_reach = reach_df["reachable_count"].min()
reach_spread = max(max_reach - min_reach, 1)


def _reach_color(count):
    """Map reachable count to a vivid blue gradient."""
    ratio = (count - min_reach) / reach_spread
    r = int(107 + (4 - 107) * ratio)
    g = int(174 + (47 - 174) * ratio)
    b = int(214 + (107 - 214) * ratio)
    return f"#{r:02x}{g:02x}{b:02x}"


# ═════════════════════════════════════════════════════════════════════════════
#  STATION VIEW
# ═════════════════════════════════════════════════════════════════════════════

if view_mode == "Stations":
    m = folium.Map(location=[50.5, 4.35], zoom_start=8, tiles="cartodbpositron")

    for _, row in reach_df.iterrows():
        ratio = (row["reachable_count"] - min_reach) / reach_spread
        radius = 4 + 10 * ratio
        color = _reach_color(row["reachable_count"])

        folium.CircleMarker(
            location=[row["lat"], row["lon"]],
            radius=radius, color=color, fill=True, fill_color=color,
            fill_opacity=0.85, weight=1.5,
            tooltip=(
                f"<b>{row['station_name']}</b><br/>"
                f"Reachable: {row['reachable_count']} stations<br/>"
                f"Avg travel: {row['avg_travel_time']:.0f} min"
            ),
        ).add_to(m)

    # Station selector for highlighting connections
    selected = st.selectbox(
        "Highlight station connections",
        options=["(none)"] + list(
            reach_df.sort_values("reachable_count", ascending=False)["station_name"]
        ),
        index=0,
    )

    if selected != "(none)":
        sel_row = reach_df[reach_df["station_name"] == selected].iloc[0]
        sel_id = sel_row["station_id"]

        reachable = compute_reachability_single(
            sel_id, station_departures, max_hours * 60,
            transfer_penalty_min=transfer_penalty,
            departure_hour=departure_hour,
        )

        # Origin marker
        folium.CircleMarker(
            location=[sel_row["lat"], sel_row["lon"]],
            radius=14, color="#e31a1c", fill=True, fill_color="#e31a1c",
            fill_opacity=0.9, weight=2,
            tooltip=f"<b>{sel_row['station_name']}</b> (ORIGIN)",
        ).add_to(m)

        # Lines to reachable stations
        for r_id, r_info in reachable.items():
            r_lookup = data["stop_lookup"].get(r_id)
            if not r_lookup:
                continue
            travel_min = r_info["travel_time"]
            time_ratio = min(travel_min / (max_hours * 60), 1.0)
            # Green (fast) to red (slow)
            lr = int(34 + (220 - 34) * time_ratio)
            lg = int(139 - 100 * time_ratio)
            lb = int(34 - 30 * time_ratio)
            lc = f"#{max(0,lr):02x}{max(0,lg):02x}{max(0,lb):02x}"

            folium.PolyLine(
                locations=[[sel_row["lat"], sel_row["lon"]], [r_lookup["lat"], r_lookup["lon"]]],
                color=lc, weight=2, opacity=0.65,
                tooltip=f"{r_lookup['name']}: {travel_min:.0f} min, {r_info['transfers']} transfer(s)",
            ).add_to(m)

            folium.CircleMarker(
                location=[r_lookup["lat"], r_lookup["lon"]],
                radius=5, color=lc, fill=True, fill_color=lc,
                fill_opacity=0.75, weight=1,
                tooltip=f"{r_lookup['name']}: {travel_min:.0f} min",
            ).add_to(m)

        st.info(f"**{sel_row['station_name']}** can reach **{len(reachable)}** stations within {max_hours}h.")

    st_folium(m, use_container_width=True, height=700, key="reach_map")

    # Data table
    st.subheader("Station Reachability Table")
    display_df = reach_df[["station_name", "reachable_count", "avg_travel_time", "province", "region"]].copy()
    display_df.columns = ["Station", "Reachable Stations", "Avg Travel (min)", "Province", "Region"]
    st.dataframe(display_df, use_container_width=True, height=400)

# ═════════════════════════════════════════════════════════════════════════════
#  PROVINCE VIEW
# ═════════════════════════════════════════════════════════════════════════════

elif view_mode == "Provinces":
    st.markdown("Average number of reachable stations per province.")

    prov_agg = reach_df.groupby("province").agg(
        avg_reachable=("reachable_count", "mean"),
        avg_travel_time=("avg_travel_time", "mean"),
        station_count=("station_id", "count"),
    ).round(1).sort_values("avg_reachable", ascending=False)

    prov_totals = prov_agg["avg_reachable"].to_dict()
    prov_vals = [v for v in prov_totals.values() if v > 0]

    if prov_vals:
        pcmap = make_step_colormap(prov_vals, "Avg reachable stations")
        pm = render_reach_choropleth(
            data["prov_geo"]["features"], prov_totals, pcmap, "name",
            lambda n, t: f"{n}: {t:.1f} avg reachable stations",
        )
        st_folium(pm, use_container_width=True, height=700, key="reach_prov_map")

    col_p1, col_p2 = st.columns(2)
    with col_p1:
        st.markdown("**Avg reachable stations**")
        st.bar_chart(prov_agg["avg_reachable"], color="#2171b5")
    with col_p2:
        st.markdown("**Avg travel time (min)**")
        st.bar_chart(prov_agg["avg_travel_time"], color="#08519c")

    st.dataframe(prov_agg, use_container_width=True)

# ═════════════════════════════════════════════════════════════════════════════
#  REGION VIEW
# ═════════════════════════════════════════════════════════════════════════════

elif view_mode == "Regions":
    st.markdown("Average reachability grouped by Belgium's three regions.")

    region_agg = reach_df.groupby("region").agg(
        avg_reachable=("reachable_count", "mean"),
        avg_travel_time=("avg_travel_time", "mean"),
        station_count=("station_id", "count"),
    ).round(1).sort_values("avg_reachable", ascending=False)

    rc1, rc2, rc3 = st.columns(3)
    for col, reg in zip([rc1, rc2, rc3], ["Brussels", "Flanders", "Wallonia"]):
        with col:
            if reg in region_agg.index:
                st.metric(reg, f"{region_agg.loc[reg, 'avg_reachable']:.1f}")
                st.caption(f"{int(region_agg.loc[reg, 'station_count'])} stations")
            else:
                st.metric(reg, "---")

    region_geo = build_region_geojson(data["prov_geo"])
    region_totals = region_agg["avg_reachable"].to_dict()
    region_vals = [v for v in region_totals.values() if v > 0]

    if region_vals:
        rcmap = make_step_colormap(region_vals, "Avg reachable stations")
        rm = render_reach_choropleth(
            region_geo["features"], region_totals, rcmap, "region",
            lambda n, t: f"{n}: {t:.1f} avg reachable stations",
        )
        st_folium(rm, use_container_width=True, height=700, key="reach_region_map")

    col_r1, col_r2 = st.columns(2)
    with col_r1:
        st.markdown("**Avg reachable stations**")
        st.bar_chart(region_agg["avg_reachable"], color="#2171b5")
    with col_r2:
        st.markdown("**Avg travel time (min)**")
        st.bar_chart(region_agg["avg_travel_time"], color="#08519c")

    st.dataframe(region_agg, use_container_width=True)

# Footer
st.markdown(
    '<div class="footer-credit">Powered by <strong>MobilityTwin.Brussels</strong> (ULB)</div>',
    unsafe_allow_html=True,
)
