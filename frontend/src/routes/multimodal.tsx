import { createRoute } from "@tanstack/react-router";
import { useState, useMemo, useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { ScatterplotLayer } from "@deck.gl/layers";
import type { Layer } from "@deck.gl/core";
import { Bus } from "lucide-react";
import { rootRoute } from "./__root";
import { Layout } from "@/components/Layout";
import { MetricCard } from "@/components/MetricCard";
import { LoadingState } from "@/components/LoadingState";
import { EmptyState } from "@/components/EmptyState";
import { ErrorAlert } from "@/components/ErrorAlert";
import { ApplyButton } from "@/components/ApplyButton";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Switch } from "@/components/ui/switch";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { DeckMap, type DeckMapRef } from "@/components/DeckMap";
import { colorToRGBA, heatmapLayer, choroplethLayer } from "@/lib/layers";
import { fetchApi } from "@/lib/api";
import { fmt, today } from "@/lib/utils";
import { aggregateByProvince, buildChoroplethGeoJSON, buildRegionGeoJSON, getRegion } from "@/lib/geo";

export const multimodalRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/multimodal",
  component: MultimodalPage,
});

interface MultimodalData {
  n_reachable: number; avg_duration: number; operators_used: number; geocoded_address: string;
  origin?: { lat: number; lon: number };
  stations?: { name: string; lat: number; lon: number; duration: number; operator: string }[];
  error?: string;
}

type ViewMode = "stations" | "gradient" | "provinces" | "regions";

const ALL_OPS = ["SNCB", "De Lijn", "STIB", "TEC"];
const OP_COLORS: Record<string, [number, number, number, number]> = {
  SNCB: [8, 69, 148, 200],
  "De Lijn": [255, 215, 0, 200],
  STIB: [227, 6, 19, 200],
  TEC: [0, 165, 80, 200],
};

function MultimodalPage() {
  const [selectedOps, setSelectedOps] = useState(ALL_OPS);
  const [direction, setDirection] = useState<"from" | "to">("from");
  const [timeBudget, setTimeBudget] = useState(1.5);
  const [depStart, setDepStart] = useState(7);
  const [depEnd, setDepEnd] = useState(9);
  const [maxTransfers, setMaxTransfers] = useState(3);
  const [lastMile, setLastMile] = useState("Walk");
  const [travelDate, setTravelDate] = useState(today());
  const [transferDist, setTransferDist] = useState(400);
  const [maxWalk, setMaxWalk] = useState(1.5);
  const [viewMode, setViewMode] = useState<ViewMode>("stations");
  const [address, setAddress] = useState("");
  const [queryParams, setQueryParams] = useState<Record<string, string | number | boolean> | null>(null);
  const mapRef = useRef<DeckMapRef>(null);

  const { data, error, isFetching } = useQuery({
    queryKey: ["multimodal", queryParams],
    queryFn: () => fetchApi<MultimodalData>("/multimodal", queryParams!),
    enabled: !!queryParams,
  });

  const { data: geoData } = useQuery({
    queryKey: ["provinces"],
    queryFn: () => fetchApi<any>("/provinces"),
  });

  const loadData = () => {
    if (!address) return;
    setQueryParams({
      address, operators: selectedOps.join(","), direction, time_budget: timeBudget,
      dep_start: depStart, dep_end: depEnd, max_transfers: maxTransfers, last_mile: lastMile, travel_date: travelDate,
    });
  };

  const toggleOp = (op: string) => setSelectedOps((prev) => prev.includes(op) ? prev.filter((o) => o !== op) : [...prev, op]);

  useEffect(() => {
    if (data?.origin) {
      mapRef.current?.flyTo({ longitude: data.origin.lon, latitude: data.origin.lat, zoom: 11 });
    }
  }, [data]);

  const layers = useMemo((): Layer[] => {
    if (!data || data.error) return [];

    const maxDur = timeBudget * 60;

    if (viewMode === "provinces" && geoData && data.stations?.length) {
      const byProvince = aggregateByProvince(
        data.stations, geoData,
        (d) => d.lon, (d) => d.lat, (d) => d.duration,
      );
      const valueMap = new Map<string, number>();
      for (const [name, agg] of byProvince) valueMap.set(name, agg.avg);
      const maxVal = Math.max(...valueMap.values(), 1);
      const enriched = buildChoroplethGeoJSON(geoData, valueMap);

      return [choroplethLayer("province-choropleth", enriched, {
        valueFn: (f) => f.properties._value,
        colorFn: (f) => colorToRGBA(f.properties._value / maxVal, 160),
        pickable: true,
      })] as Layer[];
    }

    if (viewMode === "regions" && geoData && data.stations?.length) {
      const byProvince = aggregateByProvince(
        data.stations, geoData,
        (d) => d.lon, (d) => d.lat, (d) => d.duration,
      );
      const regionAgg = new Map<string, { sum: number; count: number }>();
      for (const [province, agg] of byProvince) {
        const region = getRegion(province);
        const existing = regionAgg.get(region);
        if (existing) {
          existing.sum += agg.sum;
          existing.count += agg.count;
        } else {
          regionAgg.set(region, { sum: agg.sum, count: agg.count });
        }
      }
      const valueMap = new Map<string, number>();
      for (const [region, agg] of regionAgg) valueMap.set(region, agg.sum / agg.count);
      const maxVal = Math.max(...valueMap.values(), 1);
      const regionGeo = buildRegionGeoJSON(geoData, valueMap);

      return [choroplethLayer("region-choropleth", regionGeo, {
        valueFn: (f) => f.properties._value,
        colorFn: (f) => colorToRGBA(f.properties._value / maxVal, 160),
        pickable: true,
      })] as Layer[];
    }

    if (viewMode === "gradient") {
      const result: Layer[] = [];

      if (data.stations?.length) {
        result.push(
          heatmapLayer("multimodal-heat", data.stations, {
            positionFn: (d) => [d.lon, d.lat],
            weightFn: (d) => Math.max(0, 1 - d.duration / maxDur),
            radiusPixels: 40,
            intensity: 2,
            threshold: 0.03,
          }),
        );
      }

      if (data.origin) {
        result.push(
          new ScatterplotLayer({
            id: "multimodal-origin-gradient",
            data: [data.origin],
            getPosition: (d) => [d.lon, d.lat],
            getRadius: 8,
            getFillColor: [227, 26, 28, 230],
            radiusMinPixels: 7,
            radiusMaxPixels: 14,
            pickable: true,
          }),
        );
      }

      return result;
    }

    // Stations view
    const result: Layer[] = [];

    if (data.stations?.length) {
      result.push(
        new ScatterplotLayer({
          id: "multimodal-stations",
          data: data.stations,
          getPosition: (d) => [d.lon, d.lat],
          getRadius: 4,
          getFillColor: (d) => OP_COLORS[d.operator] || [51, 51, 51, 200],
          radiusMinPixels: 4,
          radiusMaxPixels: 8,
          pickable: true,
          updateTriggers: { getFillColor: [selectedOps] },
        }),
      );
    }

    if (data.origin) {
      result.push(
        new ScatterplotLayer({
          id: "multimodal-walk-circle",
          data: [data.origin],
          getPosition: (d) => [d.lon, d.lat],
          getRadius: maxWalk * 1000,
          radiusUnits: "meters" as const,
          filled: false,
          stroked: true,
          getLineColor: [227, 26, 28, 80],
          lineWidthMinPixels: 1,
          updateTriggers: { getRadius: [maxWalk] },
        }),
      );

      result.push(
        new ScatterplotLayer({
          id: "multimodal-origin",
          data: [data.origin],
          getPosition: (d) => [d.lon, d.lat],
          getRadius: 8,
          getFillColor: [227, 26, 28, 230],
          radiusMinPixels: 7,
          radiusMaxPixels: 14,
          pickable: true,
        }),
      );
    }

    return result;
  }, [data, geoData, viewMode, timeBudget, maxWalk, selectedOps]);

  return (
    <Layout
      sidebar={
        <>
          <div>
            <Label>Operators</Label>
            <div className="space-y-1.5 mt-1.5">
              {ALL_OPS.map((op) => (
                <div key={op} className="flex items-center justify-between text-xs text-foreground/60">
                  <span>{op}</span>
                  <Switch checked={selectedOps.includes(op)} onCheckedChange={() => toggleOp(op)} />
                </div>
              ))}
            </div>
          </div>

          <div className="border-t border-border/40 pt-3 mt-3">
            <Label>View</Label>
            <Tabs value={viewMode} onValueChange={(v) => setViewMode(v as ViewMode)} className="mt-1.5">
              <TabsList className="w-full">
                <TabsTrigger value="stations" className="flex-1">Stations</TabsTrigger>
                <TabsTrigger value="gradient" className="flex-1">Gradient</TabsTrigger>
                <TabsTrigger value="provinces" className="flex-1">Provinces</TabsTrigger>
                <TabsTrigger value="regions" className="flex-1">Regions</TabsTrigger>
              </TabsList>
            </Tabs>
          </div>

          <div className="border-t border-border/40 pt-3 mt-3 space-y-2">
            <Label>Travel Settings</Label>
            <div>
              <span className="text-[10px] text-muted-foreground/60">Direction</span>
              <Tabs value={direction} onValueChange={(v) => setDirection(v as "from" | "to")}>
                <TabsList className="w-full">
                  <TabsTrigger value="from" className="flex-1">From</TabsTrigger>
                  <TabsTrigger value="to" className="flex-1">To</TabsTrigger>
                </TabsList>
              </Tabs>
            </div>
            <div><span className="text-[10px] text-muted-foreground/60">Time budget (hours)</span><Input type="number" value={timeBudget} min={0.5} max={4} step={0.5} onChange={(e) => setTimeBudget(+e.target.value)} className="h-8 text-xs" /></div>
            <div>
              <span className="text-[10px] text-muted-foreground/60">Departure window</span>
              <div className="flex items-center gap-2"><Input type="number" value={depStart} min={0} max={24} onChange={(e) => setDepStart(+e.target.value)} className="w-16 h-8 text-xs" /><span className="text-xs text-muted-foreground/50">to</span><Input type="number" value={depEnd} min={0} max={24} onChange={(e) => setDepEnd(+e.target.value)} className="w-16 h-8 text-xs" /></div>
            </div>
            <div><span className="text-[10px] text-muted-foreground/60">Max transfers</span><Input type="number" value={maxTransfers} min={0} max={5} onChange={(e) => setMaxTransfers(+e.target.value)} className="h-8 text-xs" /></div>
            <div><span className="text-[10px] text-muted-foreground/60">Transfer distance (m)</span><Input type="number" value={transferDist} min={100} max={1000} step={100} onChange={(e) => setTransferDist(+e.target.value)} className="h-8 text-xs" /></div>
            <div><span className="text-[10px] text-muted-foreground/60">Max walk (km)</span><Input type="number" value={maxWalk} min={0.5} max={10} step={0.5} onChange={(e) => setMaxWalk(+e.target.value)} className="h-8 text-xs" /></div>
            <div>
              <span className="text-[10px] text-muted-foreground/60">Last-mile mode</span>
              <Tabs value={lastMile} onValueChange={setLastMile}>
                <TabsList className="w-full">
                  <TabsTrigger value="Walk" className="flex-1">Walk</TabsTrigger>
                  <TabsTrigger value="Bike" className="flex-1">Bike</TabsTrigger>
                  <TabsTrigger value="Car" className="flex-1">Car</TabsTrigger>
                </TabsList>
              </Tabs>
            </div>
            <div><span className="text-[10px] text-muted-foreground/60">Date</span><Input type="date" value={travelDate} onChange={(e) => setTravelDate(e.target.value)} className="h-8 text-xs" /></div>
          </div>
          <ApplyButton loading={isFetching} onClick={loadData} label="Compute" />
        </>
      }
    >
      <div className="mb-5">
        <span className="text-[10px] text-muted-foreground/60 uppercase tracking-widest font-medium block mb-1.5">Address</span>
        <Input value={address} onChange={(e) => setAddress(e.target.value)} onKeyDown={(e) => e.key === "Enter" && loadData()} placeholder="e.g. Rue de la Loi 1, Brussels" className="max-w-md text-sm" />
      </div>

      {isFetching && <LoadingState message="Computing multimodal routes..." />}
      {!isFetching && !data && <EmptyState icon={Bus} message="Enter an address and click Compute" />}

      {data && !data.error && !isFetching && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5 animate-slide-up">
            <MetricCard label="Reachable Stops" value={fmt(data.n_reachable)} />
            <MetricCard label="Avg Duration" value={fmt(data.avg_duration, 0)} suffix="min" />
            <MetricCard label="Operators Used" value={data.operators_used} />
            <MetricCard label="Address" value={data.geocoded_address} />
          </div>
          <DeckMap ref={mapRef} layers={layers} className="h-[calc(100vh-20rem)]" />
        </>
      )}

      {(error || data?.error) && <ErrorAlert message={data?.error ?? (error as Error).message} />}
    </Layout>
  );
}
