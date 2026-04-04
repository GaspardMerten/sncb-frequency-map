"""Problematic Trains dashboard.

Per (relation, station) analysis: which stations consistently see late trains
for a given relation? Drill into day-by-day reliability and delay trends.
"""

import os
from datetime import date, timedelta

import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
from dotenv import load_dotenv

from logic.shared import CUSTOM_CSS, render_footer, noon_timestamp
from logic.api import fetch_punctuality_range

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
                         help="Exclude (relation, station) pairs seen on fewer days.")

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

# ── Load data ────────────────────────────────────────────────────────────────

all_dates = [start_date + timedelta(days=i) for i in range(n_days)]

cache_key = (tuple(all_dates), token)
if st.session_state.get("_prob_raw_key") == cache_key:
    df = st.session_state["_prob_raw"]
else:
    progress = st.progress(0, text="Loading punctuality data...")

    def _on_progress(i, total, d):
        progress.progress(i / max(total, 1),
                          text=f"Fetching {d.strftime('%d %b %Y')} ({i+1}/{total})...")

    records = fetch_punctuality_range(all_dates, token, progress_cb=_on_progress)
    progress.progress(1.0, text="Done!")
    progress.empty()

    if not records:
        st.warning("No punctuality data for the selected range.")
        st.stop()

    df = pd.DataFrame(records)
    st.session_state["_prob_raw_key"] = cache_key
    st.session_state["_prob_raw"] = df

# Operator + relation filters
available_operators = sorted(df["train_serv"].dropna().unique())
with operator_placeholder:
    selected_operators = st.multiselect(
        "Operators", available_operators, default=available_operators,
        key="prob_ops",
    )
if selected_operators:
    df = df[df["train_serv"].isin(selected_operators)]

available_relations = sorted(df["relation"].dropna().unique())
with relation_placeholder:
    selected_relations = st.multiselect(
        "Relations", available_relations, default=[],
        key="prob_rels",
        help="Leave empty for all.",
    )
if selected_relations:
    df = df[df["relation"].isin(selected_relations)]

if df.empty:
    st.warning("No data after filters.")
    st.stop()

# ── Compute per (relation, station) stats ────────────────────────────────────

late_threshold_sec = late_threshold_min * 60
delay_floor_sec = delay_floor * 60
delay_cap_sec = delay_cap * 60


@st.cache_data(show_spinner="Analysing reliability per station...", ttl=3600)
def _compute_station_stats(records, threshold_sec, min_d,
                           floor_sec, cap_sec, exclude):
    df = pd.DataFrame(records)
    df["delay_dep_sec"] = pd.to_numeric(df["delay_dep"], errors="coerce")
    df["station"] = df["ptcar_lg_nm_nl"].str.strip().str.upper()
    df = df.dropna(subset=["delay_dep_sec"])

    # Delay range filter
    if exclude:
        df = df[(df["delay_dep_sec"] >= floor_sec) & (df["delay_dep_sec"] <= cap_sec)]
    else:
        df["delay_dep_sec"] = df["delay_dep_sec"].where(
            df["delay_dep_sec"] >= floor_sec, 0.0)
        df["delay_dep_sec"] = df["delay_dep_sec"].clip(upper=cap_sec)

    if df.empty:
        return pd.DataFrame()

    df["delay_dep_min"] = df["delay_dep_sec"] / 60.0
    df["is_late"] = df["delay_dep_sec"] > threshold_sec

    # Per (relation, station, date): aggregate across trains
    day_agg = df.groupby(["relation", "station", "datdep"], sort=False).agg(
        avg_delay_min=("delay_dep_min", "mean"),
        max_delay_min=("delay_dep_min", "max"),
        n_trains=("train_no", "nunique"),
        n_late=("is_late", "sum"),
        n_total=("is_late", "count"),
    ).reset_index()

    day_agg["pct_late"] = day_agg["n_late"] / day_agg["n_total"] * 100

    # Across days
    stats = day_agg.groupby(["relation", "station"], sort=False).agg(
        n_days=("datdep", "nunique"),
        avg_delay_min=("avg_delay_min", "mean"),
        avg_max_delay_min=("max_delay_min", "mean"),
        worst_day_delay_min=("max_delay_min", "max"),
        avg_pct_late=("pct_late", "mean"),
        total_trains=("n_trains", "sum"),
    ).reset_index()

    stats = stats[stats["n_days"] >= min_d]
    return stats.round(1)


stats = _compute_station_stats(
    df.to_dict("records"), late_threshold_sec, min_days,
    delay_floor_sec, delay_cap_sec, exclude_outliers,
)

if stats.empty:
    st.warning("No (relation, station) pairs meet the minimum days threshold.")
    st.stop()

# ── Header ───────────────────────────────────────────────────────────────────

st.caption(
    f"**{start_date.strftime('%d %b')} – {end_date.strftime('%d %b %Y')}** — "
    f"Late threshold: {late_threshold_min} min — "
    f"Min {min_days} days — Delay range: {delay_floor}–{delay_cap} min"
)

with st.expander("How is this computed?"):
    st.markdown(f"""
**Goal**: Find (relation, station) pairs where trains are consistently late.

**Algorithm**:
1. Punctuality data is fetched for each day in the range ({n_days} days).
2. For each (relation, station, date): average delay, max delay, and % of late stops are computed.
3. A stop is "late" if its departure delay exceeds **{late_threshold_min} min**.
4. Statistics are aggregated across days.
5. Only pairs observed on at least **{min_days}** days are shown.

**Delay range** ({delay_floor}–{delay_cap} min):
- *Exclude OFF*: below-min clamped to 0, above-max clamped to max.
- *Exclude ON*: records outside range dropped.
""")

# Metrics
n_pairs = len(stats)
n_problem = (stats["avg_pct_late"] > 50).sum()
avg_delay = stats["avg_delay_min"].mean()
worst_station = stats.nlargest(1, "avg_pct_late").iloc[0]["station"] if not stats.empty else "N/A"

c1, c2, c3, c4 = st.columns(4)
c1.metric("Station-relation pairs", n_pairs)
c2.metric("Late >50% of days", n_problem)
c3.metric("Avg delay", f"{avg_delay:.1f} min")
c4.metric("Worst station", worst_station)

# ── Scatter plot ─────────────────────────────────────────────────────────────

fig_scatter = px.scatter(
    stats,
    x="avg_pct_late",
    y="avg_delay_min",
    color="relation",
    size="total_trains",
    hover_data=["station", "n_days", "worst_day_delay_min"],
    labels={
        "avg_pct_late": "Avg % Stops Late",
        "avg_delay_min": "Avg Delay (min)",
        "relation": "Relation",
        "total_trains": "Total Trains",
    },
    height=400,
)
fig_scatter.update_layout(
    margin=dict(t=10, b=30),
    legend=dict(orientation="h", yanchor="bottom", y=1.02),
)
st.plotly_chart(fig_scatter, use_container_width=True)

# ── Sortable table ───────────────────────────────────────────────────────────

st.subheader("All station-relation pairs")
display = stats.sort_values("avg_pct_late", ascending=False)[
    ["relation", "station", "n_days", "avg_pct_late", "avg_delay_min",
     "avg_max_delay_min", "worst_day_delay_min", "total_trains"]
].copy()
display.columns = ["Relation", "Station", "Days", "Avg % Late",
                   "Avg Delay (min)", "Avg Max Delay (min)",
                   "Worst Day (min)", "Total Trains"]
display = display.reset_index(drop=True)
display.index = display.index + 1
st.dataframe(display, width="stretch", height=400)

# ── Detail view for selected (relation, station) ────────────────────────────

st.subheader("Station detail")

detail_options = [
    f"{row['relation']} @ {row['station']} — {row['avg_pct_late']:.0f}% late"
    for _, row in stats.sort_values("avg_pct_late", ascending=False).head(200).iterrows()
]
detail_map = {
    opt: (row["relation"], row["station"])
    for opt, (_, row) in zip(
        detail_options,
        stats.sort_values("avg_pct_late", ascending=False).head(200).iterrows(),
    )
}

if not detail_options:
    st.info("No pairs to display.")
else:
    selected_label = st.selectbox("Select a (relation, station) pair", detail_options)
    sel_relation, sel_station = detail_map[selected_label]

    # Filter raw data
    detail_raw = df[
        (df["relation"] == sel_relation) &
        (df["ptcar_lg_nm_nl"].str.strip().str.upper() == sel_station)
    ].copy()
    detail_raw["delay_dep_sec"] = pd.to_numeric(detail_raw["delay_dep"], errors="coerce")
    detail_raw = detail_raw.dropna(subset=["delay_dep_sec"])

    # Apply delay range
    if exclude_outliers:
        detail_raw = detail_raw[
            (detail_raw["delay_dep_sec"] >= delay_floor_sec) &
            (detail_raw["delay_dep_sec"] <= delay_cap_sec)
        ]
    else:
        detail_raw["delay_dep_sec"] = detail_raw["delay_dep_sec"].where(
            detail_raw["delay_dep_sec"] >= delay_floor_sec, 0.0)
        detail_raw["delay_dep_sec"] = detail_raw["delay_dep_sec"].clip(upper=delay_cap_sec)

    detail_raw["delay_dep_min"] = detail_raw["delay_dep_sec"] / 60.0

    if detail_raw.empty:
        st.warning("No data for this pair.")
    else:
        # Day-by-day chart
        day_detail = detail_raw.groupby("datdep").agg(
            avg_delay_min=("delay_dep_min", "mean"),
            max_delay_min=("delay_dep_min", "max"),
            n_trains=("train_no", "nunique"),
            pct_late=("delay_dep_sec", lambda x: (x > late_threshold_sec).mean() * 100),
        ).reset_index().sort_values("datdep")

        fig_day = go.Figure()
        fig_day.add_trace(go.Bar(
            x=day_detail["datdep"],
            y=day_detail["avg_delay_min"],
            name="Avg delay",
            marker_color=[
                "#22b422" if v <= 0 else
                "#ffcc00" if v <= late_threshold_min else
                "#dd2020"
                for v in day_detail["avg_delay_min"]
            ],
            hovertext=[
                f"{d}<br>Avg: {a:.1f} min<br>Max: {m:.1f} min<br>"
                f"Trains: {int(n)}<br>Late: {p:.0f}%"
                for d, a, m, n, p in zip(
                    day_detail["datdep"], day_detail["avg_delay_min"],
                    day_detail["max_delay_min"], day_detail["n_trains"],
                    day_detail["pct_late"],
                )
            ],
            hoverinfo="text",
        ))
        fig_day.add_hline(y=late_threshold_min, line_dash="dash", line_color="#dd2020",
                          annotation_text=f"Late ({late_threshold_min} min)")
        fig_day.update_layout(
            xaxis_title="Date",
            yaxis_title="Avg delay (min)",
            height=300,
            margin=dict(t=10, b=40),
        )
        st.plotly_chart(fig_day, use_container_width=True)

        # Per-train breakdown at this station
        train_breakdown = detail_raw.groupby("train_no").agg(
            n_days=("datdep", "nunique"),
            avg_delay_min=("delay_dep_min", "mean"),
            max_delay_min=("delay_dep_min", "max"),
        ).round(1).sort_values("avg_delay_min", ascending=False)
        train_breakdown.columns = ["Days", "Avg Delay (min)", "Max Delay (min)"]
        train_breakdown.index.name = "Train"

        with st.expander(f"Train breakdown at {sel_station}"):
            st.dataframe(train_breakdown, width="stretch")

render_footer()
