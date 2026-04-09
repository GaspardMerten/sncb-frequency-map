import { createRoute } from "@tanstack/react-router";
import { useState, useMemo, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import type { Layer } from "@deck.gl/core";
import { BarChart3 } from "lucide-react";
import { ScatterChart, Scatter, XAxis, YAxis, Tooltip, ResponsiveContainer, Legend } from "recharts";
import { rootRoute } from "./__root";
import { Layout } from "@/components/Layout";
import { FilterPanel, type Filters } from "@/components/FilterPanel";
import { MetricCard } from "@/components/MetricCard";
import { LoadingState } from "@/components/LoadingState";
import { EmptyState } from "@/components/EmptyState";
import { ErrorAlert } from "@/components/ErrorAlert";
import { ApplyButton } from "@/components/ApplyButton";
import { DeckMap, type DeckMapRef } from "@/components/DeckMap";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { fetchApi } from "@/lib/api";
import { filterParams, fmt, daysAgo, today } from "@/lib/utils";
import { stationLayer } from "@/lib/layers";

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
  small: [107, 174, 214, 160],
  medium: [33, 113, 181, 160],
  big: [8, 69, 148, 160],
};

function ConnectivityPage() {
  const [filters, setFilters] = useState<Filters>({
    startDate: daysAgo(7), endDate: today(), weekdays: [0, 1, 2, 3, 4],
    excludePub: false, excludeSch: false, useHour: false, hourStart: 7, hourEnd: 19,
  });
  const [timeBudget, setTimeBudget] = useState(2.0);
  const [maxTransfers, setMaxTransfers] = useState(2);
  const [depStart, setDepStart] = useState(7);
  const [depEnd, setDepEnd] = useState(9);
  const [showSmall, setShowSmall] = useState(true);
  const [showMedium, setShowMedium] = useState(true);
  const [showBig, setShowBig] = useState(true);
  const [scatterTab, setScatterTab] = useState("ab");
  const [sizeTab, setSizeTab] = useState("all");
  const [queryParams, setQueryParams] = useState<Record<string, string | number | boolean> | null>(null);
  const mapRef = useRef<DeckMapRef>(null);

  const { data, error, isFetching } = useQuery({
    queryKey: ["connectivity", queryParams],
    queryFn: () => fetchApi<ConnectivityData>("/connectivity", queryParams!),
    enabled: !!queryParams,
  });

  const loadData = () => setQueryParams({
    ...filterParams(filters), time_budget: timeBudget, max_transfers: maxTransfers,
    dep_start: depStart, dep_end: depEnd,
  });

  const filteredStations = useMemo(() => {
    if (!data) return [];
    return data.stations.filter((s) =>
      (s.size === "small" && showSmall) || (s.size === "medium" && showMedium) || (s.size === "big" && showBig)
    );
  }, [data, showSmall, showMedium, showBig]);

  const sizeFilteredStations = useMemo(() => {
    if (sizeTab === "all") return filteredStations;
    return filteredStations.filter((s) => s.size === sizeTab);
  }, [filteredStations, sizeTab]);

  const layers = useMemo<Layer[]>(() => {
    if (!filteredStations.length) return [];
    const maxFreq = Math.max(...filteredStations.map((s) => s.direct_freq));

    return [
      stationLayer("connectivity-stations", filteredStations, {
        positionFn: (d) => [d.lon, d.lat],
        radiusFn: (d) => 3 + (d.direct_freq / Math.max(maxFreq, 1)) * 12,
        colorFn: (d) => SIZE_COLORS[d.size] ?? [51, 51, 51, 160],
        radiusMinPixels: 3,
        radiusMaxPixels: 20,
      }),
    ] as Layer[];
  }, [filteredStations]);

  const regionColors: Record<string, string> = { Brussels: "#e31a1c", Flanders: "#ff7f00", Wallonia: "#2171b5" };

  const scatterData = useMemo(() => {
    return Object.entries(regionColors).map(([region, color]) => ({
      region,
      color,
      data: sizeFilteredStations.filter((s) => s.region === region),
    }));
  }, [sizeFilteredStations]);

  const sizeAvg = useMemo(() => {
    if (!sizeFilteredStations.length) return { count: 0, avgA: 0, avgB: 0, avgC: 0 };
    const count = sizeFilteredStations.length;
    const avgA = sizeFilteredStations.reduce((sum, s) => sum + s.reachable, 0) / count;
    const avgB = sizeFilteredStations.reduce((sum, s) => sum + s.direct_freq, 0) / count;
    const avgC = sizeFilteredStations.reduce((sum, s) => sum + s.reach_km, 0) / count;
    return { count, avgA, avgB, avgC };
  }, [sizeFilteredStations]);

  const renderScatterChart = (xKey: string, yKey: string, xLabel: string, yLabel: string) => {
    const keyMap: Record<string, (s: Station) => number> = {
      reachable: (s) => s.reachable,
      direct_freq: (s) => s.direct_freq,
      reach_km: (s) => s.reach_km,
    };
    const getX = keyMap[xKey];
    const getY = keyMap[yKey];

    return (
      <ResponsiveContainer width="100%" height="100%">
        <ScatterChart>
          <XAxis dataKey="x" name={xLabel} type="number" tick={{ fontSize: 11 }} />
          <YAxis dataKey="y" name={yLabel} type="number" tick={{ fontSize: 11 }} />
          <Tooltip cursor={{ strokeDasharray: "3 3" }} content={({ payload }) => {
            if (!payload?.[0]) return null;
            const d = payload[0].payload;
            return (
              <div className="bg-card border border-border rounded-lg px-3 py-2 text-xs shadow-md">
                <b>{d.name}</b><br />
                {xLabel}={typeof d.x === "number" && d.x % 1 !== 0 ? d.x.toFixed(1) : d.x},
                {yLabel}={typeof d.y === "number" && d.y % 1 !== 0 ? d.y.toFixed(1) : d.y}
              </div>
            );
          }} />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          {scatterData.map(({ region, color, data: regionData }) => (
            <Scatter
              key={region}
              name={region}
              data={regionData.map((s) => ({ x: getX(s), y: getY(s), name: s.name }))}
              fill={color + "88"}
              stroke={color}
            />
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
              <span className="text-[10px] text-muted-foreground">Time budget (hours)</span>
              <Input type="number" value={timeBudget} min={0.5} max={6} step={0.5} onChange={(e) => setTimeBudget(+e.target.value)} className="h-8 text-xs" />
            </div>
            <div>
              <span className="text-[10px] text-muted-foreground">Max transfers</span>
              <Input type="number" value={maxTransfers} min={0} max={5} onChange={(e) => setMaxTransfers(+e.target.value)} className="h-8 text-xs" />
            </div>
            <div>
              <span className="text-[10px] text-muted-foreground">Departure window</span>
              <div className="flex items-center gap-2">
                <Input type="number" value={depStart} min={0} max={24} onChange={(e) => setDepStart(+e.target.value)} className="w-16 h-8 text-xs" />
                <span className="text-xs text-muted-foreground">to</span>
                <Input type="number" value={depEnd} min={0} max={24} onChange={(e) => setDepEnd(+e.target.value)} className="w-16 h-8 text-xs" />
              </div>
            </div>
          </div>

          <div className="border-t border-border pt-3 mt-3">
            <Label>Station Size</Label>
            {[{ label: "Small (<4 trains/h)", checked: showSmall, set: setShowSmall },
              { label: "Medium (4-10 trains/h)", checked: showMedium, set: setShowMedium },
              { label: "Big (>=10 trains/h)", checked: showBig, set: setShowBig }].map((f) => (
              <label key={f.label} className="flex items-center gap-2 text-xs text-foreground/70 cursor-pointer mt-1">
                <input type="checkbox" checked={f.checked} onChange={(e) => f.set(e.target.checked)} className="rounded border-border text-primary" />
                {f.label}
              </label>
            ))}
          </div>

          <div className="border-t border-border pt-3 mt-3">
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
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
            <MetricCard label="Total Stations" value={fmt(data.total)} />
            <MetricCard label="Small" value={fmt(data.n_small)} />
            <MetricCard label="Medium" value={fmt(data.n_medium)} />
            <MetricCard label="Big" value={fmt(data.n_big)} />
          </div>
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-4 mb-4">
            <DeckMap ref={mapRef} layers={layers} className="h-96" />
            <div className="bg-card rounded-xl border border-border p-4 h-96">
              <Tabs value={scatterTab} onValueChange={setScatterTab} className="h-full flex flex-col">
                <TabsList className="w-full mb-2">
                  <TabsTrigger value="ab" className="flex-1 text-xs">A x B</TabsTrigger>
                  <TabsTrigger value="bc" className="flex-1 text-xs">B x C</TabsTrigger>
                  <TabsTrigger value="ac" className="flex-1 text-xs">A x C</TabsTrigger>
                </TabsList>
                <div className="flex-1">
                  {scatterTab === "ab" && renderScatterChart("reachable", "direct_freq", "Reachable stations (A)", "Direct freq/h (B)")}
                  {scatterTab === "bc" && renderScatterChart("direct_freq", "reach_km", "Direct freq/h (B)", "Reach km (C)")}
                  {scatterTab === "ac" && renderScatterChart("reachable", "reach_km", "Reachable stations (A)", "Reach km (C)")}
                </div>
              </Tabs>
            </div>
          </div>

          <div className="bg-card rounded-xl border border-border p-4">
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
              <MetricCard label="Avg Reachable (A)" value={sizeAvg.avgA.toFixed(1)} />
              <MetricCard label="Avg Freq/h (B)" value={sizeAvg.avgB.toFixed(2)} />
              <MetricCard label="Avg Reach (C)" value={sizeAvg.avgC.toFixed(0)} suffix=" km" />
            </div>
          </div>
        </>
      )}

      {(error || data?.error) && <ErrorAlert message={data?.error ?? (error as Error).message} />}
    </Layout>
  );
}
