"""Segment Frequency Analysis page.

Visualizes train frequencies per rail segment, province, and region.
"""

import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from logic.shared import CUSTOM_CSS, render_sidebar_filters, load_all_data, render_footer
from logic.geo import build_region_geojson
from logic.gtfs import compute_station_frequencies
from logic.matching import (
    map_frequencies_to_infra, mergure_segments,
    check_network_connectivity, build_infra_index_and_graph,
)
from logic.rendering import make_step_colormap, render_segment_map, render_choropleth, ratio_to_blue, render_voronoi_map

st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

# ── Sidebar filters ──────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown('<p class="sidebar-section">View</p>', unsafe_allow_html=True)
    view_mode = st.radio("Display", ["Segments", "Provinces", "Regions", "Voronoi"],
                         label_visibility="collapsed", horizontal=True)

filters = render_sidebar_filters()
data = load_all_data(filters)

# ── Processing ────────────────────────────────────────────────────────────────

segment_freqs = data["segment_freqs"]
cluster_map = data.get("cluster_map")

# Hashable fingerprint so the cache invalidates when filters change
_filter_key = (
    filters["start_date"], filters["end_date"], filters["day_count"],
    tuple(filters["weekdays"]),
    tuple(filters["hour_filter"]) if filters.get("hour_filter") else None,
)

@st.cache_data(show_spinner="Mapping to infrastructure...", ttl=3600)
def _cached_segments(filter_key, _seg_freqs, _stop_lookup, _infrabel_segs,
                     _gtfs_to_infra, _prov_geo, _cluster_map, _served_stations):
    segments, stats = map_frequencies_to_infra(
        _seg_freqs, _stop_lookup, _infrabel_segs, _gtfs_to_infra, _prov_geo,
        cluster_map=_cluster_map,
    )
    segments = [s for s in segments if s["frequency"] > 0]
    station_freqs = compute_station_frequencies(_seg_freqs, _served_stations)
    segments_merged = mergure_segments(segments, buffer_km=0.5)
    return segments, segments_merged, station_freqs, stats

segments, segments_merged, station_freqs, mapping_stats = _cached_segments(
    _filter_key, segment_freqs, data["stop_lookup"],
    data["infrabel_segs"], data["gtfs_to_infra"], data["prov_geo"],
    cluster_map, data.get("served_stations"),
)

if not segments:
    st.warning("No segments found for the selected filters.")
    st.stop()

_, infra_graph = build_infra_index_and_graph(data["infrabel_segs"], cluster_map)
components = check_network_connectivity(infra_graph)

freqs_merged = [s["frequency"] for s in segments_merged]
max_freq_m, min_freq_m = max(freqs_merged), min(freqs_merged)

# ── Header ───────────────────────────────────────────────────────────────────

day_labels = filters["day_labels"]
period_str = f"{filters['start_date'].strftime('%d %b %Y')} – {filters['end_date'].strftime('%d %b %Y')}"
days_str = ", ".join(day_labels[d] for d in filters["weekdays"])
hour_str = f" | {filters['hour_filter'][0]}h–{filters['hour_filter'][1]}h" if filters["hour_filter"] else ""
hol_parts = []
if filters["exclude_pub"]:
    hol_parts.append("public holidays excl.")
if filters["exclude_sch"]:
    hol_parts.append("school holidays excl.")
hol_str = " | " + ", ".join(hol_parts) if hol_parts else ""

st.caption(f"**{period_str}** — {days_str}{hour_str}{hol_str} — {filters['day_count']} days averaged")

with st.expander("ℹ️ How is this computed?"):
    st.markdown("""
**Data sources**
- **GTFS feeds** from SNCB/NMBS, fetched via the MobilityTwin API (one snapshot per month in range).
- **Infrabel infrastructure** segments and operational points (track geometry).

**Segment frequency**
1. For each GTFS trip active on the selected days, consecutive stops are paired into *segments*.
2. Each segment is weighted by its `service_day_count` (how many selected days that service runs), then divided by the number of days to get an **average daily frequency**.
3. When multiple GTFS feeds (months) are loaded, segment counts are accumulated across feeds and normalised.
4. Pass-through stops (where the train doesn't board/alight passengers) are still counted — the train physically uses the track.

**Mapping to real tracks**
1. Each GTFS station is matched to its nearest Infrabel operational point (within 1 km).
2. If a direct Infrabel segment exists between the two mapped points, its geometry is used.
3. Otherwise, a shortest-path (BFS, up to 30 hops) through the Infrabel network finds intermediate segments.
4. Segments with no match fall back to a straight line between the GTFS coordinates.

**Overlap resolution ("mergure")**
- Segments connecting the same station pair with overlapping geometry are merged (frequencies summed).

**Views**
- *Segments*: each track segment colored by daily frequency.
- *Provinces / Regions*: total segment-frequency aggregated by the province/region of each segment midpoint.
- *Voronoi*: each station generates a territory; cells are colored by station frequency (sum of touching segments).
    """)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Track segments", f"{len(segments_merged):,}")
c2.metric("Busiest segment", f"{max_freq_m:.0f}/day")
c3.metric("Services", f"{len(data['service_ids']):,}")
c4.metric("Days averaged", filters["day_count"])

with st.expander("Diagnostics"):
    d1, d2 = st.columns(2)
    with d1:
        st.markdown(f"""
**Mapping**
- GTFS stop-pairs: {mapping_stats['total']:,}
- Mapped to Infrabel: {mapping_stats['mapped']:,} ({100*mapping_stats['mapped']/max(mapping_stats['total'],1):.0f}%)
  - Direct: {mapping_stats['direct']:,} | Via path: {mapping_stats['path']:,}
- Fallback (GTFS coords): {mapping_stats.get('fallback', 0):,}
- Dropped: {mapping_stats['dropped']:,}
        """)
    with d2:
        st.markdown(f"""
**Stations**
- GTFS stops: {len(data['stop_lookup']):,}
- Matched to Infrabel (1km): {len(data['gtfs_to_infra']):,} ({100*len(data['gtfs_to_infra'])/max(len(data['stop_lookup']),1):.0f}%)

**Network**: {len(components)} component(s), largest {len(components[0]) if components else 0} stations
        """)

# ── Helper ────────────────────────────────────────────────────────────────────

def compute_group_stats(segs, key):
    df_segs = pd.DataFrame(segs)
    if df_segs.empty or key not in df_segs.columns:
        return pd.DataFrame()
    grouped = df_segs.groupby(key)["frequency"].agg(
        Segments="count",
        **{"Sum of freq.": "sum"},
        **{"Avg freq./segment": "mean"},
        **{"Busiest segment": "max"},
    ).round(1)
    grouped = grouped[grouped["Sum of freq."] > 0]
    return grouped.sort_values("Sum of freq.", ascending=False)

# ── Map views ─────────────────────────────────────────────────────────────────

if view_mode == "Segments":
    cmap = make_step_colormap(freqs_merged, "Trains / day")
    m = render_segment_map(segments_merged, cmap, min_freq_m, max_freq_m,
                           station_freqs=station_freqs,
                           stop_lookup=data["stop_lookup"],
                           gtfs_to_infra=data["gtfs_to_infra"])
    st_folium(m, width="stretch", height=700, key="seg_map")
    with st.expander("Segment data"):
        df = pd.DataFrame([
            {"From": s["stop_a"], "To": s["stop_b"],
             "Trains/day": round(s["frequency"], 1), "Province": s["province"]}
            for s in segments_merged
        ]).sort_values("Trains/day", ascending=False).reset_index(drop=True)
        st.dataframe(df, width="stretch", height=400)

elif view_mode == "Provinces":
    st.markdown("Sum of segment frequencies whose midpoint falls in each province.")
    prov_stats = compute_group_stats(segments, "province")
    prov_totals = prov_stats["Sum of freq."].to_dict()
    prov_vals = [v for v in prov_totals.values() if v > 0]
    if prov_vals:
        pcmap = make_step_colormap(prov_vals, "Sum of segment freq.")
        m = render_choropleth(data["prov_geo"]["features"], prov_totals, pcmap,
                              segments, "name",
                              lambda n, t: f"{n}: {t:.0f} segment-trains/day")
        st_folium(m, width="stretch", height=700, key="prov_map")
    st.dataframe(prov_stats, width="stretch")

elif view_mode == "Regions":
    st.markdown("Same aggregation grouped into Belgium's three regions.")
    region_stats = compute_group_stats(segments, "region")
    region_geo = build_region_geojson(data["prov_geo"])
    region_totals = region_stats["Sum of freq."].to_dict()
    region_vals = [v for v in region_totals.values() if v > 0]

    rc1, rc2, rc3 = st.columns(3)
    for col, reg in zip([rc1, rc2, rc3], ["Brussels", "Flanders", "Wallonia"]):
        with col:
            if reg in region_stats.index:
                st.metric(reg, f"{region_stats.loc[reg, 'Sum of freq.']:,.0f}")
                st.caption(f"{int(region_stats.loc[reg, 'Segments'])} segments")
            else:
                st.metric(reg, "---")

    if region_vals:
        rcmap = make_step_colormap(region_vals, "Sum of segment freq.")
        m = render_choropleth(region_geo["features"], region_totals, rcmap,
                              segments, "region",
                              lambda n, t: f"{n}: {t:.0f} segment-trains/day")
        st_folium(m, width="stretch", height=700, key="region_map")
    st.dataframe(region_stats, width="stretch")

elif view_mode == "Voronoi":
    st.markdown("Station frequency Voronoi — each cell colored by its station's total trains/day.")
    if station_freqs and data["stop_lookup"]:
        rows = []
        for sid, freq in station_freqs.items():
            info = data["stop_lookup"].get(sid)
            if info:
                rows.append({"station_name": info["name"], "lat": info["lat"],
                              "lon": info["lon"], "frequency": freq})
        if rows:
            vor_df = pd.DataFrame(rows)
            vm = render_voronoi_map(
                vor_df, "frequency",
                color_fn=lambda v, vmin, vmax: ratio_to_blue(
                    (v - vmin) / max(vmax - vmin, 1)),
                tooltip_fn=lambda r: f"<b>{r['station_name']}</b><br/>{r['frequency']:.0f} trains/day",
                prov_geo=data["prov_geo"],
            )
            st_folium(vm, width="stretch", height=700, key="voronoi_map")
    else:
        st.warning("No station frequency data available.")

render_footer()
