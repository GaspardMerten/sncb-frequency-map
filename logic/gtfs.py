"""GTFS data processing: service filtering, frequency computation, stop lookups."""

import pandas as pd
import numpy as np
from collections import defaultdict
from datetime import date

from .geo import is_in_belgium


def _to_datetime_safe(series):
    """Convert a date column to datetime, handling both string and datetime types."""
    if pd.api.types.is_datetime64_any_dtype(series):
        return series
    return pd.to_datetime(series, format="%Y%m%d")


def _timedelta_to_hours(series: pd.Series) -> pd.Series:
    """Extract integer hours from a timedelta or string time column."""
    if pd.api.types.is_timedelta64_dtype(series):
        return (series.dt.total_seconds() // 3600).fillna(-1).astype(int)
    return pd.to_numeric(
        series.astype(str).str.split(":").str[0], errors="coerce"
    ).fillna(-1).astype(int)


def get_active_service_ids(feed, target_dates: list[date]) -> set[str]:
    """Determine which GTFS service_ids are active on any of the target dates."""
    counts = get_service_day_counts(feed, target_dates)
    return set(counts.keys())


def get_service_day_counts(feed, target_dates: list[date]) -> dict[str, int]:
    """Count how many target dates each service_id is active on."""
    day_names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
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

    return dict(counts)


def _build_stop_to_station(stops: pd.DataFrame) -> dict[str, str]:
    """Build stop_id -> parent_station mapping, vectorized."""
    sid = stops["stop_id"].astype(str).str.strip()
    parent = stops["parent_station"].fillna("").astype(str).str.strip()
    station = np.where(parent != "", parent, sid)
    return dict(zip(sid, station))


# Cache stop_to_station per feed to avoid rebuilding on each call
_stop_to_station_cache: dict[int, dict] = {}


def _get_stop_to_station(stops: pd.DataFrame) -> dict[str, str]:
    """Cached version of _build_stop_to_station using DataFrame id."""
    key = id(stops)
    if key not in _stop_to_station_cache:
        _stop_to_station_cache[key] = _build_stop_to_station(stops)
    return _stop_to_station_cache[key]


def _is_pass_through(st_df: pd.DataFrame) -> pd.Series:
    """Return boolean Series: True where the stop is a pass-through (no boarding/alighting).

    GTFS pickup_type=1 means no pickup, drop_off_type=1 means no drop-off.
    A stop is pass-through when BOTH are 1 (train doesn't stop for passengers).
    Missing columns or NaN values are treated as 0 (regular stop).
    """
    pickup = pd.to_numeric(
        st_df["pickup_type"], errors="coerce"
    ).fillna(0).astype(int) if "pickup_type" in st_df.columns else 0
    dropoff = pd.to_numeric(
        st_df["drop_off_type"], errors="coerce"
    ).fillna(0).astype(int) if "drop_off_type" in st_df.columns else 0
    return (pickup == 1) & (dropoff == 1)


def build_stop_lookup(feed) -> dict:
    """Build lookup: station_id -> {name, lat, lon}, grouping by parent_station."""
    stops = feed.stops
    lats = stops["stop_lat"].values.astype(float)
    lons = stops["stop_lon"].values.astype(float)
    sids = stops["stop_id"].astype(str).str.strip().values
    parents = stops["parent_station"].fillna("").astype(str).str.strip().values
    names = stops["stop_name"].fillna("").values

    lookup = {}
    for i in range(len(stops)):
        lat, lon = lats[i], lons[i]
        if np.isnan(lat) or np.isnan(lon) or not is_in_belgium(lat, lon):
            continue
        key = parents[i] if parents[i] else sids[i]
        if key not in lookup:
            lookup[key] = {"name": names[i], "lat": float(lat), "lon": float(lon)}
    return lookup


def compute_segment_frequencies(feed, service_ids: set[str],
                                 hour_filter: tuple | None = None,
                                 day_count: int = 1,
                                 service_day_counts: dict[str, int] | None = None,
                                 ) -> dict[tuple[str, str], float]:
    """Compute average daily frequency per consecutive stop pair (vectorized).

    Uses ALL stops (including pass-throughs) to build segment edges,
    since the train physically runs on those tracks.
    """
    trips = feed.trips
    stop_times = feed.stop_times
    stops = feed.stops

    stop_to_station = _get_stop_to_station(stops)

    # Filter to active trips
    active_trips = trips.loc[trips["service_id"].isin(service_ids), ["trip_id", "service_id"]]
    active_trip_ids = set(active_trips["trip_id"])
    trip_to_service = dict(zip(active_trips["trip_id"], active_trips["service_id"]))

    st_f = stop_times[stop_times["trip_id"].isin(active_trip_ids)].copy()
    st_f = st_f.sort_values(["trip_id", "stop_sequence"])

    # Vectorized hour parsing
    st_f["hour"] = _timedelta_to_hours(st_f["departure_time"])

    # Map to parent stations
    st_f["station_id"] = st_f["stop_id"].map(stop_to_station).fillna(st_f["stop_id"])

    # Vectorized consecutive pairs
    st_f["next_station"] = st_f.groupby("trip_id")["station_id"].shift(-1)

    pairs = st_f.dropna(subset=["next_station"])
    pairs = pairs[pairs["station_id"] != pairs["next_station"]]

    if hour_filter:
        pairs = pairs[(pairs["hour"] >= hour_filter[0]) & (pairs["hour"] < hour_filter[1])]

    # Fully vectorized counting
    s_a = pairs["station_id"].values
    s_b = pairs["next_station"].values

    keys_a = np.where(s_a <= s_b, s_a, s_b)
    keys_b = np.where(s_a <= s_b, s_b, s_a)

    if service_day_counts:
        weights = np.array([
            service_day_counts.get(trip_to_service.get(tid), 1)
            for tid in pairs["trip_id"].values
        ], dtype=float)
    else:
        weights = np.ones(len(pairs), dtype=float)

    # Use pandas groupby for fast aggregation
    agg = pd.DataFrame({"a": keys_a, "b": keys_b, "w": weights})
    result = agg.groupby(["a", "b"])["w"].sum()

    divisor = max(day_count, 1)
    return {(a, b): v / divisor for (a, b), v in result.items() if v > 0}


def compute_station_frequencies(segment_freqs: dict[tuple[str, str], float],
                                 served_stations: set[str] | None = None,
                                 ) -> dict[str, float]:
    """Sum segment frequencies touching each station.

    If served_stations is provided, only count stations in that set
    (excludes pass-through stations where trains don't stop).
    """
    station_freq = defaultdict(float)
    for (a, b), freq in segment_freqs.items():
        if served_stations is None or a in served_stations:
            station_freq[a] += freq
        if served_stations is None or b in served_stations:
            station_freq[b] += freq
    return dict(station_freq)


def compute_served_stations(feed, service_ids: set[str],
                            hour_filter: tuple | None = None,
                            ) -> set[str]:
    """Return station IDs where at least one train actually stops (not pass-through).

    A stop is considered served if pickup_type != 1 OR drop_off_type != 1.
    """
    stop_times = feed.stop_times
    stops = feed.stops
    trips = feed.trips

    stop_to_station = _get_stop_to_station(stops)

    active_trip_ids = set(trips.loc[trips["service_id"].isin(service_ids), "trip_id"])
    st_f = stop_times[stop_times["trip_id"].isin(active_trip_ids)].copy()

    # Filter out pass-through stops
    st_f = st_f[~_is_pass_through(st_f)]

    if hour_filter:
        st_f["hour"] = _timedelta_to_hours(st_f["departure_time"])
        st_f = st_f[(st_f["hour"] >= hour_filter[0]) & (st_f["hour"] < hour_filter[1])]

    st_f["station_id"] = st_f["stop_id"].map(stop_to_station).fillna(st_f["stop_id"])
    return set(st_f["station_id"].unique())
