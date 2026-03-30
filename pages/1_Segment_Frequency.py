"""Segment Frequency Analysis page.

Visualizes train frequencies per rail segment, province, and region.
"""

import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from logic.shared import CUSTOM_CSS, render_sidebar_filters, load_all_data
from logic.geo import build_region_geojson
from logic.gtfs import compute_segment_frequencies, compute_station_frequencies
from logic.matching import (
    map_frequencies_to_infra, mergure_segments,
    check_network_connectivity, build_infra_graph,
)
from logic.rendering import make_step_colormap, render_segment_map, render_choropleth

st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

# ── Sidebar filters ──────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown('<p class="sidebar-section">View</p>', unsafe_allow_html=True)
    view_mode = st.radio("Display", ["Segments", "Provinces", "Regions"],
                         label_visibility="collapsed", horizontal=True)

filters = render_sidebar_filters()
data = load_all_data(filters)

# ── Processing (cached via load_all_data + st.cache on API calls) ────────────

@st.cache_data(show_spinner="Computing segment frequencies...", ttl=3600)
def _cached_segments(_gtfs, service_ids_tuple, hour_filter, day_count,
                     _sdc, _stop_lookup, _infrabel_segs, _gtfs_to_infra, _prov_geo):
    segment_freqs = compute_segment_frequencies(
        _gtfs, set(service_ids_tuple), hour_filter, day_count,
        service_day_counts=_sdc,
    )
    segments, stats = map_frequencies_to_infra(
        segment_freqs, _stop_lookup, _infrabel_segs, _gtfs_to_infra, _prov_geo,
    )
    segments = [s for s in segments if s["frequency"] > 0]
    station_freqs = compute_station_frequencies(segment_freqs)
    segments_merged = mergure_segments(segments, buffer_km=0.5)
    return segments, segments_merged, station_freqs, stats

segments, segments_merged, station_freqs, mapping_stats = _cached_segments(
    data["gtfs"], tuple(sorted(data["service_ids"])),
    filters["hour_filter"], filters["day_count"],
    data["service_day_counts"], data["stop_lookup"],
    data["infrabel_segs"], data["gtfs_to_infra"], data["prov_geo"],
)

if not segments:
    st.warning("No segments found for the selected filters.")
    st.stop()

infra_graph = build_infra_graph(data["infrabel_segs"])
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
    out = {}
    for group in sorted(set(s[key] for s in segs)):
        grp = [s for s in segs if s[key] == group]
        total = sum(s["frequency"] for s in grp)
        if total == 0:
            continue
        out[group] = {
            "Segments": len(grp),
            "Sum of freq.": round(total, 1),
            "Avg freq./segment": round(total / len(grp), 1),
            "Busiest segment": round(max(s["frequency"] for s in grp), 1),
        }
    return pd.DataFrame(out).T.sort_values("Sum of freq.", ascending=False)

# ── Map views ─────────────────────────────────────────────────────────────────

if view_mode == "Segments":
    cmap = make_step_colormap(freqs_merged, "Trains / day")
    m = render_segment_map(segments_merged, cmap, min_freq_m, max_freq_m,
                           station_freqs=station_freqs,
                           stop_lookup=data["stop_lookup"],
                           gtfs_to_infra=data["gtfs_to_infra"])
    st_folium(m, use_container_width=True, height=700, key="seg_map")
    with st.expander("Segment data"):
        df = pd.DataFrame([
            {"From": s["stop_a"], "To": s["stop_b"],
             "Trains/day": round(s["frequency"], 1), "Province": s["province"]}
            for s in segments_merged
        ]).sort_values("Trains/day", ascending=False).reset_index(drop=True)
        st.dataframe(df, use_container_width=True, height=400)

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
        st_folium(m, use_container_width=True, height=700, key="prov_map")
    st.dataframe(prov_stats, use_container_width=True)

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
        st_folium(m, use_container_width=True, height=700, key="region_map")
    st.dataframe(region_stats, use_container_width=True)

# Footer
st.markdown(
    '<div class="footer-credit">Powered by <strong>MobilityTwin.Brussels</strong> (ULB)</div>',
    unsafe_allow_html=True,
)
