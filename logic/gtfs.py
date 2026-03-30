"""GTFS data processing: service filtering, frequency computation, stop lookups."""

import pandas as pd
import numpy as np
from collections import defaultdict
from datetime import date

from .geo import is_in_belgium


def get_active_service_ids(gtfs: dict, target_dates: list[date]) -> set[str]:
    """Determine which GTFS service_ids are active on any of the target dates."""
    counts = get_service_day_counts(gtfs, target_dates)
    return set(counts.keys())


def get_service_day_counts(gtfs: dict, target_dates: list[date]) -> dict[str, int]:
    """Count how many target dates each service_id is active on."""
    day_names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    counts: dict[str, int] = defaultdict(int)
    ts_dates = {pd.Timestamp(d) for d in target_dates}

    if "calendar" in gtfs:
        cal = gtfs["calendar"].copy()
        cal["start_date"] = pd.to_datetime(cal["start_date"], format="%Y%m%d")
        cal["end_date"] = pd.to_datetime(cal["end_date"], format="%Y%m%d")
        for d in target_dates:
            ts = pd.Timestamp(d)
            mask = (cal["start_date"] <= ts) & (cal["end_date"] >= ts)
            day_col = day_names[d.weekday()]
            if day_col in cal.columns:
                for sid in cal.loc[mask & (cal[day_col] == "1"), "service_id"]:
                    counts[sid] += 1

    if "calendar_dates" in gtfs:
        cd = gtfs["calendar_dates"].copy()
        cd["date"] = pd.to_datetime(cd["date"], format="%Y%m%d")
        cd = cd[cd["date"].isin(ts_dates)]
        for sid in cd[cd["exception_type"] == "1"]["service_id"]:
            counts[sid] += 1
        for sid in cd[cd["exception_type"] == "2"]["service_id"]:
            counts[sid] -= 1
        # Remove services that ended up with zero or negative counts
        counts = {k: v for k, v in counts.items() if v > 0}

    return dict(counts)


def build_stop_lookup(gtfs: dict) -> dict:
    """Build lookup: station_id -> {name, lat, lon}, grouping by parent_station."""
    stops = gtfs["stops"].copy()
    stops["stop_lat"] = pd.to_numeric(stops["stop_lat"], errors="coerce")
    stops["stop_lon"] = pd.to_numeric(stops["stop_lon"], errors="coerce")

    lookup = {}
    for _, row in stops.iterrows():
        sid = str(row.get("stop_id", "")).strip()
        parent = str(row.get("parent_station", "")).strip()
        key = parent if parent else sid

        lat, lon = row["stop_lat"], row["stop_lon"]
        if pd.isna(lat) or pd.isna(lon) or not is_in_belgium(lat, lon):
            continue
        if key not in lookup:
            lookup[key] = {"name": row.get("stop_name", key), "lat": float(lat), "lon": float(lon)}
    return lookup


def compute_segment_frequencies(gtfs: dict, service_ids: set[str],
                                 hour_filter: tuple | None = None,
                                 day_count: int = 1,
                                 service_day_counts: dict[str, int] | None = None,
                                 ) -> dict[tuple[str, str], float]:
    """Compute average daily frequency per consecutive stop pair (vectorized).

    When service_day_counts is provided, each trip is weighted by the number of
    target dates its service is active on, giving a correct daily average.
    """
    trips = gtfs["trips"]
    stop_times = gtfs["stop_times"].copy()
    stops = gtfs["stops"]

    # Build stop -> parent station mapping
    stop_to_station = dict(zip(
        stops["stop_id"].str.strip(),
        stops.apply(
            lambda r: str(r.get("parent_station", "")).strip() or str(r["stop_id"]).strip(),
            axis=1
        )
    ))

    # Filter to active trips and attach service_id
    active_trips = trips.loc[trips["service_id"].isin(service_ids), ["trip_id", "service_id"]]
    active_trip_ids = set(active_trips["trip_id"])
    trip_to_service = dict(zip(active_trips["trip_id"], active_trips["service_id"]))

    st_f = stop_times[stop_times["trip_id"].isin(active_trip_ids)].copy()
    st_f["stop_sequence"] = pd.to_numeric(st_f["stop_sequence"], errors="coerce")
    st_f = st_f.sort_values(["trip_id", "stop_sequence"])

    # Vectorized hour parsing
    st_f["hour"] = st_f["departure_time"].str.split(":").str[0].astype(float, errors="ignore")
    st_f["hour"] = pd.to_numeric(st_f["hour"], errors="coerce").fillna(-1).astype(int)

    # Map to parent stations
    st_f["station_id"] = st_f["stop_id"].map(stop_to_station).fillna(st_f["stop_id"])

    # Vectorized: shift within each trip to get consecutive pairs
    st_f["next_station"] = st_f.groupby("trip_id")["station_id"].shift(-1)
    st_f["next_trip"] = st_f.groupby("trip_id")["trip_id"].shift(-1)

    # Keep only rows where next stop is in the same trip and different station
    pairs = st_f.dropna(subset=["next_station"])
    pairs = pairs[pairs["station_id"] != pairs["next_station"]]

    # Apply hour filter
    if hour_filter:
        pairs = pairs[(pairs["hour"] >= hour_filter[0]) & (pairs["hour"] < hour_filter[1])]

    # Create sorted pair keys and count, weighting by active days
    s_a = pairs["station_id"].values
    s_b = pairs["next_station"].values
    trip_ids = pairs["trip_id"].values

    # Sort each pair alphabetically for consistent keys
    keys_a = np.where(s_a <= s_b, s_a, s_b)
    keys_b = np.where(s_a <= s_b, s_b, s_a)

    freq = defaultdict(float)
    if service_day_counts:
        for a, b, tid in zip(keys_a, keys_b, trip_ids):
            sid = trip_to_service.get(tid)
            weight = service_day_counts.get(sid, 1) if sid else 1
            freq[(a, b)] += weight
    else:
        for a, b in zip(keys_a, keys_b):
            freq[(a, b)] += 1

    return {k: v / max(day_count, 1) for k, v in freq.items() if v > 0}


def compute_station_frequencies(segment_freqs: dict[tuple[str, str], float]) -> dict[str, float]:
    """Sum segment frequencies touching each station."""
    station_freq = defaultdict(float)
    for (a, b), freq in segment_freqs.items():
        station_freq[a] += freq
        station_freq[b] += freq
    return dict(station_freq)