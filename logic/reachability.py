"""Station reachability analysis using time-expanded BFS over GTFS timetable.

For each station, computes which other stations are reachable within a given
time budget (in hours), considering transfers. Uses a RAPTOR-lite approach:
build a timetable graph of (station, departure_time) -> (station, arrival_time)
edges, then BFS with time constraints.
"""

import heapq
import pandas as pd
import numpy as np
import gtfs_kit as gk
from collections import defaultdict

from .geo import get_province, haversine_km, PROVINCE_TO_REGION


def _vectorized_time_to_minutes(series: pd.Series) -> np.ndarray:
    """Convert GTFS time strings (HH:MM:SS) to minutes, vectorized."""
    parts = series.str.split(":", n=2, expand=True)
    hours = pd.to_numeric(parts[0], errors="coerce").fillna(-1)
    minutes = pd.to_numeric(parts[1], errors="coerce").fillna(0)
    return (hours * 60 + minutes).astype(int).values


def build_timetable_graph(feed: gk.Feed, service_ids: set[str],
                           hour_filter: tuple | None = None) -> dict:
    """Build a timetable graph from GTFS data.

    Returns:
        station_departures: dict station_id -> sorted list of (dep_min, arr_station, arr_min, trip_id)
    """
    trips = feed.trips
    stop_times = feed.stop_times
    stops = feed.stops

    from .gtfs import _build_stop_to_station
    stop_to_station = _build_stop_to_station(stops)

    active_trip_ids = set(trips.loc[trips["service_id"].isin(service_ids), "trip_id"])
    st_f = stop_times[stop_times["trip_id"].isin(active_trip_ids)].copy()
    st_f = st_f.sort_values(["trip_id", "stop_sequence"])

    st_f["dep_min"] = _vectorized_time_to_minutes(st_f["departure_time"])
    st_f["arr_min"] = _vectorized_time_to_minutes(st_f["arrival_time"])
    st_f["station_id"] = st_f["stop_id"].map(stop_to_station).fillna(st_f["stop_id"])

    st_f["next_station"] = st_f.groupby("trip_id")["station_id"].shift(-1)
    st_f["next_arr_min"] = st_f.groupby("trip_id")["arr_min"].shift(-1)

    pairs = st_f.dropna(subset=["next_station"])
    pairs = pairs[(pairs["station_id"] != pairs["next_station"]) & (pairs["dep_min"] >= 0)]

    if hour_filter:
        h_start, h_end = hour_filter
        pairs = pairs[(pairs["dep_min"] >= h_start * 60) & (pairs["dep_min"] < h_end * 60)]

    dep_mins = pairs["dep_min"].astype(int).values
    next_arr_mins = pairs["next_arr_min"].astype(int).values
    station_ids = pairs["station_id"].values
    next_stations = pairs["next_station"].values
    trip_ids = pairs["trip_id"].values

    station_departures = defaultdict(list)
    for i in range(len(dep_mins)):
        station_departures[station_ids[i]].append((
            dep_mins[i], next_stations[i], next_arr_mins[i], trip_ids[i],
        ))

    for sid in station_departures:
        station_departures[sid].sort(key=lambda x: x[0])

    return dict(station_departures)


def _bfs_single(station_id: str, station_departures: dict,
                max_minutes: float, start_min: int,
                stop_lookup: dict | None = None,
                max_transfers: int | None = None,
                transfer_penalty_min: int = 5) -> dict[str, dict]:
    """Run BFS reachability from a single station starting at start_min.

    Tracks the current trip_id so that continuing on the same train does not
    count as a transfer and does not incur a transfer penalty.
    """
    deadline = start_min + max_minutes

    best_arrival = {station_id: start_min}
    result = {}
    # State: (current_time, current_station, n_transfers, path, current_trip_id)
    queue = [(start_min, station_id, 0, [station_id], None)]

    while queue:
        current_time, current_station, n_transfers, path, current_trip = heapq.heappop(queue)

        if current_time > best_arrival.get(current_station, float("inf")):
            continue
        if current_time > deadline:
            continue
        if max_transfers is not None and n_transfers > max_transfers:
            continue

        departures = station_departures.get(current_station, [])

        # Binary search for departures at or after current_time
        lo, hi = 0, len(departures)
        while lo < hi:
            mid = (lo + hi) // 2
            if departures[mid][0] < current_time:
                lo = mid + 1
            else:
                hi = mid

        seen_next_transfer = set()
        for idx in range(lo, len(departures)):
            dep_min, next_station, arr_min, trip_id = departures[idx]

            if dep_min > deadline:
                break
            if arr_min > deadline:
                continue

            is_same_trip = current_trip is not None and trip_id == current_trip

            if is_same_trip:
                # Continuing on the same train: no penalty, no transfer increment
                new_transfers = n_transfers
            else:
                # Initial boarding or transfer to a different train
                is_initial = current_station == station_id and current_trip is None
                if not is_initial:
                    # Transfer: enforce minimum connection time
                    if dep_min < current_time + transfer_penalty_min:
                        continue
                    new_transfers = n_transfers + 1
                    if max_transfers is not None and new_transfers > max_transfers:
                        continue
                else:
                    # First boarding at origin: no penalty
                    new_transfers = n_transfers

                if next_station in seen_next_transfer:
                    continue
                seen_next_transfer.add(next_station)

            if arr_min < best_arrival.get(next_station, float("inf")):
                best_arrival[next_station] = arr_min
                new_path = path + [next_station]
                travel_time = arr_min - start_min

                if next_station != station_id:
                    entry = {
                        "travel_time": travel_time,
                        "transfers": new_transfers,
                        "path": new_path,
                    }
                    if stop_lookup is not None:
                        entry["distance_km"] = _path_distance_km(new_path, stop_lookup)
                    result[next_station] = entry

                heapq.heappush(queue, (arr_min, next_station, new_transfers, new_path, trip_id))

    return result


def compute_reachability_single(station_id: str, station_departures: dict,
                                 max_minutes: float,
                                 stop_lookup: dict | None = None,
                                 max_transfers: int | None = None,
                                 transfer_penalty_min: int = 5,
                                 departure_window: tuple[int, int] = (8, 9)) -> dict[str, dict]:
    """BFS reachability from a single station across a departure window.

    Runs BFS for each hour in the window and merges results, keeping the
    best (shortest travel time) route to each reachable station.

    Args:
        departure_window: (start_hour, end_hour) — BFS runs once per hour.
    """
    merged: dict[str, dict] = {}

    for hour in range(departure_window[0], departure_window[1]):
        start_min = hour * 60
        reachable = _bfs_single(
            station_id, station_departures, max_minutes, start_min,
            stop_lookup=stop_lookup,
            max_transfers=max_transfers,
            transfer_penalty_min=transfer_penalty_min,
        )
        for dest_id, info in reachable.items():
            if dest_id not in merged or info["travel_time"] < merged[dest_id]["travel_time"]:
                merged[dest_id] = info

    return merged


def _path_distance_km(path: list[str], stop_lookup: dict) -> float:
    """Compute total haversine distance along a path of station IDs."""
    total = 0.0
    for i in range(len(path) - 1):
        a = stop_lookup.get(path[i])
        b = stop_lookup.get(path[i + 1])
        if a and b:
            total += haversine_km(a["lat"], a["lon"], b["lat"], b["lon"])
    return total


def compute_all_reachability(station_ids: list[str], station_departures: dict,
                              max_hours: float, stop_lookup: dict,
                              prov_geo: dict,
                              transfer_penalty_min: int = 5,
                              departure_window: tuple[int, int] = (8, 9),
                              max_transfers: int | None = None,
                              progress_callback=None) -> pd.DataFrame:
    """Compute reachability for all stations.

    Args:
        departure_window: (start_hour, end_hour) range to sample departures.
        progress_callback: Optional callable(fraction) for progress updates.
    """
    max_minutes = max_hours * 60
    rows = []
    total = len(station_ids)

    for idx, sid in enumerate(station_ids):
        info = stop_lookup.get(sid)
        if not info:
            continue

        reachable = compute_reachability_single(
            sid, station_departures, max_minutes,
            max_transfers=max_transfers,
            transfer_penalty_min=transfer_penalty_min,
            departure_window=departure_window,
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

        if progress_callback and idx % 10 == 0:
            progress_callback((idx + 1) / total)

    if progress_callback:
        progress_callback(1.0)

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("reachable_count", ascending=False).reset_index(drop=True)
    return df


def compute_direct_frequency(station_id: str, station_departures: dict) -> float:
    """Average hourly frequency of direct (no-transfer) destinations from a station.

    Counts unique trips departing between 6h and 22h (16h window).
    Returns total direct departures / 16.
    """
    departures = station_departures.get(station_id, [])
    count = sum(1 for dep_min, _, _, _ in departures if 360 <= dep_min < 1320)
    return count / 16.0


def compute_connectivity_metrics(station_ids: list[str],
                                  station_departures: dict,
                                  stop_lookup: dict,
                                  prov_geo: dict,
                                  max_minutes: float = 120,
                                  max_transfers: int = 2,
                                  transfer_penalty_min: int = 5,
                                  departure_window: tuple[int, int] = (8, 9),
                                  progress_callback=None) -> pd.DataFrame:
    """Compute per-station connectivity metrics A, B, C.

    A: Number of destinations reachable within max_minutes with <= max_transfers.
    B: Average hourly direct frequency (trains 6h-22h / 16).
    C: Mean distance (km) across all reachable destinations.
    """
    rows = []
    total = len(station_ids)

    for idx, sid in enumerate(station_ids):
        info = stop_lookup.get(sid)
        if not info:
            continue

        reachable = compute_reachability_single(
            sid, station_departures, max_minutes,
            stop_lookup=stop_lookup,
            max_transfers=max_transfers,
            transfer_penalty_min=transfer_penalty_min,
            departure_window=departure_window,
        )

        a_count = len(reachable)
        b_freq = compute_direct_frequency(sid, station_departures)
        c_dist = 0.0
        if reachable:
            distances = [r["distance_km"] for r in reachable.values() if r.get("distance_km")]
            if distances:
                c_dist = sum(distances) / len(distances)

        province = get_province(info["lat"], info["lon"], prov_geo)
        region = PROVINCE_TO_REGION.get(province, "Unknown") if province else "Unknown"

        rows.append({
            "station_id": sid,
            "station_name": info["name"],
            "lat": info["lat"],
            "lon": info["lon"],
            "A_reachable": a_count,
            "B_direct_freq": round(b_freq, 2),
            "C_avg_distance_km": round(c_dist, 1),
            "province": province or "Unknown",
            "region": region,
        })

        if progress_callback and idx % 10 == 0:
            progress_callback((idx + 1) / total)

    if progress_callback:
        progress_callback(1.0)

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("A_reachable", ascending=False).reset_index(drop=True)
    return df
