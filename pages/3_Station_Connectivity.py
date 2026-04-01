"""Station Connectivity Analysis page.

Scatter plots combining three dimensions per station:
A: Reachable destinations (within time budget, max transfers)
B: Average hourly direct frequency (6h-22h)
C: Average distance (km) across reachable destinations
"""

import streamlit as st
import plotly.express as px

from logic.shared import CUSTOM_CSS, render_sidebar_filters, load_all_data
from logic.reachability import compute_connectivity_metrics

st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

# ── Sidebar ──────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown('<p class="sidebar-section">Connectivity settings</p>', unsafe_allow_html=True)
    max_hours = st.number_input("Time budget (hours)", min_value=0.5, max_value=6.0,
                                value=2.0, step=0.5, format="%.1f")
    max_transfers = st.slider("Max transfers", 0, 5, 2)
    departure_window = st.slider("Departure window", 0, 24, (7, 9), step=1)
    transfer_penalty = st.slider("Min transfer time (min)", 0, 15, 5)

filters = render_sidebar_filters()
data = load_all_data(filters)

max_minutes = max_hours * 60

# ── Compute metrics ──────────────────────────────────────────────────────────

@st.cache_data(show_spinner="Computing connectivity metrics...", ttl=3600)
def _cached_metrics(station_ids_tuple, _departures, _stop_lookup, _prov_geo,
                    max_minutes, max_transfers, transfer_penalty, departure_window):
    return compute_connectivity_metrics(
        list(station_ids_tuple), _departures, _stop_lookup, _prov_geo,
        max_minutes=max_minutes,
        max_transfers=max_transfers,
        transfer_penalty_min=transfer_penalty,
        departure_window=departure_window,
    )

station_ids = list(data["stop_lookup"].keys())
df = _cached_metrics(
    tuple(sorted(station_ids)), data["station_departures"],
    data["stop_lookup"], data["prov_geo"],
    max_minutes, max_transfers, transfer_penalty, departure_window,
)

if df.empty:
    st.warning("No connectivity data computed.")
    st.stop()

# ── Header ───────────────────────────────────────────────────────────────────

st.caption(
    f"**{filters['start_date'].strftime('%d %b %Y')} – {filters['end_date'].strftime('%d %b %Y')}** "
    f"— Budget {max_hours}h, max {max_transfers} transfers "
    f"— Departures {departure_window[0]}h–{departure_window[1]}h"
)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Stations", f"{len(df):,}")
c2.metric("Avg reachable (A)", f"{df['A_reachable'].mean():.1f}")
c3.metric("Avg direct freq/h (B)", f"{df['B_direct_freq'].mean():.2f}")
c4.metric("Avg distance km (C)", f"{df['C_avg_distance_km'].mean():.1f}")

# ── Tier classification ──────────────────────────────────────────────────────

df_sorted = df.sort_values("A_reachable", ascending=False).reset_index(drop=True)
n = len(df_sorted)


def assign_tier(idx):
    if idx < min(50, n):
        return "Well-connected (top 50)"
    elif idx < min(150, n):
        return "Medium (50-150)"
    else:
        return "Poorly connected (150+)"


df_sorted["tier"] = [assign_tier(i) for i in range(n)]

# ── Scatter plots ────────────────────────────────────────────────────────────

REGION_COLORS = {
    "Brussels": "#e31a1c",
    "Flanders": "#ff7f00",
    "Wallonia": "#1f78b4",
    "Unknown": "#999999",
}

common = dict(
    hover_data={"station_name": True, "tier": True},
    color="region",
    color_discrete_map=REGION_COLORS,
    opacity=0.7,
    height=500,
)

st.subheader("A vs B: Reachable destinations vs Direct frequency")
fig1 = px.scatter(
    df_sorted, x="A_reachable", y="B_direct_freq",
    labels={"A_reachable": f"Reachable destinations ({max_hours}h, {max_transfers} transfers)",
            "B_direct_freq": "Avg direct trains/hour (6h-22h)"},
    **common,
)
st.plotly_chart(fig1, use_container_width=True)

st.subheader("B vs C: Direct frequency vs Average distance")
fig2 = px.scatter(
    df_sorted, x="B_direct_freq", y="C_avg_distance_km",
    labels={"B_direct_freq": "Avg direct trains/hour (6h-22h)",
            "C_avg_distance_km": "Avg distance (km) to reachable stations"},
    **common,
)
st.plotly_chart(fig2, use_container_width=True)

st.subheader("A vs C: Reachable destinations vs Average distance")
fig3 = px.scatter(
    df_sorted, x="A_reachable", y="C_avg_distance_km",
    labels={"A_reachable": f"Reachable destinations ({max_hours}h, {max_transfers} transfers)",
            "C_avg_distance_km": "Avg distance (km) to reachable stations"},
    **common,
)
st.plotly_chart(fig3, use_container_width=True)

# ── Tier summary ─────────────────────────────────────────────────────────────

st.subheader("Station tiers")
tier_agg = df_sorted.groupby("tier").agg(
    count=("station_id", "count"),
    avg_A=("A_reachable", "mean"),
    avg_B=("B_direct_freq", "mean"),
    avg_C=("C_avg_distance_km", "mean"),
).round(2)
tier_agg.columns = ["Stations", "Avg reachable (A)", "Avg freq/h (B)", "Avg dist km (C)"]
st.dataframe(tier_agg, use_container_width=True)

# ── Full data table ──────────────────────────────────────────────────────────

with st.expander("Full station data"):
    display = df_sorted[["station_name", "A_reachable", "B_direct_freq",
                          "C_avg_distance_km", "region", "province", "tier"]].copy()
    display.columns = ["Station", "Reachable (A)", "Direct freq/h (B)",
                        "Avg dist km (C)", "Region", "Province", "Tier"]
    st.dataframe(display, use_container_width=True, height=400)

# Footer
st.markdown(
    '<div class="footer-credit">Powered by <strong>MobilityTwin.Brussels</strong> (ULB)</div>',
    unsafe_allow_html=True,
)
