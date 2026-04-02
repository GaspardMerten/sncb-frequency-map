"""Station Connectivity Analysis page.

Scatter plots combining three dimensions per station:
A: Reachable destinations (within time budget, max transfers)
B: Average hourly direct frequency (6h-22h)
C: Sum of max reach (km) in each cardinal direction (N+E+S+W)

Stations are classified by size based on direct frequency:
Small (< 4 trains/h), Medium (4-10), Big (> 10).
"""

import folium
import streamlit as st
import plotly.express as px
from streamlit_folium import st_folium

from logic.shared import CUSTOM_CSS, render_sidebar_filters, load_all_data, render_footer
from logic.reachability import compute_connectivity_metrics

st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

SIZE_ORDER = ["Small", "Medium", "Big"]
SIZE_COLORS = {"Small": "#6baed6", "Medium": "#2171b5", "Big": "#08306b"}

# ── Sidebar ──────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown('<p class="sidebar-section">Connectivity settings</p>', unsafe_allow_html=True)
    max_hours = st.number_input("Time budget (hours)", min_value=0.5, max_value=6.0,
                                value=2.0, step=0.5, format="%.1f")
    max_transfers = st.slider("Max transfers", 0, 5, 2)
    departure_window = st.slider("Departure window", 0, 24, (7, 9), step=1)
    transfer_penalty = st.slider("Min transfer time (min)", 0, 15, 5)

    st.markdown('<hr class="sidebar-divider"/>', unsafe_allow_html=True)
    st.markdown('<p class="sidebar-section">Station size filter</p>', unsafe_allow_html=True)
    selected_sizes = st.multiselect(
        "Show station sizes", SIZE_ORDER, default=SIZE_ORDER,
        label_visibility="collapsed",
    )

filters = render_sidebar_filters()
data = load_all_data(filters)

max_minutes = max_hours * 60

# ── Compute metrics ──────────────────────────────────────────────────────────

@st.cache_data(show_spinner="Computing connectivity metrics...", ttl=3600)
def _cached_metrics(station_ids_tuple, _departures, _stop_lookup, _prov_geo,
                    max_minutes, max_transfers, transfer_penalty, departure_window,
                    n_feeds):
    return compute_connectivity_metrics(
        list(station_ids_tuple), _departures, _stop_lookup, _prov_geo,
        max_minutes=max_minutes,
        max_transfers=max_transfers,
        transfer_penalty_min=transfer_penalty,
        departure_window=departure_window,
        n_feeds=n_feeds,
    )

station_ids = list(data["stop_lookup"].keys())
df_all = _cached_metrics(
    tuple(sorted(station_ids)), data["station_departures"],
    data["stop_lookup"], data["prov_geo"],
    max_minutes, max_transfers, transfer_penalty, departure_window,
    data.get("n_feeds", 1),
)

if df_all.empty:
    st.warning("No connectivity data computed.")
    st.stop()

# Apply size filter
df = df_all[df_all["station_size"].isin(selected_sizes)].copy()
if df.empty:
    st.warning("No stations match the selected size filter.")
    st.stop()

# ── Header ───────────────────────────────────────────────────────────────────

st.caption(
    f"**{filters['start_date'].strftime('%d %b %Y')} – {filters['end_date'].strftime('%d %b %Y')}** "
    f"— Budget {max_hours}h, max {max_transfers} transfers "
    f"— Departures {departure_window[0]}h–{departure_window[1]}h"
)

# Size breakdown metrics
size_counts = df_all["station_size"].value_counts()
c1, c2, c3, c4 = st.columns(4)
c1.metric("Stations", f"{len(df):,}")
c2.metric("Small (< 4/h)", size_counts.get("Small", 0))
c3.metric("Medium (4-10/h)", size_counts.get("Medium", 0))
c4.metric("Big (> 10/h)", size_counts.get("Big", 0))

# ═════════════════════════════════════════════════════════════════════════════
#  STATION SIZE MAP — circle size = direct frequency
# ═════════════════════════════════════════════════════════════════════════════

st.subheader("Station frequency map")
st.caption("Circle size reflects average direct trains/hour (6h-22h).")

m = folium.Map(location=[50.5, 4.35], zoom_start=8, tiles="cartodbpositron")
max_freq = df["B_direct_freq"].max() if not df.empty else 1

for _, row in df.iterrows():
    freq = row["B_direct_freq"]
    size_label = row["station_size"]
    color = SIZE_COLORS[size_label]
    radius = max(3, 4 + 14 * (freq / max(max_freq, 1)))

    folium.CircleMarker(
        location=[row["lat"], row["lon"]],
        radius=radius, color=color, fill=True, fill_color=color,
        fill_opacity=0.75, weight=1.5,
        tooltip=(
            f"<b>{row['station_name']}</b> ({size_label})<br/>"
            f"Direct freq: {freq:.1f} trains/h<br/>"
            f"Reachable: {row['A_reachable']} stations"
        ),
    ).add_to(m)

st_folium(m, use_container_width=True, height=550, key="freq_map")

# ═════════════════════════════════════════════════════════════════════════════
#  SCATTER PLOTS — one tab per station size
# ═════════════════════════════════════════════════════════════════════════════

REGION_COLORS = {
    "Brussels": "#e31a1c",
    "Flanders": "#ff7f00",
    "Wallonia": "#1f78b4",
    "Unknown": "#999999",
}

scatter_labels = {
    "A_reachable": f"Reachable destinations ({max_hours}h, {max_transfers} transfers)",
    "B_direct_freq": "Avg direct trains/hour (6h-22h)",
    "C_reach_km": "Reach N+E+S+W (km)",
}


def _scatter_section(subset, key_prefix):
    """Render the three scatter plots for a station subset."""
    if subset.empty:
        st.info("No stations in this category.")
        return

    common = dict(
        hover_data={"station_name": True, "station_size": True},
        color="region",
        color_discrete_map=REGION_COLORS,
        opacity=0.7,
        height=420,
    )

    fig1 = px.scatter(
        subset, x="A_reachable", y="B_direct_freq",
        size="C_reach_km", labels=scatter_labels, **common,
    )
    st.plotly_chart(fig1, use_container_width=True, key=f"{key_prefix}_ab")

    col1, col2 = st.columns(2)
    with col1:
        fig2 = px.scatter(
            subset, x="B_direct_freq", y="C_reach_km",
            size="A_reachable",
            labels=scatter_labels, height=380, **{k: v for k, v in common.items() if k != "height"},
        )
        st.plotly_chart(fig2, use_container_width=True, key=f"{key_prefix}_bc")
    with col2:
        fig3 = px.scatter(
            subset, x="A_reachable", y="C_reach_km",
            size="B_direct_freq",
            labels=scatter_labels, height=380, **{k: v for k, v in common.items() if k != "height"},
        )
        st.plotly_chart(fig3, use_container_width=True, key=f"{key_prefix}_ac")

    with st.expander(f"Station data ({len(subset)} stations)"):
        display = subset[["station_name", "A_reachable", "B_direct_freq",
                           "C_reach_km", "region", "province", "station_size"]].copy()
        display.columns = ["Station", "Reachable (A)", "Direct freq/h (B)",
                            "Reach NESW km (C)", "Region", "Province", "Size"]
        st.dataframe(display.sort_values("Reachable (A)", ascending=False).reset_index(drop=True),
                     use_container_width=True, height=300)


# Render tabs for each selected size
active_sizes = [s for s in SIZE_ORDER if s in selected_sizes]
tabs = st.tabs([f"{s} stations" for s in active_sizes])

for tab, size_label in zip(tabs, active_sizes):
    with tab:
        subset = df[df["station_size"] == size_label]
        n = len(subset)
        avg_a = subset["A_reachable"].mean()
        avg_b = subset["B_direct_freq"].mean()
        avg_c = subset["C_reach_km"].mean()

        mc1, mc2, mc3, mc4 = st.columns(4)
        mc1.metric("Stations", n)
        mc2.metric("Avg reachable", f"{avg_a:.1f}")
        mc3.metric("Avg freq/h", f"{avg_b:.2f}")
        mc4.metric("Avg reach", f"{avg_c:.0f} km")

        _scatter_section(subset, size_label.lower())

# ── Size comparison summary ──────────────────────────────────────────────────

st.subheader("Size comparison")
size_agg = df.groupby("station_size").agg(
    count=("station_id", "count"),
    avg_A=("A_reachable", "mean"),
    avg_B=("B_direct_freq", "mean"),
    avg_C=("C_reach_km", "mean"),
).reindex(SIZE_ORDER).dropna(how="all").round(2)
size_agg.columns = ["Stations", "Avg reachable (A)", "Avg freq/h (B)", "Reach NESW km (C)"]
st.dataframe(size_agg, use_container_width=True)

render_footer()
