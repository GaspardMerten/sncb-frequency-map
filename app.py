"""SNCB Frequency Explorer - Home page."""

import streamlit as st

st.set_page_config(
    page_title="SNCB Frequency Explorer",
    layout="wide",
    page_icon="🚆",
)

# Register pages with nice names
home = st.Page("pages/home.py", title="Home", icon="🏠", default=True)
segments = st.Page("pages/1_Segment_Frequency.py", title="Segment Frequency", icon="🚆")
reach = st.Page("pages/2_Station_Reach.py", title="Station Reach", icon="📍")

pg = st.navigation([home, segments, reach])
pg.run()
