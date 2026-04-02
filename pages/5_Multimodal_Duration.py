"""Multimodal Travel Duration page.

Door-to-door travel time from a user-specified address, combining SNCB,
De Lijn, STIB/MIVB, and TEC transit networks with walking first/last mile.
"""

import pandas as pd
import numpy as np
import folium
import streamlit as st
from streamlit_folium import st_folium
from datetime import date, datetime

from logic.shared import CUSTOM_CSS, render_footer, load_provinces_geojson, TOKEN
from logic.geocoding import geocode_address, geocode_suggestions
from logic.api import fetch_gtfs_operator, OPERATORS
from logic.multimodal import (
    build_multimodal_stop_lookup, build_multimodal_graph,
    build_transfer_edges, get_active_service_ids,
    bfs_from_point, bfs_to_point, find_nearby_stops,
    WALK_SPEED_KMH, MAX_WALK_KM,
)
from logic.geo import get_province, PROVINCE_TO_REGION, build_region_geojson
from logic.rendering import (
    duration_color, render_reach_choropleth, make_step_colormap,
    render_voronoi_map, render_gradient_map, TRANSPORT_SPEEDS,
    _add_legend_css,
)

st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

# ── Operator colors ──────────────────────────────────────────────────────────

OPERATOR_COLORS = {
    "SNCB": "#084594",
    "De Lijn": "#FFD700",
    "STIB": "#E30613",
    "TEC": "#00A550",
}

# ── Sidebar ──────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown('<p class="sidebar-section">View</p>', unsafe_allow_html=True)
    view_mode = st.radio("Display", ["Stations", "Provinces", "Regions", "Gradient"],
                         label_visibility="collapsed", horizontal=True)

    st.markdown('<hr class="sidebar-divider"/>', unsafe_allow_html=True)
    st.markdown('<p class="sidebar-section">Operators</p>', unsafe_allow_html=True)
    selected_operators = st.multiselect(
        "Transit operators", list(OPERATORS.keys()),
        default=list(OPERATORS.keys()),
        label_visibility="collapsed",
    )
    if not selected_operators:
        st.warning("Select at least one operator.")
        st.stop()

    display_operators = st.multiselect(
        "Show on map", selected_operators,
        default=["SNCB"] if "SNCB" in selected_operators else selected_operators[:1],
        help="Filter which operators' stops appear on the map. All operators are still used for routing.",
    )

    st.markdown('<hr class="sidebar-divider"/>', unsafe_allow_html=True)
    st.markdown('<p class="sidebar-section">Travel settings</p>', unsafe_allow_html=True)
    direction = st.radio("Direction", ["From address", "To address"],
                         horizontal=True,
                         help="**From address**: how long from the address to reach each stop. "
                              "**To address**: how long from each stop to reach the address.")
    max_hours = st.number_input("Time budget (hours)", min_value=0.5, max_value=4.0,
                                value=1.5, step=0.5, format="%.1f")
    departure_window = st.slider("Departure window", 0, 24, (7, 9), step=1)
    transfer_penalty = st.slider("Min transfer time (min)", 0, 15, 3)
    max_transfers = st.slider("Max transfers", 0, 5, 3)
    max_walk = st.slider("Max walking distance (km)", 0.5, 3.0, 1.5, step=0.5)

    if view_mode == "Gradient":
        mile_label = "Last-mile transport" if direction == "From address" else "First-mile transport"
        transport_mode = st.radio(mile_label, list(TRANSPORT_SPEEDS.keys()),
                                  horizontal=True)
    else:
        transport_mode = "Walk"

    st.markdown('<hr class="sidebar-divider"/>', unsafe_allow_html=True)
    st.markdown('<p class="sidebar-section">Date</p>', unsafe_allow_html=True)
    today = date.today()
    target_date = st.date_input("Travel date", value=today,
                                min_value=date(2024, 8, 21), max_value=today)

    token = TOKEN
    if not token:
        st.markdown('<hr class="sidebar-divider"/>', unsafe_allow_html=True)
        token = st.text_input("API Token", type="password",
                              help="Bearer token for api.mobilitytwin.brussels")
    if not token:
        st.info("Set `BRUSSELS_MOBILITY_TWIN_KEY` in `.env` or enter a token above.")
        st.stop()

    st.markdown('<hr class="sidebar-divider"/>', unsafe_allow_html=True)
    st.markdown(
        '<div class="footer-credit">Powered by<br/><strong>MobilityTwin.Brussels</strong><br/>(ULB)</div>',
        unsafe_allow_html=True,
    )

# ── Address input ────────────────────────────────────────────────────────────

st.markdown("### 🗺️ Multimodal Travel Duration")

address_input = st.text_input(
    "📍 Enter an address in Belgium",
    placeholder="e.g. Grand Place 1, Bruxelles",
    help="Uses OpenStreetMap Nominatim for geocoding.",
)

if not address_input:
    st.info("Enter a Belgian address above to compute travel times.")
    st.stop()

# Geocode
location = geocode_address(address_input)
if not location:
    st.error(f"Could not geocode '{address_input}'. Try a more specific address.")
    st.stop()

origin_lat, origin_lon = location["lat"], location["lon"]
st.success(f"📍 **{location['display_name']}** — ({origin_lat:.5f}, {origin_lon:.5f})")

# ── Load GTFS data ───────────────────────────────────────────────────────────

ts = int(datetime(target_date.year, target_date.month, 1).timestamp())
target_dates = [target_date]


@st.cache_data(show_spinner=False, ttl=3600)
def _load_multimodal_data(_operators, _ts, _token, _target_dates, _hour_filter):
    """Load and merge GTFS feeds from all selected operators."""
    feeds = {}
    sids_per_op = {}

    progress_bar = st.progress(0, text="Loading GTFS data…")
    n_ops = len(_operators)

    for i, op_name in enumerate(_operators):
        slug = OPERATORS[op_name]
        base_pct = i / n_ops
        step_pct = 1 / n_ops

        def _on_progress(downloaded, total, _base=base_pct, _step=step_pct):
            dl_ratio = min(downloaded / total, 1.0)
            pct = _base + _step * dl_ratio * 0.8  # 80% download, 20% parse
            progress_bar.progress(
                min(pct, 1.0),
                text=f"Downloading {op_name}… {downloaded / 1e6:.0f} / {total / 1e6:.0f} MB",
            )

        try:
            progress_bar.progress(
                base_pct, text=f"Downloading {op_name}…",
            )
            feed = fetch_gtfs_operator(slug, _ts, _token, _progress_cb=_on_progress)
        except Exception as e:
            st.warning(f"Could not load {op_name}: {e}")
            continue

        progress_bar.progress(
            base_pct + step_pct * 0.9,
            text=f"Parsing {op_name} GTFS…",
        )

        if feed.stop_times is None or feed.trips is None:
            st.warning(f"{op_name} GTFS data incomplete, skipping.")
            continue

        sids = get_active_service_ids(feed, _target_dates)
        if not sids:
            st.warning(f"No active services for {op_name} on {_target_dates[0]}")
            continue

        feeds[op_name] = feed
        sids_per_op[op_name] = sids

    if not feeds:
        progress_bar.empty()
        return None

    progress_bar.progress(0.92, text="Building stop lookup…")
    stop_lookup = build_multimodal_stop_lookup(feeds)
    progress_bar.progress(0.95, text="Building timetable graph…")
    graph = build_multimodal_graph(feeds, sids_per_op, _hour_filter)
    progress_bar.progress(0.98, text="Building transfer edges…")
    transfers = build_transfer_edges(stop_lookup, max_walk_km=0.4)
    progress_bar.progress(1.0, text="Done!")
    progress_bar.empty()

    return {
        "stop_lookup": stop_lookup,
        "graph": graph,
        "transfers": transfers,
        "operators_loaded": list(feeds.keys()),
    }


data = _load_multimodal_data(
    tuple(selected_operators), ts, token,
    tuple(target_dates), tuple(departure_window),
)

if data is None:
    st.error("No GTFS data could be loaded for any selected operator.")
    st.stop()

stop_lookup = data["stop_lookup"]
graph = data["graph"]
transfers = data["transfers"]

# ── Compute travel times ─────────────────────────────────────────────────────

max_minutes = max_hours * 60


@st.cache_data(show_spinner="Computing multimodal travel times...", ttl=3600)
def _compute_travel_times(_lat, _lon, _graph, _transfers, _stop_lookup,
                          _max_min, _dep_window, _max_transfers,
                          _transfer_penalty, _max_walk, _direction):
    if _direction == "From address":
        return bfs_from_point(
            _lat, _lon, _stop_lookup, _graph, _transfers,
            _max_min, _dep_window, _max_transfers,
            _transfer_penalty, _max_walk,
        )
    else:
        return bfs_to_point(
            _lat, _lon, _stop_lookup, _graph, _transfers,
            _max_min, _dep_window, _max_transfers,
            _transfer_penalty, _max_walk,
        )


reachable = _compute_travel_times(
    origin_lat, origin_lon,
    graph, transfers, stop_lookup,
    max_minutes, departure_window, max_transfers,
    transfer_penalty, max_walk, direction,
)

# ── Build results DataFrame ──────────────────────────────────────────────────

prov_geo = load_provinces_geojson()


def _build_result_df():
    rows = []
    for sid, info in stop_lookup.items():
        if sid in reachable:
            r = reachable[sid]
            tt = r["travel_time"]
            tr = r["transfers"]
            wt = r["walk_time"]
        else:
            tt, tr, wt = None, None, None

        province = get_province(info["lat"], info["lon"], prov_geo)
        region = PROVINCE_TO_REGION.get(province, "Unknown") if province else "Unknown"

        rows.append({
            "station_id": sid,
            "station_name": info["name"],
            "operator": info["operator"],
            "lat": info["lat"],
            "lon": info["lon"],
            "province": province or "Unknown",
            "region": region,
            "travel_time": tt,
            "transfers": tr,
            "walk_time": wt,
        })
    return pd.DataFrame(rows)


df = _build_result_df()
# Filter for display (routing uses all operators)
df_display = df[df["operator"].isin(display_operators)] if display_operators else df
df_ok = df_display[df_display["travel_time"].notna()]
df_na = df_display[df_display["travel_time"].isna()]

# Full stats (all operators)
df_ok_all = df[df["travel_time"].notna()]

if df_ok_all.empty:
    st.warning("No stops reachable from this address with the current settings. "
               "Try increasing the time budget or walking distance.")
    st.stop()

# ── Header ───────────────────────────────────────────────────────────────────

dir_label = "from" if direction == "From address" else "to"
ops_str = ", ".join(data["operators_loaded"])
st.caption(
    f"**{target_date.strftime('%a %d %b %Y')}** — {dir_label} **{location['display_name'][:60]}** "
    f"— Budget {max_hours}h — Departures {departure_window[0]}h–{departure_window[1]}h "
    f"— {ops_str}"
)

with st.expander("ℹ️ How is this computed?"):
    st.markdown(f"""
**Door-to-door multimodal travel time**

This page computes the total travel time from a specific address to every reachable
transit stop in Belgium, combining **walking** + **public transit** from multiple operators.

**Operators**: {ops_str}

**Algorithm**
1. The address is geocoded to geographic coordinates using OpenStreetMap Nominatim.
2. All transit stops within **{max_walk} km** of the address are identified as starting points.
3. Walking time to each starting stop is computed at **{WALK_SPEED_KMH} km/h**.
4. A Dijkstra-like BFS explores the combined timetable graph:
   - Each operator's GTFS schedule is loaded and unified into a single time-expanded graph.
   - **Transfers between operators** are enabled when stops of different operators are within **400m** of each other (walking connection).
   - The search respects actual departure/arrival times, transfer penalties ({transfer_penalty} min), and max transfers ({max_transfers}).
5. The result is the minimum total travel time (walk + transit) to each reachable stop.

**Views**
- *Stations*: circle per stop, colored by travel time (green = fast, red = slow), with operator-coded outline.
- *Provinces / Regions*: average travel time per area.
- *Gradient*: continuous heatmap. Total time = transit to nearest stop + last-mile distance at selected speed.
    """)

# Metrics (computed on all operators, not just displayed ones)
n_reachable = len(df_ok_all)
ops_reachable = df_ok_all["operator"].nunique()
avg_time = df_ok_all["travel_time"].mean()
median_time = df_ok_all["travel_time"].median()

c1, c2, c3, c4 = st.columns(4)
c1.metric("Reachable stops", f"{n_reachable:,}")
c2.metric("Operators", f"{ops_reachable}")
c3.metric("Avg travel time", f"{avg_time:.0f} min")
c4.metric("Median", f"{median_time:.0f} min")

# Per-operator breakdown
op_counts = df_ok_all.groupby("operator").agg(
    stops=("station_id", "count"),
    avg_time=("travel_time", "mean"),
).round(1)
op_cols = st.columns(len(data["operators_loaded"]))
for col, op in zip(op_cols, data["operators_loaded"]):
    with col:
        if op in op_counts.index:
            st.metric(
                f"{op}",
                f"{int(op_counts.loc[op, 'stops'])} stops",
                delta=f"avg {op_counts.loc[op, 'avg_time']:.0f} min",
                delta_color="off",
            )

# ── Map rendering ────────────────────────────────────────────────────────────

global_max_time = df_ok["travel_time"].max()

if view_mode == "Stations":
    m = folium.Map(location=[origin_lat, origin_lon], zoom_start=11,
                   tiles="cartodbpositron")

    # Origin marker
    folium.Marker(
        location=[origin_lat, origin_lon],
        popup=f"<b>{location['display_name'][:80]}</b>",
        tooltip="📍 Origin",
        icon=folium.Icon(color="red", icon="home", prefix="fa"),
    ).add_to(m)

    # Reachable stops
    for _, row in df_ok.iterrows():
        t = row["travel_time"]
        ratio = t / global_max_time if global_max_time > 0 else 0
        radius = 3 + 8 * (1 - ratio)
        fill_color = duration_color(t, global_max_time)
        border_color = OPERATOR_COLORS.get(row["operator"], "#333")

        folium.CircleMarker(
            location=[row["lat"], row["lon"]],
            radius=radius, color=border_color, fill=True,
            fill_color=fill_color, fill_opacity=0.8, weight=2,
            tooltip=(
                f"<b>{row['station_name']}</b> ({row['operator']})<br/>"
                f"Total: {t:.0f} min<br/>"
                f"Walking: {row['walk_time']:.0f} min<br/>"
                f"Transfers: {row['transfers']}"
            ),
        ).add_to(m)

    # Walking radius circle
    folium.Circle(
        location=[origin_lat, origin_lon],
        radius=max_walk * 1000,
        color="#e31a1c", weight=1, dash_array="5",
        fill=False, tooltip=f"Walking radius ({max_walk} km)",
    ).add_to(m)

    st_folium(m, use_container_width=True, height=650, key="mm_station_map")

    # Data table
    with st.expander("Stop data"):
        display = df_ok[["station_name", "operator", "travel_time", "walk_time",
                         "transfers", "province"]].copy()
        display.columns = ["Stop", "Operator", "Total (min)", "Walking (min)",
                           "Transfers", "Province"]
        st.dataframe(
            display.sort_values("Total (min)").reset_index(drop=True),
            use_container_width=True, height=400,
        )

elif view_mode == "Provinces":
    st.markdown("Average travel time per province (reachable stops only).")
    prov_agg = df_ok.groupby("province").agg(
        avg_time=("travel_time", "mean"),
        stop_count=("station_id", "count"),
    ).round(1).sort_values("avg_time")

    prov_totals = prov_agg["avg_time"].to_dict()
    prov_vals = [v for v in prov_totals.values() if v > 0]
    if prov_vals:
        pcmap = make_step_colormap(prov_vals, "Avg travel time (min)")
        pm = render_reach_choropleth(
            prov_geo["features"], prov_totals, pcmap, "name",
            lambda n, t: f"{n}: {t:.0f} min avg ({prov_agg.loc[n, 'stop_count'] if n in prov_agg.index else 0} stops)",
        )
        # Add origin marker
        folium.Marker(
            location=[origin_lat, origin_lon],
            icon=folium.Icon(color="red", icon="home", prefix="fa"),
            tooltip="📍 Origin",
        ).add_to(pm)
        st_folium(pm, use_container_width=True, height=650, key="mm_prov_map")
    st.dataframe(prov_agg, use_container_width=True)

elif view_mode == "Regions":
    st.markdown("Average travel time by region.")
    region_agg = df_ok.groupby("region").agg(
        avg_time=("travel_time", "mean"),
        stop_count=("station_id", "count"),
    ).round(1).sort_values("avg_time")

    rc1, rc2, rc3 = st.columns(3)
    for col, reg in zip([rc1, rc2, rc3], ["Brussels", "Flanders", "Wallonia"]):
        with col:
            if reg in region_agg.index:
                st.metric(reg, f"{region_agg.loc[reg, 'avg_time']:.0f} min")
                st.caption(f"{int(region_agg.loc[reg, 'stop_count'])} stops")
            else:
                st.metric(reg, "—")

    region_geo = build_region_geojson(prov_geo)
    region_totals = region_agg["avg_time"].to_dict()
    region_vals = [v for v in region_totals.values() if v > 0]
    if region_vals:
        rcmap = make_step_colormap(region_vals, "Avg travel time (min)")
        rm = render_reach_choropleth(
            region_geo["features"], region_totals, rcmap, "region",
            lambda n, t: f"{n}: {t:.0f} min avg",
        )
        folium.Marker(
            location=[origin_lat, origin_lon],
            icon=folium.Icon(color="red", icon="home", prefix="fa"),
            tooltip="📍 Origin",
        ).add_to(rm)
        st_folium(rm, use_container_width=True, height=650, key="mm_region_map")
    st.dataframe(region_agg, use_container_width=True)

elif view_mode == "Gradient":
    st.markdown("Continuous heatmap: transit time to nearest reachable stop + last-mile distance.")
    mile_kind = "last" if direction == "From address" else "first"
    gm = render_gradient_map(df, global_max_time, transport_mode, prov_geo,
                             mile_kind=mile_kind)
    # Add origin marker
    folium.Marker(
        location=[origin_lat, origin_lon],
        icon=folium.Icon(color="red", icon="home", prefix="fa"),
        tooltip="📍 Origin",
    ).add_to(gm)
    st_folium(gm, use_container_width=True, height=650, key="mm_gradient_map")

render_footer()
