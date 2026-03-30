"""Station matching (GTFS <-> Infrabel) and segment merging ("mergure") algorithm.

Uses Shapely STRtree for fast spatial indexing and buffered geometry operations.
"""

import logging
from collections import defaultdict

from shapely.geometry import Point
from shapely import STRtree

from .geo import (
    haversine_km, coords_to_latlon, get_province, polyline_length_km,
    compute_overlap_fraction, find_overlap_range, split_polyline_at_fractions,
    km_to_deg_buffer, PROVINCE_TO_REGION,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Station matching with spatial index
# ---------------------------------------------------------------------------

def build_gtfs_to_infra_mapping(stop_lookup: dict, op_points: dict,
                                 buffer_km: float = 1.0) -> dict[str, str]:
    """Match GTFS stations to nearest Infrabel operational point within buffer_km.

    Uses Shapely STRtree for O(n log n) nearest-neighbour queries instead of brute force.
    """
    if not op_points or "features" not in op_points:
        return {}

    # Extract Infrabel points
    infra_ids, infra_geoms = [], []
    for feat in op_points["features"]:
        props = feat.get("properties", {})
        ptcarid = str(props.get("ptcarid", "")).strip()
        if not ptcarid:
            continue
        lat, lon = _extract_point_coords(feat)
        if lat is not None and lon is not None:
            infra_ids.append(ptcarid)
            infra_geoms.append(Point(float(lon), float(lat)))

    if not infra_geoms:
        return {}

    # Build spatial index
    tree = STRtree(infra_geoms)
    buf_deg = km_to_deg_buffer(buffer_km)

    mapping = {}
    match_distances = []
    for station_id, info in stop_lookup.items():
        query_pt = Point(info["lon"], info["lat"])
        # Query nearest point
        idx = tree.nearest(query_pt)
        nearest_pt = infra_geoms[idx]
        dist_km = haversine_km(info["lat"], info["lon"],
                               nearest_pt.y, nearest_pt.x)
        if dist_km <= buffer_km:
            mapping[station_id] = infra_ids[idx]
            match_distances.append(dist_km)

    n_total = len(stop_lookup)
    n_matched = len(mapping)
    avg_dist = sum(match_distances) / len(match_distances) if match_distances else 0
    logger.info(
        f"Station matching: {n_matched}/{n_total} GTFS stops matched "
        f"(buffer={buffer_km}km, avg_dist={avg_dist:.3f}km)"
    )
    return mapping


def _extract_point_coords(feat: dict) -> tuple:
    """Extract lat/lon from an Infrabel feature."""
    props = feat.get("properties", {})
    lat, lon = None, None
    geo_pt = props.get("geo_point_2d")
    if isinstance(geo_pt, dict):
        lat, lon = geo_pt.get("lat"), geo_pt.get("lon")
    if lat is None or lon is None:
        geo = feat.get("geometry")
        if isinstance(geo, dict):
            coords = geo.get("coordinates", [])
            if isinstance(coords, list) and len(coords) >= 2:
                lon, lat = coords[0], coords[1]
    return lat, lon


# ---------------------------------------------------------------------------
# Infrabel infrastructure graph
# ---------------------------------------------------------------------------

def build_infra_segment_index(infrabel_segs: dict) -> dict[tuple[str, str], list]:
    """Index: sorted(station_from, station_to) -> GeoJSON coordinates."""
    index = {}
    if not infrabel_segs or "features" not in infrabel_segs:
        return index
    for feat in infrabel_segs["features"]:
        props = feat.get("properties", {})
        coords = feat.get("geometry", {}).get("coordinates", [])
        if not coords:
            continue
        fid = str(props.get("stationfrom_id", "")).strip()
        tid = str(props.get("stationto_id", "")).strip()
        if fid and tid:
            key = tuple(sorted([fid, tid]))
            if key not in index or len(coords) > len(index[key]):
                index[key] = coords
    return index


def build_infra_graph(infrabel_segs: dict) -> dict[str, set[str]]:
    """Adjacency graph of Infrabel station IDs."""
    graph: dict[str, set[str]] = defaultdict(set)
    if not infrabel_segs or "features" not in infrabel_segs:
        return graph
    for feat in infrabel_segs["features"]:
        props = feat.get("properties", {})
        fid = str(props.get("stationfrom_id", "")).strip()
        tid = str(props.get("stationto_id", "")).strip()
        if fid and tid:
            graph[fid].add(tid)
            graph[tid].add(fid)
    return dict(graph)


def find_path(graph: dict, start: str, end: str, max_depth: int = 15) -> list[str] | None:
    """BFS shortest path between two Infrabel stations."""
    if start == end:
        return [start]
    visited = {start}
    queue = [(start, [start])]
    while queue:
        node, path = queue.pop(0)
        if len(path) > max_depth:
            continue
        for nb in graph.get(node, []):
            if nb == end:
                return path + [nb]
            if nb not in visited:
                visited.add(nb)
                queue.append((nb, path + [nb]))
    return None


def check_network_connectivity(graph: dict) -> list[set[str]]:
    """Find connected components. Returns list of sets sorted by size descending."""
    visited = set()
    components = []
    for node in graph:
        if node in visited:
            continue
        component = set()
        stack = [node]
        while stack:
            n = stack.pop()
            if n in visited:
                continue
            visited.add(n)
            component.add(n)
            for nb in graph.get(n, []):
                if nb not in visited:
                    stack.append(nb)
        components.append(component)
    components.sort(key=len, reverse=True)
    return components


def build_infra_names(infrabel_segs: dict) -> dict[str, str]:
    """Map Infrabel station IDs to human-readable names."""
    names = {}
    if not infrabel_segs or "features" not in infrabel_segs:
        return names
    for feat in infrabel_segs["features"]:
        props = feat.get("properties", {})
        for id_key, name_key in [("stationfrom_id", "stationfrom_name"),
                                  ("stationto_id", "stationto_name")]:
            sid = str(props.get(id_key, "")).strip()
            if sid:
                names.setdefault(sid, props.get(name_key, sid))
    return names


# ---------------------------------------------------------------------------
# Map GTFS frequencies onto Infrabel segments
# ---------------------------------------------------------------------------

def map_frequencies_to_infra(segment_freqs, stop_lookup, infrabel_segs,
                              gtfs_to_infra, prov_geo):
    """Resolve GTFS stop-pair frequencies onto Infrabel track segments via BFS."""
    infra_index = build_infra_segment_index(infrabel_segs)
    infra_graph = build_infra_graph(infrabel_segs)
    infra_names = build_infra_names(infrabel_segs)
    gtfs_to_infra = gtfs_to_infra or {}

    infra_freq: dict[tuple[str, str], float] = defaultdict(float)
    stats = {"total": 0, "mapped": 0, "direct": 0, "path": 0, "dropped": 0}

    for (stop_a, stop_b), freq in segment_freqs.items():
        if stop_a not in stop_lookup or stop_b not in stop_lookup or freq <= 0:
            continue
        stats["total"] += 1

        infra_a = gtfs_to_infra.get(stop_a)
        infra_b = gtfs_to_infra.get(stop_b)
        if not infra_a or not infra_b or infra_a == infra_b:
            stats["dropped"] += 1
            continue

        direct_key = tuple(sorted([infra_a, infra_b]))
        if direct_key in infra_index:
            infra_freq[direct_key] += freq
            stats["direct"] += 1
            stats["mapped"] += 1
        else:
            path = find_path(infra_graph, infra_a, infra_b)
            if path and len(path) >= 2:
                found_any = False
                for i in range(len(path) - 1):
                    seg_key = tuple(sorted([path[i], path[i + 1]]))
                    if seg_key in infra_index:
                        infra_freq[seg_key] += freq
                        found_any = True
                if found_any:
                    stats["path"] += 1
                    stats["mapped"] += 1
                else:
                    stats["dropped"] += 1
            else:
                stats["dropped"] += 1

    results = []
    for (id_a, id_b), freq in infra_freq.items():
        if freq <= 0:
            continue
        coords = infra_index.get((id_a, id_b))
        if not coords:
            continue
        latlon = coords_to_latlon(coords)
        if len(latlon) < 2:
            continue
        mid_lat, mid_lon = latlon[len(latlon) // 2]
        province = get_province(mid_lat, mid_lon, prov_geo)
        if not province:
            continue
        results.append({
            "id_a": id_a, "id_b": id_b,
            "stop_a": infra_names.get(id_a, id_a),
            "stop_b": infra_names.get(id_b, id_b),
            "frequency": freq, "coords": latlon,
            "province": province,
            "region": PROVINCE_TO_REGION.get(province, "Unknown"),
        })

    return results, stats


# ---------------------------------------------------------------------------
# "Mergure" algorithm using Shapely geometry operations
# ---------------------------------------------------------------------------

def mergure_segments(segments: list[dict], buffer_km: float = 0.5,
                     size_tolerance: float = 0.5, max_iterations: int = 20) -> list[dict]:
    """Resolve overlapping segments by merging or cutting (Shapely-accelerated).

    Rules applied iteratively until stable:
      - Similar length + overlap >= 70% -> MERGE (sum frequencies, keep longer geometry)
      - One contained in other (>= 80%) + different sizes -> CUT larger into 3 parts
    """
    from .geo import latlon_to_linestring
    working = [dict(s) for s in segments]

    for iteration in range(max_iterations):
        changed = False
        # Build spatial index of all segment bounding boxes for fast candidate filtering
        from shapely import STRtree as ST
        geoms = []
        for seg in working:
            ls = latlon_to_linestring(seg["coords"])
            geoms.append(ls.buffer(km_to_deg_buffer(buffer_km)) if ls else Point(0, 0).buffer(0.0001))

        tree = ST(geoms)
        merged_indices = set()
        new_segments = []

        for i in range(len(working)):
            if i in merged_indices:
                continue

            # Query spatial index for nearby segments
            candidates = tree.query(geoms[i])
            for j in candidates:
                if j <= i or j in merged_indices:
                    continue

                seg_i, seg_j = working[i], working[j]
                ci, cj = seg_i["coords"], seg_j["coords"]
                if len(ci) < 2 or len(cj) < 2:
                    continue

                len_i = polyline_length_km(ci)
                len_j = polyline_length_km(cj)
                if len_i < 0.01 or len_j < 0.01:
                    continue

                overlap_ij = compute_overlap_fraction(ci, cj, buffer_km)
                overlap_ji = compute_overlap_fraction(cj, ci, buffer_km)
                size_ratio = min(len_i, len_j) / max(len_i, len_j)
                similar_size = size_ratio >= size_tolerance

                # Case 1: Similar size + mutual overlap -> MERGE
                if similar_size and overlap_ij >= 0.7 and overlap_ji >= 0.7:
                    merged_indices.add(i)
                    merged_indices.add(j)
                    new_segments.append(_merge_two(seg_i, seg_j))
                    changed = True
                    break

                # Case 2: One contained in the other -> CUT
                if overlap_ij >= 0.8 and not similar_size:
                    large, small = (seg_j, seg_i) if len_j > len_i else (seg_i, seg_j)
                    parts = _cut_larger(large, small, buffer_km)
                    if parts:
                        merged_indices.add(i)
                        merged_indices.add(j)
                        new_segments.extend(parts)
                        changed = True
                        break

                if overlap_ji >= 0.8 and not similar_size:
                    large, small = (seg_i, seg_j) if len_i > len_j else (seg_j, seg_i)
                    parts = _cut_larger(large, small, buffer_km)
                    if parts:
                        merged_indices.add(i)
                        merged_indices.add(j)
                        new_segments.extend(parts)
                        changed = True
                        break

        working = [working[i] for i in range(len(working)) if i not in merged_indices] + new_segments
        if not changed:
            break

    return working


def _merge_two(seg_a: dict, seg_b: dict) -> dict:
    """Merge two similar overlapping segments: sum frequencies, keep longer geometry."""
    len_a = polyline_length_km(seg_a["coords"])
    len_b = polyline_length_km(seg_b["coords"])
    base = seg_a if len_a >= len_b else seg_b
    other = seg_b if len_a >= len_b else seg_a
    return {
        "id_a": base["id_a"], "id_b": base["id_b"],
        "stop_a": base["stop_a"], "stop_b": base["stop_b"],
        "frequency": base["frequency"] + other["frequency"],
        "coords": base["coords"],
        "province": base["province"], "region": base["region"],
    }


def _cut_larger(seg_large: dict, seg_small: dict, buffer_km: float) -> list[dict] | None:
    """Cut the larger segment at overlap boundaries with the smaller one.

    Returns up to 3 segments: [before, overlap (combined freq), after].
    """
    overlap_range = find_overlap_range(seg_large["coords"], seg_small["coords"], buffer_km)
    if overlap_range is None:
        return None

    frac_start, frac_end = overlap_range
    if frac_start < 0.05 and frac_end > 0.95:
        return [_merge_two(seg_large, seg_small)]

    before, overlap_coords, after = split_polyline_at_fractions(
        seg_large["coords"], frac_start, frac_end
    )

    parts = []
    if len(before) >= 2:
        parts.append({
            "id_a": seg_large["id_a"], "id_b": seg_large["id_b"],
            "stop_a": seg_large["stop_a"], "stop_b": f"{seg_large['stop_b']} (split)",
            "frequency": seg_large["frequency"],
            "coords": before,
            "province": seg_large["province"], "region": seg_large["region"],
        })
    if len(overlap_coords) >= 2:
        parts.append({
            "id_a": seg_small["id_a"], "id_b": seg_small["id_b"],
            "stop_a": seg_small["stop_a"], "stop_b": seg_small["stop_b"],
            "frequency": seg_large["frequency"] + seg_small["frequency"],
            "coords": overlap_coords,
            "province": seg_small["province"], "region": seg_small["region"],
        })
    if len(after) >= 2:
        parts.append({
            "id_a": seg_large["id_a"], "id_b": seg_large["id_b"],
            "stop_a": f"{seg_large['stop_a']} (split)", "stop_b": seg_large["stop_b"],
            "frequency": seg_large["frequency"],
            "coords": after,
            "province": seg_large["province"], "region": seg_large["region"],
        })
    return parts if parts else None


def count_remaining_overlaps(segments: list[dict], buffer_km: float = 0.5) -> int:
    """Count segment pairs that still overlap significantly after mergure."""
    from .geo import latlon_to_linestring
    geoms = []
    for seg in segments:
        ls = latlon_to_linestring(seg["coords"])
        geoms.append(ls if ls else Point(0, 0))

    buf = km_to_deg_buffer(buffer_km)
    tree = STRtree(geoms)
    count = 0

    for i in range(len(segments)):
        buffered = geoms[i].buffer(buf) if geoms[i] else None
        if not buffered:
            continue
        candidates = tree.query(buffered)
        for j in candidates:
            if j <= i:
                continue
            oi = compute_overlap_fraction(segments[i]["coords"], segments[j]["coords"], buffer_km)
            oj = compute_overlap_fraction(segments[j]["coords"], segments[i]["coords"], buffer_km)
            if oi >= 0.7 and oj >= 0.7:
                count += 1
    return count
