import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ColorLegend } from "@/components/ColorLegend";
import type { StationSize, SizeFilter, MetricOption } from "@/hooks/useMapView";

const SIZE_CSS: Record<StationSize, string> = {
  small: "#4caf50",
  medium: "#ff9800",
  big: "#d32f2f",
};

const SIZE_LABELS: Record<StationSize, string> = {
  small: "Small",
  medium: "Medium",
  big: "Big",
};

interface MapViewBarProps {
  viewMode: string;
  onViewModeChange: (v: string) => void;
  /** Size filter state — omit to hide size chips */
  sizeFilter?: SizeFilter;
  onSizeFilterChange?: (size: StationSize, enabled: boolean) => void;
  /** Choropleth metric key */
  choroplethMetric?: string;
  onChoroplethMetricChange?: (key: string) => void;
  /** Available metrics for choropleth selector */
  metrics?: MetricOption[];
  /** Whether to show the gradient tab */
  showGradient?: boolean;
  /** Active metric definition (for legend text) */
  activeMetric?: MetricOption;
  /** Whether the current view is an overlay (provinces/regions/gradient) */
  isOverlayView?: boolean;
  /** Extra tabs to show alongside the defaults. position "before" puts them before Stations. */
  extraTabs?: { value: string; label: string; position?: "before" | "after" }[];
  /** Hide the default "Stations" tab */
  hideStationsTab?: boolean;
}

export function MapViewBar({
  viewMode,
  onViewModeChange,
  sizeFilter,
  onSizeFilterChange,
  choroplethMetric,
  onChoroplethMetricChange,
  metrics,
  showGradient = true,
  activeMetric,
  isOverlayView,
  extraTabs,
  hideStationsTab,
}: MapViewBarProps) {
  const isOverlay = isOverlayView ?? ["provinces", "regions", "gradient"].includes(viewMode);

  const beforeTabs = extraTabs?.filter((t) => t.position === "before") ?? [];
  const afterTabs = extraTabs?.filter((t) => t.position !== "before") ?? [];

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-3">
        <Tabs value={viewMode} onValueChange={onViewModeChange}>
          <TabsList>
            {beforeTabs.map((t) => (
              <TabsTrigger key={t.value} value={t.value} className="text-xs">{t.label}</TabsTrigger>
            ))}
            {!hideStationsTab && (
              <TabsTrigger value="stations" className="text-xs">Stations</TabsTrigger>
            )}
            <TabsTrigger value="provinces" className="text-xs">Provinces</TabsTrigger>
            <TabsTrigger value="regions" className="text-xs">Regions</TabsTrigger>
            {showGradient && (
              <TabsTrigger value="gradient" className="text-xs">Gradient</TabsTrigger>
            )}
            {afterTabs.map((t) => (
              <TabsTrigger key={t.value} value={t.value} className="text-xs">{t.label}</TabsTrigger>
            ))}
          </TabsList>
        </Tabs>

        {sizeFilter && onSizeFilterChange && (
          <div className="flex items-center gap-1.5">
            {(["small", "medium", "big"] as StationSize[]).map((size) => (
              <button
                key={size}
                onClick={() => onSizeFilterChange(size, !sizeFilter[size])}
                className={`flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-medium border transition-colors ${
                  sizeFilter[size]
                    ? "border-border/60 bg-card text-foreground/80"
                    : "border-border/20 bg-muted/30 text-muted-foreground/40 line-through"
                }`}
              >
                <span
                  className="w-2 h-2 rounded-full shrink-0"
                  style={{ backgroundColor: SIZE_CSS[size], opacity: sizeFilter[size] ? 1 : 0.3 }}
                />
                {SIZE_LABELS[size]}
              </button>
            ))}
          </div>
        )}

        {isOverlay && metrics && metrics.length > 1 && onChoroplethMetricChange && (
          <Tabs value={choroplethMetric ?? ""} onValueChange={onChoroplethMetricChange}>
            <TabsList>
              {metrics.map((m) => (
                <TabsTrigger key={m.key} value={m.key} className="text-[10px]">{m.label}</TabsTrigger>
              ))}
            </TabsList>
          </Tabs>
        )}
      </div>

      {isOverlay && activeMetric && (
        <ColorLegend min={`Low ${activeMetric.label}`} max={`High ${activeMetric.label}`} />
      )}
    </div>
  );
}

/** Tooltip handler for mapview overlay layers (choropleth + gradient). Returns null if not a mapview layer. */
export function mapViewTooltip(activeMetric: MetricOption, info: { object?: any; layer?: any }) {
  const { object, layer } = info;
  if (!object || !layer) return null;
  const id = layer.id as string;
  if (!id.startsWith("mapview-")) return null;
  const name = object.properties?.name ?? "";
  const val = object.properties?._value;
  const suffix = activeMetric.suffix ?? "";
  return {
    html: `<div style="font-size:12px"><b>${name}</b><br/>Avg ${activeMetric.label}: ${val != null ? Number(val).toFixed(1) + suffix : "—"}</div>`,
    style: {
      backgroundColor: "rgba(255,255,255,0.95)", color: "#111", padding: "6px 8px",
      borderRadius: "8px", border: "1px solid #e5e7eb", boxShadow: "0 2px 8px rgba(0,0,0,0.12)", fontSize: "12px",
    },
  };
}
