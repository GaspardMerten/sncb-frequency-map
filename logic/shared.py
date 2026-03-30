"""Shared state and data loading used across all pages."""

import os
import json
import streamlit as st
from datetime import datetime, date, timedelta
from dotenv import load_dotenv

from .api import fetch_gtfs, fetch_infrabel_segments, fetch_operational_points
from .holidays import (
    public_holidays_in_range, school_holidays_in_range, SCHOOL_HOLIDAYS,
)
from .gtfs import get_active_service_ids, get_service_day_counts, build_stop_lookup, compute_segment_frequencies
from .matching import build_gtfs_to_infra_mapping, build_infra_graph

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
    """Render shared sidebar filters and return the computed state dict.

    Returns a dict with keys: token, start_date, end_date, weekdays, hour_filter,
    day_count, all_dates, exclude_pub, exclude_sch.
    Returns None if any required input is missing (st.stop() called).
    """
    day_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    with st.sidebar:
        # Token
        token = TOKEN
        if not token:
            token = st.text_input("API Token", type="password",
                                  help="Bearer token for api.mobilitytwin.brussels")
        if not token:
            st.info("Set `BRUSSELS_MOBILITY_TWIN_KEY` in `.env` or enter a token above.")
            st.stop()

        # Date range
        st.markdown('<hr class="sidebar-divider"/>', unsafe_allow_html=True)
        st.markdown('<p class="sidebar-section">Date range</p>', unsafe_allow_html=True)
        today = date.today()
        dc1, dc2 = st.columns(2)
        with dc1:
            start_date = st.date_input("From", value=date(2025, 3, 1),
                                       min_value=date(2024, 8, 21), max_value=today)
        with dc2:
            end_date = st.date_input("To", value=today,
                                     min_value=start_date, max_value=today)
        if start_date > end_date:
            st.error("Start must be before end.")
            st.stop()
        st.caption("Uses the GTFS snapshot from the 1st of the start month.")

        # Days of week
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

        # Holidays
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

        # Hour filter
        st.markdown('<hr class="sidebar-divider"/>', unsafe_allow_html=True)
        st.markdown('<p class="sidebar-section">Time of day</p>', unsafe_allow_html=True)
        use_hour = st.toggle("Filter by hour")
        hour_filter = None
        if use_hour:
            hour_filter = st.slider("Hour window", 0, 24, (7, 19), step=1)

        # Footer
        st.markdown('<hr class="sidebar-divider"/>', unsafe_allow_html=True)
        st.markdown(
            '<div class="footer-credit">Powered by<br/><strong>MobilityTwin.Brussels</strong><br/>(ULB)</div>',
            unsafe_allow_html=True,
        )

    # Compute target dates
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


def load_all_data(filters: dict):
    """Fetch and process all data based on filters. Returns a state dict.

    Cached via st.cache_data where possible; the heavy work (API calls) is cached.
    """
    ts = int(datetime(filters["start_date"].year, filters["start_date"].month, 1).timestamp())
    token = filters["token"]

    prov_geo = load_provinces_geojson()

    try:
        gtfs = fetch_gtfs(ts, token)
    except Exception as e:
        st.error(f"Failed to fetch GTFS: {e}")
        st.stop()
    if not gtfs or "stop_times" not in gtfs or "trips" not in gtfs:
        st.error("GTFS data is incomplete.")
        st.stop()

    try:
        infrabel_segs = fetch_infrabel_segments(ts, token)
    except Exception:
        infrabel_segs = None
    try:
        op_points = fetch_operational_points(ts, token)
    except Exception:
        op_points = None

    service_day_counts = get_service_day_counts(gtfs, filters["all_dates"])
    service_ids = set(service_day_counts.keys())
    if not service_ids:
        st.warning("No active services found. Trying all...")
        service_ids = set(gtfs["trips"]["service_id"].unique())
        service_day_counts = {sid: 1 for sid in service_ids}

    stop_lookup = build_stop_lookup(gtfs)
    gtfs_to_infra = build_gtfs_to_infra_mapping(stop_lookup, op_points, buffer_km=1.0)

    return {
        "gtfs": gtfs,
        "infrabel_segs": infrabel_segs,
        "op_points": op_points,
        "prov_geo": prov_geo,
        "service_ids": service_ids,
        "service_day_counts": service_day_counts,
        "stop_lookup": stop_lookup,
        "gtfs_to_infra": gtfs_to_infra,
        "ts": ts,
    }