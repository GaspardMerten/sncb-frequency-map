"""Geocoding via OpenStreetMap Nominatim (no API key needed)."""

import requests
from functools import lru_cache

_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
_USER_AGENT = "MobilityTwinExplorer/1.0 (ULB research)"


@lru_cache(maxsize=256)
def geocode_address(address: str) -> dict | None:
    """Geocode an address string to {lat, lon, display_name}.

    Biased towards Belgium. Returns None if no result found.
    """
    params = {
        "q": address,
        "format": "jsonv2",
        "limit": 1,
        "countrycodes": "be",
        "addressdetails": 0,
    }
    try:
        r = requests.get(
            _NOMINATIM_URL,
            params=params,
            headers={"User-Agent": _USER_AGENT},
            timeout=10,
        )
        r.raise_for_status()
        results = r.json()
    except Exception:
        return None

    if not results:
        return None

    hit = results[0]
    return {
        "lat": float(hit["lat"]),
        "lon": float(hit["lon"]),
        "display_name": hit.get("display_name", address),
    }


@lru_cache(maxsize=256)
def geocode_suggestions(query: str, limit: int = 5) -> list[dict]:
    """Return up to *limit* geocoding suggestions for autocomplete."""
    if not query or len(query) < 3:
        return []
    params = {
        "q": query,
        "format": "jsonv2",
        "limit": limit,
        "countrycodes": "be",
        "addressdetails": 0,
    }
    try:
        r = requests.get(
            _NOMINATIM_URL,
            params=params,
            headers={"User-Agent": _USER_AGENT},
            timeout=10,
        )
        r.raise_for_status()
        return [
            {"lat": float(h["lat"]), "lon": float(h["lon"]),
             "display_name": h.get("display_name", query)}
            for h in r.json()
        ]
    except Exception:
        return []
