"""Data loading and processing services.

Wraps the existing logic/ modules with caching for the FastAPI app.
"""

import logging
import os
from collections import defaultdict
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
    served = data["served_stations"]
    max_minutes = time_budget * 60

    stations = []
    reachable_counts = []

    for sid in served:
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

        dests = []
        for dest_id, r_info in reachable.items():
            d_info = stop_lookup.get(dest_id)
            if d_info:
                dests.append({
                    "name": d_info["name"],
                    "lat": d_info["lat"],
                    "lon": d_info["lon"],
                    "time": round(r_info["travel_time"], 1),
                })

        stations.append({
            "id": sid,
            "name": info["name"],
            "lat": info["lat"],
            "lon": info["lon"],
            "reachable": n_reach,
            "destinations": sorted(dests, key=lambda d: d["time"]),
        })

    stations.sort(key=lambda s: -s["reachable"])

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
    served = data["served_stations"]
    n_feeds = data["n_feeds"]
    max_minutes = time_budget * 60
    prov_geo = data["prov_geo"]

    stations = []
    counts = {"Small": 0, "Medium": 0, "Big": 0}

    for sid in served:
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

        counts[size] = counts.get(size, 0) + 1

        stations.append({
            "name": info["name"],
            "lat": info["lat"],
            "lon": info["lon"],
            "reachable": a_count,
            "direct_freq": b_freq,
            "reach_km": c_reach,
            "size": size.lower(),
            "region": region,
        })

    stations.sort(key=lambda s: -s["reachable"])

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


@cached(ttl=3600)
def load_punctuality_data(target_date: date, hour_range: tuple[int, int] = (5, 24)) -> dict:
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
