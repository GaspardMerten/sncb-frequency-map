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
import { DeckMap, type DeckMapRef } from "@/components/DeckMap";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { fetchApi } from "@/lib/api";
import { fmt, daysAgo } from "@/lib/utils";
import { stationLayer, colorToRGBA } from "@/lib/layers";
import { cn } from "@/lib/utils";

export const missedRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/missed",
  component: MissedPage,
});

interface MissedStation { name: string; lat?: number; lon?: number; planned: number; missed: number; pct_missed: number; }
interface MissedData { total_connections: number; total_missed: number; pct_missed: number; stations: MissedStation[]; error?: string; }

function MissedPage() {
  const [startDate, setStartDate] = useState(daysAgo(7));
  const [endDate, setEndDate] = useState(daysAgo(1));
  const [minTransfer, setMinTransfer] = useState(2);
  const [maxTransfer, setMaxTransfer] = useState(30);
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

  const loadData = () => setQueryParams({
    start: startDate, end: endDate, min_transfer: minTransfer, max_transfer: maxTransfer,
    hour_start: hourStart, hour_end: hourEnd, min_connections: minConnections,
  });

  const top10Stations = useMemo(() => {
    if (!data?.stations) return [];
    return [...data.stations].sort((a, b) => b.missed - a.missed).slice(0, 10).map((s) => ({
      name: s.name.length > 15 ? s.name.slice(0, 15) + "..." : s.name,
      missed: s.missed,
      pct: s.pct_missed,
    }));
  }, [data]);

  const layers = useMemo<Layer[]>(() => {
    if (!data || data.error) return [];
    const stations = data.stations.filter((s) => s.lat && s.lon);
    if (!stations.length) return [];
    const maxMissed = Math.max(...stations.map((s) => s.missed));

    return [
      stationLayer("missed-stations", stations, {
        positionFn: (d) => [d.lon!, d.lat!],
        radiusFn: (d) => 4 + (d.missed / Math.max(maxMissed, 1)) * 16,
        colorFn: (d) => colorToRGBA(d.missed / Math.max(maxMissed, 1)),
        radiusMinPixels: 3,
        radiusMaxPixels: 30,
      }),
    ] as Layer[];
  }, [data]);

  return (
    <Layout
      sidebar={
        <>
          <div>
            <Label>Date Range</Label>
            <div className="grid grid-cols-2 gap-2 mt-1.5">
              <div><span className="text-[10px] text-muted-foreground">From</span><Input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} className="h-8 text-xs" /></div>
              <div><span className="text-[10px] text-muted-foreground">To</span><Input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} className="h-8 text-xs" /></div>
            </div>
          </div>
          <div className="border-t border-border pt-3 mt-3 space-y-2">
            <Label>Connection Settings</Label>
            <div><span className="text-[10px] text-muted-foreground">Min transfer time (min)</span><Input type="number" value={minTransfer} min={1} max={10} onChange={(e) => setMinTransfer(+e.target.value)} className="h-8 text-xs" /></div>
            <div><span className="text-[10px] text-muted-foreground">Max transfer time (min)</span><Input type="number" value={maxTransfer} min={5} max={60} onChange={(e) => setMaxTransfer(+e.target.value)} className="h-8 text-xs" /></div>
            <div>
              <span className="text-[10px] text-muted-foreground">Hour window</span>
              <div className="flex items-center gap-2"><Input type="number" value={hourStart} min={0} max={24} onChange={(e) => setHourStart(+e.target.value)} className="w-16 h-8 text-xs" /><span className="text-xs text-muted-foreground">to</span><Input type="number" value={hourEnd} min={0} max={24} onChange={(e) => setHourEnd(+e.target.value)} className="w-16 h-8 text-xs" /></div>
            </div>
            <div><span className="text-[10px] text-muted-foreground">Min planned connections</span><Input type="number" value={minConnections} min={1} max={100} onChange={(e) => setMinConnections(+e.target.value)} className="h-8 text-xs" /></div>
          </div>
          <ApplyButton loading={isFetching} onClick={loadData} label="Analyse" />
        </>
      }
    >
      {isFetching && <LoadingState message="Analysing missed connections..." />}
      {!isFetching && !data && <EmptyState icon={Link2} message="Configure dates and click Analyse" />}

      {data && !data.error && !isFetching && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
            <MetricCard label="Total Connections" value={fmt(data.total_connections)} />
            <MetricCard label="Missed" value={fmt(data.total_missed)} danger />
            <MetricCard label="% Missed" value={data.pct_missed} suffix="%" danger={data.pct_missed > 10} />
            <MetricCard label="Worst Station" value={data.stations[0]?.name ?? "\u2014"} />
          </div>
          <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
            <div className="xl:col-span-2 space-y-4">
              <DeckMap ref={mapRef} layers={layers} className="h-[calc(100vh-22rem)]" />
              {top10Stations.length > 0 && (
                <div className="bg-card rounded-xl border border-border p-4">
                  <h3 className="text-sm font-semibold text-foreground mb-3">Top 10 Worst Stations</h3>
                  <ResponsiveContainer width="100%" height={200}>
                    <BarChart data={top10Stations} margin={{ top: 4, right: 8, bottom: 4, left: 8 }}>
                      <XAxis dataKey="name" tick={{ fontSize: 10 }} angle={-30} textAnchor="end" height={50} />
                      <YAxis tick={{ fontSize: 10 }} allowDecimals={false} />
                      <Tooltip
                        contentStyle={{ fontSize: 12, borderRadius: 8 }}
                        formatter={(value: number) => [`${value} missed`, "Count"]}
                      />
                      <Bar dataKey="missed" fill="oklch(0.55 0.2 25)" radius={[4, 4, 0, 0]} />
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
        </>
      )}

      {(error || data?.error) && <ErrorAlert message={data?.error ?? (error as Error).message} />}
    </Layout>
  );
}
