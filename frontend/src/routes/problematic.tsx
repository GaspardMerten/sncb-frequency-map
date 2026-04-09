import { createRoute } from "@tanstack/react-router";
import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, X } from "lucide-react";
import {
  ScatterChart, Scatter, XAxis, YAxis, ZAxis, Tooltip, ResponsiveContainer, CartesianGrid, Legend,
  BarChart, Bar, ReferenceLine,
} from "recharts";
import { rootRoute } from "./__root";
import { Layout } from "@/components/Layout";
import { MetricCard } from "@/components/MetricCard";
import { LoadingState } from "@/components/LoadingState";
import { EmptyState } from "@/components/EmptyState";
import { ErrorAlert } from "@/components/ErrorAlert";
import { ApplyButton } from "@/components/ApplyButton";
import { DataTable } from "@/components/DataTable";
import { MethodologyPanel } from "@/components/MethodologyPanel";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectOption } from "@/components/ui/select";
import { fetchApi } from "@/lib/api";
import { fmt, daysAgo, cn } from "@/lib/utils";

export const problematicRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/problematic",
  component: ProblematicPage,
});

interface DailyEntry { date: string; avg_delay: number; n: number; }
interface Offender {
  train_no: string; station: string; days_seen: number; pct_late: number;
  avg_delay: string; max_delay: string; total_stops?: number;
  relation?: string; operator?: string; daily?: DailyEntry[];
}
interface ProblematicData { n_pairs: number; n_offenders: number; offenders: Offender[]; error?: string; }

// Distinct colors for relations
const RELATION_COLORS = [
  "#e31a1c", "#ff7f00", "#2557e6", "#33a02c", "#6a3d9a",
  "#b15928", "#a6cee3", "#fb9a99", "#fdbf6f", "#cab2d6",
  "#ffff99", "#1f78b4", "#b2df8a", "#e78ac3", "#66c2a5",
];

function ProblematicPage() {
  const [startDate, setStartDate] = useState(daysAgo(14));
  const [endDate, setEndDate] = useState(daysAgo(1));
  const [lateThreshold, setLateThreshold] = useState(5.0);
  const [minDays, setMinDays] = useState(3);
  const [delayFloor, setDelayFloor] = useState(0);
  const [delayCap, setDelayCap] = useState(30);
  const [selectedPair, setSelectedPair] = useState("");
  const [selectedIdx, setSelectedIdx] = useState<number | null>(null);
  const [queryParams, setQueryParams] = useState<Record<string, string | number | boolean> | null>(null);

  const { data, error, isFetching } = useQuery({
    queryKey: ["problematic", queryParams],
    queryFn: () => fetchApi<ProblematicData>("/problematic", queryParams!),
    enabled: !!queryParams,
  });

  const loadData = () => setQueryParams({ start: startDate, end: endDate, late_threshold: lateThreshold, min_days: minDays, delay_cap: delayCap });

  // Get unique relations for coloring
  const relationColorMap = useMemo(() => {
    if (!data?.offenders) return new Map<string, string>();
    const relations = [...new Set(data.offenders.map((o) => o.relation || "?"))];
    return new Map(relations.map((r, i) => [r, RELATION_COLORS[i % RELATION_COLORS.length]]));
  }, [data]);

  const scatterDataByRelation = useMemo(() => {
    if (!data?.offenders) return [];
    const byRelation = new Map<string, Offender[]>();
    for (const o of data.offenders) {
      const rel = o.relation || "?";
      if (!byRelation.has(rel)) byRelation.set(rel, []);
      byRelation.get(rel)!.push(o);
    }
    return Array.from(byRelation.entries()).map(([relation, offenders]) => ({
      relation,
      color: relationColorMap.get(relation) || "#888",
      data: offenders.map((o) => ({
        x: o.pct_late,
        y: parseFloat(o.avg_delay),
        z: o.total_stops || o.days_seen * 5,
        name: o.train_no + " @ " + o.station,
      })),
    }));
  }, [data, relationColorMap]);

  const maxStops = useMemo(() => {
    if (!data?.offenders) return 1;
    return Math.max(...data.offenders.map((o) => o.total_stops || 1), 1);
  }, [data]);

  // Day-by-day detail for selected pair
  const selectedDetail = useMemo(() => {
    if (!selectedPair || !data?.offenders) return null;
    return data.offenders.find((o) => `${o.train_no}@${o.station}` === selectedPair) ?? null;
  }, [selectedPair, data]);

  const pairOptions = useMemo(() => {
    if (!data?.offenders) return [];
    return data.offenders.slice(0, 200).map((o) => ({
      value: `${o.train_no}@${o.station}`,
      label: `${o.train_no} @ ${o.station} (${o.pct_late}%)`,
    }));
  }, [data]);

  // Selected offender from table row click
  const selectedOffender = useMemo(() => {
    if (selectedIdx === null || !data?.offenders) return null;
    return data.offenders[selectedIdx] ?? null;
  }, [selectedIdx, data]);

  const handleRowClick = (row: Offender) => {
    if (!data?.offenders) return;
    const idx = data.offenders.indexOf(row);
    setSelectedIdx(idx >= 0 ? idx : null);
  };

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
            <Label>Thresholds</Label>
            <div><span className="text-[10px] text-muted-foreground/60">Late threshold (min)</span><Input type="number" value={lateThreshold} min={1} max={30} step={0.5} onChange={(e) => setLateThreshold(+e.target.value)} className="h-8 text-xs" /></div>
            <div><span className="text-[10px] text-muted-foreground/60">Min days observed</span><Input type="number" value={minDays} min={1} max={30} onChange={(e) => setMinDays(+e.target.value)} className="h-8 text-xs" /></div>
            <div><span className="text-[10px] text-muted-foreground/60">Min delay (min)</span><Input type="number" value={delayFloor} min={0} max={120} onChange={(e) => setDelayFloor(+e.target.value)} className="h-8 text-xs" /></div>
            <div><span className="text-[10px] text-muted-foreground/60">Delay cap (min)</span><Input type="number" value={delayCap} min={1} max={120} onChange={(e) => setDelayCap(+e.target.value)} className="h-8 text-xs" /></div>
          </div>
          <ApplyButton loading={isFetching} onClick={loadData} label="Analyse" />
        </>
      }
    >
      {isFetching && <LoadingState message="Analysing train performance..." />}
      {!isFetching && !data && <EmptyState icon={AlertTriangle} message="Configure dates and click Analyse" />}

      {data && !data.error && !isFetching && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5 animate-slide-up">
            <MetricCard label="Train-Station Pairs" value={fmt(data.n_pairs)} />
            <MetricCard label="Repeat Offenders" value={fmt(data.n_offenders)} danger />
            <MetricCard label="Worst Train" value={data.offenders[0]?.train_no ?? "\u2014"} />
            <MetricCard label="Worst % Late" value={data.offenders[0]?.pct_late ?? 0} suffix="%" danger />
          </div>

          {scatterDataByRelation.length > 0 && (
            <div className="rounded-2xl border border-border/50 bg-card p-5 shadow-sm mb-4 animate-slide-up">
              <h3 className="text-sm font-semibold mb-1 text-foreground">Late Rate vs Average Delay</h3>
              <p className="text-[10px] text-muted-foreground mb-3">Color = train relation/line, bubble size = total stops observed</p>
              <ResponsiveContainer width="100%" height={360}>
                <ScatterChart margin={{ top: 10, right: 20, bottom: 20, left: 10 }}>
                  <CartesianGrid strokeDasharray="3 3" className="stroke-border/50" />
                  <XAxis dataKey="x" name="% Late" type="number" unit="%" tick={{ fontSize: 11 }} label={{ value: "% Late", position: "insideBottom", offset: -10, fontSize: 12 }} />
                  <YAxis dataKey="y" name="Avg Delay (min)" type="number" unit="m" tick={{ fontSize: 11 }} label={{ value: "Avg Delay (min)", angle: -90, position: "insideLeft", offset: 5, fontSize: 12 }} />
                  <ZAxis dataKey="z" type="number" range={[20, 400]} domain={[0, maxStops]} />
                  <Tooltip
                    cursor={{ strokeDasharray: "3 3" }}
                    content={({ active, payload }) => {
                      if (!active || !payload?.length) return null;
                      const d = payload[0].payload;
                      return (
                        <div className="rounded-xl border border-border/50 bg-card px-3 py-2 text-xs shadow-lg">
                          <p className="font-semibold">{d.name}</p>
                          <p className="text-muted-foreground">Late: {d.x}% | Avg: {d.y}m | Stops: {d.z}</p>
                        </div>
                      );
                    }}
                  />
                  <Legend wrapperStyle={{ fontSize: 10 }} />
                  {scatterDataByRelation.map(({ relation, color, data: rData }) => (
                    <Scatter key={relation} name={relation} data={rData} fill={color + "88"} stroke={color} />
                  ))}
                </ScatterChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Detail card for selected offender from table click */}
          {selectedOffender && (
            <div className="rounded-2xl border border-primary/20 bg-primary/5 p-5 shadow-sm mb-4 animate-slide-up">
              <div className="flex items-start justify-between mb-3">
                <h3 className="text-sm font-semibold text-foreground">Selected Offender Detail</h3>
                <button
                  onClick={() => setSelectedIdx(null)}
                  className="inline-flex items-center justify-center h-7 w-7 rounded-lg border border-border/50 bg-background/80 text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-6 gap-3">
                <div>
                  <span className="text-[10px] text-muted-foreground/60 block">Train</span>
                  <span className="text-sm font-mono font-semibold text-foreground">{selectedOffender.train_no}</span>
                </div>
                <div>
                  <span className="text-[10px] text-muted-foreground/60 block">Station</span>
                  <span className="text-sm font-medium text-foreground">{selectedOffender.station}</span>
                </div>
                <div>
                  <span className="text-[10px] text-muted-foreground/60 block">Days Seen</span>
                  <span className="text-sm font-semibold tabular-nums text-foreground">{selectedOffender.days_seen}</span>
                </div>
                <div>
                  <span className="text-[10px] text-muted-foreground/60 block">% Late</span>
                  <span className={cn("text-sm font-semibold tabular-nums", selectedOffender.pct_late > 75 ? "text-destructive" : selectedOffender.pct_late > 50 ? "text-orange-500" : "text-foreground")}>
                    {selectedOffender.pct_late}%
                  </span>
                </div>
                <div>
                  <span className="text-[10px] text-muted-foreground/60 block">Avg Delay</span>
                  <span className="text-sm font-semibold tabular-nums text-foreground">{selectedOffender.avg_delay}m</span>
                </div>
                <div>
                  <span className="text-[10px] text-muted-foreground/60 block">Max Delay</span>
                  <span className="text-sm font-semibold tabular-nums text-foreground">{selectedOffender.max_delay}m</span>
                </div>
              </div>
            </div>
          )}

          {/* Day-by-day detail view */}
          <div className="rounded-2xl border border-border/50 bg-card p-5 shadow-sm mb-4 animate-slide-up">
            <h3 className="text-sm font-semibold mb-3 text-foreground">Day-by-Day Detail</h3>
            <div className="mb-3">
              <Select value={selectedPair} onValueChange={setSelectedPair}>
                <SelectOption value="">Select a train-station pair...</SelectOption>
                {pairOptions.map((o) => <SelectOption key={o.value} value={o.value}>{o.label}</SelectOption>)}
              </Select>
            </div>
            {selectedDetail?.daily && selectedDetail.daily.length > 0 ? (
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={selectedDetail.daily} margin={{ top: 4, right: 8, bottom: 4, left: 8 }}>
                  <XAxis dataKey="date" tick={{ fontSize: 9 }} angle={-30} textAnchor="end" height={50} />
                  <YAxis tick={{ fontSize: 10 }} label={{ value: "Avg Delay (min)", angle: -90, position: "insideLeft", offset: 5, fontSize: 10 }} />
                  <Tooltip
                    contentStyle={{ fontSize: 12, borderRadius: 12, border: '1px solid var(--color-border)' }}
                    formatter={(value: number) => [`${value} min`, "Avg delay"]}
                  />
                  <ReferenceLine y={lateThreshold} stroke="oklch(0.65 0.20 25)" strokeDasharray="4 4" label={{ value: "Late threshold", fontSize: 9, fill: "oklch(0.65 0.20 25)" }} />
                  <Bar
                    dataKey="avg_delay"
                    radius={[4, 4, 0, 0]}
                    fill="oklch(0.55 0.15 250)"
                    label={false}
                  />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <p className="text-xs text-muted-foreground">Select a pair above to see its daily delay breakdown.</p>
            )}
          </div>

          <DataTable
            title="Repeat Offenders (sorted by % late)"
            keyFn={(_, i) => i}
            data={data.offenders}
            maxRows={100}
            onRowClick={handleRowClick}
            columns={[
              { header: "Train", accessor: (o) => <span className="font-mono font-medium">{o.train_no}</span> },
              { header: "Station", accessor: (o) => <span className="truncate max-w-[140px] block text-muted-foreground">{o.station}</span> },
              { header: "Relation", accessor: (o) => (
                <span className="flex items-center gap-1">
                  <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: relationColorMap.get(o.relation || "?") || "#888" }} />
                  <span className="truncate max-w-[80px] text-muted-foreground text-[10px]">{o.relation || "?"}</span>
                </span>
              ) },
              { header: "Days", accessor: (o) => <span className="text-muted-foreground">{o.days_seen}</span>, align: "right" },
              {
                header: "% Late",
                accessor: (o) => (
                  <div className="flex items-center justify-end gap-2">
                    <div className="w-16 h-1.5 rounded-full bg-muted overflow-hidden">
                      <div
                        className={cn(
                          "h-full rounded-full transition-all",
                          o.pct_late > 75 ? "bg-destructive" : o.pct_late > 50 ? "bg-orange-500" : "bg-primary/60",
                        )}
                        style={{ width: `${Math.min(o.pct_late, 100)}%` }}
                      />
                    </div>
                    <span className={cn("font-semibold tabular-nums w-10 text-right", o.pct_late > 75 ? "text-destructive" : o.pct_late > 50 ? "text-orange-500" : "text-muted-foreground")}>
                      {o.pct_late}%
                    </span>
                  </div>
                ),
                align: "right",
              },
              { header: "Avg", accessor: (o) => <span className="text-muted-foreground">{o.avg_delay}m</span>, align: "right" },
              { header: "Max", accessor: (o) => <span className="text-muted-foreground">{o.max_delay}m</span>, align: "right" },
            ]}
          />

          <div className="mt-4">
            <MethodologyPanel>
              <p>For each date in the range, all punctuality records are grouped by (train number, station) pairs. Per pair per day: average delay, max delay, and percentage of late stops are computed.</p>
              <p>These are then aggregated across days. Pairs observed fewer than the minimum days threshold are excluded. The scatter plot colors represent different train relations/lines, and bubble size is proportional to total stops observed. Select a pair to see its day-by-day delay trend.</p>
            </MethodologyPanel>
          </div>
        </>
      )}

      {(error || data?.error) && <ErrorAlert message={data?.error ?? (error as Error).message} />}
    </Layout>
  );
}
