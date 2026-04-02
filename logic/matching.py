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
# Infrabel station clustering: remap isolated points to connected neighbours
# ---------------------------------------------------------------------------

def build_infra_cluster_map(op_points: dict, infrabel_segs: dict,
                             radius_km: float = 1.0) -> dict[str, str]:
    """Build a mapping: Infrabel ptcarid -> canonical ptcarid.

    Only remaps stations that have NO segments (isolated operational points)
    to the nearest station that DOES have segments, within radius_km.
    Connected stations keep their own ID.
    """
    if not op_points or "features" not in op_points:
        return {}

    # Extract all operational points
    infra_points = {}  # ptcarid -> (lat, lon)
    for feat in op_points["features"]:
        props = feat.get("properties", {})
        ptcarid = str(props.get("ptcarid", "")).strip()
        if not ptcarid:
            continue
        lat, lon = _extract_point_coords(feat)
        if lat is not None and lon is not None:
            infra_points[ptcarid] = (float(lat), float(lon))

    # Find which stations appear in segments (connected)
    connected = set()
    if infrabel_segs and "features" in infrabel_segs:
        for feat in infrabel_segs["features"]:
            props = feat.get("properties", {})
            fid = str(props.get("stationfrom_id", "")).strip()
            tid = str(props.get("stationto_id", "")).strip()
            if fid:
                connected.add(fid)
            if tid:
                connected.add(tid)

    # Build spatial index of CONNECTED stations only
    connected_ids = [pid for pid in infra_points if pid in connected]
    connected_geoms = [Point(infra_points[pid][1], infra_points[pid][0])
                       for pid in connected_ids]

    if not connected_geoms:
        return {pid: pid for pid in infra_points}

    tree = STRtree(connected_geoms)

    # For each isolated station, find nearest connected station within radius
    mapping = {}
    n_remapped = 0
    for pid, (lat, lon) in infra_points.items():
        if pid in connected:
            mapping[pid] = pid
            continue

        query_pt = Point(lon, lat)
        idx = tree.nearest(query_pt)
        nearest_pt = connected_geoms[idx]
        dist = haversine_km(lat, lon, nearest_pt.y, nearest_pt.x)
        if dist <= radius_km:
            mapping[pid] = connected_ids[idx]
            n_remapped += 1
        else:
            mapping[pid] = pid

    if n_remapped > 0:
        logger.info(f"Infra clustering: {n_remapped} isolated points remapped to "
                     f"nearest connected station (radius={radius_km}km)")

    return mapping


# ---------------------------------------------------------------------------
# Station matching with spatial index
# ---------------------------------------------------------------------------

def build_gtfs_to_infra_mapping(stop_lookup: dict, op_points: dict,
                                 buffer_km: float = 1.0,
                                 infrabel_segs: dict | None = None) -> dict[str, str]:
    """Match GTFS stations to nearest Infrabel operational point within buffer_km.

    If infrabel_segs is provided, clusters isolated Infrabel stations first so that
    they get remapped to nearby connected neighbours.
    """
    if not op_points or "features" not in op_points:
        return {}

    # Build cluster map if we have segment data
    cluster_map = None
    if infrabel_segs:
        cluster_map = build_infra_cluster_map(op_points, infrabel_segs, radius_km=buffer_km)

    # Extract Infrabel points (using canonical IDs after clustering)
    infra_ids, infra_geoms = [], []
    seen_canonical = {}
    for feat in op_points["features"]:
        props = feat.get("properties", {})
        ptcarid = str(props.get("ptcarid", "")).strip()
        if not ptcarid:
            continue
        canonical = cluster_map.get(ptcarid, ptcarid) if cluster_map else ptcarid
        lat, lon = _extract_point_coords(feat)
        if lat is not None and lon is not None:
            if canonical not in seen_canonical:
                seen_canonical[canonical] = len(infra_ids)
                infra_ids.append(canonical)
                infra_geoms.append(Point(float(lon), float(lat)))

    if not infra_geoms:
        return {}

    tree = STRtree(infra_geoms)

    mapping = {}
    match_distances = []
    for station_id, info in stop_lookup.items():
        query_pt = Point(info["lon"], info["lat"])
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

def build_infra_segment_index(infrabel_segs: dict,
                               cluster_map: dict[str, str] | None = None,
                               ) -> dict[tuple[str, str], list]:
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
        if not fid or not tid or fid == tid:
            continue
        if cluster_map:
            c_fid = cluster_map.get(fid, fid)
            c_tid = cluster_map.get(tid, tid)
            # Only apply clustering when it doesn't collapse the pair
            if c_fid != c_tid:
                fid, tid = c_fid, c_tid
        key = tuple(sorted([fid, tid]))
        if key not in index or len(coords) > len(index[key]):
            index[key] = coords
    return index


def build_infra_graph(infrabel_segs: dict,
                       cluster_map: dict[str, str] | None = None,
                       ) -> dict[str, set[str]]:
    """Adjacency graph of Infrabel station IDs, with optional clustering."""
    graph: dict[str, set[str]] = defaultdict(set)
    if not infrabel_segs or "features" not in infrabel_segs:
        return graph
    for feat in infrabel_segs["features"]:
        props = feat.get("properties", {})
        fid = str(props.get("stationfrom_id", "")).strip()
        tid = str(props.get("stationto_id", "")).strip()
        if not fid or not tid or fid == tid:
            continue
        if cluster_map:
            c_fid = cluster_map.get(fid, fid)
            c_tid = cluster_map.get(tid, tid)
            # Only apply clustering when it doesn't collapse the pair
            if c_fid != c_tid:
                fid, tid = c_fid, c_tid
        graph[fid].add(tid)
        graph[tid].add(fid)
    return dict(graph)


def find_path(graph: dict, start: str, end: str, max_depth: int = 30) -> list[str] | None:
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


def build_infra_names(infrabel_segs: dict,
                       cluster_map: dict[str, str] | None = None,
                       ) -> dict[str, str]:
    """Map Infrabel station IDs to human-readable names."""
    names = {}
    if not infrabel_segs or "features" not in infrabel_segs:
        return names
    for feat in infrabel_segs["features"]:
        props = feat.get("properties", {})
        for id_key, name_key in [("stationfrom_id", "stationfrom_name"),
                                  ("stationto_id", "stationto_name")]:
            sid = str(props.get(id_key, "")).strip()
            if not sid:
                continue
            # Store name under original ID
            names.setdefault(sid, props.get(name_key, sid))
            # Also store under canonical (clustered) ID if different
            if cluster_map:
                canonical = cluster_map.get(sid, sid)
                if canonical != sid:
                    names.setdefault(canonical, props.get(name_key, sid))
    return names


# ---------------------------------------------------------------------------
# Map GTFS frequencies onto Infrabel segments
# ---------------------------------------------------------------------------

def map_frequencies_to_infra(segment_freqs, stop_lookup, infrabel_segs,
                              gtfs_to_infra, prov_geo,
                              cluster_map: dict[str, str] | None = None):
    """Resolve GTFS stop-pair frequencies onto Infrabel track segments via BFS.

    Every GTFS segment whose train physically uses a piece of track should
    be visible on the map.  When an Infrabel segment geometry exists for a hop
    we use it; otherwise we fall back to a straight line between the GTFS
    coordinates so that no track is silently dropped.
    """
    infra_index = build_infra_segment_index(infrabel_segs, cluster_map)
    infra_graph = build_infra_graph(infrabel_segs, cluster_map)
    infra_names = build_infra_names(infrabel_segs, cluster_map)
    gtfs_to_infra = gtfs_to_infra or {}

    infra_freq: dict[tuple[str, str], float] = defaultdict(float)
    # Track unmapped GTFS pairs for fallback synthetic segments
    fallback_pairs: dict[tuple[str, str], float] = defaultdict(float)
    stats = {"total": 0, "mapped": 0, "direct": 0, "path": 0, "dropped": 0, "fallback": 0}

    for (stop_a, stop_b), freq in segment_freqs.items():
        if stop_a not in stop_lookup or stop_b not in stop_lookup or freq <= 0:
            continue
        stats["total"] += 1

        infra_a = gtfs_to_infra.get(stop_a)
        infra_b = gtfs_to_infra.get(stop_b)

        # Both GTFS stops map to the same infra station, or one isn't mapped
        if not infra_a or not infra_b or infra_a == infra_b:
            fallback_pairs[(stop_a, stop_b)] += freq
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
                for i in range(len(path) - 1):
                    seg_key = tuple(sorted([path[i], path[i + 1]]))
                    infra_freq[seg_key] += freq
                stats["path"] += 1
                stats["mapped"] += 1
            else:
                fallback_pairs[(stop_a, stop_b)] += freq
                stats["dropped"] += 1

    results = []
    for (id_a, id_b), freq in infra_freq.items():
        if freq <= 0:
            continue
        coords = infra_index.get((id_a, id_b))
        if not coords:
            # BFS path hop without geometry — skip (no geometry to draw)
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

    # Fallback: create synthetic segments for unmapped GTFS pairs
    for (stop_a, stop_b), freq in fallback_pairs.items():
        if freq <= 0:
            continue
        info_a = stop_lookup[stop_a]
        info_b = stop_lookup[stop_b]
        latlon = [[info_a["lat"], info_a["lon"]], [info_b["lat"], info_b["lon"]]]
        mid_lat = (info_a["lat"] + info_b["lat"]) / 2
        mid_lon = (info_a["lon"] + info_b["lon"]) / 2
        province = get_province(mid_lat, mid_lon, prov_geo)
        if not province:
            continue
        results.append({
            "id_a": stop_a, "id_b": stop_b,
            "stop_a": info_a["name"], "stop_b": info_b["name"],
            "frequency": freq, "coords": latlon,
            "province": province,
            "region": PROVINCE_TO_REGION.get(province, "Unknown"),
        })
        stats["fallback"] += 1

    return results, stats


# ---------------------------------------------------------------------------
# "Mergure" algorithm using Shapely geometry operations
# ---------------------------------------------------------------------------

def mergure_segments(segments: list[dict], buffer_km: float = 0.5,
                     size_tolerance: float = 0.5, max_iterations: int = 20) -> list[dict]:
    """Resolve overlapping segments by merging or cutting (Shapely-accelerated)."""
    from .geo import latlon_to_linestring
    working = [dict(s) for s in segments]

    for iteration in range(max_iterations):
        changed = False
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

            candidates = tree.query(geoms[i])
            for j in candidates:
                if j <= i or j in merged_indices:
                    continue

                seg_i, seg_j = working[i], working[j]

                # Only consider merging when both endpoints match; segments
                # connecting different station pairs must stay separate even
                # when their track geometry overlaps.
                pair_i = (seg_i["id_a"], seg_i["id_b"])
                pair_j = (seg_j["id_a"], seg_j["id_b"])
                if set(pair_i) != set(pair_j):
                    continue

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

                if similar_size and overlap_ij >= 0.7 and overlap_ji >= 0.7:
                    merged_indices.add(i)
                    merged_indices.add(j)
                    new_segments.append(_merge_two(seg_i, seg_j))
                    changed = True
                    break

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
