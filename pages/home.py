"""Home page with overview and navigation cards."""

import streamlit as st

st.markdown("""
<style>
    .block-container { padding-top: 1.5rem !important; max-width: 1000px !important; margin: 0 auto; }

    /* Hero */
    .hero {
        text-align: center;
        padding: 2.5rem 1rem 1rem;
        background: linear-gradient(135deg, #f0f6ff 0%, #dce6f5 60%, #c6dbef 100%);
        border-radius: 20px;
        margin-bottom: 1.5rem;
        border: 1px solid #b8d4f0;
    }
    .hero h1 {
        font-size: 2.2rem; font-weight: 800; color: #084594;
        margin: 0 0 0.3rem;
        letter-spacing: -0.5px;
    }
    .hero .subtitle {
        font-size: 1rem; color: #4a6a8a; max-width: 600px;
        margin: 0 auto 1rem; line-height: 1.6;
    }
    .hero .data-pills {
        display: flex; justify-content: center; gap: 0.5rem;
        flex-wrap: wrap; margin-bottom: 1rem;
    }
    .hero .pill {
        display: inline-block; background: rgba(33,113,181,0.12);
        color: #2171b5; font-size: 0.75rem; font-weight: 600;
        padding: 4px 12px; border-radius: 999px;
        letter-spacing: 0.3px;
    }

    /* Cards */
    .card-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; margin-bottom: 1.5rem; }
    .nav-card {
        background: #fff;
        border: 1px solid #d4e3f5;
        border-radius: 14px;
        padding: 1.5rem;
        transition: transform 0.15s ease, box-shadow 0.15s ease, border-color 0.15s ease;
    }
    .nav-card:hover {
        transform: translateY(-3px);
        box-shadow: 0 6px 20px rgba(8,69,148,0.10);
        border-color: #6baed6;
    }
    .nav-card .card-header {
        display: flex; align-items: center; gap: 0.6rem;
        margin-bottom: 0.5rem;
    }
    .nav-card .card-icon {
        font-size: 1.6rem; width: 40px; height: 40px;
        display: flex; align-items: center; justify-content: center;
        background: linear-gradient(135deg, #e8f0fe, #dce6f5);
        border-radius: 10px;
    }
    .nav-card h3 {
        color: #084594; font-size: 1rem; font-weight: 700; margin: 0;
    }
    .nav-card .card-desc {
        color: #4a6a8a; font-size: 0.85rem; line-height: 1.5;
        margin: 0 0 0.6rem;
    }
    .nav-card .card-tags {
        display: flex; gap: 0.4rem; flex-wrap: wrap;
    }
    .nav-card .tag {
        font-size: 0.65rem; font-weight: 600; padding: 2px 8px;
        border-radius: 999px; letter-spacing: 0.3px;
    }
    .tag-gtfs { background: #e8f0fe; color: #2171b5; }
    .tag-bfs { background: #e8f5e9; color: #2e7d32; }
    .tag-scatter { background: #fff3e0; color: #e65100; }
    .tag-map { background: #fce4ec; color: #c62828; }

    /* Data pipeline */
    .pipeline {
        background: #fafcff;
        border: 1px solid #d4e3f5;
        border-radius: 14px;
        padding: 1.25rem 1.5rem;
        margin-bottom: 1.5rem;
    }
    .pipeline h4 { color: #084594; font-size: 0.9rem; margin: 0 0 0.5rem; }
    .pipeline-steps {
        display: flex; align-items: center; gap: 0; flex-wrap: wrap;
        justify-content: center;
    }
    .pipeline-step {
        background: #e8f0fe; color: #2171b5;
        font-size: 0.78rem; font-weight: 600;
        padding: 6px 14px; border-radius: 8px;
        white-space: nowrap;
    }
    .pipeline-arrow { color: #6baed6; font-size: 1.1rem; padding: 0 6px; }

    /* Footer */
    .footer-home {
        text-align: center; color: #8a9bb5; font-size: 0.82rem;
        padding: 1.5rem 0 0.5rem; border-top: 1px solid #dce6f5;
    }
    .footer-home strong { color: #2171b5; }
</style>

<div class="hero">
    <h1>🚆 SNCB Frequency Explorer</h1>
    <p class="subtitle">
        Explore the Belgian rail network through open data.
        Analyse train frequencies, station reachability, connectivity patterns,
        and travel durations — from raw GTFS schedules to interactive maps.
    </p>
    <div class="data-pills">
        <span class="pill">SNCB / NMBS GTFS</span>
        <span class="pill">INFRABEL TRACK GEOMETRY</span>
        <span class="pill">MOBILITYTWIN API</span>
    </div>
</div>
""", unsafe_allow_html=True)

# ── Data pipeline overview ─────────────────────────────────────────────────
st.markdown("""
<div class="pipeline">
    <h4>Data pipeline</h4>
    <div class="pipeline-steps">
        <div class="pipeline-step">GTFS feeds</div>
        <span class="pipeline-arrow">→</span>
        <div class="pipeline-step">Filter by date & day</div>
        <span class="pipeline-arrow">→</span>
        <div class="pipeline-step">Match to Infrabel tracks</div>
        <span class="pipeline-arrow">→</span>
        <div class="pipeline-step">Compute metrics</div>
        <span class="pipeline-arrow">→</span>
        <div class="pipeline-step">Visualise</div>
    </div>
</div>
""", unsafe_allow_html=True)

# ── Navigation cards ────────────────────────────────────────────────────────
col1, col2 = st.columns(2)

with col1:
    st.markdown("""
    <div class="nav-card">
        <div class="card-header">
            <div class="card-icon">🛤️</div>
            <h3>Segment Frequency</h3>
        </div>
        <p class="card-desc">How many trains run on each track segment per day? See which rail corridors are busiest and which are underserved.</p>
        <div class="card-tags">
            <span class="tag tag-gtfs">GTFS</span>
            <span class="tag tag-map">INFRABEL GEOMETRY</span>
        </div>
    </div>
    """, unsafe_allow_html=True)
    if st.button("Open Segment Frequency", key="nav_seg", width="stretch"):
        st.switch_page("pages/1_Segment_Frequency.py")

with col2:
    st.markdown("""
    <div class="nav-card">
        <div class="card-header">
            <div class="card-icon">📍</div>
            <h3>Station Reach</h3>
        </div>
        <p class="card-desc">From any station, how many others can you reach within a time budget? Identifies well-connected hubs vs. isolated stops.</p>
        <div class="card-tags">
            <span class="tag tag-bfs">BFS TIMETABLE</span>
            <span class="tag tag-map">TRANSFERS</span>
        </div>
    </div>
    """, unsafe_allow_html=True)
    if st.button("Open Station Reach", key="nav_reach", width="stretch"):
        st.switch_page("pages/2_Station_Reach.py")

col3, col4 = st.columns(2)

with col3:
    st.markdown("""
    <div class="nav-card">
        <div class="card-header">
            <div class="card-icon">📊</div>
            <h3>Station Connectivity</h3>
        </div>
        <p class="card-desc">Compare stations on three axes: reachable destinations, direct frequency, and geographic reach in all cardinal directions.</p>
        <div class="card-tags">
            <span class="tag tag-scatter">SCATTER ANALYSIS</span>
            <span class="tag tag-bfs">A · B · C METRICS</span>
        </div>
    </div>
    """, unsafe_allow_html=True)
    if st.button("Open Connectivity", key="nav_conn", width="stretch"):
        st.switch_page("pages/3_Station_Connectivity.py")

with col4:
    st.markdown("""
    <div class="nav-card">
        <div class="card-header">
            <div class="card-icon">⏱️</div>
            <h3>Travel Duration</h3>
        </div>
        <p class="card-desc">How long does it take to travel to a chosen destination from anywhere in Belgium? Includes a continuous gradient heatmap with last-mile transport.</p>
        <div class="card-tags">
            <span class="tag tag-map">ISOCHRONE</span>
            <span class="tag tag-gtfs">GRADIENT HEATMAP</span>
        </div>
    </div>
    """, unsafe_allow_html=True)
    if st.button("Open Travel Duration", key="nav_dur", width="stretch"):
        st.switch_page("pages/4_Travel_Duration.py")

st.markdown("""
<div class="footer-home">
    Powered by <strong>MobilityTwin.Brussels</strong> (ULB)<br/>
    Data: SNCB/NMBS GTFS &middot; Infrabel infrastructure
</div>
""", unsafe_allow_html=True)
