"""API calls to the MobilityTwin Brussels platform."""

import dataclasses
import os
import tempfile
import requests
import streamlit as st
from types import SimpleNamespace
from gtfs_parquet import read_parquet

API_BASE = "https://api.mobilitytwin.brussels"


def _to_pandas_feed(pq_feed):
    """Convert a gtfs-parquet Feed (Polars DataFrames) to a SimpleNamespace
    with pandas DataFrames so the rest of the codebase can keep using pandas."""
    ns = SimpleNamespace()
    for field in dataclasses.fields(pq_feed):
        val = getattr(pq_feed, field.name)
        setattr(ns, field.name, val.to_pandas() if val is not None else None)
    return ns


@st.cache_resource(ttl=3600)
def fetch_gtfs(timestamp: int, token: str):
    """Download and parse the SNCB GTFS parquet for a given timestamp."""
    r = requests.get(
        f"{API_BASE}/sncb/gtfs-parquet",
        params={"timestamp": timestamp},
        headers={"Authorization": f"Bearer {token}"},
        timeout=120,
    )
    r.raise_for_status()
    tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    try:
        tmp.write(r.content)
        tmp.close()
        feed = _to_pandas_feed(read_parquet(tmp.name))
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


def fetch_gtfs_operator(operator_slug: str, timestamp: int, token: str,
                        progress_cb=None):
    """Download and parse a GTFS parquet for any supported operator.

    *progress_cb*: optional ``(downloaded_bytes, total_bytes) -> None``
    callback invoked during the download so the caller can update a
    progress bar.  When *None* the file is streamed silently.
    """
    r = requests.get(
        f"{API_BASE}/{operator_slug}/gtfs-parquet",
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
            if progress_cb and total:
                progress_cb(downloaded, total)
        tmp.close()
        feed = _to_pandas_feed(read_parquet(tmp.name))
    finally:
        os.unlink(tmp.name)
    return feed
