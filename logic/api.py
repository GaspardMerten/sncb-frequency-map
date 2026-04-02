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


# ---------------------------------------------------------------------------
# Multi-operator GTFS (De Lijn, STIB/MIVB, TEC)
# ---------------------------------------------------------------------------

# Operator slug used in the MobilityTwin API
OPERATORS = {
    "SNCB":    "sncb",
    "De Lijn": "de-lijn",
    "STIB":    "stib",
    "TEC":     "tec",
}


@st.cache_resource(ttl=3600)
def fetch_gtfs_operator(operator_slug: str, timestamp: int, token: str,
                        _progress_cb=None) -> gk.Feed:
    """Download and parse a GTFS zip for any supported operator.

    *_progress_cb*: optional ``(downloaded_bytes, total_bytes) -> None``
    callback invoked during the download so the caller can update a
    progress bar.  When *None* the file is streamed silently.
    """
    r = requests.get(
        f"{API_BASE}/{operator_slug}/gtfs",
        params={"timestamp": timestamp},
        headers={"Authorization": f"Bearer {token}"},
        timeout=180,
        stream=True,
    )
    r.raise_for_status()
    total = int(r.headers.get("Content-Length", 0))
    tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    try:
        downloaded = 0
        for chunk in r.iter_content(chunk_size=1 << 20):  # 1 MB
            tmp.write(chunk)
            downloaded += len(chunk)
            if _progress_cb and total:
                _progress_cb(downloaded, total)
        tmp.close()
        feed = gk.read_feed(tmp.name, dist_units="km")
    finally:
        os.unlink(tmp.name)
    return feed
