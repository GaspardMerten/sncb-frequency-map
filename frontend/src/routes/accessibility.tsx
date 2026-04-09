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
import { DeckMap, type DeckMapRef } from "@/components/DeckMap";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Switch } from "@/components/ui/switch";
import { Select, SelectOption } from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { fetchApi } from "@/lib/api";
import { fmt, daysAgo } from "@/lib/utils";

export const accessibilityRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/accessibility",
  component: AccessibilityPage,
});

const ALL_OPS = ["SNCB", "De Lijn", "STIB", "TEC"];

interface AccessibilityData {
  n_stops: number; median_time: number; mean_time: number; p95_time: number; pct_10min: number;
  image_b64?: string; error?: string;
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

  const layers = useMemo<Layer[]>(() => {
    if (!data || data.error || !data.image_b64) return [];
    return [
      new BitmapLayer({
        id: "heatmap",
        image: "data:image/png;base64," + data.image_b64,
        bounds: [2.55, 49.5, 6.41, 51.51],
        opacity: 0.75,
      }),
    ] as Layer[];
  }, [data]);

  return (
    <Layout
      sidebar={
        <>
          <div>
            <Label>Destination Stops</Label>
            <div className="space-y-1.5 mt-1.5">
              {ALL_OPS.map((op) => (
                <div key={op} className="flex items-center justify-between text-xs text-foreground/60">
                  <span>{op}</span>
                  <Switch checked={destOperators.includes(op)} onCheckedChange={() => toggleList(destOperators, setDestOperators, op)} />
                </div>
              ))}
            </div>
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
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-5 animate-slide-up">
            <MetricCard label="Stops" value={fmt(data.n_stops)} />
            <MetricCard label="Median" value={data.median_time} suffix="min" />
            <MetricCard label="Mean" value={data.mean_time} suffix="min" />
            <MetricCard label="95th pct" value={data.p95_time} suffix="min" />
            <MetricCard label="<= 10 min" value={data.pct_10min} suffix="%" />
          </div>
          <DeckMap ref={mapRef} layers={layers} className="h-[calc(100vh-16rem)]" />
        </>
      )}

      {(error || data?.error) && <ErrorAlert message={data?.error ?? (error as Error).message} />}
    </Layout>
  );
}
