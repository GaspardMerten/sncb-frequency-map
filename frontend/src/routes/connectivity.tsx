import { createRoute } from "@tanstack/react-router";
import { useState, useMemo, useRef } from "react";
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
import { ColorLegend } from "@/components/ColorLegend";
import { MethodologyPanel } from "@/components/MethodologyPanel";
import { DataTable } from "@/components/DataTable";
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
  small: [76, 175, 80, 180],
  medium: [255, 152, 0, 180],
  big: [211, 47, 47, 180],
};

const SIZE_CSS: Record<string, string> = {
  small: "#4caf50",
  medium: "#ff9800",
  big: "#d32f2f",
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

  const regionColors: Record<string, string> = { Brussels: "#e31a1c", Flanders: "#ff7f00", Wallonia: "#2557e6" };

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

  const sizeComparisonData = useMemo(() => {
    if (!data) return [];
    const sizes = ["small", "medium", "big"] as const;
    const labels: Record<string, string> = { small: "Small", medium: "Medium", big: "Big" };
    return sizes.map((size) => {
      const stations = data.stations.filter((s) => s.size === size);
      const count = stations.length;
      if (count === 0) return { label: labels[size], count: 0, avgA: 0, avgB: 0, avgC: 0 };
      const avgA = stations.reduce((sum, s) => sum + s.reachable, 0) / count;
      const avgB = stations.reduce((sum, s) => sum + s.direct_freq, 0) / count;
      const avgC = stations.reduce((sum, s) => sum + s.reach_km, 0) / count;
      return { label: labels[size], count, avgA, avgB, avgC };
    });
  }, [data]);

  // Get max values for ZAxis domain
  const zDomains = useMemo(() => {
    if (!sizeFilteredStations.length) return { maxA: 1, maxB: 1, maxC: 1 };
    return {
      maxA: Math.max(...sizeFilteredStations.map((s) => s.reachable), 1),
      maxB: Math.max(...sizeFilteredStations.map((s) => s.direct_freq), 1),
      maxC: Math.max(...sizeFilteredStations.map((s) => s.reach_km), 1),
    };
  }, [sizeFilteredStations]);

  const renderScatterChart = (xKey: string, yKey: string, zKey: string, xLabel: string, yLabel: string, zLabel: string) => {
    const keyMap: Record<string, (s: Station) => number> = {
      reachable: (s) => s.reachable,
      direct_freq: (s) => s.direct_freq,
      reach_km: (s) => s.reach_km,
    };
    const getX = keyMap[xKey];
    const getY = keyMap[yKey];
    const getZ = keyMap[zKey];
    const maxZ = zKey === "reachable" ? zDomains.maxA : zKey === "direct_freq" ? zDomains.maxB : zDomains.maxC;

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
                {zLabel} (size): {typeof d.z === "number" && d.z % 1 !== 0 ? d.z.toFixed(1) : d.z}
              </div>
            );
          }} />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          {scatterData.map(({ region, color, data: regionData }) => (
            <Scatter
              key={region}
              name={region}
              data={regionData.map((s) => ({ x: getX(s), y: getY(s), z: getZ(s), name: s.name }))}
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
            <Label>Station Size</Label>
            {[
              { label: "Small (<4 trains/h)", checked: showSmall, set: setShowSmall, color: SIZE_CSS.small },
              { label: "Medium (4-10 trains/h)", checked: showMedium, set: setShowMedium, color: SIZE_CSS.medium },
              { label: "Big (>=10 trains/h)", checked: showBig, set: setShowBig, color: SIZE_CSS.big },
            ].map((f) => (
              <label key={f.label} className="flex items-center gap-2 text-xs text-foreground/60 cursor-pointer mt-1.5">
                <input type="checkbox" checked={f.checked} onChange={(e) => f.set(e.target.checked)} className="rounded border-border text-primary" />
                <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: f.color }} />
                {f.label}
              </label>
            ))}
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
            <MetricCard label="Small" value={fmt(data.n_small)} />
            <MetricCard label="Medium" value={fmt(data.n_medium)} />
            <MetricCard label="Big" value={fmt(data.n_big)} />
          </div>
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-4 mb-4">
            <div className="space-y-2">
              <DeckMap ref={mapRef} layers={layers} className="h-96" />
              <div className="flex gap-4 text-[10px] text-muted-foreground">
                {Object.entries(SIZE_CSS).map(([size, color]) => (
                  <span key={size} className="flex items-center gap-1">
                    <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: color }} />
                    {size}
                  </span>
                ))}
                <span className="ml-auto">Size = direct freq/h</span>
              </div>
            </div>
            <div className="bg-card rounded-2xl border border-border/50 p-5 h-96 shadow-sm">
              <Tabs value={scatterTab} onValueChange={setScatterTab} className="h-full flex flex-col">
                <TabsList className="w-full mb-3">
                  <TabsTrigger value="ab" className="flex-1 text-xs">A x B (size=C)</TabsTrigger>
                  <TabsTrigger value="bc" className="flex-1 text-xs">B x C (size=A)</TabsTrigger>
                  <TabsTrigger value="ac" className="flex-1 text-xs">A x C (size=B)</TabsTrigger>
                </TabsList>
                <div className="flex-1">
                  {scatterTab === "ab" && renderScatterChart("reachable", "direct_freq", "reach_km", "Reachable (A)", "Freq/h (B)", "Reach km (C)")}
                  {scatterTab === "bc" && renderScatterChart("direct_freq", "reach_km", "reachable", "Freq/h (B)", "Reach km (C)", "Reachable (A)")}
                  {scatterTab === "ac" && renderScatterChart("reachable", "reach_km", "direct_freq", "Reachable (A)", "Reach km (C)", "Freq/h (B)")}
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
              <MetricCard label="Avg Reachable (A)" value={sizeAvg.avgA.toFixed(1)} />
              <MetricCard label="Avg Freq/h (B)" value={sizeAvg.avgB.toFixed(2)} />
              <MetricCard label="Avg Reach (C)" value={sizeAvg.avgC.toFixed(0)} suffix=" km" />
            </div>
          </div>

          {sizeComparisonData.length > 0 && (
            <div className="mb-4 animate-slide-up">
              <DataTable
                title="Size Comparison Summary"
                keyFn={(row) => row.label}
                data={sizeComparisonData}
                columns={[
                  { header: "Size", accessor: (row) => <span className="font-medium">{row.label}</span> },
                  { header: "Count", accessor: (row) => fmt(row.count), align: "right" },
                  { header: "Avg Reachable", accessor: (row) => row.avgA.toFixed(1), align: "right" },
                  { header: "Avg Freq/h", accessor: (row) => row.avgB.toFixed(2), align: "right" },
                  { header: "Avg Reach km", accessor: (row) => <span className="font-semibold text-primary">{row.avgC.toFixed(0)}</span>, align: "right" },
                ]}
              />
            </div>
          )}

          <MethodologyPanel>
            <p><b>Metric A (Reachable Destinations):</b> BFS-based reachability count within the time budget, considering transfers.</p>
            <p><b>Metric B (Direct Frequency):</b> Average direct trains per hour between 6h-22h, normalized across GTFS feeds.</p>
            <p><b>Metric C (Cardinal Reach):</b> Maximum geographic reach distance in each cardinal direction (N/E/S/W), summed to represent geographic extent.</p>
            <p>Station size classification: Small (&lt;4 trains/h), Medium (4-10), Big (&gt;10). Bubble size in scatter plots encodes the third metric not shown on axes.</p>
          </MethodologyPanel>
        </>
      )}

      {(error || data?.error) && <ErrorAlert message={data?.error ?? (error as Error).message} />}
    </Layout>
  );
}
