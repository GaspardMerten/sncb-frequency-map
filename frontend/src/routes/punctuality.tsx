import { createRoute } from "@tanstack/react-router";
import { useState, useMemo, useRef, useEffect, useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlarmClock, Play, Pause } from "lucide-react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from "recharts";
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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { DeckMap, type DeckMapRef } from "@/components/DeckMap";
import { stationLayer, colorToRGBA } from "@/lib/layers";
import { fetchApi } from "@/lib/api";
import { fmt, daysAgo, valueToColor } from "@/lib/utils";
import { cn } from "@/lib/utils";

export const punctualityRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/punctuality",
  component: PunctualityPage,
});

interface PunctStation { name: string; lat: number; lon: number; avg_delay: number; n_trains: number; pct_late: number; }
interface HourlyEntry { hour: number; avg_delay: number; n_trains: number; }
interface PunctData { summary: { n_stations: number; avg_delay: string; median_delay: string; pct_late: string }; stations: PunctStation[]; hourly?: HourlyEntry[]; error?: string; }

const HOUR_BUTTONS = Array.from({ length: 19 }, (_, i) => i + 5); // 5..23

function PunctualityPage() {
  const [viewMode, setViewMode] = useState<"stations" | "timeline">("stations");
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

  // Timeline state
  const [currentHour, setCurrentHour] = useState(7);
  const [isPlaying, setIsPlaying] = useState(false);

  // Timeline query: fetches data for a single-hour window
  const timelineParams = useMemo(() => {
    if (viewMode !== "timeline" || !queryParams) return null;
    return {
      ...queryParams,
      hour_start: currentHour,
      hour_end: currentHour + 1,
      min_trains: 1,
    };
  }, [viewMode, queryParams, currentHour]);

  const { data, error, isFetching } = useQuery({
    queryKey: ["punctuality", queryParams],
    queryFn: () => fetchApi<PunctData>("/punctuality", queryParams!),
    enabled: !!queryParams && viewMode === "stations",
  });

  const { data: timelineData, isFetching: isTimelineFetching } = useQuery({
    queryKey: ["punctuality-timeline", timelineParams],
    queryFn: () => fetchApi<PunctData>("/punctuality", timelineParams!),
    enabled: !!timelineParams,
  });

  const activeData = viewMode === "timeline" ? timelineData : data;
  const activeLoading = viewMode === "timeline" ? isTimelineFetching : isFetching;

  // Auto-play: advance hour every 2s
  useEffect(() => {
    if (!isPlaying) return;
    const interval = setInterval(() => {
      setCurrentHour((h) => (h >= 23 ? 5 : h + 1));
    }, 2000);
    return () => clearInterval(interval);
  }, [isPlaying]);

  // Stop playing when switching away from timeline
  useEffect(() => {
    if (viewMode !== "timeline") setIsPlaying(false);
  }, [viewMode]);

  const loadData = useCallback(() => {
    setQueryParams({
      target_date: targetDate,
      hour_start: hourStart,
      hour_end: hourEnd,
      min_trains: minTrains,
      delay_floor: excludeOutliers ? delayFloor : 0,
      delay_cap: delayCap,
      metric,
    });
  }, [targetDate, hourStart, hourEnd, minTrains, delayFloor, delayCap, excludeOutliers, metric]);

  const layers = useMemo(() => {
    if (!activeData || activeData.error || !activeData.stations.length) return [];

    const maxDelay = Math.max(...activeData.stations.map((s) => s.avg_delay));
    const maxTrainsVal = Math.max(...activeData.stations.map((s) => s.n_trains));

    return [
      stationLayer("punctuality-stations", activeData.stations, {
        positionFn: (s) => [s.lon, s.lat],
        radiusFn: (s) => 4 + (s.n_trains / maxTrainsVal) * 14,
        colorFn: (s) => colorToRGBA(s.avg_delay / Math.max(maxDelay, 1)),
        radiusMinPixels: 3,
        radiusMaxPixels: 20,
      }),
    ];
  }, [activeData]);

  const handleRowClick = (s: PunctStation) => {
    mapRef.current?.flyTo({ longitude: s.lon, latitude: s.lat, zoom: 12 });
  };

  // Compute max delay for hourly chart color scaling
  const maxHourlyDelay = useMemo(() => {
    if (!data?.hourly) return 1;
    return Math.max(...data.hourly.map((h) => h.avg_delay), 1);
  }, [data]);

  return (
    <Layout
      sidebar={
        <>
          <div>
            <Label>View</Label>
            <div className="mt-1.5">
              <Tabs value={viewMode} onValueChange={(v) => setViewMode(v as "stations" | "timeline")}>
                <TabsList className="w-full">
                  <TabsTrigger value="stations" className="flex-1">Stations</TabsTrigger>
                  <TabsTrigger value="timeline" className="flex-1">Timeline</TabsTrigger>
                </TabsList>
              </Tabs>
            </div>
          </div>

          <div className="border-t border-border/40 pt-3 mt-3">
            <Label>Date</Label>
            <Input type="date" value={targetDate} onChange={(e) => setTargetDate(e.target.value)} className="h-8 text-xs mt-1.5" />
          </div>

          <div className="border-t border-border/40 pt-3 mt-3">
            <Label>Delay Metric</Label>
            <Tabs value={metric} onValueChange={(v) => setMetric(v as "departure" | "arrival")} className="mt-1.5">
              <TabsList className="w-full">
                <TabsTrigger value="departure" className="flex-1">Departure</TabsTrigger>
                <TabsTrigger value="arrival" className="flex-1">Arrival</TabsTrigger>
              </TabsList>
            </Tabs>
          </div>

          {viewMode === "stations" && (
            <div className="border-t border-border/40 pt-3 mt-3 space-y-2">
              <Label>Filters</Label>
              <div>
                <Label className="text-[10px] text-muted-foreground/60 normal-case tracking-normal font-medium">Hour window</Label>
                <div className="flex items-center gap-2">
                  <Input type="number" value={hourStart} min={0} max={24} onChange={(e) => setHourStart(+e.target.value)} className="w-16 h-8 text-xs" />
                  <span className="text-xs text-muted-foreground/50">to</span>
                  <Input type="number" value={hourEnd} min={0} max={24} onChange={(e) => setHourEnd(+e.target.value)} className="w-16 h-8 text-xs" />
                </div>
              </div>
              <div>
                <Label className="text-[10px] text-muted-foreground/60 normal-case tracking-normal font-medium">Min trains per station</Label>
                <Input type="number" value={minTrains} min={1} max={100} onChange={(e) => setMinTrains(+e.target.value)} className="h-8 text-xs" />
              </div>
              <div>
                <Label className="text-[10px] text-muted-foreground/60 normal-case tracking-normal font-medium">Min delay (min)</Label>
                <Input type="number" value={delayFloor} min={0} max={120} onChange={(e) => setDelayFloor(+e.target.value)} className="h-8 text-xs" />
              </div>
              <div>
                <Label className="text-[10px] text-muted-foreground/60 normal-case tracking-normal font-medium">Delay cap (min)</Label>
                <Input type="number" value={delayCap} min={1} max={120} onChange={(e) => setDelayCap(+e.target.value)} className="h-8 text-xs" />
              </div>
              <div className="flex items-center justify-between pt-1">
                <Label className="text-[10px] text-muted-foreground/60 normal-case tracking-normal font-medium">Exclude out-of-range</Label>
                <Switch checked={excludeOutliers} onCheckedChange={setExcludeOutliers} />
              </div>
            </div>
          )}

          {viewMode === "timeline" && (
            <div className="border-t border-border/40 pt-3 mt-3 space-y-3">
              <Label>Timeline Controls</Label>
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-lg font-semibold tabular-nums text-foreground">
                    {String(currentHour).padStart(2, "0")}:00 &ndash; {String(currentHour + 1).padStart(2, "0")}:00
                  </span>
                  <button
                    onClick={() => setIsPlaying((p) => !p)}
                    className={cn(
                      "inline-flex items-center justify-center h-8 w-8 rounded-lg border transition-colors",
                      isPlaying
                        ? "bg-destructive/10 border-destructive/30 text-destructive hover:bg-destructive/20"
                        : "bg-primary/10 border-primary/30 text-primary hover:bg-primary/20",
                    )}
                  >
                    {isPlaying ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
                  </button>
                </div>
              </div>
              <div>
                <Label className="text-[10px] text-muted-foreground/60 normal-case tracking-normal font-medium">Delay cap (min)</Label>
                <Input type="number" value={delayCap} min={1} max={120} onChange={(e) => setDelayCap(+e.target.value)} className="h-8 text-xs" />
              </div>
            </div>
          )}

          <ApplyButton loading={activeLoading} onClick={loadData} label="Analyse" />
        </>
      }
    >
      {activeData && !activeData.error && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5 animate-slide-up">
          <MetricCard label="Stations" value={fmt(activeData.summary.n_stations)} />
          <MetricCard label="Avg Delay" value={activeData.summary.avg_delay} suffix=" min" />
          <MetricCard label="Median Delay" value={activeData.summary.median_delay} suffix=" min" />
          <MetricCard label="% Late (>1min)" value={activeData.summary.pct_late} suffix="%" />
        </div>
      )}

      {activeLoading && <LoadingState message="Loading punctuality data..." />}
      {!activeLoading && !activeData && <EmptyState icon={AlarmClock} message="Select a date and click Analyse" />}

      {activeData && !activeData.error && !activeLoading && (
        <>
          {viewMode === "timeline" && (
            <div className="mb-4 flex items-center gap-3 rounded-xl border border-border/50 bg-card px-4 py-2.5 shadow-sm animate-slide-up">
              <span className="text-sm font-medium text-muted-foreground">Showing hour</span>
              <span className="text-lg font-bold tabular-nums text-foreground">
                {String(currentHour).padStart(2, "0")}:00 &ndash; {String(currentHour + 1).padStart(2, "0")}:00
              </span>
              {isPlaying && (
                <span className="ml-auto flex items-center gap-1.5 text-xs text-primary">
                  <span className="h-2 w-2 rounded-full bg-primary animate-pulse" />
                  Playing
                </span>
              )}
            </div>
          )}

          <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
            <div className="xl:col-span-2 space-y-2">
              <DeckMap ref={mapRef} layers={layers} className="h-[calc(100vh-14rem)]" />
              <ColorLegend min="On time" max="Very late" label="Delay" />

              {/* Hour buttons row below map (timeline mode only) */}
              {viewMode === "timeline" && (
                <div className="flex items-center gap-1.5 flex-wrap pt-1">
                  <button
                    onClick={() => setIsPlaying((p) => !p)}
                    className={cn(
                      "inline-flex items-center justify-center h-8 w-8 rounded-lg border transition-colors shrink-0",
                      isPlaying
                        ? "bg-destructive/10 border-destructive/30 text-destructive hover:bg-destructive/20"
                        : "bg-primary/10 border-primary/30 text-primary hover:bg-primary/20",
                    )}
                  >
                    {isPlaying ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
                  </button>
                  {HOUR_BUTTONS.map((h) => (
                    <button
                      key={h}
                      onClick={() => { setCurrentHour(h); setIsPlaying(false); }}
                      className={cn(
                        "h-8 min-w-[2.25rem] px-1.5 rounded-lg border text-xs font-medium tabular-nums transition-colors",
                        h === currentHour
                          ? "bg-primary text-primary-foreground border-primary shadow-sm"
                          : "bg-card border-border/50 text-muted-foreground hover:bg-muted hover:text-foreground",
                      )}
                    >
                      {h}h
                    </button>
                  ))}
                </div>
              )}
            </div>
            <DataTable
              title={viewMode === "timeline" ? `Stations (${String(currentHour).padStart(2, "0")}:00)` : "Most Delayed Stations"}
              keyFn={(s) => s.name}
              data={activeData.stations}
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

          {viewMode === "stations" && data?.hourly && data.hourly.length > 0 && (
            <div className="mt-4 bg-card rounded-2xl border border-border/50 p-5 shadow-sm animate-slide-up">
              <h3 className="text-sm font-semibold text-foreground mb-4">Hourly Average Delay</h3>
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={data.hourly} margin={{ top: 4, right: 8, bottom: 4, left: 8 }}>
                  <XAxis dataKey="hour" tick={{ fontSize: 10 }} tickFormatter={(h) => `${h}h`} />
                  <YAxis tick={{ fontSize: 10 }} label={{ value: "Avg delay (min)", angle: -90, position: "insideLeft", offset: 5, fontSize: 10 }} />
                  <Tooltip
                    contentStyle={{ fontSize: 12, borderRadius: 12, border: '1px solid var(--color-border)' }}
                    formatter={(value: number) => [`${value} min`, "Avg delay"]}
                    labelFormatter={(h) => `${h}:00 - ${h}:59`}
                  />
                  <Bar dataKey="avg_delay" radius={[4, 4, 0, 0]}>
                    {data.hourly.map((entry, index) => (
                      <Cell key={index} fill={valueToColor(entry.avg_delay / maxHourlyDelay)} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}

          <div className="mt-4">
            <MethodologyPanel>
              <p>Punctuality data comes from the Infrabel real-time feed, providing actual vs. planned departure/arrival times for each train at each station. Delay is computed as the difference in seconds, converted to minutes.</p>
              <p>Delays below the floor are set to 0 (on-time), and delays above the cap are clamped. Circle size represents train frequency at the station, while color represents average delay magnitude. The hourly chart shows how delays vary throughout the day.</p>
              {viewMode === "timeline" && (
                <p>Timeline mode queries the API for each one-hour window individually, letting you step through the day and observe how station-level delays evolve hour by hour. Use the play button to auto-advance through hours.</p>
              )}
            </MethodologyPanel>
          </div>
        </>
      )}

      {(error || activeData?.error) && <ErrorAlert message={activeData?.error ?? (error as Error).message} />}
    </Layout>
  );
}
