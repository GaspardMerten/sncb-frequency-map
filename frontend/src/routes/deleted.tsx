import { createRoute } from "@tanstack/react-router";
import { useState, useMemo, useCallback, useRef } from "react";
import { Ban } from "lucide-react";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  ComposedChart, Line, CartesianGrid, Legend, ReferenceLine,
} from "recharts";
import { rootRoute } from "./__root";
import { Layout } from "@/components/Layout";
import { MetricCard } from "@/components/MetricCard";
import { EmptyState } from "@/components/EmptyState";
import { ErrorAlert } from "@/components/ErrorAlert";
import { ApplyButton } from "@/components/ApplyButton";
import { DataTable } from "@/components/DataTable";
import { MethodologyPanel } from "@/components/MethodologyPanel";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { fetchApiSSE } from "@/lib/api";
import { fmt, daysAgo, cn } from "@/lib/utils";

export const deletedRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/deleted",
  component: DeletedPage,
});

interface DeletedStation { name: string; count: number; lat?: number; lon?: number; }
interface DeletedSegment { a: string; b: string; count: number; }
interface DailyPoint { date: string; scheduled: number; deleted: number; pct_deleted: number; suspicious?: boolean; }
interface HourlyPoint { hour: number; scheduled: number; deleted: number; pct_deleted: number; }
interface DeletedTrain {
  train_no: string; date: string; duration_min: number; n_stops: number;
  first_station: string; last_station: string; first_dep_hour: number;
}
interface DeletedData {
  suspicious_days?: string[];
  n_days: number;
  start_date: string;
  end_date: string;
  n_scheduled: number;
  n_deleted: number;
  pct_deleted: number;
  impacted_time_min: number;
  impacted_stops: number;
  stations: DeletedStation[];
  segments: DeletedSegment[];
  hourly: HourlyPoint[];
  daily: DailyPoint[];
  trains: DeletedTrain[];
  error?: string;
}

function formatHours(min: number): string {
  if (min < 60) return `${Math.round(min)} min`;
  const h = Math.floor(min / 60);
  const m = Math.round(min % 60);
  return m === 0 ? `${h}h` : `${h}h ${m}m`;
}

function DeletedPage() {
  const [startDate, setStartDate] = useState(daysAgo(7));
  const [endDate, setEndDate] = useState(daysAgo(2));
  const [excludePub, setExcludePub] = useState(false);
  const [minStops, setMinStops] = useState(2);

  const [data, setData] = useState<DeletedData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isFetching, setIsFetching] = useState(false);
  const [progress, setProgress] = useState<{ done: number; total: number; phase?: string } | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const loadData = useCallback(async () => {
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;

    setIsFetching(true);
    setError(null);
    setProgress(null);
    setData(null);

    try {
      const result = await fetchApiSSE<DeletedData>(
        "/deleted",
        {
          start: startDate,
          end: endDate,
          exclude_pub: excludePub,
          min_stops: minStops,
        },
        (p) => setProgress(p),
      );
      if (!ctrl.signal.aborted) {
        setData(result);
        setProgress(null);
      }
    } catch (e) {
      if (!ctrl.signal.aborted) {
        setError((e as Error).message);
      }
    } finally {
      if (!ctrl.signal.aborted) {
        setIsFetching(false);
      }
    }
  }, [startDate, endDate, excludePub, minStops]);

  const topStations = useMemo(() => {
    if (!data?.stations) return [];
    return data.stations.slice(0, 15).map((s) => ({
      name: s.name.length > 16 ? s.name.slice(0, 16) + "…" : s.name,
      fullName: s.name,
      count: s.count,
    }));
  }, [data]);

  const topSegments = useMemo(() => {
    if (!data?.segments) return [];
    return data.segments.slice(0, 15);
  }, [data]);

  const dailyChart = useMemo(() => {
    if (!data?.daily) return [];
    return data.daily.map((d) => ({
      date: d.date.slice(5),
      deleted: d.deleted,
      scheduled: d.scheduled,
      pct: d.pct_deleted,
    }));
  }, [data]);

  const avgPctDeleted = useMemo(() => {
    if (!data?.daily?.length) return 0;
    return data.daily.reduce((s, d) => s + d.pct_deleted, 0) / data.daily.length;
  }, [data]);

  return (
    <Layout
      sidebar={
        <>
          <div>
            <Label>Date Range</Label>
            <div className="grid grid-cols-2 gap-2 mt-1.5">
              <div>
                <span className="text-[10px] text-muted-foreground/60">From</span>
                <Input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} className="h-8 text-xs" />
              </div>
              <div>
                <span className="text-[10px] text-muted-foreground/60">To</span>
                <Input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} className="h-8 text-xs" />
              </div>
            </div>
            <p className="text-[10px] text-muted-foreground/60 mt-1.5">
              Punctuality data lags by ~2 days; pick dates at least 2 days in the past.
            </p>
          </div>

          <div className="border-t border-border/40 pt-3 mt-3 space-y-2">
            <Label>Filters</Label>
            <div>
              <span className="text-[10px] text-muted-foreground/60">Min commercial stops per train</span>
              <Input type="number" value={minStops} min={1} max={20} onChange={(e) => setMinStops(+e.target.value)} className="h-8 text-xs" />
            </div>
            <label className="flex items-center gap-2 text-xs text-muted-foreground cursor-pointer select-none">
              <input type="checkbox" checked={excludePub} onChange={(e) => setExcludePub(e.target.checked)} className="rounded" />
              Exclude public holidays
            </label>
          </div>
          <ApplyButton loading={isFetching} onClick={loadData} label="Analyse" />
        </>
      }
    >
      {isFetching && (
        <div className="flex flex-col items-center justify-center py-20 animate-slide-up">
          <Ban className="h-10 w-10 text-destructive/40 mb-4 animate-pulse" />
          {progress ? (
            <>
              <div className="w-64 h-2 rounded-full bg-muted overflow-hidden mb-2">
                <div
                  className="h-full rounded-full bg-destructive/60 transition-all duration-300 ease-out"
                  style={{ width: `${Math.round((progress.done / Math.max(progress.total, 1)) * 100)}%` }}
                />
              </div>
              <p className="text-sm text-muted-foreground">
                {progress.phase === "fetch" ? "Fetching" : "Processing"} day {progress.done} of {progress.total}...
              </p>
            </>
          ) : (
            <p className="text-sm text-muted-foreground">Comparing schedule to observations…</p>
          )}
        </div>
      )}

      {!isFetching && !data && !error && (
        <EmptyState icon={Ban} message="Select a date range and click Analyse" />
      )}

      {data && !data.error && !isFetching && (
        <>
          {data.suspicious_days && data.suspicious_days.length > 0 && (
            <div className="mb-4 rounded-xl border border-amber-400/40 bg-amber-50 text-amber-900 px-4 py-3 text-xs">
              <b>Data quality warning:</b> {data.suspicious_days.length} day(s)
              show unusually high deletion rates (&gt; 30%), likely a gap in the
              Infrabel punctuality feed rather than real cancellations. Affected dates:
              {" "}
              {data.suspicious_days.join(", ")}. The summary metrics below include
              these days; treat the totals as upper bounds.
            </div>
          )}

          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5 animate-slide-up">
            <MetricCard label="Days Analysed" value={fmt(data.n_days)} />
            <MetricCard label="Deleted Trains" value={fmt(data.n_deleted)} danger />
            <MetricCard label="% Deleted" value={data.pct_deleted} suffix="%" danger={data.pct_deleted > 1} />
            <MetricCard label="Impacted Service Time" value={formatHours(data.impacted_time_min)} danger />
          </div>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5 animate-slide-up">
            <MetricCard label="Scheduled Trains" value={fmt(data.n_scheduled)} />
            <MetricCard label="Impacted Stops" value={fmt(data.impacted_stops)} />
            <MetricCard label="Avg Daily % Deleted" value={avgPctDeleted.toFixed(2)} suffix="%" />
            <MetricCard label="Worst Station" value={data.stations[0]?.name ?? "\u2014"} />
          </div>

          {dailyChart.length > 0 && (
            <div className="bg-card rounded-2xl border border-border/50 p-5 shadow-sm mb-4 animate-slide-up">
              <h3 className="text-sm font-semibold text-foreground mb-1">Daily Deletions</h3>
              <p className="text-[10px] text-muted-foreground mb-3">Red bars = deleted trains · Line = % deleted (right axis)</p>
              <ResponsiveContainer width="100%" height={240}>
                <ComposedChart data={dailyChart} margin={{ top: 8, right: 24, bottom: 8, left: 8 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" opacity={0.4} />
                  <XAxis dataKey="date" tick={{ fontSize: 10 }} angle={-30} textAnchor="end" height={40} />
                  <YAxis yAxisId="left" tick={{ fontSize: 10 }} allowDecimals={false} label={{ value: "Deleted", angle: -90, position: "insideLeft", offset: 8, fontSize: 10 }} />
                  <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 10 }} label={{ value: "%", angle: 90, position: "insideRight", offset: 0, fontSize: 10 }} />
                  <Tooltip
                    contentStyle={{ fontSize: 12, borderRadius: 12, border: "1px solid var(--color-border)" }}
                    formatter={(v: number, name: string) => name === "pct" ? [`${v.toFixed(2)}%`, "% deleted"] : [fmt(v), name === "deleted" ? "Deleted" : "Scheduled"]}
                  />
                  <Bar yAxisId="left" dataKey="deleted" fill="oklch(0.58 0.22 25)" radius={[4, 4, 0, 0]} />
                  <Line yAxisId="right" type="monotone" dataKey="pct" stroke="oklch(0.55 0.15 250)" strokeWidth={2} dot={{ r: 3 }} />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          )}

          <div className="grid grid-cols-1 xl:grid-cols-2 gap-4 mb-4">
            {topStations.length > 0 && (
              <div className="bg-card rounded-2xl border border-border/50 p-5 shadow-sm animate-slide-up">
                <h3 className="text-sm font-semibold text-foreground mb-1">Most Impacted Stations</h3>
                <p className="text-[10px] text-muted-foreground mb-3">Station stops skipped because the train was deleted</p>
                <ResponsiveContainer width="100%" height={340}>
                  <BarChart data={topStations} layout="vertical" margin={{ top: 4, right: 16, bottom: 4, left: 8 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" opacity={0.4} />
                    <XAxis type="number" tick={{ fontSize: 10 }} allowDecimals={false} />
                    <YAxis type="category" dataKey="name" tick={{ fontSize: 10 }} width={120} />
                    <Tooltip
                      contentStyle={{ fontSize: 12, borderRadius: 12, border: "1px solid var(--color-border)" }}
                      content={({ active, payload }) => {
                        if (!active || !payload?.length) return null;
                        const p = payload[0].payload;
                        return (
                          <div className="rounded-xl border border-border/50 bg-card px-3 py-2 text-xs shadow-lg">
                            <p className="font-semibold">{p.fullName}</p>
                            <p>{fmt(p.count)} stops missed</p>
                          </div>
                        );
                      }}
                    />
                    <Bar dataKey="count" fill="oklch(0.58 0.22 25)" radius={[0, 4, 4, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}

            {data.hourly.length > 0 && (
              <div className="bg-card rounded-2xl border border-border/50 p-5 shadow-sm animate-slide-up">
                <h3 className="text-sm font-semibold text-foreground mb-1">Hourly Distribution</h3>
                <p className="text-[10px] text-muted-foreground mb-3">Deletions bucketed by first-departure hour</p>
                <ResponsiveContainer width="100%" height={340}>
                  <BarChart data={data.hourly} margin={{ top: 4, right: 16, bottom: 4, left: 8 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" opacity={0.4} />
                    <XAxis dataKey="hour" tick={{ fontSize: 10 }} label={{ value: "Hour", position: "insideBottom", offset: -2, fontSize: 10 }} />
                    <YAxis yAxisId="left" tick={{ fontSize: 10 }} allowDecimals={false} />
                    <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 10 }} />
                    <Tooltip
                      contentStyle={{ fontSize: 12, borderRadius: 12, border: "1px solid var(--color-border)" }}
                      formatter={(v: number, name: string) => {
                        if (name === "pct_deleted") return [`${(v as number).toFixed(2)}%`, "% deleted"];
                        return [fmt(v), name === "deleted" ? "Deleted" : "Scheduled"];
                      }}
                    />
                    <Legend wrapperStyle={{ fontSize: 10 }} />
                    <Bar yAxisId="left" dataKey="deleted" fill="oklch(0.58 0.22 25)" radius={[3, 3, 0, 0]} />
                    <ReferenceLine yAxisId="right" y={avgPctDeleted} stroke="oklch(0.55 0.15 250)" strokeDasharray="3 3" label={{ value: `avg ${avgPctDeleted.toFixed(2)}%`, fontSize: 9, fill: "oklch(0.55 0.15 250)" }} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </div>

          <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
            <DataTable
              title="Most Impacted Segments"
              keyFn={(s) => `${s.a}|${s.b}`}
              data={topSegments}
              maxRows={30}
              columns={[
                { header: "Segment", accessor: (s) => (
                  <span className="font-medium truncate max-w-[260px] block">
                    {s.a} <span className="text-muted-foreground">↔</span> {s.b}
                  </span>
                ) },
                { header: "Missed passes", accessor: (s) => <span className="font-semibold tabular-nums text-destructive">{fmt(s.count)}</span>, align: "right" },
              ]}
            />

            <DataTable
              title="Deleted Trains (sample, by duration)"
              keyFn={(t) => `${t.train_no}|${t.date}`}
              data={data.trains}
              maxRows={50}
              columns={[
                { header: "Train", accessor: (t) => <span className="font-mono font-semibold">{t.train_no}</span> },
                { header: "Date", accessor: (t) => <span className="text-muted-foreground">{t.date}</span> },
                { header: "Route", accessor: (t) => (
                  <span className="truncate max-w-[260px] block text-muted-foreground">
                    {t.first_station} <span className="text-[10px]">→</span> {t.last_station}
                  </span>
                ) },
                { header: "Stops", accessor: (t) => <span className="tabular-nums">{t.n_stops}</span>, align: "right" },
                { header: "Duration", accessor: (t) => <span className={cn("tabular-nums font-medium", t.duration_min > 60 ? "text-destructive" : "text-muted-foreground")}>{t.duration_min}m</span>, align: "right" },
                { header: "Hour", accessor: (t) => <span className="text-muted-foreground tabular-nums">{t.first_dep_hour >= 0 ? `${String(t.first_dep_hour).padStart(2, "0")}:00` : "\u2014"}</span>, align: "right" },
              ]}
            />
          </div>

          <div className="mt-4">
            <MethodologyPanel>
              <p><b>What is a "deleted" train?</b> — A train that appears in the GTFS static schedule for a given date but has no matching observation in the Infrabel punctuality feed. Trains are matched by <code>trip_short_name</code> (GTFS) against <code>train_no</code> (Infrabel).</p>
              <p><b>Scope</b> — Only SNCB/NMBS trains are considered, and only trips with at least one commercial stop (GTFS <code>pickup_type=0</code> or <code>drop_off_type=0</code>). Trips active on each analysed date are resolved through GTFS <code>calendar</code>/<code>calendar_dates</code>.</p>
              <p><b>Impacted time</b> — Sum of the GTFS-scheduled duration (first departure → last arrival) across deleted trains. <b>Impacted stops</b> sums the commercial stops each deleted train would have served.</p>
              <p><b>How is "deleted" inferred?</b> — We do <i>not</i> have an authoritative cancellation feed. A GTFS-scheduled train is flagged as deleted when its <code>train_no</code> is absent from the Infrabel punctuality feed for that day. This is a heuristic, not ground truth.</p>
              <p><b>Known caveats</b> — False positives can arise from (a) renumbered/replacement trains, (b) partial Infrabel data for the day, (c) trains running under a different operator label, (d) trains that ran but had no timing records emitted. False negatives include partial cancellations (train ran the first half of its route, then was cut short) — those count as "observed" here. Cross-check with SNCB incident reports before drawing operational conclusions. A GTFS-Realtime <code>TripUpdate</code> feed with <code>SCHEDULE_RELATIONSHIP=CANCELED</code> would be authoritative.</p>
            </MethodologyPanel>
          </div>
        </>
      )}

      {(error || data?.error) && <ErrorAlert message={data?.error ?? error ?? "Unknown error"} />}
    </Layout>
  );
}
