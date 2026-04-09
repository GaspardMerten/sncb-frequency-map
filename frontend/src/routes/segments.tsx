import { createRoute } from "@tanstack/react-router";
import { useState, useMemo, useRef } from "react";
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
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { DeckMap, type DeckMapRef } from "@/components/DeckMap";
import { fetchApi } from "@/lib/api";
import { filterParams, fmt, daysAgo, today } from "@/lib/utils";
import { stationLayer, segmentLayer, choroplethLayer, colorToRGBA } from "@/lib/layers";
import { aggregateByProvince, buildChoroplethGeoJSON, buildRegionGeoJSON, getRegion } from "@/lib/geo";

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

  const { data: geoData } = useQuery({
    queryKey: ["provinces"],
    queryFn: () => fetchApi<any>("/provinces"),
  });

  const loadData = () => setQueryParams(filterParams(filters));

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

  const layers = useMemo<Layer[]>(() => {
    if (!data || data.error) return [];

    if (viewMode === "provinces" && geoData) {
      const byProvince = aggregateByProvince(
        data.stations, geoData,
        (d) => d.lon, (d) => d.lat, (d) => d.freq,
      );
      const valueMap = new Map<string, number>();
      for (const [name, agg] of byProvince) valueMap.set(name, agg.avg);
      const maxVal = Math.max(...valueMap.values(), 1);
      const enriched = buildChoroplethGeoJSON(geoData, valueMap);

      return [choroplethLayer("province-choropleth", enriched, {
        valueFn: (f) => f.properties._value,
        colorFn: (f) => colorToRGBA(f.properties._value / maxVal, 160),
        pickable: true,
      })] as Layer[];
    }

    if (viewMode === "regions" && geoData) {
      const byProvince = aggregateByProvince(
        data.stations, geoData,
        (d) => d.lon, (d) => d.lat, (d) => d.freq,
      );
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
      for (const [region, agg] of regionAgg) valueMap.set(region, agg.sum / agg.count);
      const maxVal = Math.max(...valueMap.values(), 1);
      const regionGeo = buildRegionGeoJSON(geoData, valueMap);

      return [choroplethLayer("region-choropleth", regionGeo, {
        valueFn: (f) => f.properties._value,
        colorFn: (f) => colorToRGBA(f.properties._value / maxVal, 160),
        pickable: true,
      })] as Layer[];
    }

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
  }, [data, geoData, viewMode]);

  return (
    <Layout
      sidebar={
        <>
          <div>
            <p className="text-[10px] font-semibold text-foreground/40 uppercase tracking-widest mb-2">View</p>
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
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5 animate-slide-up">
          <MetricCard label="Segments" value={fmt(data.segments.length)} />
          <MetricCard label="Stations" value={fmt(data.stations.length)} />
          <MetricCard label="Busiest" value={data.stations[0]?.name ?? "\u2014"} suffix="/day" />
          <MetricCard label="Avg Days" value={data.day_count} />
        </div>
      )}

      {isFetching && <LoadingState message="Loading GTFS data..." />}
      {!isFetching && !data && <EmptyState icon={Train} />}

      {data && !data.error && !isFetching && (
        <>
          <div className="space-y-2">
            <DeckMap ref={mapRef} layers={layers} className="h-[calc(100vh-14rem)]" />
            <ColorLegend min="Low frequency" max="High frequency" />
          </div>

          {(viewMode === "provinces" || viewMode === "regions") && provinceData.length > 0 && (
            <div className="bg-card rounded-2xl border border-border/50 p-5 shadow-sm mt-4 animate-slide-up">
              <h3 className="text-sm font-semibold text-foreground mb-4">
                {viewMode === "provinces" ? "Avg Frequency by Province" : "Avg Frequency by Region"}
              </h3>
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={viewMode === "regions" ? provinceData.reduce((acc, p) => {
                  // Group by region for region view
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

          {viewMode === "stations" && (
            <div className="mt-4 animate-slide-up">
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
