"""Stop Accessibility page.

Gradient map showing how long it takes from any point in Belgium to reach
the nearest transit stop, for selected operators and transport modes.

Two operator roles:
- **Destination operators**: the stops you want to reach (e.g. SNCB stations).
- **Feeder operators**: transit you can ride to get closer (e.g. De Lijn, TEC buses).
  When enabled, a multi-source BFS propagates from all destination stops through
  the feeder network, giving travel time at every feeder stop.  The grid then
  becomes: walk/bike to nearest feeder stop + transit time to destination.
"""

import os
import io
import base64
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import folium
import streamlit as st
from streamlit_folium import st_folium
import branca.colormap as cm
from shapely.geometry import Point
from shapely import prepared as shp_prepared
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

# ── Load stop locations ──────────────────────────────────────────────────────

all_operators = list(set(dest_operators + feeder_operators))
ts = noon_timestamp(target_date.year, target_date.month)


@st.cache_data(show_spinner=False, ttl=3600)
def _load_stop_locations(operators, ts, token, target_date_):
    """Load GTFS feeds and extract active stop locations."""
    feeds = {}
    progress = st.progress(0, text="Loading stop data...")
    n_ops = len(operators)

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

        sids = get_active_service_ids(feed, [target_date_])
        if sids and feed.trips is not None:
            active_trips = set(feed.trips.loc[feed.trips["service_id"].isin(sids), "trip_id"])
            if feed.stop_times is not None and active_trips:
                active_stop_ids = set(
                    feed.stop_times.loc[
                        feed.stop_times["trip_id"].isin(active_trips), "stop_id"
                    ].astype(str).str.strip()
                )
                feed._active_stop_ids = active_stop_ids
            else:
                feed._active_stop_ids = None
        else:
            feed._active_stop_ids = None

        feeds[op_name] = feed

    if not feeds:
        progress.empty()
        return None

    progress.progress(0.9, text="Building stop index...")

    all_stops = []
    for operator, feed in feeds.items():
        stops = feed.stops
        lats = stops["stop_lat"].values.astype(float)
        lons = stops["stop_lon"].values.astype(float)
        sids_arr = stops["stop_id"].astype(str).str.strip().values
        if "parent_station" in stops.columns:
            parents = stops["parent_station"].fillna("").astype(str).str.strip().values
        else:
            parents = np.full(len(stops), "", dtype=object)
        names = stops["stop_name"].fillna("").values

        active_ids = getattr(feed, "_active_stop_ids", None)
        seen = set()

        for j in range(len(stops)):
            lat, lon = lats[j], lons[j]
            if np.isnan(lat) or np.isnan(lon):
                continue
            if not (49.4 <= lat <= 51.6 and 2.5 <= lon <= 6.5):
                continue
            if active_ids is not None:
                sid = sids_arr[j]
                parent = parents[j]
                if sid not in active_ids and parent not in active_ids:
                    continue

            key = parents[j] if parents[j] else sids_arr[j]
            dedup_key = f"{operator}:{key}"
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            all_stops.append({
                "operator": operator,
                "name": names[j],
                "lat": float(lat),
                "lon": float(lon),
            })

    progress.progress(1.0, text="Done!")
    progress.empty()
    return pd.DataFrame(all_stops)


stops_df = _load_stop_locations(
    tuple(all_operators), ts, token, target_date,
)

if stops_df is None or stops_df.empty:
    st.error("No stop data could be loaded.")
    st.stop()

dest_stops = stops_df[stops_df["operator"].isin(dest_operators)]
feeder_stops = stops_df[stops_df["operator"].isin(feeder_operators)] if feeder_operators else pd.DataFrame()

if dest_stops.empty:
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
**Goal**: Show how long it takes from any point in Belgium to reach the
nearest **{dest_str}** stop, using **{feeder_str}** feeder transit.

**Method (with feeder transit)**:
1. A single **multi-source BFS** starts from all {len(dest_stops):,} destination stops
   simultaneously (travel time = 0 at each).
2. It propagates outward through the combined feeder + destination timetable,
   recording the minimum travel time to reach every stop in the network.
3. This gives a travel time at every reachable transit stop (feeder or destination).
4. A {resolution}x{resolution} grid is placed over Belgium. For each cell:
   total time = **{transport_mode.lower()} to nearest reachable stop** + **that stop's transit time**.
5. Full resolution, no sampling — the BFS runs once, the grid is vectorized.

**Settings**:
- Departure window: {feeder_dep_window[0]}h–{feeder_dep_window[1]}h
- Transfer distance: {feeder_transfer_dist}m
- Transit time budget: {feeder_max_time} min
- Currently: **{len(dest_stops):,}** destination stops, **{len(feeder_stops):,}** feeder stops.
""")
    else:
        st.markdown(f"""
**Goal**: Show how long it takes from any point in Belgium to reach the
nearest **{dest_str}** stop by {transport_mode.lower()}.

**Method (direct)**:
A {resolution}x{resolution} grid is placed over Belgium.
For each cell, the Manhattan distance to every destination stop is computed:
`d = |lat_diff| x 111 + |lon_diff| x 71` km.
Travel time = `d / {speed} x 60` minutes ({transport_mode} at {speed} km/h).
The minimum across all stops is kept.

**Filters**:
- Only stops with active services on {target_date} are included.
- Cells beyond **{max_time_min} min** or **{max_distance_km} km** from any stop are masked.
- Currently showing **{len(dest_stops):,}** active destination stops.
""")

# Metrics
mc = st.columns(2 + len(dest_operators) + (len(feeder_operators) if use_feeder else 0))
mc[0].metric("Destination stops", f"{len(dest_stops):,}")
col_idx = 1
for op in dest_operators:
    n = (dest_stops["operator"] == op).sum()
    if col_idx < len(mc):
        mc[col_idx].metric(f"{op}", f"{n:,}")
        col_idx += 1
if use_feeder and feeder_operators:
    if col_idx < len(mc):
        mc[col_idx].metric("Feeder stops", f"{len(feeder_stops):,}")
        col_idx += 1
    for op in feeder_operators:
        n = (feeder_stops["operator"] == op).sum() if not feeder_stops.empty else 0
        if col_idx < len(mc):
            mc[col_idx].metric(f"{op}", f"{n:,}")
            col_idx += 1

# ── Compute grid ─────────────────────────────────────────────────────────────

prov_geo = load_provinces_geojson()


def _build_belgium_mask(res):
    """Build boolean mask of grid cells inside Belgium."""
    lat_lin = np.linspace(BE_LAT_MIN, BE_LAT_MAX, res)
    lon_lin = np.linspace(BE_LON_MIN, BE_LON_MAX, res)

    belgium = _get_belgium_border(prov_geo)
    belgium_prep = shp_prepared.prep(belgium)
    mask = np.zeros((res, res), dtype=bool)

    step = 4
    for i in range(0, res, step):
        for j in range(0, res, step):
            inside = belgium_prep.contains(Point(lon_lin[j], lat_lin[i]))
            i_end = min(i + step, res)
            j_end = min(j + step, res)
            if inside:
                mask[i:i_end, j:j_end] = True

    for i in range(res):
        for j in range(res):
            bi, bj = i % step, j % step
            if bi == 0 or bj == 0 or bi == step - 1 or bj == step - 1:
                mask[i, j] = belgium_prep.contains(Point(lon_lin[j], lat_lin[i]))

    return mask, lat_lin, lon_lin


def _vectorized_grid(stop_lats, stop_lons, stop_times, speed_kmh,
                     max_time, max_dist_km, res):
    """Vectorized grid: for each cell, walk/bike to nearest stop + stop_time."""
    s_lats = np.array(stop_lats, dtype=np.float64)
    s_lons = np.array(stop_lons, dtype=np.float64)
    s_times = np.array(stop_times, dtype=np.float64)

    lat_lin = np.linspace(BE_LAT_MIN, BE_LAT_MAX, res)
    lon_lin = np.linspace(BE_LON_MIN, BE_LON_MAX, res)

    grid_lat = lat_lin[:, None]
    grid_lon = lon_lin[None, :]

    grid_time = np.full((res, res), np.inf)
    grid_dist = np.full((res, res), np.inf)
    chunk = 50
    for s_start in range(0, len(s_lats), chunk):
        s_end = min(s_start + chunk, len(s_lats))
        dlat = np.abs(grid_lat[:, :, None] - s_lats[None, None, s_start:s_end]) * 111.0
        dlon = np.abs(grid_lon[:, :, None] - s_lons[None, None, s_start:s_end]) * 71.0
        dist = dlat + dlon
        total = s_times[None, None, s_start:s_end] + dist / speed_kmh * 60.0

        chunk_best = total.argmin(axis=2)
        chunk_min_time = np.take_along_axis(total, chunk_best[:, :, None], axis=2).squeeze(axis=2)
        chunk_min_dist = np.take_along_axis(dist, chunk_best[:, :, None], axis=2).squeeze(axis=2)

        improved = chunk_min_time < grid_time
        grid_time[improved] = chunk_min_time[improved]
        grid_dist[improved] = chunk_min_dist[improved]

    mask, _, _ = _build_belgium_mask(res)
    grid_time[~mask] = np.nan
    grid_time[grid_time > max_time] = np.nan
    if max_dist_km < 999:
        grid_time[grid_dist > max_dist_km] = np.nan

    return grid_time


# ── Direct mode (walk/bike to destination stops, all have time=0) ────────────

@st.cache_data(show_spinner="Computing accessibility grid...", ttl=3600)
def _compute_direct_grid(stop_lats, stop_lons, speed_kmh, max_time, max_dist_km,
                         res, _prov_geo_id):
    stop_times = [0.0] * len(stop_lats)
    return _vectorized_grid(stop_lats, stop_lons, stop_times,
                            speed_kmh, max_time, max_dist_km, res)


# ── Feeder mode: multi-source BFS + vectorized grid ─────────────────────────

@st.cache_data(show_spinner=False, ttl=3600)
def _build_feeder_graph(dest_ops, feeder_ops, ts, token, target_date_,
                        dep_window, transfer_dist_km):
    """Build combined timetable graph and run multi-source BFS from dest stops."""
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

    # Identify destination stop IDs
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


@st.cache_data(show_spinner="Running multi-source BFS from destination stops...", ttl=3600)
def _run_feeder_bfs(_graph, _transfers, _stop_lookup, _dest_stop_ids,
                    max_transit_min, dep_window):
    """Single multi-source BFS from all destination stops outward."""
    return bfs_from_stops(
        _dest_stop_ids, _stop_lookup, _graph, _transfers,
        max_minutes=max_transit_min,
        departure_window=dep_window,
        max_transfers=3,
        transfer_penalty_min=3,
    )


@st.cache_data(show_spinner="Computing feeder accessibility grid...", ttl=3600)
def _compute_feeder_grid(bfs_results, _stop_lookup, speed_kmh,
                         max_time, res, _prov_geo_id):
    """Build full-resolution grid from BFS stop-level results."""
    stop_lats = []
    stop_lons = []
    stop_times = []
    for sid, info in bfs_results.items():
        if sid in _stop_lookup:
            stop_lats.append(_stop_lookup[sid]["lat"])
            stop_lons.append(_stop_lookup[sid]["lon"])
            stop_times.append(info["travel_time"])

    if not stop_lats:
        return np.full((res, res), np.nan)

    return _vectorized_grid(stop_lats, stop_lons, stop_times,
                            speed_kmh, max_time, 999.0, res)


# ── Compute the appropriate grid ─────────────────────────────────────────────

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

    grid_time = _compute_feeder_grid(
        bfs_results, feeder_data["stop_lookup"], speed,
        max_time_min, resolution, id(prov_geo),
    )
else:
    grid_time = _compute_direct_grid(
        dest_stops["lat"].tolist(), dest_stops["lon"].tolist(),
        speed, max_time_min, max_distance_km, resolution,
        id(prov_geo),
    )

# ── Gradient view ────────────────────────────────────────────────────────────

if view_mode == "Gradient":
    valid = ~np.isnan(grid_time)
    if not valid.any():
        st.warning("No reachable area with current settings.")
        st.stop()

    effective_max = float(np.nanmax(grid_time))

    # Build RGBA image
    ratio = np.where(valid, grid_time / max(effective_max, 0.01), 0.0)
    ratio = np.clip(ratio, 0, 1)

    r = np.zeros_like(ratio, dtype=np.uint8)
    g = np.zeros_like(ratio, dtype=np.uint8)
    b = np.zeros_like(ratio, dtype=np.uint8)

    lo = ratio < 0.5
    hi = ~lo
    r2_lo = ratio * 2
    r2_hi = (ratio - 0.5) * 2

    r[lo] = np.clip(34 + (255 - 34) * r2_lo[lo], 0, 255).astype(np.uint8)
    g[lo] = np.clip(180 - 40 * r2_lo[lo], 0, 255).astype(np.uint8)
    b[lo] = np.clip(34 - 30 * r2_lo[lo], 0, 255).astype(np.uint8)

    r[hi] = np.clip(255 - 35 * r2_hi[hi], 0, 255).astype(np.uint8)
    g[hi] = np.clip(140 - 120 * r2_hi[hi], 0, 255).astype(np.uint8)
    b[hi] = np.clip(4 + 30 * r2_hi[hi], 0, 255).astype(np.uint8)

    rgba = np.zeros((resolution, resolution, 4), dtype=np.uint8)
    rgba[valid, 0] = r[valid]
    rgba[valid, 1] = g[valid]
    rgba[valid, 2] = b[valid]
    rgba[valid, 3] = 180

    rgba_flipped = np.flipud(rgba)

    from PIL import Image
    img = Image.fromarray(rgba_flipped, "RGBA")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    img_b64 = base64.b64encode(buf.read()).decode()

    m = folium.Map(location=[50.5, 4.35], zoom_start=8, tiles="cartodbpositron")
    folium.raster_layers.ImageOverlay(
        image=f"data:image/png;base64,{img_b64}",
        bounds=[[BE_LAT_MIN, BE_LON_MIN], [BE_LAT_MAX, BE_LON_MAX]],
        opacity=0.75,
        interactive=False,
    ).add_to(m)

    if use_feeder and feeder_operators:
        caption = f"Time to nearest {dest_str} stop via {feeder_str} (min)"
    else:
        caption = f"Time to nearest {dest_str} stop by {transport_mode} (min)"

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
        f"Median time: **{np.median(valid_times):.1f} min** | "
        f"Mean: **{np.mean(valid_times):.1f} min** | "
        f"95th pct: **{np.percentile(valid_times, 95):.1f} min**"
    )

# ── Station view ─────────────────────────────────────────────────────────────

elif view_mode == "Stations":
    m = folium.Map(location=[50.5, 4.35], zoom_start=8, tiles="cartodbpositron")

    # Draw destination stops (larger, on top)
    for op in dest_operators:
        op_stops = dest_stops[dest_stops["operator"] == op]
        color = OPERATOR_COLORS.get(op, "#333")
        layer = folium.FeatureGroup(name=f"{op} (destination)")
        for _, row in op_stops.iterrows():
            folium.CircleMarker(
                location=[row["lat"], row["lon"]],
                radius=4,
                color=color, fill=True, fill_color=color,
                fill_opacity=0.7, weight=1,
                tooltip=f"<b>{row['name']}</b> ({op}) — destination",
            ).add_to(layer)
        layer.add_to(m)

    # Draw feeder stops (smaller, below)
    if use_feeder and not feeder_stops.empty:
        for op in feeder_operators:
            op_stops = feeder_stops[feeder_stops["operator"] == op]
            color = OPERATOR_COLORS.get(op, "#999")
            layer = folium.FeatureGroup(name=f"{op} (feeder)")
            for _, row in op_stops.iterrows():
                folium.CircleMarker(
                    location=[row["lat"], row["lon"]],
                    radius=2,
                    color=color, fill=True, fill_color=color,
                    fill_opacity=0.4, weight=0.5,
                    tooltip=f"<b>{row['name']}</b> ({op}) — feeder",
                ).add_to(layer)
            layer.add_to(m)

    folium.LayerControl().add_to(m)
    st_folium(m, width="stretch", height=700, key="access_stations")

    # Operator breakdown
    st.subheader("Stops per operator")
    rows = []
    for op in dest_operators:
        rows.append({"Operator": op, "Role": "Destination",
                     "Active stops": int((dest_stops["operator"] == op).sum())})
    for op in feeder_operators:
        rows.append({"Operator": op, "Role": "Feeder",
                     "Active stops": int((feeder_stops["operator"] == op).sum()) if not feeder_stops.empty else 0})
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

render_footer()
