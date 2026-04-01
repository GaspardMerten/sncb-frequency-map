"""Shared state and data loading used across all pages."""

import os
import json
import streamlit as st
from collections import defaultdict
from datetime import datetime, date, timedelta
from dotenv import load_dotenv

from .api import fetch_gtfs, fetch_infrabel_segments, fetch_operational_points
from .holidays import (
    public_holidays_in_range, school_holidays_in_range, SCHOOL_HOLIDAYS,
)
from .gtfs import get_service_day_counts, build_stop_lookup, compute_segment_frequencies
from .reachability import build_timetable_graph
from .matching import build_gtfs_to_infra_mapping, build_infra_cluster_map

load_dotenv()

TOKEN = os.getenv("BRUSSELS_MOBILITY_TWIN_KEY", "")

# ── Custom CSS (light blue theme) ────────────────────────────────────────────

CUSTOM_CSS = """
<style>
    .block-container {
        padding-top: 1rem !important;
        padding-bottom: 0 !important;
        padding-left: 1.5rem !important;
        padding-right: 1.5rem !important;
        max-width: 100% !important;
    }
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #f0f4fa 0%, #dce6f5 100%);
        border-right: 2px solid #b8d4f0;
    }
    [data-testid="stSidebar"] .stMarkdown h1,
    [data-testid="stSidebar"] .stMarkdown h2,
    [data-testid="stSidebar"] .stMarkdown h3 {
        color: #084594;
    }
    [data-testid="stMetric"] {
        background: #f0f4fa;
        border: 1px solid #b8d4f0;
        border-radius: 8px;
        padding: 12px 16px;
    }
    [data-testid="stMetricValue"] { color: #2171b5; }
    .footer-credit {
        text-align: center;
        color: #7a8eaa;
        font-size: 0.8rem;
        padding: 12px 0 4px 0;
        border-top: 1px solid #dce6f5;
        margin-top: 8px;
    }
    .sidebar-divider {
        border: none;
        border-top: 1px solid #b8d4f0;
        margin: 12px 0;
    }
    .sidebar-section {
        color: #2171b5;
        font-size: 0.85rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        margin-bottom: 4px;
    }
</style>
"""


@st.cache_data(ttl=86400)
def load_provinces_geojson():
    path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "provinces.geojson")
    with open(path) as f:
        return json.load(f)


def render_sidebar_filters():
    """Render shared sidebar filters and return the computed state dict."""
    day_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

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
                                       min_value=date(2024, 8, 21), max_value=today)
        with dc2:
            end_date = st.date_input("To", value=today,
                                     min_value=start_date, max_value=today)
        if start_date > end_date:
            st.error("Start must be before end.")
            st.stop()
        st.caption("Loads one GTFS snapshot per month in the range.")

        st.markdown('<hr class="sidebar-divider"/>', unsafe_allow_html=True)
        st.markdown('<p class="sidebar-section">Days of the week</p>', unsafe_allow_html=True)
        weekdays = []
        day_cols = st.columns(7)
        for i, (c, lbl) in enumerate(zip(day_cols, day_labels)):
            with c:
                if st.checkbox(lbl, value=i < 5, key=f"wd_{i}"):
                    weekdays.append(i)
        if not weekdays:
            st.warning("Pick at least one day.")
            st.stop()

        pub_hols = public_holidays_in_range(start_date, end_date)
        sch_hols = school_holidays_in_range(start_date, end_date)

        st.markdown('<hr class="sidebar-divider"/>', unsafe_allow_html=True)
        st.markdown('<p class="sidebar-section">Holidays</p>', unsafe_allow_html=True)
        exclude_pub = st.toggle("Exclude public holidays", value=False)
        exclude_sch = st.toggle("Exclude school holidays", value=False)

        if pub_hols:
            with st.expander(f"Public holidays ({len(pub_hols)})"):
                for d, name in sorted(pub_hols.items()):
                    prefix = "~~" if exclude_pub else ""
                    st.caption(f"{prefix}{d.strftime('%a %d %b %Y')} — {name}{prefix}")
        if sch_hols:
            with st.expander(f"School holidays ({len(sch_hols)} periods)"):
                for s, e, name in sorted(sch_hols):
                    prefix = "~~" if exclude_sch else ""
                    st.caption(f"{prefix}{s.strftime('%d %b')} – {e.strftime('%d %b %Y')} — {name}{prefix}")

        st.markdown('<hr class="sidebar-divider"/>', unsafe_allow_html=True)
        st.markdown('<p class="sidebar-section">Time of day</p>', unsafe_allow_html=True)
        use_hour = st.toggle("Filter by hour")
        hour_filter = None
        if use_hour:
            hour_filter = st.slider("Hour window", 0, 24, (7, 19), step=1)

        st.markdown('<hr class="sidebar-divider"/>', unsafe_allow_html=True)
        st.markdown(
            '<div class="footer-credit">Powered by<br/><strong>MobilityTwin.Brussels</strong><br/>(ULB)</div>',
            unsafe_allow_html=True,
        )

    excluded_dates: set[date] = set()
    if exclude_pub:
        excluded_dates |= set(pub_hols.keys())
    if exclude_sch:
        for s, e, _ in SCHOOL_HOLIDAYS:
            d = s
            while d <= e:
                excluded_dates.add(d)
                d += timedelta(days=1)

    all_dates = []
    d = start_date
    while d <= end_date:
        if d.weekday() in weekdays and d not in excluded_dates:
            all_dates.append(d)
        d += timedelta(days=1)

    if not all_dates:
        st.warning("No dates match the selected filters.")
        st.stop()

    return {
        "token": token,
        "start_date": start_date,
        "end_date": end_date,
        "weekdays": weekdays,
        "hour_filter": hour_filter,
        "day_count": len(all_dates),
        "all_dates": all_dates,
        "day_labels": day_labels,
        "exclude_pub": exclude_pub,
        "exclude_sch": exclude_sch,
    }


def _month_ranges(start_date: date, end_date: date) -> list[tuple[int, date, date]]:
    """Return (unix_timestamp_1st, month_start, month_end) for each month in range."""
    months = []
    d = start_date.replace(day=1)
    while d <= end_date:
        month_start = d
        if d.month == 12:
            month_end = d.replace(day=31)
        else:
            month_end = d.replace(month=d.month + 1, day=1) - timedelta(days=1)
        ts = int(datetime(d.year, d.month, 1).timestamp())
        months.append((ts, month_start, month_end))
        if d.month == 12:
            d = d.replace(year=d.year + 1, month=1)
        else:
            d = d.replace(month=d.month + 1)
    return months


def load_all_data(filters: dict):
    """Fetch and process all shared data with progress indication."""
    return _load_all_data_inner(filters)


def _load_all_data_inner(filters: dict):
    token = filters["token"]
    all_dates = filters["all_dates"]
    day_count = filters["day_count"]

    prov_geo = load_provinces_geojson()

    months = _month_ranges(filters["start_date"], filters["end_date"])
    active_months = [
        (ts, ms, me) for ts, ms, me in months
        if any(ms <= d <= me for d in all_dates)
    ]
    n_months = len(active_months)

    accumulated_seg_freqs: dict[tuple[str, str], float] = defaultdict(float)
    accumulated_departures: dict[str, list] = defaultdict(list)
    stop_lookup: dict = {}
    all_service_ids: set[str] = set()
    all_service_day_counts: dict[str, int] = defaultdict(int)

    first_ts = months[0][0] if months else int(datetime(filters["start_date"].year, filters["start_date"].month, 1).timestamp())

    progress = st.progress(0, text="Loading GTFS data...")

    for i, (ts, month_start, month_end) in enumerate(active_months):
        month_label = month_start.strftime("%b %Y")
        progress.progress(
            (i) / max(n_months, 1),
            text=f"Processing {month_label} ({i+1}/{n_months})...",
        )

        month_dates = [d for d in all_dates if month_start <= d <= month_end]
        if not month_dates:
            continue

        try:
            feed = fetch_gtfs(ts, token)
        except Exception as e:
            st.error(f"Failed to fetch GTFS for {month_label}: {e}")
            continue

        if feed.stop_times is None or feed.trips is None:
            st.warning(f"GTFS data incomplete for {month_label}, skipping.")
            continue

        sdc = get_service_day_counts(feed, month_dates)
        sids = set(sdc.keys())
        if not sids:
            continue

        month_lookup = build_stop_lookup(feed)
        stop_lookup.update(month_lookup)

        month_freqs = compute_segment_frequencies(
            feed, sids, filters["hour_filter"],
            day_count=1,
            service_day_counts=sdc,
        )
        for k, v in month_freqs.items():
            accumulated_seg_freqs[k] += v

        month_deps = build_timetable_graph(feed, sids, filters["hour_filter"])
        for station, deps in month_deps.items():
            accumulated_departures[station].extend(deps)

        for sid, cnt in sdc.items():
            all_service_day_counts[sid] += cnt
        all_service_ids |= sids

        del feed

    progress.progress(1.0, text="Finalizing...")

    if not all_service_ids:
        progress.empty()
        st.error("No active services found across any month.")
        st.stop()

    for sid in accumulated_departures:
        accumulated_departures[sid].sort(key=lambda x: x[0])

    segment_freqs = {k: v / max(day_count, 1) for k, v in accumulated_seg_freqs.items()}

    try:
        infrabel_segs = fetch_infrabel_segments(first_ts, token)
    except Exception:
        infrabel_segs = None
    try:
        op_points = fetch_operational_points(first_ts, token)
    except Exception:
        op_points = None

    # Cluster Infrabel stations within 1km to handle isolated points
    cluster_map = build_infra_cluster_map(op_points, infrabel_segs, radius_km=1.0)

    gtfs_to_infra = build_gtfs_to_infra_mapping(
        stop_lookup, op_points, buffer_km=1.0, infrabel_segs=infrabel_segs,
    )

    progress.empty()

    return {
        "segment_freqs": dict(segment_freqs),
        "station_departures": dict(accumulated_departures),
        "infrabel_segs": infrabel_segs,
        "op_points": op_points,
        "prov_geo": prov_geo,
        "service_ids": all_service_ids,
        "service_day_counts": dict(all_service_day_counts),
        "stop_lookup": stop_lookup,
        "gtfs_to_infra": gtfs_to_infra,
        "cluster_map": cluster_map,
    }
