import { createRoute } from "@tanstack/react-router";
import { useState, useMemo, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { ListOrdered } from "lucide-react";
import type { Layer } from "@deck.gl/core";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell,
} from "recharts";
import { rootRoute } from "./__root";
import { Layout } from "@/components/Layout";
import { FilterPanel, type Filters } from "@/components/FilterPanel";
import { MetricCard } from "@/components/MetricCard";
import { LoadingState } from "@/components/LoadingState";
import { EmptyState } from "@/components/EmptyState";
import { ErrorAlert } from "@/components/ErrorAlert";
import { ApplyButton } from "@/components/ApplyButton";
import { DataTable } from "@/components/DataTable";
import { MethodologyPanel } from "@/components/MethodologyPanel";
import { MapViewBar, mapViewTooltip } from "@/components/MapViewBar";
import { DeckMap, type DeckMapRef } from "@/components/DeckMap";
import { ColorLegend } from "@/components/ColorLegend";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { fetchApi } from "@/lib/api";
import { filterParams, fmt, daysAgo, today } from "@/lib/utils";
import { stationLayer, colorToRGBA } from "@/lib/layers";
import { useMapView, type MetricOption } from "@/hooks/useMapView";

export const rankingsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/rankings",
  component: RankingsPage,
});

interface RankingStation {
  id: string;
  name: string;
  lat: number;
  lon: number;
  province: string;
  region: string;
  reachable: number;
  trains_per_day: number;
  last_train_min: number | null;
  last_train_str: string | null;
}
interface CommercialSpeed {
  name: string;
  region: string;
  province: string;
  trains_per_day: number;
  fast_count: number;
  medium_count: number;
  slow_count: number;
  pairs: { dest: string; avg_time_min: number | null; distance_km: number; speed_kmh: number | null }[];
}
interface RankingsData {
  stations: RankingStation[];
  commercial_speeds: CommercialSpeed[];
  time_budget: number;
  top_n: number;
  speed_window: [number, number];
  error?: string;
}

const REGION_COLORS: Record<string, string> = {
  Flanders: "#facc15",
  Brussels: "#2171b5",
  Wallonia: "#dc2626",
  Unknown: "#cbd5e1",
};
const regionColor = (r: string) => REGION_COLORS[r] ?? REGION_COLORS.Unknown;

type ReachTab = "all" | "xl" | "lm" | "s";
type TrainTab = "all" | "xl" | "m" | "s";
type SortKey = "name" | "reachable" | "trains_per_day" | "last_train_min";

function filterReach(list: RankingStation[], tab: ReachTab): RankingStation[] {
  if (tab === "xl") return list.filter((s) => s.reachable > 200);
  if (tab === "lm") return list.filter((s) => s.reachable >= 50 && s.reachable <= 200);
  if (tab === "s") return list.filter((s) => s.reachable < 50);
  return list;
}
function filterTrains(list: RankingStation[], tab: TrainTab): RankingStation[] {
  if (tab === "xl") return list.filter((s) => s.trains_per_day > 80);
  if (tab === "m") return list.filter((s) => s.trains_per_day >= 30 && s.trains_per_day <= 80);
  if (tab === "s") return list.filter((s) => s.trains_per_day < 30);
  return list;
}

function minutesToClock(m: number): string {
  const h = Math.floor(m);
  const mm = Math.round((m - h) * 60);
  const dayWrap = h >= 24 ? "+1" : "";
  const hh = ((h % 24) + 24) % 24;
  return `${String(hh).padStart(2, "0")}:${String(mm).padStart(2, "0")}${dayWrap}`;
}

const METRICS: MetricOption[] = [
  { key: "reachable", label: "Reachable stations", accessor: (d: any) => d.reachable },
  { key: "trains_per_day", label: "Trains / day", accessor: (d: any) => d.trains_per_day, suffix: "" },
];

function RankingsPage() {
  const [filters, setFilters] = useState<Filters>({
    startDate: daysAgo(7),
    endDate: today(),
    weekdays: [0, 1, 2, 3, 4],
    excludePub: false,
    excludeSch: false,
    useHour: false,
    hourStart: 7,
    hourEnd: 19,
  });
  const [timeBudget, setTimeBudget] = useState(2);
  const [depStart, setDepStart] = useState(7);
  const [depEnd, setDepEnd] = useState(9);
  const [maxTransfers, setMaxTransfers] = useState(3);
  const [minTransferTime, setMinTransferTime] = useState(5);
  const [speedDepStart, setSpeedDepStart] = useState(8);
  const [speedDepEnd, setSpeedDepEnd] = useState(20);
  const [topN, setTopN] = useState(20);

  const [reachTab, setReachTab] = useState<ReachTab>("xl");
  const [trainTab, setTrainTab] = useState<TrainTab>("xl");
  const [lastTab, setLastTab] = useState<TrainTab>("xl");
  const [search, setSearch] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("reachable");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  const [queryParams, setQueryParams] = useState<Record<string, string | number | boolean> | null>(null);
  const mapRef = useRef<DeckMapRef>(null);

  const { data, error, isFetching } = useQuery({
    queryKey: ["rankings", queryParams],
    queryFn: () => fetchApi<RankingsData>("/rankings", queryParams!),
    enabled: !!queryParams,
  });

  const { data: geoData } = useQuery({
    queryKey: ["provinces"],
    queryFn: () => fetchApi<any>("/provinces"),
  });

  const mapView = useMapView<RankingStation>({
    data: data?.stations ?? [],
    geoData,
    getLon: (d) => d.lon,
    getLat: (d) => d.lat,
    metrics: METRICS,
    showGradient: true,
    defaultViewMode: "provinces",
  });

  const stationLayers = useMemo<Layer[]>(() => {
    const stations = mapView.filtered;
    if (!stations.length) return [];
    const accessor = mapView.activeMetric.accessor;
    const vals = stations.map(accessor);
    const maxVal = Math.max(...vals, 1);
    const minVal = Math.min(...vals, 0);
    const spread = Math.max(maxVal - minVal, 1);
    return [
      stationLayer("rankings-stations", stations, {
        positionFn: (d) => [d.lon, d.lat],
        radiusFn: (d) => 3 + ((accessor(d) - minVal) / spread) * 18,
        colorFn: (d) => {
          const [r, g, b] = colorToRGBA((accessor(d) - minVal) / spread);
          return [r, g, b, 230];
        },
        radiusScale: 1,
        radiusMinPixels: 3,
        radiusMaxPixels: 40,
        pickable: true,
      }) as Layer,
    ];
  }, [mapView.filtered, mapView.activeMetric]);

  const mapLayers = mapView.isOverlayView ? mapView.overlayLayers : stationLayers;

  const loadData = () =>
    setQueryParams({
      ...filterParams(filters),
      time_budget: timeBudget,
      dep_start: depStart,
      dep_end: depEnd,
      max_transfers: maxTransfers,
      min_transfer_time: minTransferTime,
      speed_dep_start: speedDepStart,
      speed_dep_end: speedDepEnd,
      top_n: topN,
    });

  const topReach = useMemo(() => {
    if (!data?.stations?.length) return "—";
    const s = [...data.stations].sort((a, b) => b.reachable - a.reachable)[0];
    return `${s.reachable} (${s.name})`;
  }, [data]);

  const topTrains = useMemo(() => {
    if (!data?.stations?.length) return "—";
    const s = [...data.stations].sort((a, b) => b.trains_per_day - a.trains_per_day)[0];
    return `${fmt(s.trains_per_day, 0)} (${s.name})`;
  }, [data]);

  const latestTrain = useMemo(() => {
    if (!data?.stations?.length) return "—";
    const withVal = data.stations.filter((s) => s.last_train_min != null);
    if (!withVal.length) return "—";
    return withVal.sort((a, b) => (b.last_train_min ?? 0) - (a.last_train_min ?? 0))[0].last_train_str ?? "—";
  }, [data]);

  const reachChartData = useMemo(() => {
    if (!data) return [];
    return filterReach(data.stations, reachTab)
      .sort((a, b) => b.reachable - a.reachable)
      .map((s) => ({ name: s.name, value: s.reachable, region: s.region }));
  }, [data, reachTab]);

  const trainsChartData = useMemo(() => {
    if (!data) return [];
    return filterTrains(data.stations, trainTab)
      .sort((a, b) => b.trains_per_day - a.trains_per_day)
      .map((s) => ({ name: s.name, value: s.trains_per_day, region: s.region }));
  }, [data, trainTab]);

  const lastChartData = useMemo(() => {
    if (!data) return [];
    return filterTrains(
      data.stations.filter((s) => s.last_train_min != null),
      lastTab,
    )
      .sort((a, b) => (b.last_train_min ?? 0) - (a.last_train_min ?? 0))
      .map((s) => ({
        name: s.name,
        value: (s.last_train_min ?? 0) / 60,
        region: s.region,
        last_str: s.last_train_str,
      }));
  }, [data, lastTab]);

  const speedChartData = useMemo(() => {
    if (!data) return [];
    return data.commercial_speeds.map((s) => ({
      name: s.name,
      fast: s.fast_count,
      medium: s.medium_count,
      slow: s.slow_count,
      region: s.region,
    }));
  }, [data]);

  const filteredStations = useMemo(() => {
    if (!data) return [];
    const q = search.toLowerCase().trim();
    let list = q
      ? data.stations.filter((s) => s.name.toLowerCase().includes(q))
      : [...data.stations];
    const dir = sortDir === "asc" ? 1 : -1;
    list.sort((a, b) => {
      const av = (a[sortKey] ?? -Infinity) as number | string;
      const bv = (b[sortKey] ?? -Infinity) as number | string;
      if (typeof av === "string" && typeof bv === "string") return av.localeCompare(bv) * dir;
      return (((av as number) - (bv as number)) as number) * dir;
    });
    return list;
  }, [data, search, sortKey, sortDir]);

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) setSortDir(sortDir === "asc" ? "desc" : "asc");
    else {
      setSortKey(key);
      setSortDir("desc");
    }
  };

  const chartHeight = (n: number) => Math.max(260, Math.min(3200, n * 16 + 80));

  return (
    <Layout
      sidebar={
        <>
          <div className="space-y-2">
            <Label>Reach Settings</Label>
            <div>
              <span className="text-[10px] text-muted-foreground/60">Time budget (hours)</span>
              <Input type="number" value={timeBudget} min={0.5} max={6} step={0.5}
                onChange={(e) => setTimeBudget(+e.target.value)} className="h-8 text-xs" />
            </div>
            <div>
              <span className="text-[10px] text-muted-foreground/60">Departure window (reach)</span>
              <div className="flex items-center gap-2">
                <Input type="number" value={depStart} min={0} max={24}
                  onChange={(e) => setDepStart(+e.target.value)} className="w-16 h-8 text-xs" />
                <span className="text-xs text-muted-foreground/50">to</span>
                <Input type="number" value={depEnd} min={0} max={24}
                  onChange={(e) => setDepEnd(+e.target.value)} className="w-16 h-8 text-xs" />
              </div>
            </div>
            <div>
              <span className="text-[10px] text-muted-foreground/60">Max transfers</span>
              <Input type="number" value={maxTransfers} min={0} max={5}
                onChange={(e) => setMaxTransfers(+e.target.value)} className="h-8 text-xs" />
            </div>
            <div>
              <span className="text-[10px] text-muted-foreground/60">Min transfer time (min)</span>
              <Input type="number" value={minTransferTime} min={0} max={15}
                onChange={(e) => setMinTransferTime(+e.target.value)} className="h-8 text-xs" />
            </div>
          </div>

          <div className="border-t border-border/40 pt-3 mt-3 space-y-2">
            <Label>Commercial Speed</Label>
            <div>
              <span className="text-[10px] text-muted-foreground/60">Speed window</span>
              <div className="flex items-center gap-2">
                <Input type="number" value={speedDepStart} min={0} max={24}
                  onChange={(e) => setSpeedDepStart(+e.target.value)} className="w-16 h-8 text-xs" />
                <span className="text-xs text-muted-foreground/50">to</span>
                <Input type="number" value={speedDepEnd} min={0} max={24}
                  onChange={(e) => setSpeedDepEnd(+e.target.value)} className="w-16 h-8 text-xs" />
              </div>
            </div>
            <div>
              <span className="text-[10px] text-muted-foreground/60">Top N stations</span>
              <Input type="number" value={topN} min={5} max={40}
                onChange={(e) => setTopN(+e.target.value)} className="h-8 text-xs" />
            </div>
          </div>

          <div className="border-t border-border/40 pt-3 mt-3">
            <FilterPanel filters={filters} onChange={setFilters} />
          </div>

          <ApplyButton loading={isFetching} onClick={loadData}
            label="Compute Rankings" loadingLabel="Computing..." />
        </>
      }
    >
      {isFetching && <LoadingState message="Computing station rankings (this may take a minute)..." />}
      {!isFetching && !data && <EmptyState icon={ListOrdered} message="Configure settings and click Compute" />}

      {data && !data.error && !isFetching && (
        <>
          <div className="flex flex-wrap items-center gap-4 mb-4 text-xs text-muted-foreground">
            <span className="font-semibold text-primary">Regions:</span>
            <span className="flex items-center gap-1.5">
              <span className="w-3 h-3 rounded-sm" style={{ background: "#facc15" }} /> Flanders
            </span>
            <span className="flex items-center gap-1.5">
              <span className="w-3 h-3 rounded-sm" style={{ background: "#2171b5" }} /> Brussels
            </span>
            <span className="flex items-center gap-1.5">
              <span className="w-3 h-3 rounded-sm" style={{ background: "#dc2626" }} /> Wallonia
            </span>
            <span className="flex items-center gap-1.5 text-muted-foreground/70">
              <span className="w-3 h-3 rounded-sm bg-muted-foreground/30" /> Unknown
            </span>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5 animate-slide-up">
            <MetricCard label="Stations" value={fmt(data.stations.length)} />
            <MetricCard label="Top Reach" value={topReach} />
            <MetricCard label="Top Trains/day" value={topTrains} />
            <MetricCard label="Latest Train" value={latestTrain} />
          </div>

          <section className="bg-card rounded-2xl border border-border/60 mb-4 shadow-sm">
            <div className="px-4 py-3 border-b border-border/40">
              <h3 className="text-sm font-semibold text-foreground">Aggregate map view</h3>
              <p className="text-[11px] text-muted-foreground mt-0.5">
                Per-station, per-province or per-region aggregation of reach and trains/day.
              </p>
            </div>
            <div className="p-4 space-y-2">
              <MapViewBar
                viewMode={mapView.viewMode}
                onViewModeChange={mapView.setViewMode}
                choroplethMetric={mapView.choroplethMetric}
                onChoroplethMetricChange={mapView.setChoroplethMetric}
                metrics={mapView.metrics}
                showGradient={mapView.showGradient}
                activeMetric={mapView.activeMetric}
                isOverlayView={mapView.isOverlayView}
              />
              <DeckMap
                ref={mapRef}
                layers={mapLayers}
                className="h-[420px]"
                getTooltip={(info) => {
                  if (!mapView.isOverlayView) {
                    const { object, layer } = info;
                    if (!object || !layer) return null;
                    if (layer.id !== "rankings-stations") return null;
                    return {
                      html: `<div style="font-size:12px"><b>${object.name}</b><br/>${mapView.activeMetric.label}: ${fmt(mapView.activeMetric.accessor(object), 1)}<br/>${object.region}</div>`,
                      style: { backgroundColor: "rgba(255,255,255,0.95)", color: "#111", padding: "6px 8px", borderRadius: "8px", border: "1px solid #e5e7eb", boxShadow: "0 2px 8px rgba(0,0,0,0.12)" },
                    };
                  }
                  return mapViewTooltip(mapView.activeMetric, info);
                }}
              />
              {!mapView.isOverlayView && (
                <ColorLegend min={`Low ${mapView.activeMetric.label}`} max={`High ${mapView.activeMetric.label}`} />
              )}
            </div>
          </section>

          <section className="bg-card rounded-2xl border border-border/60 mb-4 shadow-sm">
            <div className="px-4 py-3 border-b border-border/40 flex items-center justify-between flex-wrap gap-2">
              <div>
                <h3 className="text-sm font-semibold text-foreground">1. Reach — stations reachable in {timeBudget}h</h3>
                <p className="text-[11px] text-muted-foreground mt-0.5">
                  Stations ranked by number of unique destinations reachable within the time budget.
                </p>
              </div>
              <Tabs value={reachTab} onValueChange={(v) => setReachTab(v as ReachTab)}>
                <TabsList>
                  <TabsTrigger value="all">All</TabsTrigger>
                  <TabsTrigger value="xl">XL (&gt; 200)</TabsTrigger>
                  <TabsTrigger value="lm">L + M (50–200)</TabsTrigger>
                  <TabsTrigger value="s">S (&lt; 50)</TabsTrigger>
                </TabsList>
              </Tabs>
            </div>
            <div className="p-4" style={{ height: chartHeight(reachChartData.length) }}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={reachChartData} layout="vertical" margin={{ top: 4, right: 16, left: 8, bottom: 4 }}>
                  <XAxis type="number" tick={{ fontSize: 10 }} />
                  <YAxis type="category" dataKey="name" width={130} tick={{ fontSize: 9 }} interval={0} />
                  <Tooltip
                    contentStyle={{ fontSize: 12, borderRadius: 12, border: "1px solid var(--color-border)" }}
                    formatter={(value: number, _n, ctx) => [`${value} · ${(ctx.payload as { region: string }).region}`, "Reachable"]}
                  />
                  <Bar dataKey="value" radius={[0, 4, 4, 0]}>
                    {reachChartData.map((d, i) => <Cell key={i} fill={regionColor(d.region)} />)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </section>

          <section className="bg-card rounded-2xl border border-border/60 mb-4 shadow-sm">
            <div className="px-4 py-3 border-b border-border/40 flex items-center justify-between flex-wrap gap-2">
              <div>
                <h3 className="text-sm font-semibold text-foreground">2. Trains per day</h3>
                <p className="text-[11px] text-muted-foreground mt-0.5">
                  Average number of train-trips stopping at the station per day.
                </p>
              </div>
              <Tabs value={trainTab} onValueChange={(v) => setTrainTab(v as TrainTab)}>
                <TabsList>
                  <TabsTrigger value="all">All</TabsTrigger>
                  <TabsTrigger value="xl">&gt; 80</TabsTrigger>
                  <TabsTrigger value="m">30–80</TabsTrigger>
                  <TabsTrigger value="s">&lt; 30</TabsTrigger>
                </TabsList>
              </Tabs>
            </div>
            <div className="p-4" style={{ height: chartHeight(trainsChartData.length) }}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={trainsChartData} layout="vertical" margin={{ top: 4, right: 16, left: 8, bottom: 4 }}>
                  <XAxis type="number" tick={{ fontSize: 10 }} />
                  <YAxis type="category" dataKey="name" width={130} tick={{ fontSize: 9 }} interval={0} />
                  <Tooltip
                    contentStyle={{ fontSize: 12, borderRadius: 12, border: "1px solid var(--color-border)" }}
                    formatter={(value: number, _n, ctx) => [`${fmt(value, 1)} · ${(ctx.payload as { region: string }).region}`, "Trains/day"]}
                  />
                  <Bar dataKey="value" radius={[0, 4, 4, 0]}>
                    {trainsChartData.map((d, i) => <Cell key={i} fill={regionColor(d.region)} />)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </section>

          <section className="bg-card rounded-2xl border border-border/60 mb-4 shadow-sm">
            <div className="px-4 py-3 border-b border-border/40 flex items-center justify-between flex-wrap gap-2">
              <div>
                <h3 className="text-sm font-semibold text-foreground">3. Latest evening departure</h3>
                <p className="text-[11px] text-muted-foreground mt-0.5">
                  Latest departure time observed at each station (any direction).
                </p>
              </div>
              <Tabs value={lastTab} onValueChange={(v) => setLastTab(v as TrainTab)}>
                <TabsList>
                  <TabsTrigger value="all">All</TabsTrigger>
                  <TabsTrigger value="xl">&gt; 80</TabsTrigger>
                  <TabsTrigger value="m">30–80</TabsTrigger>
                  <TabsTrigger value="s">&lt; 30</TabsTrigger>
                </TabsList>
              </Tabs>
            </div>
            <div className="p-4" style={{ height: chartHeight(lastChartData.length) }}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={lastChartData} layout="vertical" margin={{ top: 4, right: 16, left: 8, bottom: 4 }}>
                  <XAxis type="number" domain={[16, "auto"]} tickFormatter={minutesToClock} tick={{ fontSize: 10 }} />
                  <YAxis type="category" dataKey="name" width={130} tick={{ fontSize: 9 }} interval={0} />
                  <Tooltip
                    contentStyle={{ fontSize: 12, borderRadius: 12, border: "1px solid var(--color-border)" }}
                    formatter={(_v: number, _n, ctx) => {
                      const p = ctx.payload as { last_str: string; region: string };
                      return [`${p.last_str} · ${p.region}`, "Last"];
                    }}
                  />
                  <Bar dataKey="value" radius={[0, 4, 4, 0]}>
                    {lastChartData.map((d, i) => <Cell key={i} fill={regionColor(d.region)} />)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </section>

          <section className="bg-card rounded-2xl border border-border/60 mb-4 shadow-sm">
            <div className="px-4 py-3 border-b border-border/40">
              <h3 className="text-sm font-semibold text-foreground">
                4. Commercial speed — top {data.top_n} busiest stations
              </h3>
              <p className="text-[11px] text-muted-foreground mt-0.5">
                For each origin, the other top stations are grouped by average commercial speed
                (distance ÷ avg travel time) between {data.speed_window[0]}h and {data.speed_window[1]}h.
              </p>
              <div className="flex flex-wrap items-center gap-4 mt-2 text-[11px] text-muted-foreground">
                <span className="flex items-center gap-1.5">
                  <span className="w-3 h-3 rounded-sm" style={{ background: "#16a34a" }} /> &gt; 80 km/h (fast)
                </span>
                <span className="flex items-center gap-1.5">
                  <span className="w-3 h-3 rounded-sm" style={{ background: "#f59e0b" }} /> 60–80 km/h
                </span>
                <span className="flex items-center gap-1.5">
                  <span className="w-3 h-3 rounded-sm" style={{ background: "#dc2626" }} /> &lt; 60 km/h (slow)
                </span>
              </div>
            </div>
            <div className="p-4" style={{ height: Math.max(280, speedChartData.length * 22 + 80) }}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={speedChartData} layout="vertical" margin={{ top: 4, right: 16, left: 8, bottom: 4 }}>
                  <XAxis type="number" allowDecimals={false} tick={{ fontSize: 10 }} />
                  <YAxis type="category" dataKey="name" width={130} tick={{ fontSize: 10 }} interval={0} />
                  <Tooltip contentStyle={{ fontSize: 12, borderRadius: 12, border: "1px solid var(--color-border)" }} />
                  <Bar dataKey="fast" stackId="speed" fill="#16a34a" name="> 80 km/h" />
                  <Bar dataKey="medium" stackId="speed" fill="#f59e0b" name="60–80 km/h" />
                  <Bar dataKey="slow" stackId="speed" fill="#dc2626" name="< 60 km/h" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </section>

          <div className="mb-3 flex items-center justify-between gap-2">
            <div className="text-sm font-semibold text-foreground">All stations</div>
            <Input
              type="text" value={search} onChange={(e) => setSearch(e.target.value)}
              placeholder="Search station..." className="h-8 w-48 text-xs"
            />
          </div>

          <DataTable
            title="Rankings"
            keyFn={(s) => s.id}
            data={filteredStations}
            maxRows={500}
            columns={[
              {
                header: "Station",
                accessor: (s) => (
                  <button type="button" onClick={() => toggleSort("name")}
                    className="font-medium truncate max-w-[180px] block text-left">
                    {s.name}
                  </button>
                ),
              },
              {
                header: "Region",
                accessor: (s) => (
                  <span className="inline-flex items-center gap-1.5 text-muted-foreground">
                    <span className="inline-block w-2 h-2 rounded-full"
                      style={{ background: regionColor(s.region) }} />
                    {s.region}
                  </span>
                ),
              },
              {
                header: "Reach",
                align: "right",
                accessor: (s) => <span className="font-semibold text-primary">{s.reachable}</span>,
              },
              {
                header: "Trains/day",
                align: "right",
                accessor: (s) => fmt(s.trains_per_day, 1),
              },
              {
                header: "Last train",
                align: "right",
                accessor: (s) => s.last_train_str ?? "—",
              },
            ]}
          />

          <div className="mt-2 flex items-center gap-3 text-[10px] text-muted-foreground">
            <span>Sort:</span>
            {(["reachable", "trains_per_day", "last_train_min", "name"] as SortKey[]).map((k) => (
              <button
                key={k}
                type="button"
                onClick={() => toggleSort(k)}
                className={sortKey === k ? "font-semibold text-primary" : "hover:text-foreground"}
              >
                {k === "last_train_min" ? "last train" : k.replace("_", " ")}
                {sortKey === k ? (sortDir === "asc" ? " ↑" : " ↓") : ""}
              </button>
            ))}
          </div>

          <div className="mt-4">
            <MethodologyPanel>
              <p>
                Rankings combine four per-station metrics over the selected date range: reach
                (# unique destinations reachable by BFS within the time budget), trains/day
                (max of incoming/outgoing segment frequencies, daily-averaged), latest departure
                (maximum observed dep_min across outgoing edges, full day), and commercial speed
                (haversine distance ÷ average BFS travel time, averaged across hourly starts in
                the speed window).
              </p>
              <p>
                Commercial speed is an approximation: waiting time at the origin is counted in
                travel time, so pairs with poor connectivity show an upward bias.
              </p>
            </MethodologyPanel>
          </div>
        </>
      )}

      {(error || data?.error) && <ErrorAlert message={data?.error ?? (error as Error).message} />}
    </Layout>
  );
}
