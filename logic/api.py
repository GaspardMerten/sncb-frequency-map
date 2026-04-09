"""API calls to the MobilityTwin Brussels platform."""

import os
import tempfile
from datetime import datetime, timedelta
from functools import lru_cache

import requests
from gtfs_parquet import read_parquet

API_BASE = "https://api.mobilitytwin.brussels"

# The punctuality endpoint returns data for 2 days before the requested
# timestamp.  To get data for date D, request timestamp for D+2 at noon.
_PUNCTUALITY_OFFSET_DAYS = 2


def punctuality_ts(d) -> int:
    """Return the API timestamp needed to fetch punctuality for date *d*."""
    target = d + timedelta(days=_PUNCTUALITY_OFFSET_DAYS)
    return int(datetime(target.year, target.month, target.day, 12, 0).timestamp())


@lru_cache(maxsize=8)
def fetch_gtfs(timestamp: int, token: str):
    """Download and parse the SNCB GTFS parquet for a given timestamp.

    Returns a native gtfs_parquet.Feed (Polars DataFrames).
    """
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
        feed = read_parquet(tmp.name)
    finally:
        os.unlink(tmp.name)
    return feed


@lru_cache(maxsize=8)
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


@lru_cache(maxsize=8)
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


@lru_cache(maxsize=16)
def fetch_punctuality(timestamp: int, token: str) -> list[dict]:
    """Fetch Infrabel train punctuality data."""
    r = requests.get(
        f"{API_BASE}/infrabel/punctuality",
        params={"timestamp": timestamp},
        headers={"Authorization": f"Bearer {token}"},
        timeout=120,
    )
    r.raise_for_status()
    return r.json()


# ---------------------------------------------------------------------------
# Multi-operator GTFS (De Lijn, STIB/MIVB, TEC)
# ---------------------------------------------------------------------------

OPERATORS = {
    "SNCB":    "sncb",
    "De Lijn": "de-lijn",
    "STIB":    "stib",
    "TEC":     "tec",
}


def fetch_gtfs_operator(operator_slug: str, timestamp: int, token: str,
                        progress_cb=None):
    """Download and parse a GTFS parquet for any supported operator.

    Returns a native gtfs_parquet.Feed (Polars DataFrames).
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
        for chunk in r.iter_content(chunk_size=1 << 20):
            tmp.write(chunk)
            downloaded += len(chunk)
            if progress_cb and total:
                progress_cb(downloaded, total)
        tmp.close()
        feed = read_parquet(tmp.name)
    finally:
        os.unlink(tmp.name)
    return feed
