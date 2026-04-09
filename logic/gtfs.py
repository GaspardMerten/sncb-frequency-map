"""GTFS data processing: service filtering, frequency computation, stop lookups.

Delegates heavy lifting to gtfs_parquet.ops.graph (Polars-native) and provides
thin adapters for the rest of the codebase.
"""

from collections import defaultdict
from datetime import date

from gtfs_parquet.ops.graph import (
    build_stop_lookup as _lib_build_stop_lookup,
    compute_segment_frequencies as _lib_compute_segment_frequencies,
    get_service_day_counts as _lib_get_service_day_counts,
    served_stations as _lib_served_stations,
)

from .geo import is_in_belgium


def get_service_day_counts(feed, target_dates: list[date]) -> dict[str, int]:
    """Count how many target dates each service_id is active on."""
    return _lib_get_service_day_counts(feed, target_dates)


def get_active_service_ids(feed, target_dates: list[date]) -> set[str]:
    """Determine which GTFS service_ids are active on any of the target dates."""
    return set(get_service_day_counts(feed, target_dates).keys())


def build_stop_lookup(feed) -> dict:
    """Build lookup: station_id -> {name, lat, lon}, filtered to Belgium.

    Uses parent_station resolution from the library, then renames keys
    and filters to Belgian coordinates.
    """
    raw = _lib_build_stop_lookup(feed, parent_stations=True)
    lookup = {}
    for sid, info in raw.items():
        lat = info.get("stop_lat")
        lon = info.get("stop_lon")
        if lat is None or lon is None or not is_in_belgium(lat, lon):
            continue
        lookup[sid] = {
            "name": info.get("stop_name", ""),
            "lat": float(lat),
            "lon": float(lon),
        }
    return lookup


def compute_segment_frequencies(feed, service_ids: set[str],
                                 hour_filter: tuple | None = None,
                                 day_count: int = 1,
                                 service_day_counts: dict[str, int] | None = None,
                                 ) -> dict[tuple[str, str], float]:
    """Compute average daily frequency per consecutive stop pair.

    The library computes weighted frequencies natively in Polars.
    We normalise by day_count afterward if needed.
    """
    sids_list = list(service_ids)
    raw = _lib_compute_segment_frequencies(
        feed, sids_list, hour_filter, service_day_counts,
    )
    if day_count <= 1:
        return raw
    divisor = max(day_count, 1)
    return {k: v / divisor for k, v in raw.items()}


def compute_station_frequencies(segment_freqs: dict[tuple[str, str], float],
                                 stop_lookup: dict | None = None,
                                 ) -> dict[str, float]:
    """Sum segment frequencies touching each station."""
    station_freq: dict[str, float] = defaultdict(float)
    for (a, b), freq in segment_freqs.items():
        if stop_lookup is None or a in stop_lookup:
            station_freq[a] += freq
        if stop_lookup is None or b in stop_lookup:
            station_freq[b] += freq
    return dict(station_freq)


def compute_served_stations(feed, service_ids: set[str],
                            hour_filter: tuple | None = None,
                            ) -> set[str]:
    """Return station IDs where at least one train actually stops."""
    return _lib_served_stations(feed, list(service_ids), hour_filter)
