import { useState, useMemo } from "react";
import type { Layer } from "@deck.gl/core";
import { choroplethLayer, colorToRGBA, heatmapLayer } from "@/lib/layers";
import {
  aggregateByProvince,
  buildChoroplethGeoJSON,
  buildRegionGeoJSON,
  getRegion,
} from "@/lib/geo";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Built-in geographic view modes handled by the hook. Pages can add custom modes. */
export type GeoViewMode = "stations" | "provinces" | "regions" | "gradient";
export type StationSize = "small" | "medium" | "big";

export interface MetricOption {
  key: string;
  label: string;
  accessor: (d: any) => number;
  /** Suffix shown in tooltips, e.g. " km", "/h" */
  suffix?: string;
}

export interface SizeFilter {
  small: boolean;
  medium: boolean;
  big: boolean;
}

export interface UseMapViewOptions<T> {
  /** Station-like data array */
  data: T[];
  /** Province GeoJSON (from /api/provinces) — null while loading */
  geoData: any | null;
  getLon: (d: T) => number;
  getLat: (d: T) => number;
  /**
   * Classify a data point into small / medium / big.
   * If omitted the size filter is hidden and all data passes through.
   */
  getSize?: (d: T) => StationSize;
  /** Metrics available for choropleth / gradient aggregation */
  metrics: MetricOption[];
  /** Key of the default metric (defaults to first) */
  defaultMetric?: string;
  /** Show the gradient tab? (default true) */
  showGradient?: boolean;
  /** Default view mode (default "stations") */
  defaultViewMode?: string;
}

export interface UseMapViewReturn<T> {
  viewMode: string;
  setViewMode: (v: string) => void;
  sizeFilter: SizeFilter;
  setSizeEnabled: (size: StationSize, enabled: boolean) => void;
  choroplethMetric: string;
  setChoroplethMetric: (m: string) => void;
  /** Data filtered by size (use this for your station layer) */
  filtered: T[];
  /** Overlay layers for province / region / gradient views (empty for stations + custom modes) */
  overlayLayers: Layer[];
  /** True when viewMode is provinces / regions / gradient */
  isOverlayView: boolean;
  /** Whether size filtering is available */
  hasSizeFilter: boolean;
  /** The metric options passed in */
  metrics: MetricOption[];
  /** The currently active metric definition */
  activeMetric: MetricOption;
  /** Whether gradient view is enabled */
  showGradient: boolean;
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

const OVERLAY_MODES = new Set(["provinces", "regions", "gradient"]);

export function useMapView<T>(opts: UseMapViewOptions<T>): UseMapViewReturn<T> {
  const {
    data,
    geoData,
    getLon,
    getLat,
    getSize,
    metrics,
    defaultMetric,
    showGradient = true,
    defaultViewMode = "stations",
  } = opts;

  const [viewMode, setViewMode] = useState(defaultViewMode);
  const [sizeFilter, setSizeFilter] = useState<SizeFilter>({
    small: true,
    medium: true,
    big: true,
  });
  const [choroplethMetric, setChoroplethMetric] = useState(
    defaultMetric ?? metrics[0]?.key ?? "",
  );

  const setSizeEnabled = (size: StationSize, enabled: boolean) =>
    setSizeFilter((prev) => ({ ...prev, [size]: enabled }));

  const hasSizeFilter = !!getSize;
  const isOverlayView = OVERLAY_MODES.has(viewMode);

  // Filter data by size
  const filtered = useMemo(() => {
    if (!getSize) return data;
    return data.filter((d) => sizeFilter[getSize(d)]);
  }, [data, sizeFilter, getSize]);

  const activeMetric = metrics.find((m) => m.key === choroplethMetric) ?? metrics[0];

  // Build overlay layers
  const overlayLayers = useMemo((): Layer[] => {
    if (!isOverlayView || !filtered.length) return [];

    const accessor = activeMetric?.accessor;
    if (!accessor) return [];

    if (viewMode === "gradient") {
      const maxVal = Math.max(...filtered.map(accessor), 1);
      return [
        heatmapLayer("mapview-gradient", filtered, {
          positionFn: (d) => [getLon(d), getLat(d)],
          weightFn: (d) => accessor(d) / maxVal,
          radiusPixels: 40,
          intensity: 2,
          threshold: 0.03,
        }),
      ] as Layer[];
    }

    if (!geoData) return [];

    if (viewMode === "provinces") {
      const byProvince = aggregateByProvince(filtered, geoData, getLon, getLat, accessor);
      const valueMap = new Map<string, number>();
      for (const [name, agg] of byProvince) valueMap.set(name, agg.avg);
      const maxVal = Math.max(...valueMap.values(), 1);
      const enriched = buildChoroplethGeoJSON(geoData, valueMap);
      return [
        choroplethLayer("mapview-province-choropleth", enriched, {
          valueFn: (f) => f.properties._value,
          colorFn: (f) => colorToRGBA(f.properties._value / maxVal, 160),
          pickable: true,
        }),
      ] as Layer[];
    }

    if (viewMode === "regions") {
      const byProvince = aggregateByProvince(filtered, geoData, getLon, getLat, accessor);
      const regionAgg = new Map<string, { sum: number; count: number }>();
      for (const [province, agg] of byProvince) {
        const region = getRegion(province);
        const existing = regionAgg.get(region);
        if (existing) {
          existing.sum += agg.sum;
          existing.count += agg.count;
        } else {
          regionAgg.set(region, { sum: agg.sum, count: agg.count });
        }
      }
      const valueMap = new Map<string, number>();
      for (const [region, agg] of regionAgg)
        valueMap.set(region, agg.sum / agg.count);
      const maxVal = Math.max(...valueMap.values(), 1);
      const regionGeo = buildRegionGeoJSON(geoData, valueMap);
      return [
        choroplethLayer("mapview-region-choropleth", regionGeo, {
          valueFn: (f) => f.properties._value,
          colorFn: (f) => colorToRGBA(f.properties._value / maxVal, 160),
          pickable: true,
        }),
      ] as Layer[];
    }

    return [];
  }, [filtered, viewMode, choroplethMetric, geoData, getLon, getLat, activeMetric, isOverlayView]);

  return {
    viewMode,
    setViewMode,
    sizeFilter,
    setSizeEnabled,
    choroplethMetric,
    setChoroplethMetric,
    filtered,
    overlayLayers,
    isOverlayView,
    hasSizeFilter,
    metrics,
    activeMetric,
    showGradient,
  };
}

// ---------------------------------------------------------------------------
// Size classification helpers
// ---------------------------------------------------------------------------

export function classifyByThresholds(
  value: number,
  smallBelow: number,
  bigAbove: number,
): StationSize {
  if (value < smallBelow) return "small";
  if (value < bigAbove) return "medium";
  return "big";
}

/**
 * Create a size classifier that splits data into terciles (bottom 33% / middle / top 33%).
 */
export function makeTercileClassifier<T>(
  data: T[],
  getValue: (d: T) => number,
): (d: T) => StationSize {
  if (!data.length) return () => "medium";
  const sorted = data.map(getValue).sort((a, b) => a - b);
  const p33 = sorted[Math.floor(sorted.length * 0.33)];
  const p66 = sorted[Math.floor(sorted.length * 0.66)];
  return (d: T) => classifyByThresholds(getValue(d), p33, p66);
}
