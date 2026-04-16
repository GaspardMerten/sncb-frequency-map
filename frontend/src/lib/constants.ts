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
  CloudRain,
  type LucideIcon,
} from "lucide-react";

export interface PageInfo {
  slug: string;
  title: string;
  shortTitle?: string;
  icon: LucideIcon;
  desc: string;
  gradient: string;
}

export const PAGES: PageInfo[] = [
  { slug: "segments", title: "Segment Frequency", shortTitle: "Segments", icon: Train, desc: "Train frequencies per track segment", gradient: "from-blue-500/15 to-indigo-500/5" },
  { slug: "reach", title: "Station Reach", shortTitle: "Reach", icon: MapPin, desc: "Reachable stations within a time budget", gradient: "from-emerald-500/15 to-teal-500/5" },
  { slug: "connectivity", title: "Station Connectivity", shortTitle: "Connect.", icon: BarChart3, desc: "Multi-dimensional station comparison", gradient: "from-violet-500/15 to-purple-500/5" },
  { slug: "duration", title: "Travel Duration", shortTitle: "Duration", icon: Timer, desc: "Travel time to any destination", gradient: "from-amber-500/15 to-orange-500/5" },
  { slug: "multimodal", title: "Multimodal Duration", shortTitle: "Multimodal", icon: Bus, desc: "Door-to-door with all operators", gradient: "from-cyan-500/15 to-sky-500/5" },
  { slug: "punctuality", title: "Train Punctuality", shortTitle: "Punctuality", icon: AlarmClock, desc: "Real-time delay analysis", gradient: "from-rose-500/15 to-pink-500/5" },
  { slug: "accessibility", title: "Stop Accessibility", shortTitle: "Access.", icon: Footprints, desc: "Distance to nearest transit stop", gradient: "from-lime-500/15 to-green-500/5" },
  { slug: "propagation", title: "Delay Propagation", shortTitle: "Propag.", icon: Search, desc: "Where delays originate", gradient: "from-orange-500/15 to-red-500/5" },
  { slug: "problematic", title: "Problematic Trains", shortTitle: "Problem.", icon: AlertTriangle, desc: "Consistently late trains", gradient: "from-red-500/15 to-rose-500/5" },
  { slug: "missed", title: "Missed Connections", shortTitle: "Missed", icon: Link2, desc: "Broken transfers due to delays", gradient: "from-fuchsia-500/15 to-pink-500/5" },
  { slug: "weather", title: "Weather & Delays", shortTitle: "Weather", icon: CloudRain, desc: "Weather impact on train punctuality", gradient: "from-sky-500/15 to-blue-500/5" },
];

export const MAP_CENTER: [number, number] = [50.5, 4.35];
export const MAP_ZOOM = 8;
export const TILE_URL = "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png";
export const TILE_ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> &copy; <a href="https://carto.com/">CARTO</a>';
