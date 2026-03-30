"""Map rendering functions for Folium maps."""

import numpy as np
import folium
import branca.colormap as cm

PALETTE = ["#e8f0fe", "#b8d4f0", "#7baed6", "#4a90c4", "#2171b5", "#084594"]


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
    return cm.StepColormap(
        colors=colors, index=list(edges[:-1]),
        vmin=float(edges[0]), vmax=float(edges[-1]), caption=caption,
    )


def render_segment_map(segments, colormap, min_f, max_f,
                       station_freqs=None, stop_lookup=None, gtfs_to_infra=None):
    """Render the segment frequency map with optional station circles.

    Args:
        segments: List of segment dicts with coords and frequency.
        colormap: Colormap for segment coloring.
        min_f, max_f: Frequency range for line thickness scaling.
        station_freqs: Optional dict of station_id -> frequency for circles.
        stop_lookup: Optional GTFS stop lookup for station positions.
        gtfs_to_infra: Optional GTFS-to-Infrabel mapping.
    """
    m = folium.Map(location=[50.5, 4.35], zoom_start=8, tiles="cartodbpositron")
    spread = max(max_f - min_f, 1)

    # Draw segments
    for seg in segments:
        f = seg["frequency"]
        folium.PolyLine(
            locations=seg["coords"],
            color=colormap(f),
            weight=max(2, min(10, 2 + 8 * (f - min_f) / spread)),
            opacity=0.85,
            tooltip=f"{seg['stop_a']} ↔ {seg['stop_b']}: {f:.1f} trains/day",
        ).add_to(m)

    # Draw station circles
    if station_freqs and stop_lookup:
        max_station_freq = max(station_freqs.values()) if station_freqs else 1
        min_station_freq = min(station_freqs.values()) if station_freqs else 0
        freq_spread = max(max_station_freq - min_station_freq, 1)

        # Build reverse mapping: infra_id -> gtfs_ids
        infra_to_gtfs = {}
        if gtfs_to_infra:
            for gtfs_id, infra_id in gtfs_to_infra.items():
                infra_to_gtfs.setdefault(infra_id, []).append(gtfs_id)

        drawn_stations = set()
        for station_id, freq in station_freqs.items():
            if station_id in drawn_stations:
                continue
            info = stop_lookup.get(station_id)
            if not info:
                continue

            drawn_stations.add(station_id)
            # Scale radius: 3-12px based on frequency
            ratio = (freq - min_station_freq) / freq_spread
            radius = 3 + 9 * ratio

            # Color: light blue to dark blue
            color = _freq_to_color(ratio)

            folium.CircleMarker(
                location=[info["lat"], info["lon"]],
                radius=radius,
                color=color,
                fill=True,
                fill_color=color,
                fill_opacity=0.8,
                weight=1.5,
                tooltip=f"{info['name']}: {freq:.0f} trains/day",
            ).add_to(m)

    colormap.add_to(m)
    return m


def _freq_to_color(ratio: float) -> str:
    """Map a 0-1 ratio to a blue color gradient."""
    # Interpolate from light (#b8d4f0) to dark (#084594)
    r = int(184 + (8 - 184) * ratio)
    g = int(212 + (69 - 212) * ratio)
    b = int(240 + (148 - 240) * ratio)
    return f"#{r:02x}{g:02x}{b:02x}"


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
                "fillColor": fc, "color": "#666",
                "weight": 1.5, "fillOpacity": 0.55,
            },
            tooltip=tooltip_fn(name, total),
        ).add_to(m)

    # Overlay rail segments as thin lines
    for seg in segments:
        folium.PolyLine(
            locations=seg["coords"], color="#3a3a5c",
            weight=1, opacity=0.2,
        ).add_to(m)

    colormap.add_to(m)
    return m
