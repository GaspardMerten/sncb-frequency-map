import { createRoute } from "@tanstack/react-router";
import { useState, useMemo, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { ScatterplotLayer } from "@deck.gl/layers";
import type { Layer } from "@deck.gl/core";
import { Timer, X } from "lucide-react";
import { rootRoute } from "./__root";
import { Layout } from "@/components/Layout";
import { FilterPanel, type Filters } from "@/components/FilterPanel";
import { MetricCard } from "@/components/MetricCard";
import { LoadingState } from "@/components/LoadingState";
import { EmptyState } from "@/components/EmptyState";
import { ErrorAlert } from "@/components/ErrorAlert";
import { ApplyButton } from "@/components/ApplyButton";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { DeckMap, type DeckMapRef } from "@/components/DeckMap";
import { colorToRGBA, heatmapLayer } from "@/lib/layers";
import { fetchApi } from "@/lib/api";
import { filterParams, fmt, daysAgo, today } from "@/lib/utils";

export const durationRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/duration",
  component: DurationPage,
});

interface DurationData {
  stations: { name: string; lat: number; lon: number; duration: number }[];
  dest_coords?: { name: string; lat: number; lon: number }[];
  avg_duration: number; min_duration: number; max_duration: number; error?: string;
}

type Aggregation = "average" | "min" | "max";
type TransportMode = "walk" | "bike" | "car";
type ViewMode = "stations" | "gradient";

const TRANSPORT_SPEEDS: Record<TransportMode, number> = {
  walk: 5,
  bike: 15,
  car: 50,
};

function DurationPage() {
  const [filters, setFilters] = useState<Filters>({
    startDate: daysAgo(7), endDate: today(), weekdays: [0, 1, 2, 3, 4],
    excludePub: false, excludeSch: false, useHour: false, hourStart: 7, hourEnd: 19,
  });
  const [direction, setDirection] = useState<"to" | "from">("to");
  const [timeBudget, setTimeBudget] = useState(3.0);
  const [depStart, setDepStart] = useState(7);
  const [depEnd, setDepEnd] = useState(9);
  const [maxTransfers, setMaxTransfers] = useState(3);
  const [aggregation, setAggregation] = useState<Aggregation>("average");
  const [transportMode, setTransportMode] = useState<TransportMode>("walk");
  const [viewMode, setViewMode] = useState<ViewMode>("stations");
  const [destSearch, setDestSearch] = useState("");
  const [selectedDests, setSelectedDests] = useState<string[]>(["Bruxelles-Central"]);
  const [queryParams, setQueryParams] = useState<Record<string, string | number | boolean> | null>(null);
  const mapRef = useRef<DeckMapRef>(null);

  const { data, error, isFetching } = useQuery({
    queryKey: ["duration", queryParams],
    queryFn: () => fetchApi<DurationData>("/duration", queryParams!),
    enabled: !!queryParams,
  });

  const loadData = () => {
    if (!selectedDests.length) return;
    setQueryParams({
      ...filterParams(filters), direction, destinations: selectedDests.join(","),
      time_budget: timeBudget, dep_start: depStart, dep_end: depEnd, max_transfers: maxTransfers,
      aggregation, transport: transportMode,
    });
  };

  const addDest = () => {
    const v = destSearch.trim();
    if (v && !selectedDests.includes(v)) setSelectedDests([...selectedDests, v]);
    setDestSearch("");
  };

  const mileLabel = direction === "to" ? "First-mile transport" : "Last-mile transport";

  const layers = useMemo((): Layer[] => {
    if (!data || data.error) return [];

    const maxDur = timeBudget * 60;

    if (viewMode === "gradient") {
      const heat = heatmapLayer("duration-heat", data.stations, {
        positionFn: (d) => [d.lon, d.lat],
        weightFn: (d) => Math.max(0, 1 - d.duration / maxDur),
        radiusPixels: 40,
        intensity: 2,
        threshold: 0.03,
      });

      const destLayer = new ScatterplotLayer({
        id: "duration-destinations-gradient",
        data: data.dest_coords || [],
        getPosition: (d) => [d.lon, d.lat],
        getRadius: 10,
        getFillColor: [227, 26, 28, 230],
        radiusMinPixels: 8,
        radiusMaxPixels: 14,
        pickable: true,
      });

      return [heat, destLayer] as Layer[];
    }

    const stationsLayer = new ScatterplotLayer({
      id: "duration-stations",
      data: data.stations,
      getPosition: (d) => [d.lon, d.lat],
      getRadius: (d) => 4 + (1 - d.duration / maxDur) * 10,
      getFillColor: (d) => colorToRGBA(d.duration / maxDur),
      radiusMinPixels: 3,
      radiusMaxPixels: 18,
      pickable: true,
      updateTriggers: {
        getRadius: [timeBudget],
        getFillColor: [timeBudget],
      },
    });

    const destLayer = new ScatterplotLayer({
      id: "duration-destinations",
      data: data.dest_coords || [],
      getPosition: (d) => [d.lon, d.lat],
      getRadius: 10,
      getFillColor: [227, 26, 28, 230],
      radiusMinPixels: 8,
      radiusMaxPixels: 14,
      pickable: true,
    });

    return [stationsLayer, destLayer] as Layer[];
  }, [data, viewMode, timeBudget]);

  return (
    <Layout
      sidebar={
        <>
          <div>
            <Label>Direction</Label>
            <Tabs value={direction} onValueChange={(v) => setDirection(v as "to" | "from")} className="mt-1.5">
              <TabsList className="w-full">
                <TabsTrigger value="to" className="flex-1">To dest</TabsTrigger>
                <TabsTrigger value="from" className="flex-1">From dest</TabsTrigger>
              </TabsList>
            </Tabs>
          </div>
          <div className="border-t border-border/40 pt-3 mt-3">
            <Label>Aggregation</Label>
            <Tabs value={aggregation} onValueChange={(v) => setAggregation(v as Aggregation)} className="mt-1.5">
              <TabsList className="w-full">
                <TabsTrigger value="average" className="flex-1">Average</TabsTrigger>
                <TabsTrigger value="min" className="flex-1">Min</TabsTrigger>
                <TabsTrigger value="max" className="flex-1">Max</TabsTrigger>
              </TabsList>
            </Tabs>
          </div>
          <div className="border-t border-border/40 pt-3 mt-3">
            <Label>View</Label>
            <Tabs value={viewMode} onValueChange={(v) => setViewMode(v as ViewMode)} className="mt-1.5">
              <TabsList className="w-full">
                <TabsTrigger value="stations" className="flex-1">Stations</TabsTrigger>
                <TabsTrigger value="gradient" className="flex-1">Gradient</TabsTrigger>
              </TabsList>
            </Tabs>
          </div>
          {viewMode === "gradient" && (
            <div className="border-t border-border/40 pt-3 mt-3">
              <Label>{mileLabel}</Label>
              <Tabs value={transportMode} onValueChange={(v) => setTransportMode(v as TransportMode)} className="mt-1.5">
                <TabsList className="w-full">
                  <TabsTrigger value="walk" className="flex-1">Walk</TabsTrigger>
                  <TabsTrigger value="bike" className="flex-1">Bike</TabsTrigger>
                  <TabsTrigger value="car" className="flex-1">Car</TabsTrigger>
                </TabsList>
              </Tabs>
              <p className="text-[10px] text-muted-foreground/60 mt-1">
                Speed: {TRANSPORT_SPEEDS[transportMode]} km/h
              </p>
            </div>
          )}
          <div className="border-t border-border/40 pt-3 mt-3 space-y-2">
            <Label>Settings</Label>
            <div>
              <span className="text-[10px] text-muted-foreground/60">Time budget (hours)</span>
              <Input type="number" value={timeBudget} min={0.5} max={6} step={0.5} onChange={(e) => setTimeBudget(+e.target.value)} className="h-8 text-xs" />
            </div>
            <div>
              <span className="text-[10px] text-muted-foreground/60">Departure window</span>
              <div className="flex items-center gap-2">
                <Input type="number" value={depStart} min={0} max={24} onChange={(e) => setDepStart(+e.target.value)} className="w-16 h-8 text-xs" />
                <span className="text-xs text-muted-foreground/50">to</span>
                <Input type="number" value={depEnd} min={0} max={24} onChange={(e) => setDepEnd(+e.target.value)} className="w-16 h-8 text-xs" />
              </div>
            </div>
            <div>
              <span className="text-[10px] text-muted-foreground/60">Max transfers</span>
              <Input type="number" value={maxTransfers} min={0} max={5} onChange={(e) => setMaxTransfers(+e.target.value)} className="h-8 text-xs" />
            </div>
          </div>
          <div className="border-t border-border/40 pt-3 mt-3"><FilterPanel filters={filters} onChange={setFilters} /></div>
          <ApplyButton loading={isFetching} onClick={loadData} label="Compute" />
        </>
      }
    >
      <div className="mb-5">
        <span className="text-[10px] text-muted-foreground/60 uppercase tracking-widest font-medium block mb-1.5">Destination station(s)</span>
        <div className="flex gap-2">
          <Input value={destSearch} onChange={(e) => setDestSearch(e.target.value)} onKeyDown={(e) => e.key === "Enter" && addDest()} placeholder="Search station..." className="max-w-sm text-sm" />
          <Button size="sm" variant="secondary" onClick={addDest}>Add</Button>
        </div>
        <div className="flex flex-wrap gap-1.5 mt-2">
          {selectedDests.map((d) => (
            <Badge key={d} variant="secondary" className="gap-1 pr-1">
              {d}
              <button onClick={() => setSelectedDests(selectedDests.filter((x) => x !== d))} className="hover:text-destructive cursor-pointer"><X className="w-3 h-3" /></button>
            </Badge>
          ))}
        </div>
      </div>

      {isFetching && <LoadingState message="Computing travel durations..." />}
      {!isFetching && !data && <EmptyState icon={Timer} message="Select destination(s) and click Compute" />}

      {data && !data.error && !isFetching && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5 animate-slide-up">
            <MetricCard label="Stations" value={fmt(data.stations.length)} />
            <MetricCard label="Avg Duration" value={fmt(data.avg_duration, 0)} suffix=" min" />
            <MetricCard label="Min" value={fmt(data.min_duration, 0)} suffix=" min" />
            <MetricCard label="Max" value={fmt(data.max_duration, 0)} suffix=" min" />
          </div>

          <DeckMap ref={mapRef} layers={layers} className="h-[calc(100vh-20rem)]" />
        </>
      )}

      {(error || data?.error) && <ErrorAlert message={data?.error ?? (error as Error).message} />}
    </Layout>
  );
}
