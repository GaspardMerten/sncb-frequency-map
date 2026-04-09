import { ScatterplotLayer, PathLayer, GeoJsonLayer, TextLayer } from "@deck.gl/layers";
import { HeatmapLayer } from "@deck.gl/aggregation-layers";

/**
 * Convert a 0-1 ratio to an RGBA colour array (green -> yellow -> red).
 * Uses the same interpolation curve as `valueToColor` in utils.ts.
 */
export function colorToRGBA(
  ratio: number,
  alpha = 200,
): [number, number, number, number] {
  ratio = Math.max(0, Math.min(1, ratio));
  let r: number, g: number, b: number;
  if (ratio < 0.5) {
    const t = ratio * 2;
    r = Math.round(34 + 221 * t);
    g = Math.round(180 - 40 * t);
    b = Math.round(34 - 30 * t);
  } else {
    const t = (ratio - 0.5) * 2;
    r = Math.round(255 - 35 * t);
    g = Math.round(140 - 120 * t);
    b = Math.round(4 + 30 * t);
  }
  return [r, g, b, alpha];
}

// ---------------------------------------------------------------------------
// Layer factory helpers
// ---------------------------------------------------------------------------

interface StationLayerOpts<T> {
  radiusFn: (d: T) => number;
  colorFn: (d: T) => [number, number, number, number];
  onHover?: (info: any) => void;
  onClick?: (info: any) => void;
  positionFn?: (d: T) => [number, number];
  radiusScale?: number;
  radiusMinPixels?: number;
  radiusMaxPixels?: number;
  pickable?: boolean;
}

/** Create a ScatterplotLayer for station-style point data. */
export function stationLayer<T>(
  id: string,
  stations: T[],
  opts: StationLayerOpts<T>,
): ScatterplotLayer<T> {
  return new ScatterplotLayer<T>({
    id,
    data: stations,
    getPosition: (opts.positionFn ?? ((d: any) => [d.longitude, d.latitude])) as any,
    getRadius: opts.radiusFn as any,
    getFillColor: opts.colorFn as any,
    radiusScale: opts.radiusScale ?? 1,
    radiusMinPixels: opts.radiusMinPixels ?? 3,
    radiusMaxPixels: opts.radiusMaxPixels ?? 30,
    pickable: opts.pickable ?? true,
    onHover: opts.onHover,
    onClick: opts.onClick,
    updateTriggers: {
      getRadius: [opts.radiusFn],
      getFillColor: [opts.colorFn],
    },
  });
}

interface SegmentLayerOpts<T> {
  widthFn: (d: T) => number;
  colorFn: (d: T) => [number, number, number, number];
  pathFn?: (d: T) => [number, number][];
  widthScale?: number;
  widthMinPixels?: number;
  widthMaxPixels?: number;
  pickable?: boolean;
}

/** Create a PathLayer for route / segment data. */
export function segmentLayer<T>(
  id: string,
  segments: T[],
  opts: SegmentLayerOpts<T>,
): PathLayer<T> {
  return new PathLayer<T>({
    id,
    data: segments,
    getPath: (opts.pathFn ?? ((d: any) => d.path)) as any,
    getWidth: opts.widthFn as any,
    getColor: opts.colorFn as any,
    widthScale: opts.widthScale ?? 1,
    widthMinPixels: opts.widthMinPixels ?? 1,
    widthMaxPixels: opts.widthMaxPixels ?? 20,
    pickable: opts.pickable ?? true,
    updateTriggers: {
      getWidth: [opts.widthFn],
      getColor: [opts.colorFn],
    },
  });
}

interface HeatmapLayerOpts<T> {
  weightFn: (d: T) => number;
  positionFn?: (d: T) => [number, number];
  radiusPixels?: number;
  intensity?: number;
  threshold?: number;
}

/** Create a HeatmapLayer. */
export function heatmapLayer<T>(
  id: string,
  points: T[],
  opts: HeatmapLayerOpts<T>,
): HeatmapLayer<T> {
  return new HeatmapLayer<T>({
    id,
    data: points,
    getPosition: (opts.positionFn ?? ((d: any) => [d.longitude, d.latitude])) as any,
    getWeight: opts.weightFn as any,
    radiusPixels: opts.radiusPixels ?? 30,
    intensity: opts.intensity ?? 1,
    threshold: opts.threshold ?? 0.05,
    updateTriggers: {
      getWeight: [opts.weightFn],
    },
  });
}

interface ChoroplethLayerOpts {
  valueFn: (f: any) => number;
  colorFn: (f: any) => [number, number, number, number];
  lineWidth?: number;
  pickable?: boolean;
  onHover?: (info: any) => void;
  onClick?: (info: any) => void;
}

/** Create a GeoJsonLayer styled as a choropleth. */
export function choroplethLayer(
  id: string,
  geojson: any,
  opts: ChoroplethLayerOpts,
): GeoJsonLayer {
  return new GeoJsonLayer({
    id,
    data: geojson,
    getFillColor: opts.colorFn,
    getLineColor: [100, 100, 100, 120],
    getLineWidth: opts.lineWidth ?? 1,
    lineWidthMinPixels: 1,
    filled: true,
    stroked: true,
    pickable: opts.pickable ?? true,
    onHover: opts.onHover,
    onClick: opts.onClick,
    updateTriggers: {
      getFillColor: [opts.colorFn],
    },
  });
}
