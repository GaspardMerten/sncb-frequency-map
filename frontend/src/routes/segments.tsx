import { createRoute } from "@tanstack/react-router";
import { useState, useMemo, useRef, useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import { Train } from "lucide-react";
import type { Layer } from "@deck.gl/core";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";
import { rootRoute } from "./__root";
import { Layout } from "@/components/Layout";
import { FilterPanel, type Filters } from "@/components/FilterPanel";
import { MetricCard } from "@/components/MetricCard";
import { LoadingState } from "@/components/LoadingState";
import { EmptyState } from "@/components/EmptyState";
import { ErrorAlert } from "@/components/ErrorAlert";
import { ApplyButton } from "@/components/ApplyButton";
import { DataTable } from "@/components/DataTable";
import { ColorLegend } from "@/components/ColorLegend";
import { MethodologyPanel } from "@/components/MethodologyPanel";
import { MapViewBar, mapViewTooltip } from "@/components/MapViewBar";
import { DeckMap, type DeckMapRef } from "@/components/DeckMap";
import { fetchApi } from "@/lib/api";
import { filterParams, fmt, daysAgo, today } from "@/lib/utils";
import { stationLayer, segmentLayer, colorToRGBA } from "@/lib/layers";
import { aggregateByProvince, getRegion } from "@/lib/geo";
import { useMapView, makeTercileClassifier, type MetricOption } from "@/hooks/useMapView";

export const segmentsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/segments",
  component: SegmentsPage,
});

interface SegmentData {
  segments: { id: string; freq: number; coords: [number, number][] }[];
  stations: { id: string; name: string; freq: number; lat: number; lon: number }[];
  day_count: number;
  error?: string;
}

const METRICS: MetricOption[] = [
  { key: "freq", label: "Trains/day", accessor: (d: any) => d.freq },
];

function SegmentsPage() {
  const [filters, setFilters] = useState<Filters>({
    startDate: daysAgo(7), endDate: today(), weekdays: [0, 1, 2, 3, 4],
    excludePub: false, excludeSch: false, useHour: false, hourStart: 7, hourEnd: 19,
  });
  const [queryParams, setQueryParams] = useState<Record<string, string | number | boolean> | null>(null);
  const mapRef = useRef<DeckMapRef>(null);

  const { data, error, isFetching } = useQuery({
    queryKey: ["segments", queryParams],
    queryFn: () => fetchApi<SegmentData>("/segments", queryParams!),
    enabled: !!queryParams,
  });

  const { data: geoData } = useQuery({
    queryKey: ["provinces"],
    queryFn: () => fetchApi<any>("/provinces"),
  });

  const loadData = () => setQueryParams(filterParams(filters));

  const sizeClassifier = useMemo(
    () => makeTercileClassifier(data?.stations ?? [], (d) => d.freq),
    [data],
  );

  const mapView = useMapView({
    data: data?.stations ?? [],
    geoData,
    getLon: (d) => d.lon,
    getLat: (d) => d.lat,
    getSize: sizeClassifier,
    metrics: METRICS,
    showGradient: true,
    defaultViewMode: "segments",
  });

  const handleStationClick = useCallback((s: { lat: number; lon: number }) => {
    mapRef.current?.flyTo({ longitude: s.lon, latitude: s.lat, zoom: 12 });
  }, []);

  const stationNameById = useMemo(() => {
    const m = new Map<string, string>();
    if (data) for (const st of data.stations) m.set(st.id, st.name);
    return m;
  }, [data]);

  const filteredSegments = useMemo(
    () => (data ? data.segments.filter((s) => s.freq > 1) : []),
    [data],
  );

  const topSegments = useMemo(() => {
    if (!data) return [];
    return [...filteredSegments].sort((a, b) => b.freq - a.freq).slice(0, 50);
  }, [filteredSegments]);

  // Province data for bar charts
  const provinceData = useMemo(() => {
    if (!data || !geoData) return [];
    const byProvince = aggregateByProvince(
      data.stations, geoData,
      (d) => d.lon, (d) => d.lat, (d) => d.freq,
    );
    return Array.from(byProvince.entries())
      .map(([name, agg]) => ({
        name: name.length > 12 ? name.slice(0, 12) + "..." : name,
        fullName: name,
        avg: Math.round(agg.avg * 10) / 10,
        sum: Math.round(agg.sum),
        count: agg.count,
      }))
      .sort((a, b) => b.avg - a.avg);
  }, [data, geoData]);

  // Segment + station dot layers for the custom "segments" view mode
  const segmentViewLayers = useMemo<Layer[]>(() => {
    if (mapView.viewMode !== "segments" || !data) return [];
    const segs = filteredSegments;
    if (!segs.length) return [];
    const maxFreq = Math.max(...segs.map((s) => s.freq));
    const maxStationFreq = Math.max(...data.stations.map((s) => s.freq), 1);

    const pathLayer = segmentLayer("segment-paths", segs, {
      pathFn: (d) => d.coords.map(([lat, lon]) => [lon, lat] as [number, number]),
      widthFn: (d) => 1 + (d.freq / maxFreq) * 10,
      colorFn: (d) => colorToRGBA(d.freq / maxFreq),
      widthMinPixels: 2,
      widthMaxPixels: 16,
      pickable: true,
    });

    const dotLayer = stationLayer("segment-station-dots", data.stations, {
      positionFn: (d) => [d.lon, d.lat],
      radiusFn: (d) => 2 + (d.freq / maxStationFreq) * 8,
      colorFn: () => [8, 69, 148, 200],
      radiusMinPixels: 2,
      radiusMaxPixels: 14,
      pickable: true,
    });

    return [pathLayer, dotLayer] as Layer[];
  }, [data, filteredSegments, mapView.viewMode]);

  // Station circles for the "stations" view mode
  const stationViewLayers = useMemo<Layer[]>(() => {
    if (!data || !mapView.filtered.length) return [];
    const maxFreq = Math.max(...mapView.filtered.map((s) => s.freq), 1);

    return [
      stationLayer("station-circles", mapView.filtered, {
        positionFn: (d) => [d.lon, d.lat],
        radiusFn: (d) => 3 + (d.freq / maxFreq) * 18,
        colorFn: (d) => colorToRGBA(d.freq / maxFreq),
        radiusScale: 1,
        radiusMinPixels: 3,
        radiusMaxPixels: 40,
        pickable: true,
      }),
    ] as Layer[];
  }, [data, mapView.filtered]);

  const layers = mapView.isOverlayView
    ? mapView.overlayLayers
    : mapView.viewMode === "segments"
      ? segmentViewLayers
      : stationViewLayers;

  return (
    <Layout
      sidebar={
        <>
          <FilterPanel filters={filters} onChange={setFilters} />
          <ApplyButton loading={isFetching} onClick={loadData} />
        </>
      }
    >
      {data && !data.error && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5 animate-slide-up">
          <MetricCard label="Segments" value={fmt(filteredSegments.length)} />
          <MetricCard label="Stations" value={fmt(data.stations.length)} />
          <MetricCard label="Busiest" value={data.stations[0]?.name ?? "\u2014"} suffix="/day" />
          <MetricCard label="Avg Days" value={data.day_count} />
        </div>
      )}

      {isFetching && <LoadingState message="Loading GTFS data..." />}
      {!isFetching && !data && <EmptyState icon={Train} />}

      {data && !data.error && !isFetching && (
        <>
          <MapViewBar
            viewMode={mapView.viewMode}
            onViewModeChange={mapView.setViewMode}
            sizeFilter={mapView.sizeFilter}
            onSizeFilterChange={mapView.setSizeEnabled}
            choroplethMetric={mapView.choroplethMetric}
            onChoroplethMetricChange={mapView.setChoroplethMetric}
            metrics={mapView.metrics}
            showGradient={mapView.showGradient}
            activeMetric={mapView.activeMetric}
            isOverlayView={mapView.isOverlayView}
            extraTabs={[{ value: "segments", label: "Segments", position: "before" }]}
          />

          <div className="space-y-2 mt-3">
            <DeckMap
              ref={mapRef}
              layers={layers}
              className="h-[calc(100vh-14rem)]"
              getTooltip={(info) => {
                const mv = mapViewTooltip(mapView.activeMetric, info);
                if (mv) return mv;
                const { object, layer } = info;
                if (!object || !layer) return null;
                const id = layer.id as string;
                if (id === "segment-paths") {
                  const [fromId, toId] = String(object.id ?? "").split("_");
                  const from = stationNameById.get(fromId) ?? fromId ?? "?";
                  const to = stationNameById.get(toId) ?? toId ?? "?";
                  return {
                    html: `<div style="font-size:12px"><b>${from} \u2192 ${to}</b><br/>${fmt(object.freq, 1)} trains/day</div>`,
                    style: { backgroundColor: "rgba(255,255,255,0.95)", color: "#111", padding: "6px 8px", borderRadius: "8px", border: "1px solid #e5e7eb", boxShadow: "0 2px 8px rgba(0,0,0,0.12)" },
                  };
                }
                if (id === "segment-station-dots" || id === "station-circles") {
                  return {
                    html: `<div style="font-size:12px"><b>${object.name ?? object.id}</b><br/>${fmt(object.freq, 1)} trains/day</div>`,
                    style: { backgroundColor: "rgba(255,255,255,0.95)", color: "#111", padding: "6px 8px", borderRadius: "8px", border: "1px solid #e5e7eb", boxShadow: "0 2px 8px rgba(0,0,0,0.12)" },
                  };
                }
                return null;
              }}
            />
            {!mapView.isOverlayView && <ColorLegend min="Low frequency" max="High frequency" />}
          </div>

          {(mapView.viewMode === "provinces" || mapView.viewMode === "regions") && provinceData.length > 0 && (
            <div className="bg-card rounded-2xl border border-border/50 p-5 shadow-sm mt-4 animate-slide-up">
              <h3 className="text-sm font-semibold text-foreground mb-4">
                {mapView.viewMode === "provinces" ? "Avg Frequency by Province" : "Avg Frequency by Region"}
              </h3>
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={mapView.viewMode === "regions" ? provinceData.reduce((acc, p) => {
                  const region = getRegion(p.fullName);
                  const existing = acc.find((r) => r.name === region);
                  if (existing) {
                    existing.sum += p.sum;
                    existing.count += p.count;
                    existing.avg = Math.round(existing.sum / existing.count * 10) / 10;
                  } else {
                    acc.push({ name: region, sum: p.sum, count: p.count, avg: p.avg, fullName: region });
                  }
                  return acc;
                }, [] as typeof provinceData) : provinceData} margin={{ top: 4, right: 8, bottom: 4, left: 8 }}>
                  <XAxis dataKey="name" tick={{ fontSize: 10 }} angle={-30} textAnchor="end" height={50} />
                  <YAxis tick={{ fontSize: 10 }} />
                  <Tooltip
                    contentStyle={{ fontSize: 12, borderRadius: 12, border: '1px solid var(--color-border)' }}
                    formatter={(value: number) => [`${value}`, "Avg trains/day"]}
                  />
                  <Bar dataKey="avg" fill="oklch(0.55 0.15 250)" radius={[6, 6, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}

          {mapView.viewMode === "segments" && topSegments.length > 0 && (
            <div className="mt-4 animate-slide-up">
              <DataTable
                title="Top Segments by Frequency"
                keyFn={(s) => s.id}
                data={topSegments}
                columns={[
                  { header: "#", accessor: (_, i) => i + 1, className: "text-muted-foreground w-10" },
                  { header: "From", accessor: (s) => <span className="font-medium">{stationNameById.get(s.id.split("_")[0]) ?? s.id.split("_")[0]}</span> },
                  { header: "To", accessor: (s) => <span className="font-medium">{stationNameById.get(s.id.split("_")[1]) ?? s.id.split("_")[1]}</span> },
                  { header: "Trains/day", accessor: (s) => <span className="font-semibold text-primary">{fmt(s.freq, 1)}</span>, align: "right" },
                ]}
              />
            </div>
          )}

          {mapView.viewMode === "stations" && (
            <div className="mt-4 animate-slide-up">
              <DataTable
                title="Top Stations by Frequency"
                keyFn={(s) => s.id}
                data={data.stations}
                onRowClick={handleStationClick}
                columns={[
                  { header: "#", accessor: (_, i) => i + 1, className: "text-muted-foreground w-10" },
                  { header: "Station", accessor: (s) => <span className="font-medium">{s.name}</span> },
                  { header: "Trains/day", accessor: (s) => <span className="font-semibold text-primary">{fmt(s.freq, 1)}</span>, align: "right" },
                ]}
              />
            </div>
          )}

          <div className="mt-4">
            <MethodologyPanel>
              <p>Segment frequencies are computed from GTFS stop_times: consecutive stops in each trip define a segment. Frequencies are summed across all matching trips and normalized by the number of service days.</p>
              <p>Segments are matched to Infrabel track infrastructure geometry. When a direct match isn't found, BFS path-finding through the track network is attempted (up to 30 hops). Unmatched segments fall back to straight-line geometry.</p>
            </MethodologyPanel>
          </div>
        </>
      )}

      {(error || data?.error) && <ErrorAlert message={data?.error ?? (error as Error).message} />}
    </Layout>
  );
}
