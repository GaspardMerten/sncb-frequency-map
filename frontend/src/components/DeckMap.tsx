import { useRef, useEffect, useImperativeHandle, forwardRef } from "react";
import { Map as MapLibreMap, NavigationControl } from "maplibre-gl";
import { MapboxOverlay } from "@deck.gl/mapbox";
import type { Layer } from "@deck.gl/core";
import { cn } from "@/lib/utils";

interface DeckMapProps {
  id?: string;
  layers: Layer[];
  initialViewState?: {
    longitude: number;
    latitude: number;
    zoom: number;
  };
  className?: string;
  onClick?: (info: any) => void;
  getTooltip?: (info: any) => string | { html: string; style?: any } | null;
}

export interface DeckMapRef {
  flyTo: (opts: { longitude: number; latitude: number; zoom?: number; duration?: number }) => void;
  getMap: () => MapLibreMap | null;
}

const DEFAULT_VIEW = {
  longitude: 4.35,
  latitude: 50.5,
  zoom: 7.5,
};

const BASEMAP_STYLE =
  "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json";

export const DeckMap = forwardRef<DeckMapRef, DeckMapProps>(
  function DeckMap({ id, layers, initialViewState, className, onClick, getTooltip }, ref) {
    const containerRef = useRef<HTMLDivElement>(null);
    const mapRef = useRef<MapLibreMap | null>(null);
    const overlayRef = useRef<MapboxOverlay | null>(null);

    useImperativeHandle(ref, () => ({
      flyTo({ longitude, latitude, zoom, duration = 1200 }) {
        mapRef.current?.flyTo({
          center: [longitude, latitude],
          ...(zoom !== undefined ? { zoom } : {}),
          duration,
        });
      },
      getMap() {
        return mapRef.current;
      },
    }));

    useEffect(() => {
      if (!containerRef.current || mapRef.current) return;

      const view = initialViewState ?? DEFAULT_VIEW;

      const map = new MapLibreMap({
        container: containerRef.current,
        style: BASEMAP_STYLE,
        center: [view.longitude, view.latitude],
        zoom: view.zoom,
      });

      const overlay = new MapboxOverlay({
        layers: [],
        ...(onClick ? { onClick } : {}),
        ...(getTooltip ? { getTooltip: getTooltip as any } : {}),
      });

      map.addControl(overlay as any);
      map.addControl(new NavigationControl(), "top-right");

      mapRef.current = map;
      overlayRef.current = overlay;

      return () => {
        map.remove();
        mapRef.current = null;
        overlayRef.current = null;
      };
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    useEffect(() => {
      overlayRef.current?.setProps({
        layers,
        ...(getTooltip ? { getTooltip: getTooltip as any } : {}),
      });
    }, [layers, getTooltip]);

    return (
      <div
        ref={containerRef}
        id={id}
        className={cn(
          "w-full rounded-2xl border border-border/60 shadow-sm overflow-hidden",
          className,
        )}
      />
    );
  },
);
