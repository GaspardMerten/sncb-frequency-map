"""Multimodal timetable graph and door-to-door BFS.

Combines GTFS feeds from multiple operators (SNCB, De Lijn, STIB, TEC) into a
single timetable graph, then runs BFS from a geographic coordinate (address)
to compute travel time to every reachable stop, including walking first/last
mile.
"""

import bisect
import heapq
import numpy as np
import pandas as pd
from collections import defaultdict
from datetime import date

from .gtfs import _to_datetime_safe

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
        if feed.stops is None:
            continue
        stops = feed.stops
        lats = stops["stop_lat"].values.astype(float)
        lons = stops["stop_lon"].values.astype(float)
        sids = stops["stop_id"].astype(str).str.strip().values
        if "parent_station" in stops.columns:
            parents = stops["parent_station"].fillna("").astype(str).str.strip().values
        else:
            parents = np.full(len(stops), "", dtype=object)
        names = stops["stop_name"].fillna("").values

        for i in range(len(stops)):
            lat, lon = lats[i], lons[i]
            if np.isnan(lat) or np.isnan(lon) or not is_in_belgium(lat, lon):
                continue
            key = parents[i] if parents[i] else sids[i]
            prefixed = f"{operator}:{key}"
            if prefixed not in lookup:
                lookup[prefixed] = {
                    "name": names[i], "lat": float(lat), "lon": float(lon),
                    "operator": operator,
                }
    return lookup


# ---------------------------------------------------------------------------
# Multi-operator timetable graph
# ---------------------------------------------------------------------------

def _vectorized_time_to_minutes(series: pd.Series) -> np.ndarray:
    if pd.api.types.is_timedelta64_dtype(series):
        return (series.dt.total_seconds() / 60).fillna(-1).astype(int).values
    parts = series.astype(str).str.split(":", n=2, expand=True)
    hours = pd.to_numeric(parts[0], errors="coerce").fillna(-1)
    minutes = pd.to_numeric(parts[1], errors="coerce").fillna(0)
    return (hours * 60 + minutes).astype(int).values


def _build_stop_to_station(stops: pd.DataFrame) -> dict[str, str]:
    sid = stops["stop_id"].astype(str).str.strip()
    if "parent_station" in stops.columns:
        parent = stops["parent_station"].fillna("").astype(str).str.strip()
    else:
        parent = pd.Series("", index=stops.index)
    station = np.where(parent != "", parent, sid)
    return dict(zip(sid, station))


def _is_pass_through(st_df: pd.DataFrame) -> pd.Series:
    pickup = pd.to_numeric(
        st_df["pickup_type"], errors="coerce"
    ).fillna(0).astype(int) if "pickup_type" in st_df.columns else 0
    dropoff = pd.to_numeric(
        st_df["drop_off_type"], errors="coerce"
    ).fillna(0).astype(int) if "drop_off_type" in st_df.columns else 0
    return (pickup == 1) & (dropoff == 1)


def get_active_service_ids(feed, target_dates: list[date]) -> set[str]:
    """Determine active service_ids for the given dates."""
    day_names = ["monday", "tuesday", "wednesday", "thursday", "friday",
                 "saturday", "sunday"]
    counts: dict[str, int] = defaultdict(int)
    ts_dates = {pd.Timestamp(d) for d in target_dates}

    if feed.calendar is not None:
        cal = feed.calendar.copy()
        cal["start_date"] = _to_datetime_safe(cal["start_date"])
        cal["end_date"] = _to_datetime_safe(cal["end_date"])
        for d in target_dates:
            ts = pd.Timestamp(d)
            mask = (cal["start_date"] <= ts) & (cal["end_date"] >= ts)
            day_col = day_names[d.weekday()]
            if day_col in cal.columns:
                for sid in cal.loc[mask & (cal[day_col] == 1), "service_id"]:
                    counts[sid] += 1

    if feed.calendar_dates is not None:
        cd = feed.calendar_dates.copy()
        cd["date"] = _to_datetime_safe(cd["date"])
        cd = cd[cd["date"].isin(ts_dates)]
        for sid in cd[cd["exception_type"] == 1]["service_id"]:
            counts[sid] += 1
        for sid in cd[cd["exception_type"] == 2]["service_id"]:
            counts[sid] -= 1
        counts = {k: v for k, v in counts.items() if v > 0}

    return set(counts.keys())


def build_multimodal_graph(feeds: dict,
                           service_ids_per_op: dict[str, set[str]],
                           hour_filter: tuple | None = None,
                           ) -> dict[str, list]:
    """Build a unified timetable graph from multiple GTFS feeds.

    Station IDs are prefixed: "SNCB:stop_id", "STIB:stop_id", etc.
    Returns station_departures dict.
    """
    all_departures: dict[str, list] = defaultdict(list)

    for operator, feed in feeds.items():
        sids = service_ids_per_op.get(operator, set())
        if not sids:
            continue

        trips = feed.trips
        stop_times = feed.stop_times
        stops = feed.stops

        if stop_times is None or trips is None or stops is None:
            continue

        stop_to_station = _build_stop_to_station(stops)

        active_trip_ids = set(
            trips.loc[trips["service_id"].isin(sids), "trip_id"]
        )
        st_f = stop_times[stop_times["trip_id"].isin(active_trip_ids)].copy()
        st_f = st_f.sort_values(["trip_id", "stop_sequence"])

        st_f = st_f[~_is_pass_through(st_f)]

        st_f["dep_min"] = _vectorized_time_to_minutes(st_f["departure_time"])
        st_f["arr_min"] = _vectorized_time_to_minutes(st_f["arrival_time"])
        st_f["station_id"] = st_f["stop_id"].map(stop_to_station).fillna(
            st_f["stop_id"])

        st_f["next_station"] = st_f.groupby("trip_id")["station_id"].shift(-1)
        st_f["next_arr_min"] = st_f.groupby("trip_id")["arr_min"].shift(-1)

        pairs = st_f.dropna(subset=["next_station"])
        pairs = pairs[
            (pairs["station_id"] != pairs["next_station"]) &
            (pairs["dep_min"] >= 0)
        ]

        if hour_filter:
            h_start, h_end = hour_filter
            pairs = pairs[
                (pairs["dep_min"] >= h_start * 60) &
                (pairs["dep_min"] < h_end * 60)
            ]

        # Prefix station IDs with operator — fully vectorized
        prefix = f"{operator}:"
        from_ids = (prefix + pairs["station_id"].astype(str)).values
        to_ids = (prefix + pairs["next_station"].astype(str)).values
        trip_ids = (prefix + pairs["trip_id"].astype(str)).values
        dep_vals = pairs["dep_min"].values.astype(int)
        arr_vals = pairs["next_arr_min"].values.astype(int)

        for k in range(len(from_ids)):
            all_departures[from_ids[k]].append((
                dep_vals[k], to_ids[k], arr_vals[k], trip_ids[k],
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
    Connects stops within max_walk_km, both inter- and intra-operator
    (different station IDs only).
    """
    ids = list(stop_lookup.keys())
    coords = np.array([(stop_lookup[s]["lat"], stop_lookup[s]["lon"]) for s in ids])

    transfers: dict[str, list[tuple[str, float]]] = defaultdict(list)

    # Use spatial binning for efficiency (avoid O(n²))
    # Bin by 0.01° (~1.1km lat, ~0.7km lon)
    bins: dict[tuple[int, int], list[int]] = defaultdict(list)
    for i in range(len(ids)):
        bx = int(coords[i, 0] / 0.01)
        by = int(coords[i, 1] / 0.01)
        bins[(bx, by)].append(i)

    for (bx, by), indices_in_bin in bins.items():
        # Check this bin + 8 neighbours
        neighbours = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                neighbours.extend(bins.get((bx + dx, by + dy), []))

        for i in indices_in_bin:
            for j in neighbours:
                if i >= j:
                    continue
                # Skip self-links (same prefixed ID is impossible, but same
                # underlying station within one operator is redundant)
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
    """Door-to-door Dijkstra from a geographic point.

    Tries departures every 5 minutes within the window, keeps the best
    travel time to each stop across all departure times.

    Returns: stop_id -> {travel_time, transfers, walk_time, transit_time}
    """
    nearby = find_nearby_stops(origin_lat, origin_lon, stop_lookup, max_walk_km)
    if not nearby:
        return {}

    # Precompute departure time lists for bisect
    dep_times = {sid: [d[0] for d in deps]
                 for sid, deps in station_departures.items()}

    best_results: dict[str, dict] = {}

    # Try every 5 minutes in the departure window
    start_min = departure_window[0] * 60
    end_min = departure_window[1] * 60
    for base_time in range(start_min, end_min, 5):
        deadline = base_time + max_minutes

        best_arrival: dict[str, float] = {}
        queue: list = []

        # Seed: walk from origin to nearby stops
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

            # Record result
            total_travel = current_time - base_time
            if current_stop not in best_results or \
               total_travel < best_results[current_stop]["travel_time"]:
                best_results[current_stop] = {
                    "travel_time": total_travel,
                    "transfers": n_transfers,
                    "walk_time": walk_accum,
                    "transit_time": total_travel - walk_accum,
                }

            # Explore transit departures
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

            # Explore walking transfers
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
    """Build a reverse timetable graph for backward Dijkstra.

    Original: from_stop -> [(dep_min, to_stop, arr_min, trip_id), ...]
    Reverse:  to_stop   -> [(arr_min, from_stop, dep_min, trip_id), ...]

    Sorted by arr_min descending (latest first) for backward search.
    """
    reverse: dict[str, list] = defaultdict(list)
    for from_stop, deps in station_departures.items():
        for dep_min, to_stop, arr_min, trip_id in deps:
            reverse[to_stop].append((arr_min, from_stop, dep_min, trip_id))

    # Sort by arrival time descending (we search backward in time)
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
    """Door-to-door reverse Dijkstra *to* a destination point.

    Runs backward from the destination: starts at stops near the destination,
    then follows the timetable graph in reverse (arrivals → departures) to
    find the latest possible departure from each origin stop that still
    arrives in time.

    Returns: stop_id -> {travel_time, transfers, walk_time, transit_time}
    """
    nearby_dest = find_nearby_stops(dest_lat, dest_lon, stop_lookup, max_walk_km)
    if not nearby_dest:
        return {}

    reverse_graph = _build_reverse_graph(station_departures)

    # Precompute arrival time lists for bisect (descending order)
    arr_times = {sid: [e[0] for e in edges]
                 for sid, edges in reverse_graph.items()}

    best_results: dict[str, dict] = {}

    # Try target arrival times every 5 minutes in the window
    start_min = departure_window[0] * 60
    end_min = departure_window[1] * 60

    for target_arrival in range(start_min, end_min, 5):
        # The traveller must arrive at destination by target_arrival + max_minutes
        deadline_arrival = target_arrival + max_minutes
        # Earliest departure we consider
        earliest_dep = target_arrival

        # latest_departure[stop] = latest time you can depart from stop and
        # still reach the destination by deadline_arrival
        latest_departure: dict[str, float] = {}

        # Max-heap (negate time): (-departure_time, stop_id, n_transfers, trip_id, walk_accum)
        queue: list = []

        # Seed: walk from destination-nearby stops to destination
        for stop_id, walk_min in nearby_dest:
            # You need to arrive at this stop by deadline_arrival - walk_min
            depart_by = deadline_arrival - walk_min
            if depart_by < earliest_dep:
                continue
            if stop_id not in latest_departure or depart_by > latest_departure[stop_id]:
                latest_departure[stop_id] = depart_by
                heapq.heappush(queue, (-depart_by, stop_id, 0, None, walk_min))

        while queue:
            neg_time, current_stop, n_transfers, current_trip, walk_accum = \
                heapq.heappop(queue)
            current_time = -neg_time  # latest time to depart from current_stop

            if current_time < latest_departure.get(current_stop, -1):
                continue
            if current_time < earliest_dep:
                continue
            if max_transfers is not None and n_transfers > max_transfers:
                continue

            # Record result: travel_time = deadline_arrival - current_time
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

            # Explore reverse transit: find arrivals at current_stop where
            # arr_min <= current_time (i.e. the train arrived before we need
            # to be here). Then we can "go back" to the departure stop.
            arrivals = reverse_graph.get(current_stop, [])
            atimes = arr_times.get(current_stop, [])

            # atimes is sorted descending; find first index where arr <= current_time
            # binary search: we want largest arr_min <= current_time
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
                        # Transfer: arrival must be at least penalty before current
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

                # dep_min = the time you'd need to be at from_stop
                if dep_min > latest_departure.get(from_stop, -1):
                    latest_departure[from_stop] = dep_min
                    heapq.heappush(queue, (
                        -dep_min, from_stop, new_transfers, trip_id, walk_accum,
                    ))

            # Explore walking transfers (backward)
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
