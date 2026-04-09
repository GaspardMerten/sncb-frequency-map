import { createRoute } from "@tanstack/react-router";
import { useState, useMemo, useRef, useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import { MapPin } from "lucide-react";
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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Select, SelectOption } from "@/components/ui/select";
import { DeckMap, type DeckMapRef } from "@/components/DeckMap";
import { fetchApi } from "@/lib/api";
import { filterParams, fmt, daysAgo, today } from "@/lib/utils";
import { stationLayer, segmentLayer, choroplethLayer, colorToRGBA } from "@/lib/layers";
import { aggregateByProvince, buildChoroplethGeoJSON, buildRegionGeoJSON, getRegion } from "@/lib/geo";

export const reachRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/reach",
  component: ReachPage,
});

interface ReachStation {
  id: string; name: string; lat: number; lon: number; reachable: number;
  destinations?: { name: string; lat: number; lon: number; time: number; path?: [number, number][] }[];
}
interface ReachData {
  stations: ReachStation[]; max_reachable: number; avg_reachable: number; median_reachable: number; error?: string;
}

function ReachPage() {
  const [filters, setFilters] = useState<Filters>({
    startDate: daysAgo(7), endDate: today(), weekdays: [0, 1, 2, 3, 4],
    excludePub: false, excludeSch: false, useHour: false, hourStart: 7, hourEnd: 19,
  });
  const [timeBudget, setTimeBudget] = useState(1.5);
  const [depStart, setDepStart] = useState(7);
  const [depEnd, setDepEnd] = useState(9);
  const [maxTransfers, setMaxTransfers] = useState(3);
  const [minTransferTime, setMinTransferTime] = useState(5);
  const [selectedStation, setSelectedStation] = useState("");
  const [viewMode, setViewMode] = useState("stations");
  const [queryParams, setQueryParams] = useState<Record<string, string | number | boolean> | null>(null);
  const mapRef = useRef<DeckMapRef>(null);

  const { data, error, isFetching } = useQuery({
    queryKey: ["reach", queryParams],
    queryFn: () => fetchApi<ReachData>("/reach", queryParams!),
    enabled: !!queryParams,
  });

  const { data: geoData } = useQuery({
    queryKey: ["provinces"],
    queryFn: () => fetchApi<any>("/provinces"),
  });

  const loadData = () => setQueryParams({
    ...filterParams(filters), time_budget: timeBudget, dep_start: depStart,
    dep_end: depEnd, max_transfers: maxTransfers, min_transfer_time: minTransferTime,
  });

  const handleSelectStation = useCallback((stationId: string) => {
    setSelectedStation(stationId);
    if (stationId && data) {
      const s = data.stations.find((x) => x.id === stationId);
      if (s) {
        mapRef.current?.flyTo({ longitude: s.lon, latitude: s.lat, zoom: 9 });
      }
    }
  }, [data]);

  // Province aggregation for bar charts
  const provinceData = useMemo(() => {
    if (!data || !geoData) return [];
    const byProvince = aggregateByProvince(
      data.stations, geoData,
      (d) => d.lon, (d) => d.lat, (d) => d.reachable,
    );
    return Array.from(byProvince.entries())
      .map(([name, agg]) => ({ name: name.length > 12 ? name.slice(0, 12) + "..." : name, fullName: name, avg: Math.round(agg.avg * 10) / 10, count: agg.count }))
      .sort((a, b) => b.avg - a.avg);
  }, [data, geoData]);

  const layers = useMemo<Layer[]>(() => {
    if (!data || data.error) return [];

    if (viewMode === "provinces" && geoData) {
      const byProvince = aggregateByProvince(
        data.stations, geoData,
        (d) => d.lon, (d) => d.lat, (d) => d.reachable,
      );
      const valueMap = new Map<string, number>();
      for (const [name, agg] of byProvince) valueMap.set(name, agg.avg);
      const maxVal = Math.max(...valueMap.values(), 1);
      const enriched = buildChoroplethGeoJSON(geoData, valueMap);

      return [choroplethLayer("reach-province-choropleth", enriched, {
        valueFn: (f) => f.properties._value,
        colorFn: (f) => colorToRGBA(f.properties._value / maxVal, 160),
        pickable: true,
      })] as Layer[];
    }

    if (viewMode === "regions" && geoData) {
      const byProvince = aggregateByProvince(
        data.stations, geoData,
        (d) => d.lon, (d) => d.lat, (d) => d.reachable,
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

      return [choroplethLayer("reach-region-choropleth", regionGeo, {
        valueFn: (f) => f.properties._value,
        colorFn: (f) => colorToRGBA(f.properties._value / maxVal, 160),
        pickable: true,
      })] as Layer[];
    }

    if (viewMode !== "stations") return [];

    const stations = data.stations;
    if (!stations.length) return [];
    const maxReach = Math.max(...stations.map((s) => s.reachable));

    const result: Layer[] = [];

    result.push(
      stationLayer("reach-stations", stations, {
        positionFn: (d) => [d.lon, d.lat],
        radiusFn: (d) => 4 + (d.reachable / Math.max(maxReach, 1)) * 12,
        colorFn: (d) => colorToRGBA(d.reachable / Math.max(maxReach, 1)),
        radiusMinPixels: 3,
        radiusMaxPixels: 30,
        pickable: true,
      }) as Layer,
    );

    if (selectedStation) {
      const s = stations.find((x) => x.id === selectedStation);
      if (s) {
        result.push(
          stationLayer("reach-selected", [s], {
            positionFn: (d) => [d.lon, d.lat],
            radiusFn: () => 10,
            colorFn: () => [227, 26, 28, 230],
            radiusMinPixels: 8,
            radiusMaxPixels: 16,
            pickable: false,
          }) as Layer,
        );

        if (s.destinations && s.destinations.length) {
          // Draw route paths if available
          const destsWithPath = s.destinations.filter((d) => d.path && d.path.length >= 2);
          if (destsWithPath.length) {
            result.push(
              segmentLayer("reach-routes", destsWithPath, {
                pathFn: (d) => d.path!.map(([lat, lon]) => [lon, lat] as [number, number]),
                widthFn: () => 2,
                colorFn: (d) => colorToRGBA(d.time / (timeBudget * 60), 160),
                widthMinPixels: 1,
                widthMaxPixels: 6,
              }) as Layer,
            );
          }

          // Draw straight lines for destinations without path data
          const destsWithoutPath = s.destinations.filter((d) => !d.path || d.path.length < 2);
          if (destsWithoutPath.length) {
            result.push(
              segmentLayer("reach-routes-fallback", destsWithoutPath, {
                pathFn: (d) => [[s.lon, s.lat], [d.lon, d.lat]],
                widthFn: () => 1,
                colorFn: (d) => colorToRGBA(d.time / (timeBudget * 60), 100),
                widthMinPixels: 1,
                widthMaxPixels: 3,
              }) as Layer,
            );
          }

          result.push(
            stationLayer("reach-destinations", s.destinations, {
              positionFn: (d) => [d.lon, d.lat],
              radiusFn: () => 5,
              colorFn: (d) => colorToRGBA(d.time / (timeBudget * 60)),
              radiusMinPixels: 4,
              radiusMaxPixels: 12,
              pickable: true,
            }) as Layer,
          );
        }
      }
    }

    return result;
  }, [data, viewMode, selectedStation, timeBudget, geoData]);

  return (
    <Layout
      sidebar={
        <>
          <div className="space-y-2">
            <Label>Reach Settings</Label>
            <div>
              <span className="text-[10px] text-muted-foreground/60">Time budget (hours)</span>
              <Input type="number" value={timeBudget} min={0.5} max={6} step={0.5} onChange={(e) => setTimeBudget(+e.target.value)} className="h-8 text-xs" />
            </div>
            <div>
              <span className="text-[10px] text-muted-foreground/60">Departure window</span>
              <div className="flex items-center gap-2">
                <Input type="number" value={depStart} min={0} max={24} onChange={(e) => setDepStart(+e.target.value)} className="w-16 h-8 text-xs" />
                <span className="text-xs text-muted-foreground/50">to</span>
                <Input type="number" value={depEnd} min={0} max={24} onChange={(e) => setDepEnd(+e.target.value)} className="w-16 h-8 text-xs" />
              </div>
            </div>
            <div>
              <span className="text-[10px] text-muted-foreground/60">Max transfers</span>
              <Input type="number" value={maxTransfers} min={0} max={5} onChange={(e) => setMaxTransfers(+e.target.value)} className="h-8 text-xs" />
            </div>
            <div>
              <span className="text-[10px] text-muted-foreground/60">Min transfer time (min)</span>
              <Input type="number" value={minTransferTime} min={0} max={15} onChange={(e) => setMinTransferTime(+e.target.value)} className="h-8 text-xs" />
            </div>
          </div>
          <div className="border-t border-border/40 pt-3 mt-3">
            <FilterPanel filters={filters} onChange={setFilters} />
          </div>
          <ApplyButton loading={isFetching} onClick={loadData} label="Compute Reachability" loadingLabel="Computing..." />
        </>
      }
    >
      {data && !data.error && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5 animate-slide-up">
          <MetricCard label="Stations" value={fmt(data.stations.length)} />
          <MetricCard label="Max Reachable" value={fmt(data.max_reachable)} />
          <MetricCard label="Avg Reachable" value={fmt(data.avg_reachable, 1)} />
          <MetricCard label="Median" value={fmt(data.median_reachable)} />
        </div>
      )}

      {isFetching && <LoadingState message="Computing reachability (this may take a while)..." />}
      {!isFetching && !data && <EmptyState icon={MapPin} message="Configure settings and click Compute" />}

      {data && !data.error && !isFetching && (
        <>
          <Tabs value={viewMode} onValueChange={setViewMode} className="mb-4">
            <TabsList>
              <TabsTrigger value="stations">Stations</TabsTrigger>
              <TabsTrigger value="provinces">Provinces</TabsTrigger>
              <TabsTrigger value="regions">Regions</TabsTrigger>
            </TabsList>
          </Tabs>

          {viewMode === "stations" && (
            <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
              <div className="xl:col-span-2 space-y-2">
                <DeckMap ref={mapRef} layers={layers} className="h-[calc(100vh-16rem)]" />
                <ColorLegend min="Few reachable" max="Many reachable" />
              </div>
              <div>
                <div className="mb-3">
                  <span className="text-[10px] text-muted-foreground/60 block mb-1">Highlight station</span>
                  <Select value={selectedStation} onValueChange={handleSelectStation}>
                    <SelectOption value="">All stations</SelectOption>
                    {data.stations.map((s) => <SelectOption key={s.id} value={s.id}>{s.name} ({s.reachable})</SelectOption>)}
                  </Select>
                </div>
                <DataTable
                  title="Stations by Reachability"
                  keyFn={(s) => s.id}
                  data={data.stations}
                  onRowClick={(s) => handleSelectStation(s.id)}
                  columns={[
                    { header: "Station", accessor: (s) => <span className="font-medium truncate max-w-[160px] block">{s.name}</span> },
                    { header: "Reachable", accessor: (s) => <span className="font-semibold text-primary">{s.reachable}</span>, align: "right" },
                  ]}
                />
              </div>
            </div>
          )}

          {(viewMode === "provinces" || viewMode === "regions") && (
            <div className="space-y-4">
              <div className="space-y-2">
                <DeckMap ref={mapRef} layers={layers} className="h-[calc(100vh-18rem)]" />
                <ColorLegend min="Low avg reachable" max="High avg reachable" />
              </div>
              {viewMode === "provinces" && provinceData.length > 0 && (
                <div className="bg-card rounded-2xl border border-border/50 p-5 shadow-sm animate-slide-up">
                  <h3 className="text-sm font-semibold text-foreground mb-4">Avg Reachable Stations by Province</h3>
                  <ResponsiveContainer width="100%" height={220}>
                    <BarChart data={provinceData} margin={{ top: 4, right: 8, bottom: 4, left: 8 }}>
                      <XAxis dataKey="name" tick={{ fontSize: 10 }} angle={-30} textAnchor="end" height={50} />
                      <YAxis tick={{ fontSize: 10 }} allowDecimals={false} />
                      <Tooltip
                        contentStyle={{ fontSize: 12, borderRadius: 12, border: '1px solid var(--color-border)' }}
                        formatter={(value: number) => [`${value}`, "Avg reachable"]}
                      />
                      <Bar dataKey="avg" fill="oklch(0.55 0.15 250)" radius={[6, 6, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              )}
            </div>
          )}

          <div className="mt-4">
            <MethodologyPanel>
              <p>Reachability is computed using a Breadth-First Search (BFS) on the GTFS timetable graph. For each station, the algorithm explores all trains departing within the departure window and follows connections (with configurable transfer penalties) until the time budget is exhausted.</p>
              <p>The reachable count represents how many unique stations can be reached from each origin within the given time budget and transfer constraints. When a station is selected, route paths are drawn using infrastructure geometry where available, with straight-line fallbacks.</p>
            </MethodologyPanel>
          </div>
        </>
      )}

      {(error || data?.error) && <ErrorAlert message={data?.error ?? (error as Error).message} />}
    </Layout>
  );
}
