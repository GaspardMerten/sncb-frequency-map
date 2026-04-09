import {
  Train,
  MapPin,
  BarChart3,
  Timer,
  Bus,
  AlarmClock,
  Footprints,
  Search,
  AlertTriangle,
  Link2,
  type LucideIcon,
} from "lucide-react";

export interface PageInfo {
  slug: string;
  title: string;
  icon: LucideIcon;
  desc: string;
}

export const PAGES: PageInfo[] = [
  { slug: "segments", title: "Segment Frequency", icon: Train, desc: "Train frequencies per track segment" },
  { slug: "reach", title: "Station Reach", icon: MapPin, desc: "Reachable stations within a time budget" },
  { slug: "connectivity", title: "Station Connectivity", icon: BarChart3, desc: "Multi-dimensional station comparison" },
  { slug: "duration", title: "Travel Duration", icon: Timer, desc: "Travel time to any destination" },
  { slug: "multimodal", title: "Multimodal Duration", icon: Bus, desc: "Door-to-door with all operators" },
  { slug: "punctuality", title: "Train Punctuality", icon: AlarmClock, desc: "Real-time delay analysis" },
  { slug: "accessibility", title: "Stop Accessibility", icon: Footprints, desc: "Distance to nearest transit stop" },
  { slug: "propagation", title: "Delay Propagation", icon: Search, desc: "Where delays originate" },
  { slug: "problematic", title: "Problematic Trains", icon: AlertTriangle, desc: "Consistently late trains" },
  { slug: "missed", title: "Missed Connections", icon: Link2, desc: "Broken transfers due to delays" },
];

export const MAP_CENTER: [number, number] = [50.5, 4.35];
export const MAP_ZOOM = 8;
export const TILE_URL = "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png";
export const TILE_ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> &copy; <a href="https://carto.com/">CARTO</a>';
