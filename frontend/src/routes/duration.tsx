import { createRoute } from "@tanstack/react-router";
import { useState, useMemo, useRef, useCallback } from "react";
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
import { ColorLegend } from "@/components/ColorLegend";
import { MethodologyPanel } from "@/components/MethodologyPanel";
import { DataTable } from "@/components/DataTable";
import { MapViewBar, mapViewTooltip } from "@/components/MapViewBar";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { DeckMap, type DeckMapRef } from "@/components/DeckMap";
import { colorToRGBA } from "@/lib/layers";
import { fetchApi } from "@/lib/api";
import { filterParams, fmt, daysAgo, today } from "@/lib/utils";
import { useMapView, makeTercileClassifier, type MetricOption } from "@/hooks/useMapView";

export const durationRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/duration",
  component: DurationPage,
});

interface DurationStation {
  name: string; lat: number; lon: number; duration: number;
}

interface DurationData {
  stations: DurationStation[];
  dest_coords?: { name: string; lat: number; lon: number }[];
  avg_duration: number; min_duration: number; max_duration: number; error?: string;
}

type Aggregation = "average" | "min" | "max";
type TransportMode = "walk" | "bike" | "car";

const TRANSPORT_SPEEDS: Record<TransportMode, number> = { walk: 5, bike: 15, car: 50 };

const METRICS: MetricOption[] = [
  { key: "duration", label: "Duration (min)", accessor: (d: DurationStation) => d.duration, suffix: " min" },
];

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
  const [destSearch, setDestSearch] = useState("");
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [selectedDests, setSelectedDests] = useState<string[]>(["Bruxelles-Central"]);
  const [queryParams, setQueryParams] = useState<Record<string, string | number | boolean> | null>(null);
  const mapRef = useRef<DeckMapRef>(null);

  const { data, error, isFetching } = useQuery({
    queryKey: ["duration", queryParams],
    queryFn: () => fetchApi<DurationData>("/duration", queryParams!),
    enabled: !!queryParams,
  });

  const { data: geoData } = useQuery({
    queryKey: ["provinces"],
    queryFn: () => fetchApi<any>("/provinces"),
  });

  const loadData = () => {
    if (!selectedDests.length) return;
    setQueryParams({
      ...filterParams(filters), direction, destinations: selectedDests.join(","),
      time_budget: timeBudget, dep_start: depStart, dep_end: depEnd, max_transfers: maxTransfers,
      aggregation, transport: transportMode,
    });
  };

  const sizeClassifier = useMemo(
    () => makeTercileClassifier(data?.stations ?? [], (d) => d.duration),
    [data],
  );

  const mapView = useMapView<DurationStation>({
    data: data?.stations ?? [],
    geoData,
    getLon: (d) => d.lon,
    getLat: (d) => d.lat,
    getSize: sizeClassifier,
    metrics: METRICS,
    showGradient: true,
  });

  const suggestions = useMemo(() => {
    if (!destSearch || destSearch.length < 2 || !data) return [];
    return data.stations
      .filter((s) => s.name.toLowerCase().includes(destSearch.toLowerCase()))
      .filter((s) => !selectedDests.includes(s.name))
      .slice(0, 8);
  }, [destSearch, data, selectedDests]);

  const addDest = useCallback((name: string) => {
    const v = name.trim();
    if (v && !selectedDests.includes(v)) setSelectedDests((prev) => [...prev, v]);
    setDestSearch("");
    setShowSuggestions(false);
  }, [selectedDests]);

  const sortedStations = useMemo(() => {
    if (!data?.stations) return [];
    return [...mapView.filtered].sort((a, b) => a.duration - b.duration);
  }, [mapView.filtered]);

  const mileLabel = direction === "to" ? "First-mile transport" : "Last-mile transport";

  const stationLayers = useMemo((): Layer[] => {
    if (!data || data.error || !mapView.filtered.length) return [];

    const stations = mapView.filtered;
    const durations = stations.map((d) => d.duration);
    const minDur = Math.min(...durations);
    const maxDurActual = Math.max(...durations);
    const spread = Math.max(maxDurActual - minDur, 1);
    const ratio = (d: DurationStation) => (d.duration - minDur) / spread;

    const stationsLayer = new ScatterplotLayer({
      id: "duration-stations",
      data: stations,
      getPosition: (d: DurationStation) => [d.lon, d.lat],
      getRadius: (d: DurationStation) => 2 + (1 - ratio(d)) * 10,
      getFillColor: (d: DurationStation) => colorToRGBA(ratio(d), 230),
      radiusUnits: "pixels",
      radiusMinPixels: 2,
      radiusMaxPixels: 22,
      pickable: true,
      updateTriggers: { getRadius: [minDur, maxDurActual], getFillColor: [minDur, maxDurActual] },
    });

    const destLayer = new ScatterplotLayer({
      id: "duration-destinations",
      data: data.dest_coords || [],
      getPosition: (d) => [d.lon, d.lat],
      getRadius: 8,
      getFillColor: [227, 26, 28, 230],
      radiusUnits: "pixels",
      radiusMinPixels: 7,
      radiusMaxPixels: 12,
      pickable: true,
    });

    return [stationsLayer, destLayer] as Layer[];
  }, [data, mapView.filtered, timeBudget]);

  const layers = mapView.isOverlayView ? mapView.overlayLayers : stationLayers;

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
          {mapView.viewMode === "gradient" && (
            <div className="border-t border-border/40 pt-3 mt-3">
              <Label>{mileLabel}</Label>
              <Tabs value={transportMode} onValueChange={(v) => setTransportMode(v as TransportMode)} className="mt-1.5">
                <TabsList className="w-full">
                  <TabsTrigger value="walk" className="flex-1">Walk</TabsTrigger>
                  <TabsTrigger value="bike" className="flex-1">Bike</TabsTrigger>
                  <TabsTrigger value="car" className="flex-1">Car</TabsTrigger>
                </TabsList>
              </Tabs>
              <p className="text-[10px] text-muted-foreground/60 mt-1">Speed: {TRANSPORT_SPEEDS[transportMode]} km/h</p>
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
        <div className="relative">
          <div className="flex gap-2">
            <Input
              value={destSearch}
              onChange={(e) => { setDestSearch(e.target.value); setShowSuggestions(true); }}
              onFocus={() => setShowSuggestions(true)}
              onKeyDown={(e) => {
                if (e.key === "Enter") { addDest(suggestions.length > 0 ? suggestions[0].name : destSearch); }
                if (e.key === "Escape") setShowSuggestions(false);
              }}
              placeholder="Search station..."
              className="max-w-sm text-sm"
            />
            <Button size="sm" variant="secondary" onClick={() => addDest(suggestions.length > 0 ? suggestions[0].name : destSearch)}>Add</Button>
          </div>
          {showSuggestions && suggestions.length > 0 && (
            <div className="absolute z-50 top-full mt-1 w-full max-w-sm rounded-lg border border-border/50 bg-card shadow-lg overflow-hidden">
              {suggestions.map((s) => (
                <button key={s.name} className="w-full text-left px-3 py-2 text-sm hover:bg-accent/50 transition-colors cursor-pointer flex items-center justify-between"
                  onMouseDown={(e) => e.preventDefault()} onClick={() => addDest(s.name)}>
                  <span>{s.name}</span>
                  <span className="text-[10px] text-muted-foreground tabular-nums">{Math.round(s.duration)} min</span>
                </button>
              ))}
            </div>
          )}
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

          <div className="space-y-2">
            <MapViewBar
              viewMode={mapView.viewMode}
              onViewModeChange={mapView.setViewMode}
              sizeFilter={mapView.sizeFilter}
              onSizeFilterChange={mapView.setSizeEnabled}
              choroplethMetric={mapView.choroplethMetric}
              onChoroplethMetricChange={mapView.setChoroplethMetric}
              metrics={mapView.metrics}
              showGradient={mapView.showGradient}
              activeMetric={mapView.activeMetric}
              isOverlayView={mapView.isOverlayView}
            />
            <DeckMap
              ref={mapRef} layers={layers} className="h-[calc(100vh-20rem)]"
              getTooltip={(info) => {
                const mv = mapViewTooltip(mapView.activeMetric, info);
                if (mv) return mv;
                const { object, layer } = info;
                if (!object || !layer) return null;
                const id = layer.id as string;
                const style = { backgroundColor: "rgba(255,255,255,0.95)", color: "#111", padding: "6px 8px", borderRadius: "8px", border: "1px solid #e5e7eb", boxShadow: "0 2px 8px rgba(0,0,0,0.12)" };
                if (id === "duration-stations") return { html: `<div style="font-size:12px"><b>${object.name}</b><br/>${Math.round(object.duration)} min</div>`, style };
                if (id === "duration-destinations") return { html: `<div style="font-size:12px"><b>${object.name}</b><br/>Destination</div>`, style };
                return null;
              }}
            />
            {!mapView.isOverlayView && <ColorLegend min="Short travel time" max="Long travel time" />}
          </div>

          {sortedStations.length > 0 && (
            <div className="mt-4">
              <DataTable
                title="All Stations - Travel Duration"
                keyFn={(_, i) => i}
                data={sortedStations}
                maxRows={200}
                columns={[
                  { header: "Station", accessor: (s) => <span className="font-medium">{s.name}</span> },
                  {
                    header: "Duration (min)",
                    accessor: (s) => (
                      <div className="flex items-center justify-end gap-2">
                        <div className="w-20 h-1.5 rounded-full bg-muted overflow-hidden">
                          <div className="h-full rounded-full bg-primary/60 transition-all" style={{ width: `${Math.min((s.duration / (timeBudget * 60)) * 100, 100)}%` }} />
                        </div>
                        <span className="text-muted-foreground tabular-nums w-12 text-right">{Math.round(s.duration)}</span>
                      </div>
                    ),
                    align: "right" as const,
                  },
                ]}
              />
            </div>
          )}

          <div className="mt-4">
            <MethodologyPanel>
              <p>Travel duration is computed using BFS on the GTFS timetable graph. For "To destination" mode, a reverse search finds all stations that can reach the destination within the time budget. For "From destination", forward BFS explores outbound connections.</p>
              <p>Multiple destinations can be combined using Average, Min, or Max aggregation. The gradient view adds first/last-mile transport time based on the selected mode (Walk 5km/h, Bike 15km/h, Car 50km/h).</p>
            </MethodologyPanel>
          </div>
        </>
      )}

      {(error || data?.error) && <ErrorAlert message={data?.error ?? (error as Error).message} />}
    </Layout>
  );
}
