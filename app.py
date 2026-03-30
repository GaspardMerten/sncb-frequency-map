"""SNCB Frequency Explorer - Multi-page Streamlit application entry point."""

import streamlit as st

st.set_page_config(page_title="SNCB Frequency Explorer", layout="wide", page_icon="🚆")

# ── Home Page ────────────────────────────────────────────────────────────────

st.markdown("""
<link href="https://cdn.jsdelivr.net/npm/tailwindcss@2.2.19/dist/tailwind.min.css" rel="stylesheet">
<style>
    .block-container { padding-top: 2rem !important; max-width: 960px !important; margin: 0 auto; }
    .hero { text-align: center; padding: 3rem 1rem 2rem; }
    .hero h1 { font-size: 2.5rem; font-weight: 800; color: #084594; margin-bottom: 0.5rem; }
    .hero p { font-size: 1.15rem; color: #4a6a8a; max-width: 640px; margin: 0 auto 2rem; line-height: 1.6; }
    .card-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; max-width: 760px; margin: 0 auto 3rem; }
    .card {
        background: linear-gradient(135deg, #f0f6ff 0%, #e0ecf8 100%);
        border: 1px solid #b8d4f0;
        border-radius: 16px;
        padding: 2rem 1.5rem;
        text-align: center;
        transition: transform 0.15s ease, box-shadow 0.15s ease;
        text-decoration: none;
        display: block;
        color: inherit;
    }
    .card:hover { transform: translateY(-4px); box-shadow: 0 8px 24px rgba(8,69,148,0.12); }
    .card-icon { font-size: 2.5rem; margin-bottom: 0.75rem; }
    .card h3 { color: #084594; font-size: 1.2rem; font-weight: 700; margin-bottom: 0.5rem; }
    .card p { color: #4a6a8a; font-size: 0.92rem; line-height: 1.5; margin: 0; }
    .badge {
        display: inline-block;
        background: #2171b5;
        color: white;
        font-size: 0.7rem;
        font-weight: 600;
        padding: 2px 10px;
        border-radius: 999px;
        margin-top: 0.75rem;
        letter-spacing: 0.5px;
    }
    .footer-home {
        text-align: center;
        color: #8a9bb5;
        font-size: 0.82rem;
        padding: 2rem 0 1rem;
        border-top: 1px solid #dce6f5;
    }
    .footer-home strong { color: #2171b5; }
</style>

<div class="hero">
    <h1>SNCB Frequency Explorer</h1>
    <p>
        Explore the Belgian rail network through data.
        Analyze train frequencies across segments, provinces and regions,
        or discover how far you can travel from any station within a given time budget.
    </p>
</div>

<div class="card-grid">
    <div class="card">
        <div class="card-icon">&#128674;</div>
        <h3>Segment Frequency</h3>
        <p>
            Visualize how many trains pass through each rail segment per day.
            See frequency heatmaps by segment, province or region,
            based on official GTFS timetable data.
        </p>
        <span class="badge">GTFS + INFRABEL</span>
    </div>
    <div class="card">
        <div class="card-icon">&#128205;</div>
        <h3>Station Reach Analysis</h3>
        <p>
            For every station in Belgium, compute how many other stations
            are reachable within a time budget &mdash; including transfers.
            Explore connectivity and accessibility across the network.
        </p>
        <span class="badge">BFS REACHABILITY</span>
    </div>
</div>

<div class="footer-home">
    Powered by <strong>MobilityTwin.Brussels</strong> (ULB)<br/>
    Data: SNCB/NMBS GTFS &middot; Infrabel infrastructure
</div>
""", unsafe_allow_html=True)

st.markdown("")
st.caption("Select a page from the sidebar to get started.")
