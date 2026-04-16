"""JSON API routes for data endpoints."""

import asyncio
import io
import json
import math
import os
import urllib.request
from collections import defaultdict
from datetime import date, timedelta
from functools import lru_cache
from typing import Any

import numpy as np
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse as _JSONResponse

from logic.api import OPERATORS, fetch_gtfs_operator, punctuality_ts
from logic.geo import BE_LAT_MAX, BE_LAT_MIN, BE_LON_MAX, BE_LON_MIN, get_province
from logic.geocoding import geocode_address
from logic.multimodal import (
    bfs_from_point,
    bfs_from_stops,
    bfs_to_point,
    build_multimodal_graph,
    build_multimodal_stop_lookup,
    build_transfer_edges,
    get_active_service_ids,
)
from logic.reachability import (
    build_reverse_timetable_graph,
    compute_reachability_single,
    compute_reachability_to_dest,
)
from logic.rendering import _get_belgium_border
from logic.shared import load_provinces_geojson, noon_timestamp

from services.data import (
    load_connectivity_data,
    load_duration_data,
    load_gtfs_data,
    load_punctuality_data,
    load_reach_data,
    load_segments,
    prefetch_punctuality,
)


class _NumpyEncoder(json.JSONEncoder):
    """JSON encoder that handles numpy types."""
    def default(self, obj: Any) -> Any:
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)


class JSONResponse(_JSONResponse):
    """JSONResponse with numpy type support."""
    def render(self, content: Any) -> bytes:
        return json.dumps(content, cls=_NumpyEncoder, ensure_ascii=False).encode("utf-8")


router = APIRouter()

TOKEN = os.getenv("BRUSSELS_MOBILITY_TWIN_KEY", "")

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _defaults(start: str | None, end: str | None, days_back: int = 7):
    """Return (start_date, end_date) with sensible defaults."""
    today = date.today()
    if end:
        end_date = date.fromisoformat(end)
    else:
        end_date = today
    if start:
        start_date = date.fromisoformat(start)
    else:
        start_date = end_date - timedelta(days=days_back)
    return start_date, end_date


def _wd(weekdays_str: str | None) -> tuple[int, ...]:
    """Parse '0,1,2,3,4' into a tuple of ints."""
    if not weekdays_str:
        return (0, 1, 2, 3, 4)
    return tuple(int(x.strip()) for x in weekdays_str.split(",") if x.strip().isdigit())


def _hf(hour_start: int | None, hour_end: int | None) -> tuple[int, int] | None:
    """Return hour filter tuple or None."""
    if hour_start is not None and hour_end is not None:
        return (int(hour_start), int(hour_end))
    return None


def _date_range(start: date, end: date):
    """Yield dates from start to end inclusive."""
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def _station_name(rec: dict) -> str:
    """Extract upper-cased station name from punctuality record."""
    return (rec.get("ptcar_lg_nm_nl") or "").strip().upper()


def _parse_hour(time_str: str) -> int:
    """Parse 'HH:MM:SS' to int hour. Returns -1 on failure."""
    try:
        return int(str(time_str).split(":")[0])
    except (ValueError, IndexError):
        return -1


def _excluded_dates(start_d: date, end_d: date, exclude_pub: bool, exclude_sch: bool) -> set:
    """Build set of dates to exclude based on holiday filters."""
    from logic.holidays import public_holidays_in_range
    excluded: set = set()
    if exclude_pub:
        excluded |= set(public_holidays_in_range(start_d, end_d).keys())
    if exclude_sch:
        from logic.holidays import SCHOOL_HOLIDAYS
        for s, e, _ in SCHOOL_HOLIDAYS:
            d = s
            while d <= e:
                excluded.add(d)
                d += timedelta(days=1)
    return excluded


def _filter_dates(start_d: date, end_d: date, weekdays: tuple[int, ...],
                  exclude_pub: bool = False, exclude_sch: bool = False) -> list[date]:
    """Return list of dates in range matching weekday + holiday filters."""
    excluded = _excluded_dates(start_d, end_d, exclude_pub, exclude_sch) if (exclude_pub or exclude_sch) else set()
    return [d for d in _date_range(start_d, end_d)
            if d.weekday() in weekdays and d not in excluded]


def _fetch_weather(lat: float, lon: float, start_date: date, end_date: date) -> dict | None:
    """Fetch daily weather from Open-Meteo archive API."""
    params = (
        f"latitude={lat}&longitude={lon}"
        f"&start_date={start_date.isoformat()}&end_date={end_date.isoformat()}"
        f"&daily=temperature_2m_mean,precipitation_sum,rain_sum,snowfall_sum,"
        f"wind_speed_10m_max,wind_gusts_10m_max"
        f"&timezone=Europe/Brussels"
    )
    url = f"https://archive-api.open-meteo.com/v1/archive?{params}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "MobilityTwin/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def _fetch_weather_hourly(lat: float, lon: float, start_date: date, end_date: date) -> dict | None:
    """Fetch hourly weather from Open-Meteo archive API."""
    params = (
        f"latitude={lat}&longitude={lon}"
        f"&start_date={start_date.isoformat()}&end_date={end_date.isoformat()}"
        f"&hourly=precipitation,rain,snowfall,wind_speed_10m,wind_gusts_10m,temperature_2m"
        f"&timezone=Europe/Brussels"
    )
    url = f"https://archive-api.open-meteo.com/v1/archive?{params}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "MobilityTwin/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/provinces")
async def api_provinces():
    """Return Belgium provinces GeoJSON."""
    return JSONResponse(content=load_provinces_geojson())

@router.get("/segments")
async def api_segments(
    start: str | None = None,
    end: str | None = None,
    weekdays: str | None = None,
    hour_start: int | None = None,
    hour_end: int | None = None,
    exclude_pub: bool = False,
    exclude_sch: bool = False,
):
    """Return segment frequency data for the map."""
    start_date, end_date = _defaults(start, end)
    result = await asyncio.to_thread(
        load_segments,
        start_date, end_date, _wd(weekdays), _hf(hour_start, hour_end),
        exclude_pub, exclude_sch,
    )
    return JSONResponse(content=result)


@router.get("/punctuality")
async def api_punctuality(
    target_date: str | None = None,
    hour_start: int = 5,
    hour_end: int = 24,
    min_trains: int = 5,
    delay_floor: float = 0,
    delay_cap: float = 30,
    exclude_out_of_range: bool = False,
    metric: str = "departure",
):
    """Return per-station punctuality stats for a single date."""
    if target_date:
        td = date.fromisoformat(target_date)
    else:
        td = date.today() - timedelta(days=2)

    data = await asyncio.to_thread(load_punctuality_data, td, (hour_start, hour_end))
    if "error" in data:
        return JSONResponse(content={"error": data["error"]})

    records = data["records"]
    station_coords = data["station_coords"]

    delay_col = "delay_dep" if metric == "departure" else "delay_arr"
    time_col = "planned_time_dep" if metric == "departure" else "planned_time_arr"

    # Aggregate per station
    station_data: dict[str, dict] = defaultdict(lambda: {"delays": []})

    for rec in records:
        name = _station_name(rec)
        if not name:
            continue
        # Hour filter
        hour = _parse_hour(rec.get(time_col, ""))
        if hour < hour_start or hour >= hour_end:
            continue
        # Parse delay
        try:
            delay_sec = float(rec.get(delay_col, 0) or 0)
        except (ValueError, TypeError):
            continue
        delay_min = delay_sec / 60.0

        if exclude_out_of_range:
            if delay_min < delay_floor or delay_min > delay_cap:
                continue
        else:
            if delay_min < delay_floor:
                delay_min = 0.0
            delay_min = min(delay_min, delay_cap)

        station_data[name]["delays"].append(delay_min)

    stations = []
    all_avg_delays = []

    for name, info in station_data.items():
        delays = info["delays"]
        if len(delays) < min_trains:
            continue
        avg_delay = round(sum(delays) / len(delays), 1)
        n_trains = len(delays)
        pct_late = round(sum(1 for d in delays if d > 1) / n_trains * 100, 1)

        coords = station_coords.get(name)
        if not coords:
            continue

        stations.append({
            "name": name,
            "lat": coords["lat"],
            "lon": coords["lon"],
            "avg_delay": avg_delay,
            "n_trains": n_trains,
            "pct_late": pct_late,
        })
        all_avg_delays.append(avg_delay)

    stations.sort(key=lambda s: -s["avg_delay"])

    if all_avg_delays:
        sorted_delays = sorted(all_avg_delays)
        mid = len(sorted_delays) // 2
        median_delay = (
            sorted_delays[mid]
            if len(sorted_delays) % 2
            else round((sorted_delays[mid - 1] + sorted_delays[mid]) / 2, 1)
        )
        avg_delay_overall = round(sum(all_avg_delays) / len(all_avg_delays), 1)
        pct_late_overall = round(
            sum(1 for d in all_avg_delays if d > 1) / len(all_avg_delays) * 100, 1
        )
    else:
        median_delay = 0
        avg_delay_overall = 0
        pct_late_overall = 0

    # Hourly aggregation
    hourly_data: dict[int, list[float]] = defaultdict(list)
    for rec in records:
        name = _station_name(rec)
        if not name:
            continue
        hour = _parse_hour(rec.get(time_col, ""))
        if hour < hour_start or hour >= hour_end:
            continue
        try:
            delay_sec = float(rec.get(delay_col, 0) or 0)
        except (ValueError, TypeError):
            continue
        delay_min = delay_sec / 60.0
        if exclude_out_of_range:
            if delay_min < delay_floor or delay_min > delay_cap:
                continue
        else:
            if delay_min < delay_floor:
                delay_min = 0.0
            delay_min = min(delay_min, delay_cap)
        hourly_data[hour].append(delay_min)

    hourly = []
    for h in range(hour_start, hour_end):
        delays_h = hourly_data.get(h, [])
        if delays_h:
            hourly.append({"hour": h, "avg_delay": round(sum(delays_h) / len(delays_h), 1), "n_trains": len(delays_h)})
        else:
            hourly.append({"hour": h, "avg_delay": 0, "n_trains": 0})

    return JSONResponse(content={
        "summary": {
            "n_stations": len(stations),
            "avg_delay": str(avg_delay_overall),
            "median_delay": str(median_delay),
            "pct_late": str(pct_late_overall),
        },
        "stations": stations,
        "hourly": hourly,
    })


@router.get("/reach")
async def api_reach(
    start: str | None = None,
    end: str | None = None,
    weekdays: str | None = None,
    hour_start: int | None = None,
    hour_end: int | None = None,
    exclude_pub: bool = False,
    exclude_sch: bool = False,
    time_budget: float = 1.5,
    dep_start: int = 7,
    dep_end: int = 9,
    max_transfers: int = 3,
    min_transfer_time: int = 5,
):
    """Compute reachability for each station."""
    start_date, end_date = _defaults(start, end)
    result = await asyncio.to_thread(
        load_reach_data,
        start_date, end_date, _wd(weekdays), _hf(hour_start, hour_end),
        exclude_pub, exclude_sch,
        time_budget, dep_start, dep_end, max_transfers, min_transfer_time,
    )
    return JSONResponse(content=result)


@router.get("/duration")
async def api_duration(
    start: str | None = None,
    end: str | None = None,
    weekdays: str | None = None,
    hour_start: int | None = None,
    hour_end: int | None = None,
    exclude_pub: bool = False,
    exclude_sch: bool = False,
    direction: str = "to",
    destinations: str = "Bruxelles-Central",
    time_budget: float = 3.0,
    dep_start: int = 7,
    dep_end: int = 9,
    max_transfers: int = 3,
):
    """Compute travel duration from/to destination station(s)."""
    start_date, end_date = _defaults(start, end)
    dest_tuple = tuple(d.strip() for d in destinations.split(",") if d.strip())
    result = await asyncio.to_thread(
        load_duration_data,
        start_date, end_date, _wd(weekdays), _hf(hour_start, hour_end),
        exclude_pub, exclude_sch,
        direction, dest_tuple, time_budget, dep_start, dep_end, max_transfers,
    )
    return JSONResponse(content=result)


@router.get("/connectivity")
async def api_connectivity(
    start: str | None = None,
    end: str | None = None,
    weekdays: str | None = None,
    hour_start: int | None = None,
    hour_end: int | None = None,
    exclude_pub: bool = False,
    exclude_sch: bool = False,
    time_budget: float = 2.0,
    max_transfers: int = 2,
    dep_start: int = 7,
    dep_end: int = 9,
):
    """Compute connectivity metrics (reachable, freq, reach_km) per station."""
    start_date, end_date = _defaults(start, end)
    result = await asyncio.to_thread(
        load_connectivity_data,
        start_date, end_date, _wd(weekdays), _hf(hour_start, hour_end),
        exclude_pub, exclude_sch,
        time_budget, max_transfers, dep_start, dep_end,
    )
    return JSONResponse(content=result)


@router.get("/multimodal")
async def api_multimodal(
    address: str = "",
    operators: str = "SNCB,De Lijn,STIB,TEC",
    direction: str = "from",
    time_budget: float = 1.5,
    dep_start: int = 7,
    dep_end: int = 9,
    max_transfers: int = 3,
    last_mile: str = "Walk",
    travel_date: str | None = None,
):
    """Compute multimodal reachability from/to an address."""
    if not address:
        return JSONResponse(content={"error": "Address is required"})

    def _compute():
        geo = geocode_address(address)
        if not geo:
            return {"error": f"Could not geocode address: {address}"}

        origin_lat, origin_lon = geo["lat"], geo["lon"]
        geocoded_name = geo["display_name"]

        if travel_date:
            td = date.fromisoformat(travel_date)
        else:
            td = date.today()

        ts = noon_timestamp(td.year, td.month, td.day)

        selected_ops = [o.strip() for o in operators.split(",") if o.strip()]

        # Load feeds for each operator, falling back to earlier days if the
        # upstream parquet for the requested timestamp is missing/corrupt.
        feeds = {}
        service_ids_per_op = {}
        warnings: list[str] = []
        for op_name in selected_ops:
            slug = OPERATORS.get(op_name)
            if not slug:
                warnings.append(f"Unknown operator: {op_name}")
                continue
            last_err: Exception | None = None
            for delta in range(0, 10):
                try_td = td - timedelta(days=delta)
                try_ts = noon_timestamp(try_td.year, try_td.month, try_td.day)
                try:
                    feed = fetch_gtfs_operator(slug, try_ts, TOKEN)
                    sids = get_active_service_ids(feed, [try_td])
                    if not sids:
                        last_err = RuntimeError("no active services")
                        continue
                    feeds[op_name] = feed
                    service_ids_per_op[op_name] = sids
                    if delta > 0:
                        warnings.append(
                            f"{op_name}: used GTFS from {try_td.isoformat()} "
                            f"({delta}d before requested date)"
                        )
                    break
                except Exception as e:
                    last_err = e
            else:
                warnings.append(f"{op_name}: failed to load GTFS ({last_err})")

        if not feeds:
            return {"error": "No GTFS feeds could be loaded", "warnings": warnings}

        # Build multimodal graph
        mm_departures = build_multimodal_graph(feeds, service_ids_per_op)
        mm_stop_lookup = build_multimodal_stop_lookup(feeds)
        transfer_edges = build_transfer_edges(mm_stop_lookup, max_walk_km=0.4)

        max_minutes = time_budget * 60

        # Run BFS
        if direction == "from":
            results = bfs_from_point(
                origin_lat, origin_lon, mm_stop_lookup, mm_departures,
                transfer_edges, max_minutes,
                departure_window=(dep_start, dep_end),
                max_transfers=max_transfers,
            )
        else:
            results = bfs_to_point(
                origin_lat, origin_lon, mm_stop_lookup, mm_departures,
                transfer_edges, max_minutes,
                departure_window=(dep_start, dep_end),
                max_transfers=max_transfers,
            )

        # Build station list
        stations = []
        operators_seen = set()
        for stop_id, r_info in results.items():
            s_info = mm_stop_lookup.get(stop_id)
            if not s_info:
                continue
            op = s_info.get("operator", "")
            operators_seen.add(op)
            stations.append({
                "name": s_info["name"],
                "lat": s_info["lat"],
                "lon": s_info["lon"],
                "duration": round(r_info["travel_time"], 1),
                "operator": op,
            })

        stations.sort(key=lambda s: s["duration"])

        if stations:
            avg_dur = round(sum(s["duration"] for s in stations) / len(stations), 1)
        else:
            avg_dur = 0

        return {
            "n_reachable": len(stations),
            "avg_duration": avg_dur,
            "operators_used": len(operators_seen),
            "geocoded_address": geocoded_name,
            "origin": {"lat": origin_lat, "lon": origin_lon},
            "stations": stations,
            "warnings": warnings,
        }

    async def _stream():
        loop = asyncio.get_event_loop()
        future = loop.run_in_executor(None, _compute)

        while True:
            try:
                item = await asyncio.to_thread(progress_q.get, timeout=0.3)
            except Exception:
                if future.done():
                    break
                continue
            if item is None:
                break
            done, total = item
            payload = json.dumps({"done": done, "total": total})
            yield f"event: progress\ndata: {payload}\n\n"

        result = await future
        result_payload = json.dumps(result, cls=_NumpyEncoder)
        yield f"event: result\ndata: {result_payload}\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream")


@router.get("/accessibility")
async def api_accessibility(
    dest_operators: str = "SNCB",
    use_feeder: bool = True,
    feeder_operators: str = "De Lijn,STIB,TEC",
    feeder_dep_start: int = 7,
    feeder_dep_end: int = 9,
    feeder_max_time: int = 60,
    transport: str = "Walk",
    max_time: int = 200,
    resolution: int = 200,
    target_date: str | None = None,
):
    """Compute accessibility grid: time to nearest stop across Belgium."""
    def _compute():
        import base64
        from PIL import Image
        from shapely.geometry import Point
        from shapely import prepared as shp_prepared

        if target_date:
            td = date.fromisoformat(target_date)
        else:
            td = date.today() - timedelta(days=1)

        ts = noon_timestamp(td.year, td.month, td.day)

        dest_ops = [o.strip() for o in dest_operators.split(",") if o.strip()]
        feeder_ops = [o.strip() for o in feeder_operators.split(",") if o.strip()] if use_feeder else []

        # Load destination stops
        all_ops = list(set(dest_ops + feeder_ops))
        feeds = {}
        service_ids_per_op = {}
        for op_name in all_ops:
            slug = OPERATORS.get(op_name)
            if not slug:
                continue
            try:
                feed = fetch_gtfs_operator(slug, ts, TOKEN)
                feeds[op_name] = feed
                sids = get_active_service_ids(feed, [td])
                service_ids_per_op[op_name] = sids
            except Exception:
                continue

        if not feeds:
            return {"error": "No GTFS feeds could be loaded"}

        mm_stop_lookup = build_multimodal_stop_lookup(feeds)

        # Get destination stop IDs
        dest_stop_ids = set()
        for stop_id, info in mm_stop_lookup.items():
            if info.get("operator") in dest_ops:
                dest_stop_ids.add(stop_id)

        if not dest_stop_ids:
            return {"error": "No destination stops found"}

        # If feeder is used, run multi-source BFS to expand reachability
        if use_feeder and feeder_ops:
            mm_departures = build_multimodal_graph(
                {op: feeds[op] for op in feeder_ops if op in feeds},
                {op: service_ids_per_op.get(op, set()) for op in feeder_ops},
            )
            transfer_edges = build_transfer_edges(mm_stop_lookup, max_walk_km=0.4)

            bfs_results = bfs_from_stops(
                dest_stop_ids, mm_stop_lookup, mm_departures, transfer_edges,
                max_minutes=feeder_max_time,
                departure_window=(feeder_dep_start, feeder_dep_end),
                max_transfers=2,
            )

            # Add BFS-reachable stops (treated as reachable via feeder)
            for stop_id, r_info in bfs_results.items():
                if stop_id not in dest_stop_ids:
                    dest_stop_ids.add(stop_id)

        # Collect coordinates and build grid
        stop_lats = []
        stop_lons = []
        for sid in dest_stop_ids:
            info = mm_stop_lookup.get(sid)
            if info:
                stop_lats.append(info["lat"])
                stop_lons.append(info["lon"])

        n_stops = len(stop_lats)
        if n_stops == 0:
            return {"error": "No stops with coordinates"}

        s_lats = np.array(stop_lats, dtype=np.float64)
        s_lons = np.array(stop_lons, dtype=np.float64)

        # Transport speed
        speed_map = {"Walk": 5, "Bike": 15, "Car": 50}
        speed_kmh = speed_map.get(transport, 5)

        lat_lin = np.linspace(BE_LAT_MIN, BE_LAT_MAX, resolution)
        lon_lin = np.linspace(BE_LON_MIN, BE_LON_MAX, resolution)

        grid_lat = lat_lin[:, None]
        grid_lon = lon_lin[None, :]

        # Compute grid time to nearest stop
        chunk = 20
        grid_time = np.full((resolution, resolution), np.inf)
        for s_start in range(0, len(s_lats), chunk):
            s_end = min(s_start + chunk, len(s_lats))
            dlat = np.abs(grid_lat[:, :, None] - s_lats[None, None, s_start:s_end]) * 111.0
            dlon = np.abs(grid_lon[:, :, None] - s_lons[None, None, s_start:s_end]) * 71.0
            total = (dlat + dlon) / speed_kmh * 60.0
            np.minimum(grid_time, total.min(axis=2), out=grid_time)

        # Belgium border mask
        prov_geo = load_provinces_geojson()
        belgium = _get_belgium_border(prov_geo)
        belgium_prep = shp_prepared.prep(belgium)

        mask = np.zeros((resolution, resolution), dtype=bool)
        step = 4
        for i in range(0, resolution, step):
            for j in range(0, resolution, step):
                inside = belgium_prep.contains(Point(lon_lin[j], lat_lin[i]))
                i_end = min(i + step, resolution)
                j_end = min(j + step, resolution)
                if inside:
                    mask[i:i_end, j:j_end] = True
        for i in range(resolution):
            for j in range(resolution):
                bi, bj = i % step, j % step
                if bi == 0 or bj == 0 or bi == step - 1 or bj == step - 1:
                    mask[i, j] = belgium_prep.contains(Point(lon_lin[j], lat_lin[i]))

        grid_time[~mask] = np.nan
        grid_time[grid_time > max_time] = np.nan

        valid_times = grid_time[~np.isnan(grid_time)]
        if len(valid_times) == 0:
            return {"error": "No accessible area within time budget"}

        median_time = round(float(np.median(valid_times)), 1)
        mean_time = round(float(np.mean(valid_times)), 1)
        p95_time = round(float(np.percentile(valid_times, 95)), 1)
        pct_5min = round(float(np.mean(valid_times <= 5) * 100), 1)
        pct_10min = round(float(np.mean(valid_times <= 10) * 100), 1)
        pct_15min = round(float(np.mean(valid_times <= 15) * 100), 1)
        pct_20min = round(float(np.mean(valid_times <= 20) * 100), 1)
        pct_30min = round(float(np.mean(valid_times <= 30) * 100), 1)

        # Render image
        effective_max = min(float(np.nanmax(grid_time[mask])) if np.any(mask & ~np.isnan(grid_time)) else max_time, max_time)
        grid_display = np.clip(grid_time, 0, effective_max)

        ratio = grid_display / effective_max if effective_max > 0 else np.zeros_like(grid_display)
        ratio = np.clip(ratio, 0, 1)
        ratio = np.nan_to_num(ratio, nan=0.0)

        r = np.zeros((resolution, resolution), dtype=np.uint8)
        g = np.zeros((resolution, resolution), dtype=np.uint8)
        b = np.zeros((resolution, resolution), dtype=np.uint8)

        lo = ratio < 0.5
        hi = ~lo
        r2_lo = ratio * 2
        r2_hi = (ratio - 0.5) * 2

        r[lo] = np.clip(34 + (255 - 34) * r2_lo[lo], 0, 255).astype(np.uint8)
        g[lo] = np.clip(180 - 40 * r2_lo[lo], 0, 255).astype(np.uint8)
        b[lo] = np.clip(34 - 30 * r2_lo[lo], 0, 255).astype(np.uint8)

        r[hi] = np.clip(255 - 35 * r2_hi[hi], 0, 255).astype(np.uint8)
        g[hi] = np.clip(140 - 120 * r2_hi[hi], 0, 255).astype(np.uint8)
        b[hi] = np.clip(4 + 30 * r2_hi[hi], 0, 255).astype(np.uint8)

        valid_mask = mask & ~np.isnan(grid_display)
        rgba = np.zeros((resolution, resolution, 4), dtype=np.uint8)
        rgba[valid_mask, 0] = r[valid_mask]
        rgba[valid_mask, 1] = g[valid_mask]
        rgba[valid_mask, 2] = b[valid_mask]
        rgba[valid_mask, 3] = 180

        rgba_flipped = np.flipud(rgba)
        img = Image.fromarray(rgba_flipped, "RGBA")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        image_b64 = base64.b64encode(buf.read()).decode()

        # Build stop list for stations view
        stops_list = []
        for sid in dest_stop_ids:
            info = mm_stop_lookup.get(sid)
            if info:
                stops_list.append({
                    "name": info.get("name", ""),
                    "lat": info["lat"],
                    "lon": info["lon"],
                    "operator": info.get("operator", ""),
                })

        return {
            "n_stops": n_stops,
            "median_time": median_time,
            "mean_time": mean_time,
            "p95_time": p95_time,
            "pct_5min": pct_5min,
            "pct_10min": pct_10min,
            "pct_15min": pct_15min,
            "pct_20min": pct_20min,
            "pct_30min": pct_30min,
            "image_b64": image_b64,
            "stops": stops_list,
        }

    async def _stream():
        loop = asyncio.get_event_loop()
        future = loop.run_in_executor(None, _compute)

        while True:
            try:
                item = await asyncio.to_thread(progress_q.get, timeout=0.3)
            except Exception:
                if future.done():
                    break
                continue
            if item is None:
                break
            done, total = item
            payload = json.dumps({"done": done, "total": total})
            yield f"event: progress\ndata: {payload}\n\n"

        result = await future
        result_payload = json.dumps(result, cls=_NumpyEncoder)
        yield f"event: result\ndata: {result_payload}\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream")



@router.get("/propagation")
async def api_propagation(
    start: str | None = None,
    end: str | None = None,
    min_increase: int = 60,
    min_incidents: int = 3,
    hour_start: int = 0,
    hour_end: int = 24,
    view: str = "stations",
):
    """Analyse delay propagation across a date range."""
    def _compute():
        import pandas as pd

        start_date, end_date = _defaults(start, end)
        n_days = (end_date - start_date).days + 1
        if n_days > 30:
            return {"error": "Max 30 days"}

        # Accumulators
        sta_total: dict[str, float] = defaultdict(float)
        sta_count: dict[str, int] = defaultdict(int)
        sta_trips: dict[str, int] = defaultdict(int)
        # Segment accumulators for segment view
        seg_total: dict[tuple, float] = defaultdict(float)
        seg_count: dict[tuple, int] = defaultdict(int)
        seg_trips: dict[tuple, int] = defaultdict(int)

        prefetch_punctuality(list(_date_range(start_date, end_date)))

        for d in _date_range(start_date, end_date):
            try:
                data = load_punctuality_data(d)
            except Exception:
                continue
            if "error" in data:
                continue

            records = data["records"]
            if not records:
                continue

            df = pd.DataFrame(records)
            df["delay_dep_sec"] = pd.to_numeric(df["delay_dep"], errors="coerce")
            df = df.dropna(subset=["delay_dep_sec"])

            # Parse hour
            hours = pd.to_numeric(
                df["planned_time_dep"].astype(str).str.split(":").str[0], errors="coerce"
            ).fillna(-1).astype(int)
            mask = (hours >= hour_start) & (hours < hour_end)
            df = df[mask.values]

            if df.empty:
                continue

            stations = df["ptcar_lg_nm_nl"].str.strip().str.upper().values
            train_nos = np.asarray(df["train_no"].values, dtype=object)
            delays = df["delay_dep_sec"].values.copy()

            # Count total departures per station
            for sname in stations:
                sta_trips[sname] += 1

            # Sort by (train_no, planned_time_dep)
            dep_minutes = pd.to_numeric(
                df["planned_time_dep"].astype(str).str.split(":").str[0], errors="coerce"
            ).fillna(0).astype(int).values * 60 + pd.to_numeric(
                df["planned_time_dep"].astype(str).str.split(":").str[1], errors="coerce"
            ).fillna(0).astype(int).values

            order = np.lexsort((dep_minutes, train_nos))
            stations = stations[order]
            train_nos = train_nos[order]
            delays = delays[order]

            # Count trips per consecutive segment (same train)
            same_train = train_nos[1:] == train_nos[:-1]
            for i in np.where(same_train)[0]:
                seg_key = (stations[i], stations[i + 1])
                seg_trips[seg_key] += 1

            # Find consecutive increases within same train
            increases = delays[1:] - delays[:-1]
            hits = same_train & (increases > min_increase)
            idx = np.where(hits)[0]

            for i in idx:
                from_station = stations[i]
                to_station = stations[i + 1]
                sta_total[to_station] += float(increases[i])
                sta_count[to_station] += 1
                seg_key = (from_station, to_station)
                seg_total[seg_key] += float(increases[i])
                seg_count[seg_key] += 1

        # Filter by min_incidents
        station_coords = {}
        for d in _date_range(start_date, end_date):
            data = load_punctuality_data(d)
            if "error" not in data:
                station_coords = data.get("station_coords", {})
                break

        result_stations = []
        total_events = 0
        total_delay_sec = 0

        for name in sta_total:
            if sta_count[name] < min_incidents:
                continue
            total_delay = round(sta_total[name] / 60, 1)
            incidents = sta_count[name]
            total_events += incidents
            total_delay_sec += sta_total[name]
            n_trips = sta_trips.get(name, 0)

            coords = station_coords.get(name)
            entry = {
                "name": name,
                "incidents": incidents,
                "total_delay": total_delay,
                "n_trips": n_trips,
                "incidents_per_1k": round(incidents / max(n_trips, 1) * 1000, 1),
                "delay_per_trip": round(sta_total[name] / 60 / max(n_trips, 1), 3),
            }
            if coords:
                entry["lat"] = coords["lat"]
                entry["lon"] = coords["lon"]
            result_stations.append(entry)

        result_stations.sort(key=lambda s: -s["total_delay"])

        # Build segment list
        result_segments = []
        for (from_name, to_name) in seg_total:
            if seg_count[(from_name, to_name)] < min_incidents:
                continue
            total_d = round(seg_total[(from_name, to_name)] / 60, 1)
            n_seg_trips = seg_trips.get((from_name, to_name), 0)
            from_coords = station_coords.get(from_name)
            to_coords = station_coords.get(to_name)
            if from_coords and to_coords:
                result_segments.append({
                    "from_name": from_name,
                    "to_name": to_name,
                    "incidents": seg_count[(from_name, to_name)],
                    "total_delay": total_d,
                    "n_trips": n_seg_trips,
                    "incidents_per_1k": round(seg_count[(from_name, to_name)] / max(n_seg_trips, 1) * 1000, 1),
                    "delay_per_trip": round(total_d / max(n_seg_trips, 1), 3),
                    "from_lat": from_coords["lat"],
                    "from_lon": from_coords["lon"],
                    "to_lat": to_coords["lat"],
                    "to_lon": to_coords["lon"],
                })
        result_segments.sort(key=lambda s: -s["total_delay"])

        return {
            "n_events": total_events,
            "n_stations": len(result_stations),
            "total_delay_min": round(total_delay_sec / 60, 1),
            "stations": result_stations,
            "segments": result_segments,
        }

    async def _stream():
        loop = asyncio.get_event_loop()
        future = loop.run_in_executor(None, _compute)

        while True:
            try:
                item = await asyncio.to_thread(progress_q.get, timeout=0.3)
            except Exception:
                if future.done():
                    break
                continue
            if item is None:
                break
            done, total = item
            payload = json.dumps({"done": done, "total": total})
            yield f"event: progress\ndata: {payload}\n\n"

        result = await future
        result_payload = json.dumps(result, cls=_NumpyEncoder)
        yield f"event: result\ndata: {result_payload}\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream")


@router.get("/problematic")
async def api_problematic(
    start: str | None = None,
    end: str | None = None,
    late_threshold: float = 5.0,
    min_days: int = 3,
    delay_cap: float = 30,
):
    """Find train-station pairs that are consistently late."""
    def _compute():
        import pandas as pd

        start_date, end_date = _defaults(start, end, days_back=14)
        n_days = (end_date - start_date).days + 1
        if n_days > 30:
            return {"error": "Max 30 days"}

        late_threshold_sec = late_threshold * 60
        delay_cap_sec = delay_cap * 60

        # Accumulators: (train_no, station) -> {days -> {sum, max, n, n_late}}
        pair_days: dict[tuple, dict[str, dict]] = defaultdict(lambda: defaultdict(lambda: {
            "sum": 0.0, "max": 0.0, "n": 0, "n_late": 0,
        }))

        prefetch_punctuality(list(_date_range(start_date, end_date)))

        # Filter dates by weekday/holiday settings
        allowed_weekdays = _wd(weekdays)
        all_dates = _filter_dates(start_date, end_date, allowed_weekdays, exclude_pub, exclude_sch)
        if not all_dates:
            return {"error": "No dates match filters"}
        n_days = len(all_dates)

        # Parallel prefetch with progress callback
        prefetch_punctuality(list(_date_range(start_date, end_date)))

        for d in all_dates:
            data = load_punctuality_data(d)
            if "error" in data:
                continue
            records = data["records"]
            if not records:
                continue

            df = pd.DataFrame(records)
            delays = pd.to_numeric(df["delay_dep"], errors="coerce")
            valid = delays.notna()
            df = df[valid.values]
            delays = delays[valid.values].values.astype(np.float64)

            if len(df) == 0:
                continue

            # Clamp delays
            delays = np.where(delays >= 0, delays, 0.0)
            np.clip(delays, None, delay_cap_sec, out=delays)

            stations = df["ptcar_lg_nm_nl"].str.strip().str.upper().values
            train_nos = np.asarray(df["train_no"].values, dtype=object)
            datdep = str(d)

            relations = np.asarray(df.get("relation", pd.Series(["?"] * len(df))).fillna("?").values, dtype=object)
            operators = np.asarray(df.get("train_serv", pd.Series(["?"] * len(df))).fillna("?").values, dtype=object)

            for j in range(len(df)):
                key = (train_nos[j], stations[j])
                day_agg = pair_days[key][datdep]
                day_agg["sum"] += delays[j]
                if delays[j] > day_agg["max"]:
                    day_agg["max"] = delays[j]
                day_agg["n"] += 1
                if delays[j] > late_threshold_sec:
                    day_agg["n_late"] += 1
                if "relation" not in day_agg or day_agg["relation"] == "?":
                    day_agg["relation"] = str(relations[j])
                    day_agg["operator"] = str(operators[j])

        # Aggregate
        offenders = []
        n_pairs = 0

        for (train_no, station), days_dict in pair_days.items():
            nd = len(days_dict)
            if nd < min_days:
                continue
            n_pairs += 1

            total_sum = 0.0
            total_max_sum = 0.0
            total_pct_sum = 0.0

            for datdep, agg in days_dict.items():
                avg_d = agg["sum"] / max(agg["n"], 1)
                total_sum += avg_d
                total_max_sum += agg["max"]
                pct = agg["n_late"] / max(agg["n"], 1) * 100
                total_pct_sum += pct

            avg_pct_late = round(total_pct_sum / nd, 1)
            avg_delay = round(total_sum / nd / 60, 1)
            avg_max_delay = round(total_max_sum / nd / 60, 1)
            total_stops = sum(agg["n"] for agg in days_dict.values())

            # Get relation/operator from first day
            first_day = next(iter(days_dict.values()))
            relation = first_day.get("relation", "?")
            operator = first_day.get("operator", "?")

            # Build daily breakdown
            daily = []
            for datdep_key in sorted(days_dict.keys()):
                agg = days_dict[datdep_key]
                day_avg = round(agg["sum"] / max(agg["n"], 1) / 60, 1)
                daily.append({"date": datdep_key, "avg_delay": day_avg, "n": agg["n"]})

            offenders.append({
                "train_no": str(train_no),
                "station": station,
                "days_seen": nd,
                "pct_late": avg_pct_late,
                "avg_delay": str(avg_delay),
                "max_delay": str(avg_max_delay),
                "total_stops": total_stops,
                "relation": relation,
                "operator": operator,
                "daily": daily,
            })

        offenders.sort(key=lambda o: -o["pct_late"])
        n_offenders = sum(1 for o in offenders if o["pct_late"] > 50)

        return {
            "n_pairs": n_pairs,
            "n_offenders": n_offenders,
            "offenders": offenders,
        }

    async def _stream():
        loop = asyncio.get_event_loop()
        future = loop.run_in_executor(None, _compute)

        while True:
            try:
                item = await asyncio.to_thread(progress_q.get, timeout=0.3)
            except Exception:
                if future.done():
                    break
                continue
            if item is None:
                break
            done, total = item
            payload = json.dumps({"done": done, "total": total})
            yield f"event: progress\ndata: {payload}\n\n"

        result = await future
        result_payload = json.dumps(result, cls=_NumpyEncoder)
        yield f"event: result\ndata: {result_payload}\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream")


@router.get("/missed")
async def api_missed(
    start: str | None = None,
    end: str | None = None,
    min_transfer: int = 2,
    max_transfer: int = 15,
    hour_start: int = 0,
    hour_end: int = 24,
    min_connections: int = 10,
):
    """Analyse missed connections at stations."""
    def _compute():
        import pandas as pd

        start_date, end_date = _defaults(start, end)
        n_days = (end_date - start_date).days + 1
        if n_days > 30:
            return {"error": "Max 30 days"}

        min_transfer_sec = min_transfer * 60
        max_transfer_sec = max_transfer * 60

        acc_planned: dict[str, int] = defaultdict(int)
        acc_missed: dict[str, int] = defaultdict(int)

        prefetch_punctuality(list(_date_range(start_date, end_date)))

        for d in _date_range(start_date, end_date):
            data = load_punctuality_data(d)
            if "error" in data:
                continue
            records = data["records"]
            if not records:
                continue

            df = pd.DataFrame(records)
            # SNCB only
            df = df[df["train_serv"] == "SNCB/NMBS"]
            if df.empty:
                continue

            # Parse times
            def _parse_time_sec_vec(series):
                parts = series.astype(str).str.split(":", expand=True)
                h = pd.to_numeric(parts[0], errors="coerce").fillna(-1)
                m = pd.to_numeric(parts[1], errors="coerce").fillna(0)
                s = pd.to_numeric(parts.get(2, 0), errors="coerce").fillna(0) if 2 in parts.columns else 0
                result = (h * 3600 + m * 60 + s).values.astype(np.int64)
                result[h.values < 0] = -1
                return result

            arr_sec = _parse_time_sec_vec(df["planned_time_arr"])
            dep_sec = _parse_time_sec_vec(df["planned_time_dep"])
            delay_arr = pd.to_numeric(df["delay_arr"], errors="coerce").fillna(0).values.astype(np.int64)
            delay_dep = pd.to_numeric(df["delay_dep"], errors="coerce").fillna(0).values.astype(np.int64)
            stations_arr = np.asarray(df["ptcar_lg_nm_nl"].str.strip().str.upper().values, dtype=object)
            trains = np.asarray(df["train_no"].values, dtype=object)

            # Hour filter
            arr_h = arr_sec // 3600
            dep_h = dep_sec // 3600
            in_range = ((arr_h >= hour_start) & (arr_h < hour_end)) | ((dep_h >= hour_start) & (dep_h < hour_end))
            valid = in_range & ((arr_sec >= 0) | (dep_sec >= 0))

            arr_sec = arr_sec[valid]
            dep_sec = dep_sec[valid]
            delay_arr = delay_arr[valid]
            delay_dep = delay_dep[valid]
            stations_arr = stations_arr[valid]
            trains = trains[valid]

            if len(stations_arr) == 0:
                continue

            # Group by station
            order = np.argsort(stations_arr, kind="stable")
            stations_s = stations_arr[order]
            arr_s = arr_sec[order]
            dep_s = dep_sec[order]
            da_s = delay_arr[order]
            dd_s = delay_dep[order]
            tr_s = trains[order]

            breaks = np.where(stations_s[1:] != stations_s[:-1])[0] + 1
            starts = np.concatenate([[0], breaks])
            ends = np.concatenate([breaks, [len(stations_s)]])

            for si in range(len(starts)):
                s, e = starts[si], ends[si]
                station_name = stations_s[s]

                arr_mask = arr_s[s:e] >= 0
                arr_planned = arr_s[s:e][arr_mask]
                arr_actual = arr_planned + da_s[s:e][arr_mask]
                arr_trains = tr_s[s:e][arr_mask]

                dep_mask = dep_s[s:e] >= 0
                dep_planned = dep_s[s:e][dep_mask]
                dep_actual = dep_planned + dd_s[s:e][dep_mask]
                dep_trains = tr_s[s:e][dep_mask]

                n_arr = len(arr_planned)
                n_dep = len(dep_planned)
                if n_arr == 0 or n_dep == 0:
                    continue

                gap = dep_planned[None, :] - arr_planned[:, None]
                diff_train = arr_trains[:, None] != dep_trains[None, :]
                valid_conn = diff_train & (gap >= min_transfer_sec) & (gap <= max_transfer_sec)

                planned_count = int(valid_conn.sum())
                if planned_count == 0:
                    continue

                actual_arr_2d = arr_actual[:, None]
                actual_dep_2d = dep_actual[None, :]
                missed_mask = valid_conn & (actual_arr_2d > actual_dep_2d)
                missed_count = int(missed_mask.sum())

                acc_planned[station_name] += planned_count
                acc_missed[station_name] += missed_count

                del gap, diff_train, valid_conn, missed_mask

        # Get station coords
        station_coords = {}
        for d in _date_range(start_date, end_date):
            data = load_punctuality_data(d)
            if "error" not in data:
                station_coords = data.get("station_coords", {})
                break

        # Build result
        result_stations = []
        total_planned = 0
        total_missed = 0

        for name in acc_planned:
            p = acc_planned[name]
            m = acc_missed[name]
            if p < min_connections:
                continue
            total_planned += p
            total_missed += m
            pct = round(m / max(p, 1) * 100, 1)

            entry: dict = {
                "name": name,
                "planned": p,
                "missed": m,
                "pct_missed": pct,
            }
            coords = station_coords.get(name)
            if coords:
                entry["lat"] = coords["lat"]
                entry["lon"] = coords["lon"]
            result_stations.append(entry)

        result_stations.sort(key=lambda s: -s["missed"])

        pct_missed = round(total_missed / max(total_planned, 1) * 100, 1)

        return {
            "total_connections": total_planned,
            "total_missed": total_missed,
            "pct_missed": pct_missed,
            "stations": result_stations,
        }

    async def _stream():
        loop = asyncio.get_event_loop()
        future = loop.run_in_executor(None, _compute)

        while True:
            try:
                item = await asyncio.to_thread(progress_q.get, timeout=0.3)
            except Exception:
                if future.done():
                    break
                continue
            if item is None:
                break
            done, total = item
            payload = json.dumps({"done": done, "total": total})
            yield f"event: progress\ndata: {payload}\n\n"

        result = await future
        result_payload = json.dumps(result, cls=_NumpyEncoder)
        yield f"event: result\ndata: {result_payload}\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream")




# ---------------------------------------------------------------------------
# Missed-connections deep report (storytelling page)
# ---------------------------------------------------------------------------

_DOW_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

_DEFAULT_KEY_ROUTES = (
    "BRUXELLES-MIDI>ANTWERPEN-CENTRAAL,"
    "BRUXELLES-MIDI>GENT-SINT-PIETERS,"
    "BRUXELLES-MIDI>LIEGE-GUILLEMINS,"
    "BRUXELLES-MIDI>NAMUR,"
    "BRUXELLES-MIDI>LEUVEN"
)

_BRUSSELS_STATIONS = {
    "BRUXELLES-MIDI", "BRUXELLES-CENTRAL", "BRUXELLES-NORD",
    "BRUSSEL-ZUID", "BRUSSEL-CENTRAAL", "BRUSSEL-NOORD",
}

_CORRIDOR_PAIRS = [
    ("GENT-SINT-PIETERS", "LIEGE-GUILLEMINS"),
    ("ANTWERPEN-CENTRAAL", "NAMUR"),
    ("BRUGGE", "LEUVEN"),
    ("GENT-SINT-PIETERS", "LEUVEN"),
    ("ANTWERPEN-CENTRAAL", "LIEGE-GUILLEMINS"),
    ("BRUGGE", "NAMUR"),
    ("OOSTENDE", "LIEGE-GUILLEMINS"),
    ("ANTWERPEN-CENTRAAL", "CHARLEROI-SUD"),
    ("GENT-SINT-PIETERS", "NAMUR"),
    ("BRUGGE", "LIEGE-GUILLEMINS"),
]




@router.get("/missed-report")
async def api_missed_report(
    start: str | None = None,
    end: str | None = None,
    min_transfer: int = 2,
    max_transfer: int = 15,
    hour_start: int = 0,
    hour_end: int = 24,
    min_connections: int = 10,
    key_routes: str = _DEFAULT_KEY_ROUTES,
    close_call_sec: int = 120,
    weekdays: str | None = None,
    exclude_pub: bool = False,
    exclude_sch: bool = False,
):
    """Rich missed-connections analysis for the storytelling report page.

    Returns Server-Sent Events: progress events during data fetch, then result.
    Uses DuckDB for fast analytical queries over the connection matrix.
    """
    import queue
    import duckdb
    from starlette.responses import StreamingResponse

    progress_q: queue.Queue[tuple[int, int, str] | None] = queue.Queue()

    def _on_progress(done: int, total: int):
        progress_q.put((done, total, "fetch"))

    def _emit_processing(step: int, total: int, phase: str = "process"):
        progress_q.put((step, total, phase))

    def _compute():
        import pandas as pd

        start_date, end_date = _defaults(start, end)
        n_days_raw = (end_date - start_date).days + 1
        if n_days_raw < 1:
            return {"error": "Invalid date range"}

        min_transfer_sec = min_transfer * 60
        max_transfer_sec = max_transfer * 60

        allowed_weekdays = _wd(weekdays)
        all_dates = _filter_dates(start_date, end_date, allowed_weekdays, exclude_pub, exclude_sch)
        if not all_dates:
            return {"error": "No dates match filters"}
        n_days = len(all_dates)

        # Parse key routes
        route_pairs: list[tuple[str, str]] = []
        for pair in key_routes.split(","):
            pair = pair.strip()
            if ">" in pair:
                o, d = pair.split(">", 1)
                route_pairs.append((o.strip().upper(), d.strip().upper()))

        # ---- Process in weekly chunks: fetch + analyze per chunk ----
        CHUNK_SIZE = 7  # days per chunk (1 week)
        chunks = [all_dates[i:i + CHUNK_SIZE] for i in range(0, len(all_dates), CHUNK_SIZE)]
        n_chunks = len(chunks)
        _days_fetched = 0

        # Accumulated results across chunks (small aggregated DataFrames)
        all_agg: list[pd.DataFrame] = []
        all_toxic: list[pd.DataFrame] = []
        all_pairs: list[pd.DataFrame] = []
        all_demand: list[pd.DataFrame] = []
        all_wait_times: list[float] = []
        all_train_routes: list[pd.DataFrame] = []
        all_train_daily: list[pd.DataFrame] = []  # per-train per-day delay for weather sensitivity
        station_coords: dict[str, dict] = {}

        # Corridor accumulators — filled per chunk via DuckDB
        _BRU_SQL = ", ".join(f"'{s}'" for s in _BRUSSELS_STATIONS)
        corridor_acc: dict[tuple, dict] = {
            cp: {"planned": 0, "missed": 0,
                 "hour_planned": defaultdict(int), "hour_missed": defaultdict(int)}
            for cp in _CORRIDOR_PAIRS
        }
        # Key route accumulators
        route_acc: dict[tuple, dict] = {
            rp: {"planned": 0, "missed": 0, "transfer_stations": set()}
            for rp in route_pairs
        }

        _CREATE_REC_SQL = """
            CREATE TABLE rec AS
            SELECT
                _date AS day_date,
                _dow AS dow,
                UPPER(TRIM(ptcar_lg_nm_nl)) AS station,
                CAST(train_no AS VARCHAR) AS train_no,
                COALESCE(relation, '') AS relation,
                CASE WHEN LENGTH(CAST(planned_time_arr AS VARCHAR)) = 8
                     THEN TRY_CAST(SPLIT_PART(CAST(planned_time_arr AS VARCHAR), ':', 1) AS INT) * 3600
                        + TRY_CAST(SPLIT_PART(CAST(planned_time_arr AS VARCHAR), ':', 2) AS INT) * 60
                        + COALESCE(TRY_CAST(SPLIT_PART(CAST(planned_time_arr AS VARCHAR), ':', 3) AS INT), 0)
                     ELSE -1 END AS arr_sec,
                CASE WHEN LENGTH(CAST(planned_time_dep AS VARCHAR)) = 8
                     THEN TRY_CAST(SPLIT_PART(CAST(planned_time_dep AS VARCHAR), ':', 1) AS INT) * 3600
                        + TRY_CAST(SPLIT_PART(CAST(planned_time_dep AS VARCHAR), ':', 2) AS INT) * 60
                        + COALESCE(TRY_CAST(SPLIT_PART(CAST(planned_time_dep AS VARCHAR), ':', 3) AS INT), 0)
                     ELSE -1 END AS dep_sec,
                COALESCE(TRY_CAST(delay_arr AS BIGINT), 0) AS delay_arr,
                COALESCE(TRY_CAST(delay_dep AS BIGINT), 0) AS delay_dep,
            FROM chunk_df
        """

        _CONNECTIONS_SQL = f"""
            CREATE VIEW connections AS
            WITH arrivals AS (
                SELECT day_date, dow, station, train_no, relation,
                       arr_sec AS planned, arr_sec + delay_arr AS actual, delay_arr
                FROM rec WHERE arr_sec >= 0
            ),
            departures AS (
                SELECT day_date, dow, station, train_no, relation,
                       dep_sec AS planned, dep_sec + delay_dep AS actual
                FROM rec WHERE dep_sec >= 0
            )
            SELECT
                a.day_date, a.dow, a.station,
                a.train_no AS arr_train, d.train_no AS dep_train,
                a.relation AS rel_arr, d.relation AS rel_dep,
                d.planned - a.planned AS gap,
                d.planned // 3600 AS dep_hour,
                a.actual AS arr_actual, d.actual AS dep_actual,
                a.delay_arr,
                CASE WHEN a.actual > d.actual THEN 1 ELSE 0 END AS missed,
                CASE WHEN a.actual <= d.actual AND d.actual - a.actual < {close_call_sec}
                     THEN 1 ELSE 0 END AS close_call
            FROM arrivals a
            JOIN departures d
              ON a.day_date = d.day_date AND a.station = d.station AND a.train_no != d.train_no
            WHERE d.planned - a.planned BETWEEN {min_transfer_sec} AND {max_transfer_sec}
        """

        for ci, chunk_dates in enumerate(chunks):
            # Fetch this chunk's data (parallel within chunk)
            _base = _days_fetched
            prefetch_punctuality(chunk_dates, on_progress=lambda done, total, base=_base: (
                progress_q.put((base + done, n_days, "fetch"))
            ))
            _days_fetched += len(chunk_dates)

            _emit_processing(ci + 1, n_chunks, "chunk")

            # Load chunk records from cache — build DataFrame directly,
            # avoid mutating cached dicts and avoid list-of-dicts copy
            day_frames = []
            for d in chunk_dates:
                data = load_punctuality_data(d)
                if "error" in data:
                    continue
                if not station_coords:
                    station_coords = data.get("station_coords", {})
                recs = data["records"]
                if not recs:
                    continue
                day_df = pd.DataFrame(recs)
                day_df["_date"] = d.isoformat()
                day_df["_dow"] = d.weekday()
                day_frames.append(day_df)
                del data, recs, day_df

            if not day_frames:
                continue

            chunk_df = pd.concat(day_frames, ignore_index=True)
            del day_frames
            chunk_df = chunk_df[chunk_df["train_serv"] == "SNCB/NMBS"]
            if chunk_df.empty:
                continue
            # Drop columns not needed by DuckDB queries to save memory
            _keep = ["_date", "_dow", "ptcar_lg_nm_nl", "train_no", "relation",
                     "planned_time_arr", "planned_time_dep", "delay_arr", "delay_dep"]
            chunk_df = chunk_df[[c for c in _keep if c in chunk_df.columns]]

            con = duckdb.connect()
            con.execute(_CREATE_REC_SQL)
            del chunk_df

            if hour_start > 0 or hour_end < 24:
                con.execute(f"""
                    DELETE FROM rec
                    WHERE NOT (
                        (arr_sec >= 0 AND arr_sec / 3600 >= {hour_start} AND arr_sec / 3600 < {hour_end})
                        OR (dep_sec >= 0 AND dep_sec / 3600 >= {hour_start} AND dep_sec / 3600 < {hour_end})
                    )
                """)

            con.execute(_CONNECTIONS_SQL)

            # Aggregation queries — small results
            agg = con.execute("""
                SELECT station, dep_hour, dow, day_date,
                       COUNT(*) AS planned, SUM(missed) AS missed, SUM(close_call) AS close_calls
                FROM connections GROUP BY station, dep_hour, dow, day_date
            """).fetchdf()
            if not agg.empty:
                all_agg.append(agg)

            # Demand (train stops per station)
            demand = con.execute("""
                SELECT station, COUNT(*) AS stops FROM rec GROUP BY station
            """).fetchdf()
            if not demand.empty:
                all_demand.append(demand)

            # Toxic arrivals — track relation with frequency for better merging
            toxic = con.execute("""
                SELECT station, arr_train, rel_arr,
                       SUM(missed) AS missed_downstream,
                       AVG(CASE WHEN missed = 1 THEN delay_arr END) AS avg_delay,
                       COUNT(DISTINCT day_date) AS n_days_seen,
                       COUNT(*) AS rel_count
                FROM connections WHERE missed = 1
                GROUP BY station, arr_train, rel_arr
                HAVING SUM(missed) >= 1
            """).fetchdf()
            if not toxic.empty:
                all_toxic.append(toxic)

            # Train routes: first and last station per train (by planned time)
            train_routes = con.execute("""
                WITH ordered AS (
                    SELECT train_no, station, relation,
                           ROW_NUMBER() OVER (PARTITION BY train_no ORDER BY CASE WHEN dep_sec >= 0 THEN dep_sec ELSE arr_sec END ASC) AS rn_first,
                           ROW_NUMBER() OVER (PARTITION BY train_no ORDER BY CASE WHEN arr_sec >= 0 THEN arr_sec ELSE dep_sec END DESC) AS rn_last
                    FROM rec
                )
                SELECT
                    train_no,
                    MAX(CASE WHEN rn_first = 1 THEN station END) AS first_station,
                    MAX(CASE WHEN rn_last = 1 THEN station END) AS last_station
                FROM ordered
                GROUP BY train_no
            """).fetchdf()
            if not train_routes.empty:
                all_train_routes.append(train_routes)

            # Worst pairs
            pairs = con.execute("""
                SELECT station, arr_train, dep_train,
                       ANY_VALUE(rel_arr) AS rel_arr, ANY_VALUE(rel_dep) AS rel_dep,
                       COUNT(*) AS n_occ, SUM(missed) AS n_missed,
                       AVG(gap / 60.0) AS avg_gap_min,
                       AVG(CASE WHEN missed = 1 THEN (arr_actual - dep_actual) / 60.0 END) AS avg_overshoot_min
                FROM connections
                GROUP BY station, arr_train, dep_train
                HAVING SUM(missed) >= 1
            """).fetchdf()
            if not pairs.empty:
                all_pairs.append(pairs)

            # Wait times — no sampling limit for accuracy
            wait = con.execute("""
                WITH missed_arrivals AS (
                    SELECT DISTINCT day_date, station, arr_actual
                    FROM connections WHERE missed = 1
                ),
                next_deps AS (
                    SELECT ma.day_date, ma.station, ma.arr_actual,
                           MIN(r.dep_sec + r.delay_dep) AS next_dep
                    FROM missed_arrivals ma
                    JOIN rec r ON ma.day_date = r.day_date AND ma.station = r.station
                    WHERE r.dep_sec >= 0 AND r.dep_sec + r.delay_dep > ma.arr_actual
                      AND r.dep_sec + r.delay_dep - ma.arr_actual <= 7200
                    GROUP BY ma.day_date, ma.station, ma.arr_actual
                )
                SELECT (next_dep - arr_actual) / 60.0 AS wait_min
                FROM next_deps WHERE next_dep - arr_actual > 0
            """).fetchdf()
            if not wait.empty:
                all_wait_times.extend(wait["wait_min"].tolist())

            # ---- Corridor queries: actual train-level connections at Brussels ----
            for cp in _CORRIDOR_PAIRS:
                cp_origin, cp_dest = cp
                corr = con.execute(f"""
                    WITH origin_trains AS (
                        SELECT DISTINCT train_no FROM rec WHERE station = '{cp_origin}'
                    ),
                    dest_trains AS (
                        SELECT DISTINCT train_no FROM rec WHERE station = '{cp_dest}'
                    )
                    SELECT dep_hour, COUNT(*) AS planned, SUM(missed) AS missed
                    FROM connections
                    WHERE station IN ({_BRU_SQL})
                      AND arr_train IN (SELECT train_no FROM origin_trains)
                      AND dep_train IN (SELECT train_no FROM dest_trains)
                    GROUP BY dep_hour
                """).fetchdf()
                if not corr.empty:
                    for _, crow in corr.iterrows():
                        h = int(crow["dep_hour"])
                        p = int(crow["planned"])
                        m = int(crow["missed"])
                        corridor_acc[cp]["planned"] += p
                        corridor_acc[cp]["missed"] += m
                        corridor_acc[cp]["hour_planned"][h] += p
                        corridor_acc[cp]["hour_missed"][h] += m

            # ---- Key route queries: trains that serve both origin and destination ----
            for rp in route_pairs:
                rp_origin, rp_dest = rp
                kr = con.execute(f"""
                    WITH route_trains AS (
                        SELECT train_no FROM rec
                        WHERE station = '{rp_origin}'
                        INTERSECT
                        SELECT train_no FROM rec
                        WHERE station = '{rp_dest}'
                    ),
                    route_stations AS (
                        SELECT DISTINCT station FROM rec
                        WHERE train_no IN (SELECT train_no FROM route_trains)
                    )
                    SELECT
                        c.station,
                        COUNT(*) AS planned,
                        SUM(c.missed) AS missed
                    FROM connections c
                    WHERE c.station IN (SELECT station FROM route_stations)
                      AND (c.arr_train IN (SELECT train_no FROM route_trains)
                           OR c.dep_train IN (SELECT train_no FROM route_trains))
                    GROUP BY c.station
                """).fetchdf()
                if not kr.empty:
                    for _, krow in kr.iterrows():
                        route_acc[rp]["planned"] += int(krow["planned"])
                        route_acc[rp]["missed"] += int(krow["missed"])
                        route_acc[rp]["transfer_stations"].add(krow["station"])

            # Per-train per-day delay (for weather sensitivity analysis)
            # Only trains that caused at least one missed connection
            train_daily = con.execute("""
                WITH miss_trains AS (
                    SELECT DISTINCT arr_train AS train_no FROM connections WHERE missed = 1
                )
                SELECT r.train_no, r.day_date,
                       AVG(r.delay_arr) / 60.0 AS avg_delay_min,
                       MAX(r.delay_arr) / 60.0 AS max_delay_min,
                       COUNT(*) AS n_stops,
                       ANY_VALUE(r.relation) AS relation
                FROM rec r
                WHERE r.train_no IN (SELECT train_no FROM miss_trains)
                  AND r.arr_sec >= 0
                GROUP BY r.train_no, r.day_date
            """).fetchdf()
            if not train_daily.empty:
                all_train_daily.append(train_daily)

            con.close()  # Free DuckDB memory for this chunk

        # ---- Merge chunk results ----
        if not all_agg:
            progress_q.put(None)
            return {"error": "No data available for selected dates"}

        _emit_processing(n_chunks, n_chunks, "merge")

        agg_df = pd.concat(all_agg, ignore_index=True)
        del all_agg

        # Station totals
        st_totals = agg_df.groupby("station")[["planned", "missed", "close_calls"]].sum().reset_index()
        acc_planned = dict(zip(st_totals["station"], st_totals["planned"].astype(int)))
        acc_missed = dict(zip(st_totals["station"], st_totals["missed"].astype(int)))
        acc_lucky = dict(zip(st_totals["station"], st_totals["close_calls"].astype(int)))

        # Station demand weight
        if all_demand:
            demand_merged = pd.concat(all_demand, ignore_index=True).groupby("station")["stops"].sum().reset_index()
            station_demand = dict(zip(demand_merged["station"], (demand_merged["stops"] / n_days).round(0).astype(int)))
        else:
            station_demand = {}
        max_demand = max(station_demand.values()) if station_demand else 1
        del all_demand

        # Daily totals
        day_totals = agg_df.groupby("day_date")[["planned", "missed"]].sum().reset_index()
        daily_planned = dict(zip(day_totals["day_date"], day_totals["planned"].astype(int)))
        daily_missed = dict(zip(day_totals["day_date"], day_totals["missed"].astype(int)))

        # Hourly totals
        hour_totals = agg_df.groupby("dep_hour")[["planned", "missed"]].sum().reset_index()
        hourly_planned = dict(zip(hour_totals["dep_hour"].astype(int), hour_totals["planned"].astype(int)))
        hourly_missed = dict(zip(hour_totals["dep_hour"].astype(int), hour_totals["missed"].astype(int)))

        # Hub heatmap
        hub_heatmap_df = agg_df.groupby(["station", "dep_hour", "dow"])[["planned", "missed"]].sum().reset_index()

        # Merge toxic arrivals across chunks — pick most common relation per (station, train)
        if all_toxic:
            toxic_merged = pd.concat(all_toxic, ignore_index=True)
            # For each (station, arr_train), pick the relation with the highest rel_count
            toxic_merged["_wt_delay"] = toxic_merged["avg_delay"].fillna(0) * toxic_merged["n_days_seen"]
            grouped = toxic_merged.groupby(["station", "arr_train"])
            # Get best relation per group
            best_rel = toxic_merged.loc[
                toxic_merged.groupby(["station", "arr_train"])["rel_count"].idxmax()
            ][["station", "arr_train", "rel_arr"]].set_index(["station", "arr_train"])
            toxic_df = grouped.agg(
                missed_downstream=("missed_downstream", "sum"),
                _wt_delay=("_wt_delay", "sum"),
                n_days_seen=("n_days_seen", "sum"),
            ).reset_index()
            toxic_df = toxic_df.join(best_rel, on=["station", "arr_train"])
            toxic_df["avg_delay"] = toxic_df["_wt_delay"] / toxic_df["n_days_seen"].clip(lower=1)
            toxic_df = toxic_df.drop(columns=["_wt_delay"])
            toxic_df = toxic_df[toxic_df["missed_downstream"] >= 2]
        else:
            toxic_df = pd.DataFrame(columns=["station", "arr_train", "rel_arr", "missed_downstream", "avg_delay", "n_days_seen"])
        del all_toxic

        # Merge worst pairs across chunks
        if all_pairs:
            pairs_merged = pd.concat(all_pairs, ignore_index=True)
            pairs_df = pairs_merged.groupby(["station", "arr_train", "dep_train"]).agg(
                rel_arr=("rel_arr", "first"),
                rel_dep=("rel_dep", "first"),
                n_occ=("n_occ", "sum"),
                n_missed=("n_missed", "sum"),
                avg_gap_min=("avg_gap_min", "mean"),
                avg_overshoot_min=("avg_overshoot_min", "mean"),
            ).reset_index()
            pairs_df = pairs_df[pairs_df["n_missed"] >= 2]
        else:
            pairs_df = pd.DataFrame(columns=["station", "arr_train", "dep_train", "rel_arr", "rel_dep",
                                              "n_occ", "n_missed", "avg_gap_min", "avg_overshoot_min"])
        del all_pairs

        wait_times = all_wait_times

        # ---- Weather correlation ----
        weather_section = None
        if n_days >= 3:
            weather_raw = _fetch_weather(50.85, 4.35, start_date, end_date)
            if weather_raw and "daily" in weather_raw:
                wd = weather_raw["daily"]
                w_dates = wd.get("time", [])
                w_by_date = {}
                for wi, wd_str in enumerate(w_dates):
                    w_by_date[wd_str] = {
                        "temp": wd["temperature_2m_mean"][wi],
                        "precip": wd["precipitation_sum"][wi],
                        "rain": wd["rain_sum"][wi],
                        "snow": wd["snowfall_sum"][wi],
                        "wind": wd["wind_speed_10m_max"][wi],
                        "gusts": wd["wind_gusts_10m_max"][wi],
                    }

                w_daily = []
                miss_pcts = []
                precip_vals = []
                wind_vals = []
                temp_vals = []
                snow_vals = []

                for d_iter in _date_range(start_date, end_date):
                    ds = d_iter.isoformat()
                    dp = daily_planned.get(ds, 0)
                    dm = daily_missed.get(ds, 0)
                    w = w_by_date.get(ds)
                    if w is None or dp == 0:
                        continue
                    mp = dm / dp * 100
                    miss_pcts.append(mp)
                    precip_vals.append(w["precip"] or 0)
                    wind_vals.append(w["wind"] or 0)
                    temp_vals.append(w["temp"] if w["temp"] is not None else 10)
                    snow_vals.append(w["snow"] or 0)
                    w_daily.append({
                        "date": ds, "pct_missed": round(mp, 1),
                        "precip_mm": round(w["precip"] or 0, 1),
                        "rain_mm": round(w["rain"] or 0, 1),
                        "snow_cm": round(w["snow"] or 0, 1),
                        "wind_kmh": round(w["wind"] or 0, 1),
                        "gusts_kmh": round(w["gusts"] or 0, 1),
                        "temp_c": round(w["temp"], 1) if w["temp"] is not None else None,
                    })

                correlations = {}
                if len(miss_pcts) >= 5:
                    mp_arr = np.array(miss_pcts, dtype=float)
                    for name, vals in [("precipitation", precip_vals), ("wind", wind_vals),
                                       ("temperature", temp_vals), ("snow", snow_vals)]:
                        v_arr = np.array(vals, dtype=float)
                        if np.std(v_arr) > 0 and np.std(mp_arr) > 0:
                            r = float(np.corrcoef(mp_arr, v_arr)[0, 1])
                            correlations[name] = round(r, 3)

                rainy_miss = [mp for mp, pr in zip(miss_pcts, precip_vals) if pr >= 1.0]
                dry_miss = [mp for mp, pr in zip(miss_pcts, precip_vals) if pr < 1.0]
                comparison = {}
                if rainy_miss and dry_miss:
                    comparison["rainy_avg_pct"] = round(sum(rainy_miss) / len(rainy_miss), 2)
                    comparison["dry_avg_pct"] = round(sum(dry_miss) / len(dry_miss), 2)
                    comparison["rainy_days"] = len(rainy_miss)
                    comparison["dry_days"] = len(dry_miss)
                windy_miss = [mp for mp, w in zip(miss_pcts, wind_vals) if w >= 40]
                calm_miss = [mp for mp, w in zip(miss_pcts, wind_vals) if w < 40]
                if windy_miss and calm_miss:
                    comparison["windy_avg_pct"] = round(sum(windy_miss) / len(windy_miss), 2)
                    comparison["calm_avg_pct"] = round(sum(calm_miss) / len(calm_miss), 2)
                    comparison["windy_days"] = len(windy_miss)
                    comparison["calm_days"] = len(calm_miss)
                cold_miss = [mp for mp, t in zip(miss_pcts, temp_vals) if t < 5]
                mild_miss = [mp for mp, t in zip(miss_pcts, temp_vals) if t >= 5]
                if cold_miss and mild_miss:
                    comparison["cold_avg_pct"] = round(sum(cold_miss) / len(cold_miss), 2)
                    comparison["mild_avg_pct"] = round(sum(mild_miss) / len(mild_miss), 2)
                    comparison["cold_days"] = len(cold_miss)
                    comparison["mild_days"] = len(mild_miss)

                weather_section = {
                    "daily": w_daily, "correlations": correlations,
                    "comparison": comparison, "n_days": len(w_daily),
                }

        # Merge train routes (first/last station per train)
        train_route_map: dict[str, tuple[str, str]] = {}
        if all_train_routes:
            tr_merged = pd.concat(all_train_routes, ignore_index=True)
            # Pick the most common first/last per train
            for tn, grp in tr_merged.groupby("train_no"):
                first = grp["first_station"].mode()
                last = grp["last_station"].mode()
                train_route_map[tn] = (
                    first.iloc[0] if len(first) > 0 else "",
                    last.iloc[0] if len(last) > 0 else "",
                )
        del all_train_routes

        # ---- Weather sensitivity per train ----
        weather_trains = []
        if weather_section and all_train_daily:
            # Build daily weather lookup (reuse w_by_date from weather section)
            td_merged = pd.concat(all_train_daily, ignore_index=True)
            del all_train_daily
            # Aggregate per train+day across chunks
            td_agg = td_merged.groupby(["train_no", "day_date"]).agg(
                avg_delay_min=("avg_delay_min", "mean"),
                max_delay_min=("max_delay_min", "max"),
                n_stops=("n_stops", "sum"),
                relation=("relation", "first"),
            ).reset_index()

            # Get daily precipitation from weather data
            precip_by_date = {}
            wind_by_date = {}
            if weather_section and weather_section.get("daily"):
                for wd in weather_section["daily"]:
                    precip_by_date[wd["date"]] = wd.get("precip_mm", 0) or 0
                    wind_by_date[wd["date"]] = wd.get("wind_kmh", 0) or 0

            if precip_by_date:
                # For each train, split days into bad-weather vs good-weather
                for tn, grp in td_agg.groupby("train_no"):
                    if len(grp) < 5:
                        continue
                    rainy_delays = []
                    dry_delays = []
                    windy_delays = []
                    calm_delays = []
                    all_delays = []
                    for _, row in grp.iterrows():
                        d = row["day_date"]
                        delay = float(row["avg_delay_min"])
                        all_delays.append(delay)
                        precip = precip_by_date.get(d, 0)
                        wind = wind_by_date.get(d, 0)
                        if precip >= 2.0:
                            rainy_delays.append(delay)
                        else:
                            dry_delays.append(delay)
                        if wind >= 40:
                            windy_delays.append(delay)
                        else:
                            calm_delays.append(delay)

                    if not rainy_delays or not dry_delays:
                        continue

                    avg_rainy = sum(rainy_delays) / len(rainy_delays)
                    avg_dry = sum(dry_delays) / len(dry_delays)
                    avg_all = sum(all_delays) / len(all_delays)

                    # Sensitivity: ratio of delay in rain vs dry
                    if avg_dry > 0.1:
                        rain_sensitivity = avg_rainy / avg_dry
                    else:
                        rain_sensitivity = avg_rainy / 0.1

                    wind_sensitivity = None
                    if windy_delays and calm_delays:
                        avg_windy = sum(windy_delays) / len(windy_delays)
                        avg_calm = sum(calm_delays) / len(calm_delays)
                        if avg_calm > 0.1:
                            wind_sensitivity = round(avg_windy / avg_calm, 2)

                    rel = grp["relation"].mode()
                    relation = rel.iloc[0] if len(rel) > 0 else ""
                    route = train_route_map.get(tn, ("", ""))

                    weather_trains.append({
                        "train": tn,
                        "relation": relation,
                        "first_station": route[0],
                        "last_station": route[1],
                        "n_days": len(grp),
                        "avg_delay_min": round(avg_all, 1),
                        "avg_delay_rainy": round(avg_rainy, 1),
                        "avg_delay_dry": round(avg_dry, 1),
                        "rain_sensitivity": round(rain_sensitivity, 2),
                        "wind_sensitivity": wind_sensitivity,
                        "rainy_days": len(rainy_delays),
                        "dry_days": len(dry_delays),
                    })

                weather_trains.sort(key=lambda x: -x["rain_sensitivity"])
                weather_trains = weather_trains[:30]
        else:
            if all_train_daily:
                del all_train_daily

        # ---- Build response ----
        if not station_coords:
            for d in _date_range(start_date, end_date):
                data = load_punctuality_data(d)
                if "error" not in data:
                    station_coords = data.get("station_coords", {})
                    break

        total_planned = sum(acc_planned.values())
        total_missed = sum(acc_missed.values())
        total_lucky = sum(acc_lucky.values())
        total_wait = sum(wait_times)
        pct_missed = round(total_missed / max(total_planned, 1) * 100, 1)

        overview = {
            "total_connections": total_planned,
            "total_missed": total_missed,
            "pct_missed": pct_missed,
            "close_calls": total_lucky,
            "total_added_wait_minutes": round(total_wait, 1),
            "n_days": n_days,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        }

        # Daily
        daily = [
            {"date": d_iter.isoformat(),
             "planned": daily_planned.get(d_iter.isoformat(), 0),
             "missed": daily_missed.get(d_iter.isoformat(), 0),
             "pct": round(daily_missed.get(d_iter.isoformat(), 0) / max(daily_planned.get(d_iter.isoformat(), 0), 1) * 100, 1),
             "dow": d_iter.weekday(), "dow_label": _DOW_LABELS[d_iter.weekday()]}
            for d_iter in _date_range(start_date, end_date)
        ]

        # Hourly
        hourly = [
            {"hour": h, "planned": hourly_planned.get(h, 0), "missed": hourly_missed.get(h, 0),
             "pct": round(hourly_missed.get(h, 0) / max(hourly_planned.get(h, 0), 1) * 100, 1)}
            for h in range(24)
        ]

        # Day of week summary
        dow_acc: dict[int, dict] = defaultdict(lambda: {"planned": 0, "missed": 0})
        for entry in daily:
            dow_acc[entry["dow"]]["planned"] += entry["planned"]
            dow_acc[entry["dow"]]["missed"] += entry["missed"]
        dow_summary = [
            {"dow": dow, "label": _DOW_LABELS[dow],
             "planned": dow_acc[dow]["planned"], "missed": dow_acc[dow]["missed"],
             "pct": round(dow_acc[dow]["missed"] / max(dow_acc[dow]["planned"], 1) * 100, 1)}
            for dow in range(7)
        ]

        # Stations with worst pairs
        result_stations = []
        for name in acc_planned:
            p = acc_planned[name]
            m = acc_missed[name]
            if p < min_connections:
                continue
            pct = round(m / max(p, 1) * 100, 1)
            demand = station_demand.get(name, 0)
            impact = round(m * (demand / max_demand) if max_demand else 0, 1)
            entry: dict = {"name": name, "planned": p, "missed": m, "pct_missed": pct,
                           "daily_trains": demand, "impact_score": impact}
            coords = station_coords.get(name)
            if coords:
                entry["lat"] = coords["lat"]
                entry["lon"] = coords["lon"]
            result_stations.append(entry)
        result_stations.sort(key=lambda s_entry: -s_entry["impact_score"])

        for st in result_stations[:20]:
            st_pairs = pairs_df[pairs_df["station"] == st["name"]].nlargest(5, "n_missed")
            st["worst_pairs"] = [
                {
                    "arriving_train": row["arr_train"],
                    "departing_train": row["dep_train"],
                    "relation_arr": row["rel_arr"],
                    "relation_dep": row["rel_dep"],
                    "planned_gap_min": round(row["avg_gap_min"], 1),
                    "actual_gap_min": round(row["avg_overshoot_min"], 1) if pd.notna(row["avg_overshoot_min"]) else 0,
                    "n_occurrences": int(row["n_occ"]),
                    "n_missed": int(row["n_missed"]),
                }
                for _, row in st_pairs.iterrows()
            ]

        # Lucky
        lucky_section = {
            "total_close_calls": total_lucky,
            "pct_of_all": round(total_lucky / max(total_planned, 1) * 100, 1),
            "pct_saved": round(total_lucky / max(total_lucky + total_missed, 1) * 100, 1),
        }

        # Wait time stats
        if wait_times:
            sorted_waits = sorted(wait_times)
            n_w = len(sorted_waits)
            avg_wait = sum(sorted_waits) / n_w
            median_wait = sorted_waits[n_w // 2]
            buckets = [(0, 5), (5, 10), (10, 15), (15, 20), (20, 30), (30, 60), (60, 120)]
            hist = [
                {"bucket": f"{lo}-{hi}", "count": cnt}
                for lo, hi in buckets
                if (cnt := sum(1 for w in sorted_waits if lo <= w < hi)) > 0
            ]
            added_wait = {
                "avg_wait_min": round(avg_wait, 1),
                "median_wait_min": round(median_wait, 1),
                "total_person_wait_min": round(total_wait, 0),
                "histogram": hist,
                "n_samples": n_w,
            }
        else:
            added_wait = {"avg_wait_min": 0, "median_wait_min": 0, "total_person_wait_min": 0, "histogram": [], "n_samples": 0}

        # Key routes
        key_routes_result = []
        for rp in route_pairs:
            ra = route_acc[rp]
            if ra["planned"] == 0:
                continue
            rp_pct = round(ra["missed"] / max(ra["planned"], 1) * 100, 1)
            avg_rw = added_wait["avg_wait_min"]
            daily_missed_avg = ra["missed"] / max(n_days, 1)
            yearly_hours = round(daily_missed_avg * avg_rw * 220 / 60, 1)
            key_routes_result.append({
                "origin": rp[0], "destination": rp[1],
                "transfer_stations": sorted(ra["transfer_stations"])[:10],
                "total_connections": ra["planned"], "missed": ra["missed"],
                "pct_missed": rp_pct, "avg_added_wait_min": avg_rw,
                "yearly_loss_hours": yearly_hours,
            })

        # Hub spotlight
        hub_stations_ranked = sorted(acc_planned.keys(), key=lambda s: -acc_planned[s])[:5]
        hub_spotlight = []
        for hs in hub_stations_ranked:
            hs_hm = hub_heatmap_df[hub_heatmap_df["station"] == hs]
            heatmap = [
                {"hour": int(row["dep_hour"]), "dow": int(row["dow"]),
                 "dow_label": _DOW_LABELS[int(row["dow"])],
                 "planned": int(row["planned"]), "missed": int(row["missed"]),
                 "pct": round(int(row["missed"]) / max(int(row["planned"]), 1) * 100, 1)}
                for _, row in hs_hm.iterrows() if int(row["planned"]) > 0
            ]
            hs_toxic = toxic_df[toxic_df["station"] == hs].nlargest(5, "missed_downstream")
            toxic = [
                {"train": row["arr_train"], "relation": row["rel_arr"],
                 "missed_caused": int(row["missed_downstream"]),
                 "avg_delay_min": round(float(row["avg_delay"]) / 60, 1) if pd.notna(row["avg_delay"]) else 0,
                 "n_days_seen": int(row["n_days_seen"])}
                for _, row in hs_toxic.iterrows()
            ]
            coords = station_coords.get(hs)
            hub_spotlight.append({
                "station": hs,
                "lat": coords["lat"] if coords else None,
                "lon": coords["lon"] if coords else None,
                "summary": {
                    "planned": acc_planned[hs], "missed": acc_missed[hs],
                    "pct": round(acc_missed[hs] / max(acc_planned[hs], 1) * 100, 1),
                    "close_calls": acc_lucky.get(hs, 0),
                    "daily_trains": station_demand.get(hs, 0),
                },
                "heatmap": heatmap,
                "toxic_arrivals": toxic,
            })

        # Corridors — now using actual per-corridor data from DuckDB queries
        corridors_result = []
        for cp in _CORRIDOR_PAIRS:
            ca = corridor_acc[cp]
            if ca["planned"] == 0:
                continue
            cpct = round(ca["missed"] / ca["planned"] * 100, 1)
            worst_hours = sorted([
                {"hour": h, "planned": ca["hour_planned"][h], "missed": ca["hour_missed"][h],
                 "pct": round(ca["hour_missed"][h] / ca["hour_planned"][h] * 100, 1)}
                for h in ca["hour_planned"] if ca["hour_planned"][h] >= 3
            ], key=lambda x: -x["pct"])
            corridors_result.append({
                "origin": cp[0], "destination": cp[1], "via": "Brussels",
                "planned": ca["planned"], "missed": ca["missed"],
                "reliability_pct": round(100 - cpct, 1), "pct_missed": cpct,
                "avg_added_wait_min": added_wait["avg_wait_min"],
                "worst_hours": worst_hours[:3],
            })

        # Domino trains — aggregate across stations, pick most-seen relation
        # Use max(n_days_seen) per station instead of sum to avoid overcounting
        domino_agg: dict[str, dict] = defaultdict(
            lambda: {"total_missed": 0, "stations": set(), "relations": defaultdict(int),
                     "delay_sum": 0.0, "delay_n": 0, "max_days": 0}
        )
        for _, row in toxic_df.iterrows():
            da = domino_agg[row["arr_train"]]
            da["total_missed"] += int(row["missed_downstream"])
            da["stations"].add(row["station"])
            rel = row["rel_arr"] if pd.notna(row.get("rel_arr")) else ""
            if rel:
                da["relations"][rel] += int(row["missed_downstream"])
            days = int(row["n_days_seen"])
            if days > da["max_days"]:
                da["max_days"] = days
            if pd.notna(row["avg_delay"]):
                da["delay_sum"] += float(row["avg_delay"]) * days
                da["delay_n"] += days
        domino_result = sorted([
            {"train": tn,
             "relation": max(v["relations"], key=v["relations"].get) if v["relations"] else "",
             "total_missed_caused": v["total_missed"],
             "stations_affected": sorted(v["stations"])[:5],
             "n_stations": len(v["stations"]),
             "avg_delay_min": round(v["delay_sum"] / max(v["delay_n"], 1) / 60, 1),
             "n_days_seen": v["max_days"],
             "first_station": train_route_map.get(tn, ("", ""))[0],
             "last_station": train_route_map.get(tn, ("", ""))[1]}
            for tn, v in domino_agg.items() if v["total_missed"] >= 3
        ], key=lambda x: -x["total_missed_caused"])[:50]

        progress_q.put(None)  # sentinel: all done

        return {
            "overview": overview,
            "daily": daily,
            "hourly": hourly,
            "dow_summary": dow_summary,
            "stations": result_stations,
            "lucky": lucky_section,
            "added_wait": added_wait,
            "key_routes": key_routes_result,
            "hub_spotlight": hub_spotlight,
            "corridors": corridors_result,
            "domino_trains": domino_result,
            "weather": weather_section,
            "weather_sensitive_trains": weather_trains,
        }


    async def _stream():
        loop = asyncio.get_event_loop()
        future = loop.run_in_executor(None, _compute)

        while True:
            try:
                item = await asyncio.to_thread(progress_q.get, timeout=0.3)
            except Exception:
                if future.done():
                    break
                continue
            if item is None:
                break
            done, total, phase = item
            payload = json.dumps({"done": done, "total": total, "phase": phase})
            yield f"event: progress\ndata: {payload}\n\n"

        result = await future
        result_payload = json.dumps(result, cls=_NumpyEncoder)
        yield f"event: result\ndata: {result_payload}\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream")





@router.get("/weather-delay")
async def api_weather_delay(
    start: str | None = None,
    end: str | None = None,
    weekdays: str | None = None,
    hour_start: int | None = None,
    hour_end: int | None = None,
    exclude_pub: bool = False,
    exclude_sch: bool = False,
    metric: str = "departure",
):
    """Correlate daily weather conditions with train delay statistics.

    Returns Server-Sent Events: progress events during fetch, then result.
    """
    import queue
    from starlette.responses import StreamingResponse

    progress_q: queue.Queue[tuple[int, int]] = queue.Queue()

    def _on_progress(done: int, total: int):
        progress_q.put((done, total))

    def _compute():
        start_date, end_date = _defaults(start, end, days_back=30)
        n_days = (end_date - start_date).days + 1
        if n_days > 365:
            return {"error": "Max 365 days for weather correlation"}

        allowed_weekdays = _wd(weekdays)
        hour_filter = _hf(hour_start, hour_end)
        h_start = hour_filter[0] if hour_filter else 5
        h_end = hour_filter[1] if hour_filter else 24

        active_dates = _filter_dates(start_date, end_date, allowed_weekdays, exclude_pub, exclude_sch)
        if not active_dates:
            return {"error": "No dates match filters"}

        # Fetch weather for central Belgium (Brussels)
        weather = _fetch_weather(50.85, 4.35, start_date, end_date)
        if not weather or "daily" not in weather:
            return {"error": "Could not fetch weather data from Open-Meteo"}

        daily_weather = weather["daily"]
        weather_dates = daily_weather.get("time", [])
        weather_by_date = {}
        for i, d_str in enumerate(weather_dates):
            weather_by_date[d_str] = {
                "temp": daily_weather["temperature_2m_mean"][i],
                "precipitation": daily_weather["precipitation_sum"][i],
                "rain": daily_weather["rain_sum"][i],
                "snow": daily_weather["snowfall_sum"][i],
                "wind_speed": daily_weather["wind_speed_10m_max"][i],
                "wind_gusts": daily_weather["wind_gusts_10m_max"][i],
            }

        # Fetch hourly weather for hour-level correlations
        hourly_weather = _fetch_weather_hourly(50.85, 4.35, start_date, end_date)
        # Index hourly weather by (date_str, hour)
        hourly_w_by_dh: dict[tuple[str, int], dict] = {}
        if hourly_weather and "hourly" in hourly_weather:
            hw = hourly_weather["hourly"]
            hw_times = hw.get("time", [])
            for i, ts in enumerate(hw_times):
                # ts format: "2026-04-09T07:00"
                d_part = ts[:10]
                h_part = int(ts[11:13])
                hourly_w_by_dh[(d_part, h_part)] = {
                    "precipitation": hw["precipitation"][i] if hw["precipitation"][i] is not None else 0,
                    "rain": hw["rain"][i] if hw["rain"][i] is not None else 0,
                    "snow": hw["snowfall"][i] if hw["snowfall"][i] is not None else 0,
                    "wind_speed": hw["wind_speed_10m"][i] if hw["wind_speed_10m"][i] is not None else 0,
                    "wind_gusts": hw["wind_gusts_10m"][i] if hw["wind_gusts_10m"][i] is not None else 0,
                    "temp": hw["temperature_2m"][i] if hw["temperature_2m"][i] is not None else 10,
                }

        delay_col = "delay_dep" if metric == "departure" else "delay_arr"
        time_col = "planned_time_dep" if metric == "departure" else "planned_time_arr"

        # Fetch + process in weekly batches
        BATCH = 7
        batches = [active_dates[i:i + BATCH] for i in range(0, len(active_dates), BATCH)]
        _fetched = 0

        daily_points = []
        # Per-train per-day delay accumulator
        train_day_acc: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
        train_relations: dict[str, str] = {}
        # Hourly accumulators: hour -> {delays: [], precip: [], wind: [], temp: []}
        hourly_acc: dict[int, dict] = defaultdict(lambda: {
            "delays": [], "precip": [], "wind": [], "temp": [],
            "n_trains": 0, "n_late": 0,
        })

        for batch in batches:
            _base = _fetched
            prefetch_punctuality(batch, on_progress=lambda done, total, b=_base: (
                _on_progress(b + done, len(active_dates))
            ))
            _fetched += len(batch)

            for d in batch:
                d_str = d.isoformat()
                w = weather_by_date.get(d_str)
                if not w:
                    continue

                data = load_punctuality_data(d)
                if "error" in data:
                    continue

                records = data["records"]
                delays = []
                # Per-hour delays for this day
                hour_delays: dict[int, list[float]] = defaultdict(list)
                for rec in records:
                    name = _station_name(rec)
                    if not name:
                        continue
                    hour = _parse_hour(rec.get(time_col, ""))
                    if hour < h_start or hour >= h_end:
                        continue
                    try:
                        delay_sec = float(rec.get(delay_col, 0) or 0)
                    except (ValueError, TypeError):
                        continue
                    delay_min = delay_sec / 60.0
                    delays.append(delay_min)
                    hour_delays[hour].append(delay_min)
                    # Track per-train
                    tn = str(rec.get("train_no", ""))
                    if tn:
                        train_day_acc[tn][d_str].append(delay_min)
                        if tn not in train_relations:
                            rel = rec.get("relation", "")
                            if rel:
                                train_relations[tn] = rel

                if not delays:
                    continue

                n_trains = len(delays)
                avg_delay = round(sum(delays) / n_trains, 2)
                pct_late = round(sum(1 for d_ in delays if d_ > 1) / n_trains * 100, 1)
                sorted_d = sorted(delays)
                mid = len(sorted_d) // 2
                median_delay = sorted_d[mid] if len(sorted_d) % 2 else round((sorted_d[mid - 1] + sorted_d[mid]) / 2, 2)

                daily_points.append({
                    "date": d_str,
                    "weekday": d.weekday(),
                    "n_trains": n_trains,
                    "avg_delay": avg_delay,
                    "median_delay": median_delay,
                    "pct_late": pct_late,
                    **w,
                })

                # Accumulate hourly data
                for h, h_dels in hour_delays.items():
                    hw = hourly_w_by_dh.get((d_str, h))
                    if hw:
                        avg_h = sum(h_dels) / len(h_dels)
                        pct_h = sum(1 for dd in h_dels if dd > 1) / len(h_dels) * 100
                        hourly_acc[h]["delays"].append(avg_h)
                        hourly_acc[h]["precip"].append(hw["precipitation"])
                        hourly_acc[h]["wind"].append(hw["wind_speed"])
                        hourly_acc[h]["temp"].append(hw["temp"])
                        hourly_acc[h]["n_trains"] += len(h_dels)
                        hourly_acc[h]["n_late"] += sum(1 for dd in h_dels if dd > 1)

        progress_q.put(None)  # sentinel: all batches done

        if not daily_points:
            return {"error": "No data points could be computed"}

        # Compute daily correlations
        n = len(daily_points)
        weather_vars = ["temp", "precipitation", "rain", "snow", "wind_speed", "wind_gusts"]
        delay_vars = ["avg_delay", "pct_late"]
        correlations = {}

        for wv in weather_vars:
            for dv in delay_vars:
                xs = [p[wv] for p in daily_points if p[wv] is not None]
                ys = [p[dv] for p in daily_points if p[wv] is not None]
                if len(xs) < 3:
                    continue
                x_arr = np.array(xs, dtype=float)
                y_arr = np.array(ys, dtype=float)
                if np.std(x_arr) == 0 or np.std(y_arr) == 0:
                    r = 0.0
                else:
                    r = float(np.corrcoef(x_arr, y_arr)[0, 1])
                correlations[f"{wv}_vs_{dv}"] = round(r, 3)

        # Build hourly weather vs delay summary
        hourly_points = []
        for h in range(h_start, h_end):
            ha = hourly_acc.get(h)
            if not ha or not ha["delays"]:
                continue
            n_obs = len(ha["delays"])
            avg_d = round(sum(ha["delays"]) / n_obs, 2)
            avg_precip = round(sum(ha["precip"]) / n_obs, 2) if ha["precip"] else 0
            avg_wind = round(sum(ha["wind"]) / n_obs, 1) if ha["wind"] else 0
            avg_temp = round(sum(ha["temp"]) / n_obs, 1) if ha["temp"] else 10
            pct = round(ha["n_late"] / max(ha["n_trains"], 1) * 100, 1)

            # Per-hour correlation between precipitation and delay
            h_corr = None
            if n_obs >= 5:
                p_arr = np.array(ha["precip"], dtype=float)
                d_arr = np.array(ha["delays"], dtype=float)
                if np.std(p_arr) > 0 and np.std(d_arr) > 0:
                    h_corr = round(float(np.corrcoef(p_arr, d_arr)[0, 1]), 3)

            hourly_points.append({
                "hour": h,
                "avg_delay": avg_d,
                "pct_late": pct,
                "n_trains": ha["n_trains"],
                "avg_precip_mm": avg_precip,
                "avg_wind_kmh": avg_wind,
                "avg_temp_c": avg_temp,
                "precip_delay_corr": h_corr,
                "n_observations": n_obs,
            })

        # Weather-sensitive trains analysis
        sensitive_trains = []
        precip_lookup = {p["date"]: p.get("precipitation", 0) or 0 for p in daily_points}
        wind_lookup = {p["date"]: p.get("wind_speed", 0) or 0 for p in daily_points}
        for tn, day_delays in train_day_acc.items():
            if len(day_delays) < 5:
                continue
            rainy_d = []
            dry_d = []
            all_d = []
            for dd_str, dd_delays in day_delays.items():
                avg_dd = sum(dd_delays) / len(dd_delays)
                all_d.append(avg_dd)
                precip = precip_lookup.get(dd_str, 0)
                if precip >= 2.0:
                    rainy_d.append(avg_dd)
                else:
                    dry_d.append(avg_dd)
            if not rainy_d or not dry_d:
                continue
            avg_rainy = sum(rainy_d) / len(rainy_d)
            avg_dry = sum(dry_d) / len(dry_d)
            avg_all = sum(all_d) / len(all_d)
            sensitivity = avg_rainy / max(avg_dry, 0.1)
            sensitive_trains.append({
                "train": tn,
                "relation": train_relations.get(tn, ""),
                "n_days": len(day_delays),
                "avg_delay_min": round(avg_all, 1),
                "avg_delay_rainy": round(avg_rainy, 1),
                "avg_delay_dry": round(avg_dry, 1),
                "rain_sensitivity": round(sensitivity, 2),
                "rainy_days": len(rainy_d),
                "dry_days": len(dry_d),
            })
        sensitive_trains.sort(key=lambda x: -x["rain_sensitivity"])
        sensitive_trains = [t for t in sensitive_trains if t["avg_delay_min"] >= 1.0][:30]

        return {
            "n_days": n,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "daily": daily_points,
            "correlations": correlations,
            "hourly": hourly_points,
            "sensitive_trains": sensitive_trains,
        }

    async def _stream():
        loop = asyncio.get_event_loop()
        future = loop.run_in_executor(None, _compute)

        # Stream progress events from the prefetch phase
        while True:
            try:
                item = await asyncio.to_thread(progress_q.get, timeout=0.3)
            except Exception:
                if future.done():
                    break
                continue
            if item is None:
                break
            done, total = item
            payload = json.dumps({"done": done, "total": total})
            yield f"event: progress\ndata: {payload}\n\n"

        result = await future
        result_payload = json.dumps(result, cls=_NumpyEncoder)
        yield f"event: result\ndata: {result_payload}\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream")

