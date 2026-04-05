"""Missed Connections page.

Identifies stations where train delays cause passengers to miss planned
connections. Merges Infrabel punctuality data with GTFS station coordinates.
SNCB only. Processes each day incrementally with numpy-vectorized matching.
"""

import os
from collections import defaultdict
from datetime import date, timedelta

import numpy as np
import pandas as pd
import folium
import streamlit as st
from streamlit_folium import st_folium
import branca.colormap as cm
from dotenv import load_dotenv

from logic.shared import CUSTOM_CSS, render_footer, noon_timestamp
from logic.api import fetch_punctuality, fetch_operational_points

load_dotenv()

st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

TOKEN = os.getenv("BRUSSELS_MOBILITY_TWIN_KEY", "")

# ── Sidebar ──────────────────────────────────────────────────────────────────

with st.sidebar:
    token = TOKEN
    if not token:
        token = st.text_input("API Token", type="password",
                              help="Bearer token for api.mobilitytwin.brussels")
    if not token:
        st.info("Set `BRUSSELS_MOBILITY_TWIN_KEY` in `.env` or enter a token above.")
        st.stop()

    st.markdown('<hr class="sidebar-divider"/>', unsafe_allow_html=True)
    st.markdown('<p class="sidebar-section">Date range</p>', unsafe_allow_html=True)
    today = date.today()
    dc1, dc2 = st.columns(2)
    with dc1:
        start_date = st.date_input("From", value=today - timedelta(days=7),
                                   min_value=date(2024, 8, 21), max_value=today,
                                   key="mc_from")
    with dc2:
        end_date = st.date_input("To", value=today - timedelta(days=1),
                                 min_value=start_date, max_value=today,
                                 key="mc_to")
    n_days = (end_date - start_date).days + 1
    if n_days > 30:
        st.error("Max 30 days.")
        st.stop()
    st.caption(f"{n_days} day(s) selected")

    st.markdown('<hr class="sidebar-divider"/>', unsafe_allow_html=True)
    st.markdown('<p class="sidebar-section">Connection settings</p>', unsafe_allow_html=True)
    min_transfer = st.slider("Min transfer time (min)", 1, 10, 2,
                             help="Minimum planned gap between arrival and departure "
                                  "for a connection to be considered valid.")
    max_transfer = st.slider("Max transfer time (min)", 5, 60, 30,
                             help="Maximum planned gap — beyond this, it's not a connection.")
    hour_range = st.slider("Hour window", 0, 24, (5, 24), step=1, key="mc_hr")
    min_connections = st.slider("Min planned connections", 1, 100, 10,
                                help="Exclude stations with fewer planned connections.")

    st.markdown('<hr class="sidebar-divider"/>', unsafe_allow_html=True)
    st.markdown(
        '<div class="footer-credit">Powered by<br/><strong>MobilityTwin.Brussels</strong><br/>(ULB)</div>',
        unsafe_allow_html=True,
    )

# ── Vectorized day processing ────────────────────────────────────────────────

all_dates = [start_date + timedelta(days=i) for i in range(n_days)]
min_transfer_sec = min_transfer * 60
max_transfer_sec = max_transfer * 60


def _parse_time_sec_vec(series):
    """Vectorized parse of HH:MM:SS strings to seconds."""
    parts = series.astype(str).str.split(":", expand=True)
    h = pd.to_numeric(parts[0], errors="coerce").fillna(-1)
    m = pd.to_numeric(parts[1], errors="coerce").fillna(0)
    s = pd.to_numeric(parts.get(2, 0), errors="coerce").fillna(0) if 2 in parts.columns else 0
    result = (h * 3600 + m * 60 + s).values.astype(np.int64)
    result[h.values < 0] = -1
    return result


def _process_day_connections(records, h_start, h_end,
                             min_xfer, max_xfer):
    """Process one day with numpy vectorization.

    Returns dict: station -> (planned_count, missed_count)
    """
    if not records:
        return {}

    df = pd.DataFrame(records)

    # SNCB only
    df = df[df["train_serv"] == "SNCB/NMBS"]
    if df.empty:
        return {}

    # Parse times vectorized
    arr_sec = _parse_time_sec_vec(df["planned_time_arr"])
    dep_sec = _parse_time_sec_vec(df["planned_time_dep"])
    delay_arr = pd.to_numeric(df["delay_arr"], errors="coerce").fillna(0).values.astype(np.int64)
    delay_dep = pd.to_numeric(df["delay_dep"], errors="coerce").fillna(0).values.astype(np.int64)
    stations = df["ptcar_lg_nm_nl"].str.strip().str.upper().values
    trains = df["train_no"].values

    # Hour filter
    arr_h = arr_sec // 3600
    dep_h = dep_sec // 3600
    in_range = ((arr_h >= h_start) & (arr_h < h_end)) | ((dep_h >= h_start) & (dep_h < h_end))
    valid = in_range & ((arr_sec >= 0) | (dep_sec >= 0))

    arr_sec = arr_sec[valid]
    dep_sec = dep_sec[valid]
    delay_arr = delay_arr[valid]
    delay_dep = delay_dep[valid]
    stations = stations[valid]
    trains = trains[valid]

    if len(stations) == 0:
        return {}

    # Group by station using numpy — sort by station then process runs
    order = np.argsort(stations, kind="stable")
    stations_s = stations[order]
    arr_s = arr_sec[order]
    dep_s = dep_sec[order]
    da_s = delay_arr[order]
    dd_s = delay_dep[order]
    tr_s = trains[order]

    # Find station boundaries
    breaks = np.where(stations_s[1:] != stations_s[:-1])[0] + 1
    starts = np.concatenate([[0], breaks])
    ends = np.concatenate([breaks, [len(stations_s)]])

    result = {}
    for si in range(len(starts)):
        s, e = starts[si], ends[si]
        station_name = stations_s[s]

        # Arrivals: valid arr_sec
        arr_mask = arr_s[s:e] >= 0
        arr_planned = arr_s[s:e][arr_mask]
        arr_actual = arr_planned + da_s[s:e][arr_mask]
        arr_trains = tr_s[s:e][arr_mask]

        # Departures: valid dep_sec
        dep_mask = dep_s[s:e] >= 0
        dep_planned = dep_s[s:e][dep_mask]
        dep_actual = dep_planned + dd_s[s:e][dep_mask]
        dep_trains = tr_s[s:e][dep_mask]

        n_arr = len(arr_planned)
        n_dep = len(dep_planned)
        if n_arr == 0 or n_dep == 0:
            continue

        # Vectorized connection detection using broadcasting
        # gap[i,j] = dep_planned[j] - arr_planned[i]
        gap = dep_planned[None, :] - arr_planned[:, None]  # (n_arr, n_dep)

        # Valid connections: gap in [min_xfer, max_xfer] and different train
        diff_train = arr_trains[:, None] != dep_trains[None, :]  # (n_arr, n_dep)
        valid_conn = diff_train & (gap >= min_xfer) & (gap <= max_xfer)

        planned_count = int(valid_conn.sum())
        if planned_count == 0:
            continue

        # Missed: actual_arr > actual_dep where connection was valid
        actual_arr_2d = arr_actual[:, None]  # (n_arr, 1)
        actual_dep_2d = dep_actual[None, :]  # (1, n_dep)
        missed_mask = valid_conn & (actual_arr_2d > actual_dep_2d)
        missed_count = int(missed_mask.sum())

        result[station_name] = (planned_count, missed_count)

        # Free the 2D arrays
        del gap, diff_train, valid_conn, missed_mask

    return result


# ── Incremental processing across days ───────────────────────────────────────

cache_key = (
    tuple(all_dates), token, min_transfer_sec, max_transfer_sec, tuple(hour_range),
)

if st.session_state.get("_mc_agg_key") == cache_key:
    station_stats = st.session_state["_mc_stats"]
else:
    progress = st.progress(0, text="Loading and processing...")

    acc_planned = defaultdict(int)
    acc_missed = defaultdict(int)
    acc_days = defaultdict(int)

    for i, d in enumerate(all_dates):
        progress.progress(i / n_days,
                          text=f"Processing {d.strftime('%d %b %Y')} ({i+1}/{n_days})...")
        ts = noon_timestamp(d.year, d.month, d.day)
        try:
            records = fetch_punctuality(ts, token)
        except Exception:
            continue
        if not records:
            continue

        day_result = _process_day_connections(
            records, hour_range[0], hour_range[1],
            min_transfer_sec, max_transfer_sec,
        )
        del records

        for station, (p, m) in day_result.items():
            acc_planned[station] += p
            acc_missed[station] += m
            acc_days[station] += 1

    progress.progress(1.0, text="Done!")
    progress.empty()

    rows = []
    for station in acc_planned:
        p = acc_planned[station]
        m = acc_missed[station]
        rows.append({
            "station": station,
            "planned_connections": p,
            "missed_connections": m,
            "miss_rate": round(m / max(p, 1) * 100, 1),
            "n_days": acc_days[station],
            "avg_missed_per_day": round(m / max(acc_days[station], 1), 1),
        })

    station_stats = pd.DataFrame(rows) if rows else pd.DataFrame()

    st.session_state["_mc_agg_key"] = cache_key
    st.session_state["_mc_stats"] = station_stats

if station_stats.empty:
    st.warning("No connections found with current settings.")
    st.stop()

station_stats = station_stats[station_stats["planned_connections"] >= min_connections]

if station_stats.empty:
    st.warning("No stations meet the minimum connections threshold.")
    st.stop()

# Station coordinates
ts_infra = noon_timestamp(start_date.year, start_date.month, start_date.day)
op_points = fetch_operational_points(ts_infra, token)


@st.cache_data(show_spinner=False, ttl=3600)
def _build_station_coords(op_json):
    coords = {}
    for feat in op_json["features"]:
        props = feat["properties"]
        name = props.get("longnamedutch", "").strip().upper()
        if not name:
            continue
        pt = props.get("geo_point_2d") or {}
        lat, lon = pt.get("lat"), pt.get("lon")
        if lat and lon:
            coords[name] = (lat, lon)
    return coords


station_coords = _build_station_coords(op_points)

# ── Header ───────────────────────────────────────────────────────────────────

st.caption(
    f"**{start_date.strftime('%d %b')} – {end_date.strftime('%d %b %Y')}** — "
    f"SNCB only — {hour_range[0]}h–{hour_range[1]}h — "
    f"Transfer window: {min_transfer}–{max_transfer} min — "
    f"Min {min_connections} connections"
)

with st.expander("How is this computed?"):
    st.markdown(f"""
**Goal**: Identify stations where delays cause passengers to miss connections.

**Algorithm**:
1. For each day, Infrabel punctuality data is fetched (SNCB trains only).
2. At each station, arrivals and departures are matched using **numpy broadcasting**
   — no Python nested loop. The gap matrix `dep_planned - arr_planned` is computed
   in one operation for all pairs simultaneously.
3. A **planned connection**: different trains, planned gap in [{min_transfer}, {max_transfer}] min.
4. **Missed** if `actual_arrival > actual_departure`.
5. Aggregated across all days.
""")

# Metrics
total_planned = station_stats["planned_connections"].sum()
total_missed = station_stats["missed_connections"].sum()
overall_rate = total_missed / max(total_planned, 1) * 100
worst = station_stats.nlargest(1, "miss_rate").iloc[0]

c1, c2, c3, c4 = st.columns(4)
c1.metric("Stations", len(station_stats))
c2.metric("Total missed", f"{total_missed:,}")
c3.metric("Overall miss rate", f"{overall_rate:.1f}%")
c4.metric("Worst station", worst["station"])

# ── Map ──────────────────────────────────────────────────────────────────────

lats = station_stats["station"].map(lambda s: station_coords.get(s, (None,))[0])
lons = station_stats["station"].map(
    lambda s: station_coords[s][1] if s in station_coords else None)
geo = station_stats.assign(lat=lats, lon=lons).dropna(subset=["lat", "lon"])

if geo.empty:
    st.warning("No stations could be matched to coordinates.")
    st.stop()

max_missed = geo["missed_connections"].quantile(0.95)
max_rate = geo["miss_rate"].quantile(0.95)

m = folium.Map(location=[50.5, 4.35], zoom_start=8, tiles="cartodbpositron")


def _miss_color(rate, max_r):
    ratio = min(rate / max(max_r, 0.1), 1.0)
    if ratio < 0.5:
        r2 = ratio * 2
        r = int(34 + 221 * r2)
        g = int(180 - 40 * r2)
        b = int(34 - 30 * r2)
    else:
        r2 = (ratio - 0.5) * 2
        r = int(255 - 35 * r2)
        g = int(140 - 120 * r2)
        b = int(4 + 30 * r2)
    return f"#{max(0,min(255,r)):02x}{max(0,min(255,g)):02x}{max(0,min(255,b)):02x}"


for _, row in geo.iterrows():
    missed = row["missed_connections"]
    rate = row["miss_rate"]
    size_ratio = min(missed / max(max_missed, 1), 1.0)
    radius = 3 + 14 * size_ratio
    color = _miss_color(rate, max_rate)

    folium.CircleMarker(
        location=[row["lat"], row["lon"]],
        radius=radius,
        color=color, fill=True, fill_color=color,
        fill_opacity=0.8, weight=1,
        tooltip=(
            f"<b>{row['station']}</b><br/>"
            f"Planned: {int(row['planned_connections']):,}<br/>"
            f"Missed: {int(row['missed_connections']):,}<br/>"
            f"Miss rate: {rate:.1f}%<br/>"
            f"Avg missed/day: {row['avg_missed_per_day']:.1f}"
        ),
    ).add_to(m)

cmap = cm.LinearColormap(
    colors=["#22b422", "#ffcc00", "#dd2020"],
    vmin=0, vmax=round(max_rate, 1),
    caption="Miss rate (%) — dot size = total missed connections",
)
cmap.add_to(m)
st_folium(m, width="stretch", height=650, key="mc_map")

# ── Table ────────────────────────────────────────────────────────────────────

st.subheader("Worst stations for missed connections")
top = geo.nlargest(30, "missed_connections")[
    ["station", "planned_connections", "missed_connections", "miss_rate",
     "avg_missed_per_day", "n_days"]
]
top.columns = ["Station", "Planned", "Missed", "Miss Rate (%)",
               "Avg Missed/Day", "Days"]
st.dataframe(top.reset_index(drop=True), width="stretch")

# ── Miss rate distribution ───────────────────────────────────────────────────

import plotly.express as px

fig = px.histogram(
    geo, x="miss_rate", nbins=30,
    labels={"miss_rate": "Miss Rate (%)"},
)
fig.update_layout(height=300, margin=dict(t=10, b=30))
st.plotly_chart(fig, use_container_width=True)

render_footer()
