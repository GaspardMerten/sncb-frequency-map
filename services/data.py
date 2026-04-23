"""Data loading and processing services.

Wraps the existing logic/ modules with caching for the FastAPI app.
"""

import logging
import os
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta

from logic.api import (
    fetch_gtfs,
    fetch_infrabel_segments,
    fetch_operational_points,
    fetch_punctuality,
)
from logic.gtfs import (
    build_stop_lookup,
    compute_segment_frequencies,
    compute_served_stations,
    get_service_day_counts,
)
from logic.holidays import public_holidays_in_range, school_holidays_in_range
from logic.matching import (
    build_gtfs_to_infra_mapping,
    build_infra_cluster_map,
    map_frequencies_to_infra,
    mergure_segments,
)
from logic.reachability import build_timetable_graph
from logic.shared import _month_ranges, load_provinces_geojson, noon_timestamp

from .cache import cached

logger = logging.getLogger(__name__)

TOKEN = os.getenv("BRUSSELS_MOBILITY_TWIN_KEY", "")


def _safe_fetch(fn, *args):
    try:
        return fn(*args)
    except Exception:
        return None


def prefetch_punctuality(dates: list[date], max_workers: int = 8,
                         on_progress=None) -> None:
    """Pre-warm the punctuality cache for a list of dates in parallel.

    Each date is fetched via load_punctuality_data (which is @cached), so
    subsequent sequential access hits the warm cache.  *on_progress*, if
    provided, is called with (completed_count, total) after each date
    finishes — useful for streaming progress to the frontend.
    """
    total = len(dates)
    if total == 0:
        return

    done = 0
    with ThreadPoolExecutor(max_workers=min(max_workers, total)) as pool:
        futures = {pool.submit(load_punctuality_data, d): d for d in dates}
        for fut in as_completed(futures):
            fut.result()          # propagate exceptions / populate cache
            done += 1
            if on_progress:
                on_progress(done, total)


@cached(ttl=3600)
def load_gtfs_data(
    start_date: date,
    end_date: date,
    weekdays: tuple[int, ...],
    hour_filter: tuple[int, int] | None,
    exclude_pub: bool = False,
    exclude_sch: bool = False,
) -> dict:
    """Load and process GTFS data for a date range."""
    from logic.holidays import SCHOOL_HOLIDAYS

    pub_hols = public_holidays_in_range(start_date, end_date)

    excluded_dates: set[date] = set()
    if exclude_pub:
        excluded_dates |= set(pub_hols.keys())
    if exclude_sch:
        for s, e, _ in SCHOOL_HOLIDAYS:
            d = s
            while d <= e:
                excluded_dates.add(d)
                d += timedelta(days=1)

    all_dates = []
    d = start_date
    while d <= end_date:
        if d.weekday() in weekdays and d not in excluded_dates:
            all_dates.append(d)
        d += timedelta(days=1)

    if not all_dates:
        return {"error": "No dates match filters"}

    day_count = len(all_dates)
    months = _month_ranges(start_date, end_date)
    active_months = [
        (ts, ms, me) for ts, ms, me in months
        if any(ms <= d <= me for d in all_dates)
    ]

    logger.info("Loading GTFS: %s to %s, %d months, token=%s...",
                start_date, end_date, len(active_months), TOKEN[:8] if TOKEN else "EMPTY")

    seg_freqs: dict[tuple[str, str], float] = defaultdict(float)
    departures: dict[str, list] = defaultdict(list)
    stop_lookup: dict = {}
    service_ids: set[str] = set()
    service_day_counts: dict[str, int] = defaultdict(int)
    served_stations: set[str] = set()
    n_feeds = 0

    for ts, month_start, month_end in active_months:
        month_dates = [d for d in all_dates if month_start <= d <= month_end]
        if not month_dates:
            continue

        try:
            feed = fetch_gtfs(ts, TOKEN)
        except Exception as e:
            logger.error("Failed to fetch GTFS for ts=%d: %s", ts, e)
            continue
        if feed.stop_times is None or feed.trips is None:
            logger.warning("GTFS incomplete for ts=%d", ts)
            continue

        sdc = get_service_day_counts(feed, month_dates)
        sids = set(sdc.keys())
        if not sids:
            logger.warning("No service IDs for ts=%d, dates=%s", ts, month_dates)
            continue

        n_feeds += 1
        stop_lookup.update(build_stop_lookup(feed))
        served_stations |= compute_served_stations(feed, sids, hour_filter)

        # Compute raw segment counts (no service_day_counts weighting —
        # the library normalises internally when sdc is passed, producing
        # tiny fractions).  We accumulate raw counts and divide by
        # day_count later for proper daily averages.
        for k, v in compute_segment_frequencies(
            feed, sids, hour_filter, day_count=1,
        ).items():
            seg_freqs[k] += v

        for station, deps in build_timetable_graph(feed, sids, hour_filter).items():
            departures[station].extend(deps)

        for sid, cnt in sdc.items():
            service_day_counts[sid] += cnt
        service_ids |= sids
        del feed

    if not service_ids:
        logger.error("No active services found after processing %d months", len(active_months))
        return {"error": "No active services found"}

    for sid in departures:
        departures[sid].sort(key=lambda x: x[0])

    segment_freqs = {k: v / max(day_count, 1) for k, v in seg_freqs.items()}

    first_ts = months[0][0] if months else noon_timestamp(start_date.year, start_date.month)
    infrabel_segs = _safe_fetch(fetch_infrabel_segments, first_ts, TOKEN)
    op_points = _safe_fetch(fetch_operational_points, first_ts, TOKEN)

    cluster_map = build_infra_cluster_map(op_points, infrabel_segs, radius_km=1.0)
    gtfs_to_infra = build_gtfs_to_infra_mapping(
        stop_lookup, op_points, buffer_km=1.0, infrabel_segs=infrabel_segs,
    )

    prov_geo = load_provinces_geojson()

    return {
        "segment_freqs": dict(segment_freqs),
        "station_departures": dict(departures),
        "infrabel_segs": infrabel_segs,
        "op_points": op_points,
        "prov_geo": prov_geo,
        "service_ids": service_ids,
        "service_day_counts": dict(service_day_counts),
        "stop_lookup": stop_lookup,
        "served_stations": served_stations,
        "n_feeds": max(n_feeds, 1),
        "gtfs_to_infra": gtfs_to_infra,
        "cluster_map": cluster_map,
        "day_count": day_count,
        "all_dates": all_dates,
    }


@cached(ttl=3600)
def load_segments(
    start_date: date,
    end_date: date,
    weekdays: tuple[int, ...],
    hour_filter: tuple[int, int] | None,
    exclude_pub: bool = False,
    exclude_sch: bool = False,
) -> dict:
    """Load segment frequency data for the map."""
    data = load_gtfs_data(start_date, end_date, weekdays, hour_filter,
                          exclude_pub, exclude_sch)
    if "error" in data:
        return data

    infra_segments, _stats = map_frequencies_to_infra(
        data["segment_freqs"],
        data["stop_lookup"],
        data["infrabel_segs"],
        data["gtfs_to_infra"],
        data["prov_geo"],
        cluster_map=data["cluster_map"],
    )
    infra_segments = [s for s in infra_segments if s["frequency"] > 0]
    merged = mergure_segments(infra_segments, buffer_km=0.5)

    segments = []
    for seg in merged:
        coords = seg.get("coords", [])
        freq = seg.get("frequency", 0)
        if coords and freq > 0:
            segments.append({
                "id": f"{seg.get('id_a', '')}_{seg.get('id_b', '')}",
                "freq": round(freq, 1),
                "coords": [[c[0], c[1]] for c in coords],
            })

    from logic.gtfs import compute_station_frequencies
    station_freqs = compute_station_frequencies(
        data["segment_freqs"], data["stop_lookup"],
    )

    stations = []
    for sid, freq in station_freqs.items():
        s = data["stop_lookup"].get(sid)
        if s and freq > 0:
            stations.append({
                "id": sid,
                "name": s.get("name", sid),
                "lat": s["lat"],
                "lon": s["lon"],
                "freq": round(freq, 1),
            })

    return {
        "segments": sorted(segments, key=lambda x: x["freq"]),
        "stations": sorted(stations, key=lambda x: -x["freq"]),
        "day_count": data["day_count"],
        "n_feeds": data["n_feeds"],
    }


@cached(ttl=3600)
def load_reach_data(
    start_date: date,
    end_date: date,
    weekdays: tuple[int, ...],
    hour_filter: tuple[int, int] | None,
    exclude_pub: bool = False,
    exclude_sch: bool = False,
    time_budget: float = 1.5,
    dep_start: int = 7,
    dep_end: int = 9,
    max_transfers: int = 3,
    min_transfer_time: int = 5,
) -> dict:
    """Compute reachability for each station (cached)."""
    from logic.reachability import compute_reachability_single

    data = load_gtfs_data(
        start_date, end_date, weekdays, hour_filter, exclude_pub, exclude_sch,
    )
    if "error" in data:
        return data

    departures = data["station_departures"]
    stop_lookup = data["stop_lookup"]
    max_minutes = time_budget * 60

    by_key: dict = {}
    reachable_counts = []

    for sid in departures.keys():
        info = stop_lookup.get(sid)
        if not info:
            continue

        reachable = compute_reachability_single(
            sid, departures, max_minutes,
            max_transfers=max_transfers,
            transfer_penalty_min=min_transfer_time,
            departure_window=(dep_start, dep_end),
        )
        n_reach = len(reachable)
        reachable_counts.append(n_reach)

        dests_by_name: dict = {}
        for dest_id, r_info in reachable.items():
            d_info = stop_lookup.get(dest_id)
            if not d_info:
                continue
            name = d_info["name"]
            t = round(r_info["travel_time"], 1)
            if name not in dests_by_name or t < dests_by_name[name]["time"]:
                dests_by_name[name] = {
                    "name": name,
                    "lat": d_info["lat"],
                    "lon": d_info["lon"],
                    "time": t,
                }

        key = info["name"]
        existing = by_key.get(key)
        if existing is None or n_reach > existing["reachable"]:
            by_key[key] = {
                "id": sid,
                "name": info["name"],
                "lat": info["lat"],
                "lon": info["lon"],
                "reachable": n_reach,
                "destinations": sorted(dests_by_name.values(), key=lambda d: d["time"]),
            }

    stations = sorted(by_key.values(), key=lambda s: -s["reachable"])

    if reachable_counts:
        max_r = max(reachable_counts)
        avg_r = round(sum(reachable_counts) / len(reachable_counts), 1)
        sorted_rc = sorted(reachable_counts)
        mid = len(sorted_rc) // 2
        median_r = sorted_rc[mid] if len(sorted_rc) % 2 else round(
            (sorted_rc[mid - 1] + sorted_rc[mid]) / 2, 1)
    else:
        max_r = avg_r = median_r = 0

    return {
        "stations": stations,
        "max_reachable": max_r,
        "avg_reachable": avg_r,
        "median_reachable": median_r,
    }


def _build_infra_rail_graph(infrabel_segs: dict | None) -> dict[str, dict[str, float]]:
    """Undirected graph of Infrabel ptcarid -> {ptcarid: shortest segment length km}.

    Parallel segments between the same pair of stations are collapsed to the
    minimum length (real track distance between operational points).
    """
    from logic.geo import polyline_length_km

    graph: dict[str, dict[str, float]] = defaultdict(dict)
    if not infrabel_segs or "features" not in infrabel_segs:
        return graph
    for feat in infrabel_segs["features"]:
        props = feat.get("properties", {})
        a = str(props.get("stationfrom_id", "")).strip()
        b = str(props.get("stationto_id", "")).strip()
        if not a or not b or a == b:
            continue
        coords = feat.get("geometry", {}).get("coordinates", [])
        if not coords:
            continue
        length = polyline_length_km(coords)
        if length <= 0:
            continue
        if b not in graph[a] or graph[a][b] > length:
            graph[a][b] = length
            graph[b][a] = length
    return graph


def _rail_distance_from(origin: str, graph: dict[str, dict[str, float]]) -> dict[str, float]:
    """Dijkstra on the Infrabel rail graph. Returns ptcarid -> distance km."""
    import heapq
    if origin not in graph:
        return {}
    dist: dict[str, float] = {origin: 0.0}
    pq: list[tuple[float, str]] = [(0.0, origin)]
    while pq:
        d, u = heapq.heappop(pq)
        if d > dist.get(u, float("inf")):
            continue
        for v, w in graph[u].items():
            nd = d + w
            if nd < dist.get(v, float("inf")):
                dist[v] = nd
                heapq.heappush(pq, (nd, v))
    return dist


@cached(ttl=3600)
def load_rankings_data(
    start_date: date,
    end_date: date,
    weekdays: tuple[int, ...],
    hour_filter: tuple[int, int] | None,
    exclude_pub: bool = False,
    exclude_sch: bool = False,
    time_budget: float = 2.0,
    dep_start: int = 7,
    dep_end: int = 9,
    max_transfers: int = 3,
    min_transfer_time: int = 5,
    speed_dep_start: int = 8,
    speed_dep_end: int = 20,
    top_n: int = 20,
) -> dict:
    """Compute per-station rankings: reach, trains/day, last train, commercial speed.

    Returns a payload used by the `/rankings` report page with one row per
    served Belgian station (served = has at least one active service in
    the selected date range).

    ``hour_filter`` is accepted for API parity with the other endpoints
    but NOT applied: trains/day and the last-train metric need the full
    day, and each sub-metric defines its own hour window
    (``dep_start``/``dep_end`` for reach, ``speed_dep_start``/
    ``speed_dep_end`` for commercial speed).

    Metric definitions:
      * ``trains_per_day`` = ``max(in_freq, out_freq)`` over daily-averaged
        segment frequencies. Counts trains stopping at the station (handles
        through, terminating and starting trains correctly — each train
        increments both counters for through stations and one counter for
        terminus stops).
      * ``last_train_str`` = latest outgoing ``dep_min`` observed at the
        chosen stop_id. Stations that only receive trains have no value.
      * ``reachable`` = ``|{station_ids reachable within time_budget hours}|``
        using BFS over the GTFS timetable graph, with the same transfer
        penalties as the /reach endpoint.
      * ``commercial_speeds[].speed_kmh`` = ``rail_km / median(travel_time)``
        where:
          - ``rail_km`` is the shortest-path distance over the Infrabel track
            segment graph (falls back to crow-flies haversine when either
            endpoint isn't mapped to an Infrabel ptcarid). Note this is the
            shortest *track* route — if the BFS-optimal train takes a longer
            route (e.g., via Brussels), the speed will be slightly
            under-reported relative to the actual on-train experience.
          - ``travel_time`` is ``arr_min - start_min`` from ``_bfs_single``.
            We sample every actual origin departure in
            ``[speed_dep_start, speed_dep_end)`` and take the MINIMUM
            travel time per destination — the fastest directly-available
            journey. This matches the conventional meaning of "commercial
            speed" (fastest regular service), rather than an average over
            all departures (which would include boarding an S-train in the
            wrong direction and transferring back, biasing times upward).
            Pairs reachable in fewer than half the hours of the window
            are reported with ``speed_kmh=null`` to filter freak paths.

    Stations sharing a name are deduplicated, keeping the stop with the
    highest ``trains_per_day`` (ties broken by lexicographic stop_id for
    determinism).
    """
    del hour_filter  # intentionally unused — see docstring
    from logic.geo import PROVINCE_TO_REGION, get_province, haversine_km
    from logic.reachability import (
        _bfs_single,
        _precompute_dep_times,
        compute_reachability_single,
    )

    # Hour filter is intentionally ignored here: trains_per_day and the
    # last-train metric must see the full day. Per-metric windows are
    # handled separately below.
    data = load_gtfs_data(
        start_date, end_date, weekdays, None, exclude_pub, exclude_sch,
    )
    if "error" in data:
        return data

    departures = data["station_departures"]
    stop_lookup = data["stop_lookup"]
    prov_geo = data["prov_geo"]
    segment_freqs = data["segment_freqs"]
    max_minutes = time_budget * 60

    # Trains per day: max(incoming, outgoing) over daily-averaged segment_freqs.
    # Last train: max dep_min across all outgoing edges (unfiltered by hour).
    in_freq: dict[str, float] = defaultdict(float)
    out_freq: dict[str, float] = defaultdict(float)
    for (a, b), f in segment_freqs.items():
        out_freq[a] += f
        in_freq[b] += f

    last_dep_min: dict[str, int] = {}
    for src, edges in departures.items():
        for dep_min, _arr_station, _arr_min, _trip_id in edges:
            if dep_min > last_dep_min.get(src, -1):
                last_dep_min[src] = dep_min

    by_name: dict = {}
    all_sids = set(stop_lookup.keys()) & (set(out_freq) | set(in_freq) | set(departures))

    for sid in all_sids:
        info = stop_lookup.get(sid)
        if not info:
            continue

        trains_per_day = max(out_freq.get(sid, 0.0), in_freq.get(sid, 0.0))

        reachable = compute_reachability_single(
            sid, departures, max_minutes,
            max_transfers=max_transfers,
            transfer_penalty_min=min_transfer_time,
            departure_window=(dep_start, dep_end),
        )
        n_reach = len(reachable)

        ldm = last_dep_min.get(sid, -1)
        last_str = None
        if ldm >= 0:
            hh = int(ldm // 60)
            mm = int(ldm % 60)
            last_str = f"{hh:02d}:{mm:02d}" if hh < 24 else f"{hh - 24:02d}:{mm:02d}+1"

        province = get_province(info["lat"], info["lon"], prov_geo)
        region = PROVINCE_TO_REGION.get(province, "Unknown") if province else "Unknown"

        name = info["name"]
        existing = by_name.get(name)
        if existing is not None:
            # Keep busier stop; on tie, keep lexicographically-smaller id for
            # determinism across runs.
            if existing["trains_per_day"] > trains_per_day:
                continue
            if existing["trains_per_day"] == trains_per_day and existing["id"] <= sid:
                continue
        by_name[name] = {
            "id": sid,
            "name": name,
            "lat": info["lat"],
            "lon": info["lon"],
            "province": province or "Unknown",
            "region": region,
            "reachable": n_reach,
            "trains_per_day": round(trains_per_day, 1),
            "last_train_min": ldm if ldm >= 0 else None,
            "last_train_str": last_str,
        }

    stations = list(by_name.values())

    # Commercial speed between the top_n busiest stations, over the configured
    # speed window (default 8h–20h). For each origin we sample one ACTUAL train
    # departure per hour inside the window — this keeps the initial wait at the
    # origin near zero, so travel_time approximates real in-vehicle time.
    # Distance is the true rail distance from the Infrabel segment network
    # (shortest path over stationfrom_id/stationto_id segment lengths), with a
    # haversine fallback when either endpoint isn't in the Infrabel graph.
    # Speed is (rail_km / average_travel_hours) over sampled starts.
    speed_candidates = sorted(
        stations, key=lambda s: -s["trains_per_day"],
    )[:top_n]
    top_name_list = [s["name"] for s in speed_candidates]
    top_names = set(top_name_list)
    top_coords = {s["name"]: (s["lat"], s["lon"]) for s in speed_candidates}

    speed_budget_min = 4 * 60
    window_lo = speed_dep_start * 60
    window_hi = speed_dep_end * 60

    # Build the Infrabel rail graph once. Rail distance = shortest path over
    # actual track segment lengths. Falls back to haversine crow-flies for
    # pairs that aren't connected in the Infrabel network.
    infra_graph = _build_infra_rail_graph(data.get("infrabel_segs"))
    gtfs_to_infra = data.get("gtfs_to_infra", {})
    dest_ptc_by_name = {s["name"]: gtfs_to_infra.get(s["id"]) for s in speed_candidates}

    _dep_times = _precompute_dep_times(departures)
    commercial_speeds = []
    for origin in speed_candidates:
        origin_sid = origin["id"]

        # Sample every actual origin departure in the window. For each
        # destination we'll take the MINIMUM travel time across these starts
        # — this is "commercial speed" in its usual sense: the fastest
        # regularly-available direct journey. Intermediate starts (e.g.,
        # an S-train to Aalst) yield big travel times that we simply
        # ignore for this destination.
        starts = sorted(
            dep_min for dep_min, _, _, _
            in departures.get(origin_sid, [])
            if window_lo <= dep_min < window_hi
        )
        # Dedupe exact starts (multiple trips at the same minute do not help)
        starts = sorted(set(starts))
        if not starts:
            starts = list(range(window_lo, window_hi, 60))

        # Per-origin Dijkstra on the Infrabel rail graph
        origin_ptc = gtfs_to_infra.get(origin_sid)
        rail_dist = _rail_distance_from(origin_ptc, infra_graph) if origin_ptc else {}

        # For each destination, track the minimum observed travel time across
        # all sampled starts. We also count the number of hours in the window
        # in which this destination was reachable — connectivity proxy used
        # below to filter out pairs with only a freak single-hour connection.
        min_time: dict[str, float] = {}
        hours_reached: dict[str, set[int]] = defaultdict(set)
        for start_min in starts:
            r = _bfs_single(
                origin_sid, departures, speed_budget_min, start_min,
                max_transfers=max_transfers,
                transfer_penalty_min=min_transfer_time,
                _dep_times=_dep_times,
            )
            per_name: dict[str, float] = {}
            for dest_id, info in r.items():
                d = stop_lookup.get(dest_id)
                if not d:
                    continue
                dname = d["name"]
                if dname not in top_names or dname == origin["name"]:
                    continue
                t = info["travel_time"]
                if dname not in per_name or t < per_name[dname]:
                    per_name[dname] = t
            for dname, t in per_name.items():
                if dname not in min_time or t < min_time[dname]:
                    min_time[dname] = t
                hours_reached[dname].add(start_min // 60)

        fast = medium = slow = 0
        pairs = []
        n_hours = max(1, (window_hi - window_lo) // 60)
        for dname in top_name_list:
            if dname == origin["name"]:
                continue
            t_best = min_time.get(dname)
            haversine_dist = haversine_km(
                origin["lat"], origin["lon"], *top_coords[dname],
            )
            dest_ptc = dest_ptc_by_name.get(dname)
            dist = rail_dist.get(dest_ptc) if dest_ptc else None
            if dist is None or dist <= 0:
                dist = haversine_dist
            # Require the destination to be reachable in at least half of the
            # hours in the window, to avoid reporting fluke single-hour speeds.
            reachable_hours = len(hours_reached.get(dname, set()))
            enough = reachable_hours >= max(1, n_hours // 2)
            if t_best is None or not enough:
                pairs.append({
                    "dest": dname,
                    "avg_time_min": None,
                    "distance_km": round(dist, 1),
                    "speed_kmh": None,
                })
                continue
            avg_t = t_best
            speed = (dist / (avg_t / 60.0)) if avg_t > 0 else 0
            pairs.append({
                "dest": dname,
                "avg_time_min": round(avg_t, 1),
                "distance_km": round(dist, 1),
                "speed_kmh": round(speed, 1),
            })
            if speed > 80:
                fast += 1
            elif speed >= 60:
                medium += 1
            else:
                slow += 1

        commercial_speeds.append({
            "name": origin["name"],
            "lat": origin["lat"],
            "lon": origin["lon"],
            "region": origin["region"],
            "province": origin["province"],
            "trains_per_day": origin["trains_per_day"],
            "fast_count": fast,
            "medium_count": medium,
            "slow_count": slow,
            "pairs": pairs,
        })

    commercial_speeds.sort(
        key=lambda s: (-(s["fast_count"] + s["medium_count"] * 0.5), -s["trains_per_day"]),
    )

    return {
        "stations": stations,
        "commercial_speeds": commercial_speeds,
        "time_budget": time_budget,
        "top_n": top_n,
        "speed_window": [speed_dep_start, speed_dep_end],
    }


@cached(ttl=3600)
def load_connectivity_data(
    start_date: date,
    end_date: date,
    weekdays: tuple[int, ...],
    hour_filter: tuple[int, int] | None,
    exclude_pub: bool = False,
    exclude_sch: bool = False,
    time_budget: float = 2.0,
    max_transfers: int = 2,
    dep_start: int = 7,
    dep_end: int = 9,
) -> dict:
    """Compute connectivity metrics per station (cached)."""
    from logic.geo import PROVINCE_TO_REGION, get_province
    from logic.reachability import (
        _cardinal_reach,
        compute_direct_frequency,
        compute_reachability_single,
        station_size,
    )

    data = load_gtfs_data(
        start_date, end_date, weekdays, hour_filter, exclude_pub, exclude_sch,
    )
    if "error" in data:
        return data

    departures = data["station_departures"]
    stop_lookup = data["stop_lookup"]
    n_feeds = data["n_feeds"]
    max_minutes = time_budget * 60
    prov_geo = data["prov_geo"]

    by_name: dict = {}
    counts = {"Small": 0, "Medium": 0, "Big": 0}

    for sid in departures.keys():
        info = stop_lookup.get(sid)
        if not info:
            continue

        reachable = compute_reachability_single(
            sid, departures, max_minutes,
            stop_lookup=stop_lookup,
            max_transfers=max_transfers,
            transfer_penalty_min=5,
            departure_window=(dep_start, dep_end),
        )

        a_count = len(reachable)
        b_freq = round(compute_direct_frequency(sid, departures, n_feeds=n_feeds), 2)
        c_reach = round(_cardinal_reach(sid, reachable, stop_lookup), 1)
        size = station_size(b_freq)

        province = get_province(info["lat"], info["lon"], prov_geo)
        region = PROVINCE_TO_REGION.get(province, "Unknown") if province else "Unknown"

        name = info["name"]
        existing = by_name.get(name)
        if existing is not None and existing["reachable"] >= a_count:
            continue
        if existing is not None:
            counts[existing["_size_label"]] = max(counts.get(existing["_size_label"], 1) - 1, 0)
        counts[size] = counts.get(size, 0) + 1
        by_name[name] = {
            "name": name,
            "lat": info["lat"],
            "lon": info["lon"],
            "reachable": a_count,
            "direct_freq": b_freq,
            "reach_km": c_reach,
            "size": size.lower(),
            "region": region,
            "_size_label": size,
        }

    stations = sorted(by_name.values(), key=lambda s: -s["reachable"])
    for st in stations:
        st.pop("_size_label", None)

    return {
        "stations": stations,
        "total": len(stations),
        "n_small": counts.get("Small", 0),
        "n_medium": counts.get("Medium", 0),
        "n_big": counts.get("Big", 0),
    }


@cached(ttl=3600)
def load_duration_data(
    start_date: date,
    end_date: date,
    weekdays: tuple[int, ...],
    hour_filter: tuple[int, int] | None,
    exclude_pub: bool = False,
    exclude_sch: bool = False,
    direction: str = "to",
    destinations: tuple[str, ...] = ("Bruxelles-Central",),
    time_budget: float = 3.0,
    dep_start: int = 7,
    dep_end: int = 9,
    max_transfers: int = 3,
) -> dict:
    """Compute travel duration from/to destination station(s) (cached)."""
    from logic.reachability import (
        build_reverse_timetable_graph,
        compute_reachability_single,
        compute_reachability_to_dest,
    )

    data = load_gtfs_data(
        start_date, end_date, weekdays, hour_filter, exclude_pub, exclude_sch,
    )
    if "error" in data:
        return data

    departures = data["station_departures"]
    stop_lookup = data["stop_lookup"]
    max_minutes = time_budget * 60

    # Find destination station IDs by name matching
    dest_ids = []
    dest_coords = []
    name_lower_map = {sid: info["name"].lower() for sid, info in stop_lookup.items()}
    for dname in destinations:
        dname_lower = dname.lower()
        for sid, name_l in name_lower_map.items():
            if dname_lower == name_l or dname_lower in name_l:
                info = stop_lookup[sid]
                dest_ids.append(sid)
                dest_coords.append({
                    "name": info["name"],
                    "lat": info["lat"],
                    "lon": info["lon"],
                })
                break

    if not dest_ids:
        return {"error": "No matching destination stations found"}

    merged: dict[str, dict] = {}

    if direction == "to":
        reverse_departures = build_reverse_timetable_graph(departures)
        for dest_id in dest_ids:
            reachable = compute_reachability_to_dest(
                dest_id, reverse_departures, max_minutes,
                max_transfers=max_transfers,
                arrival_window=(dep_start, dep_end),
            )
            for origin_id, r_info in reachable.items():
                if origin_id not in merged or r_info["travel_time"] < merged[origin_id]["travel_time"]:
                    merged[origin_id] = r_info
    else:
        for dest_id in dest_ids:
            reachable = compute_reachability_single(
                dest_id, departures, max_minutes,
                max_transfers=max_transfers,
                departure_window=(dep_start, dep_end),
            )
            for target_id, r_info in reachable.items():
                if target_id not in merged or r_info["travel_time"] < merged[target_id]["travel_time"]:
                    merged[target_id] = r_info

    stations = []
    durations = []
    for sid, r_info in merged.items():
        info = stop_lookup.get(sid)
        if not info:
            continue
        dur = round(r_info["travel_time"], 1)
        stations.append({
            "name": info["name"],
            "lat": info["lat"],
            "lon": info["lon"],
            "duration": dur,
        })
        durations.append(dur)

    stations.sort(key=lambda s: s["duration"])

    if durations:
        avg_dur = round(sum(durations) / len(durations), 1)
        min_dur = round(min(durations), 1)
        max_dur = round(max(durations), 1)
    else:
        avg_dur = min_dur = max_dur = 0

    return {
        "stations": stations,
        "dest_coords": dest_coords,
        "avg_duration": avg_dur,
        "min_duration": min_dur,
        "max_duration": max_dur,
    }



def _build_commercial_stops(feed, station_coords: dict[str, dict]) -> dict[str, set[str]]:
    """Build {UPPER_STATION_NL: set[train_no]} for commercial stops from GTFS.

    Uses coordinate matching to map GTFS French names → Infrabel Dutch names.
    Only includes stops where pickup_type=0 or drop_off_type=0 (actual passenger stops).
    """
    import math
    import polars as pl

    st = feed.stop_times
    trips = feed.trips
    stops = feed.stops

    # 1. Filter to commercial stops (passenger pickup or dropoff)
    commercial = st.filter(
        (pl.col("pickup_type") == 0) | (pl.col("drop_off_type") == 0)
    )

    # 2. Join with trips to get train number
    commercial = commercial.join(
        trips.select(["trip_id", "trip_short_name"]), on="trip_id"
    )

    # 3. Resolve stop_id → parent station name
    stop_parent = stops.select(["stop_id", "parent_station", "stop_name"])
    parents = stops.filter(pl.col("location_type") == 1).select(
        pl.col("stop_id").alias("pid"), pl.col("stop_name").alias("parent_name")
    )
    stop_parent = stop_parent.join(parents, left_on="parent_station", right_on="pid", how="left")
    stop_parent = stop_parent.with_columns(
        pl.coalesce(["parent_name", "stop_name"]).alias("station_name")
    )
    commercial = commercial.join(
        stop_parent.select(["stop_id", "station_name"]), on="stop_id"
    )

    # 4. Build GTFS station → set[train_no]
    gtfs_trains: dict[str, set[str]] = {}
    for stn, tn in commercial.select(["station_name", "trip_short_name"]).unique().iter_rows():
        gtfs_trains.setdefault(stn, set()).add(tn)

    # 5. Coordinate-match GTFS stations → Infrabel Dutch names
    parents_with_coords = stops.filter(pl.col("location_type") == 1).select(
        ["stop_name", "stop_lat", "stop_lon"]
    )
    gtfs_list = [
        (row[0], float(row[1]), float(row[2]))
        for row in parents_with_coords.iter_rows()
    ]

    def _haversine_m(lat1, lon1, lat2, lon2):
        R = 6371000
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = (math.sin(dlat / 2) ** 2
             + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
             * math.sin(dlon / 2) ** 2)
        return R * 2 * math.asin(math.sqrt(a))

    # Map Infrabel station name → closest GTFS station (within 1km)
    result: dict[str, set[str]] = {}
    for infra_name, coords in station_coords.items():
        lat, lon = coords["lat"], coords["lon"]
        best_dist = 1000
        best_gtfs = None
        for gname, glat, glon in gtfs_list:
            d = _haversine_m(lat, lon, glat, glon)
            if d < best_dist:
                best_dist = d
                best_gtfs = gname
        if best_gtfs and best_gtfs in gtfs_trains:
            result[infra_name] = gtfs_trains[best_gtfs]

    return result


@cached(ttl=86400)
def load_commercial_stops(month_ts: int) -> dict[str, set[str]]:
    """Return {UPPER_STATION_NL: set[train_no]} of commercial stops for a month.

    Fetches the GTFS feed + operational points for that month, then builds
    the mapping. Cached for 24h since GTFS doesn't change within a month.
    """
    try:
        feed = fetch_gtfs(month_ts, TOKEN)
    except Exception:
        logger.warning("Failed to fetch GTFS for ts=%s, skipping commercial stop filter", month_ts)
        return {}
    # Need station_coords for the coord matching
    op_points = _safe_fetch(fetch_operational_points, month_ts, TOKEN)
    station_coords: dict[str, dict] = {}
    if op_points and "features" in op_points:
        for feat in op_points["features"]:
            props = feat.get("properties") or {}
            name = (props.get("longnamedutch") or "").strip().upper()
            if not name:
                continue
            pt = props.get("geo_point_2d") or {}
            lat, lon = pt.get("lat"), pt.get("lon")
            if lat and lon:
                station_coords[name] = {"lat": lat, "lon": lon}
    if not station_coords:
        return {}
    return _build_commercial_stops(feed, station_coords)


def filter_passthrough_records(records: list[dict], commercial_stops: dict[str, set[str]]) -> list[dict]:
    """Filter out records where the train doesn't commercially stop at the station.

    If commercial_stops is empty (GTFS unavailable), returns all records unchanged.
    """
    if not commercial_stops:
        return records
    return [
        r for r in records
        if str(r.get("train_no", "")) in commercial_stops.get(
            (r.get("ptcar_lg_nm_nl") or "").strip().upper(), set()
        )
    ]



@cached(ttl=3600)
def load_punctuality_data(target_date: date) -> dict:
    """Load punctuality data for a single date."""
    ts = noon_timestamp(target_date.year, target_date.month, target_date.day)

    try:
        records = fetch_punctuality(ts, TOKEN)
    except Exception as e:
        return {"error": str(e)}

    if records is None or len(records) == 0:
        return {"error": "No punctuality data available"}

    op_points = _safe_fetch(fetch_operational_points, ts, TOKEN)

    station_coords = {}
    if op_points and "features" in op_points:
        for feat in op_points["features"]:
            props = feat.get("properties") or {}
            name = (props.get("longnamedutch") or "").strip().upper()
            if not name:
                continue
            pt = props.get("geo_point_2d") or {}
            lat, lon = pt.get("lat"), pt.get("lon")
            if lat and lon:
                station_coords[name] = {"lat": lat, "lon": lon}

    return {
        "records": records,
        "station_coords": station_coords,
    }


@cached(ttl=3600)
def load_scheduled_trains(target_date: date) -> dict:
    """Return GTFS-scheduled SNCB trains for *target_date* — lean shape.

    Output::

        {
            "trains": {
                train_no: {
                    "stops": tuple[str, ...],   # UPPER-CASE station names, in order
                    "duration_min": float,
                    "first_dep_hour": int,
                },
                ...
            },
            "station_coords": {UPPER_NAME: {"lat", "lon"}},  # only Belgium parents
        }

    Only trains with >=1 commercial stop (GTFS pickup_type=0 or
    drop_off_type=0) are included.  train_no == GTFS trip_short_name;
    consumer matches against Infrabel ``train_no``.

    Memory: stop lists are stored as tuples of deduplicated station
    name strings (interned via a local pool) so a 31-day cache window
    stays under ~150 MB in practice.
    """
    import polars as pl

    ts = noon_timestamp(target_date.year, target_date.month, 15)
    try:
        feed = fetch_gtfs(ts, TOKEN)
    except Exception as e:
        logger.warning("Failed to fetch GTFS for %s: %s", target_date, e)
        return {"trains": {}, "station_coords": {}}

    if feed.trips is None or feed.stop_times is None or feed.stops is None:
        return {"trains": {}, "station_coords": {}}

    sdc = get_service_day_counts(feed, [target_date])
    active_sids = [s for s, n in sdc.items() if n > 0]
    if not active_sids:
        return {"trains": {}, "station_coords": {}}

    trips = feed.trips.filter(pl.col("service_id").is_in(active_sids)).select(
        ["trip_id", "trip_short_name"],
    ).filter(
        pl.col("trip_short_name").is_not_null() & (pl.col("trip_short_name") != ""),
    )
    if trips.height == 0:
        return {"trains": {}, "station_coords": {}}

    parents = feed.stops.filter(pl.col("location_type") == 1).select(
        pl.col("stop_id").alias("pid"),
        pl.col("stop_name").alias("parent_name"),
        pl.col("stop_lat").alias("parent_lat"),
        pl.col("stop_lon").alias("parent_lon"),
    )
    stop_map = feed.stops.select(
        ["stop_id", "parent_station", "stop_name", "stop_lat",
         "stop_lon", "location_type"],
    ).join(parents, left_on="parent_station", right_on="pid", how="left")
    stop_map = stop_map.with_columns(
        pl.coalesce(["parent_name", "stop_name"]).alias("station_name"),
        pl.coalesce(["parent_lat", "stop_lat"]).alias("station_lat"),
        pl.coalesce(["parent_lon", "stop_lon"]).alias("station_lon"),
    ).select(["stop_id", "station_name", "station_lat", "station_lon"])

    # Aggregate per-trip in Polars: ordered list of station names + first/last times
    st = (
        feed.stop_times
        .filter((pl.col("pickup_type") == 0) | (pl.col("drop_off_type") == 0))
        .select(["trip_id", "stop_id", "stop_sequence",
                 "arrival_time", "departure_time"])
        .join(trips, on="trip_id")
        .join(stop_map, on="stop_id")
        .with_columns(
            pl.col("arrival_time").dt.total_seconds().alias("arr_sec"),
            pl.col("departure_time").dt.total_seconds().alias("dep_sec"),
            pl.col("station_name").str.strip_chars().str.to_uppercase()
                .alias("station_up"),
        )
        .sort(["trip_short_name", "stop_sequence"])
    )

    agg = st.group_by("trip_short_name").agg(
        pl.col("station_up").alias("stops"),
        pl.col("arr_sec").first().alias("arr0"),
        pl.col("dep_sec").first().alias("dep0"),
        pl.col("arr_sec").last().alias("arrN"),
        pl.col("dep_sec").last().alias("depN"),
    )

    # Build Belgium-only station coord map (parent stations only, small).
    from logic.geo import is_in_belgium
    station_coords: dict[str, dict] = {}
    for row in parents.iter_rows(named=True):
        lat = row["parent_lat"]
        lon = row["parent_lon"]
        name = (row["parent_name"] or "").strip().upper()
        if not name or lat is None or lon is None:
            continue
        if not is_in_belgium(float(lat), float(lon)):
            continue
        station_coords.setdefault(name, {"lat": float(lat), "lon": float(lon)})

    # Intern station name strings so repeated occurrences share memory.
    name_pool: dict[str, str] = {n: n for n in station_coords}

    trains: dict[str, dict] = {}
    for row in agg.iter_rows(named=True):
        tn = str(row["trip_short_name"])
        if not tn:
            continue
        raw_stops = row["stops"] or []
        if not raw_stops:
            continue
        stops_tup = tuple(
            name_pool.setdefault(s, s) for s in raw_stops if s
        )
        if not stops_tup:
            continue

        arr0 = row["arr0"] if row["arr0"] is not None else -1
        dep0 = row["dep0"] if row["dep0"] is not None else -1
        arrN = row["arrN"] if row["arrN"] is not None else -1
        depN = row["depN"] if row["depN"] is not None else -1
        start = dep0 if dep0 >= 0 else arr0
        end = arrN if arrN >= 0 else depN
        duration_sec = max(end - start, 0) if (start >= 0 and end >= 0) else 0

        trains[tn] = {
            "stops": stops_tup,
            "duration_min": round(duration_sec / 60, 1),
            "first_dep_hour": int(start // 3600) if start >= 0 else -1,
        }

    return {"trains": trains, "station_coords": station_coords}
