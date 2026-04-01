"""Map rendering functions for Folium maps."""

import numpy as np
import folium
import branca.colormap as cm
from branca.element import MacroElement, Template

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
            color = _ratio_to_color(ratio)
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


def _ratio_to_color(ratio: float) -> str:
    """Map a 0-1 ratio to a vivid blue gradient."""
    r = int(107 + (4 - 107) * ratio)
    g = int(174 + (47 - 174) * ratio)
    b = int(214 + (107 - 214) * ratio)
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
