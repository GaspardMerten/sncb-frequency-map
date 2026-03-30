"""API calls to the MobilityTwin Brussels platform."""

import io
import zipfile
import requests
import pandas as pd
import streamlit as st

API_BASE = "https://api.mobilitytwin.brussels"


@st.cache_data(ttl=3600, show_spinner="Fetching SNCB schedule...")
def fetch_gtfs(timestamp: int, token: str) -> dict[str, pd.DataFrame]:
    """Download and parse the SNCB GTFS zip for a given timestamp."""
    r = requests.get(
        f"{API_BASE}/sncb/gtfs",
        params={"timestamp": timestamp},
        headers={"Authorization": f"Bearer {token}"},
        timeout=120,
    )
    r.raise_for_status()
    frames = {}
    needed = {"stops", "stop_times", "trips", "calendar", "calendar_dates"}
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        for name in zf.namelist():
            key = name.replace(".txt", "").split("/")[-1]
            if key in needed:
                with zf.open(name) as f:
                    frames[key] = pd.read_csv(f, dtype=str)
    return frames


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
