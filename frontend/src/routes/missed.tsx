import { createRoute } from "@tanstack/react-router";
import { useState, useMemo, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import type { Layer } from "@deck.gl/core";
import { Link2 } from "lucide-react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";
import { rootRoute } from "./__root";
import { Layout } from "@/components/Layout";
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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { fetchApi } from "@/lib/api";
import { fmt, daysAgo } from "@/lib/utils";
import { stationLayer, colorToRGBA } from "@/lib/layers";
import { tooltipBox } from "@/lib/tooltip";
import { cn } from "@/lib/utils";
import { useMapView, makeTercileClassifier, type MetricOption } from "@/hooks/useMapView";

export const missedRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/missed",
  component: MissedPage,
});

interface MissedStation { name: string; lat?: number; lon?: number; planned: number; missed: number; pct_missed: number; }
interface MissedData { total_connections: number; total_missed: number; pct_missed: number; stations: MissedStation[]; error?: string; }

const METRICS: MetricOption[] = [
  { key: "pct_missed", label: "% Missed", accessor: (d: MissedStation) => d.pct_missed, suffix: "%" },
  { key: "missed", label: "Missed count", accessor: (d: MissedStation) => d.missed },
];

function MissedPage() {
  const [startDate, setStartDate] = useState(daysAgo(7));
  const [endDate, setEndDate] = useState(daysAgo(1));
  const [minTransfer, setMinTransfer] = useState(2);
  const [maxTransfer, setMaxTransfer] = useState(15);
  const [hourStart, setHourStart] = useState(0);
  const [hourEnd, setHourEnd] = useState(24);
  const [minConnections, setMinConnections] = useState(10);
  const [queryParams, setQueryParams] = useState<Record<string, string | number | boolean> | null>(null);
  const mapRef = useRef<DeckMapRef>(null);

  const { data, error, isFetching } = useQuery({
    queryKey: ["missed", queryParams],
    queryFn: () => fetchApi<MissedData>("/missed", queryParams!),
    enabled: !!queryParams,
  });

  const { data: geoData } = useQuery({
    queryKey: ["provinces"],
    queryFn: () => fetchApi<any>("/provinces"),
  });

  const loadData = () => setQueryParams({
    start: startDate, end: endDate, min_transfer: minTransfer, max_transfer: maxTransfer,
    hour_start: hourStart, hour_end: hourEnd, min_connections: minConnections,
  });

  const geoStations = useMemo(
    () => (data?.stations ?? []).filter((s): s is MissedStation & { lat: number; lon: number } => !!s.lat && !!s.lon),
    [data],
  );

  const sizeClassifier = useMemo(
    () => makeTercileClassifier(geoStations, (d) => d.missed),
    [geoStations],
  );

  const mapView = useMapView({
    data: geoStations,
    geoData,
    getLon: (d) => d.lon,
    getLat: (d) => d.lat,
    getSize: sizeClassifier,
    metrics: METRICS,
    showGradient: true,
  });

  const top10Stations = useMemo(() => {
    if (!data?.stations) return [];
    return [...data.stations].sort((a, b) => b.missed - a.missed).slice(0, 10).map((s) => ({
      name: s.name.length > 15 ? s.name.slice(0, 15) + "..." : s.name,
      missed: s.missed,
      pct: s.pct_missed,
    }));
  }, [data]);

  const histogramData = useMemo(() => {
    if (!data?.stations || data.stations.length < 2) return [];
    const bins = 15;
    const maxRate = Math.max(...data.stations.map((s) => s.pct_missed), 1);
    const binWidth = Math.ceil(maxRate / bins) || 1;
    const counts: { range: string; count: number; from: number }[] = [];
    for (let i = 0; i < bins; i++) {
      const from = i * binWidth;
      const to = (i + 1) * binWidth;
      if (from > maxRate) break;
      counts.push({
        range: `${from}-${Math.min(to, Math.ceil(maxRate))}%`,
        count: data.stations.filter((s) => s.pct_missed >= from && s.pct_missed < to).length,
        from,
      });
    }
    return counts.filter((b) => b.count > 0);
  }, [data]);

  const stationLayers = useMemo<Layer[]>(() => {
    if (!data || data.error || !mapView.filtered.length) return [];
    const maxMissed = Math.max(...mapView.filtered.map((s) => s.missed));

    return [
      stationLayer("missed-stations", mapView.filtered, {
        positionFn: (d) => [d.lon, d.lat],
        radiusFn: (d) => 4 + (d.missed / Math.max(maxMissed, 1)) * 16,
        colorFn: (d) => colorToRGBA(d.missed / Math.max(maxMissed, 1)),
        radiusMinPixels: 3,
        radiusMaxPixels: 30,
      }),
    ] as Layer[];
  }, [data, mapView.filtered]);

  const layers = mapView.isOverlayView ? mapView.overlayLayers : stationLayers;

  return (
    <Layout
      sidebar={
        <>
          <div>
            <Label>Date Range</Label>
            <div className="grid grid-cols-2 gap-2 mt-1.5">
              <div><span className="text-[10px] text-muted-foreground/60">From</span><Input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} className="h-8 text-xs" /></div>
              <div><span className="text-[10px] text-muted-foreground/60">To</span><Input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} className="h-8 text-xs" /></div>
            </div>
          </div>
          <div className="border-t border-border/40 pt-3 mt-3 space-y-2">
            <Label>Connection Settings</Label>
            <div><span className="text-[10px] text-muted-foreground/60">Min transfer time (min)</span><Input type="number" value={minTransfer} min={1} max={10} onChange={(e) => setMinTransfer(+e.target.value)} className="h-8 text-xs" /></div>
            <div><span className="text-[10px] text-muted-foreground/60">Max transfer time (min)</span><Input type="number" value={maxTransfer} min={5} max={60} onChange={(e) => setMaxTransfer(+e.target.value)} className="h-8 text-xs" /></div>
            <div>
              <span className="text-[10px] text-muted-foreground/60">Hour window</span>
              <div className="flex items-center gap-2"><Input type="number" value={hourStart} min={0} max={24} onChange={(e) => setHourStart(+e.target.value)} className="w-16 h-8 text-xs" /><span className="text-xs text-muted-foreground/50">to</span><Input type="number" value={hourEnd} min={0} max={24} onChange={(e) => setHourEnd(+e.target.value)} className="w-16 h-8 text-xs" /></div>
            </div>
            <div><span className="text-[10px] text-muted-foreground/60">Min planned connections</span><Input type="number" value={minConnections} min={1} max={100} onChange={(e) => setMinConnections(+e.target.value)} className="h-8 text-xs" /></div>
          </div>
          <ApplyButton loading={isFetching} onClick={loadData} label="Analyse" />
        </>
      }
    >
      {isFetching && <LoadingState message="Analysing missed connections..." />}
      {!isFetching && !data && <EmptyState icon={Link2} message="Configure dates and click Analyse" />}

      {data && !data.error && !isFetching && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5 animate-slide-up">
            <MetricCard label="Total Connections" value={fmt(data.total_connections)} />
            <MetricCard label="Missed" value={fmt(data.total_missed)} danger />
            <MetricCard label="% Missed" value={data.pct_missed} suffix="%" danger={data.pct_missed > 10} />
            <MetricCard label="Worst Station" value={data.stations[0]?.name ?? "\u2014"} />
          </div>

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

          <div className="grid grid-cols-1 xl:grid-cols-3 gap-4 mt-3">
            <div className="xl:col-span-2 space-y-4">
              <div className="space-y-2">
                <DeckMap ref={mapRef} layers={layers} className="h-[calc(100vh-22rem)]"
                  getTooltip={(info) => {
                    const mv = mapViewTooltip(mapView.activeMetric, info);
                    if (mv) return mv;
                    const { object, layer } = info;
                    if (!object || !layer) return null;
                    if (layer.id === "missed-stations") {
                      return tooltipBox(`<b>${object.name}</b><br/>Missed: ${fmt(object.missed)} / ${fmt(object.planned)}<br/>${fmt(object.pct_missed, 1)}%`);
                    }
                    return null;
                  }}
                />
                {!mapView.isOverlayView && <ColorLegend min="Few missed" max="Many missed" />}
              </div>
              {top10Stations.length > 0 && (
                <div className="bg-card rounded-2xl border border-border/50 p-5 shadow-sm animate-slide-up">
                  <h3 className="text-sm font-semibold text-foreground mb-4">Top 10 Worst Stations</h3>
                  <ResponsiveContainer width="100%" height={200}>
                    <BarChart data={top10Stations} margin={{ top: 4, right: 8, bottom: 4, left: 8 }}>
                      <XAxis dataKey="name" tick={{ fontSize: 10 }} angle={-30} textAnchor="end" height={50} />
                      <YAxis tick={{ fontSize: 10 }} allowDecimals={false} />
                      <Tooltip
                        contentStyle={{ fontSize: 12, borderRadius: 12, border: '1px solid var(--color-border)' }}
                        formatter={(value: number) => [`${value} missed`, "Count"]}
                      />
                      <Bar dataKey="missed" fill="oklch(0.58 0.22 25)" radius={[6, 6, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              )}
              {histogramData.length > 0 && (
                <div className="bg-card rounded-2xl border border-border/50 p-5 shadow-sm animate-slide-up">
                  <h3 className="text-sm font-semibold text-foreground mb-4">Miss Rate Distribution</h3>
                  <ResponsiveContainer width="100%" height={180}>
                    <BarChart data={histogramData} margin={{ top: 4, right: 8, bottom: 4, left: 8 }}>
                      <XAxis dataKey="range" tick={{ fontSize: 9 }} angle={-30} textAnchor="end" height={45} />
                      <YAxis tick={{ fontSize: 10 }} allowDecimals={false} label={{ value: "Stations", angle: -90, position: "insideLeft", offset: 5, fontSize: 10 }} />
                      <Tooltip
                        contentStyle={{ fontSize: 12, borderRadius: 12, border: '1px solid var(--color-border)' }}
                        formatter={(value: number) => [`${value} stations`, "Count"]}
                      />
                      <Bar dataKey="count" fill="oklch(0.55 0.15 290)" radius={[4, 4, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              )}
            </div>
            <DataTable
              title="Stations by Missed Connections"
              keyFn={(s) => s.name}
              data={data.stations}
              maxRows={40}
              onRowClick={(s) => s.lat && s.lon && mapRef.current?.flyTo({ longitude: s.lon!, latitude: s.lat! })}
              columns={[
                { header: "Station", accessor: (s) => <span className="font-medium truncate max-w-[130px] block">{s.name}</span> },
                { header: "Planned", accessor: (s) => <span className="text-muted-foreground">{fmt(s.planned)}</span>, align: "right" },
                { header: "Missed", accessor: (s) => <span className="font-semibold text-destructive">{fmt(s.missed)}</span>, align: "right" },
                { header: "%", accessor: (s) => <span className={cn(s.pct_missed > 15 ? "text-destructive font-semibold" : "text-muted-foreground")}>{s.pct_missed}%</span>, align: "right" },
              ]}
            />
          </div>

          <div className="mt-4">
            <MethodologyPanel>
              <p>For each station and day, all arriving and departing SNCB trains are paired. A valid connection exists when two different trains have a gap between the planned arrival and planned departure within the transfer window.</p>
              <p>A connection is "missed" when the actual arrival time exceeds the actual departure time. The histogram shows how miss rates are distributed across stations — a right-skewed distribution indicates a few problem stations.</p>
            </MethodologyPanel>
          </div>
        </>
      )}

      {(error || data?.error) && <ErrorAlert message={data?.error ?? (error as Error).message} />}
    </Layout>
  );
}
