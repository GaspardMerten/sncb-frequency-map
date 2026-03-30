"""Station reachability analysis using time-expanded BFS over GTFS timetable.

For each station, computes which other stations are reachable within a given
time budget (in hours), considering transfers. Uses a RAPTOR-lite approach:
build a timetable graph of (station, departure_time) -> (station, arrival_time)
edges, then BFS with time constraints.
"""

import pandas as pd
import numpy as np
from collections import defaultdict

from .geo import get_province, PROVINCE_TO_REGION


def _parse_gtfs_time_to_minutes(time_str: str) -> int:
    """Convert GTFS time string (HH:MM:SS, can be >24h) to minutes since midnight."""
    try:
        parts = str(time_str).split(":")
        return int(parts[0]) * 60 + int(parts[1])
    except Exception:
        return -1


def build_timetable_graph(gtfs: dict, service_ids: set[str],
                           hour_filter: tuple | None = None) -> dict:
    """Build a timetable graph from GTFS data.

    Returns:
        connections: list of (dep_station, arr_station, dep_min, arr_min, trip_id)
            sorted by dep_min.
        station_departures: dict station_id -> sorted list of (dep_min, arr_station, arr_min, trip_id)
    """
    trips = gtfs["trips"]
    stop_times = gtfs["stop_times"].copy()
    stops = gtfs["stops"]

    # Map stops to parent stations
    stop_to_station = {}
    for _, row in stops.iterrows():
        sid = str(row["stop_id"]).strip()
        parent = str(row.get("parent_station", "")).strip()
        stop_to_station[sid] = parent if parent else sid

    active_trip_ids = set(trips.loc[trips["service_id"].isin(service_ids), "trip_id"])
    st_f = stop_times[stop_times["trip_id"].isin(active_trip_ids)].copy()
    st_f["stop_sequence"] = pd.to_numeric(st_f["stop_sequence"], errors="coerce")
    st_f = st_f.sort_values(["trip_id", "stop_sequence"])

    # Parse times to minutes
    st_f["dep_min"] = st_f["departure_time"].apply(_parse_gtfs_time_to_minutes)
    st_f["arr_min"] = st_f["arrival_time"].apply(_parse_gtfs_time_to_minutes)
    st_f["station_id"] = st_f["stop_id"].map(stop_to_station).fillna(st_f["stop_id"])

    # Build connections: consecutive stops within each trip
    st_f["next_station"] = st_f.groupby("trip_id")["station_id"].shift(-1)
    st_f["next_arr_min"] = st_f.groupby("trip_id")["arr_min"].shift(-1)

    pairs = st_f.dropna(subset=["next_station"]).copy()
    pairs = pairs[pairs["station_id"] != pairs["next_station"]]
    pairs = pairs[pairs["dep_min"] >= 0]
    pairs["next_arr_min"] = pairs["next_arr_min"].astype(int)

    if hour_filter:
        h_start, h_end = hour_filter
        pairs = pairs[(pairs["dep_min"] >= h_start * 60) & (pairs["dep_min"] < h_end * 60)]

    # Build station_departures index for fast BFS
    station_departures = defaultdict(list)
    for _, row in pairs.iterrows():
        station_departures[row["station_id"]].append((
            int(row["dep_min"]),
            row["next_station"],
            int(row["next_arr_min"]),
            row["trip_id"],
        ))

    # Sort each station's departures by time
    for sid in station_departures:
        station_departures[sid].sort(key=lambda x: x[0])

    return dict(station_departures)


def compute_reachability_single(station_id: str, station_departures: dict,
                                 max_minutes: float, transfer_penalty_min: int = 5,
                                 departure_hour: int = 8) -> dict[str, dict]:
    """BFS reachability from a single station within max_minutes.

    Explores all departures from departure_hour (default 8:00), considering
    transfers with a minimum transfer time penalty.

    Returns: dict of reachable_station_id -> {
        'travel_time': minutes, 'transfers': int, 'path': list of station_ids
    }
    """
    start_min = departure_hour * 60
    deadline = start_min + max_minutes

    # best_arrival[station] = earliest arrival time in minutes
    best_arrival = {station_id: start_min}
    # For result tracking
    result = {}

    # Priority queue: (current_time, current_station, n_transfers, path)
    # Use a simple BFS with time ordering
    import heapq
    queue = [(start_min, station_id, 0, [station_id])]

    while queue:
        current_time, current_station, n_transfers, path = heapq.heappop(queue)

        # Skip if we already found a better route to this station
        if current_time > best_arrival.get(current_station, float("inf")):
            continue

        if current_time > deadline:
            continue

        # Get departures from current station after current_time (+ transfer penalty if not origin)
        earliest_dep = current_time
        if current_station != station_id or n_transfers > 0:
            earliest_dep = current_time + transfer_penalty_min

        departures = station_departures.get(current_station, [])

        # Binary search for first departure >= earliest_dep
        lo, hi = 0, len(departures)
        while lo < hi:
            mid = (lo + hi) // 2
            if departures[mid][0] < earliest_dep:
                lo = mid + 1
            else:
                hi = mid

        # Track which trip_ids we've already boarded from this station to avoid duplicates
        seen_next = set()
        for idx in range(lo, len(departures)):
            dep_min, next_station, arr_min, trip_id = departures[idx]

            if dep_min > deadline:
                break
            if arr_min > deadline:
                continue
            if next_station in seen_next:
                continue
            seen_next.add(next_station)

            # Check if this is a better arrival
            if arr_min < best_arrival.get(next_station, float("inf")):
                best_arrival[next_station] = arr_min
                new_path = path + [next_station]
                travel_time = arr_min - start_min

                # Record result
                if next_station != station_id:
                    result[next_station] = {
                        "travel_time": travel_time,
                        "transfers": n_transfers,
                        "path": new_path,
                    }

                heapq.heappush(queue, (arr_min, next_station, n_transfers + 1, new_path))

    return result


def compute_all_reachability(station_ids: list[str], station_departures: dict,
                              max_hours: float, stop_lookup: dict,
                              prov_geo: dict,
                              transfer_penalty_min: int = 5,
                              departure_hour: int = 8) -> pd.DataFrame:
    """Compute reachability for all stations.

    Returns DataFrame with columns:
        station_id, station_name, lat, lon, reachable_count, avg_travel_time,
        province, region
    """
    max_minutes = max_hours * 60
    rows = []

    for sid in station_ids:
        info = stop_lookup.get(sid)
        if not info:
            continue

        reachable = compute_reachability_single(
            sid, station_departures, max_minutes,
            transfer_penalty_min=transfer_penalty_min,
            departure_hour=departure_hour,
        )

        n_reachable = len(reachable)
        avg_time = 0.0
        if reachable:
            avg_time = sum(r["travel_time"] for r in reachable.values()) / n_reachable

        province = get_province(info["lat"], info["lon"], prov_geo)
        region = PROVINCE_TO_REGION.get(province, "Unknown") if province else "Unknown"

        rows.append({
            "station_id": sid,
            "station_name": info["name"],
            "lat": info["lat"],
            "lon": info["lon"],
            "reachable_count": n_reachable,
            "avg_travel_time": round(avg_time, 1),
            "province": province or "Unknown",
            "region": region,
        })

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("reachable_count", ascending=False).reset_index(drop=True)
    return df
