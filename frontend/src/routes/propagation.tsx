import { createRoute } from "@tanstack/react-router";
import { useState, useMemo, useRef, useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import type { Layer } from "@deck.gl/core";
import { Search } from "lucide-react";
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
import { MapViewBar, mapViewTooltip } from "@/components/MapViewBar";
import { DeckMap, type DeckMapRef } from "@/components/DeckMap";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { fetchApi } from "@/lib/api";
import { fmt, daysAgo } from "@/lib/utils";
import { stationLayer, segmentLayer, colorToRGBA } from "@/lib/layers";
import { tooltipBox } from "@/lib/tooltip";
import { useMapView, makeTercileClassifier, type MetricOption } from "@/hooks/useMapView";

export const propagationRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/propagation",
  component: PropagationPage,
});

interface PropStation { name: string; lat?: number; lon?: number; incidents: number; total_delay: number; n_trips: number; incidents_per_1k: number; delay_per_trip: number; }
interface PropSegment { from_name: string; to_name: string; from_lat: number; from_lon: number; to_lat: number; to_lon: number; incidents: number; total_delay: number; n_trips: number; incidents_per_1k: number; delay_per_trip: number; }
interface PropData { n_events: number; n_stations: number; total_delay_min: number; stations: PropStation[]; segments?: PropSegment[]; error?: string; }

const METRICS_ABSOLUTE: MetricOption[] = [
  { key: "total_delay", label: "Total delay (min)", accessor: (d: PropStation) => d.total_delay, suffix: " min" },
  { key: "incidents", label: "Incidents", accessor: (d: PropStation) => d.incidents },
];

const METRICS_RELATIVE: MetricOption[] = [
  { key: "incidents_per_1k", label: "Incidents/1k trips", accessor: (d: PropStation) => d.incidents_per_1k },
  { key: "delay_per_trip", label: "Delay/trip (min)", accessor: (d: PropStation) => d.delay_per_trip, suffix: " min" },
];

function PropagationPage() {
  const [scaleMode, setScaleMode] = useState<"absolute" | "relative">("absolute");
  const [startDate, setStartDate] = useState(daysAgo(7));
  const [endDate, setEndDate] = useState(daysAgo(1));
  const [minIncrease, setMinIncrease] = useState(60);
  const [minIncidents, setMinIncidents] = useState(3);
  const [hourStart, setHourStart] = useState(0);
  const [hourEnd, setHourEnd] = useState(24);
  const [queryParams, setQueryParams] = useState<Record<string, string | number | boolean> | null>(null);
  const mapRef = useRef<DeckMapRef>(null);

  const { data, error, isFetching } = useQuery({
    queryKey: ["propagation", queryParams],
    queryFn: () => fetchApi<PropData>("/propagation", queryParams!),
    enabled: !!queryParams,
  });

  const { data: geoData } = useQuery({
    queryKey: ["provinces"],
    queryFn: () => fetchApi<any>("/provinces"),
  });

  const metrics = scaleMode === "relative" ? METRICS_RELATIVE : METRICS_ABSOLUTE;

  const geoStations = useMemo(
    () => (data?.stations ?? []).filter((s): s is PropStation & { lat: number; lon: number } => !!s.lat && !!s.lon),
    [data],
  );

  const sizeClassifier = useMemo(
    () => makeTercileClassifier(geoStations, (d) => d.total_delay),
    [geoStations],
  );

  const mapView = useMapView({
    data: geoStations,
    geoData,
    getLon: (d) => d.lon,
    getLat: (d) => d.lat,
    getSize: sizeClassifier,
    metrics,
    showGradient: true,
  });

  const loadData = () => setQueryParams({ start: startDate, end: endDate, min_increase: minIncrease, min_incidents: minIncidents, hour_start: hourStart, hour_end: hourEnd, view: mapView.viewMode === "segments" ? "segments" : "stations" });

  const handleStationClick = useCallback((s: PropStation) => {
    if (s.lat && s.lon) {
      mapRef.current?.flyTo({ longitude: s.lon, latitude: s.lat, zoom: 12 });
    }
  }, []);

  // Segment layers (custom "segments" mode)
  const segmentLayers = useMemo<Layer[]>(() => {
    if (mapView.viewMode !== "segments" || !data?.segments?.length) return [];
    const segs = data.segments;
    const metric = scaleMode === "relative"
      ? (d: PropSegment) => d.incidents_per_1k
      : (d: PropSegment) => d.total_delay;
    const maxVal = Math.max(...segs.map(metric), 0.001);

    return [
      segmentLayer("propagation-segments", segs, {
        pathFn: (d) => [[d.from_lon, d.from_lat], [d.to_lon, d.to_lat]],
        widthFn: (d) => 2 + (metric(d) / maxVal) * 6,
        colorFn: (d) => colorToRGBA(metric(d) / maxVal),
        widthMinPixels: 1,
        widthMaxPixels: 12,
      }),
    ] as Layer[];
  }, [data, mapView.viewMode, scaleMode]);

  // Station layers (default "stations" mode)
  const stationLayers = useMemo<Layer[]>(() => {
    if (!data || data.error || !mapView.filtered.length) return [];
    const metric = scaleMode === "relative"
      ? (d: PropStation & { lat: number; lon: number }) => d.incidents_per_1k
      : (d: PropStation & { lat: number; lon: number }) => d.total_delay;
    const maxVal = Math.max(...mapView.filtered.map(metric), 0.001);

    return [
      stationLayer("propagation-stations", mapView.filtered, {
        positionFn: (d) => [d.lon, d.lat],
        radiusFn: (d) => 4 + (metric(d) / maxVal) * 16,
        colorFn: (d) => colorToRGBA(metric(d) / maxVal),
        radiusMinPixels: 3,
        radiusMaxPixels: 30,
      }),
    ] as Layer[];
  }, [data, mapView.filtered, scaleMode]);

  const layers = mapView.isOverlayView
    ? mapView.overlayLayers
    : mapView.viewMode === "segments"
      ? segmentLayers
      : stationLayers;

  const stationTableData = useMemo(() => {
    if (!data) return [];
    const list = [...data.stations];
    if (scaleMode === "relative") {
      list.sort((a, b) => b.incidents_per_1k - a.incidents_per_1k);
    }
    return list;
  }, [data, scaleMode]);

  const segmentTableData = useMemo(() => {
    if (!data?.segments) return [];
    const list = [...data.segments];
    if (scaleMode === "relative") {
      list.sort((a, b) => b.incidents_per_1k - a.incidents_per_1k);
    }
    return list;
  }, [data, scaleMode]);

  // Summary: worst per-trip station for the "relative" insight card
  const worstRelative = useMemo(() => {
    if (!data?.stations.length) return null;
    return [...data.stations].sort((a, b) => b.incidents_per_1k - a.incidents_per_1k)[0];
  }, [data]);

  return (
    <Layout
      sidebar={
        <>
          <div>
            <Label>Scale</Label>
            <div className="mt-1.5">
              <Tabs value={scaleMode} onValueChange={(v) => setScaleMode(v as "absolute" | "relative")}>
                <TabsList className="w-full">
                  <TabsTrigger value="absolute" className="flex-1">Absolute</TabsTrigger>
                  <TabsTrigger value="relative" className="flex-1">Per trip</TabsTrigger>
                </TabsList>
              </Tabs>
            </div>
          </div>
          <div className="border-t border-border/40 pt-3 mt-3">
            <Label>Date Range</Label>
            <div className="grid grid-cols-2 gap-2 mt-1.5">
              <div><span className="text-[10px] text-muted-foreground/60">From</span><Input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} className="h-8 text-xs" /></div>
              <div><span className="text-[10px] text-muted-foreground/60">To</span><Input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} className="h-8 text-xs" /></div>
            </div>
          </div>
          <div className="border-t border-border/40 pt-3 mt-3 space-y-2">
            <Label>Thresholds</Label>
            <div><span className="text-[10px] text-muted-foreground/60">Min delay increase (sec)</span><Input type="number" value={minIncrease} min={0} max={600} onChange={(e) => setMinIncrease(+e.target.value)} className="h-8 text-xs" /></div>
            <div><span className="text-[10px] text-muted-foreground/60">Min incidents</span><Input type="number" value={minIncidents} min={1} max={100} onChange={(e) => setMinIncidents(+e.target.value)} className="h-8 text-xs" /></div>
            <div>
              <span className="text-[10px] text-muted-foreground/60">Hour window</span>
              <div className="flex items-center gap-2"><Input type="number" value={hourStart} min={0} max={24} onChange={(e) => setHourStart(+e.target.value)} className="w-16 h-8 text-xs" /><span className="text-xs text-muted-foreground/50">to</span><Input type="number" value={hourEnd} min={0} max={24} onChange={(e) => setHourEnd(+e.target.value)} className="w-16 h-8 text-xs" /></div>
            </div>
          </div>
          <ApplyButton loading={isFetching} onClick={loadData} label="Analyse" />
        </>
      }
    >
      {isFetching && <LoadingState message="Analysing delay propagation..." />}
      {!isFetching && !data && <EmptyState icon={Search} message="Configure filters and click Analyse" />}

      {data && !data.error && !isFetching && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5 animate-slide-up">
            <MetricCard label="Delay Events" value={fmt(data.n_events)} />
            <MetricCard label="Stations Involved" value={fmt(data.n_stations)} />
            <MetricCard label="Total Delay Added" value={fmt(data.total_delay_min, 0)} suffix=" min" />
            {worstRelative && (
              <MetricCard
                label="Worst Rate"
                value={`${fmt(worstRelative.incidents_per_1k, 1)}`}
                suffix={`/1k at ${worstRelative.name.split(" ")[0]}`}
              />
            )}
          </div>

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
            extraTabs={[{ value: "segments", label: "Segments", position: "before" }]}
          />

          <div className="grid grid-cols-1 xl:grid-cols-3 gap-4 mt-3">
            <div className="xl:col-span-2 space-y-2">
              <DeckMap ref={mapRef} layers={layers} className="h-[calc(100vh-14rem)]"
                getTooltip={(info) => {
                  const mv = mapViewTooltip(mapView.activeMetric, info);
                  if (mv) return mv;
                  const { object, layer } = info;
                  if (!object || !layer) return null;
                  const id = layer.id as string;
                  if (id === "propagation-stations") {
                    const primary = scaleMode === "relative"
                      ? `<b>${fmt(object.incidents_per_1k, 1)} incidents/1k trips</b>`
                      : `<b>${fmt(object.total_delay, 0)} min</b> total delay`;
                    return tooltipBox(
                      `<b>${object.name}</b><br/>`
                      + `${primary}<br/>`
                      + `<span style="opacity:0.7">${fmt(object.incidents)} events across ${fmt(object.n_trips)} departures</span>`
                    );
                  }
                  if (id === "propagation-segments") {
                    const primary = scaleMode === "relative"
                      ? `<b>${fmt(object.incidents_per_1k, 1)} incidents/1k trips</b>`
                      : `<b>${fmt(object.total_delay, 0)} min</b> total delay`;
                    return tooltipBox(
                      `<b>${object.from_name} \u2192 ${object.to_name}</b><br/>`
                      + `${primary}<br/>`
                      + `<span style="opacity:0.7">${fmt(object.incidents)} events across ${fmt(object.n_trips)} trips</span>`
                    );
                  }
                  return null;
                }}
              />
              {!mapView.isOverlayView && (
                <ColorLegend
                  min={scaleMode === "relative" ? "Low incidents/trip" : "Low total delay"}
                  max={scaleMode === "relative" ? "High incidents/trip" : "High total delay"}
                />
              )}
            </div>
            {mapView.viewMode === "segments" ? (
              <DataTable
                title={scaleMode === "relative" ? "Highest Propagation Rate" : "Most Delay Added"}
                keyFn={(s: PropSegment, i) => `${s.from_name}-${s.to_name}-${i}`}
                data={segmentTableData}
                maxRows={30}
                columns={[
                  { header: "Segment", accessor: (s: PropSegment) => (
                    <span className="font-medium truncate max-w-[160px] block" title={`${s.from_name} \u2192 ${s.to_name}`}>
                      {s.from_name} <span className="text-muted-foreground">\u2192</span> {s.to_name}
                    </span>
                  )},
                  { header: "Events", accessor: (s: PropSegment) => <span className="text-muted-foreground">{fmt(s.incidents)}</span>, align: "right" as const },
                  { header: "Trips", accessor: (s: PropSegment) => <span className="text-muted-foreground">{fmt(s.n_trips)}</span>, align: "right" as const },
                  { header: scaleMode === "relative" ? "/1k" : "Delay", accessor: (s: PropSegment) => (
                    <span className="font-semibold text-destructive">
                      {scaleMode === "relative" ? fmt(s.incidents_per_1k, 1) : `${fmt(s.total_delay, 0)}m`}
                    </span>
                  ), align: "right" as const },
                ]}
              />
            ) : !mapView.isOverlayView ? (
              <DataTable
                title={scaleMode === "relative" ? "Highest Propagation Rate" : "Most Delay Added"}
                keyFn={(s: PropStation) => s.name}
                data={stationTableData}
                maxRows={30}
                onRowClick={handleStationClick}
                columns={[
                  { header: "Station", accessor: (s: PropStation) => <span className="font-medium truncate max-w-[120px] block">{s.name}</span> },
                  { header: "Events", accessor: (s: PropStation) => <span className="text-muted-foreground">{fmt(s.incidents)}</span>, align: "right" as const },
                  { header: "Trips", accessor: (s: PropStation) => <span className="text-muted-foreground">{fmt(s.n_trips)}</span>, align: "right" as const },
                  { header: scaleMode === "relative" ? "/1k" : "Delay", accessor: (s: PropStation) => (
                    <span className="font-semibold text-destructive">
                      {scaleMode === "relative" ? fmt(s.incidents_per_1k, 1) : `${fmt(s.total_delay, 0)}m`}
                    </span>
                  ), align: "right" as const },
                ]}
              />
            ) : null}
          </div>

          <div className="mt-4">
            <MethodologyPanel>
              <p>Delay propagation is detected by tracking each train's delay at consecutive stops. When a train's delay <b>increases</b> by more than the threshold between two stops, we record a propagation incident at the receiving station.</p>
              <p><b>Absolute</b> mode ranks stations by total minutes of delay introduced — useful for identifying the biggest contributors to system-wide delay. Large hub stations naturally rank higher.</p>
              <p><b>Per trip</b> mode divides the number of incidents by total departures at each station (shown as incidents per 1,000 trips). This reveals stations where a high <i>proportion</i> of trains pick up delay, regardless of station size — often the most actionable finding for infrastructure planners.</p>
            </MethodologyPanel>
          </div>
        </>
      )}

      {(error || data?.error) && <ErrorAlert message={data?.error ?? (error as Error).message} />}
    </Layout>
  );
}
