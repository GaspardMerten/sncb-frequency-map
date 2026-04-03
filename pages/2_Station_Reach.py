"""Station Reach Analysis page.

For each station, computes how many other stations are reachable within a
user-specified time budget (including transfers), then visualizes connectivity.
"""

import folium
import streamlit as st
from streamlit_folium import st_folium

from logic.shared import CUSTOM_CSS, render_sidebar_filters, load_all_data, render_footer
from logic.geo import build_region_geojson
from logic.reachability import compute_reachability_single, compute_all_reachability
from logic.matching import (
    build_infra_segment_index, build_infra_index_and_graph, find_path,
)
from logic.rendering import make_step_colormap, render_reach_choropleth, ratio_to_blue, duration_color, render_voronoi_map

st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

# ── Sidebar ──────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown('<p class="sidebar-section">View</p>', unsafe_allow_html=True)
    view_mode = st.radio("Display", ["Stations", "Provinces", "Regions", "Voronoi"],
                         label_visibility="collapsed", horizontal=True)
    st.markdown('<hr class="sidebar-divider"/>', unsafe_allow_html=True)
    st.markdown('<p class="sidebar-section">Reach settings</p>', unsafe_allow_html=True)
    max_hours = st.number_input("Time budget (hours)", min_value=0.5, max_value=6.0,
                                value=1.5, step=0.5, format="%.1f")
    departure_window = st.slider("Departure window", 0, 24, (7, 9), step=1)
    transfer_penalty = st.slider("Min transfer time (min)", 0, 15, 5)
    max_transfers = st.slider("Max transfers", 0, 5, 3)

filters = render_sidebar_filters()
data = load_all_data(filters)

station_departures = data["station_departures"]
cluster_map = data.get("cluster_map")

# ── Cached heavy computations ────────────────────────────────────────────────

@st.cache_data(show_spinner="Computing station reachability...", ttl=3600)
def _cached_reachability(station_ids_tuple, _station_departures, max_hours,
                          _stop_lookup, _prov_geo, transfer_penalty, departure_window,
                          max_transfers):
    return compute_all_reachability(
        list(station_ids_tuple), _station_departures, max_hours,
        _stop_lookup, _prov_geo,
        transfer_penalty_min=transfer_penalty,
        departure_window=departure_window,
        max_transfers=max_transfers,
    )


station_ids = list(data["stop_lookup"].keys())

reach_df = _cached_reachability(
    tuple(sorted(station_ids)), station_departures, max_hours,
    data["stop_lookup"], data["prov_geo"],
    transfer_penalty, departure_window, max_transfers,
)

if reach_df.empty:
    st.warning("No reachability data computed.")
    st.stop()

# ── Header ───────────────────────────────────────────────────────────────────

st.caption(
    f"**{filters['start_date'].strftime('%d %b %Y')} – {filters['end_date'].strftime('%d %b %Y')}** "
    f"— {filters['day_count']} days — Departures {departure_window[0]}h–{departure_window[1]}h — Budget {max_hours}h"
)

with st.expander("ℹ️ How is this computed?"):
    st.markdown("""
**What it measures**

For each station: *how many other stations can you reach within a given time budget, allowing transfers?*

**Algorithm — Breadth-First Search (BFS) on the timetable**
1. A timetable graph is built from GTFS data: for every station, the list of departures (destination, departure time, arrival time, trip ID) during the selected time window.
2. Starting from a station every 5 minutes in the **departure window** (e.g. 7:00–9:00), the algorithm explores all reachable destinations by following actual train connections.
3. **Transfers** are allowed: when arriving at an intermediate station, you can board a different train after a minimum transfer time (configurable, default 5 min).
4. The search stops when the travel time exceeds the **time budget** or the **maximum number of transfers** is reached.
5. The best result (shortest time, fewest transfers) across all departure minutes is kept.

**Metrics per station**
- **Reachable count**: number of distinct stations reachable within the budget.
- **Avg travel time**: average travel time (in minutes) to all reachable stations.

**Views**
- *Stations*: circle size and color reflect reachable count. Select one station to see its connections drawn along real track geometry.
- *Provinces / Regions*: average reachable count per area.
- *Voronoi*: territory per station, colored by reachable count.
    """)

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
    ratio = (count - min_reach) / reach_spread
    return ratio_to_blue(ratio)


def _time_color(travel_min, max_min):
    """Green (fast) -> yellow -> red (slow)."""
    return duration_color(travel_min, max_min)


def _draw_infra_path(m, path, stop_lookup, gtfs_to_infra, infra_index, infra_graph,
                      color, weight, opacity, tooltip):
    """Draw a reachability path using Infrabel segment geometry when available."""
    from logic.geo import coords_to_latlon
    drawn = False
    for i in range(len(path) - 1):
        a_infra = gtfs_to_infra.get(path[i])
        b_infra = gtfs_to_infra.get(path[i + 1])
        if a_infra and b_infra and a_infra != b_infra:
            # Try direct segment
            seg_key = tuple(sorted([a_infra, b_infra]))
            if seg_key in infra_index:
                coords = coords_to_latlon(infra_index[seg_key])
                folium.PolyLine(coords, color=color, weight=weight,
                                opacity=opacity, tooltip=tooltip).add_to(m)
                drawn = True
                continue
            # Try BFS path through infra
            infra_path = find_path(infra_graph, a_infra, b_infra, max_depth=10)
            if infra_path:
                for j in range(len(infra_path) - 1):
                    sk = tuple(sorted([infra_path[j], infra_path[j + 1]]))
                    if sk in infra_index:
                        coords = coords_to_latlon(infra_index[sk])
                        folium.PolyLine(coords, color=color, weight=weight,
                                        opacity=opacity, tooltip=tooltip).add_to(m)
                        drawn = True
                continue
        # Fallback: straight line for this hop
        a_info = stop_lookup.get(path[i])
        b_info = stop_lookup.get(path[i + 1])
        if a_info and b_info:
            folium.PolyLine(
                [[a_info["lat"], a_info["lon"]], [b_info["lat"], b_info["lon"]]],
                color=color, weight=weight, opacity=opacity,
                tooltip=tooltip, dash_array="6",
            ).add_to(m)
            drawn = True
    return drawn


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
            max_transfers=max_transfers,
            transfer_penalty_min=transfer_penalty,
            departure_window=departure_window,
        )

        # Build infra index for path rendering
        infra_index, infra_graph = build_infra_index_and_graph(data["infrabel_segs"], cluster_map)

        # Origin marker
        folium.CircleMarker(
            location=[sel_row["lat"], sel_row["lon"]],
            radius=14, color="#e31a1c", fill=True, fill_color="#e31a1c",
            fill_opacity=0.9, weight=2,
            tooltip=f"<b>{sel_row['station_name']}</b> (ORIGIN)",
        ).add_to(m)

        max_min = max_hours * 60
        for r_id, r_info in reachable.items():
            r_lookup = data["stop_lookup"].get(r_id)
            if not r_lookup:
                continue
            travel_min = r_info["travel_time"]
            lc = _time_color(travel_min, max_min)
            path = r_info.get("path", [])

            tooltip_text = f"{r_lookup['name']}: {travel_min:.0f} min, {r_info['transfers']} transfer(s)"

            if len(path) >= 2:
                _draw_infra_path(m, path, data["stop_lookup"], data["gtfs_to_infra"],
                                  infra_index, infra_graph,
                                  color=lc, weight=3, opacity=0.75,
                                  tooltip=tooltip_text)

            folium.CircleMarker(
                location=[r_lookup["lat"], r_lookup["lon"]],
                radius=5, color=lc, fill=True, fill_color=lc,
                fill_opacity=0.75, weight=1,
                tooltip=f"{r_lookup['name']}: {travel_min:.0f} min",
            ).add_to(m)

        st.info(f"**{sel_row['station_name']}** can reach **{len(reachable)}** stations within {max_hours}h.")

    st_folium(m, width="stretch", height=700, key="reach_map")

    st.subheader("Station Reachability Table")
    display_df = reach_df[["station_name", "reachable_count", "avg_travel_time", "province", "region"]].copy()
    display_df.columns = ["Station", "Reachable Stations", "Avg Travel (min)", "Province", "Region"]
    st.dataframe(display_df, width="stretch", height=400)

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
        st_folium(pm, width="stretch", height=700, key="reach_prov_map")

    col_p1, col_p2 = st.columns(2)
    with col_p1:
        st.markdown("**Avg reachable stations**")
        st.bar_chart(prov_agg["avg_reachable"], color="#2171b5")
    with col_p2:
        st.markdown("**Avg travel time (min)**")
        st.bar_chart(prov_agg["avg_travel_time"], color="#08519c")

    st.dataframe(prov_agg, width="stretch")

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
        st_folium(rm, width="stretch", height=700, key="reach_region_map")

    col_r1, col_r2 = st.columns(2)
    with col_r1:
        st.markdown("**Avg reachable stations**")
        st.bar_chart(region_agg["avg_reachable"], color="#2171b5")
    with col_r2:
        st.markdown("**Avg travel time (min)**")
        st.bar_chart(region_agg["avg_travel_time"], color="#08519c")

    st.dataframe(region_agg, width="stretch")

elif view_mode == "Voronoi":
    st.markdown("Voronoi tessellation — each cell colored by its station's reachable count.")
    vm = render_voronoi_map(
        reach_df, "reachable_count",
        color_fn=lambda v, vmin, vmax: ratio_to_blue(
            (v - vmin) / max(vmax - vmin, 1)),
        tooltip_fn=lambda r: (
            f"<b>{r['station_name']}</b><br/>"
            f"Reachable: {r['reachable_count']} stations<br/>"
            f"Avg travel: {r['avg_travel_time']:.0f} min"
        ),
        prov_geo=data["prov_geo"],
    )
    st_folium(vm, width="stretch", height=700, key="reach_voronoi_map")

render_footer()
