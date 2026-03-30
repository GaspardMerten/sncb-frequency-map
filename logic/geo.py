"""Geographic utility functions using Shapely for efficient spatial operations."""

import math
import numpy as np
from shapely.geometry import Point, LineString, MultiPolygon, shape
from shapely.ops import nearest_points, split, substring
from shapely import prepared

# Belgium bounding box
BE_LAT_MIN, BE_LAT_MAX = 49.4, 51.6
BE_LON_MIN, BE_LON_MAX = 2.5, 6.5

# Approximate conversion at Belgian latitudes (~50.5N): 1 degree ~ 111km lat, ~71km lon
DEG_PER_KM_LAT = 1.0 / 111.0
DEG_PER_KM_LON = 1.0 / 71.0

PROVINCE_TO_REGION = {
    "Bruxelles": "Brussels", "Antwerpen": "Flanders", "Limburg": "Flanders",
    "Oost-Vlaanderen": "Flanders", "Vlaams Brabant": "Flanders",
    "West-Vlaanderen": "Flanders", "Brabant Wallon": "Wallonia",
    "Hainaut": "Wallonia", "Liège": "Wallonia", "Luxembourg": "Wallonia",
    "Namur": "Wallonia",
}

PROVINCE_CENTROIDS = {
    "Bruxelles": (50.85, 4.35), "Antwerpen": (51.22, 4.40),
    "Limburg": (50.97, 5.35), "Oost-Vlaanderen": (51.04, 3.73),
    "Vlaams Brabant": (50.88, 4.57), "West-Vlaanderen": (51.05, 3.08),
    "Brabant Wallon": (50.67, 4.52), "Hainaut": (50.45, 3.85),
    "Liège": (50.50, 5.65), "Luxembourg": (49.90, 5.40), "Namur": (50.25, 4.85),
}


def is_in_belgium(lat, lon):
    return BE_LAT_MIN <= lat <= BE_LAT_MAX and BE_LON_MIN <= lon <= BE_LON_MAX


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat, dlon = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def km_to_deg_buffer(km):
    """Convert km buffer to approximate degree buffer (averaged lat/lon at 50.5N)."""
    return km * (DEG_PER_KM_LAT + DEG_PER_KM_LON) / 2.0


# ---------------------------------------------------------------------------
# Shapely-based polyline operations
# ---------------------------------------------------------------------------

def latlon_to_linestring(coords):
    """Convert [[lat, lon], ...] to a Shapely LineString (lon, lat order)."""
    if len(coords) < 2:
        return None
    return LineString([(c[1], c[0]) for c in coords])


def linestring_to_latlon(ls):
    """Convert Shapely LineString back to [[lat, lon], ...]."""
    return [[c[1], c[0]] for c in ls.coords]


def polyline_length_km(coords):
    """Total length of a polyline [[lat, lon], ...] in km."""
    ls = latlon_to_linestring(coords)
    if ls is None:
        return 0.0
    # Approximate: length in degrees -> km
    return ls.length / km_to_deg_buffer(1.0)


def compute_overlap_fraction(coords_a, coords_b, buffer_km=0.5):
    """Fraction of line A that falls within buffer_km of line B, using Shapely."""
    ls_a = latlon_to_linestring(coords_a)
    ls_b = latlon_to_linestring(coords_b)
    if ls_a is None or ls_b is None:
        return 0.0
    buf = km_to_deg_buffer(buffer_km)
    b_buffered = ls_b.buffer(buf)
    intersection = ls_a.intersection(b_buffered)
    if intersection.is_empty:
        return 0.0
    return intersection.length / ls_a.length


def find_overlap_range(coords_long, coords_short, buffer_km=0.5):
    """Find normalized (0-1) start/end of where coords_long overlaps with coords_short.

    Returns (start_frac, end_frac) or None if no overlap.
    """
    ls_long = latlon_to_linestring(coords_long)
    ls_short = latlon_to_linestring(coords_short)
    if ls_long is None or ls_short is None:
        return None

    buf = km_to_deg_buffer(buffer_km)
    short_buffered = ls_short.buffer(buf)
    intersection = ls_long.intersection(short_buffered)
    if intersection.is_empty:
        return None

    # Project the intersection bounds onto the long line
    total_len = ls_long.length
    if total_len < 1e-12:
        return None

    # Get the min/max projection distance along ls_long
    if intersection.geom_type == 'MultiLineString':
        all_coords = []
        for geom in intersection.geoms:
            all_coords.extend(geom.coords)
    elif intersection.geom_type == 'LineString':
        all_coords = list(intersection.coords)
    elif intersection.geom_type == 'GeometryCollection':
        all_coords = []
        for geom in intersection.geoms:
            if hasattr(geom, 'coords'):
                all_coords.extend(geom.coords)
    else:
        return None

    if not all_coords:
        return None

    projections = [ls_long.project(Point(c), normalized=True) for c in all_coords]
    return (min(projections), max(projections))


def split_polyline_at_fractions(coords, frac_start, frac_end):
    """Split a polyline into (before, overlap, after) at normalized fractions.

    Uses Shapely substring for precise cutting.
    """
    ls = latlon_to_linestring(coords)
    if ls is None:
        return [], list(coords), []

    total_len = ls.length

    before_ls = substring(ls, 0, frac_start, normalized=True) if frac_start > 0.01 else None
    overlap_ls = substring(ls, frac_start, frac_end, normalized=True)
    after_ls = substring(ls, frac_end, 1.0, normalized=True) if frac_end < 0.99 else None

    before = linestring_to_latlon(before_ls) if before_ls and not before_ls.is_empty and before_ls.length > 0 else []
    overlap = linestring_to_latlon(overlap_ls) if overlap_ls and not overlap_ls.is_empty and overlap_ls.length > 0 else []
    after = linestring_to_latlon(after_ls) if after_ls and not after_ls.is_empty and after_ls.length > 0 else []

    return before, overlap, after


# ---------------------------------------------------------------------------
# Province / polygon lookups (using Shapely for speed)
# ---------------------------------------------------------------------------

_province_cache = {}

def _build_province_index(prov_geo):
    """Build a list of (name, prepared_shape) for fast point-in-polygon."""
    key = id(prov_geo)
    if key in _province_cache:
        return _province_cache[key]

    index = []
    for feat in prov_geo["features"]:
        name = feat["properties"]["name"]
        geom = shape(feat["geometry"])
        prep = prepared.prep(geom)
        index.append((name, prep, geom))
    _province_cache[key] = index
    return index


def get_province(lat, lon, prov_geo):
    """Determine which Belgian province a coordinate falls in (Shapely-accelerated)."""
    index = _build_province_index(prov_geo)
    pt = Point(lon, lat)

    for name, prep_geom, _ in index:
        if prep_geom.contains(pt):
            return name

    # Fallback: nearest centroid
    best, best_d = None, float("inf")
    for prov, (clat, clon) in PROVINCE_CENTROIDS.items():
        d = haversine_km(lat, lon, clat, clon)
        if d < best_d:
            best_d, best = d, prov
    return best if best_d < 30 else None


def coords_to_latlon(coords):
    """Convert GeoJSON [lon, lat] coordinates to [[lat, lon], ...] for folium."""
    if not coords:
        return []
    if isinstance(coords[0], (int, float)):
        return []
    if isinstance(coords[0][0], (int, float)):
        return [[c[1], c[0]] for c in coords]
    best = []
    for part in coords:
        cand = coords_to_latlon(part)
        if len(cand) > len(best):
            best = cand
    return best


def build_region_geojson(prov_geo):
    """Merge province polygons into region-level MultiPolygons."""
    region_polys = {"Brussels": [], "Flanders": [], "Wallonia": []}
    for feat in prov_geo["features"]:
        r = PROVINCE_TO_REGION.get(feat["properties"]["name"])
        if not r:
            continue
        geom = feat["geometry"]
        if geom["type"] == "Polygon":
            region_polys[r].append(geom["coordinates"])
        elif geom["type"] == "MultiPolygon":
            region_polys[r].extend(geom["coordinates"])
    return {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "properties": {"region": r},
             "geometry": {"type": "MultiPolygon", "coordinates": p}}
            for r, p in region_polys.items() if p
        ],
    }
