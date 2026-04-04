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
connectivity = st.Page("pages/3_Station_Connectivity.py", title="Station Connectivity", icon="📊")
duration = st.Page("pages/4_Travel_Duration.py", title="Travel Duration", icon="⏱️")
multimodal = st.Page("pages/5_Multimodal_Duration.py", title="Multimodal Duration", icon="🚌")
punctuality = st.Page("pages/6_Train_Punctuality.py", title="Train Punctuality", icon="⏰")
accessibility = st.Page("pages/7_Stop_Accessibility.py", title="Stop Accessibility", icon="🚏")
propagation = st.Page("pages/8_Delay_Propagation.py", title="Delay Propagation", icon="🔍")
problematic = st.Page("pages/9_Problematic_Trains.py", title="Problematic Trains", icon="🚂")

pg = st.navigation([home, segments, reach, connectivity, duration, multimodal,
                     punctuality, accessibility, propagation, problematic])
pg.run()
