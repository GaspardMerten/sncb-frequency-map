"""Missed Connections page.

Identifies stations where train delays cause passengers to miss planned
connections. Merges Infrabel punctuality data with GTFS station coordinates.
SNCB only.

A missed connection: Train A arrives at station S with delay, and connecting
Train B departs from S before Train A actually arrives — but after it was
scheduled to arrive (i.e. the connection was viable on paper).
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

# ── Incremental data loading + processing ────────────────────────────────────

all_dates = [start_date + timedelta(days=i) for i in range(n_days)]
min_transfer_sec = min_transfer * 60
max_transfer_sec = max_transfer * 60


def _parse_time_sec(time_str):
    """Parse HH:MM:SS to seconds since midnight."""
    if not time_str or not isinstance(time_str, str):
        return -1
    parts = time_str.split(":")
    if len(parts) < 2:
        return -1
    try:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + (int(parts[2]) if len(parts) > 2 else 0)
    except (ValueError, TypeError):
        return -1


def _process_day_connections(records, h_start, h_end,
                             min_xfer_sec, max_xfer_sec):
    """Process one day: find planned connections and check if missed.

    Returns dict: station -> {planned: int, missed: int, missed_trains: list}
    """
    if not records:
        return {}

    # Filter to SNCB only
    sncb = [r for r in records if r.get("train_serv") == "SNCB/NMBS"]
    if not sncb:
        return {}

    # Group by station
    by_station = defaultdict(list)
    for r in sncb:
        station = (r.get("ptcar_lg_nm_nl") or "").strip().upper()
        if not station:
            continue

        arr_time = _parse_time_sec(r.get("planned_time_arr"))
        dep_time = _parse_time_sec(r.get("planned_time_dep"))
        delay_arr = r.get("delay_arr")
        delay_dep = r.get("delay_dep")

        if arr_time < 0 and dep_time < 0:
            continue

        arr_h = arr_time // 3600 if arr_time >= 0 else -1
        dep_h = dep_time // 3600 if dep_time >= 0 else -1

        # At least one time must be in hour range
        if not ((h_start <= arr_h < h_end) or (h_start <= dep_h < h_end)):
            continue

        by_station[station].append({
            "train": r.get("train_no", "?"),
            "relation": r.get("relation", "?"),
            "arr_sec": arr_time,
            "dep_sec": dep_time,
            "delay_arr": int(delay_arr) if delay_arr is not None else 0,
            "delay_dep": int(delay_dep) if delay_dep is not None else 0,
        })

    # For each station, find connections and check if missed
    result = {}
    for station, stops in by_station.items():
        # Separate arrivals and departures
        arrivals = [(s["train"], s["arr_sec"], s["delay_arr"], s["relation"])
                    for s in stops if s["arr_sec"] >= 0]
        departures = [(s["train"], s["dep_sec"], s["delay_dep"], s["relation"])
                      for s in stops if s["dep_sec"] >= 0]

        if not arrivals or not departures:
            continue

        # Sort by planned time
        arrivals.sort(key=lambda x: x[1])
        departures.sort(key=lambda x: x[1])

        planned = 0
        missed = 0

        for arr_train, arr_planned, arr_delay, arr_rel in arrivals:
            actual_arr = arr_planned + arr_delay

            for dep_train, dep_planned, dep_delay, dep_rel in departures:
                # Skip same train
                if dep_train == arr_train:
                    continue

                # Check if this is a valid planned connection
                gap = dep_planned - arr_planned
                if gap < min_xfer_sec:
                    continue
                if gap > max_xfer_sec:
                    break  # sorted, no more valid connections

                # This is a planned connection
                planned += 1

                # Check if missed: actual arrival > actual departure
                actual_dep = dep_planned + dep_delay
                if actual_arr > actual_dep:
                    missed += 1

        if planned > 0:
            result[station] = {"planned": planned, "missed": missed}

    return result


cache_key = (
    tuple(all_dates), token, min_transfer_sec, max_transfer_sec, tuple(hour_range),
)

if st.session_state.get("_mc_agg_key") == cache_key:
    station_stats = st.session_state["_mc_stats"]
else:
    progress = st.progress(0, text="Loading and processing...")

    # Accumulate across days
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

        for station, counts in day_result.items():
            acc_planned[station] += counts["planned"]
            acc_missed[station] += counts["missed"]
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
2. At each station, all arrivals and departures are collected.
3. A **planned connection** is a pair (Train A arriving, Train B departing)
   where the planned gap is between **{min_transfer}** and **{max_transfer}** minutes
   and they are different trains.
4. A connection is **missed** if Train A's actual arrival time
   (planned + delay) is later than Train B's actual departure time
   (planned + delay).
5. Results are aggregated across all days.

**Interpretation**: Stations with high miss rates are bottlenecks where
tight connections are frequently broken by delays — potential candidates
for schedule padding or infrastructure improvements.
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
    # Size by total missed connections, color by miss rate
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
            f"Planned connections: {int(row['planned_connections']):,}<br/>"
            f"Missed: {int(row['missed_connections']):,}<br/>"
            f"Miss rate: {rate:.1f}%<br/>"
            f"Avg missed/day: {row['avg_missed_per_day']:.1f}<br/>"
            f"Days: {int(row['n_days'])}"
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
    title="Distribution of miss rates across stations",
)
fig.update_layout(height=300, margin=dict(t=40, b=30))
st.plotly_chart(fig, use_container_width=True)

render_footer()
