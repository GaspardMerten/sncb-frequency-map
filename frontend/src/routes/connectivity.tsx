import { createRoute } from "@tanstack/react-router";
import { useState, useMemo, useRef, useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import type { Layer } from "@deck.gl/core";
import { BarChart3 } from "lucide-react";
import { ScatterChart, Scatter, XAxis, YAxis, ZAxis, Tooltip, ResponsiveContainer, Legend } from "recharts";
import { rootRoute } from "./__root";
import { Layout } from "@/components/Layout";
import { FilterPanel, type Filters } from "@/components/FilterPanel";
import { MetricCard } from "@/components/MetricCard";
import { LoadingState } from "@/components/LoadingState";
import { EmptyState } from "@/components/EmptyState";
import { ErrorAlert } from "@/components/ErrorAlert";
import { ApplyButton } from "@/components/ApplyButton";
import { MethodologyPanel } from "@/components/MethodologyPanel";
import { DataTable } from "@/components/DataTable";
import { DeckMap, type DeckMapRef } from "@/components/DeckMap";
import { MapViewBar } from "@/components/MapViewBar";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { fetchApi } from "@/lib/api";
import { filterParams, fmt, daysAgo, today } from "@/lib/utils";
import { stationLayer } from "@/lib/layers";
import { tooltipBox } from "@/lib/tooltip";
import { useMapView, type StationSize, type MetricOption } from "@/hooks/useMapView";

export const connectivityRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/connectivity",
  component: ConnectivityPage,
});

interface Station {
  name: string; lat: number; lon: number; reachable: number; direct_freq: number;
  reach_km: number; size: string; region: string;
}
interface ConnectivityData {
  stations: Station[]; total: number; n_small: number; n_medium: number; n_big: number; error?: string;
}

const SIZE_COLORS: Record<string, [number, number, number, number]> = {
  small: [76, 175, 80, 180],
  medium: [255, 152, 0, 180],
  big: [211, 47, 47, 180],
};

const SIZE_CSS: Record<string, string> = {
  small: "#4caf50",
  medium: "#ff9800",
  big: "#d32f2f",
};

const METRICS: MetricOption[] = [
  { key: "reachable", label: "Reachable stations", accessor: (d: Station) => d.reachable },
  { key: "direct_freq", label: "Direct freq/h", accessor: (d: Station) => d.direct_freq, suffix: "/h" },
  { key: "reach_km", label: "Cardinal reach (km)", accessor: (d: Station) => d.reach_km, suffix: " km" },
];

const SCATTER_TABS = [
  { value: "ab", label: "Reachable vs Freq", xKey: "reachable", yKey: "direct_freq", zKey: "reach_km", xLabel: "Reachable stations", yLabel: "Direct freq/h", zLabel: "Cardinal reach (km)" },
  { value: "bc", label: "Freq vs Reach", xKey: "direct_freq", yKey: "reach_km", zKey: "reachable", xLabel: "Direct freq/h", yLabel: "Cardinal reach (km)", zLabel: "Reachable stations" },
  { value: "ac", label: "Reachable vs Reach", xKey: "reachable", yKey: "reach_km", zKey: "direct_freq", xLabel: "Reachable stations", yLabel: "Cardinal reach (km)", zLabel: "Direct freq/h" },
] as const;

function ConnectivityPage() {
  const [filters, setFilters] = useState<Filters>({
    startDate: daysAgo(7), endDate: today(), weekdays: [0, 1, 2, 3, 4],
    excludePub: false, excludeSch: false, useHour: false, hourStart: 7, hourEnd: 19,
  });
  const [timeBudget, setTimeBudget] = useState(2.0);
  const [maxTransfers, setMaxTransfers] = useState(2);
  const [depStart, setDepStart] = useState(7);
  const [depEnd, setDepEnd] = useState(9);
  const [scatterTab, setScatterTab] = useState("ab");
  const [sizeTab, setSizeTab] = useState("all");
  const [queryParams, setQueryParams] = useState<Record<string, string | number | boolean> | null>(null);
  const mapRef = useRef<DeckMapRef>(null);

  const { data, error, isFetching } = useQuery({
    queryKey: ["connectivity", queryParams],
    queryFn: () => fetchApi<ConnectivityData>("/connectivity", queryParams!),
    enabled: !!queryParams,
  });

  const { data: geoData } = useQuery({
    queryKey: ["provinces"],
    queryFn: () => fetchApi<any>("/provinces"),
  });

  const loadData = () => setQueryParams({
    ...filterParams(filters), time_budget: timeBudget, max_transfers: maxTransfers,
    dep_start: depStart, dep_end: depEnd,
  });

  const mapView = useMapView<Station>({
    data: data?.stations ?? [],
    geoData,
    getLon: (d) => d.lon,
    getLat: (d) => d.lat,
    getSize: (d) => d.size as StationSize,
    metrics: METRICS,
  });

  const handleStationClick = useCallback((s: Station) => {
    mapRef.current?.flyTo({ longitude: s.lon, latitude: s.lat, zoom: 12 });
  }, []);

  const sizeFilteredStations = useMemo(() => {
    if (sizeTab === "all") return mapView.filtered;
    return mapView.filtered.filter((s) => s.size === sizeTab);
  }, [mapView.filtered, sizeTab]);

  const stationLayers = useMemo<Layer[]>(() => {
    if (!mapView.filtered.length) return [];
    const maxFreq = Math.max(...mapView.filtered.map((s) => s.direct_freq));
    return [
      stationLayer("connectivity-stations", mapView.filtered, {
        positionFn: (d) => [d.lon, d.lat],
        radiusFn: (d) => 3 + (d.direct_freq / Math.max(maxFreq, 1)) * 12,
        colorFn: (d) => SIZE_COLORS[d.size] ?? [51, 51, 51, 160],
        radiusMinPixels: 3,
        radiusMaxPixels: 20,
      }),
    ] as Layer[];
  }, [mapView.filtered]);

  const layers = mapView.isOverlayView ? mapView.overlayLayers : stationLayers;

  const regionColors: Record<string, string> = { Brussels: "#e31a1c", Flanders: "#ff7f00", Wallonia: "#2557e6" };

  const scatterData = useMemo(() => {
    return Object.entries(regionColors).map(([region, color]) => ({
      region, color,
      data: sizeFilteredStations.filter((s) => s.region === region),
    }));
  }, [sizeFilteredStations]);

  const sizeAvg = useMemo(() => {
    if (!sizeFilteredStations.length) return { count: 0, avgReachable: 0, avgFreq: 0, avgReach: 0 };
    const count = sizeFilteredStations.length;
    const avgReachable = sizeFilteredStations.reduce((sum, s) => sum + s.reachable, 0) / count;
    const avgFreq = sizeFilteredStations.reduce((sum, s) => sum + s.direct_freq, 0) / count;
    const avgReach = sizeFilteredStations.reduce((sum, s) => sum + s.reach_km, 0) / count;
    return { count, avgReachable, avgFreq, avgReach };
  }, [sizeFilteredStations]);

  const sizeComparisonData = useMemo(() => {
    if (!data) return [];
    const sizes = ["small", "medium", "big"] as const;
    const labels: Record<string, string> = { small: "Small", medium: "Medium", big: "Big" };
    return sizes.map((size) => {
      const stations = data.stations.filter((s) => s.size === size);
      const count = stations.length;
      if (count === 0) return { label: labels[size], count: 0, avgReachable: 0, avgFreq: 0, avgReach: 0 };
      const avgReachable = stations.reduce((sum, s) => sum + s.reachable, 0) / count;
      const avgFreq = stations.reduce((sum, s) => sum + s.direct_freq, 0) / count;
      const avgReach = stations.reduce((sum, s) => sum + s.reach_km, 0) / count;
      return { label: labels[size], count, avgReachable, avgFreq, avgReach };
    });
  }, [data]);

  const zDomains = useMemo(() => {
    if (!sizeFilteredStations.length) return { maxReachable: 1, maxFreq: 1, maxReach: 1 };
    return {
      maxReachable: Math.max(...sizeFilteredStations.map((s) => s.reachable), 1),
      maxFreq: Math.max(...sizeFilteredStations.map((s) => s.direct_freq), 1),
      maxReach: Math.max(...sizeFilteredStations.map((s) => s.reach_km), 1),
    };
  }, [sizeFilteredStations]);

  const activeScatter = SCATTER_TABS.find((t) => t.value === scatterTab) ?? SCATTER_TABS[0];

  const renderScatterChart = (xKey: string, yKey: string, zKey: string, xLabel: string, yLabel: string, zLabel: string) => {
    const keyMap: Record<string, (s: Station) => number> = {
      reachable: (s) => s.reachable, direct_freq: (s) => s.direct_freq, reach_km: (s) => s.reach_km,
    };
    const getX = keyMap[xKey], getY = keyMap[yKey], getZ = keyMap[zKey];
    const maxZ = zKey === "reachable" ? zDomains.maxReachable : zKey === "direct_freq" ? zDomains.maxFreq : zDomains.maxReach;

    return (
      <ResponsiveContainer width="100%" height="100%">
        <ScatterChart>
          <XAxis dataKey="x" name={xLabel} type="number" tick={{ fontSize: 11 }} />
          <YAxis dataKey="y" name={yLabel} type="number" tick={{ fontSize: 11 }} />
          <ZAxis dataKey="z" name={zLabel} type="number" range={[20, 400]} domain={[0, maxZ]} />
          <Tooltip cursor={{ strokeDasharray: "3 3" }} content={({ payload }) => {
            if (!payload?.[0]) return null;
            const d = payload[0].payload;
            return (
              <div className="bg-card border border-border/50 rounded-xl px-3 py-2 text-xs shadow-lg">
                <b>{d.name}</b><br />
                {xLabel}: {typeof d.x === "number" && d.x % 1 !== 0 ? d.x.toFixed(1) : d.x}<br />
                {yLabel}: {typeof d.y === "number" && d.y % 1 !== 0 ? d.y.toFixed(1) : d.y}<br />
                <span className="text-muted-foreground">{zLabel} (bubble size): {typeof d.z === "number" && d.z % 1 !== 0 ? d.z.toFixed(1) : d.z}</span>
              </div>
            );
          }} />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          {scatterData.map(({ region, color, data: regionData }) => (
            <Scatter key={region} name={region}
              data={regionData.map((s) => ({ x: getX(s), y: getY(s), z: getZ(s), name: s.name }))}
              fill={color + "88"} stroke={color} />
          ))}
        </ScatterChart>
      </ResponsiveContainer>
    );
  };

  return (
    <Layout
      sidebar={
        <>
          <div className="space-y-2">
            <Label>Settings</Label>
            <div>
              <span className="text-[10px] text-muted-foreground/60">Time budget (hours)</span>
              <Input type="number" value={timeBudget} min={0.5} max={6} step={0.5} onChange={(e) => setTimeBudget(+e.target.value)} className="h-8 text-xs" />
            </div>
            <div>
              <span className="text-[10px] text-muted-foreground/60">Max transfers</span>
              <Input type="number" value={maxTransfers} min={0} max={5} onChange={(e) => setMaxTransfers(+e.target.value)} className="h-8 text-xs" />
            </div>
            <div>
              <span className="text-[10px] text-muted-foreground/60">Departure window</span>
              <div className="flex items-center gap-2">
                <Input type="number" value={depStart} min={0} max={24} onChange={(e) => setDepStart(+e.target.value)} className="w-16 h-8 text-xs" />
                <span className="text-xs text-muted-foreground/50">to</span>
                <Input type="number" value={depEnd} min={0} max={24} onChange={(e) => setDepEnd(+e.target.value)} className="w-16 h-8 text-xs" />
              </div>
            </div>
          </div>
          <div className="border-t border-border/40 pt-3 mt-3">
            <FilterPanel filters={filters} onChange={setFilters} />
          </div>
          <ApplyButton loading={isFetching} onClick={loadData} label="Compute" />
        </>
      }
    >
      {isFetching && <LoadingState message="Computing connectivity metrics..." />}
      {!isFetching && !data && <EmptyState icon={BarChart3} message="Configure settings and click Compute" />}

      {data && !data.error && !isFetching && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5 animate-slide-up">
            <MetricCard label="Total Stations" value={fmt(data.total)} />
            <MetricCard label="Small (<4/h)" value={fmt(data.n_small)} />
            <MetricCard label="Medium (4-10/h)" value={fmt(data.n_medium)} />
            <MetricCard label="Big (>10/h)" value={fmt(data.n_big)} />
          </div>
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-4 mb-4">
            <div className="space-y-2">
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
              />
              <DeckMap ref={mapRef} layers={layers} className="h-96"
                getTooltip={({ object, layer }) => {
                  if (!object || !layer) return null;
                  const id = layer.id as string;
                  if (id === "connectivity-stations") {
                    return tooltipBox(
                      `<b>${object.name}</b> <span style="opacity:0.6">(${object.size})</span><br/>` +
                      `<b>${fmt(object.reachable ?? 0)}</b> reachable stations<br/>` +
                      `<span style="opacity:0.7">${fmt(object.direct_freq ?? 0, 1)} trains/h &middot; ${fmt(object.reach_km ?? 0, 0)} km reach</span>`
                    );
                  }
                  if (id.startsWith("mapview-")) {
                    const name = object.properties?.name ?? "";
                    const val = object.properties?._value;
                    return tooltipBox(`<b>${name}</b><br/>Avg ${mapView.activeMetric.label}: ${val != null ? fmt(val, 1) + (mapView.activeMetric.suffix ?? "") : "\u2014"}`);
                  }
                  return null;
                }}
              />
              {!mapView.isOverlayView && (
                <div className="flex gap-4 text-[10px] text-muted-foreground">
                  {Object.entries(SIZE_CSS).map(([size, color]) => (
                    <span key={size} className="flex items-center gap-1">
                      <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: color }} />
                      {size}
                    </span>
                  ))}
                  <span className="ml-auto">Circle size = direct frequency</span>
                </div>
              )}
            </div>
            <div className="bg-card rounded-2xl border border-border/50 p-5 h-96 shadow-sm">
              <Tabs value={scatterTab} onValueChange={setScatterTab} className="h-full flex flex-col">
                <TabsList className="w-full mb-3">
                  {SCATTER_TABS.map((t) => (
                    <TabsTrigger key={t.value} value={t.value} className="flex-1 text-xs">{t.label}</TabsTrigger>
                  ))}
                </TabsList>
                <p className="text-[10px] text-muted-foreground mb-2">
                  Bubble size = {activeScatter.zLabel} &middot; Color = region
                </p>
                <div className="flex-1">
                  {renderScatterChart(activeScatter.xKey, activeScatter.yKey, activeScatter.zKey, activeScatter.xLabel, activeScatter.yLabel, activeScatter.zLabel)}
                </div>
              </Tabs>
            </div>
          </div>

          <div className="bg-card rounded-2xl border border-border/50 p-5 shadow-sm mb-4">
            <Label className="mb-2 block">Station Size Breakdown</Label>
            <Tabs value={sizeTab} onValueChange={setSizeTab}>
              <TabsList className="w-full mb-3">
                <TabsTrigger value="all" className="flex-1 text-xs">All</TabsTrigger>
                <TabsTrigger value="small" className="flex-1 text-xs">Small</TabsTrigger>
                <TabsTrigger value="medium" className="flex-1 text-xs">Medium</TabsTrigger>
                <TabsTrigger value="big" className="flex-1 text-xs">Big</TabsTrigger>
              </TabsList>
            </Tabs>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-3">
              <MetricCard label="Stations" value={fmt(sizeAvg.count)} />
              <MetricCard label="Avg Reachable" value={sizeAvg.avgReachable.toFixed(1)} />
              <MetricCard label="Avg Freq/h" value={sizeAvg.avgFreq.toFixed(2)} />
              <MetricCard label="Avg Cardinal Reach" value={sizeAvg.avgReach.toFixed(0)} suffix=" km" />
            </div>
          </div>

          {sizeComparisonData.length > 0 && (
            <div className="mb-4 animate-slide-up">
              <DataTable
                title="Size Comparison Summary"
                keyFn={(row) => row.label}
                data={sizeComparisonData}
                onRowClick={() => {}}
                columns={[
                  { header: "Size", accessor: (row) => <span className="font-medium">{row.label}</span> },
                  { header: "Count", accessor: (row) => fmt(row.count), align: "right" },
                  { header: "Avg Reachable", accessor: (row) => row.avgReachable.toFixed(1), align: "right" },
                  { header: "Avg Freq/h", accessor: (row) => row.avgFreq.toFixed(2), align: "right" },
                  { header: "Avg Reach (km)", accessor: (row) => <span className="font-semibold text-primary">{row.avgReach.toFixed(0)}</span>, align: "right" },
                ]}
              />
            </div>
          )}

          {data.stations.length > 0 && (
            <div className="mb-4 animate-slide-up">
              <DataTable
                title="All Stations"
                keyFn={(s) => s.name}
                data={sizeFilteredStations}
                maxRows={50}
                onRowClick={handleStationClick}
                columns={[
                  { header: "Station", accessor: (s) => <span className="font-medium">{s.name}</span> },
                  { header: "Size", accessor: (s) => (
                    <span className="flex items-center gap-1">
                      <span className="w-2 h-2 rounded-full" style={{ backgroundColor: SIZE_CSS[s.size] }} />
                      <span className="text-muted-foreground capitalize">{s.size}</span>
                    </span>
                  )},
                  { header: "Reachable", accessor: (s) => fmt(s.reachable), align: "right" },
                  { header: "Freq/h", accessor: (s) => fmt(s.direct_freq, 1), align: "right" },
                  { header: "Reach (km)", accessor: (s) => <span className="font-semibold text-primary">{fmt(s.reach_km, 0)}</span>, align: "right" },
                ]}
              />
            </div>
          )}

          <MethodologyPanel>
            <p>Each station is evaluated on three connectivity dimensions:</p>
            <p><b>Reachable stations</b> — how many other stations can be reached within the time budget via BFS graph traversal, considering transfers and waiting times.</p>
            <p><b>Direct frequency</b> — average direct departures per hour (6h-22h), normalized across GTFS feeds. Stations are classified as Small (&lt;4/h), Medium (4-10/h), or Big (&gt;10/h).</p>
            <p><b>Cardinal reach</b> — maximum geographic distance reached in each cardinal direction (N/E/S/W), summed to represent how far a station's connections extend geographically.</p>
            <p>The scatter plots let you explore relationships between these three metrics. Each dot is a station, colored by region (Brussels / Flanders / Wallonia), with bubble size encoding the third metric.</p>
          </MethodologyPanel>
        </>
      )}

      {(error || data?.error) && <ErrorAlert message={data?.error ?? (error as Error).message} />}
    </Layout>
  );
}
