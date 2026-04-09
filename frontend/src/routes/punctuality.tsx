import { createRoute } from "@tanstack/react-router";
import { useState, useMemo, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlarmClock } from "lucide-react";
import { rootRoute } from "./__root";
import { Layout } from "@/components/Layout";
import { MetricCard } from "@/components/MetricCard";
import { LoadingState } from "@/components/LoadingState";
import { EmptyState } from "@/components/EmptyState";
import { ErrorAlert } from "@/components/ErrorAlert";
import { ApplyButton } from "@/components/ApplyButton";
import { DataTable } from "@/components/DataTable";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { DeckMap, type DeckMapRef } from "@/components/DeckMap";
import { stationLayer, colorToRGBA } from "@/lib/layers";
import { fetchApi } from "@/lib/api";
import { fmt, daysAgo } from "@/lib/utils";
import { cn } from "@/lib/utils";

export const punctualityRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/punctuality",
  component: PunctualityPage,
});

interface PunctStation { name: string; lat: number; lon: number; avg_delay: number; n_trains: number; pct_late: number; }
interface PunctData { summary: { n_stations: number; avg_delay: string; median_delay: string; pct_late: string }; stations: PunctStation[]; error?: string; }

function PunctualityPage() {
  const [targetDate, setTargetDate] = useState(daysAgo(2));
  const [metric, setMetric] = useState<"departure" | "arrival">("departure");
  const [hourStart, setHourStart] = useState(5);
  const [hourEnd, setHourEnd] = useState(24);
  const [minTrains, setMinTrains] = useState(5);
  const [delayFloor, setDelayFloor] = useState(0);
  const [delayCap, setDelayCap] = useState(30);
  const [excludeOutliers, setExcludeOutliers] = useState(false);
  const [queryParams, setQueryParams] = useState<Record<string, string | number | boolean> | null>(null);
  const mapRef = useRef<DeckMapRef>(null);

  const { data, error, isFetching } = useQuery({
    queryKey: ["punctuality", queryParams],
    queryFn: () => fetchApi<PunctData>("/punctuality", queryParams!),
    enabled: !!queryParams,
  });

  const loadData = () => setQueryParams({
    target_date: targetDate,
    hour_start: hourStart,
    hour_end: hourEnd,
    min_trains: minTrains,
    delay_floor: excludeOutliers ? delayFloor : 0,
    delay_cap: delayCap,
    metric,
  });

  const layers = useMemo(() => {
    if (!data || data.error || !data.stations.length) return [];

    const maxDelay = Math.max(...data.stations.map((s) => s.avg_delay));
    const maxTrainsVal = Math.max(...data.stations.map((s) => s.n_trains));

    return [
      stationLayer("punctuality-stations", data.stations, {
        positionFn: (s) => [s.lon, s.lat],
        radiusFn: (s) => 4 + (s.n_trains / maxTrainsVal) * 14,
        colorFn: (s) => colorToRGBA(s.avg_delay / Math.max(maxDelay, 1)),
        radiusMinPixels: 3,
        radiusMaxPixels: 20,
      }),
    ];
  }, [data]);

  const handleRowClick = (s: PunctStation) => {
    mapRef.current?.flyTo({ longitude: s.lon, latitude: s.lat, zoom: 12 });
  };

  return (
    <Layout
      sidebar={
        <>
          <div><Label>Date</Label><Input type="date" value={targetDate} onChange={(e) => setTargetDate(e.target.value)} className="h-8 text-xs mt-1.5" /></div>
          <div className="border-t border-border pt-3 mt-3">
            <Label>Delay Metric</Label>
            <Tabs value={metric} onValueChange={(v) => setMetric(v as "departure" | "arrival")} className="mt-1.5">
              <TabsList className="w-full">
                <TabsTrigger value="departure" className="flex-1">Departure</TabsTrigger>
                <TabsTrigger value="arrival" className="flex-1">Arrival</TabsTrigger>
              </TabsList>
            </Tabs>
          </div>
          <div className="border-t border-border pt-3 mt-3 space-y-2">
            <Label>Filters</Label>
            <div>
              <Label className="text-[10px] text-muted-foreground">Hour window</Label>
              <div className="flex items-center gap-2">
                <Input type="number" value={hourStart} min={0} max={24} onChange={(e) => setHourStart(+e.target.value)} className="w-16 h-8 text-xs" />
                <span className="text-xs text-muted-foreground">to</span>
                <Input type="number" value={hourEnd} min={0} max={24} onChange={(e) => setHourEnd(+e.target.value)} className="w-16 h-8 text-xs" />
              </div>
            </div>
            <div>
              <Label className="text-[10px] text-muted-foreground">Min trains per station</Label>
              <Input type="number" value={minTrains} min={1} max={100} onChange={(e) => setMinTrains(+e.target.value)} className="h-8 text-xs" />
            </div>
            <div>
              <Label className="text-[10px] text-muted-foreground">Min delay (min)</Label>
              <Input type="number" value={delayFloor} min={0} max={120} onChange={(e) => setDelayFloor(+e.target.value)} className="h-8 text-xs" />
            </div>
            <div>
              <Label className="text-[10px] text-muted-foreground">Delay cap (min)</Label>
              <Input type="number" value={delayCap} min={1} max={120} onChange={(e) => setDelayCap(+e.target.value)} className="h-8 text-xs" />
            </div>
            <div className="flex items-center justify-between pt-1">
              <Label className="text-[10px] text-muted-foreground">Exclude out-of-range</Label>
              <Switch checked={excludeOutliers} onCheckedChange={setExcludeOutliers} />
            </div>
          </div>
          <ApplyButton loading={isFetching} onClick={loadData} label="Analyse" />
        </>
      }
    >
      {data && !data.error && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
          <MetricCard label="Stations" value={fmt(data.summary.n_stations)} />
          <MetricCard label="Avg Delay" value={data.summary.avg_delay} suffix=" min" />
          <MetricCard label="Median Delay" value={data.summary.median_delay} suffix=" min" />
          <MetricCard label="% Late (>1min)" value={data.summary.pct_late} suffix="%" />
        </div>
      )}

      {isFetching && <LoadingState message="Loading punctuality data..." />}
      {!isFetching && !data && <EmptyState icon={AlarmClock} message="Select a date and click Analyse" />}

      {data && !data.error && !isFetching && (
        <>
          <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
            <div className="xl:col-span-2">
              <DeckMap ref={mapRef} layers={layers} className="h-[calc(100vh-14rem)]" />
            </div>
            <DataTable
              title="Most Delayed Stations"
              keyFn={(s) => s.name}
              data={data.stations}
              maxRows={30}
              onRowClick={handleRowClick}
              columns={[
                { header: "Station", accessor: (s) => <span className="font-medium truncate max-w-[140px] block">{s.name}</span> },
                { header: "Avg", accessor: (s) => <span className={cn("font-semibold", s.avg_delay > 5 ? "text-destructive" : "text-primary")}>{s.avg_delay}m</span>, align: "right" },
                { header: "Trains", accessor: (s) => <span className="text-muted-foreground">{s.n_trains}</span>, align: "right" },
                { header: "% Late", accessor: (s) => <span className={cn(s.pct_late > 50 ? "text-destructive" : "text-muted-foreground")}>{s.pct_late}%</span>, align: "right" },
              ]}
            />
          </div>

          <div className="mt-4 rounded-xl border border-border bg-card p-4 shadow-sm">
            <h3 className="text-sm font-semibold mb-1">Hourly Delay Analysis</h3>
            <p className="text-xs text-muted-foreground">Hourly analysis requires per-train data not available from the current station-level API response.</p>
          </div>
        </>
      )}

      {(error || data?.error) && <ErrorAlert message={data?.error ?? (error as Error).message} />}
    </Layout>
  );
}
