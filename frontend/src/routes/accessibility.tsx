import { createRoute } from "@tanstack/react-router";
import { useState, useMemo, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { BitmapLayer } from "@deck.gl/layers";
import type { Layer } from "@deck.gl/core";
import { Footprints } from "lucide-react";
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
import { Switch } from "@/components/ui/switch";
import { Select, SelectOption } from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { fetchApi } from "@/lib/api";
import { fmt, daysAgo } from "@/lib/utils";
import { stationLayer } from "@/lib/layers";
import { tooltipBox } from "@/lib/tooltip";

export const accessibilityRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/accessibility",
  component: AccessibilityPage,
});

const ALL_OPS = ["SNCB", "De Lijn", "STIB", "TEC"];
const OP_COLORS: Record<string, [number, number, number, number]> = {
  SNCB: [8, 69, 148, 200],
  "De Lijn": [255, 215, 0, 200],
  STIB: [227, 6, 19, 200],
  TEC: [0, 165, 80, 200],
};

type ViewMode = "gradient" | "stations";

interface StopEntry { name: string; lat: number; lon: number; operator: string; }

interface AccessibilityData {
  n_stops: number; median_time: number; mean_time: number; p95_time: number;
  pct_5min?: number; pct_10min: number; pct_15min?: number; pct_20min?: number; pct_30min?: number;
  image_b64?: string; stops?: StopEntry[]; error?: string;
}

function AccessibilityPage() {
  const [destOperators, setDestOperators] = useState(["SNCB"]);
  const [useFeeder, setUseFeeder] = useState(true);
  const [feederOperators, setFeederOperators] = useState(["De Lijn", "STIB", "TEC"]);
  const [feederDepStart, setFeederDepStart] = useState(7);
  const [feederDepEnd, setFeederDepEnd] = useState(9);
  const [feederMaxTime, setFeederMaxTime] = useState(60);
  const [transport, setTransport] = useState("Walk");
  const [maxTime, setMaxTime] = useState(200);
  const [resolution, setResolution] = useState(200);
  const [targetDate, setTargetDate] = useState(daysAgo(1));
  const [viewMode, setViewMode] = useState<ViewMode>("gradient");
  const [queryParams, setQueryParams] = useState<Record<string, string | number | boolean> | null>(null);
  const mapRef = useRef<DeckMapRef>(null);

  const { data, error, isFetching } = useQuery({
    queryKey: ["accessibility", queryParams],
    queryFn: () => fetchApi<AccessibilityData>("/accessibility", queryParams!),
    enabled: !!queryParams,
  });

  const loadData = () => setQueryParams({
    dest_operators: destOperators.join(","), use_feeder: useFeeder,
    feeder_operators: feederOperators.join(","), feeder_dep_start: feederDepStart,
    feeder_dep_end: feederDepEnd, feeder_max_time: feederMaxTime,
    transport, max_time: maxTime, resolution, target_date: targetDate,
  });

  const toggleList = (list: string[], setList: (v: string[]) => void, item: string) =>
    setList(list.includes(item) ? list.filter((o) => o !== item) : [...list, item]);

  const stopsByOp = useMemo(() => {
    if (!data?.stops) return new Map<string, number>();
    const map = new Map<string, number>();
    for (const s of data.stops) {
      map.set(s.operator, (map.get(s.operator) || 0) + 1);
    }
    return map;
  }, [data]);

  const opTableData = useMemo(() => {
    return Array.from(stopsByOp.entries()).map(([op, count]) => ({ operator: op, count })).sort((a, b) => b.count - a.count);
  }, [stopsByOp]);

  const layers = useMemo<Layer[]>(() => {
    if (!data || data.error) return [];

    if (viewMode === "gradient" && data.image_b64) {
      return [
        new BitmapLayer({
          id: "heatmap",
          image: "data:image/png;base64," + data.image_b64,
          bounds: [2.55, 49.5, 6.41, 51.51],
          opacity: 0.75,
        }),
      ] as Layer[];
    }

    if (viewMode === "stations" && data.stops?.length) {
      return [
        stationLayer("accessibility-stops", data.stops, {
          positionFn: (d) => [d.lon, d.lat],
          radiusFn: () => 3,
          colorFn: (d) => OP_COLORS[d.operator] || [51, 51, 51, 160],
          radiusMinPixels: 2,
          radiusMaxPixels: 8,
          pickable: true,
        }),
      ] as Layer[];
    }

    return [];
  }, [data, viewMode]);

  return (
    <Layout
      sidebar={
        <>
          <div>
            <Label>Destination Stops</Label>
            <div className="space-y-1.5 mt-1.5">
              {ALL_OPS.map((op) => (
                <div key={op} className="flex items-center justify-between text-xs text-foreground/60">
                  <span className="flex items-center gap-1.5">
                    <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: `rgba(${OP_COLORS[op]?.slice(0, 3).join(",")},1)` }} />
                    {op}
                  </span>
                  <Switch checked={destOperators.includes(op)} onCheckedChange={() => toggleList(destOperators, setDestOperators, op)} />
                </div>
              ))}
            </div>
          </div>

          <div className="border-t border-border/40 pt-3 mt-3">
            <Label>View</Label>
            <Tabs value={viewMode} onValueChange={(v) => setViewMode(v as ViewMode)} className="mt-1.5">
              <TabsList className="w-full">
                <TabsTrigger value="gradient" className="flex-1">Gradient</TabsTrigger>
                <TabsTrigger value="stations" className="flex-1">Stations</TabsTrigger>
              </TabsList>
            </Tabs>
          </div>

          <div className="border-t border-border/40 pt-3 mt-3">
            <Label>Feeder Transit</Label>
            <div className="flex items-center justify-between text-xs text-foreground/60 mt-1.5 mb-2">
              <span>Use public transport to reach stop</span>
              <Switch checked={useFeeder} onCheckedChange={setUseFeeder} />
            </div>
            {useFeeder && (
              <div className="space-y-2 pl-1">
                <div>
                  <span className="text-[10px] text-muted-foreground/60">Feeder operators</span>
                  <div className="space-y-1.5 mt-1">
                    {ALL_OPS.filter((o) => !destOperators.includes(o)).map((op) => (
                      <div key={op} className="flex items-center justify-between text-xs text-foreground/60">
                        <span>{op}</span>
                        <Switch checked={feederOperators.includes(op)} onCheckedChange={() => toggleList(feederOperators, setFeederOperators, op)} />
                      </div>
                    ))}
                  </div>
                </div>
                <div>
                  <span className="text-[10px] text-muted-foreground/60">Departure window</span>
                  <div className="flex items-center gap-2"><Input type="number" value={feederDepStart} min={0} max={24} onChange={(e) => setFeederDepStart(+e.target.value)} className="w-16 h-8 text-xs" /><span className="text-xs text-muted-foreground/50">to</span><Input type="number" value={feederDepEnd} min={0} max={24} onChange={(e) => setFeederDepEnd(+e.target.value)} className="w-16 h-8 text-xs" /></div>
                </div>
                <div><span className="text-[10px] text-muted-foreground/60">Max transit time (min)</span><Input type="number" value={feederMaxTime} min={5} max={120} step={5} onChange={(e) => setFeederMaxTime(+e.target.value)} className="h-8 text-xs" /></div>
              </div>
            )}
          </div>

          <div className="border-t border-border/40 pt-3 mt-3 space-y-2">
            <Label>Last Mile</Label>
            <Tabs value={transport} onValueChange={setTransport}>
              <TabsList className="w-full">
                <TabsTrigger value="Walk" className="flex-1">Walk</TabsTrigger>
                <TabsTrigger value="Bike" className="flex-1">Bike</TabsTrigger>
                <TabsTrigger value="Car" className="flex-1">Car</TabsTrigger>
              </TabsList>
            </Tabs>
            <div><span className="text-[10px] text-muted-foreground/60">Max total time (min)</span><Input type="number" value={maxTime} min={5} max={300} step={5} onChange={(e) => setMaxTime(+e.target.value)} className="h-8 text-xs" /></div>
            <div>
              <span className="text-[10px] text-muted-foreground/60">Resolution</span>
              <Select value={String(resolution)} onValueChange={(v) => setResolution(+v)}>
                <SelectOption value="100">100 (fast)</SelectOption>
                <SelectOption value="150">150</SelectOption>
                <SelectOption value="200">200 (default)</SelectOption>
                <SelectOption value="300">300 (sharp)</SelectOption>
              </Select>
            </div>
            <div><span className="text-[10px] text-muted-foreground/60">Date</span><Input type="date" value={targetDate} onChange={(e) => setTargetDate(e.target.value)} className="h-8 text-xs" /></div>
          </div>
          <ApplyButton loading={isFetching} onClick={loadData} label="Compute" />
        </>
      }
    >
      {isFetching && <LoadingState message="Computing accessibility grid..." />}
      {!isFetching && !data && <EmptyState icon={Footprints} message="Configure settings and click Compute" />}

      {data && !data.error && !isFetching && (
        <>
          {/* Summary stats */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4 animate-slide-up">
            <MetricCard label="Stops" value={fmt(data.n_stops)} />
            <MetricCard label="Median" value={data.median_time} suffix=" min" />
            <MetricCard label="Mean" value={data.mean_time} suffix=" min" />
            <MetricCard label="95th pct" value={data.p95_time} suffix=" min" />
          </div>

          {/* Coverage thresholds */}
          <div className="grid grid-cols-3 md:grid-cols-5 gap-3 mb-5 animate-slide-up">
            {data.pct_5min != null && <MetricCard label="<= 5 min" value={data.pct_5min} suffix="%" />}
            <MetricCard label="<= 10 min" value={data.pct_10min} suffix="%" />
            {data.pct_15min != null && <MetricCard label="<= 15 min" value={data.pct_15min} suffix="%" />}
            {data.pct_20min != null && <MetricCard label="<= 20 min" value={data.pct_20min} suffix="%" />}
            {data.pct_30min != null && <MetricCard label="<= 30 min" value={data.pct_30min} suffix="%" />}
          </div>

          <DeckMap ref={mapRef} layers={layers} className="h-[calc(100vh-20rem)]"
            getTooltip={({ object, layer }) => {
              if (!object || !layer) return null;
              if (layer.id === "accessibility-stops") {
                return tooltipBox(`<b>${object.name}</b><br/>Operator: ${object.operator}`);
              }
              return null;
            }}
          />

          {/* Operator legend + stops table for stations view */}
          {viewMode === "stations" && (
            <div className="mt-4 space-y-3">
              <div className="flex gap-4 text-[10px] text-muted-foreground">
                {ALL_OPS.map((op) => {
                  const count = stopsByOp.get(op) || 0;
                  if (!count) return null;
                  return (
                    <span key={op} className="flex items-center gap-1">
                      <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: `rgba(${OP_COLORS[op]?.slice(0, 3).join(",")},1)` }} />
                      {op} ({fmt(count)})
                    </span>
                  );
                })}
              </div>
              {opTableData.length > 0 && (
                <DataTable
                  title="Stops per Operator"
                  keyFn={(d) => d.operator}
                  data={opTableData}
                  columns={[
                    { header: "Operator", accessor: (d) => (
                      <span className="flex items-center gap-2 font-medium">
                        <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: `rgba(${OP_COLORS[d.operator]?.slice(0, 3).join(",")},1)` }} />
                        {d.operator}
                      </span>
                    )},
                    { header: "Stops", accessor: (d) => <span className="font-semibold text-primary">{fmt(d.count)}</span>, align: "right" },
                  ]}
                />
              )}
            </div>
          )}
        </>
      )}

      {(error || data?.error) && <ErrorAlert message={data?.error ?? (error as Error).message} />}
    </Layout>
  );
}
