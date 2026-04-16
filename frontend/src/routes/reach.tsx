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
import { MapViewBar, mapViewTooltip } from "@/components/MapViewBar";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectOption } from "@/components/ui/select";
import { DeckMap, type DeckMapRef } from "@/components/DeckMap";
import { fetchApi } from "@/lib/api";
import { filterParams, fmt, daysAgo, today } from "@/lib/utils";
import { ScatterplotLayer } from "@deck.gl/layers";
import { stationLayer, colorToRGBA } from "@/lib/layers";
import { aggregateByProvince } from "@/lib/geo";
import { useMapView, makeTercileClassifier, type MetricOption } from "@/hooks/useMapView";

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

const METRICS: MetricOption[] = [
  { key: "reachable", label: "Reachable stations", accessor: (d: ReachStation) => d.reachable },
];

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

  const sizeClassifier = useMemo(
    () => makeTercileClassifier(data?.stations ?? [], (d) => d.reachable),
    [data],
  );

  const mapView = useMapView<ReachStation>({
    data: data?.stations ?? [],
    geoData,
    getLon: (d) => d.lon,
    getLat: (d) => d.lat,
    getSize: sizeClassifier,
    metrics: METRICS,
    showGradient: true,
  });

  const handleSelectStation = useCallback((stationId: string) => {
    setSelectedStation(stationId);
    if (stationId && data) {
      const s = data.stations.find((x) => x.id === stationId);
      if (s) mapRef.current?.flyTo({ longitude: s.lon, latitude: s.lat, zoom: 9 });
    }
  }, [data]);

  const provinceData = useMemo(() => {
    if (!data || !geoData) return [];
    const byProvince = aggregateByProvince(
      data.stations, geoData, (d) => d.lon, (d) => d.lat, (d) => d.reachable,
    );
    return Array.from(byProvince.entries())
      .map(([name, agg]) => ({ name: name.length > 12 ? name.slice(0, 12) + "..." : name, fullName: name, avg: Math.round(agg.avg * 10) / 10, count: agg.count }))
      .sort((a, b) => b.avg - a.avg);
  }, [data, geoData]);

  const stationLayers = useMemo<Layer[]>(() => {
    const stations = mapView.filtered;
    if (!stations.length) return [];
    const reaches = stations.map((s) => s.reachable);
    const maxReach = Math.max(...reaches);
    const minReach = Math.min(...reaches);
    const spread = Math.max(maxReach - minReach, 1);
    const ratio = (d: ReachStation) => (d.reachable - minReach) / spread;

    const selected = selectedStation ? stations.find((x) => x.id === selectedStation) : undefined;
    const reachableNames = selected?.destinations
      ? new Set(selected.destinations.map((d) => d.name))
      : null;

    const result: Layer[] = [];

    result.push(
      stationLayer("reach-stations", stations, {
        positionFn: (d) => [d.lon, d.lat],
        radiusFn: (d) => 3 + ratio(d) * 18,
        colorFn: (d) => {
          const [r, g, b] = colorToRGBA(ratio(d));
          if (reachableNames && d.id !== selectedStation && !reachableNames.has(d.name)) {
            return [r, g, b, 20];
          }
          return [r, g, b, 230];
        },
        radiusScale: 1,
        radiusMinPixels: 3,
        radiusMaxPixels: 40,
        pickable: true,
      }) as Layer,
    );

    if (selected) {
      result.push(
        new ScatterplotLayer({
          id: "reach-selected-halo",
          data: [selected],
          getPosition: (d: ReachStation) => [d.lon, d.lat],
          getRadius: 26, radiusUnits: "pixels",
          getFillColor: [227, 26, 28, 60],
          stroked: true, getLineColor: [227, 26, 28, 220], getLineWidth: 2, lineWidthUnits: "pixels",
          pickable: false,
        }) as unknown as Layer,
      );
      result.push(
        new ScatterplotLayer({
          id: "reach-selected",
          data: [selected],
          getPosition: (d: ReachStation) => [d.lon, d.lat],
          getRadius: 12, radiusUnits: "pixels",
          getFillColor: [227, 26, 28, 255],
          stroked: true, getLineColor: [255, 255, 255, 255], getLineWidth: 3, lineWidthUnits: "pixels",
          pickable: false,
        }) as unknown as Layer,
      );
    }

    return result;
  }, [mapView.filtered, selectedStation, timeBudget]);

  const layers = mapView.isOverlayView ? mapView.overlayLayers : stationLayers;

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
          />

          {!mapView.isOverlayView && (
            <div className="grid grid-cols-1 xl:grid-cols-3 gap-4 mt-3">
              <div className="xl:col-span-2 space-y-2">
                <DeckMap
                  ref={mapRef} layers={layers} className="h-[calc(100vh-16rem)]"
                  onClick={(info) => {
                    if (info?.layer?.id === "reach-stations" && info.object) {
                      setSelectedStation(info.object.id === selectedStation ? "" : info.object.id);
                    } else if (!info?.object) {
                      setSelectedStation("");
                    }
                  }}
                  getTooltip={(info) => {
                    const { object, layer } = info;
                    if (!object || !layer) return null;
                    const id = layer.id as string;
                    if (id === "reach-stations") {
                      const isSelected = object.id === selectedStation;
                      const isReachable = selectedStation && data?.stations.find((s) => s.id === selectedStation)?.destinations?.some((d) => d.name === object.name);
                      const badge = isSelected ? " (selected)" : isReachable ? " (reachable)" : "";
                      return {
                        html: `<div style="font-size:12px"><b>${object.name}</b>${badge}<br/>${fmt(object.reachable)} reachable stations</div>`,
                        style: { backgroundColor: "rgba(255,255,255,0.95)", color: "#111", padding: "6px 8px", borderRadius: "8px", border: "1px solid #e5e7eb", boxShadow: "0 2px 8px rgba(0,0,0,0.12)" },
                      };
                    }
                    return null;
                  }}
                />
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

          {mapView.isOverlayView && (
            <div className="space-y-4 mt-3">
              <div className="space-y-2">
                <DeckMap ref={mapRef} layers={layers} className="h-[calc(100vh-18rem)]"
                  getTooltip={(info) => mapViewTooltip(mapView.activeMetric, info)}
                />
              </div>
              {mapView.viewMode === "provinces" && provinceData.length > 0 && (
                <div className="bg-card rounded-2xl border border-border/50 p-5 shadow-sm animate-slide-up">
                  <h3 className="text-sm font-semibold text-foreground mb-4">Avg Reachable Stations by Province</h3>
                  <ResponsiveContainer width="100%" height={220}>
                    <BarChart data={provinceData} margin={{ top: 4, right: 8, bottom: 4, left: 8 }}>
                      <XAxis dataKey="name" tick={{ fontSize: 10 }} angle={-30} textAnchor="end" height={50} />
                      <YAxis tick={{ fontSize: 10 }} allowDecimals={false} />
                      <Tooltip contentStyle={{ fontSize: 12, borderRadius: 12, border: '1px solid var(--color-border)' }} formatter={(value: number) => [`${value}`, "Avg reachable"]} />
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
              <p>The reachable count represents how many unique stations can be reached from each origin within the given time budget and transfer constraints.</p>
            </MethodologyPanel>
          </div>
        </>
      )}

      {(error || data?.error) && <ErrorAlert message={data?.error ?? (error as Error).message} />}
    </Layout>
  );
}
