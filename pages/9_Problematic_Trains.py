"""Problematic Trains dashboard.

Per (train_no, station) analysis: which specific trains are consistently late
at specific stations? Processes each day incrementally to minimize memory.
"""

import os
from collections import defaultdict
from datetime import date, timedelta

import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
from dotenv import load_dotenv

from logic.shared import CUSTOM_CSS, render_footer, noon_timestamp
from logic.api import fetch_punctuality

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
        start_date = st.date_input("From", value=today - timedelta(days=14),
                                   min_value=date(2024, 8, 21), max_value=today,
                                   key="prob_from")
    with dc2:
        end_date = st.date_input("To", value=today - timedelta(days=1),
                                 min_value=start_date, max_value=today,
                                 key="prob_to")
    n_days = (end_date - start_date).days + 1
    if n_days > 30:
        st.error("Max 30 days.")
        st.stop()
    st.caption(f"{n_days} day(s) selected")

    st.markdown('<hr class="sidebar-divider"/>', unsafe_allow_html=True)
    st.markdown('<p class="sidebar-section">Thresholds</p>', unsafe_allow_html=True)
    late_threshold_min = st.number_input("Late threshold (min)", value=5.0, step=1.0,
                                         help="A stop is 'late' if its departure delay exceeds this.")
    min_days = st.slider("Min days observed", 1, min(14, n_days), min(3, n_days),
                         help="Exclude (train, station) pairs seen on fewer days.")

    st.markdown('<hr class="sidebar-divider"/>', unsafe_allow_html=True)
    st.markdown('<p class="sidebar-section">Delay range</p>', unsafe_allow_html=True)
    col_min, col_max = st.columns(2)
    with col_min:
        delay_floor = st.number_input("Min delay (min)", value=0.0, step=1.0,
                                      key="prob_floor")
    with col_max:
        delay_cap = st.number_input("Max delay (min)", value=60.0, step=5.0,
                                    key="prob_cap")
    exclude_outliers = st.toggle(
        "Exclude out-of-range", value=False, key="prob_excl",
        help="**ON**: drop records outside [min, max]. "
             "**OFF** (default): clamp below-min to 0, above-max to max.",
    )

    operator_placeholder = st.empty()
    relation_placeholder = st.empty()

    st.markdown('<hr class="sidebar-divider"/>', unsafe_allow_html=True)
    st.markdown(
        '<div class="footer-credit">Powered by<br/><strong>MobilityTwin.Brussels</strong><br/>(ULB)</div>',
        unsafe_allow_html=True,
    )

# ── Incremental processing ───────────────────────────────────────────────────

all_dates = [start_date + timedelta(days=i) for i in range(n_days)]
late_threshold_sec = late_threshold_min * 60
delay_floor_sec = delay_floor * 60
delay_cap_sec = delay_cap * 60

cache_key = (
    tuple(all_dates), token, delay_floor_sec, delay_cap_sec, exclude_outliers,
)

if st.session_state.get("_prob_agg_key") == cache_key:
    stats = st.session_state["_prob_stats"]
    detail_cache = st.session_state["_prob_detail"]
    all_operators_found = st.session_state["_prob_operators"]
    all_relations_found = st.session_state["_prob_relations"]
else:
    progress = st.progress(0, text="Loading and processing...")

    # Accumulators keyed by (train_no, station)
    # Per day: sum of delays, max delay, count, late count
    # We key the inner dict by datdep to count unique days
    pair_days = defaultdict(lambda: defaultdict(lambda: {
        "sum": 0.0, "max": 0.0, "n": 0, "n_late": 0,
    }))
    pair_meta = {}  # (train_no, station) -> {relation, operator}
    operators_seen = set()
    relations_seen = set()

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

        # Process in numpy for speed
        df = pd.DataFrame(records)
        delays = pd.to_numeric(df["delay_dep"], errors="coerce")
        valid = delays.notna()
        df = df[valid.values]
        delays = delays[valid.values].values.astype(np.float64)
        del records

        if len(df) == 0:
            continue

        # Delay range
        if exclude_outliers:
            keep = (delays >= delay_floor_sec) & (delays <= delay_cap_sec)
            df = df[keep]
            delays = delays[keep]
        else:
            delays = np.where(delays >= delay_floor_sec, delays, 0.0)
            np.clip(delays, None, delay_cap_sec, out=delays)

        if len(df) == 0:
            continue

        stations = df["ptcar_lg_nm_nl"].str.strip().str.upper().values
        train_nos = df["train_no"].values
        relations = df["relation"].values
        operators = df["train_serv"].values
        datdep = str(d)

        for j in range(len(df)):
            key = (train_nos[j], stations[j])
            day_agg = pair_days[key][datdep]
            day_agg["sum"] += delays[j]
            if delays[j] > day_agg["max"]:
                day_agg["max"] = delays[j]
            day_agg["n"] += 1
            if delays[j] > late_threshold_sec:
                day_agg["n_late"] += 1

            if key not in pair_meta:
                pair_meta[key] = {"relation": relations[j], "operator": operators[j]}

            operators_seen.add(operators[j])
            relations_seen.add(relations[j])

        del df, delays

    progress.progress(0.95, text="Aggregating...")

    all_operators_found = sorted(operators_seen)
    all_relations_found = sorted(relations_seen)

    # Build stats from accumulators
    rows = []
    detail_cache = {}
    for (train_no, station), days_dict in pair_days.items():
        nd = len(days_dict)
        total_sum = 0.0
        total_max_sum = 0.0
        total_pct_sum = 0.0
        worst_day = 0.0
        total_stops = 0
        day_details = {}

        for datdep, agg in days_dict.items():
            avg_d = agg["sum"] / max(agg["n"], 1)
            total_sum += avg_d
            total_max_sum += agg["max"]
            pct = agg["n_late"] / max(agg["n"], 1) * 100
            total_pct_sum += pct
            if agg["max"] > worst_day:
                worst_day = agg["max"]
            total_stops += agg["n"]
            day_details[datdep] = {
                "avg": round(avg_d / 60, 1),
                "max": round(agg["max"] / 60, 1),
                "n": agg["n"],
                "pct_late": round(pct, 1),
            }

        meta = pair_meta.get((train_no, station), {})
        rows.append({
            "train_no": train_no,
            "station": station,
            "relation": meta.get("relation", "?"),
            "operator": meta.get("operator", "?"),
            "n_days": nd,
            "avg_delay_min": round(total_sum / nd / 60, 1),
            "avg_max_delay_min": round(total_max_sum / nd / 60, 1),
            "worst_day_delay_min": round(worst_day / 60, 1),
            "avg_pct_late": round(total_pct_sum / nd, 1),
            "total_stops": total_stops,
        })
        detail_cache[(train_no, station)] = day_details

    del pair_days, pair_meta

    stats = pd.DataFrame(rows) if rows else pd.DataFrame()
    del rows

    progress.empty()

    st.session_state["_prob_agg_key"] = cache_key
    st.session_state["_prob_stats"] = stats
    st.session_state["_prob_detail"] = detail_cache
    st.session_state["_prob_operators"] = all_operators_found
    st.session_state["_prob_relations"] = all_relations_found

# Filters
with operator_placeholder:
    selected_operators = st.multiselect(
        "Operators", all_operators_found, default=all_operators_found,
        key="prob_ops",
    )

with relation_placeholder:
    selected_relations = st.multiselect(
        "Relations", all_relations_found, default=[],
        key="prob_rels",
        help="Leave empty for all.",
    )

if stats.empty:
    st.warning("No data found.")
    st.stop()

filtered = stats.copy()
if selected_operators:
    filtered = filtered[filtered["operator"].isin(selected_operators)]
if selected_relations:
    filtered = filtered[filtered["relation"].isin(selected_relations)]
filtered = filtered[filtered["n_days"] >= min_days]

if filtered.empty:
    st.warning("No (train, station) pairs meet the filters.")
    st.stop()

# ── Header ───────────────────────────────────────────────────────────────────

st.caption(
    f"**{start_date.strftime('%d %b')} – {end_date.strftime('%d %b %Y')}** — "
    f"Late threshold: {late_threshold_min} min — "
    f"Min {min_days} days — Delay range: {delay_floor}–{delay_cap} min"
)

with st.expander("How is this computed?"):
    st.markdown(f"""
**Goal**: Find specific trains that are consistently late at specific stations.

**Method**: Each day is processed individually. For each (train number, station, date):
average delay and % late stops are computed. Statistics are then aggregated across days
for each (train, station) pair.

A stop is "late" if departure delay exceeds **{late_threshold_min} min**.
Only pairs observed on at least **{min_days}** days are shown.
This reveals, for example, that train 2432 is late at Liege-Guillemins 80% of days.
""")

# Metrics
n_pairs = len(filtered)
n_problem = (filtered["avg_pct_late"] > 50).sum()
avg_delay = filtered["avg_delay_min"].mean()
worst = filtered.nlargest(1, "avg_pct_late").iloc[0]
worst_label = f"{worst['train_no']}@{worst['station']}"

c1, c2, c3, c4 = st.columns(4)
c1.metric("Train-station pairs", n_pairs)
c2.metric("Late >50%", n_problem)
c3.metric("Avg delay", f"{avg_delay:.1f} min")
c4.metric("Worst pair", worst_label)

# ── Scatter plot ─────────────────────────────────────────────────────────────

fig_scatter = px.scatter(
    filtered,
    x="avg_pct_late", y="avg_delay_min",
    color="relation", size="total_stops",
    hover_data=["train_no", "station", "operator", "n_days", "worst_day_delay_min"],
    labels={
        "avg_pct_late": "Avg % Late",
        "avg_delay_min": "Avg Delay (min)",
        "relation": "Relation",
        "total_stops": "Total Stops",
    },
    height=400,
)
fig_scatter.update_layout(
    margin=dict(t=10, b=30),
    legend=dict(orientation="h", yanchor="bottom", y=1.02),
)
st.plotly_chart(fig_scatter, use_container_width=True)

# ── Table ────────────────────────────────────────────────────────────────────

st.subheader("All train-station pairs")
display = filtered.sort_values("avg_pct_late", ascending=False)[
    ["train_no", "station", "relation", "operator", "n_days", "avg_pct_late",
     "avg_delay_min", "avg_max_delay_min", "worst_day_delay_min", "total_stops"]
]
display.columns = ["Train", "Station", "Relation", "Operator", "Days", "Avg % Late",
                   "Avg Delay (min)", "Avg Max (min)", "Worst Day (min)", "Total Stops"]
st.dataframe(display.reset_index(drop=True), width="stretch", height=400)

# ── Detail view ──────────────────────────────────────────────────────────────

st.subheader("Detail")

detail_options = [
    f"Train {row['train_no']} @ {row['station']} ({row['relation']}) — {row['avg_pct_late']:.0f}% late"
    for _, row in filtered.sort_values("avg_pct_late", ascending=False).head(200).iterrows()
]
detail_map = {
    opt: (row["train_no"], row["station"])
    for opt, (_, row) in zip(
        detail_options,
        filtered.sort_values("avg_pct_late", ascending=False).head(200).iterrows(),
    )
}

if not detail_options:
    st.info("No pairs to display.")
else:
    selected_label = st.selectbox("Select a (train, station) pair", detail_options)
    sel_train, sel_station = detail_map[selected_label]

    day_details = detail_cache.get((sel_train, sel_station), {})

    if not day_details:
        st.warning("No detail data for this pair.")
    else:
        day_rows = [
            {"date": d, **v}
            for d, v in sorted(day_details.items())
        ]
        day_df = pd.DataFrame(day_rows)

        fig_day = go.Figure()
        fig_day.add_trace(go.Bar(
            x=day_df["date"],
            y=day_df["avg"],
            marker_color=[
                "#22b422" if v <= 0 else
                "#ffcc00" if v <= late_threshold_min else
                "#dd2020"
                for v in day_df["avg"]
            ],
            hovertext=[
                f"{d}<br>Avg: {a} min<br>Max: {m} min<br>Stops: {n}<br>Late: {p}%"
                for d, a, m, n, p in zip(
                    day_df["date"], day_df["avg"], day_df["max"],
                    day_df["n"], day_df["pct_late"],
                )
            ],
            hoverinfo="text",
        ))
        fig_day.add_hline(y=late_threshold_min, line_dash="dash",
                          line_color="#dd2020",
                          annotation_text=f"Late ({late_threshold_min} min)")
        fig_day.update_layout(
            xaxis_title="Date", yaxis_title="Avg delay (min)",
            height=300, margin=dict(t=10, b=40),
        )
        st.plotly_chart(fig_day, use_container_width=True)

        with st.expander("Day-by-day data"):
            show_df = day_df.rename(columns={
                "date": "Date", "avg": "Avg Delay (min)", "max": "Max Delay (min)",
                "n": "Stops", "pct_late": "% Late",
            })
            st.dataframe(show_df, width="stretch", hide_index=True)

render_footer()
