import { createRoute } from "@tanstack/react-router";
import { useState, useMemo, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { Train } from "lucide-react";
import type { Layer } from "@deck.gl/core";
import { rootRoute } from "./__root";
import { Layout } from "@/components/Layout";
import { FilterPanel, type Filters } from "@/components/FilterPanel";
import { MetricCard } from "@/components/MetricCard";
import { LoadingState } from "@/components/LoadingState";
import { EmptyState } from "@/components/EmptyState";
import { ErrorAlert } from "@/components/ErrorAlert";
import { ApplyButton } from "@/components/ApplyButton";
import { DataTable } from "@/components/DataTable";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { DeckMap, type DeckMapRef } from "@/components/DeckMap";
import { fetchApi } from "@/lib/api";
import { filterParams, fmt, daysAgo, today } from "@/lib/utils";
import { stationLayer, segmentLayer, colorToRGBA } from "@/lib/layers";

export const segmentsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/segments",
  component: SegmentsPage,
});

interface SegmentData {
  segments: { freq: number; coords: [number, number][] }[];
  stations: { id: string; name: string; freq: number; lat: number; lon: number }[];
  day_count: number;
  error?: string;
}

function SegmentsPage() {
  const [filters, setFilters] = useState<Filters>({
    startDate: daysAgo(7), endDate: today(), weekdays: [0, 1, 2, 3, 4],
    excludePub: false, excludeSch: false, useHour: false, hourStart: 7, hourEnd: 19,
  });
  const [viewMode, setViewMode] = useState<"segments" | "stations" | "provinces" | "regions">("segments");
  const [queryParams, setQueryParams] = useState<Record<string, string | number | boolean> | null>(null);
  const mapRef = useRef<DeckMapRef>(null);

  const { data, error, isFetching } = useQuery({
    queryKey: ["segments", queryParams],
    queryFn: () => fetchApi<SegmentData>("/segments", queryParams!),
    enabled: !!queryParams,
  });

  const loadData = () => setQueryParams(filterParams(filters));

  const layers = useMemo<Layer[]>(() => {
    if (!data || data.error) return [];
    if (viewMode === "provinces" || viewMode === "regions") return [];

    if (viewMode === "segments") {
      const segs = data.segments;
      if (!segs.length) return [];
      const maxFreq = Math.max(...segs.map((s) => s.freq));

      const pathLayer = segmentLayer("segment-paths", segs, {
        pathFn: (d) => d.coords.map(([lat, lon]) => [lon, lat] as [number, number]),
        widthFn: (d) => 2 + (d.freq / maxFreq) * 4,
        colorFn: (d) => colorToRGBA(d.freq / maxFreq),
        widthMinPixels: 1,
        widthMaxPixels: 10,
      });

      const dotLayer = stationLayer("segment-station-dots", data.stations, {
        positionFn: (d) => [d.lon, d.lat],
        radiusFn: () => 3,
        colorFn: () => [8, 69, 148, 160],
        radiusMinPixels: 2,
        radiusMaxPixels: 6,
        pickable: true,
      });

      return [pathLayer, dotLayer] as Layer[];
    }

    // viewMode === "stations"
    const stations = data.stations;
    if (!stations.length) return [];
    const maxFreq = stations[0].freq;

    const layer = stationLayer("station-circles", stations, {
      positionFn: (d) => [d.lon, d.lat],
      radiusFn: (d) => 4 + (d.freq / maxFreq) * 12,
      colorFn: (d) => colorToRGBA(d.freq / maxFreq),
      radiusScale: 1,
      radiusMinPixels: 3,
      radiusMaxPixels: 30,
      pickable: true,
    });

    return [layer] as Layer[];
  }, [data, viewMode]);

  return (
    <Layout
      sidebar={
        <>
          <div>
            <p className="text-[11px] font-semibold text-primary uppercase tracking-wider mb-2">View</p>
            <Tabs value={viewMode} onValueChange={(v) => setViewMode(v as typeof viewMode)}>
              <TabsList className="w-full">
                <TabsTrigger value="segments" className="flex-1">Segments</TabsTrigger>
                <TabsTrigger value="stations" className="flex-1">Stations</TabsTrigger>
                <TabsTrigger value="provinces" className="flex-1">Provinces</TabsTrigger>
                <TabsTrigger value="regions" className="flex-1">Regions</TabsTrigger>
              </TabsList>
            </Tabs>
          </div>
          <FilterPanel filters={filters} onChange={setFilters} />
          <ApplyButton loading={isFetching} onClick={loadData} />
        </>
      }
    >
      {data && !data.error && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
          <MetricCard label="Segments" value={fmt(data.segments.length)} />
          <MetricCard label="Stations" value={fmt(data.stations.length)} />
          <MetricCard label="Busiest" value={data.stations[0]?.name ?? "\u2014"} suffix="/day" />
          <MetricCard label="Avg Days" value={data.day_count} />
        </div>
      )}

      {isFetching && <LoadingState message="Loading GTFS data..." />}
      {!isFetching && !data && <EmptyState icon={Train} />}

      {data && !data.error && !isFetching && (viewMode === "provinces" || viewMode === "regions") && (
        <div className="flex items-center justify-center h-[calc(100vh-14rem)] rounded-xl border border-border bg-muted/30">
          <p className="text-muted-foreground text-sm">View mode coming soon</p>
        </div>
      )}

      {data && !data.error && !isFetching && (viewMode === "segments" || viewMode === "stations") && (
        <>
          <DeckMap ref={mapRef} layers={layers} className="h-[calc(100vh-14rem)]" />
          {viewMode === "stations" && (
            <div className="mt-4">
              <DataTable
                title="Top Stations by Frequency"
                keyFn={(s) => s.id}
                data={data.stations}
                columns={[
                  { header: "#", accessor: (_, i) => i + 1, className: "text-muted-foreground w-10" },
                  { header: "Station", accessor: (s) => <span className="font-medium">{s.name}</span> },
                  { header: "Trains/day", accessor: (s) => <span className="font-semibold text-primary">{fmt(s.freq, 1)}</span>, align: "right" },
                ]}
              />
            </div>
          )}
        </>
      )}

      {(error || data?.error) && <ErrorAlert message={data?.error ?? (error as Error).message} />}
    </Layout>
  );
}
