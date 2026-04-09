import { createRoute } from "@tanstack/react-router";
import { useState, useMemo, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import type { Layer } from "@deck.gl/core";
import { Search } from "lucide-react";
import { rootRoute } from "./__root";
import { Layout } from "@/components/Layout";
import { MetricCard } from "@/components/MetricCard";
import { LoadingState } from "@/components/LoadingState";
import { EmptyState } from "@/components/EmptyState";
import { ErrorAlert } from "@/components/ErrorAlert";
import { ApplyButton } from "@/components/ApplyButton";
import { DataTable } from "@/components/DataTable";
import { DeckMap, type DeckMapRef } from "@/components/DeckMap";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { fetchApi } from "@/lib/api";
import { fmt, daysAgo } from "@/lib/utils";
import { stationLayer, colorToRGBA } from "@/lib/layers";

export const propagationRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/propagation",
  component: PropagationPage,
});

interface PropStation { name: string; lat?: number; lon?: number; incidents: number; total_delay: number; }
interface PropData { n_events: number; n_stations: number; total_delay_min: number; stations: PropStation[]; error?: string; }

function PropagationPage() {
  const [viewMode, setViewMode] = useState<"stations" | "segments">("stations");
  const [startDate, setStartDate] = useState(daysAgo(7));
  const [endDate, setEndDate] = useState(daysAgo(1));
  const [minIncrease, setMinIncrease] = useState(60);
  const [minIncidents, setMinIncidents] = useState(3);
  const [hourStart, setHourStart] = useState(0);
  const [hourEnd, setHourEnd] = useState(24);
  const [queryParams, setQueryParams] = useState<Record<string, string | number | boolean> | null>(null);
  const mapRef = useRef<DeckMapRef>(null);

  const { data, error, isFetching } = useQuery({
    queryKey: ["propagation", queryParams],
    queryFn: () => fetchApi<PropData>("/propagation", queryParams!),
    enabled: !!queryParams,
  });

  const loadData = () => setQueryParams({ start: startDate, end: endDate, min_increase: minIncrease, min_incidents: minIncidents, hour_start: hourStart, hour_end: hourEnd, view: viewMode });

  const layers = useMemo<Layer[]>(() => {
    if (!data || data.error) return [];
    const stations = (data.stations || []).filter((s) => s.lat && s.lon);
    if (!stations.length) return [];
    const maxDelay = Math.max(...stations.map((s) => s.total_delay));

    return [
      stationLayer("propagation-stations", stations, {
        positionFn: (d) => [d.lon!, d.lat!],
        radiusFn: (d) => 4 + (d.total_delay / Math.max(maxDelay, 1)) * 16,
        colorFn: (d) => colorToRGBA(d.total_delay / Math.max(maxDelay, 1)),
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
            <Label>View</Label>
            <div className="mt-1.5">
              <Tabs value={viewMode} onValueChange={(v) => setViewMode(v as "stations" | "segments")}>
                <TabsList className="w-full">
                  <TabsTrigger value="stations" className="flex-1 capitalize">Stations</TabsTrigger>
                  <TabsTrigger value="segments" className="flex-1 capitalize">Segments</TabsTrigger>
                </TabsList>
              </Tabs>
            </div>
          </div>
          <div className="border-t border-border/40 pt-3 mt-3">
            <Label>Date Range</Label>
            <div className="grid grid-cols-2 gap-2 mt-1.5">
              <div><span className="text-[10px] text-muted-foreground/60">From</span><Input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} className="h-8 text-xs" /></div>
              <div><span className="text-[10px] text-muted-foreground/60">To</span><Input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} className="h-8 text-xs" /></div>
            </div>
          </div>
          <div className="border-t border-border/40 pt-3 mt-3 space-y-2">
            <Label>Thresholds</Label>
            <div><span className="text-[10px] text-muted-foreground/60">Min delay increase (sec)</span><Input type="number" value={minIncrease} min={0} max={600} onChange={(e) => setMinIncrease(+e.target.value)} className="h-8 text-xs" /></div>
            <div><span className="text-[10px] text-muted-foreground/60">Min incidents</span><Input type="number" value={minIncidents} min={1} max={100} onChange={(e) => setMinIncidents(+e.target.value)} className="h-8 text-xs" /></div>
            <div>
              <span className="text-[10px] text-muted-foreground/60">Hour window</span>
              <div className="flex items-center gap-2"><Input type="number" value={hourStart} min={0} max={24} onChange={(e) => setHourStart(+e.target.value)} className="w-16 h-8 text-xs" /><span className="text-xs text-muted-foreground/50">to</span><Input type="number" value={hourEnd} min={0} max={24} onChange={(e) => setHourEnd(+e.target.value)} className="w-16 h-8 text-xs" /></div>
            </div>
          </div>
          <ApplyButton loading={isFetching} onClick={loadData} label="Analyse" />
        </>
      }
    >
      {isFetching && <LoadingState message="Analysing delay propagation..." />}
      {!isFetching && !data && <EmptyState icon={Search} message="Configure filters and click Analyse" />}

      {data && !data.error && !isFetching && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-3 mb-5 animate-slide-up">
            <MetricCard label="Delay Events" value={fmt(data.n_events)} />
            <MetricCard label="Stations Involved" value={fmt(data.n_stations)} />
            <MetricCard label="Total Delay Added" value={fmt(data.total_delay_min, 0)} suffix="min" />
          </div>
          <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
            <div className="xl:col-span-2">
              <DeckMap ref={mapRef} layers={layers} className="h-[calc(100vh-14rem)]" />
            </div>
            <DataTable
              title="Worst Delay Sources"
              keyFn={(s) => s.name}
              data={data.stations}
              maxRows={30}
              columns={[
                { header: "Station", accessor: (s) => <span className="font-medium truncate max-w-[140px] block">{s.name}</span> },
                { header: "Events", accessor: (s) => <span className="text-muted-foreground">{s.incidents}</span>, align: "right" },
                { header: "Delay", accessor: (s) => <span className="font-semibold text-destructive">{fmt(s.total_delay, 0)}m</span>, align: "right" },
              ]}
            />
          </div>
        </>
      )}

      {(error || data?.error) && <ErrorAlert message={data?.error ?? (error as Error).message} />}
    </Layout>
  );
}
