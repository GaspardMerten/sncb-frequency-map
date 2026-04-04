"""Delay Propagation Analysis page.

Identifies stations and segments where delays are introduced by comparing
consecutive stops along each train journey across multiple days.
Processes each day incrementally to avoid holding all raw data in memory.
"""

import os
from collections import defaultdict
from datetime import date, datetime, timedelta

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

    st.markdown('<p class="sidebar-section">View</p>', unsafe_allow_html=True)
    view_mode = st.radio("Display", ["Stations", "Segments"],
                         label_visibility="collapsed", horizontal=True)

    st.markdown('<hr class="sidebar-divider"/>', unsafe_allow_html=True)
    st.markdown('<p class="sidebar-section">Date range</p>', unsafe_allow_html=True)
    today = date.today()
    dc1, dc2 = st.columns(2)
    with dc1:
        start_date = st.date_input("From", value=today - timedelta(days=7),
                                   min_value=date(2024, 8, 21), max_value=today,
                                   key="prop_from")
    with dc2:
        end_date = st.date_input("To", value=today - timedelta(days=1),
                                 min_value=start_date, max_value=today,
                                 key="prop_to")
    n_days = (end_date - start_date).days + 1
    if n_days > 30:
        st.error("Max 30 days.")
        st.stop()
    st.caption(f"{n_days} day(s) selected")

    st.markdown('<hr class="sidebar-divider"/>', unsafe_allow_html=True)
    st.markdown('<p class="sidebar-section">Filters</p>', unsafe_allow_html=True)
    hour_range = st.slider("Hour window", 0, 24, (5, 24), step=1, key="prop_hr")
    threshold_sec = st.number_input("Min delay increase (sec)", value=60, step=30,
                                    help="Only count a segment if delay increased by more than this.")
    min_incidents = st.slider("Min incidents", 1, 50, 3,
                              help="Exclude stations/segments with fewer delay events.")

    st.markdown('<hr class="sidebar-divider"/>', unsafe_allow_html=True)
    st.markdown('<p class="sidebar-section">Delay range</p>', unsafe_allow_html=True)
    col_min, col_max = st.columns(2)
    with col_min:
        delay_floor = st.number_input("Min delay (min)", value=0.0, step=1.0,
                                      key="prop_floor")
    with col_max:
        delay_cap = st.number_input("Max delay (min)", value=30.0, step=1.0,
                                    key="prop_cap")
    exclude_outliers = st.toggle(
        "Exclude out-of-range", value=False, key="prop_excl",
        help="**ON**: drop records outside [min, max]. "
             "**OFF** (default): clamp below-min to 0, above-max to max.",
    )

    operator_placeholder = st.empty()

    st.markdown('<hr class="sidebar-divider"/>', unsafe_allow_html=True)
    st.markdown(
        '<div class="footer-credit">Powered by<br/><strong>MobilityTwin.Brussels</strong><br/>(ULB)</div>',
        unsafe_allow_html=True,
    )

# ── Incremental data loading + processing ────────────────────────────────────

all_dates = [start_date + timedelta(days=i) for i in range(n_days)]
delay_floor_sec = delay_floor * 60
delay_cap_sec = delay_cap * 60


def _process_day(records, datdep_str, threshold, h_start, h_end,
                 floor_sec, cap_sec, exclude):
    """Process one day's records into propagation events. Returns list of tuples."""
    if not records:
        return []

    df = pd.DataFrame(records)
    df["delay_dep_sec"] = pd.to_numeric(df["delay_dep"], errors="coerce")
    df = df.dropna(subset=["delay_dep_sec"])

    # Parse hour for filtering
    hours = pd.to_numeric(
        df["planned_time_dep"].astype(str).str.split(":").str[0], errors="coerce"
    ).fillna(-1).astype(int)
    minutes = pd.to_numeric(
        df["planned_time_dep"].astype(str).str.split(":").str[1], errors="coerce"
    ).fillna(0).astype(int)

    mask = (hours >= h_start) & (hours < h_end)
    df = df[mask.values]
    dep_total = (hours[mask] * 60 + minutes[mask]).values

    if df.empty:
        return []

    # Delay range
    delays = df["delay_dep_sec"].values.copy()
    if exclude:
        keep = (delays >= floor_sec) & (delays <= cap_sec)
        df = df[keep]
        delays = delays[keep]
        dep_total = dep_total[keep]
    else:
        delays = np.where(delays >= floor_sec, delays, 0.0)
        np.clip(delays, None, cap_sec, out=delays)

    if len(df) == 0:
        return []

    stations = df["ptcar_lg_nm_nl"].str.strip().str.upper().values
    train_nos = df["train_no"].values
    relations = df["relation"].values
    train_serv = df["train_serv"].values

    # Sort by (train_no, dep_total) using numpy argsort
    order = np.lexsort((dep_total, train_nos))
    stations = stations[order]
    train_nos = train_nos[order]
    relations = relations[order]
    train_serv_arr = train_serv[order]
    delays = delays[order]

    # Find consecutive pairs within same train
    same_train = train_nos[1:] == train_nos[:-1]
    increases = delays[1:] - delays[:-1]
    above = increases > threshold

    hits = same_train & above
    idx = np.where(hits)[0]

    events = []
    for i in idx:
        events.append((
            stations[i],       # from_station
            stations[i + 1],   # to_station
            float(increases[i]),
            train_nos[i + 1],
            relations[i + 1],
            datdep_str,
            train_serv_arr[i + 1],
        ))
    return events


# Cache key includes all parameters that affect the result
cache_key = (
    tuple(all_dates), token, threshold_sec, tuple(hour_range),
    delay_floor_sec, delay_cap_sec, exclude_outliers,
)

if st.session_state.get("_prop_agg_key") == cache_key:
    station_agg = st.session_state["_prop_station_agg"]
    segment_agg = st.session_state["_prop_segment_agg"]
    all_operators_found = st.session_state["_prop_operators"]
else:
    progress = st.progress(0, text="Loading and processing...")
    all_events = []
    operators_seen = set()

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

        # Collect operators before processing
        for r in records[:100]:  # sample first 100 for operators
            if r.get("train_serv"):
                operators_seen.add(r["train_serv"])

        events = _process_day(
            records, str(d), threshold_sec, hour_range[0], hour_range[1],
            delay_floor_sec, delay_cap_sec, exclude_outliers,
        )
        all_events.extend(events)
        del records  # free memory immediately

    progress.progress(1.0, text="Aggregating...")

    all_operators_found = sorted(operators_seen)

    if not all_events:
        progress.empty()
        st.warning("No delay propagation events found.")
        st.stop()

    # Build aggregations directly from event tuples
    # Station accumulator
    sta_total = defaultdict(float)
    sta_count = defaultdict(int)
    sta_trains = defaultdict(set)
    sta_days = defaultdict(set)
    sta_rels = defaultdict(lambda: defaultdict(int))

    seg_total = defaultdict(float)
    seg_count = defaultdict(int)
    seg_trains = defaultdict(set)

    for from_s, to_s, increase, train, rel, datdep, serv in all_events:
        sta_total[to_s] += increase
        sta_count[to_s] += 1
        sta_trains[to_s].add(train)
        sta_days[to_s].add(datdep)
        sta_rels[to_s][rel] += 1

        seg_key = (from_s, to_s)
        seg_total[seg_key] += increase
        seg_count[seg_key] += 1
        seg_trains[seg_key].add(train)

    del all_events

    station_rows = []
    for s in sta_total:
        top_rel = max(sta_rels[s], key=sta_rels[s].get)
        station_rows.append({
            "station": s,
            "total_delay_min": round(sta_total[s] / 60, 1),
            "avg_increase_min": round(sta_total[s] / sta_count[s] / 60, 1),
            "n_incidents": sta_count[s],
            "n_trains": len(sta_trains[s]),
            "n_days": len(sta_days[s]),
            "top_relation": top_rel,
        })
    station_agg = pd.DataFrame(station_rows)

    segment_rows = []
    for (f, t) in seg_total:
        segment_rows.append({
            "from_station": f,
            "to_station": t,
            "total_delay_min": round(seg_total[(f, t)] / 60, 1),
            "avg_increase_min": round(seg_total[(f, t)] / seg_count[(f, t)] / 60, 1),
            "n_incidents": seg_count[(f, t)],
            "n_trains": len(seg_trains[(f, t)]),
        })
    segment_agg = pd.DataFrame(segment_rows) if segment_rows else pd.DataFrame()

    progress.empty()

    st.session_state["_prop_agg_key"] = cache_key
    st.session_state["_prop_station_agg"] = station_agg
    st.session_state["_prop_segment_agg"] = segment_agg
    st.session_state["_prop_operators"] = all_operators_found

# Operator filter (post-hoc on aggregated data — filters by top_relation's operator)
with operator_placeholder:
    selected_operators = st.multiselect(
        "Operators", all_operators_found, default=all_operators_found,
        key="prop_ops",
    )

if station_agg.empty:
    st.warning("No delay propagation events found with current settings.")
    st.stop()

station_agg = station_agg[station_agg["n_incidents"] >= min_incidents]
if segment_agg is not None and not segment_agg.empty:
    segment_agg = segment_agg[segment_agg["n_incidents"] >= min_incidents]

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
    f"{hour_range[0]}h–{hour_range[1]}h — "
    f"Threshold: {threshold_sec}s — Min incidents: {min_incidents} — "
    f"Delay range: {delay_floor}–{delay_cap} min"
)

with st.expander("How is this computed?"):
    st.markdown(f"""
**Goal**: Identify where delays are *introduced* into the network.

**Algorithm**:
1. Each day is fetched and processed individually (no full dataset in memory).
2. Per train journey: sorted by planned departure, consecutive delay increases computed.
3. Increases above **{threshold_sec}s** are recorded and aggregated across all days.

**Delay range** ({delay_floor}–{delay_cap} min):
- *Exclude OFF*: below-min clamped to 0, above-max clamped to max.
- *Exclude ON*: records outside range dropped.
""")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Stations", len(station_agg))
total_hours = station_agg["total_delay_min"].sum() / 60
c2.metric("Total delay introduced", f"{total_hours:.1f} h")
if not station_agg.empty:
    worst = station_agg.nlargest(1, "total_delay_min").iloc[0]
    c3.metric("Worst station", worst["station"])
    c4.metric("Avg increase", f"{station_agg['avg_increase_min'].mean():.1f} min")


# ── Color helper ─────────────────────────────────────────────────────────────

def _delay_color(ratio):
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


# ── Station view ─────────────────────────────────────────────────────────────

if view_mode == "Stations":
    lats = station_agg["station"].map(lambda s: station_coords.get(s, (None,))[0])
    lons = station_agg["station"].map(
        lambda s: station_coords[s][1] if s in station_coords else None)
    geo = station_agg.assign(lat=lats, lon=lons).dropna(subset=["lat", "lon"])

    if geo.empty:
        st.warning("No stations could be matched to coordinates.")
        st.stop()

    max_total = geo["total_delay_min"].quantile(0.95)
    max_avg = geo["avg_increase_min"].quantile(0.95)

    m = folium.Map(location=[50.5, 4.35], zoom_start=8, tiles="cartodbpositron")

    for _, row in geo.iterrows():
        total = row["total_delay_min"]
        avg = row["avg_increase_min"]
        radius = 3 + 14 * min(total / max(max_total, 0.1), 1.0)
        color = _delay_color(min(avg / max(max_avg, 0.1), 1.0))

        folium.CircleMarker(
            location=[row["lat"], row["lon"]],
            radius=radius, color=color, fill=True, fill_color=color,
            fill_opacity=0.8, weight=1,
            tooltip=(
                f"<b>{row['station']}</b><br/>"
                f"Total: {total:.0f} min | Avg: {avg:.1f} min<br/>"
                f"Incidents: {int(row['n_incidents'])} | Trains: {int(row['n_trains'])}<br/>"
                f"Top: {row['top_relation']}"
            ),
        ).add_to(m)

    cmap = cm.LinearColormap(
        colors=["#22b422", "#ffcc00", "#dd2020"],
        vmin=0, vmax=round(max_avg, 1),
        caption="Avg delay increase (min) — dot size = total delay introduced",
    )
    cmap.add_to(m)
    st_folium(m, width="stretch", height=650, key="prop_stations")

    st.subheader("Worst delay-introducing stations")
    top = geo.nlargest(25, "total_delay_min")[
        ["station", "total_delay_min", "avg_increase_min", "n_incidents",
         "n_trains", "n_days", "top_relation"]
    ]
    top.columns = ["Station", "Total (min)", "Avg (min)",
                   "Incidents", "Trains", "Days", "Top Relation"]
    st.dataframe(top.reset_index(drop=True), width="stretch")

# ── Segment view ─────────────────────────────────────────────────────────────

elif view_mode == "Segments":
    if segment_agg is None or segment_agg.empty:
        st.warning("No segments found.")
        st.stop()

    geo = segment_agg.assign(
        from_lat=segment_agg["from_station"].map(
            lambda s: station_coords.get(s, (None,))[0]),
        from_lon=segment_agg["from_station"].map(
            lambda s: station_coords[s][1] if s in station_coords else None),
        to_lat=segment_agg["to_station"].map(
            lambda s: station_coords.get(s, (None,))[0]),
        to_lon=segment_agg["to_station"].map(
            lambda s: station_coords[s][1] if s in station_coords else None),
    ).dropna(subset=["from_lat", "from_lon", "to_lat", "to_lon"])

    if geo.empty:
        st.warning("No segments matched to coordinates.")
        st.stop()

    max_total = geo["total_delay_min"].quantile(0.95)
    max_avg = geo["avg_increase_min"].quantile(0.95)

    m = folium.Map(location=[50.5, 4.35], zoom_start=8, tiles="cartodbpositron")

    for _, row in geo.iterrows():
        total = row["total_delay_min"]
        avg = row["avg_increase_min"]
        weight = max(2, min(10, 2 + 8 * min(total / max(max_total, 0.1), 1.0)))
        color = _delay_color(min(avg / max(max_avg, 0.1), 1.0))

        folium.PolyLine(
            locations=[[row["from_lat"], row["from_lon"]],
                       [row["to_lat"], row["to_lon"]]],
            color=color, weight=weight, opacity=0.8,
            tooltip=(
                f"<b>{row['from_station']} -> {row['to_station']}</b><br/>"
                f"Total: {total:.0f} min | Avg: {avg:.1f} min<br/>"
                f"Incidents: {int(row['n_incidents'])}"
            ),
        ).add_to(m)

    cmap = cm.LinearColormap(
        colors=["#22b422", "#ffcc00", "#dd2020"],
        vmin=0, vmax=round(max_avg, 1),
        caption="Avg delay increase (min) — line thickness = total delay",
    )
    cmap.add_to(m)
    st_folium(m, width="stretch", height=650, key="prop_segments")

    st.subheader("Worst delay-introducing segments")
    top = geo.nlargest(25, "total_delay_min")[
        ["from_station", "to_station", "total_delay_min", "avg_increase_min",
         "n_incidents", "n_trains"]
    ]
    top.columns = ["From", "To", "Total (min)", "Avg (min)", "Incidents", "Trains"]
    st.dataframe(top.reset_index(drop=True), width="stretch")

render_footer()
