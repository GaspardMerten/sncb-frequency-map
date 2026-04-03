"""Station reachability analysis using time-expanded BFS over GTFS timetable.

For each station, computes which other stations are reachable within a given
time budget (in hours), considering transfers. Uses a RAPTOR-lite approach:
build a timetable graph of (station, departure_time) -> (station, arrival_time)
edges, then BFS with time constraints.
"""

import bisect
import heapq
import pandas as pd
import numpy as np
from collections import defaultdict

from .geo import get_province, haversine_km, PROVINCE_TO_REGION


def _vectorized_time_to_minutes(series: pd.Series) -> np.ndarray:
    """Convert GTFS time values (timedelta or HH:MM:SS strings) to minutes, vectorized."""
    if pd.api.types.is_timedelta64_dtype(series):
        return (series.dt.total_seconds() / 60).fillna(-1).astype(int).values
    parts = series.astype(str).str.split(":", n=2, expand=True)
    hours = pd.to_numeric(parts[0], errors="coerce").fillna(-1)
    minutes = pd.to_numeric(parts[1], errors="coerce").fillna(0)
    return (hours * 60 + minutes).astype(int).values


def build_timetable_graph(feed, service_ids: set[str],
                           hour_filter: tuple | None = None) -> dict:
    """Build a timetable graph from GTFS data.

    Only includes stops where the train actually stops for passengers
    (excludes pass-throughs where pickup_type=1 AND drop_off_type=1).

    Returns:
        station_departures: dict station_id -> sorted list of (dep_min, arr_station, arr_min, trip_id)
    """
    trips = feed.trips
    stop_times = feed.stop_times
    stops = feed.stops

    from .gtfs import _get_stop_to_station, _is_pass_through
    stop_to_station = _get_stop_to_station(stops)

    active_trip_ids = set(trips.loc[trips["service_id"].isin(service_ids), "trip_id"])
    st_f = stop_times[stop_times["trip_id"].isin(active_trip_ids)].copy()
    st_f = st_f.sort_values(["trip_id", "stop_sequence"])

    # Remove pass-through stops: passengers can't board or alight there
    st_f = st_f[~_is_pass_through(st_f)]

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


def _precompute_dep_times(station_departures: dict) -> dict:
    """Pre-extract departure times as lists for fast bisect lookups."""
    return {sid: [d[0] for d in deps] for sid, deps in station_departures.items()}


def _precompute_arr_times(reverse_departures: dict) -> dict:
    """Pre-extract arrival times as lists for fast bisect lookups."""
    return {sid: [d[0] for d in deps] for sid, deps in reverse_departures.items()}


def build_reverse_timetable_graph(station_departures: dict) -> dict:
    """Build a reverse timetable graph for backward-time BFS.

    The forward graph has: station -> [(dep_min, next_station, arr_min, trip_id), ...]
    The reverse graph has: station -> [(arr_min, prev_station, dep_min, trip_id), ...]
    sorted by arr_min DESCENDING (latest first) for backward search.

    This lets us answer "from which stations can you reach station X by time T?"
    by running a backward BFS from the destination.
    """
    reverse: dict[str, list] = defaultdict(list)

    for station, departures in station_departures.items():
        for dep_min, next_station, arr_min, trip_id in departures:
            # In reverse: arriving at next_station means we came from station
            reverse[next_station].append((arr_min, station, dep_min, trip_id))

    # Sort by arr_min descending (we search backward in time)
    for sid in reverse:
        reverse[sid].sort(key=lambda x: x[0], reverse=True)

    return dict(reverse)


def _bfs_reverse(station_id: str, reverse_departures: dict,
                 max_minutes: float, arrive_by: int,
                 max_transfers: int | None = None,
                 transfer_penalty_min: int = 5,
                 _arr_times: dict | None = None) -> dict[str, dict]:
    """Run backward BFS: find which stations can reach station_id by arrive_by.

    Uses the reverse timetable graph. Searches backward in time from the
    destination, finding the latest possible departures from each origin.
    """
    earliest_dep = arrive_by - max_minutes

    # best_departure[station] = latest time we can depart from station
    best_departure = {station_id: arrive_by}
    result = {}
    # State: (-current_time for max-heap, station, n_transfers, current_trip_id)
    # We use negative time because heapq is a min-heap and we want latest first
    queue = [(-arrive_by, station_id, 0, None)]

    while queue:
        neg_time, current_station, n_transfers, current_trip = heapq.heappop(queue)
        current_time = -neg_time

        if current_time < best_departure.get(current_station, float("-inf")):
            continue
        if current_time < earliest_dep:
            continue
        if max_transfers is not None and n_transfers > max_transfers:
            continue

        arrivals = reverse_departures.get(current_station, [])

        # Binary search for arrivals at or before current_time (list is descending)
        if _arr_times is not None:
            atimes = _arr_times.get(current_station, [])
        else:
            atimes = [a[0] for a in arrivals]
        # atimes is descending; find first index where value <= current_time
        # bisect_left on negated values: find first -val >= -current_time
        lo = bisect.bisect_left(atimes, -current_time, key=lambda x: -x)

        seen_prev_transfer = set()
        for idx in range(lo, len(arrivals)):
            arr_min, prev_station, dep_min, trip_id = arrivals[idx]

            if arr_min > current_time:
                continue
            if dep_min < earliest_dep:
                break

            is_same_trip = current_trip is not None and trip_id == current_trip

            if is_same_trip:
                new_transfers = n_transfers
            else:
                is_initial = current_station == station_id and current_trip is None
                if not is_initial:
                    # Transfer: the train must arrive before we need to depart
                    if arr_min > current_time - transfer_penalty_min:
                        continue
                    new_transfers = n_transfers + 1
                    if max_transfers is not None and new_transfers > max_transfers:
                        continue
                else:
                    new_transfers = n_transfers

                if prev_station in seen_prev_transfer:
                    continue
                seen_prev_transfer.add(prev_station)

            if dep_min > best_departure.get(prev_station, float("-inf")):
                best_departure[prev_station] = dep_min
                travel_time = arrive_by - dep_min

                if prev_station != station_id:
                    result[prev_station] = {
                        "travel_time": travel_time,
                        "transfers": new_transfers,
                    }

                heapq.heappush(queue, (-dep_min, prev_station, new_transfers, trip_id))

    return result


def compute_reachability_to_dest(station_id: str, reverse_departures: dict,
                                  max_minutes: float,
                                  max_transfers: int | None = None,
                                  transfer_penalty_min: int = 5,
                                  arrival_window: tuple[int, int] = (8, 9)) -> dict[str, dict]:
    """Compute travel times FROM every station TO station_id.

    Uses reverse BFS across the arrival window, keeping the best (shortest)
    travel time from each origin.
    """
    merged: dict[str, dict] = {}
    _arr_times = _precompute_arr_times(reverse_departures)

    for arrive_by in range(arrival_window[0] * 60, arrival_window[1] * 60, 5):
        reachable = _bfs_reverse(
            station_id, reverse_departures, max_minutes, arrive_by,
            max_transfers=max_transfers,
            transfer_penalty_min=transfer_penalty_min,
            _arr_times=_arr_times,
        )
        for origin_id, info in reachable.items():
            if origin_id not in merged or info["travel_time"] < merged[origin_id]["travel_time"]:
                merged[origin_id] = info

    return merged


def _bfs_single(station_id: str, station_departures: dict,
                max_minutes: float, start_min: int,
                stop_lookup: dict | None = None,
                max_transfers: int | None = None,
                transfer_penalty_min: int = 5,
                _dep_times: dict | None = None) -> dict[str, dict]:
    """Run BFS reachability from a single station starting at start_min.

    Tracks the current trip_id so that continuing on the same train does not
    count as a transfer and does not incur a transfer penalty.
    Path tracking is only enabled when stop_lookup is provided (for distance).
    """
    deadline = start_min + max_minutes
    track_paths = stop_lookup is not None

    best_arrival = {station_id: start_min}
    result = {}
    # State: (current_time, current_station, n_transfers, current_trip_id)
    queue = [(start_min, station_id, 0, None)]
    if track_paths:
        parent = {}

    while queue:
        current_time, current_station, n_transfers, current_trip = heapq.heappop(queue)

        if current_time > best_arrival.get(current_station, float("inf")):
            continue
        if current_time > deadline:
            continue
        if max_transfers is not None and n_transfers > max_transfers:
            continue

        departures = station_departures.get(current_station, [])

        # Binary search for departures at or after current_time
        if _dep_times is not None:
            dtimes = _dep_times.get(current_station, [])
        else:
            dtimes = [d[0] for d in departures]
        lo = bisect.bisect_left(dtimes, current_time)

        seen_next_transfer = set()
        for idx in range(lo, len(departures)):
            dep_min, next_station, arr_min, trip_id = departures[idx]

            if dep_min > deadline:
                break
            if arr_min > deadline:
                continue

            is_same_trip = current_trip is not None and trip_id == current_trip

            if is_same_trip:
                new_transfers = n_transfers
            else:
                is_initial = current_station == station_id and current_trip is None
                if not is_initial:
                    if dep_min < current_time + transfer_penalty_min:
                        continue
                    new_transfers = n_transfers + 1
                    if max_transfers is not None and new_transfers > max_transfers:
                        continue
                else:
                    new_transfers = n_transfers

                if next_station in seen_next_transfer:
                    continue
                seen_next_transfer.add(next_station)

            if arr_min < best_arrival.get(next_station, float("inf")):
                best_arrival[next_station] = arr_min
                travel_time = arr_min - start_min

                if track_paths:
                    parent[next_station] = current_station

                if next_station != station_id:
                    result[next_station] = {
                        "travel_time": travel_time,
                        "transfers": new_transfers,
                    }

                heapq.heappush(queue, (arr_min, next_station, new_transfers, trip_id))

    if track_paths:
        for dest_id, entry in result.items():
            path = _reconstruct_path(dest_id, parent, station_id)
            entry["path"] = path
            entry["distance_km"] = _path_distance_km(path, stop_lookup)

    return result


def _reconstruct_path(dest: str, parent: dict, origin: str) -> list[str]:
    """Reconstruct path from parent map."""
    path = [dest]
    current = dest
    while current in parent and current != origin:
        current = parent[current]
        path.append(current)
    path.reverse()
    return path


def compute_reachability_single(station_id: str, station_departures: dict,
                                 max_minutes: float,
                                 stop_lookup: dict | None = None,
                                 max_transfers: int | None = None,
                                 transfer_penalty_min: int = 5,
                                 departure_window: tuple[int, int] = (8, 9)) -> dict[str, dict]:
    """BFS reachability from a single station across a departure window.

    Runs BFS every 5 minutes in the window and merges results, keeping the
    best (shortest travel time) route to each reachable station.

    Args:
        departure_window: (start_hour, end_hour) — BFS runs every 5 minutes.
    """
    merged: dict[str, dict] = {}
    _dep_times = _precompute_dep_times(station_departures)

    for start_min in range(departure_window[0] * 60, departure_window[1] * 60, 5):
        reachable = _bfs_single(
            station_id, station_departures, max_minutes, start_min,
            stop_lookup=stop_lookup,
            max_transfers=max_transfers,
            transfer_penalty_min=transfer_penalty_min,
            _dep_times=_dep_times,
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


def _station_row(sid: str, stop_lookup: dict, prov_geo: dict, **extra) -> dict | None:
    """Build a common station row dict with geographic info. Returns None if station unknown."""
    info = stop_lookup.get(sid)
    if not info:
        return None
    province = get_province(info["lat"], info["lon"], prov_geo)
    region = PROVINCE_TO_REGION.get(province, "Unknown") if province else "Unknown"
    return {
        "station_id": sid,
        "station_name": info["name"],
        "lat": info["lat"],
        "lon": info["lon"],
        "province": province or "Unknown",
        "region": region,
        **extra,
    }


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
    _dep_times = _precompute_dep_times(station_departures)

    for idx, sid in enumerate(station_ids):
        reachable = compute_reachability_single(
            sid, station_departures, max_minutes,
            max_transfers=max_transfers,
            transfer_penalty_min=transfer_penalty_min,
            departure_window=departure_window,
        )

        n_reachable = len(reachable)
        avg_time = (sum(r["travel_time"] for r in reachable.values()) / n_reachable
                    if reachable else 0.0)

        row = _station_row(
            sid, stop_lookup, prov_geo,
            reachable_count=n_reachable,
            avg_travel_time=round(avg_time, 1),
        )
        if row:
            rows.append(row)

        if progress_callback and idx % 10 == 0:
            progress_callback((idx + 1) / total)

    if progress_callback:
        progress_callback(1.0)

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("reachable_count", ascending=False).reset_index(drop=True)
    return df


def compute_direct_frequency(station_id: str, station_departures: dict,
                              n_feeds: int = 1) -> float:
    """Average hourly frequency of direct (no-transfer) destinations from a station.

    Counts unique trips departing between 6h and 22h (16h window).
    Normalises by n_feeds (number of GTFS feeds accumulated) to avoid
    inflating the count when data spans multiple months.
    Returns total direct departures / 16 / n_feeds.
    """
    departures = station_departures.get(station_id, [])
    count = sum(1 for dep_min, _, _, _ in departures if 360 <= dep_min < 1320)
    return count / 16.0 / max(n_feeds, 1)


# Station size thresholds (trains/hour)
_SIZE_THRESHOLDS = [(4, "Small"), (10, "Medium")]


def station_size(freq_per_hour: float) -> str:
    """Classify a station as Small / Medium / Big based on direct trains/hour."""
    for threshold, label in _SIZE_THRESHOLDS:
        if freq_per_hour < threshold:
            return label
    return "Big"


def _cardinal_reach(origin_id: str, reachable: dict, stop_lookup: dict) -> float:
    """Sum of the maximum reachable distance in each cardinal direction.

    For every reachable station, determine which quadrant (N/E/S/W) it falls
    into relative to the origin using latitude/longitude differences, then
    keep the farthest station per quadrant and return the sum of those four
    maximum distances.
    """
    origin = stop_lookup.get(origin_id)
    if not origin:
        return 0.0
    o_lat, o_lon = origin["lat"], origin["lon"]

    # max distance per quadrant: N, E, S, W
    best = {"N": 0.0, "E": 0.0, "S": 0.0, "W": 0.0}

    for dest_id, info in reachable.items():
        d_km = info.get("distance_km", 0)
        if not d_km:
            continue
        dest = stop_lookup.get(dest_id)
        if not dest:
            continue
        dlat = dest["lat"] - o_lat
        dlon = dest["lon"] - o_lon
        # Dominant axis decides the quadrant
        if abs(dlat) >= abs(dlon):
            direction = "N" if dlat >= 0 else "S"
        else:
            direction = "E" if dlon >= 0 else "W"
        if d_km > best[direction]:
            best[direction] = d_km

    return sum(best.values())


def compute_connectivity_metrics(station_ids: list[str],
                                  station_departures: dict,
                                  stop_lookup: dict,
                                  prov_geo: dict,
                                  max_minutes: float = 120,
                                  max_transfers: int = 2,
                                  transfer_penalty_min: int = 5,
                                  departure_window: tuple[int, int] = (8, 9),
                                  n_feeds: int = 1,
                                  progress_callback=None) -> pd.DataFrame:
    """Compute per-station connectivity metrics A, B, C.

    A: Number of destinations reachable within max_minutes with <= max_transfers.
    B: Average hourly direct frequency (trains 6h-22h / 16).
    C: Sum of max reach (km) in each cardinal direction (N + E + S + W).
    """
    rows = []
    total = len(station_ids)
    _dep_times = _precompute_dep_times(station_departures)

    for idx, sid in enumerate(station_ids):
        reachable = compute_reachability_single(
            sid, station_departures, max_minutes,
            stop_lookup=stop_lookup,
            max_transfers=max_transfers,
            transfer_penalty_min=transfer_penalty_min,
            departure_window=departure_window,
        )

        a_count = len(reachable)
        b_freq = compute_direct_frequency(sid, station_departures, n_feeds=n_feeds)
        c_reach = _cardinal_reach(sid, reachable, stop_lookup)

        row = _station_row(
            sid, stop_lookup, prov_geo,
            A_reachable=a_count,
            B_direct_freq=round(b_freq, 2),
            C_reach_km=round(c_reach, 1),
            station_size=station_size(b_freq),
        )
        if row:
            rows.append(row)

        if progress_callback and idx % 10 == 0:
            progress_callback((idx + 1) / total)

    if progress_callback:
        progress_callback(1.0)

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("A_reachable", ascending=False).reset_index(drop=True)
    return df
