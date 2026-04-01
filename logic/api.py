"""API calls to the MobilityTwin Brussels platform."""

import os
import tempfile
import requests
import streamlit as st
import gtfs_kit as gk

API_BASE = "https://api.mobilitytwin.brussels"


@st.cache_resource(ttl=3600)
def fetch_gtfs(timestamp: int, token: str) -> gk.Feed:
    """Download and parse the SNCB GTFS zip for a given timestamp."""
    r = requests.get(
        f"{API_BASE}/sncb/gtfs",
        params={"timestamp": timestamp},
        headers={"Authorization": f"Bearer {token}"},
        timeout=120,
    )
    r.raise_for_status()
    tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    try:
        tmp.write(r.content)
        tmp.close()
        feed = gk.read_feed(tmp.name, dist_units="km")
    finally:
        os.unlink(tmp.name)
    return feed


@st.cache_data(ttl=3600, show_spinner="Fetching rail segments...")
def fetch_infrabel_segments(timestamp: int, token: str) -> dict:
    """Fetch Infrabel track segment GeoJSON."""
    r = requests.get(
        f"{API_BASE}/infrabel/segments",
        params={"timestamp": timestamp},
        headers={"Authorization": f"Bearer {token}"},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()


@st.cache_data(ttl=3600, show_spinner="Fetching stations...")
def fetch_operational_points(timestamp: int, token: str) -> dict:
    """Fetch Infrabel operational points (stations) GeoJSON."""
    r = requests.get(
        f"{API_BASE}/infrabel/operational-points",
        params={"timestamp": timestamp},
        headers={"Authorization": f"Bearer {token}"},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()
