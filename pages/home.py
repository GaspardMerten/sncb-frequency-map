"""Home page with overview and navigation cards."""

import streamlit as st

st.markdown("""
<link href="https://cdn.jsdelivr.net/npm/tailwindcss@2.2.19/dist/tailwind.min.css" rel="stylesheet">
<style>
    .block-container { padding-top: 2rem !important; max-width: 960px !important; margin: 0 auto; }
    .hero { text-align: center; padding: 3rem 1rem 2rem; }
    .hero h1 { font-size: 2.5rem; font-weight: 800; color: #084594; margin-bottom: 0.5rem; }
    .hero p { font-size: 1.15rem; color: #4a6a8a; max-width: 640px; margin: 0 auto 2rem; line-height: 1.6; }
    .card {
        background: linear-gradient(135deg, #f0f6ff 0%, #e0ecf8 100%);
        border: 1px solid #b8d4f0;
        border-radius: 16px;
        padding: 2rem 1.5rem;
        text-align: center;
        transition: transform 0.15s ease, box-shadow 0.15s ease;
        cursor: pointer;
    }
    .card:hover { transform: translateY(-4px); box-shadow: 0 8px 24px rgba(8,69,148,0.15); }
    .card-icon { font-size: 2.5rem; margin-bottom: 0.75rem; }
    .card h3 { color: #084594; font-size: 1.1rem; font-weight: 700; margin-bottom: 0.5rem; }
    .card p { color: #4a6a8a; font-size: 0.88rem; line-height: 1.5; margin: 0; }
    .badge {
        display: inline-block; background: #2171b5; color: white;
        font-size: 0.65rem; font-weight: 600; padding: 2px 8px;
        border-radius: 999px; margin-top: 0.75rem; letter-spacing: 0.5px;
    }
    .footer-home {
        text-align: center; color: #8a9bb5; font-size: 0.82rem;
        padding: 2rem 0 1rem; border-top: 1px solid #dce6f5;
    }
    .footer-home strong { color: #2171b5; }
</style>

<div class="hero">
    <h1>SNCB Frequency Explorer</h1>
    <p>
        Explore the Belgian rail network through data.
        Analyze train frequencies, station reachability, connectivity scores,
        and travel durations across the network.
    </p>
</div>
""", unsafe_allow_html=True)

col1, col2 = st.columns(2)

with col1:
    st.markdown("""
    <div class="card">
        <div class="card-icon">&#128674;</div>
        <h3>Segment Frequency</h3>
        <p>Train frequencies per rail segment, province or region.</p>
        <span class="badge">GTFS + INFRABEL</span>
    </div>
    """, unsafe_allow_html=True)
    if st.button("Open Segment Frequency", key="nav_seg", use_container_width=True):
        st.switch_page("pages/1_Segment_Frequency.py")

with col2:
    st.markdown("""
    <div class="card">
        <div class="card-icon">&#128205;</div>
        <h3>Station Reach</h3>
        <p>How many stations are reachable within a time budget.</p>
        <span class="badge">BFS REACHABILITY</span>
    </div>
    """, unsafe_allow_html=True)
    if st.button("Open Station Reach", key="nav_reach", use_container_width=True):
        st.switch_page("pages/2_Station_Reach.py")

col3, col4 = st.columns(2)

with col3:
    st.markdown("""
    <div class="card">
        <div class="card-icon">&#128200;</div>
        <h3>Station Connectivity</h3>
        <p>Scatter plots: reachable destinations, direct frequency, cardinal reach.</p>
        <span class="badge">SCATTER ANALYSIS</span>
    </div>
    """, unsafe_allow_html=True)
    if st.button("Open Connectivity", key="nav_conn", use_container_width=True):
        st.switch_page("pages/3_Station_Connectivity.py")

with col4:
    st.markdown("""
    <div class="card">
        <div class="card-icon">&#9201;</div>
        <h3>Travel Duration</h3>
        <p>Travel time from every station to a chosen destination.</p>
        <span class="badge">ISOCHRONE MAP</span>
    </div>
    """, unsafe_allow_html=True)
    if st.button("Open Travel Duration", key="nav_dur", use_container_width=True):
        st.switch_page("pages/4_Travel_Duration.py")

st.markdown("""
<div class="footer-home">
    Powered by <strong>MobilityTwin.Brussels</strong> (ULB)<br/>
    Data: SNCB/NMBS GTFS &middot; Infrabel infrastructure
</div>
""", unsafe_allow_html=True)
