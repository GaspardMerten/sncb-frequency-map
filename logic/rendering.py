"""Map rendering functions for Folium maps."""

import io
import base64
import json

import numpy as np
import folium
import branca.colormap as cm
from branca.element import MacroElement, Template
from shapely.geometry import MultiPoint, shape, mapping, Point
from shapely.ops import voronoi_diagram, unary_union

# Stronger, more visible blue palette
PALETTE = ["#c6dbef", "#6baed6", "#3182bd", "#2171b5", "#08519c", "#042f6b"]


def make_step_colormap(values: list[float], caption: str) -> cm.StepColormap:
    """Build a quantile-based StepColormap for the given values."""
    arr = np.array(values)
    n_bins = len(PALETTE)
    edges = np.unique(np.round(np.quantile(arr, np.linspace(0, 1, n_bins + 1)), 1))
    if len(edges) < 3:
        edges = np.round(np.linspace(arr.min(), arr.max(), n_bins + 1), 1)
    n_intervals = len(edges) - 1
    colors = list(PALETTE[:n_intervals])
    while len(colors) < n_intervals:
        colors.append(PALETTE[-1])
    cmap = cm.StepColormap(
        colors=colors, index=list(edges[:-1]),
        vmin=float(edges[0]), vmax=float(edges[-1]), caption=caption,
    )
    return cmap


def _add_legend_css(m):
    """Add CSS to make the branca colormap legend more readable."""
    css = MacroElement()
    css._template = Template("""
    {% macro header(this, kwargs) %}
    <style>
        .legend.leaflet-control {
            background: rgba(255,255,255,0.92) !important;
            padding: 8px 14px !important;
            border-radius: 6px !important;
            box-shadow: 0 2px 8px rgba(0,0,0,0.2) !important;
            font-size: 13px !important;
            line-height: 1.6 !important;
        }
        .legend.leaflet-control .caption {
            font-weight: 700 !important;
            font-size: 13px !important;
            margin-bottom: 4px !important;
            color: #333 !important;
        }
        .legend.leaflet-control svg {
            height: 20px !important;
        }
        .legend.leaflet-control .tick text {
            font-size: 11px !important;
            font-weight: 500 !important;
        }
        div.legend {
            font-size: 13px !important;
        }
    </style>
    {% endmacro %}
    """)
    m.get_root().add_child(css)


def render_segment_map(segments, colormap, min_f, max_f,
                       station_freqs=None, stop_lookup=None, gtfs_to_infra=None):
    """Render the segment frequency map with optional station circles.

    Stations are drawn UNDER segments so short segments remain visible.
    """
    m = folium.Map(location=[50.5, 4.35], zoom_start=8, tiles="cartodbpositron")
    spread = max(max_f - min_f, 1)

    # Draw station circles FIRST (bottom layer)
    if station_freqs and stop_lookup:
        station_layer = folium.FeatureGroup(name="Stations")
        max_sf = max(station_freqs.values()) if station_freqs else 1
        min_sf = min(station_freqs.values()) if station_freqs else 0
        sf_spread = max(max_sf - min_sf, 1)

        drawn = set()
        for station_id, freq in station_freqs.items():
            if station_id in drawn:
                continue
            info = stop_lookup.get(station_id)
            if not info:
                continue
            drawn.add(station_id)
            ratio = (freq - min_sf) / sf_spread
            radius = 3 + 6 * ratio
            color = ratio_to_blue(ratio)
            folium.CircleMarker(
                location=[info["lat"], info["lon"]],
                radius=radius, color=color, fill=True, fill_color=color,
                fill_opacity=0.7, weight=1,
                tooltip=f"{info['name']}: {freq:.0f} trains/day",
            ).add_to(station_layer)
        station_layer.add_to(m)

    # Draw segments ON TOP
    segment_layer = folium.FeatureGroup(name="Segments")
    for seg in segments:
        f = seg["frequency"]
        folium.PolyLine(
            locations=seg["coords"],
            color=colormap(f),
            weight=max(2, min(10, 2 + 8 * (f - min_f) / spread)),
            opacity=0.9,
            tooltip=f"{seg['stop_a']} ↔ {seg['stop_b']}: {f:.1f} trains/day",
        ).add_to(segment_layer)
    segment_layer.add_to(m)

    colormap.add_to(m)
    _add_legend_css(m)
    return m


def ratio_to_blue(ratio: float) -> str:
    """Map a 0-1 ratio to a vivid blue gradient (light -> dark)."""
    r = int(107 + (4 - 107) * ratio)
    g = int(174 + (47 - 174) * ratio)
    b = int(214 + (107 - 214) * ratio)
    return f"#{r:02x}{g:02x}{b:02x}"


def duration_color(minutes: float, max_minutes: float) -> str:
    """Map travel time to a green -> yellow -> red gradient."""
    ratio = min(minutes / max(max_minutes, 1), 1.0)
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


def render_choropleth(geo_features, totals, colormap, segments, name_key, tooltip_fn):
    """Render a choropleth map with rail segments overlaid."""
    m = folium.Map(location=[50.5, 4.35], zoom_start=8, tiles="cartodbpositron")
    for feat in geo_features:
        name = feat["properties"][name_key]
        total = totals.get(name, 0)
        if total == 0:
            continue
        fc = colormap(total)
        folium.GeoJson(
            feat,
            style_function=lambda _, fc=fc: {
                "fillColor": fc, "color": "#333",
                "weight": 1.5, "fillOpacity": 0.65,
            },
            tooltip=tooltip_fn(name, total),
        ).add_to(m)

    for seg in segments:
        folium.PolyLine(
            locations=seg["coords"], color="#2a2a4a",
            weight=1, opacity=0.25,
        ).add_to(m)

    colormap.add_to(m)
    _add_legend_css(m)
    return m


def render_reach_choropleth(geo_features, totals, colormap, name_key, tooltip_fn):
    """Render a choropleth map for reachability data (no segment overlay)."""
    m = folium.Map(location=[50.5, 4.35], zoom_start=8, tiles="cartodbpositron")
    for feat in geo_features:
        name = feat["properties"][name_key]
        total = totals.get(name, 0)
        if total == 0:
            continue
        fc = colormap(total)
        folium.GeoJson(
            feat,
            style_function=lambda _, fc=fc: {
                "fillColor": fc, "color": "#333",
                "weight": 1.5, "fillOpacity": 0.65,
            },
            tooltip=tooltip_fn(name, total),
        ).add_to(m)
    colormap.add_to(m)
    _add_legend_css(m)
    return m


# ---------------------------------------------------------------------------
# Voronoi map
# ---------------------------------------------------------------------------

def render_voronoi_map(df, value_col, color_fn, tooltip_fn, prov_geo):
    """Render a Voronoi tessellation colored by a per-station value.

    Parameters
    ----------
    df : DataFrame with columns lat, lon, station_name, and *value_col*.
    value_col : column name for the numeric value to color by.
    color_fn : callable(value, vmin, vmax) -> hex color string.
    tooltip_fn : callable(row_dict) -> tooltip string.
    prov_geo : provinces GeoJSON dict used to clip cells to Belgium border.
    """
    df_ok = df[df[value_col].notna()].copy()
    if df_ok.empty:
        return folium.Map(location=[50.5, 4.35], zoom_start=8, tiles="cartodbpositron")

    # Build Belgium border as a union of province polygons
    province_shapes = [shape(f["geometry"]) for f in prov_geo["features"]]
    belgium = unary_union(province_shapes).buffer(0)

    # Voronoi from station points (lon, lat order for Shapely)
    points = MultiPoint([(row["lon"], row["lat"]) for _, row in df_ok.iterrows()])
    vd = voronoi_diagram(points, envelope=belgium.envelope.buffer(0.5))

    # Map each Voronoi cell to the station it belongs to (nearest point)
    station_coords = list(zip(df_ok["lon"].values, df_ok["lat"].values))
    station_values = df_ok[value_col].values
    rows_list = df_ok.to_dict("records")

    vmin = float(df_ok[value_col].min())
    vmax = float(df_ok[value_col].max())

    m = folium.Map(location=[50.5, 4.35], zoom_start=8, tiles="cartodbpositron")

    for cell in vd.geoms:
        centroid = cell.centroid
        best_idx, best_dist = 0, float("inf")
        for i, (sx, sy) in enumerate(station_coords):
            d = (centroid.x - sx) ** 2 + (centroid.y - sy) ** 2
            if d < best_dist:
                best_dist, best_idx = d, i

        val = float(station_values[best_idx])
        color = color_fn(val, vmin, vmax)
        tip = tooltip_fn(rows_list[best_idx])

        clipped = cell.intersection(belgium)
        if clipped.is_empty:
            continue

        geojson = mapping(clipped)
        folium.GeoJson(
            {"type": "Feature", "geometry": geojson, "properties": {}},
            style_function=lambda _, c=color: {
                "fillColor": c, "color": "#666",
                "weight": 0.5, "fillOpacity": 0.7,
            },
            tooltip=tip,
        ).add_to(m)

    return m


# ---------------------------------------------------------------------------
# Gradient (continuous heatmap) for Travel Duration
# ---------------------------------------------------------------------------

# Transport mode speeds in km/h
TRANSPORT_SPEEDS = {"Walk": 5, "Bike": 15, "Car": 50}


def render_gradient_map(df, max_time, transport_mode, prov_geo, resolution=200, mile_kind="last"):
    """Render a continuous heatmap of total travel time across Belgium.

    For each grid cell: total_time = station_travel_time + first/last_mile_time,
    where first/last_mile_time uses Manhattan distance to the nearest station
    at the given transport mode speed.
    """
    from .geo import BE_LAT_MIN, BE_LAT_MAX, BE_LON_MIN, BE_LON_MAX

    df_ok = df[df["travel_time"].notna()].copy()
    if df_ok.empty:
        return folium.Map(location=[50.5, 4.35], zoom_start=8, tiles="cartodbpositron")

    speed_kmh = TRANSPORT_SPEEDS.get(transport_mode, 5)

    s_lats = df_ok["lat"].values.astype(np.float64)
    s_lons = df_ok["lon"].values.astype(np.float64)
    s_times = df_ok["travel_time"].values.astype(np.float64)

    lat_lin = np.linspace(BE_LAT_MIN, BE_LAT_MAX, resolution)
    lon_lin = np.linspace(BE_LON_MIN, BE_LON_MAX, resolution)

    # Fully vectorized grid computation
    # grid_lat shape: (resolution, 1), grid_lon shape: (1, resolution)
    grid_lat = lat_lin[:, None]  # (R, 1)
    grid_lon = lon_lin[None, :]  # (1, R)

    # Process in chunks to avoid huge memory (resolution² × n_stations)
    chunk = 20
    grid_time = np.full((resolution, resolution), np.inf)
    for s_start in range(0, len(s_lats), chunk):
        s_end = min(s_start + chunk, len(s_lats))
        # shapes: dlat (R, 1, chunk), dlon (1, R, chunk)
        dlat = np.abs(grid_lat[:, :, None] - s_lats[None, None, s_start:s_end]) * 111.0
        dlon = np.abs(grid_lon[:, :, None] - s_lons[None, None, s_start:s_end]) * 71.0
        total = s_times[None, None, s_start:s_end] + (dlat + dlon) / speed_kmh * 60.0
        np.minimum(grid_time, total.min(axis=2), out=grid_time)

    # Vectorized Belgium border mask using rasterization
    province_shapes = [shape(f["geometry"]) for f in prov_geo["features"]]
    belgium = unary_union(province_shapes).buffer(0)

    # Sample border at coarse grid, then refine only border cells
    mask = np.zeros((resolution, resolution), dtype=bool)
    from shapely import prepared as shp_prepared
    belgium_prep = shp_prepared.prep(belgium)

    # Coarse pass: check every 4th cell
    step = 4
    for i in range(0, resolution, step):
        for j in range(0, resolution, step):
            inside = belgium_prep.contains(Point(lon_lin[j], lat_lin[i]))
            # Fill the step×step block
            i_end = min(i + step, resolution)
            j_end = min(j + step, resolution)
            if inside:
                mask[i:i_end, j:j_end] = True

    # Refine: re-check cells near block boundaries (where mask changes)
    for i in range(resolution):
        for j in range(resolution):
            # Only re-check cells at block edges
            bi, bj = i % step, j % step
            if bi == 0 or bj == 0 or bi == step - 1 or bj == step - 1:
                mask[i, j] = belgium_prep.contains(Point(lon_lin[j], lat_lin[i]))

    grid_time[~mask] = np.nan

    effective_max = min(float(np.nanmax(grid_time)), max_time) if not np.all(np.isnan(grid_time)) else max_time
    grid_display = np.clip(grid_time, 0, effective_max)

    # Vectorized RGBA computation (no per-pixel string parsing)
    ratio = grid_display / effective_max if effective_max > 0 else np.zeros_like(grid_display)
    ratio = np.clip(ratio, 0, 1)

    r = np.zeros((resolution, resolution), dtype=np.uint8)
    g = np.zeros((resolution, resolution), dtype=np.uint8)
    b = np.zeros((resolution, resolution), dtype=np.uint8)

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

    valid = mask & ~np.isnan(grid_display)
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

    cmap = cm.LinearColormap(
        colors=["#22b422", "#ffcc00", "#dd2020"],
        vmin=0, vmax=effective_max,
        caption=f"Total travel time (min) — {mile_kind} mile by {transport_mode}",
    )
    cmap.add_to(m)
    _add_legend_css(m)
    return m
