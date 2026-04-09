import { createRoute } from "@tanstack/react-router";
import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";
import { ScatterChart, Scatter, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";
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
import { fetchApi } from "@/lib/api";
import { fmt, daysAgo, cn } from "@/lib/utils";

export const problematicRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/problematic",
  component: ProblematicPage,
});

interface Offender { train_no: string; station: string; days_seen: number; pct_late: number; avg_delay: string; max_delay: string; }
interface ProblematicData { n_pairs: number; n_offenders: number; offenders: Offender[]; error?: string; }

function ProblematicPage() {
  const [startDate, setStartDate] = useState(daysAgo(14));
  const [endDate, setEndDate] = useState(daysAgo(1));
  const [lateThreshold, setLateThreshold] = useState(5.0);
  const [minDays, setMinDays] = useState(3);
  const [delayFloor, setDelayFloor] = useState(0);
  const [delayCap, setDelayCap] = useState(30);
  const [queryParams, setQueryParams] = useState<Record<string, string | number | boolean> | null>(null);

  const { data, error, isFetching } = useQuery({
    queryKey: ["problematic", queryParams],
    queryFn: () => fetchApi<ProblematicData>("/problematic", queryParams!),
    enabled: !!queryParams,
  });

  const loadData = () => setQueryParams({ start: startDate, end: endDate, late_threshold: lateThreshold, min_days: minDays, delay_cap: delayCap });

  const scatterData = useMemo(() => {
    if (!data?.offenders) return [];
    return data.offenders.map((o) => ({
      x: o.pct_late,
      y: parseFloat(o.avg_delay),
      name: o.train_no + " @ " + o.station,
      z: o.days_seen,
    }));
  }, [data]);

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const renderDot = (props: any) => {
    const r = Math.max(3, Math.min(14, 3 + (props.payload.z / 5)));
    return <circle cx={props.cx} cy={props.cy} r={r} fill="oklch(0.50 0.16 260)" fillOpacity={0.6} stroke="oklch(0.50 0.16 260)" strokeWidth={1} />;
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

          {scatterData.length > 0 && (
            <div className="rounded-2xl border border-border/50 bg-card p-5 shadow-sm mb-4 animate-slide-up">
              <h3 className="text-sm font-semibold mb-4 text-foreground">Late Rate vs Average Delay</h3>
              <ResponsiveContainer width="100%" height={360}>
                <ScatterChart margin={{ top: 10, right: 20, bottom: 20, left: 10 }}>
                  <CartesianGrid strokeDasharray="3 3" className="stroke-border/50" />
                  <XAxis dataKey="x" name="% Late" type="number" unit="%" tick={{ fontSize: 11 }} label={{ value: "% Late", position: "insideBottom", offset: -10, fontSize: 12 }} />
                  <YAxis dataKey="y" name="Avg Delay (min)" type="number" unit="m" tick={{ fontSize: 11 }} label={{ value: "Avg Delay (min)", angle: -90, position: "insideLeft", offset: 5, fontSize: 12 }} />
                  <Tooltip
                    cursor={{ strokeDasharray: "3 3" }}
                    content={({ active, payload }) => {
                      if (!active || !payload?.length) return null;
                      const d = payload[0].payload;
                      return (
                        <div className="rounded-xl border border-border/50 bg-card px-3 py-2 text-xs shadow-lg">
                          <p className="font-semibold">{d.name}</p>
                          <p className="text-muted-foreground">Late: {d.x}% | Avg: {d.y}m | Days: {d.z}</p>
                        </div>
                      );
                    }}
                  />
                  <Scatter data={scatterData} fill="oklch(0.50 0.16 260)" fillOpacity={0.6} shape={renderDot} />
                </ScatterChart>
              </ResponsiveContainer>
            </div>
          )}

          <DataTable
            title="Repeat Offenders (sorted by % late)"
            keyFn={(_, i) => i}
            data={data.offenders}
            maxRows={100}
            columns={[
              { header: "Train", accessor: (o) => <span className="font-mono font-medium">{o.train_no}</span> },
              { header: "Station", accessor: (o) => <span className="truncate max-w-[180px] block text-muted-foreground">{o.station}</span> },
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
              { header: "Avg Delay", accessor: (o) => <span className="text-muted-foreground">{o.avg_delay}m</span>, align: "right" },
              { header: "Max Delay", accessor: (o) => <span className="text-muted-foreground">{o.max_delay}m</span>, align: "right" },
            ]}
          />
        </>
      )}

      {(error || data?.error) && <ErrorAlert message={data?.error ?? (error as Error).message} />}
    </Layout>
  );
}
