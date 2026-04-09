"""Multimodal timetable graph and door-to-door BFS.

Combines GTFS feeds from multiple operators (SNCB, De Lijn, STIB, TEC) into a
single timetable graph, then runs BFS from a geographic coordinate (address)
to compute travel time to every reachable stop, including walking first/last
mile.
"""

import bisect
import heapq
import numpy as np
from collections import defaultdict
from datetime import date

from gtfs_parquet.ops.graph import (
    build_stop_lookup as _lib_build_stop_lookup,
    build_timetable_graph as _lib_build_timetable_graph,
    get_service_day_counts as _lib_get_service_day_counts,
)

from .geo import haversine_km, is_in_belgium


# ---------------------------------------------------------------------------
# Walking speed & constants
# ---------------------------------------------------------------------------

WALK_SPEED_KMH = 4.5  # average walking speed
MAX_WALK_KM = 1.5     # max walking distance to reach a stop


def _walk_minutes(dist_km: float) -> float:
    """Walking time in minutes for a given distance in km."""
    return dist_km / WALK_SPEED_KMH * 60.0


# ---------------------------------------------------------------------------
# Multi-operator stop lookup
# ---------------------------------------------------------------------------

def build_multimodal_stop_lookup(feeds: dict) -> dict[str, dict]:
    """Build a unified stop lookup across all operators.

    Keys are prefixed: "SNCB:stop_id", "STIB:stop_id", etc.
    Values: {name, lat, lon, operator}.
    """
    lookup = {}
    for operator, feed in feeds.items():
        raw = _lib_build_stop_lookup(feed, parent_stations=True)
        prefix = f"{operator}:"
        for sid, info in raw.items():
            lat = info.get("stop_lat")
            lon = info.get("stop_lon")
            if lat is None or lon is None or not is_in_belgium(lat, lon):
                continue
            prefixed = f"{prefix}{sid}"
            if prefixed not in lookup:
                lookup[prefixed] = {
                    "name": info.get("stop_name", ""),
                    "lat": float(lat),
                    "lon": float(lon),
                    "operator": operator,
                }
    return lookup


# ---------------------------------------------------------------------------
# Multi-operator timetable graph
# ---------------------------------------------------------------------------

def get_active_service_ids(feed, target_dates: list[date]) -> set[str]:
    """Determine active service_ids for the given dates."""
    return set(_lib_get_service_day_counts(feed, target_dates).keys())


def build_multimodal_graph(feeds: dict,
                           service_ids_per_op: dict[str, set[str]],
                           hour_filter: tuple | None = None,
                           ) -> dict[str, list]:
    """Build a unified timetable graph from multiple GTFS feeds.

    Station IDs are prefixed: "SNCB:stop_id", "STIB:stop_id", etc.
    Returns station_departures dict with tuples (dep_min, next_station, arr_min, trip_id).
    """
    all_departures: dict[str, list] = defaultdict(list)

    for operator, feed in feeds.items():
        sids = service_ids_per_op.get(operator, set())
        if not sids:
            continue

        # Library returns {stop_id: [(next_stop_id, dep_min, arr_min, trip_id), ...]}
        lib_graph = _lib_build_timetable_graph(feed, list(sids), hour_filter)

        prefix = f"{operator}:"
        for from_sid, edges in lib_graph.items():
            prefixed_from = f"{prefix}{from_sid}"
            for next_sid, dep_min, arr_min, trip_id in edges:
                all_departures[prefixed_from].append((
                    dep_min, f"{prefix}{next_sid}", arr_min, f"{prefix}{trip_id}",
                ))

    # Sort by departure time
    for sid in all_departures:
        all_departures[sid].sort(key=lambda x: x[0])

    return dict(all_departures)


# ---------------------------------------------------------------------------
# Inter-modal transfer edges (walking between nearby stops of diff operators)
# ---------------------------------------------------------------------------

def build_transfer_edges(stop_lookup: dict[str, dict],
                         max_walk_km: float = 0.4,
                         ) -> dict[str, list[tuple[str, float]]]:
    """Build walking transfer edges between nearby stops.

    Returns: dict stop_id -> [(other_stop_id, walk_minutes), ...]
    """
    ids = list(stop_lookup.keys())
    coords = np.array([(stop_lookup[s]["lat"], stop_lookup[s]["lon"]) for s in ids])

    transfers: dict[str, list[tuple[str, float]]] = defaultdict(list)

    # Use spatial binning for efficiency (avoid O(n²))
    bins: dict[tuple[int, int], list[int]] = defaultdict(list)
    for i in range(len(ids)):
        bx = int(coords[i, 0] / 0.01)
        by = int(coords[i, 1] / 0.01)
        bins[(bx, by)].append(i)

    for (bx, by), indices_in_bin in bins.items():
        neighbours = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                neighbours.extend(bins.get((bx + dx, by + dy), []))

        for i in indices_in_bin:
            for j in neighbours:
                if i >= j:
                    continue
                if ids[i] == ids[j]:
                    continue
                dist = haversine_km(
                    coords[i, 0], coords[i, 1],
                    coords[j, 0], coords[j, 1],
                )
                if dist <= max_walk_km:
                    walk_min = _walk_minutes(dist)
                    transfers[ids[i]].append((ids[j], walk_min))
                    transfers[ids[j]].append((ids[i], walk_min))

    return dict(transfers)


# ---------------------------------------------------------------------------
# Door-to-door BFS from a geographic point
# ---------------------------------------------------------------------------

def find_nearby_stops(lat: float, lon: float, stop_lookup: dict,
                      max_km: float = MAX_WALK_KM,
                      ) -> list[tuple[str, float]]:
    """Find stops within max_km of a point. Returns [(stop_id, walk_min), ...]."""
    results = []
    for sid, info in stop_lookup.items():
        d = haversine_km(lat, lon, info["lat"], info["lon"])
        if d <= max_km:
            results.append((sid, _walk_minutes(d)))
    return results


def bfs_from_point(origin_lat: float, origin_lon: float,
                   stop_lookup: dict,
                   station_departures: dict,
                   transfer_edges: dict,
                   max_minutes: float,
                   departure_window: tuple[int, int] = (7, 9),
                   max_transfers: int = 3,
                   transfer_penalty_min: int = 3,
                   max_walk_km: float = MAX_WALK_KM,
                   ) -> dict[str, dict]:
    """Door-to-door Dijkstra from a geographic point."""
    nearby = find_nearby_stops(origin_lat, origin_lon, stop_lookup, max_walk_km)
    if not nearby:
        return {}

    dep_times = {sid: [d[0] for d in deps]
                 for sid, deps in station_departures.items()}

    best_results: dict[str, dict] = {}

    start_min = departure_window[0] * 60
    end_min = departure_window[1] * 60
    for base_time in range(start_min, end_min, 5):
        deadline = base_time + max_minutes

        best_arrival: dict[str, float] = {}
        queue: list = []

        for stop_id, walk_min in nearby:
            arrive_at = base_time + walk_min
            if arrive_at > deadline:
                continue
            if stop_id not in best_arrival or arrive_at < best_arrival[stop_id]:
                best_arrival[stop_id] = arrive_at
                heapq.heappush(queue, (arrive_at, stop_id, 0, None, walk_min))

        while queue:
            current_time, current_stop, n_transfers, current_trip, walk_accum = \
                heapq.heappop(queue)

            if current_time > best_arrival.get(current_stop, float("inf")):
                continue
            if current_time > deadline:
                continue
            if max_transfers is not None and n_transfers > max_transfers:
                continue

            total_travel = current_time - base_time
            if current_stop not in best_results or \
               total_travel < best_results[current_stop]["travel_time"]:
                best_results[current_stop] = {
                    "travel_time": total_travel,
                    "transfers": n_transfers,
                    "walk_time": walk_accum,
                    "transit_time": total_travel - walk_accum,
                }

            departures = station_departures.get(current_stop, [])
            dtimes = dep_times.get(current_stop, [])
            lo = bisect.bisect_left(dtimes, current_time)

            seen_next = set()
            for idx in range(lo, len(departures)):
                dep_min, next_stop, arr_min, trip_id = departures[idx]

                if dep_min > deadline:
                    break
                if arr_min > deadline:
                    continue

                is_same_trip = current_trip is not None and trip_id == current_trip

                if is_same_trip:
                    new_transfers = n_transfers
                else:
                    is_initial = current_trip is None
                    if not is_initial:
                        if dep_min < current_time + transfer_penalty_min:
                            continue
                        new_transfers = n_transfers + 1
                        if max_transfers is not None and \
                           new_transfers > max_transfers:
                            continue
                    else:
                        new_transfers = n_transfers

                    if next_stop in seen_next:
                        continue
                    seen_next.add(next_stop)

                if arr_min < best_arrival.get(next_stop, float("inf")):
                    best_arrival[next_stop] = arr_min
                    heapq.heappush(queue, (
                        arr_min, next_stop, new_transfers, trip_id, walk_accum,
                    ))

            for other_stop, walk_min in transfer_edges.get(current_stop, []):
                arr_walk = current_time + walk_min
                if arr_walk > deadline:
                    continue
                if arr_walk < best_arrival.get(other_stop, float("inf")):
                    best_arrival[other_stop] = arr_walk
                    new_walk = walk_accum + walk_min
                    heapq.heappush(queue, (
                        arr_walk, other_stop, n_transfers, None, new_walk,
                    ))

    return best_results


def _build_reverse_graph(station_departures: dict[str, list],
                         ) -> dict[str, list]:
    """Build a reverse timetable graph for backward Dijkstra."""
    reverse: dict[str, list] = defaultdict(list)
    for from_stop, deps in station_departures.items():
        for dep_min, to_stop, arr_min, trip_id in deps:
            reverse[to_stop].append((arr_min, from_stop, dep_min, trip_id))

    for sid in reverse:
        reverse[sid].sort(key=lambda x: x[0], reverse=True)

    return dict(reverse)


def bfs_to_point(dest_lat: float, dest_lon: float,
                 stop_lookup: dict,
                 station_departures: dict,
                 transfer_edges: dict,
                 max_minutes: float,
                 departure_window: tuple[int, int] = (7, 9),
                 max_transfers: int = 3,
                 transfer_penalty_min: int = 3,
                 max_walk_km: float = MAX_WALK_KM,
                 ) -> dict[str, dict]:
    """Door-to-door reverse Dijkstra *to* a destination point."""
    nearby_dest = find_nearby_stops(dest_lat, dest_lon, stop_lookup, max_walk_km)
    if not nearby_dest:
        return {}

    reverse_graph = _build_reverse_graph(station_departures)

    arr_times = {sid: [e[0] for e in edges]
                 for sid, edges in reverse_graph.items()}

    best_results: dict[str, dict] = {}

    start_min = departure_window[0] * 60
    end_min = departure_window[1] * 60

    for target_arrival in range(start_min, end_min, 5):
        deadline_arrival = target_arrival + max_minutes
        earliest_dep = target_arrival

        latest_departure: dict[str, float] = {}
        queue: list = []

        for stop_id, walk_min in nearby_dest:
            depart_by = deadline_arrival - walk_min
            if depart_by < earliest_dep:
                continue
            if stop_id not in latest_departure or depart_by > latest_departure[stop_id]:
                latest_departure[stop_id] = depart_by
                heapq.heappush(queue, (-depart_by, stop_id, 0, None, walk_min))

        while queue:
            neg_time, current_stop, n_transfers, current_trip, walk_accum = \
                heapq.heappop(queue)
            current_time = -neg_time

            if current_time < latest_departure.get(current_stop, -1):
                continue
            if current_time < earliest_dep:
                continue
            if max_transfers is not None and n_transfers > max_transfers:
                continue

            total_travel = deadline_arrival - current_time
            if total_travel > max_minutes:
                continue
            if current_stop not in best_results or \
               total_travel < best_results[current_stop]["travel_time"]:
                best_results[current_stop] = {
                    "travel_time": total_travel,
                    "transfers": n_transfers,
                    "walk_time": walk_accum,
                    "transit_time": total_travel - walk_accum,
                }

            arrivals = reverse_graph.get(current_stop, [])
            atimes = arr_times.get(current_stop, [])

            lo = bisect.bisect_left(atimes, -current_time, key=lambda x: -x)

            seen_prev = set()
            for idx in range(lo, len(arrivals)):
                arr_min, from_stop, dep_min, trip_id = arrivals[idx]

                if arr_min > current_time:
                    continue
                if dep_min < earliest_dep:
                    break

                is_same_trip = current_trip is not None and trip_id == current_trip

                if is_same_trip:
                    new_transfers = n_transfers
                else:
                    is_initial = current_trip is None
                    if not is_initial:
                        if arr_min + transfer_penalty_min > current_time:
                            continue
                        new_transfers = n_transfers + 1
                        if max_transfers is not None and \
                           new_transfers > max_transfers:
                            continue
                    else:
                        new_transfers = n_transfers

                    if from_stop in seen_prev:
                        continue
                    seen_prev.add(from_stop)

                if dep_min > latest_departure.get(from_stop, -1):
                    latest_departure[from_stop] = dep_min
                    heapq.heappush(queue, (
                        -dep_min, from_stop, new_transfers, trip_id, walk_accum,
                    ))

            for other_stop, walk_min in transfer_edges.get(current_stop, []):
                depart_by = current_time - walk_min
                if depart_by < earliest_dep:
                    continue
                if depart_by > latest_departure.get(other_stop, -1):
                    latest_departure[other_stop] = depart_by
                    new_walk = walk_accum + walk_min
                    heapq.heappush(queue, (
                        -depart_by, other_stop, n_transfers, None, new_walk,
                    ))

    return best_results


# ---------------------------------------------------------------------------
# Multi-source BFS: from a set of source stops outward
# ---------------------------------------------------------------------------

def bfs_from_stops(source_stop_ids: set[str],
                   stop_lookup: dict,
                   station_departures: dict,
                   transfer_edges: dict,
                   max_minutes: float,
                   departure_window: tuple[int, int] = (7, 9),
                   max_transfers: int = 3,
                   transfer_penalty_min: int = 3,
                   ) -> dict[str, dict]:
    """Multi-source Dijkstra: all *source_stop_ids* start at time 0."""
    dep_times = {sid: [d[0] for d in deps]
                 for sid, deps in station_departures.items()}

    best_results: dict[str, dict] = {}

    start_min = departure_window[0] * 60
    end_min = departure_window[1] * 60

    for base_time in range(start_min, end_min, 5):
        deadline = base_time + max_minutes

        best_arrival: dict[str, float] = {}
        queue: list = []

        for sid in source_stop_ids:
            if sid not in stop_lookup:
                continue
            best_arrival[sid] = base_time
            heapq.heappush(queue, (base_time, sid, 0, None))

        while queue:
            current_time, current_stop, n_transfers, current_trip = \
                heapq.heappop(queue)

            if current_time > best_arrival.get(current_stop, float("inf")):
                continue
            if current_time > deadline:
                continue
            if max_transfers is not None and n_transfers > max_transfers:
                continue

            total_travel = current_time - base_time
            if current_stop not in best_results or \
               total_travel < best_results[current_stop]["travel_time"]:
                best_results[current_stop] = {
                    "travel_time": total_travel,
                    "transfers": n_transfers,
                }

            departures = station_departures.get(current_stop, [])
            dtimes = dep_times.get(current_stop, [])
            lo = bisect.bisect_left(dtimes, current_time)

            seen_next = set()
            for idx in range(lo, len(departures)):
                dep_min, next_stop, arr_min, trip_id = departures[idx]

                if dep_min > deadline:
                    break
                if arr_min > deadline:
                    continue

                is_same_trip = current_trip is not None and trip_id == current_trip

                if is_same_trip:
                    new_transfers = n_transfers
                else:
                    is_initial = current_trip is None
                    if not is_initial:
                        if dep_min < current_time + transfer_penalty_min:
                            continue
                        new_transfers = n_transfers + 1
                        if max_transfers is not None and \
                           new_transfers > max_transfers:
                            continue
                    else:
                        new_transfers = n_transfers

                    if next_stop in seen_next:
                        continue
                    seen_next.add(next_stop)

                if arr_min < best_arrival.get(next_stop, float("inf")):
                    best_arrival[next_stop] = arr_min
                    heapq.heappush(queue, (
                        arr_min, next_stop, new_transfers, trip_id,
                    ))

            for other_stop, walk_min in transfer_edges.get(current_stop, []):
                arr_walk = current_time + walk_min
                if arr_walk > deadline:
                    continue
                if arr_walk < best_arrival.get(other_stop, float("inf")):
                    best_arrival[other_stop] = arr_walk
                    heapq.heappush(queue, (
                        arr_walk, other_stop, n_transfers, None,
                    ))

    return best_results
