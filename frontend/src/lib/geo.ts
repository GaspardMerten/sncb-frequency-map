/**
 * Geographic utilities for point-in-polygon checks and province/region assignment.
 */

/** Ray-casting point-in-polygon test. Coordinates are [lon, lat]. */
export function pointInPolygon(
  lon: number,
  lat: number,
  polygon: number[][],
): boolean {
  let inside = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const [xi, yi] = polygon[i]; // [lon, lat]
    const [xj, yj] = polygon[j];
    if (
      yi > lat !== yj > lat &&
      lon < ((xj - xi) * (lat - yi)) / (yj - yi) + xi
    ) {
      inside = !inside;
    }
  }
  return inside;
}

/** Assign a province name from a GeoJSON FeatureCollection to a point. */
export function assignProvince(
  lon: number,
  lat: number,
  geojson: any,
): string | null {
  for (const feature of geojson.features) {
    const geom = feature.geometry;
    const rings: number[][][] =
      geom.type === "MultiPolygon"
        ? geom.coordinates.flat()
        : geom.coordinates;
    for (const ring of rings) {
      if (pointInPolygon(lon, lat, ring)) {
        return feature.properties?.name ?? null;
      }
    }
  }
  return null;
}

/** Province-to-region mapping for Belgium. */
const PROVINCE_TO_REGION: Record<string, string> = {
  Bruxelles: "Brussels",
  "Brabant Wallon": "Wallonia",
  Hainaut: "Wallonia",
  "Liège": "Wallonia",
  Luxembourg: "Wallonia",
  Namur: "Wallonia",
  Antwerpen: "Flanders",
  Limburg: "Flanders",
  "Oost-Vlaanderen": "Flanders",
  "Vlaams Brabant": "Flanders",
  "West-Vlaanderen": "Flanders",
};

/** Get the region (Brussels / Flanders / Wallonia) for a province name. */
export function getRegion(province: string): string {
  return PROVINCE_TO_REGION[province] ?? "Unknown";
}

/** Get all region names. */
export function getAllRegions(): string[] {
  return ["Brussels", "Flanders", "Wallonia"];
}

/**
 * Aggregate numeric values by province.
 * Returns a map of province name -> { sum, count, avg }.
 */
export function aggregateByProvince<T>(
  items: T[],
  geojson: any,
  getLon: (d: T) => number,
  getLat: (d: T) => number,
  getValue: (d: T) => number,
): Map<string, { sum: number; count: number; avg: number }> {
  const result = new Map<string, { sum: number; count: number; avg: number }>();

  for (const item of items) {
    const province = assignProvince(getLon(item), getLat(item), geojson);
    if (!province) continue;

    const existing = result.get(province);
    const value = getValue(item);
    if (existing) {
      existing.sum += value;
      existing.count += 1;
      existing.avg = existing.sum / existing.count;
    } else {
      result.set(province, { sum: value, count: 1, avg: value });
    }
  }

  return result;
}

/**
 * Build a GeoJSON FeatureCollection with a `_value` property on each feature,
 * based on aggregated station data. Useful for choropleth rendering.
 */
export function buildChoroplethGeoJSON(
  geojson: any,
  valuesByName: Map<string, number>,
): any {
  return {
    type: "FeatureCollection",
    features: geojson.features.map((f: any) => ({
      ...f,
      properties: {
        ...f.properties,
        _value: valuesByName.get(f.properties?.name) ?? 0,
      },
    })),
  };
}

/**
 * Merge province geometries into region-level MultiPolygons.
 * Returns a GeoJSON FeatureCollection with one feature per region.
 */
export function buildRegionGeoJSON(
  provinceGeoJSON: any,
  valuesByRegion: Map<string, number>,
): any {
  const regionCoords: Record<string, number[][][][]> = {};

  for (const feature of provinceGeoJSON.features) {
    const name = feature.properties?.name;
    if (!name) continue;
    const region = getRegion(name);
    if (!regionCoords[region]) regionCoords[region] = [];

    const geom = feature.geometry;
    if (geom.type === "MultiPolygon") {
      regionCoords[region].push(...geom.coordinates);
    } else {
      regionCoords[region].push(geom.coordinates);
    }
  }

  const features = Object.entries(regionCoords).map(([region, coords]) => ({
    type: "Feature" as const,
    properties: {
      name: region,
      _value: valuesByRegion.get(region) ?? 0,
    },
    geometry: {
      type: "MultiPolygon" as const,
      coordinates: coords,
    },
  }));

  return { type: "FeatureCollection", features };
}
