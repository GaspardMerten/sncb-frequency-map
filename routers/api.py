"""JSON API routes for data endpoints."""

import asyncio
import io
import json
import math
import os
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


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

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

        # Clamp
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

    return JSONResponse(content={
        "summary": {
            "n_stations": len(stations),
            "avg_delay": str(avg_delay_overall),
            "median_delay": str(median_delay),
            "pct_late": str(pct_late_overall),
        },
        "stations": stations,
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

        # Load feeds for each operator
        feeds = {}
        service_ids_per_op = {}
        for op_name in selected_ops:
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
        }

    result = await asyncio.to_thread(_compute)
    return JSONResponse(content=result)


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
        pct_10min = round(float(np.mean(valid_times <= 10) * 100), 1)

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

        return {
            "n_stops": n_stops,
            "median_time": median_time,
            "mean_time": mean_time,
            "p95_time": p95_time,
            "pct_10min": pct_10min,
            "image_b64": image_b64,
        }

    result = await asyncio.to_thread(_compute)
    return JSONResponse(content=result)


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

            # Find consecutive increases within same train
            same_train = train_nos[1:] == train_nos[:-1]
            increases = delays[1:] - delays[:-1]
            hits = same_train & (increases > min_increase)
            idx = np.where(hits)[0]

            for i in idx:
                to_station = stations[i + 1]
                sta_total[to_station] += float(increases[i])
                sta_count[to_station] += 1

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

            coords = station_coords.get(name)
            entry = {
                "name": name,
                "incidents": incidents,
                "total_delay": total_delay,
            }
            if coords:
                entry["lat"] = coords["lat"]
                entry["lon"] = coords["lon"]
            result_stations.append(entry)

        result_stations.sort(key=lambda s: -s["total_delay"])

        return {
            "n_events": total_events,
            "n_stations": len(result_stations),
            "total_delay_min": round(total_delay_sec / 60, 1),
            "stations": result_stations,
        }

    result = await asyncio.to_thread(_compute)
    return JSONResponse(content=result)


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

        for d in _date_range(start_date, end_date):
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

            for j in range(len(df)):
                key = (train_nos[j], stations[j])
                day_agg = pair_days[key][datdep]
                day_agg["sum"] += delays[j]
                if delays[j] > day_agg["max"]:
                    day_agg["max"] = delays[j]
                day_agg["n"] += 1
                if delays[j] > late_threshold_sec:
                    day_agg["n_late"] += 1

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

            offenders.append({
                "train_no": str(train_no),
                "station": station,
                "days_seen": nd,
                "pct_late": avg_pct_late,
                "avg_delay": str(avg_delay),
                "max_delay": str(avg_max_delay),
            })

        offenders.sort(key=lambda o: -o["pct_late"])
        n_offenders = sum(1 for o in offenders if o["pct_late"] > 50)

        return {
            "n_pairs": n_pairs,
            "n_offenders": n_offenders,
            "offenders": offenders,
        }

    result = await asyncio.to_thread(_compute)
    return JSONResponse(content=result)


@router.get("/missed")
async def api_missed(
    start: str | None = None,
    end: str | None = None,
    min_transfer: int = 2,
    max_transfer: int = 30,
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

    result = await asyncio.to_thread(_compute)
    return JSONResponse(content=result)
