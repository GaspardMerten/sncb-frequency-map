"""Stop Accessibility page.

Gradient map showing how long it takes from any point in Belgium to reach
the nearest transit stop, for selected operators and transport modes.

Uses scipy cKDTree for O(n log k) nearest-stop lookup instead of brute-force.
Belgium mask is cached across calls. RGBA image built in a single pass.
"""

import os
import io
import base64
from datetime import date, datetime, timedelta

import numpy as np
import folium
import streamlit as st
from streamlit_folium import st_folium
import branca.colormap as cm
from shapely.geometry import Point
from shapely import prepared as shp_prepared
from scipy.spatial import cKDTree
from dotenv import load_dotenv

from logic.shared import CUSTOM_CSS, render_footer, load_provinces_geojson, noon_timestamp
from logic.api import fetch_gtfs_operator, OPERATORS
from logic.multimodal import (
    build_multimodal_stop_lookup, build_multimodal_graph,
    build_transfer_edges, get_active_service_ids,
    bfs_from_stops, WALK_SPEED_KMH,
)
from logic.geo import BE_LAT_MIN, BE_LAT_MAX, BE_LON_MIN, BE_LON_MAX
from logic.rendering import _get_belgium_border, _add_legend_css

load_dotenv()

st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

TOKEN = os.getenv("BRUSSELS_MOBILITY_TWIN_KEY", "")

LAST_MILE_SPEEDS = {"Bike": 15.0, "Walk": 4.5}  # km/h

OPERATOR_COLORS = {
    "SNCB": "#084594",
    "De Lijn": "#FFD700",
    "STIB": "#E30613",
    "TEC": "#00A550",
}

# ── Sidebar ──────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown('<p class="sidebar-section">View</p>', unsafe_allow_html=True)
    view_mode = st.radio("Display", ["Gradient", "Stations"],
                         label_visibility="collapsed", horizontal=True)

    st.markdown('<hr class="sidebar-divider"/>', unsafe_allow_html=True)
    st.markdown('<p class="sidebar-section">Destination stops</p>', unsafe_allow_html=True)
    dest_operators = st.multiselect(
        "Stops to reach", list(OPERATORS.keys()),
        default=["SNCB"],
        help="Which operators' stops do you want to reach?",
        label_visibility="collapsed",
    )
    if not dest_operators:
        st.warning("Select at least one destination operator.")
        st.stop()

    st.markdown('<hr class="sidebar-divider"/>', unsafe_allow_html=True)
    st.markdown('<p class="sidebar-section">Feeder transit</p>', unsafe_allow_html=True)
    use_feeder = st.toggle("Use public transport to reach stop", value=True,
                           help="Enable to ride feeder transit (bus/tram) "
                                "instead of walking/biking the whole way.")
    feeder_operators = []
    if use_feeder:
        feeder_operators = st.multiselect(
            "Feeder operators", [op for op in OPERATORS if op not in dest_operators],
            default=[op for op in OPERATORS if op not in dest_operators],
            help="Transit you can ride to get closer to a destination stop.",
            label_visibility="collapsed",
        )
        feeder_dep_window = st.slider("Departure window", 0, 24, (7, 9), step=1,
                                      key="feeder_dep")
        feeder_transfer_dist = st.slider(
            "Transfer distance (m)", 100, 1000, 400, step=50,
            help="Max distance between stops for a walking transfer.",
        )
        feeder_max_time = st.slider(
            "Max transit time (min)", 5, 120, 60, step=5,
            help="Time budget for the BFS from destination stops through the feeder network.",
        )

    st.markdown('<hr class="sidebar-divider"/>', unsafe_allow_html=True)
    st.markdown('<p class="sidebar-section">Last mile mode</p>', unsafe_allow_html=True)
    if use_feeder:
        st.caption("How you travel from home to the nearest reachable stop.")
    transport_mode = st.radio("Mode", list(LAST_MILE_SPEEDS.keys()),
                              horizontal=True, label_visibility="collapsed")

    st.markdown('<hr class="sidebar-divider"/>', unsafe_allow_html=True)
    st.markdown('<p class="sidebar-section">Thresholds</p>', unsafe_allow_html=True)
    max_time_min = st.slider("Max total time (min)", 5, 300, 200, step=5,
                             help="Areas beyond this total time are shown as unreachable.")
    if not use_feeder:
        max_distance_km = st.slider("Max distance (km)", 1.0, 30.0, 10.0, step=0.5,
                                    help="Hard cutoff distance to nearest stop.")
    else:
        max_distance_km = 999.0
    resolution = st.select_slider("Map resolution", [100, 150, 200, 300], value=200,
                                  help="Grid cells per axis. Higher = sharper but slower.")

    st.markdown('<hr class="sidebar-divider"/>', unsafe_allow_html=True)
    st.markdown('<p class="sidebar-section">Date</p>', unsafe_allow_html=True)
    target_date = st.date_input("Reference date", value=date.today() - timedelta(days=1),
                                min_value=date(2024, 8, 21), max_value=date.today(),
                                help="Used to determine which stops are active.")

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

# ── Load stop locations (as numpy arrays, not DataFrame) ─────────────────────

all_operators = list(set(dest_operators + feeder_operators))
ts = noon_timestamp(target_date.year, target_date.month)


@st.cache_data(show_spinner=False, ttl=3600)
def _load_stop_arrays(operators, ts, token, target_date_):
    """Load GTFS feeds and extract active stop locations as numpy arrays."""
    progress = st.progress(0, text="Loading stop data...")
    n_ops = len(operators)

    all_lats = []
    all_lons = []
    all_names = []
    all_ops = []

    for i, op_name in enumerate(operators):
        slug = OPERATORS[op_name]
        progress.progress(i / n_ops, text=f"Downloading {op_name}...")

        try:
            feed = fetch_gtfs_operator(slug, ts, token)
        except Exception as e:
            st.warning(f"Could not load {op_name}: {e}")
            continue

        if feed.stops is None:
            continue

        # Find active stop IDs
        active_ids = None
        sids = get_active_service_ids(feed, [target_date_])
        if sids and feed.trips is not None:
            active_trips = set(feed.trips.loc[feed.trips["service_id"].isin(sids), "trip_id"])
            if feed.stop_times is not None and active_trips:
                active_ids = set(
                    feed.stop_times.loc[
                        feed.stop_times["trip_id"].isin(active_trips), "stop_id"
                    ].astype(str).str.strip()
                )

        stops = feed.stops
        lats = stops["stop_lat"].values.astype(float)
        lons = stops["stop_lon"].values.astype(float)
        sids_arr = stops["stop_id"].astype(str).str.strip().values
        parents = (stops["parent_station"].fillna("").astype(str).str.strip().values
                   if "parent_station" in stops.columns
                   else np.full(len(stops), "", dtype=object))
        names = stops["stop_name"].fillna("").values

        seen = set()
        for j in range(len(stops)):
            lat, lon = lats[j], lons[j]
            if np.isnan(lat) or np.isnan(lon):
                continue
            if not (49.4 <= lat <= 51.6 and 2.5 <= lon <= 6.5):
                continue
            if active_ids is not None:
                if sids_arr[j] not in active_ids and parents[j] not in active_ids:
                    continue
            key = parents[j] if parents[j] else sids_arr[j]
            dedup = f"{op_name}:{key}"
            if dedup in seen:
                continue
            seen.add(dedup)
            all_lats.append(lat)
            all_lons.append(lon)
            all_names.append(names[j])
            all_ops.append(op_name)

    progress.progress(1.0, text="Done!")
    progress.empty()

    if not all_lats:
        return None

    return {
        "lats": np.array(all_lats, dtype=np.float64),
        "lons": np.array(all_lons, dtype=np.float64),
        "names": all_names,
        "operators": all_ops,
    }


stop_data = _load_stop_arrays(tuple(all_operators), ts, token, target_date)

if stop_data is None:
    st.error("No stop data could be loaded.")
    st.stop()

# Build operator masks
op_arr = np.array(stop_data["operators"])
dest_mask = np.isin(op_arr, dest_operators)
feeder_mask = np.isin(op_arr, feeder_operators) if feeder_operators else np.zeros(len(op_arr), dtype=bool)

n_dest = dest_mask.sum()
n_feeder = feeder_mask.sum()

if n_dest == 0:
    st.error("No active stops found for the destination operator(s).")
    st.stop()

# ── Header ───────────────────────────────────────────────────────────────────

speed = LAST_MILE_SPEEDS[transport_mode]
dest_str = ", ".join(dest_operators)
feeder_str = ", ".join(feeder_operators) if feeder_operators else "none"

if use_feeder and feeder_operators:
    caption_text = (
        f"**{target_date.strftime('%a %d %b %Y')}** — "
        f"Reach **{dest_str}** stops via **{feeder_str}** — "
        f"Last mile: **{transport_mode}** ({speed} km/h) — Max {max_time_min} min"
    )
else:
    caption_text = (
        f"**{target_date.strftime('%a %d %b %Y')}** — "
        f"Reach **{dest_str}** stops — "
        f"Mode: **{transport_mode}** ({speed} km/h) — Max {max_time_min} min / {max_distance_km} km"
    )
st.caption(caption_text)

with st.expander("How is this computed?"):
    if use_feeder and feeder_operators:
        st.markdown(f"""
**Method (with feeder transit)**:
1. Multi-source BFS from all {n_dest:,} destination stops through the feeder network.
2. {resolution}x{resolution} grid over Belgium. For each cell:
   total = {transport_mode.lower()} to nearest reachable stop + transit time.
3. Uses **scipy cKDTree** for O(n log k) nearest-stop lookup.
""")
    else:
        st.markdown(f"""
**Method (direct)**:
{resolution}x{resolution} grid. For each cell, find nearest destination stop
using **scipy cKDTree** (Manhattan-approximated). Travel time = distance / {speed} km/h.
""")

# Metrics
mc = st.columns(2 + len(dest_operators) + (len(feeder_operators) if use_feeder else 0))
mc[0].metric("Destination stops", f"{n_dest:,}")
col_idx = 1
for op in dest_operators:
    n = (op_arr[dest_mask] == op).sum()
    if col_idx < len(mc):
        mc[col_idx].metric(f"{op}", f"{n:,}")
        col_idx += 1
if use_feeder and feeder_operators:
    if col_idx < len(mc):
        mc[col_idx].metric("Feeder stops", f"{n_feeder:,}")
        col_idx += 1
    for op in feeder_operators:
        n = (op_arr[feeder_mask] == op).sum()
        if col_idx < len(mc):
            mc[col_idx].metric(f"{op}", f"{n:,}")
            col_idx += 1

# ── Cached Belgium mask ──────────────────────────────────────────────────────

prov_geo = load_provinces_geojson()


@st.cache_data(show_spinner=False, ttl=86400)
def _cached_belgium_mask(res, _prov_geo_id):
    """Build and cache boolean mask of grid cells inside Belgium."""
    lat_lin = np.linspace(BE_LAT_MIN, BE_LAT_MAX, res)
    lon_lin = np.linspace(BE_LON_MIN, BE_LON_MAX, res)

    belgium = _get_belgium_border(prov_geo)
    belgium_prep = shp_prepared.prep(belgium)
    mask = np.zeros((res, res), dtype=bool)

    step = 4
    for i in range(0, res, step):
        for j in range(0, res, step):
            if belgium_prep.contains(Point(lon_lin[j], lat_lin[i])):
                mask[i:min(i + step, res), j:min(j + step, res)] = True

    for i in range(res):
        for j in range(res):
            bi, bj = i % step, j % step
            if bi == 0 or bj == 0 or bi == step - 1 or bj == step - 1:
                mask[i, j] = belgium_prep.contains(Point(lon_lin[j], lat_lin[i]))

    return mask


# ── Grid computation with cKDTree ────────────────────────────────────────────

@st.cache_data(show_spinner="Computing accessibility grid...", ttl=3600)
def _compute_grid_kdtree(stop_lats, stop_lons, stop_times, speed_kmh,
                         max_time, max_dist_km, res, _prov_geo_id):
    """Compute travel time grid using cKDTree for nearest-stop lookup.

    Uses scaled coordinates so Euclidean distance approximates Manhattan/great-circle.
    """
    s_lats = np.asarray(stop_lats, dtype=np.float64)
    s_lons = np.asarray(stop_lons, dtype=np.float64)
    s_times = np.asarray(stop_times, dtype=np.float64)

    # Scale to approximate km: lat*111, lon*71 (at ~50.5N)
    stop_coords = np.column_stack([s_lats * 111.0, s_lons * 71.0])
    tree = cKDTree(stop_coords)

    lat_lin = np.linspace(BE_LAT_MIN, BE_LAT_MAX, res)
    lon_lin = np.linspace(BE_LON_MIN, BE_LON_MAX, res)

    # Build grid coordinates (res*res, 2)
    grid_lat, grid_lon = np.meshgrid(lat_lin, lon_lin, indexing="ij")
    grid_coords = np.column_stack([
        grid_lat.ravel() * 111.0,
        grid_lon.ravel() * 71.0,
    ])

    # Query nearest stop for each grid cell — O(n_cells * log(n_stops))
    dists_km, indices = tree.query(grid_coords, k=1)

    # Total time = stop travel time + walk/bike distance
    grid_time = (s_times[indices] + dists_km / speed_kmh * 60.0).reshape(res, res)

    # Apply Belgium mask
    mask = _cached_belgium_mask(res, id(prov_geo))
    grid_time[~mask] = np.nan
    grid_time[grid_time > max_time] = np.nan
    if max_dist_km < 999:
        grid_dist = dists_km.reshape(res, res)
        grid_time[grid_dist > max_dist_km] = np.nan

    return grid_time


# ── Feeder mode: multi-source BFS + grid ─────────────────────────────────────

@st.cache_data(show_spinner=False, ttl=3600)
def _build_feeder_graph(dest_ops, feeder_ops, ts, token, target_date_,
                        dep_window, transfer_dist_km):
    combined_ops = list(set(list(dest_ops) + list(feeder_ops)))
    feeds = {}
    sids_per_op = {}

    progress = st.progress(0, text="Building feeder transit graph...")
    n_ops = len(combined_ops)

    for i, op_name in enumerate(combined_ops):
        slug = OPERATORS[op_name]
        progress.progress(i / n_ops, text=f"Loading {op_name}...")
        try:
            feed = fetch_gtfs_operator(slug, ts, token)
        except Exception as e:
            st.warning(f"Could not load {op_name}: {e}")
            continue
        if feed.stop_times is None or feed.trips is None:
            continue
        sids = get_active_service_ids(feed, [target_date_])
        if not sids:
            continue
        feeds[op_name] = feed
        sids_per_op[op_name] = sids

    if not feeds:
        progress.empty()
        return None

    progress.progress(0.6, text="Building stop lookup...")
    stop_lookup = build_multimodal_stop_lookup(feeds)
    progress.progress(0.7, text="Building timetable graph...")
    graph = build_multimodal_graph(feeds, sids_per_op, dep_window)
    progress.progress(0.8, text="Building transfer edges...")
    transfers = build_transfer_edges(stop_lookup, max_walk_km=transfer_dist_km)

    dest_stop_ids = {sid for sid, info in stop_lookup.items()
                     if info["operator"] in dest_ops}

    progress.progress(1.0, text="Done!")
    progress.empty()

    return {
        "stop_lookup": stop_lookup,
        "graph": graph,
        "transfers": transfers,
        "dest_stop_ids": dest_stop_ids,
    }


@st.cache_data(show_spinner="Running multi-source BFS...", ttl=3600)
def _run_feeder_bfs(_graph, _transfers, _stop_lookup, _dest_stop_ids,
                    max_transit_min, dep_window):
    return bfs_from_stops(
        _dest_stop_ids, _stop_lookup, _graph, _transfers,
        max_minutes=max_transit_min,
        departure_window=dep_window,
        max_transfers=3,
        transfer_penalty_min=3,
    )


# ── Compute the grid ─────────────────────────────────────────────────────────

if use_feeder and feeder_operators:
    feeder_data = _build_feeder_graph(
        tuple(dest_operators), tuple(feeder_operators),
        ts, token, target_date,
        tuple(feeder_dep_window), feeder_transfer_dist / 1000.0,
    )

    if feeder_data is None:
        st.error("Could not build feeder transit graph.")
        st.stop()

    bfs_results = _run_feeder_bfs(
        feeder_data["graph"], feeder_data["transfers"],
        feeder_data["stop_lookup"], feeder_data["dest_stop_ids"],
        feeder_max_time, tuple(feeder_dep_window),
    )

    if not bfs_results:
        st.warning("BFS found no reachable stops from destination stops.")
        st.stop()

    # Extract stop coords + times from BFS results
    sl = feeder_data["stop_lookup"]
    bfs_lats = []
    bfs_lons = []
    bfs_times = []
    for sid, info in bfs_results.items():
        if sid in sl:
            bfs_lats.append(sl[sid]["lat"])
            bfs_lons.append(sl[sid]["lon"])
            bfs_times.append(info["travel_time"])

    grid_time = _compute_grid_kdtree(
        bfs_lats, bfs_lons, bfs_times,
        speed, max_time_min, 999.0, resolution, id(prov_geo),
    )
else:
    d_lats = stop_data["lats"][dest_mask]
    d_lons = stop_data["lons"][dest_mask]
    grid_time = _compute_grid_kdtree(
        d_lats.tolist(), d_lons.tolist(),
        [0.0] * int(dest_mask.sum()),
        speed, max_time_min, max_distance_km, resolution, id(prov_geo),
    )

# ── Gradient view (single-pass RGBA) ─────────────────────────────────────────

if view_mode == "Gradient":
    valid = ~np.isnan(grid_time)
    if not valid.any():
        st.warning("No reachable area with current settings.")
        st.stop()

    effective_max = float(np.nanmax(grid_time))

    # Build RGBA in one pass — no separate r/g/b arrays
    rgba = np.zeros((resolution, resolution, 4), dtype=np.uint8)
    ratio = np.where(valid, grid_time / max(effective_max, 0.01), 0.0)
    np.clip(ratio, 0, 1, out=ratio)

    lo = valid & (ratio < 0.5)
    hi = valid & (ratio >= 0.5)
    r2_lo = ratio[lo] * 2
    r2_hi = (ratio[hi] - 0.5) * 2

    rgba[lo, 0] = np.clip(34 + 221 * r2_lo, 0, 255).astype(np.uint8)
    rgba[lo, 1] = np.clip(180 - 40 * r2_lo, 0, 255).astype(np.uint8)
    rgba[lo, 2] = np.clip(34 - 30 * r2_lo, 0, 255).astype(np.uint8)
    rgba[lo, 3] = 180

    rgba[hi, 0] = np.clip(255 - 35 * r2_hi, 0, 255).astype(np.uint8)
    rgba[hi, 1] = np.clip(140 - 120 * r2_hi, 0, 255).astype(np.uint8)
    rgba[hi, 2] = np.clip(4 + 30 * r2_hi, 0, 255).astype(np.uint8)
    rgba[hi, 3] = 180

    del ratio  # free immediately

    # Flip in-place for image orientation
    rgba = rgba[::-1]

    from PIL import Image
    img = Image.fromarray(rgba, "RGBA")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    del rgba, img
    buf.seek(0)
    img_b64 = base64.b64encode(buf.read()).decode()
    del buf

    m = folium.Map(location=[50.5, 4.35], zoom_start=8, tiles="cartodbpositron")
    folium.raster_layers.ImageOverlay(
        image=f"data:image/png;base64,{img_b64}",
        bounds=[[BE_LAT_MIN, BE_LON_MIN], [BE_LAT_MAX, BE_LON_MAX]],
        opacity=0.75,
        interactive=False,
    ).add_to(m)

    caption = (f"Time to nearest {dest_str} stop via {feeder_str} (min)"
               if use_feeder and feeder_operators
               else f"Time to nearest {dest_str} stop by {transport_mode} (min)")

    cmap = cm.LinearColormap(
        colors=["#22b422", "#ffcc00", "#dd2020"],
        vmin=0, vmax=round(effective_max, 1),
        caption=caption,
    )
    cmap.add_to(m)
    _add_legend_css(m)
    st_folium(m, width="stretch", height=700, key="access_gradient")

    # Summary stats
    st.subheader("Coverage statistics")
    valid_times = grid_time[~np.isnan(grid_time)]

    thresholds = [5, 10, 15, 20, 30]
    total_cells = valid.sum()
    cols = st.columns(len(thresholds))
    for col, t in zip(cols, thresholds):
        pct = (valid_times <= t).sum() / total_cells * 100 if total_cells > 0 else 0
        col.metric(f"<= {t} min", f"{pct:.0f}%")

    st.caption(
        f"Median: **{np.median(valid_times):.1f} min** | "
        f"Mean: **{np.mean(valid_times):.1f} min** | "
        f"95th pct: **{np.percentile(valid_times, 95):.1f} min**"
    )

# ── Station view ─────────────────────────────────────────────────────────────

elif view_mode == "Stations":
    m = folium.Map(location=[50.5, 4.35], zoom_start=8, tiles="cartodbpositron")

    for op in dest_operators:
        op_mask = dest_mask & (op_arr == op)
        color = OPERATOR_COLORS.get(op, "#333")
        layer = folium.FeatureGroup(name=f"{op} (destination)")
        idxs = np.where(op_mask)[0]
        for j in idxs:
            folium.CircleMarker(
                location=[stop_data["lats"][j], stop_data["lons"][j]],
                radius=4, color=color, fill=True, fill_color=color,
                fill_opacity=0.7, weight=1,
                tooltip=f"<b>{stop_data['names'][j]}</b> ({op})",
            ).add_to(layer)
        layer.add_to(m)

    if use_feeder:
        for op in feeder_operators:
            op_mask = feeder_mask & (op_arr == op)
            color = OPERATOR_COLORS.get(op, "#999")
            layer = folium.FeatureGroup(name=f"{op} (feeder)")
            idxs = np.where(op_mask)[0]
            for j in idxs:
                folium.CircleMarker(
                    location=[stop_data["lats"][j], stop_data["lons"][j]],
                    radius=2, color=color, fill=True, fill_color=color,
                    fill_opacity=0.4, weight=0.5,
                    tooltip=f"<b>{stop_data['names'][j]}</b> ({op})",
                ).add_to(layer)
            layer.add_to(m)

    folium.LayerControl().add_to(m)
    st_folium(m, width="stretch", height=700, key="access_stations")

    st.subheader("Stops per operator")
    import pandas as pd
    rows = []
    for op in dest_operators:
        rows.append({"Operator": op, "Role": "Destination",
                     "Active stops": int((op_arr[dest_mask] == op).sum())})
    for op in feeder_operators:
        rows.append({"Operator": op, "Role": "Feeder",
                     "Active stops": int((op_arr[feeder_mask] == op).sum())})
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

render_footer()
