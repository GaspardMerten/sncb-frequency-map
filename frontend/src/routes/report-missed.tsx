import { createRoute } from "@tanstack/react-router";
import { useState, useMemo, useEffect, useRef, useCallback } from "react";
import type { Layer } from "@deck.gl/core";
import {
  ChevronDown,
  Link2,
  Clock,
  MapPin,
  TrendingDown,
  Sparkles,
  Settings2,
  AlertTriangle,
  Download,
  CloudRain, Search, MessageCircle, Lightbulb, ArrowRight} from "lucide-react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  AreaChart,
  Area,
  Cell,
  PieChart,
  Pie,
  ScatterChart,
  Scatter,
  ZAxis,
} from "recharts";
import { rootRoute } from "./__root";
import { DeckMap } from "@/components/DeckMap";
import { ErrorAlert } from "@/components/ErrorAlert";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { fetchApiSSE, type SSEProgress } from "@/lib/api";
import { fmt, cn } from "@/lib/utils";
import { stationLayer } from "@/lib/layers";
import { tooltipBox } from "@/lib/tooltip";
import { useScrollReveal } from "@/hooks/useScrollReveal";
import { ReportChatbot } from "@/components/ReportChatbot";

export const reportMissedRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/report/missed",
  component: MissedReportPage,
});

/* ---------- Types ---------- */

interface TrainPair {
  arriving_train: string;
  departing_train: string;
  relation_arr: string;
  relation_dep: string;
  planned_gap_min: number;
  actual_gap_min: number;
  n_occurrences: number;
  n_missed: number;
}

interface ReportStation {
  name: string;
  planned: number;
  missed: number;
  pct_missed: number;
  daily_trains: number;
  impact_score: number;
  lat?: number;
  lon?: number;
  worst_pairs?: TrainPair[];
}

interface KeyRoute {
  origin: string;
  destination: string;
  transfer_stations: string[];
  total_connections: number;
  missed: number;
  pct_missed: number;
  avg_added_wait_min: number;
  yearly_loss_hours: number;
}

interface WeatherSection {
  daily: {
    date: string;
    pct_missed: number;
    precip_mm: number;
    rain_mm: number;
    snow_cm: number;
    wind_kmh: number;
    gusts_kmh: number;
    temp_c: number | null;
  }[];
  correlations: Record<string, number>;
  comparison: Record<string, number>;
  n_days: number;
}


interface HubSpotlight {
  station: string;
  lat: number | null;
  lon: number | null;
  summary: { planned: number; missed: number; pct: number; close_calls: number; daily_trains: number };
  heatmap: { hour: number; dow: number; dow_label: string; planned: number; missed: number; pct: number }[];
  toxic_arrivals: { train: string; relation: string; missed_caused: number; avg_delay_min: number; n_days_seen: number }[];
}

interface Corridor {
  origin: string;
  destination: string;
  via: string;
  planned: number;
  missed: number;
  reliability_pct: number;
  pct_missed: number;
  avg_added_wait_min: number;
  worst_hours: { hour: number; planned: number; missed: number; pct: number }[];
}

interface DominoTrain {
  train: string;
  relation: string;
  total_missed_caused: number;
  stations_affected: string[];
  n_stations: number;
  avg_delay_min: number;
  n_days_seen: number;
  first_station?: string;
  last_station?: string;
}

interface WeatherSensitiveTrain {
  train: string;
  relation: string;
  first_station?: string;
  last_station?: string;
  n_days: number;
  avg_delay_min: number;
  avg_delay_rainy: number;
  avg_delay_dry: number;
  rain_sensitivity: number;
  wind_sensitivity?: number | null;
  rainy_days: number;
  dry_days: number;
}


interface OptBufferPoint {
  buffer_min: number;
  planned: number;
  missed: number;
  pct: number;
}

interface OptRecommendation {
  station: string;
  total_missed: number;
  total_planned: number;
  pct_missed: number;
  delta_min: number;
  saved_local: number;
  new_misses_downstream: number;
  saved_downstream: number;
  net_benefit: number;
  net_pct_of_station: number;
}

interface OptQuickWin {
  station: string;
  arr_train: string;
  dep_train: string;
  count: number;
  avg_overshoot_sec: number;
}

interface Optimization {
  buffer_curve: OptBufferPoint[];
  recommendations: OptRecommendation[];
  quick_wins: OptQuickWin[];
  barely_missed_pct: number;
  total_missed: number;
  total_net_saveable: number;
  net_saveable_pct: number;
}

interface MissedReportData {
  overview: {
    total_connections: number;
    total_missed: number;
    pct_missed: number;
    close_calls: number;
    total_added_wait_minutes: number;
    n_days: number;
    start_date: string;
    end_date: string;
  };
  daily: {
    date: string;
    planned: number;
    missed: number;
    pct: number;
    dow: number;
    dow_label: string;
  }[];
  hourly: { hour: number; planned: number; missed: number; pct: number }[];
  dow_summary: {
    dow: number;
    label: string;
    planned: number;
    missed: number;
    pct: number;
  }[];
  stations: ReportStation[];
  lucky: { total_close_calls: number; pct_of_all: number; pct_saved: number };
  added_wait: {
    avg_wait_min: number;
    median_wait_min: number;
    total_person_wait_min: number;
    histogram: { bucket: string; count: number }[];
    n_samples?: number;
  };
  key_routes: KeyRoute[];
  hub_spotlight: HubSpotlight[];
  corridors: Corridor[];
  domino_trains: DominoTrain[];
  weather: WeatherSection | null;
  weather_sensitive_trains?: WeatherSensitiveTrain[];
  optimization?: Optimization | null;
  error?: string;
}

/* ---------- Helpers ---------- */

function daysAgo(n: number) {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
}

const TT = {
  fontSize: 12,
  borderRadius: 12,
  border: "1px solid var(--color-border)",
};

function missColor(ratio: number): [number, number, number, number] {
  const t = Math.pow(Math.min(Math.max(ratio, 0), 1), 0.4);
  let r: number, g: number, b: number;
  if (t < 0.5) {
    const f = t * 2;
    r = Math.round(30 + f * 225);
    g = Math.round(100 + f * 80);
    b = Math.round(200 * (1 - f));
  } else {
    const f = (t - 0.5) * 2;
    r = Math.round(255 - f * 35);
    g = Math.round(180 * (1 - f));
    b = 0;
  }
  return [r, g, b, 220];
}

function titleCase(s: string) {
  return s
    .replace(/-/g, " ")
    .toLowerCase()
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function corrLabel(r: number): string {
  const a = Math.abs(r);
  if (a < 0.1) return "no correlation";
  if (a < 0.3) return "weak";
  if (a < 0.5) return "moderate";
  return "strong";
}

/* ---------- Scroll reveal ---------- */

function StorySection({
  children,
  className,
  id,
}: {
  children: React.ReactNode;
  className?: string;
  id?: string;
}) {
  const { ref, isVisible } = useScrollReveal();
  return (
    <section
      ref={ref}
      id={id}
      className={cn(
        "transition-all duration-700 ease-out",
        isVisible ? "opacity-100 translate-y-0" : "opacity-0 translate-y-8",
        className,
      )}
    >
      {children}
    </section>
  );
}

/* ---------- Animated counter ---------- */

function Counter({
  end,
  duration = 1500,
  suffix = "",
  visible,
  decimals = 0,
}: {
  end: number;
  duration?: number;
  suffix?: string;
  visible: boolean;
  decimals?: number;
}) {
  const [current, setCurrent] = useState(0);
  const raf = useRef(0);

  useEffect(() => {
    if (!visible || end === 0) return;
    const start = performance.now();
    const tick = (now: number) => {
      const elapsed = now - start;
      const p = Math.min(elapsed / duration, 1);
      const eased = 1 - Math.pow(1 - p, 3);
      setCurrent(end * eased);
      if (p < 1) raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf.current);
  }, [visible, end, duration]);

  return (
    <span>
      {decimals > 0 ? current.toFixed(decimals) : fmt(Math.round(current))}
      {suffix}
    </span>
  );
}

/* ---------- Main page ---------- */

function MissedReportPage() {
  const [startDate, setStartDate] = useState(daysAgo(7));
  const [endDate, setEndDate] = useState(daysAgo(1));
  const [minTransfer, setMinTransfer] = useState(2);
  const [maxTransfer, setMaxTransfer] = useState(15);
  const [hourStart, setHourStart] = useState(0);
  const [hourEnd, setHourEnd] = useState(24);
  const [closeCallSec, setCloseCallSec] = useState(120);
  const [weekdays, setWeekdays] = useState([0, 1, 2, 3, 4]);
  const [excludePub, setExcludePub] = useState(false);
  const [excludeSch, setExcludeSch] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [chatOpen, setChatOpen] = useState(false);
  const [weatherSearch, setWeatherSearch] = useState("");

  const [data, setData] = useState<MissedReportData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isFetching, setIsFetching] = useState(false);
  const [progress, setProgress] = useState<SSEProgress | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const generate = useCallback(async () => {
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;

    setIsFetching(true);
    setError(null);
    setProgress(null);

    try {
      const result = await fetchApiSSE<MissedReportData>(
        "/missed-report",
        {
          start: startDate,
          end: endDate,
          min_transfer: minTransfer,
          max_transfer: maxTransfer,
          hour_start: hourStart,
          hour_end: hourEnd,
          close_call_sec: closeCallSec,
          weekdays: weekdays.join(","),
          exclude_pub: excludePub,
          exclude_sch: excludeSch,
        },
        (p) => setProgress(p),
      );
      if (!ctrl.signal.aborted) {
        setData(result);
        setProgress(null);
      }
    } catch (e) {
      if (!ctrl.signal.aborted) {
        setError((e as Error).message);
      }
    } finally {
      if (!ctrl.signal.aborted) {
        setIsFetching(false);
      }
    }
  }, [startDate, endDate, minTransfer, maxTransfer, hourStart, hourEnd, closeCallSec, weekdays, excludePub, excludeSch]);

  const [heroVisible, setHeroVisible] = useState(false);
  useEffect(() => {
    if (data && !data.error) {
      const t = setTimeout(() => setHeroVisible(true), 200);
      return () => clearTimeout(t);
    }
    setHeroVisible(false);
  }, [data]);

  const rushPct = useMemo(() => {
    if (!data) return { rush: 0, off: 0 };
    const isRush = (h: number) =>
      (h >= 7 && h < 9) || (h >= 17 && h < 19);
    const rush = data.hourly.filter((h) => isRush(h.hour));
    const off = data.hourly.filter((h) => !isRush(h.hour) && h.planned > 0);
    const rM = rush.reduce((s, h) => s + h.missed, 0);
    const rT = rush.reduce((s, h) => s + h.planned, 0);
    const oM = off.reduce((s, h) => s + h.missed, 0);
    const oT = off.reduce((s, h) => s + h.planned, 0);
    return {
      rush: rT > 0 ? Math.round((rM / rT) * 1000) / 10 : 0,
      off: oT > 0 ? Math.round((oM / oT) * 1000) / 10 : 0,
    };
  }, [data]);

  const mapLayers = useMemo<Layer[]>(() => {
    if (!data) return [];
    const sts = data.stations.filter((s) => s.lat && s.lon);
    if (!sts.length) return [];
    const mx = Math.max(...sts.map((s) => s.missed), 1);
    return [
      stationLayer("rpt", sts, {
        positionFn: (d: ReportStation) => [d.lon!, d.lat!],
        radiusFn: (d: ReportStation) => 3 + (d.missed / mx) * 22,
        colorFn: (d: ReportStation) => missColor(d.missed / mx),
        radiusMinPixels: 3,
        radiusMaxPixels: 40,
      }),
    ] as Layer[];
  }, [data]);

  const hourlyData = useMemo(() => {
    if (!data) return [];
    return data.hourly
      .filter((h) => h.planned > 0)
      .map((h) => ({
        ...h,
        label: `${h.hour}h`,
        isRush: (h.hour >= 7 && h.hour < 9) || (h.hour >= 17 && h.hour < 19),
      }));
  }, [data]);

  const pieData = useMemo(() => {
    if (!data) return [];
    const cc = data.lucky.total_close_calls;
    const missed = data.overview.total_missed;
    if (cc + missed === 0) return [];
    return [
      { name: "Close call — made it", value: cc, fill: "oklch(0.64 0.17 150)" },
      { name: "Missed", value: missed, fill: "oklch(0.58 0.22 25)" },
    ];
  }, [data]);

  const [stationSort, setStationSort] = useState<"pct" | "impact">("impact");

  // Stations sorted by selected metric for "worst stations" section
  const allStations = useMemo(() => {
    if (!data) return [];
    return [...data.stations]
      .filter((s) => s.planned >= 50)
      .sort((a, b) => stationSort === "impact"
        ? b.impact_score - a.impact_score
        : b.pct_missed - a.pct_missed);
  }, [data, stationSort]);

  const [stationSearch, setStationSearch] = useState("");
  const [stationPage, setStationPage] = useState(0);
  const STATIONS_PER_PAGE = 10;

  const filteredStations = useMemo(() => {
    if (!stationSearch.trim()) return allStations;
    const q = stationSearch.trim().toUpperCase();
    return allStations.filter((s) => s.name.includes(q));
  }, [allStations, stationSearch]);

  const stationPageCount = Math.ceil(filteredStations.length / STATIONS_PER_PAGE);
  const pagedStations = filteredStations.slice(stationPage * STATIONS_PER_PAGE, (stationPage + 1) * STATIONS_PER_PAGE);

  // Reset page when search changes
  useEffect(() => { setStationPage(0); }, [stationSearch]);

  // For backward compat
  const worstByPct = allStations.slice(0, 10);

  const [dominoSearch, setDominoSearch] = useState("");
  const [dominoPage, setDominoPage] = useState(0);
  const DOMINO_PER_PAGE = 10;

  const filteredDominos = useMemo(() => {
    if (!data) return [];
    const all = data.domino_trains;
    if (!dominoSearch.trim()) return all;
    const q = dominoSearch.trim().toUpperCase();
    return all.filter((dt) => dt.train.includes(q) || dt.relation.toUpperCase().includes(q)
      || dt.stations_affected.some((s) => s.includes(q)));
  }, [data, dominoSearch]);

  const dominoPageCount = Math.ceil(filteredDominos.length / DOMINO_PER_PAGE);
  const pagedDominos = filteredDominos.slice(dominoPage * DOMINO_PER_PAGE, (dominoPage + 1) * DOMINO_PER_PAGE);

  useEffect(() => { setDominoPage(0); }, [dominoSearch]);

  const exportPdf = () => {
    window.print();
  };

  const ov = data?.overview;

  return (
    <div className="flex flex-row min-h-screen bg-background print:bg-white">
      <div className={cn("flex-1 min-h-screen transition-all duration-300", chatOpen && "max-w-[calc(100%-400px)]")} id="report">
      {/* Top bar */}
      <header className="sticky top-0 z-50 glass border-b border-white/20 print:hidden">
        <div className="max-w-4xl mx-auto px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Link2 className="w-4 h-4 text-primary" />
            <span className="text-sm font-semibold tracking-tight">
              Missed Connections Report
            </span>
          </div>
          <div className="flex items-center gap-3">
            {data && !data.error && (
              <button
                onClick={exportPdf}
                className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
              >
                <Download className="w-3.5 h-3.5" />
                PDF
              </button>
            )}
            {data && !data.error && (
              <button
                onClick={() => setChatOpen(!chatOpen)}
                className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
              >
                <MessageCircle className="w-3.5 h-3.5" />
                Chat
              </button>
            )}
            <button
              onClick={() => setSettingsOpen(!settingsOpen)}
              className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
            >
              <Settings2 className="w-3.5 h-3.5" />
              Settings
              <ChevronDown
                className={cn(
                  "w-3 h-3 transition-transform",
                  settingsOpen && "rotate-180",
                )}
              />
            </button>
          </div>
        </div>
        {settingsOpen && (
          <div className="border-t border-border/30 bg-card/80 backdrop-blur animate-slide-up">
            <div className="max-w-4xl mx-auto px-4 py-4">
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <div>
                  <Label>From</Label>
                  <Input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} className="h-8 text-xs mt-1" />
                </div>
                <div>
                  <Label>To</Label>
                  <Input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} className="h-8 text-xs mt-1" />
                </div>
                <div>
                  <Label>Transfer window</Label>
                  <div className="flex gap-1.5 mt-1 items-center">
                    <Input type="number" value={minTransfer} min={1} max={10} onChange={(e) => setMinTransfer(+e.target.value)} className="h-8 text-xs w-16" />
                    <span className="text-xs text-muted-foreground">to</span>
                    <Input type="number" value={maxTransfer} min={5} max={60} onChange={(e) => setMaxTransfer(+e.target.value)} className="h-8 text-xs w-16" />
                    <span className="text-[10px] text-muted-foreground">min</span>
                  </div>
                </div>
                <div>
                  <Label>Hours</Label>
                  <div className="flex gap-1.5 mt-1 items-center">
                    <Input type="number" value={hourStart} min={0} max={24} onChange={(e) => setHourStart(+e.target.value)} className="h-8 text-xs w-16" />
                    <span className="text-xs text-muted-foreground">to</span>
                    <Input type="number" value={hourEnd} min={0} max={24} onChange={(e) => setHourEnd(+e.target.value)} className="h-8 text-xs w-16" />
                  </div>
                </div>
                <div>
                  <Label>Close call threshold</Label>
                  <div className="flex gap-1.5 mt-1 items-center">
                    <Input type="number" value={closeCallSec} min={30} max={600} step={30} onChange={(e) => setCloseCallSec(+e.target.value)} className="h-8 text-xs w-20" />
                    <span className="text-[10px] text-muted-foreground">sec</span>
                  </div>
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-4 mt-3">
                <div className="flex items-center gap-1.5">
                  <Label className="text-[10px]">Days</Label>
                  {["Mo","Tu","We","Th","Fr","Sa","Su"].map((d, i) => (
                    <button
                      key={i}
                      onClick={() => setWeekdays(prev => prev.includes(i) ? prev.filter(x => x !== i) : [...prev, i].sort())}
                      className={cn(
                        "h-7 w-7 rounded-md text-[10px] font-medium transition-all cursor-pointer",
                        weekdays.includes(i)
                          ? "bg-primary text-primary-foreground shadow-sm"
                          : "bg-muted/50 text-muted-foreground hover:bg-muted",
                      )}
                    >{d}</button>
                  ))}
                </div>
                <div className="flex items-center gap-3 text-xs text-muted-foreground">
                  <label className="flex items-center gap-1.5 cursor-pointer">
                    <Switch checked={excludePub} onCheckedChange={setExcludePub} />
                    <span>Excl. public holidays</span>
                  </label>
                  <label className="flex items-center gap-1.5 cursor-pointer">
                    <Switch checked={excludeSch} onCheckedChange={setExcludeSch} />
                    <span>Excl. school holidays</span>
                  </label>
                </div>
              </div>
              <button
                onClick={() => { generate(); setSettingsOpen(false); }}
                disabled={isFetching}
                className="mt-3 px-6 py-2 rounded-xl text-xs font-semibold text-white bg-primary hover:bg-primary/90 disabled:opacity-50 transition-colors cursor-pointer flex items-center gap-2"
              >
                <Sparkles className="w-3.5 h-3.5" /> Generate Report
              </button>
            </div>
          </div>
        )}
      </header>

      <main className="max-w-4xl mx-auto px-4">
        {/* Landing */}
        {!data && !isFetching && !error && (
          <div className="flex flex-col items-center justify-center min-h-[80vh] text-center">
            <div className="w-20 h-20 rounded-3xl bg-gradient-to-br from-primary/10 to-destructive/10 flex items-center justify-center mb-6">
              <Link2 className="w-10 h-10 text-primary/60" />
            </div>
            <h1 className="text-4xl md:text-5xl font-black tracking-tight mb-3">Missed Connections</h1>
            <p className="text-muted-foreground max-w-md mb-8">
              How delays break thousands of planned transfers across Belgium's rail network — and what it costs commuters.
            </p>
            <button onClick={generate} className="px-8 py-3 rounded-2xl text-sm font-semibold text-white bg-primary hover:bg-primary/90 transition-colors cursor-pointer flex items-center gap-2 shadow-lg shadow-primary/20">
              <Sparkles className="w-4 h-4" /> Generate Report
            </button>
            <p className="text-[10px] text-muted-foreground/50 mt-3">Last 7 days by default</p>
          </div>
        )}

        {isFetching && (
          <div className="flex flex-col items-center justify-center min-h-[80vh] animate-slide-up">
            <Link2 className="h-10 w-10 text-primary/40 mb-4 animate-pulse" />
            {progress ? (
              <>
                <div className="w-64 h-2 rounded-full bg-muted overflow-hidden mb-2">
                  <div
                    className="h-full rounded-full bg-primary transition-all duration-300 ease-out"
                    style={{ width: `${Math.round((progress.done / progress.total) * 100)}%` }}
                  />
                </div>
                <p className="text-sm text-muted-foreground">
                  {progress.phase === "chunk"
                    ? `Analyzing chunk ${progress.done} of ${progress.total}...`
                    : progress.phase === "merge"
                      ? "Merging results..."
                      : progress.phase === "process"
                        ? `Processing step ${progress.done} of ${progress.total}...`
                        : `Fetching day ${progress.done} of ${progress.total}...`}
                </p>
              </>
            ) : (
              <p className="text-sm text-muted-foreground">Preparing analysis...</p>
            )}
          </div>
        )}

        {error && <div className="py-20"><ErrorAlert message={error} /></div>}
        {data?.error && <div className="py-20"><ErrorAlert message={data.error} /></div>}

        {/* ===== REPORT ===== */}
        {data && !data.error && !isFetching && ov && (
          <article className="pb-32 print:pb-8">

            {/* ── HERO ── */}
            <section className="min-h-[85vh] print:min-h-0 flex flex-col items-center justify-center text-center pt-8 relative">
              <div className="absolute inset-0 overflow-hidden pointer-events-none print:hidden">
                <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[700px] h-[700px] rounded-full bg-gradient-to-br from-destructive/[0.03] via-transparent to-primary/[0.02] blur-3xl" />
              </div>
              <div className="relative">
                <p className="text-[11px] uppercase tracking-[0.25em] text-muted-foreground/40 font-medium mb-8 print:mb-4">
                  Belgian Rail Network Analysis
                </p>
                <h1 className={cn(
                  "text-[6rem] md:text-[8rem] font-black tracking-tighter leading-[0.85] text-destructive transition-all duration-[2s] ease-out",
                  heroVisible ? "opacity-100 translate-y-0 blur-0" : "opacity-0 translate-y-6 blur-sm",
                )}>
                  <Counter end={ov.total_missed} visible={heroVisible} duration={2500} />
                </h1>
                <p className={cn(
                  "text-2xl md:text-3xl font-light text-muted-foreground/70 tracking-wide mt-2 mb-12 transition-all duration-1000 delay-300",
                  heroVisible ? "opacity-100" : "opacity-0",
                )}>
                  broken connections
                </p>

                <div className={cn(
                  "inline-flex items-center gap-1 text-xs text-muted-foreground/50 bg-muted/50 rounded-full px-4 py-1.5 mb-10 transition-all duration-700 delay-700",
                  heroVisible ? "opacity-100" : "opacity-0",
                )}>
                  {ov.start_date} — {ov.end_date}
                  <span className="mx-1.5 text-border">·</span>
                  {ov.n_days} days
                </div>

                <div className={cn(
                  "grid grid-cols-3 gap-8 md:gap-20 max-w-2xl mx-auto transition-all duration-1000 delay-500",
                  heroVisible ? "opacity-100 translate-y-0" : "opacity-0 translate-y-4",
                )}>
                  <Stat value={<Counter end={ov.total_connections} visible={heroVisible} duration={2000} />} label="planned" />
                  <Stat value={<><Counter end={ov.pct_missed} visible={heroVisible} decimals={1} suffix="%" duration={2000} /></>} label="failure rate" danger />
                  <Stat value={<Counter end={ov.close_calls} visible={heroVisible} duration={2000} />} label="close calls" subtle />
                </div>

                <ChevronDown className="w-5 h-5 text-muted-foreground/20 animate-scroll-bounce mx-auto mt-16 print:hidden" />
              </div>
            </section>

            {/* ── NARRATIVE LEAD ── */}
            <StorySection className="mt-20 print:mt-8">
              <div className="max-w-2xl mx-auto text-center">
                <p className="text-lg md:text-xl leading-relaxed text-foreground/80">
                  Every day, <strong>{fmt(Math.round(ov.total_connections / ov.n_days))}</strong> train-to-train
                  connections are scheduled across Belgium.
                  <span className="text-destructive font-semibold"> {fmt(Math.round(ov.total_missed / ov.n_days))}</span> break
                  because the arriving train is too late for the departing one —
                  stranding passengers on the platform.
                </p>
              </div>
            </StorySection>

            {/* ── WHEN ── */}
            <StorySection id="when" className="mt-28 print:mt-12">
              <Heading>When connections break</Heading>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
                <Card>
                  <CardLabel>By hour of day</CardLabel>
                  <ResponsiveContainer width="100%" height={220}>
                    <BarChart data={hourlyData} margin={{ top: 8, right: 8, bottom: 4, left: -8 }}>
                      <XAxis dataKey="label" tick={{ fontSize: 9 }} interval={1} />
                      <YAxis tick={{ fontSize: 10 }} tickFormatter={(v) => `${v}%`} />
                      <Tooltip contentStyle={TT} formatter={(v: number) => [`${v}%`, "Miss rate"]} />
                      <Bar dataKey="pct" radius={[3, 3, 0, 0]}>
                        {hourlyData.map((h, i) => (
                          <Cell key={i} fill={h.isRush ? "oklch(0.58 0.22 25)" : "oklch(0.65 0.08 260)"} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                  {rushPct.rush > 0 && (
                    <Callout>
                      Rush hour (7-9 &amp; 17-19): <b className="text-destructive">{rushPct.rush}%</b> vs <b>{rushPct.off}%</b> off-peak
                    </Callout>
                  )}
                </Card>
                <Card>
                  <CardLabel>By day of week</CardLabel>
                  <ResponsiveContainer width="100%" height={220}>
                    <BarChart data={data.dow_summary.filter((d) => d.planned > 0)} margin={{ top: 8, right: 8, bottom: 4, left: -8 }}>
                      <XAxis dataKey="label" tick={{ fontSize: 10 }} />
                      <YAxis tick={{ fontSize: 10 }} tickFormatter={(v) => `${v}%`} />
                      <Tooltip contentStyle={TT} formatter={(v: number) => [`${v}%`, "Miss rate"]} />
                      <Bar dataKey="pct" fill="oklch(0.65 0.08 260)" radius={[4, 4, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </Card>
              </div>
              {data.daily.length > 3 && (
                <Card className="mt-5">
                  <CardLabel>Daily trend</CardLabel>
                  <ResponsiveContainer width="100%" height={160}>
                    <AreaChart data={data.daily.filter((d) => d.planned > 0)} margin={{ top: 8, right: 8, bottom: 4, left: -8 }}>
                      <defs>
                        <linearGradient id="dG" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%" stopColor="oklch(0.58 0.22 25)" stopOpacity={0.25} />
                          <stop offset="95%" stopColor="oklch(0.58 0.22 25)" stopOpacity={0} />
                        </linearGradient>
                      </defs>
                      <XAxis dataKey="date" tick={{ fontSize: 9 }} tickFormatter={(v) => v.slice(5)} />
                      <YAxis tick={{ fontSize: 10 }} tickFormatter={(v) => `${v}%`} />
                      <Tooltip contentStyle={TT} formatter={(v: number) => [`${v}%`, "Miss rate"]} />
                      <Area type="monotone" dataKey="pct" stroke="oklch(0.58 0.22 25)" fill="url(#dG)" strokeWidth={2} />
                    </AreaChart>
                  </ResponsiveContainer>
                </Card>
              )}
              {rushPct.rush > 0 && rushPct.off > 0 && (
                <Callout>
                  {rushPct.rush > rushPct.off
                    ? <>Connections are <b className="text-destructive">{((rushPct.rush / rushPct.off - 1) * 100).toFixed(0)}% more likely</b> to break during rush hour — peak congestion cascades through the network.</>
                    : <>Surprisingly, rush hours don't show higher failure rates — delays appear evenly spread throughout the day.</>}
                </Callout>
              )}
            </StorySection>

            {/* ── MAP ── */}
            <StorySection id="map" className="mt-28 print:mt-12">
              <Heading>Where transfers break</Heading>
              <p className="text-sm text-muted-foreground/60 -mt-4 mb-4">
                Size = absolute missed count. Color = blue (few) to red (many).
              </p>
              <DeckMap
                layers={mapLayers}
                className="h-[65vh] print:h-[400px]"
                getTooltip={({ object, layer }: any) => {
                  if (!object || layer?.id !== "rpt") return null;
                  const s = object as ReportStation;
                  return tooltipBox(
                    `<b>${s.name}</b><br/><span style="color:#d32222;font-weight:700">${fmt(s.missed)}</span> missed / ${fmt(s.planned)}<br/>${s.pct_missed}% failure`,
                  );
                }}
              />
              <div className="flex items-center justify-between text-[10px] text-muted-foreground/50 px-1 mt-1">
                <span>Few</span>
                <div className="flex-1 mx-3 h-1.5 rounded-full" style={{ background: "linear-gradient(to right, rgb(30,100,200), rgb(255,180,0), rgb(220,20,0))" }} />
                <span>Many</span>
              </div>
            </StorySection>

            {/* ── WORST STATIONS ── */}
            <StorySection id="worst" className="mt-28 print:mt-12 print:break-before-page">
              <Heading>Station rankings</Heading>
              <p className="text-sm text-muted-foreground/60 -mt-4 mb-5">
                {stationSort === "impact"
                  ? <>Ranked by <b>impact score</b> (missed × sqrt(miss rate)) — balances volume and severity.</>
                  : <>Ranked by <b>miss rate</b> — highest percentage of connections missed.</>}
                {" "}Stations with under 50 connections excluded.
                {allStations.length > STATIONS_PER_PAGE && <> Showing {filteredStations.length} of {allStations.length} stations.</>}
              </p>

              {/* Search + sort toggle (hidden in print) */}
              <div className="flex items-center gap-3 mb-4 print:hidden">
                <div className="relative flex-1 max-w-xs">
                  <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground/40" />
                  <input
                    type="text"
                    placeholder="Search station..."
                    value={stationSearch}
                    onChange={(e) => setStationSearch(e.target.value)}
                    className="w-full h-9 pl-9 pr-3 text-xs rounded-xl border border-border/40 bg-card focus:outline-none focus:ring-1 focus:ring-primary/30"
                  />
                </div>
                <div className="flex items-center rounded-lg border border-border/40 overflow-hidden text-[10px] shrink-0">
                  <button
                    onClick={() => setStationSort("impact")}
                    className={cn("px-2.5 py-1.5 transition-colors cursor-pointer", stationSort === "impact" ? "bg-primary text-primary-foreground" : "bg-card text-muted-foreground hover:bg-muted/50")}
                  >Impact</button>
                  <button
                    onClick={() => setStationSort("pct")}
                    className={cn("px-2.5 py-1.5 transition-colors cursor-pointer", stationSort === "pct" ? "bg-primary text-primary-foreground" : "bg-card text-muted-foreground hover:bg-muted/50")}
                  >Miss rate</button>
                </div>
                <span className="text-[10px] text-muted-foreground/40">{filteredStations.length} result{filteredStations.length !== 1 ? "s" : ""}</span>
              </div>

              <div className="space-y-3">
                {pagedStations.map((st, i) => (
                  <StationRow key={st.name} station={st} rank={stationPage * STATIONS_PER_PAGE + i + 1} maxPct={allStations[0]?.pct_missed ?? 1} />
                ))}
              </div>

              {/* Pagination (hidden in print) */}
              {stationPageCount > 1 && (
                <div className="flex items-center justify-center gap-2 mt-4 print:hidden">
                  <button
                    onClick={() => setStationPage((p) => Math.max(0, p - 1))}
                    disabled={stationPage === 0}
                    className="h-8 px-3 rounded-lg text-xs border border-border/40 bg-card disabled:opacity-30 hover:bg-muted cursor-pointer disabled:cursor-default"
                  >
                    Previous
                  </button>
                  <span className="text-xs text-muted-foreground tabular-nums">
                    {stationPage + 1} / {stationPageCount}
                  </span>
                  <button
                    onClick={() => setStationPage((p) => Math.min(stationPageCount - 1, p + 1))}
                    disabled={stationPage >= stationPageCount - 1}
                    className="h-8 px-3 rounded-lg text-xs border border-border/40 bg-card disabled:opacity-30 hover:bg-muted cursor-pointer disabled:cursor-default"
                  >
                    Next
                  </button>
                </div>
              )}

              {worstByPct.length > 0 && !stationSearch && stationPage === 0 && (
                <Callout>
                  {worstByPct[0].name} tops the list at <b className="text-destructive">{worstByPct[0].pct_missed}%</b> failure rate.
                  {worstByPct.length >= 3 && <> The top 3 stations alone account for{" "}
                  <b className="text-foreground">{fmt(worstByPct.slice(0, 3).reduce((s, st) => s + st.missed, 0))}</b> missed connections.</>}
                </Callout>
              )}
            </StorySection>

            {/* ── HUB SPOTLIGHT ── */}
            {data.hub_spotlight.length > 0 && (
              <StorySection id="hubs" className="mt-28 print:mt-12 print:break-before-page">
                <Heading>Hub station spotlight</Heading>
                <p className="text-sm text-muted-foreground/60 -mt-4 mb-5">
                  Deep dive into the top 5 stations by connection volume — when do they fail, and which trains cause the most damage?
                </p>
                <div className="space-y-6">
                  {data.hub_spotlight.map((hub) => (
                    <HubCard key={hub.station} hub={hub} />
                  ))}
                </div>
              </StorySection>
            )}

            {/* ── CROSS-BELGIUM CORRIDORS ── */}
            {data.corridors.length > 0 && (
              <StorySection id="corridors" className="mt-28 print:mt-12">
                <Heading>Cross-Belgium corridors</Heading>
                <p className="text-sm text-muted-foreground/60 -mt-4 mb-5">
                  City-to-city journeys that transfer through Brussels — how reliable is the connection?
                </p>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {data.corridors.map((cr) => (
                    <Card key={`${cr.origin}-${cr.destination}`}>
                      <div className="flex items-start justify-between mb-2">
                        <div>
                          <p className="text-base font-bold tracking-tight">
                            {titleCase(cr.origin)} → {titleCase(cr.destination)}
                          </p>
                          <p className="text-[10px] text-muted-foreground/40">via {cr.via}</p>
                        </div>
                        <div className={cn(
                          "text-3xl font-black leading-none",
                          cr.pct_missed > 15 ? "text-destructive" : cr.pct_missed > 8 ? "text-warning" : "text-success",
                        )}>
                          {cr.reliability_pct.toFixed(0)}%
                        </div>
                      </div>
                      <div className="h-2 rounded-full bg-muted overflow-hidden mb-3">
                        <div className="h-full rounded-full bg-destructive/70" style={{ width: `${Math.min(cr.pct_missed * 2, 100)}%` }} />
                      </div>
                      <div className="grid grid-cols-3 text-center gap-2 mb-2">
                        <MiniStat value={fmt(cr.missed)} label={`of ${fmt(cr.planned)}`} />
                        <MiniStat value={`${cr.avg_added_wait_min.toFixed(0)}m`} label="avg wait" />
                        <MiniStat value={`${cr.pct_missed.toFixed(1)}%`} label="miss rate" danger={cr.pct_missed > 10} />
                      </div>
                      {cr.worst_hours.length > 0 && (
                        <div className="flex gap-1.5 mt-1">
                          {cr.worst_hours.map((wh) => (
                            <span key={wh.hour} className="text-[9px] bg-destructive/[0.06] text-destructive/80 rounded-md px-1.5 py-0.5 font-medium">
                              {wh.hour}h: {wh.pct}%
                            </span>
                          ))}
                        </div>
                      )}
                    </Card>
                  ))}
                </div>
                <Callout>
                  {(() => {
                    const worst = [...data.corridors].sort((a, b) => b.pct_missed - a.pct_missed)[0];
                    const best = [...data.corridors].sort((a, b) => a.pct_missed - b.pct_missed)[0];
                    if (!worst || !best) return null;
                    return <>
                      Worst corridor: <b className="text-destructive">{titleCase(worst.origin)} → {titleCase(worst.destination)}</b> at {worst.pct_missed}% failure.
                      {best.pct_missed < worst.pct_missed && <> Best: <b className="text-success">{titleCase(best.origin)} → {titleCase(best.destination)}</b> at {best.pct_missed}%.</>}
                    </>;
                  })()}
                </Callout>
              </StorySection>
            )}

            {/* ── DOMINO TRAINS ── */}
            {data.domino_trains.length > 0 && (
              <StorySection id="domino" className="mt-28 print:mt-12">
                <Heading>Domino trains</Heading>
                <p className="text-sm text-muted-foreground/60 -mt-4 mb-5">
                  The arriving trains that cause the most cascading missed connections. A single chronically late service can break dozens of transfers.
                </p>
                {/* Search (hidden in print) */}
                <div className="flex items-center gap-3 mb-4 print:hidden">
                  <div className="relative flex-1 max-w-xs">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground/40" />
                    <input
                      type="text"
                      placeholder="Search train number, route, or station..."
                      value={dominoSearch}
                      onChange={(e) => setDominoSearch(e.target.value)}
                      className="w-full h-9 pl-9 pr-3 text-xs rounded-xl border border-border/40 bg-card focus:outline-none focus:ring-1 focus:ring-primary/30"
                    />
                  </div>
                  <span className="text-[10px] text-muted-foreground/40">{filteredDominos.length} result{filteredDominos.length !== 1 ? "s" : ""}</span>
                </div>

                <div className="space-y-2">
                  {pagedDominos.map((dt, i) => {
                    const maxMissed = data.domino_trains[0]?.total_missed_caused ?? 1;
                    const barW = Math.max((dt.total_missed_caused / maxMissed) * 100, 4);
                    return (
                      <div key={dt.train} className="rounded-2xl border border-border/40 bg-card px-5 py-3 shadow-sm">
                        <div className="flex items-center gap-4">
                          <span className="text-lg font-black text-muted-foreground/30 w-6 text-right shrink-0">{dominoPage * 10 + i + 1}</span>
                          <div className="flex-1 min-w-0">
                            <div className="flex items-baseline justify-between mb-1.5">
                              <div className="min-w-0">
                                <div className="flex items-center gap-2">
                                  {dt.relation ? (
                                    <>
                                      <span className="text-sm font-bold">{dt.relation}</span>
                                      <span className="font-mono text-[10px] text-muted-foreground/50">#{dt.train}</span>
                                    </>
                                  ) : (
                                    <span className="font-mono text-sm font-bold">Train #{dt.train}</span>
                                  )}
                                </div>
                                {dt.first_station && dt.last_station && dt.first_station !== dt.last_station && (
                                  <p className="text-[10px] text-muted-foreground/60 mt-0.5 truncate">
                                    {titleCase(dt.first_station)} → {titleCase(dt.last_station)}
                                  </p>
                                )}
                              </div>
                              <span className="text-xl font-black text-destructive tabular-nums ml-2 shrink-0">{fmt(dt.total_missed_caused)}</span>
                            </div>
                            <div className="h-2.5 rounded-full bg-muted/60 overflow-hidden">
                              <div className="h-full rounded-full bg-destructive/70 transition-all duration-700" style={{ width: `${barW}%` }} />
                            </div>
                            <div className="flex items-center gap-3 mt-1.5 text-[10px] text-muted-foreground/50">
                              <span>across <b className="text-foreground/60">{dt.n_stations}</b> station{dt.n_stations > 1 ? "s" : ""}</span>
                              <span>avg <b className="text-foreground/60">{dt.avg_delay_min.toFixed(0)}</b> min late</span>
                              <span>seen <b className="text-foreground/60">{dt.n_days_seen}</b> day{dt.n_days_seen > 1 ? "s" : ""}</span>
                              {dt.stations_affected.length > 0 && (
                                <span className="flex gap-1">
                                  {dt.stations_affected.slice(0, 3).map((s) => (
                                    <span key={s} className="bg-muted/50 rounded px-1 py-0.5 text-[8px]">{s}</span>
                                  ))}
                                </span>
                              )}
                            </div>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>

                {/* Pagination (hidden in print) */}
                {dominoPageCount > 1 && (
                  <div className="flex items-center justify-center gap-2 mt-4 print:hidden">
                    <button
                      onClick={() => setDominoPage((p) => Math.max(0, p - 1))}
                      disabled={dominoPage === 0}
                      className="h-8 px-3 rounded-lg text-xs border border-border/40 bg-card disabled:opacity-30 hover:bg-muted cursor-pointer disabled:cursor-default"
                    >
                      Previous
                    </button>
                    <span className="text-xs text-muted-foreground tabular-nums">
                      {dominoPage + 1} / {dominoPageCount}
                    </span>
                    <button
                      onClick={() => setDominoPage((p) => Math.min(dominoPageCount - 1, p + 1))}
                      disabled={dominoPage >= dominoPageCount - 1}
                      className="h-8 px-3 rounded-lg text-xs border border-border/40 bg-card disabled:opacity-30 hover:bg-muted cursor-pointer disabled:cursor-default"
                    >
                      Next
                    </button>
                  </div>
                )}

                <Callout>
                  The top {Math.min(data.domino_trains.length, 10)} trains alone caused{" "}
                  <b className="text-destructive">{fmt(data.domino_trains.slice(0, 10).reduce((s, dt) => s + dt.total_missed_caused, 0))}</b>{" "}
                  missed connections — {(() => {
                    const topSum = data.domino_trains.slice(0, 10).reduce((s, dt) => s + dt.total_missed_caused, 0);
                    const pct = ov.total_missed > 0 ? (topSum / ov.total_missed * 100).toFixed(0) : "0";
                    return <><b>{pct}%</b> of the total. Improving punctuality on these services would have outsized impact.</>;
                  })()}
                </Callout>
              </StorySection>
            )}

                        {/* ── COMMUTER IMPACT ── */}
            {data.key_routes.length > 0 && (
              <StorySection id="commuter" className="mt-28 print:mt-12">
                <Heading>The commuter cost</Heading>
                <p className="text-sm text-muted-foreground/60 -mt-4 mb-5">
                  How missed connections affect Belgium's busiest rail corridors.
                </p>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {data.key_routes.map((kr) => (
                    <Card key={`${kr.origin}-${kr.destination}`}>
                      <div className="flex items-start justify-between mb-2">
                        <div>
                          <p className="text-base font-bold tracking-tight">
                            {titleCase(kr.origin)} → {titleCase(kr.destination)}
                          </p>
                        </div>
                        <div className={cn(
                          "text-3xl font-black leading-none",
                          kr.pct_missed > 12 ? "text-destructive" : kr.pct_missed > 5 ? "text-warning" : "text-success",
                        )}>
                          {(100 - kr.pct_missed).toFixed(0)}%
                        </div>
                      </div>
                      <div className="h-2 rounded-full bg-muted overflow-hidden mb-4">
                        <div className="h-full rounded-full bg-destructive/70" style={{ width: `${kr.pct_missed}%` }} />
                      </div>
                      <div className="grid grid-cols-3 text-center gap-2">
                        <MiniStat value={fmt(kr.missed)} label="missed" />
                        <MiniStat value={`${kr.avg_added_wait_min.toFixed(0)}m`} label="avg wait" />
                        <MiniStat value={`${kr.yearly_loss_hours.toFixed(0)}h`} label="lost/year*" danger />
                      </div>
                    </Card>
                  ))}
                </div>
                <p className="text-[10px] text-muted-foreground/30 mt-2">* Projected over 220 working days</p>
              </StorySection>
            )}

            {/* ── CLOSE CALLS & WAIT ── */}
            <StorySection id="close-calls" className="mt-28 print:mt-12">
              <Heading>Close calls & waiting</Heading>
              <p className="text-sm text-muted-foreground/60 -mt-4 mb-5">
                A <b className="text-foreground/70">close call</b> is a connection where the passenger made
                the transfer, but with less than {closeCallSec < 60 ? `${closeCallSec} seconds` : `${Math.round(closeCallSec / 60)} minute${closeCallSec >= 120 ? "s" : ""}`} to spare between actual arrival and actual departure.
              </p>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
                <Card className="flex flex-col items-center justify-center text-center py-8">
                  {pieData.length > 0 && (
                    <>
                      <ResponsiveContainer width={180} height={180}>
                        <PieChart>
                          <Pie data={pieData} cx="50%" cy="50%" innerRadius={50} outerRadius={72} paddingAngle={4} dataKey="value">
                            {pieData.map((e, i) => <Cell key={i} fill={e.fill} />)}
                          </Pie>
                          <Tooltip contentStyle={TT} formatter={(v: number) => [fmt(v), ""]} />
                        </PieChart>
                      </ResponsiveContainer>
                      <div className="flex gap-4 text-[10px] text-muted-foreground mt-2 mb-4">
                        <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-success" /> Close call</span>
                        <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-destructive" /> Missed</span>
                      </div>
                    </>
                  )}
                  <p className="text-sm text-muted-foreground leading-relaxed max-w-xs">
                    Of the <b className="text-foreground">{fmt(data.lucky.total_close_calls + ov.total_missed)}</b> connections
                    where timing was tight (&lt; {closeCallSec}s margin),{" "}
                    <b className="text-success">{data.lucky.pct_saved}%</b> still made it
                    and <b className="text-destructive">{(100 - data.lucky.pct_saved).toFixed(1)}%</b> were missed.
                  </p>
                </Card>

                {data.added_wait.histogram.length > 0 && (
                  <Card>
                    <CardLabel>After a missed connection — how long until the next departure?</CardLabel>
                    <p className="text-xs text-muted-foreground/50 mb-1">
                      When a connection is missed, how long before another train leaves from the same station? Measured across {fmt(data.added_wait.n_samples ?? 0)} missed arrivals.
                    </p>
                    <p className="text-xs text-muted-foreground/50 mb-3">
                      Average: <b className="text-foreground">{data.added_wait.avg_wait_min.toFixed(1)} min</b> · Median: <b className="text-foreground">{data.added_wait.median_wait_min.toFixed(1)} min</b>
                    </p>
                    <ResponsiveContainer width="100%" height={200}>
                      <BarChart data={data.added_wait.histogram} margin={{ top: 4, right: 8, bottom: 4, left: -8 }}>
                        <XAxis dataKey="bucket" tick={{ fontSize: 9 }} />
                        <YAxis tick={{ fontSize: 10 }} />
                        <Tooltip contentStyle={TT} formatter={(v: number) => [fmt(v), "Occurrences"]} labelFormatter={(l) => `${l} min`} />
                        <Bar dataKey="count" fill="oklch(0.55 0.12 270)" radius={[4, 4, 0, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  </Card>
                )}
              </div>
            </StorySection>

            {/* ── WEATHER IMPACT ── */}
            {data.weather && data.weather.n_days >= 5 && (
              <StorySection id="weather" className="mt-28 print:mt-12">
                <Heading>Does weather make it worse?</Heading>
                <p className="text-sm text-muted-foreground/60 -mt-4 mb-5">
                  Cross-referencing daily miss rates with weather conditions in Brussels (central Belgium).
                </p>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
                  {/* Precipitation scatter */}
                  <Card>
                    <CardLabel>Precipitation vs miss rate</CardLabel>
                    <ResponsiveContainer width="100%" height={220}>
                      <ScatterChart margin={{ top: 8, right: 8, bottom: 4, left: -8 }}>
                        <XAxis
                          dataKey="precip_mm"
                          type="number"
                          name="Precipitation"
                          unit="mm"
                          tick={{ fontSize: 10 }}
                          label={{ value: "mm", position: "insideBottomRight", offset: -4, fontSize: 9, fill: "var(--color-muted-foreground)" }}
                        />
                        <YAxis
                          dataKey="pct_missed"
                          type="number"
                          name="Miss rate"
                          unit="%"
                          tick={{ fontSize: 10 }}
                          tickFormatter={(v) => `${v}%`}
                        />
                        <ZAxis range={[30, 30]} />
                        <Tooltip
                          contentStyle={TT}
                          formatter={(v: number, name: string) => [
                            name === "Precipitation" ? `${v} mm` : `${v}%`,
                            name === "Precipitation" ? "Rain" : "Miss rate",
                          ]}
                        />
                        <Scatter data={data.weather.daily} fill="oklch(0.55 0.15 250)" fillOpacity={0.6} />
                      </ScatterChart>
                    </ResponsiveContainer>
                    {data.weather.correlations.precipitation !== undefined && (
                      <p className="text-[10px] text-muted-foreground/60 mt-1">
                        Correlation: <b className="text-foreground/70">r = {data.weather.correlations.precipitation}</b>{" "}
                        ({corrLabel(data.weather.correlations.precipitation)})
                      </p>
                    )}
                  </Card>

                  {/* Wind scatter */}
                  <Card>
                    <CardLabel>Wind speed vs miss rate</CardLabel>
                    <ResponsiveContainer width="100%" height={220}>
                      <ScatterChart margin={{ top: 8, right: 8, bottom: 4, left: -8 }}>
                        <XAxis
                          dataKey="wind_kmh"
                          type="number"
                          name="Wind"
                          unit="km/h"
                          tick={{ fontSize: 10 }}
                          label={{ value: "km/h", position: "insideBottomRight", offset: -4, fontSize: 9, fill: "var(--color-muted-foreground)" }}
                        />
                        <YAxis
                          dataKey="pct_missed"
                          type="number"
                          name="Miss rate"
                          unit="%"
                          tick={{ fontSize: 10 }}
                          tickFormatter={(v) => `${v}%`}
                        />
                        <ZAxis range={[30, 30]} />
                        <Tooltip
                          contentStyle={TT}
                          formatter={(v: number, name: string) => [
                            name === "Wind" ? `${v} km/h` : `${v}%`,
                            name === "Wind" ? "Wind speed" : "Miss rate",
                          ]}
                        />
                        <Scatter data={data.weather.daily} fill="oklch(0.55 0.15 170)" fillOpacity={0.6} />
                      </ScatterChart>
                    </ResponsiveContainer>
                    {data.weather.correlations.wind !== undefined && (
                      <p className="text-[10px] text-muted-foreground/60 mt-1">
                        Correlation: <b className="text-foreground/70">r = {data.weather.correlations.wind}</b>{" "}
                        ({corrLabel(data.weather.correlations.wind)})
                      </p>
                    )}
                  </Card>
                </div>

                {/* Comparison cards */}
                {Object.keys(data.weather.comparison).length > 0 && (
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mt-5">
                    {data.weather.comparison.rainy_avg_pct !== undefined && (
                      <WeatherCompareCard
                        label="Rain"
                        icon={<CloudRain className="w-4 h-4" />}
                        condA="Rainy days"
                        condB="Dry days"
                        pctA={data.weather.comparison.rainy_avg_pct}
                        pctB={data.weather.comparison.dry_avg_pct}
                        nA={data.weather.comparison.rainy_days}
                        nB={data.weather.comparison.dry_days}
                        thresholdLabel="1+ mm"
                      />
                    )}
                    {data.weather.comparison.windy_avg_pct !== undefined && (
                      <WeatherCompareCard
                        label="Wind"
                        icon={<TrendingDown className="w-4 h-4 rotate-180" />}
                        condA="Windy days"
                        condB="Calm days"
                        pctA={data.weather.comparison.windy_avg_pct}
                        pctB={data.weather.comparison.calm_avg_pct}
                        nA={data.weather.comparison.windy_days}
                        nB={data.weather.comparison.calm_days}
                        thresholdLabel="40+ km/h"
                      />
                    )}
                    {data.weather.comparison.cold_avg_pct !== undefined && (
                      <WeatherCompareCard
                        label="Temperature"
                        icon={<AlertTriangle className="w-4 h-4" />}
                        condA="Cold days"
                        condB="Mild days"
                        pctA={data.weather.comparison.cold_avg_pct}
                        pctB={data.weather.comparison.mild_avg_pct}
                        nA={data.weather.comparison.cold_days}
                        nB={data.weather.comparison.mild_days}
                        thresholdLabel="< 5°C"
                      />
                    )}
                  </div>
                )}
                {(() => {
                  const w = data.weather!;
                  const precip_r = w.correlations.precipitation;
                  const wind_r = w.correlations.wind;
                  const hasRain = w.comparison.rainy_avg_pct !== undefined;
                  const rainDiff = hasRain ? w.comparison.rainy_avg_pct - w.comparison.dry_avg_pct : 0;
                  const strongWeather = (precip_r !== undefined && Math.abs(precip_r) >= 0.3) || (wind_r !== undefined && Math.abs(wind_r) >= 0.3);
                  return (
                    <Callout>
                      {strongWeather
                        ? <>Weather appears to <b className="text-destructive">measurably affect</b> missed connections.
                            {precip_r !== undefined && Math.abs(precip_r) >= 0.3 && <> Precipitation shows a {corrLabel(precip_r)} correlation (r={precip_r}).</>}
                            {wind_r !== undefined && Math.abs(wind_r) >= 0.3 && <> Wind shows a {corrLabel(wind_r)} correlation (r={wind_r}).</>}
                            {hasRain && rainDiff > 0.5 && <> Rainy days see <b>{rainDiff.toFixed(1)}</b> percentage points more failures on average.</>}
                          </>
                        : <>Over this period, weather shows <b>no strong effect</b> on missed connections.
                            {hasRain && Math.abs(rainDiff) <= 0.5
                              ? <> Rainy and dry days have nearly identical miss rates.</>
                              : hasRain && rainDiff > 0
                                ? <> Rainy days are slightly worse (+{rainDiff.toFixed(1)} pp), but the sample is small.</>
                                : null}
                            Delays seem driven more by operational factors than by weather — at least in this time window.
                          </>}
                    </Callout>
                  );
                })()}
                <p className="text-[10px] text-muted-foreground/30 mt-3">
                  Weather data: Open-Meteo archive (Brussels, 50.85°N 4.35°E). Correlation does not imply causation — short periods may show noise.
                </p>
              </StorySection>
            )}

            {/* ── BOTTOM LINE ── */}
            <StorySection id="bottom" className="mt-28 print:mt-12 print:break-before-page">
              <div className="rounded-3xl border border-border/40 bg-gradient-to-b from-muted/20 to-card p-8 md:p-12 text-center">
                <p className="text-[11px] uppercase tracking-[0.2em] text-muted-foreground/40 mb-6">The bottom line</p>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-8 mb-8">
                  <div>
                    <div className="text-4xl md:text-5xl font-black text-destructive">{fmt(ov.total_missed)}</div>
                    <div className="text-[10px] uppercase tracking-widest text-muted-foreground/40 mt-1">connections missed</div>
                  </div>
                  <div>
                    <div className="text-4xl md:text-5xl font-black">{fmt(Math.round(data.added_wait.total_person_wait_min / 60))}<span className="text-xl font-medium text-muted-foreground">h</span></div>
                    <div className="text-[10px] uppercase tracking-widest text-muted-foreground/40 mt-1">total wait added</div>
                  </div>
                  <div>
                    <div className="text-4xl md:text-5xl font-black text-destructive">{fmt(Math.round((data.added_wait.total_person_wait_min / ov.n_days) * 365 / 60))}<span className="text-xl font-medium text-muted-foreground">h</span></div>
                    <div className="text-[10px] uppercase tracking-widest text-muted-foreground/40 mt-1">projected yearly</div>
                  </div>
                </div>
                <p className="text-sm text-muted-foreground/60 max-w-lg mx-auto leading-relaxed">
                  In {ov.n_days} days, passengers collectively waited
                  an estimated <b className="text-foreground">{fmt(Math.round(data.added_wait.total_person_wait_min / 60))} hours</b> for
                  the next train after a broken connection.
                </p>
              </div>
            </StorySection>

            {/* ── WEATHER-SENSITIVE TRAINS ── */}
            {data.weather_sensitive_trains && data.weather_sensitive_trains.length > 0 && (
              <StorySection id="weather-trains" className="mt-28 print:mt-12">
                <Heading>Weather-vulnerable services</Heading>
                <p className="text-sm text-muted-foreground/60 -mt-4 mb-5">
                  Trains whose delays increase the most during rain or wind — candidates for predictive maintenance or schedule padding.
                  Sensitivity = delay in bad weather ÷ delay in good weather (higher = more vulnerable).
                </p>
                <div className="relative mb-3">
                  <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground/40" />
                  <input
                    value={weatherSearch}
                    onChange={(e) => setWeatherSearch(e.target.value)}
                    placeholder="Search by train, relation, or station..."
                    className="w-full bg-muted/30 rounded-lg pl-9 pr-3 py-2 text-xs placeholder:text-muted-foreground/40 focus:outline-none focus:ring-1 focus:ring-primary/30"
                  />
                </div>
                <div className="space-y-2">
                  {(weatherSearch.trim()
                    ? data.weather_sensitive_trains.filter((wt) => {
                        const q = weatherSearch.toLowerCase();
                        return (
                          wt.train.toLowerCase().includes(q) ||
                          (wt.relation && wt.relation.toLowerCase().includes(q)) ||
                          (wt.first_station && wt.first_station.toLowerCase().includes(q)) ||
                          (wt.last_station && wt.last_station.toLowerCase().includes(q))
                        );
                      })
                    : data.weather_sensitive_trains.slice(0, 15)
                  ).map((wt, i) => {
                    const maxSens = data.weather_sensitive_trains![0]?.rain_sensitivity ?? 1;
                    const barW = Math.max((wt.rain_sensitivity / maxSens) * 100, 4);
                    return (
                      <div key={wt.train} className="rounded-2xl border border-border/40 bg-card px-5 py-3 shadow-sm">
                        <div className="flex items-center gap-4">
                          <span className="text-lg font-black text-muted-foreground/30 w-6 text-right shrink-0">{i + 1}</span>
                          <div className="flex-1 min-w-0">
                            <div className="flex items-baseline justify-between mb-1">
                              <div className="min-w-0">
                                <div className="flex items-center gap-2">
                                  {wt.relation ? (
                                    <>
                                      <span className="text-sm font-bold">{wt.relation}</span>
                                      <span className="font-mono text-[10px] text-muted-foreground/50">#{wt.train}</span>
                                    </>
                                  ) : (
                                    <span className="font-mono text-sm font-bold">Train #{wt.train}</span>
                                  )}
                                </div>
                                {wt.first_station && wt.last_station && wt.first_station !== wt.last_station && (
                                  <p className="text-[10px] text-muted-foreground/60 mt-0.5 truncate">
                                    {titleCase(wt.first_station)} → {titleCase(wt.last_station)}
                                  </p>
                                )}
                              </div>
                              <div className="text-right ml-2 shrink-0">
                                <span className="text-xl font-black text-destructive tabular-nums">{wt.rain_sensitivity.toFixed(1)}×</span>
                                <p className="text-[9px] text-muted-foreground/50">rain sensitivity</p>
                              </div>
                            </div>
                            <div className="h-2 rounded-full bg-muted/60 overflow-hidden mb-1.5">
                              <div className="h-full rounded-full bg-blue-500/70 transition-all duration-700" style={{ width: `${barW}%` }} />
                            </div>
                            <div className="flex items-center gap-4 text-[10px] text-muted-foreground/50">
                              <span>🌧 <b className="text-foreground/60">{wt.avg_delay_rainy.toFixed(1)}</b> min avg ({wt.rainy_days}d)</span>
                              <span>☀️ <b className="text-foreground/60">{wt.avg_delay_dry.toFixed(1)}</b> min avg ({wt.dry_days}d)</span>
                              {wt.wind_sensitivity != null && (
                                <span>💨 <b className="text-foreground/60">{wt.wind_sensitivity.toFixed(1)}×</b> wind</span>
                              )}
                              <span>seen <b className="text-foreground/60">{wt.n_days}</b> days</span>
                            </div>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
                <Callout>
                  {(() => {
                    const top = data.weather_sensitive_trains![0];
                    if (!top) return null;
                    return <>
                      Most weather-sensitive: <b className="text-destructive">{top.relation || `Train #${top.train}`}</b> —
                      delays are <b>{top.rain_sensitivity.toFixed(1)}× worse</b> on rainy days
                      ({top.avg_delay_rainy.toFixed(1)} min vs {top.avg_delay_dry.toFixed(1)} min dry).
                    </>;
                  })()}
                </Callout>
              </StorySection>
            )}


            {/* ── OPTIMIZATION: HOW TO IMPROVE ── */}
            {data.optimization && data.optimization.recommendations.length > 0 && (
              <StorySection id="optimization" className="mt-28 print:mt-12 print:break-before-page">
                <Heading>How to improve connections</Heading>
                <p className="text-sm text-muted-foreground/60 -mt-4 mb-6">
                  Network-aware simulation: for each station, we model adding buffer time and trace the ripple effect downstream.
                  Adding buffer saves local connections but delays the departing train, which may cause new misses at later stations.
                  Only recommendations with a <b>positive net benefit</b> are shown.
                </p>

                {/* Key stats */}
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-8">
                  <Card>
                    <p className="text-[10px] text-muted-foreground/50 uppercase tracking-wide">Barely missed</p>
                    <p className="text-2xl font-black mt-1">{data.optimization.barely_missed_pct}%</p>
                    <p className="text-[10px] text-muted-foreground/40 mt-0.5">missed by &lt;3 min</p>
                  </Card>
                  <Card>
                    <p className="text-[10px] text-muted-foreground/50 uppercase tracking-wide">Net saveable</p>
                    <p className="text-2xl font-black text-emerald-600 mt-1">{fmt(data.optimization.total_net_saveable)}</p>
                    <p className="text-[10px] text-muted-foreground/40 mt-0.5">{data.optimization.net_saveable_pct}% of all misses</p>
                  </Card>
                  <Card>
                    <p className="text-[10px] text-muted-foreground/50 uppercase tracking-wide">Total missed</p>
                    <p className="text-2xl font-black mt-1">{fmt(data.optimization.total_missed)}</p>
                    <p className="text-[10px] text-muted-foreground/40 mt-0.5">in analysis period</p>
                  </Card>
                  <Card>
                    <p className="text-[10px] text-muted-foreground/50 uppercase tracking-wide">Top 10 stations</p>
                    <p className="text-2xl font-black mt-1">{data.optimization.recommendations.length}</p>
                    <p className="text-[10px] text-muted-foreground/40 mt-0.5">with positive net benefit</p>
                  </Card>
                </div>

                {/* Buffer sensitivity curve */}
                {data.optimization.buffer_curve.length > 0 && (
                  <Card className="mb-6">
                    <h3 className="text-sm font-semibold mb-1">Buffer sensitivity</h3>
                    <p className="text-[10px] text-muted-foreground/50 mb-3">
                      Miss rate as a function of minimum transfer buffer. Current default: 2 min.
                      Increasing buffer excludes tight connections but those that remain are more reliable.
                    </p>
                    <ResponsiveContainer width="100%" height={220}>
                      <AreaChart data={data.optimization.buffer_curve} margin={{ top: 8, right: 16, bottom: 4, left: 8 }}>
                        <XAxis dataKey="buffer_min" tick={{ fontSize: 10 }} tickFormatter={(v: number) => `${v}m`} />
                        <YAxis tick={{ fontSize: 10 }} domain={[0, "auto"]} tickFormatter={(v: number) => `${v}%`} />
                        <Tooltip contentStyle={TT} formatter={(v: number) => [`${v}%`, "Miss rate"]} labelFormatter={(v: number) => `${v} min buffer`} />
                        <Area dataKey="pct" stroke="hsl(220, 70%, 55%)" fill="hsl(220, 70%, 55%)" fillOpacity={0.15} strokeWidth={2} />
                      </AreaChart>
                    </ResponsiveContainer>
                  </Card>
                )}

                {/* Recommendations */}
                <h3 className="text-lg font-bold mb-3 flex items-center gap-2">
                  <Lightbulb className="w-4 h-4 text-amber-500" />
                  Top recommendations
                </h3>
                <p className="text-[10px] text-muted-foreground/50 mb-4">
                  Each recommendation accounts for downstream propagation: delaying a departing train here
                  means it arrives later at subsequent stations, potentially breaking other connections.
                  Green = net connections saved after accounting for all network effects.
                </p>
                <div className="space-y-2 mb-6">
                  {data.optimization.recommendations.map((rec, i) => {
                    const maxNet = data.optimization!.recommendations[0]?.net_benefit ?? 1;
                    const barW = Math.max((rec.net_benefit / maxNet) * 100, 4);
                    return (
                      <div key={rec.station} className="rounded-2xl border border-border/40 bg-card px-5 py-3 shadow-sm">
                        <div className="flex items-center gap-4">
                          <span className="text-lg font-black text-muted-foreground/30 w-6 text-right shrink-0">{i + 1}</span>
                          <div className="flex-1 min-w-0">
                            <div className="flex items-baseline justify-between mb-1">
                              <div className="min-w-0">
                                <span className="text-sm font-bold">{titleCase(rec.station)}</span>
                                <span className="text-[10px] text-muted-foreground/50 ml-2">+{rec.delta_min} min buffer</span>
                              </div>
                              <div className="text-right ml-2 shrink-0">
                                <span className="text-xl font-black text-emerald-600 tabular-nums">+{rec.net_benefit}</span>
                                <p className="text-[9px] text-muted-foreground/50">net saved</p>
                              </div>
                            </div>
                            <div className="h-2 rounded-full bg-muted/60 overflow-hidden mb-1.5">
                              <div className="h-full rounded-full bg-emerald-500/70 transition-all duration-700" style={{ width: `${barW}%` }} />
                            </div>
                            <div className="flex items-center gap-1 text-[10px] text-muted-foreground/50 flex-wrap">
                              <span className="text-emerald-600 font-semibold">+{rec.saved_local} saved locally</span>
                              <ArrowRight className="w-2.5 h-2.5" />
                              <span className="text-destructive font-semibold">-{rec.new_misses_downstream} broken downstream</span>
                              <ArrowRight className="w-2.5 h-2.5" />
                              <span className="text-emerald-600 font-semibold">+{rec.saved_downstream} saved downstream</span>
                              <span className="ml-auto">({rec.net_pct_of_station}% of station misses)</span>
                            </div>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>

                {/* Quick wins */}
                {data.optimization.quick_wins.length > 0 && (
                  <Card>
                    <h3 className="text-sm font-semibold mb-1">Quick wins — closest misses</h3>
                    <p className="text-[10px] text-muted-foreground/50 mb-3">
                      Specific train-pair connections that were missed by under 2 minutes.
                      These are the easiest to fix with minimal schedule adjustments.
                    </p>
                    <div className="space-y-1.5">
                      {data.optimization.quick_wins.map((qw, i) => (
                        <div key={i} className="flex items-center justify-between text-xs bg-muted/20 rounded-lg px-3 py-2">
                          <div className="flex items-center gap-2 min-w-0">
                            <span className="text-muted-foreground/40 font-bold w-4">{i + 1}</span>
                            <span className="font-medium truncate">{titleCase(qw.station)}</span>
                            <span className="text-[10px] text-muted-foreground/40 font-mono">
                              {qw.arr_train} <ArrowRight className="w-2.5 h-2.5 inline" /> {qw.dep_train}
                            </span>
                          </div>
                          <div className="flex items-center gap-3 shrink-0">
                            <span className="text-amber-600 font-bold">{Math.round(qw.avg_overshoot_sec)}s late</span>
                            <span className="text-muted-foreground/60">{qw.count}× missed</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  </Card>
                )}

                <Callout>
                  By optimizing buffer times at just the top {data.optimization.recommendations.length} stations
                  (accounting for network propagation effects),
                  we could save an estimated <b className="text-emerald-600">{fmt(data.optimization.total_net_saveable)} connections</b> ({data.optimization.net_saveable_pct}% of all misses).
                  {data.optimization.barely_missed_pct > 30 && <> Notably, <b>{data.optimization.barely_missed_pct}%</b> of all missed connections
                  were missed by less than 3 minutes — small schedule adjustments could have large effects.</>}
                </Callout>
              </StorySection>
            )}

            {/* ── METHODOLOGY ── */}
            <StorySection className="mt-16 print:mt-8">
              <details className="rounded-2xl border border-border/40 bg-card">
                <summary className="px-5 py-3 text-xs font-medium text-muted-foreground cursor-pointer select-none flex items-center gap-2">
                  <span className="text-[10px]">i</span> How this is computed
                </summary>
                <div className="px-5 pb-4 text-xs text-muted-foreground/70 leading-relaxed space-y-3 border-t border-border/20 pt-3">
                  <p className="font-semibold text-foreground/60">Connection Detection</p>
                  <p>A <b>connection</b> is any pair of different trains stopping at the same station where the planned gap between arrival and departure falls within the <b>transfer window</b> (default 2-15 min). This is a structural measure: it captures all <i>possible</i> connections, not just those passengers actually intended to make. At large hubs like Brussels-Midi, this produces many pairs — which inflates absolute counts but keeps percentages valid for comparison.</p>
                  <p>A connection is <b>missed</b> when the arriving train's actual arrival time exceeds the departing train's actual departure time — meaning the departing train has already left.</p>

                  <p className="font-semibold text-foreground/60 pt-2">What We Don't Know</p>
                  <p>We don't have passenger origin-destination data. This means: (1) we can't tell if passengers <i>intended</i> a connection, (2) if a missed train to Ghent is followed by another Ghent train 10 min later, we still count the miss, (3) we can't weight by actual passenger counts.</p>

                  <p className="font-semibold text-foreground/60 pt-2">Impact Score</p>
                  <p>To approximate passenger impact without OD data, each station is weighted by its <b>daily train frequency</b> (number of train stops per day). The <b>impact score</b> = missed connections × (station demand / max demand). Stations with more trains serve more passengers, so a missed connection there affects more people. This is a proxy — the real multiplier would be passenger counts, which SNCB doesn't publish.</p>

                  <p className="font-semibold text-foreground/60 pt-2">Close Calls, Wait Times & Other Metrics</p>
                  <p><b>Close call</b> = connection made with less than {closeCallSec}s to spare. <b>Wait time</b> = time until the next departing train at the same station after a missed connection (any train, any direction, capped at 2h) — this is a lower bound since the actual wait for a specific destination may be longer. <b>Toxic arrivals</b> = late trains that cause multiple downstream missed connections. <b>Corridors</b> = cross-Belgium journeys via Brussels, combining a leg A train and a leg B train through Brussels stations.</p>

                  <p className="font-semibold text-foreground/60 pt-2">Data Source & Limitations</p>
                  <p>Train data: Infrabel real-time punctuality feed, filtered to SNCB/NMBS trains only. Weather: Open-Meteo archive API (Brussels coordinates). Yearly projections assume 220 working days. All figures represent connection <i>pairs</i>, not individual passengers. The analysis runs entirely in DuckDB with vectorized SQL queries across all selected dates.</p>
                </div>
              </details>
            </StorySection>

          </article>
        )}
      </main>

      {/* Print styles */}
      <style>{`
        @media print {
          header, .animate-scroll-bounce, button { display: none !important; }
          section { opacity: 1 !important; transform: none !important; }
          .maplibregl-canvas-container { height: 400px !important; }
        }
      `}</style>
      </div>
      {chatOpen && data && (
        <div className="w-[400px] h-screen sticky top-0 shrink-0 print:hidden animate-slide-in-right">
          <ReportChatbot reportData={data as unknown as Record<string, unknown>} onClose={() => setChatOpen(false)} />
        </div>
      )}
    </div>
  );
}

/* ── Tiny components ── */

function Heading({ children }: { children: React.ReactNode }) {
  return <h2 className="text-2xl md:text-3xl font-black tracking-tight mb-6">{children}</h2>;
}

function Card({ children, className }: { children: React.ReactNode; className?: string }) {
  return <div className={cn("rounded-2xl border border-border/40 bg-card p-5 shadow-sm", className)}>{children}</div>;
}

function CardLabel({ children }: { children: React.ReactNode }) {
  return <h3 className="text-sm font-semibold text-foreground/80 mb-3">{children}</h3>;
}

function Callout({ children }: { children: React.ReactNode }) {
  return <div className="mt-3 p-3 rounded-xl bg-destructive/[0.04] border border-destructive/10 text-xs text-muted-foreground">{children}</div>;
}

function Stat({ value, label, danger, subtle }: { value: React.ReactNode; label: string; danger?: boolean; subtle?: boolean }) {
  return (
    <div className="text-center">
      <div className={cn("text-3xl md:text-4xl font-black tracking-tight", danger ? "text-destructive" : subtle ? "text-muted-foreground" : "text-foreground/80")}>{value}</div>
      <div className="text-[10px] uppercase tracking-widest text-muted-foreground/40 mt-1">{label}</div>
    </div>
  );
}

function MiniStat({ value, label, danger }: { value: string; label: string; danger?: boolean }) {
  return (
    <div>
      <div className={cn("text-lg font-bold", danger && "text-destructive")}>{value}</div>
      <div className="text-[9px] text-muted-foreground/50">{label}</div>
    </div>
  );
}

/* ── Station row (visual bar-based design) ── */

function StationRow({ station, rank, maxPct }: { station: ReportStation; rank: number; maxPct: number }) {
  const [expanded, setExpanded] = useState(false);
  const barWidth = Math.max((station.pct_missed / maxPct) * 100, 4);
  const dangerLevel = station.pct_missed > 15 ? "text-destructive" : station.pct_missed > 8 ? "text-warning" : "text-foreground/70";

  return (
    <div className="rounded-2xl border border-border/40 bg-card px-5 py-4 shadow-sm">
      <div className="flex items-center gap-4">
        {/* Rank */}
        <span className="text-lg font-black text-muted-foreground/30 w-6 text-right shrink-0">
          {rank}
        </span>

        {/* Main content */}
        <div className="flex-1 min-w-0">
          <div className="flex items-baseline justify-between mb-2">
            <span className="text-sm font-semibold truncate">{station.name}</span>
            <span className={cn("text-xl font-black tabular-nums ml-2 shrink-0", dangerLevel)}>
              {station.pct_missed}%
            </span>
          </div>

          {/* Visual bar */}
          <div className="h-3 rounded-full bg-muted/60 overflow-hidden">
            <div
              className="h-full rounded-full transition-all duration-700"
              style={{
                width: `${barWidth}%`,
                background: station.pct_missed > 15
                  ? "oklch(0.58 0.22 25)"
                  : station.pct_missed > 8
                    ? "oklch(0.7 0.15 70)"
                    : "oklch(0.65 0.08 260)",
              }}
            />
          </div>

          {/* Stats below the bar */}
          <div className="flex items-center gap-4 mt-1.5 text-[10px] text-muted-foreground/50">
            <span><b className="text-foreground/60">{fmt(station.missed)}</b> missed</span>
            <span>of {fmt(station.planned)} connections</span>
            <span className="ml-auto">{fmt(station.daily_trains)} trains/day</span>
            <span className="px-1.5 py-0.5 rounded bg-primary/10 text-primary font-bold">impact {fmt(Math.round(station.impact_score))}</span>
          </div>
        </div>
      </div>

      {station.worst_pairs && station.worst_pairs.length > 0 && (
        <>
          <button onClick={() => setExpanded(!expanded)} className="mt-2 ml-10 text-[10px] text-primary hover:text-primary/80 font-medium flex items-center gap-1 cursor-pointer">
            {expanded ? "Hide" : "Show"} worst train pairs
            <ChevronDown className={cn("w-3 h-3 transition-transform", expanded && "rotate-180")} />
          </button>
          {expanded && (
            <div className="mt-2 ml-10 space-y-1.5 animate-slide-up">
              {station.worst_pairs.map((p, i) => (
                <div key={i} className="text-[10px] bg-muted/30 rounded-lg px-3 py-2 flex items-center justify-between gap-2">
                  <div className="min-w-0">
                    <span className="font-mono font-medium">{p.arriving_train}</span>
                    <span className="text-muted-foreground/50"> → </span>
                    <span className="font-mono font-medium">{p.departing_train}</span>
                    {p.relation_arr && <span className="text-muted-foreground/40 ml-1">({p.relation_arr})</span>}
                  </div>
                  <span className="text-destructive font-semibold whitespace-nowrap">{p.n_missed}/{p.n_occurrences}</span>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

/* ── Weather comparison card ── */

function WeatherCompareCard({
  label,
  icon,
  condA,
  condB,
  pctA,
  pctB,
  nA,
  nB,
  thresholdLabel,
}: {
  label: string;
  icon: React.ReactNode;
  condA: string;
  condB: string;
  pctA: number;
  pctB: number;
  nA: number;
  nB: number;
  thresholdLabel: string;
}) {
  const diff = pctA - pctB;
  const worse = diff > 0.3;
  const better = diff < -0.3;

  return (
    <div className="rounded-2xl border border-border/40 bg-card p-5 shadow-sm">
      <div className="flex items-center gap-2 mb-3">
        <span className="text-muted-foreground/50">{icon}</span>
        <h4 className="text-sm font-semibold">{label}</h4>
        <span className="text-[9px] text-muted-foreground/40 ml-auto">{thresholdLabel}</span>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div className="text-center">
          <div className={cn("text-2xl font-black", worse ? "text-destructive" : "text-foreground/70")}>{pctA.toFixed(1)}%</div>
          <div className="text-[9px] text-muted-foreground/50">{condA} ({nA}d)</div>
        </div>
        <div className="text-center">
          <div className={cn("text-2xl font-black", better ? "text-destructive" : "text-foreground/70")}>{pctB.toFixed(1)}%</div>
          <div className="text-[9px] text-muted-foreground/50">{condB} ({nB}d)</div>
        </div>
      </div>
      {Math.abs(diff) > 0.3 && (
        <p className="text-[10px] text-muted-foreground/60 mt-2 text-center">
          {worse ? "+" : ""}{diff.toFixed(1)} percentage points {worse ? "more" : "fewer"} missed
        </p>
      )}
    </div>
  );
}

/* ── Hub station card with heatmap ── */

const DOW_SHORT = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"];

function HubCard({ hub }: { hub: HubSpotlight }) {
  const [expanded, setExpanded] = useState(false);

  // Build heatmap grid: 7 rows (dow) x 24 cols (hour)
  const heatmapGrid = useMemo(() => {
    const grid: (number | null)[][] = Array.from({ length: 7 }, () => Array(24).fill(null));
    let maxPct = 1;
    for (const cell of hub.heatmap) {
      grid[cell.dow][cell.hour] = cell.pct;
      if (cell.pct > maxPct) maxPct = cell.pct;
    }
    return { grid, maxPct };
  }, [hub.heatmap]);

  return (
    <div className="rounded-2xl border border-border/40 bg-card shadow-sm overflow-hidden">
      <div className="p-5">
        <div className="flex items-start justify-between mb-3">
          <div>
            <h3 className="text-base font-bold tracking-tight">{hub.station}</h3>
            <p className="text-[10px] text-muted-foreground/50 mt-0.5">
              {fmt(hub.summary.planned)} connections · {hub.summary.pct}% failure rate
            </p>
          </div>
          <div className="grid grid-cols-3 gap-3 text-center">
            <MiniStat value={fmt(hub.summary.missed)} label="missed" danger />
            <MiniStat value={`${hub.summary.pct}%`} label="fail rate" />
            <MiniStat value={fmt(hub.summary.close_calls)} label="close calls" />
          </div>
        </div>

        {/* Heatmap */}
        <div className="mt-3">
          <p className="text-[10px] text-muted-foreground/50 mb-1.5">Failure rate by hour and day of week</p>
          <div className="overflow-x-auto">
            <div className="min-w-[500px]">
              {/* Hour labels */}
              <div className="flex ml-7 mb-0.5">
                {Array.from({ length: 24 }, (_, h) => (
                  <div key={h} className="flex-1 text-[7px] text-muted-foreground/30 text-center">
                    {h % 3 === 0 ? `${h}` : ""}
                  </div>
                ))}
              </div>
              {/* Grid rows */}
              {heatmapGrid.grid.map((row, dow) => (
                <div key={dow} className="flex items-center">
                  <span className="w-6 text-[8px] text-muted-foreground/40 font-medium shrink-0">{DOW_SHORT[dow]}</span>
                  <div className="flex flex-1 gap-px">
                    {row.map((pct, h) => (
                      <div
                        key={h}
                        className="flex-1 h-3 rounded-[2px] transition-colors"
                        title={pct !== null ? `${DOW_SHORT[dow]} ${h}h: ${pct}%` : "No data"}
                        style={{
                          backgroundColor: pct !== null
                            ? `rgba(${missColor(pct / heatmapGrid.maxPct).slice(0, 3).join(",")}, 0.85)`
                            : "var(--color-muted)",
                          opacity: pct !== null ? 1 : 0.3,
                        }}
                      />
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Toxic arrivals */}
      {hub.toxic_arrivals.length > 0 && (
        <div className="border-t border-border/30">
          <button
            onClick={() => setExpanded(!expanded)}
            className="w-full px-5 py-2 text-[10px] text-primary hover:text-primary/80 font-medium flex items-center gap-1 cursor-pointer"
          >
            {expanded ? "Hide" : "Show"} most damaging arriving trains
            <ChevronDown className={cn("w-3 h-3 transition-transform", expanded && "rotate-180")} />
          </button>
          {expanded && (
            <div className="px-5 pb-4 space-y-1.5 animate-slide-up">
              {hub.toxic_arrivals.map((ta, i) => (
                <div key={i} className="text-[10px] bg-muted/30 rounded-lg px-3 py-2 flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2 min-w-0">
                    <span className="font-black text-destructive/60 w-4">{i + 1}</span>
                    <span className="font-mono font-medium">{ta.train}</span>
                    {ta.relation && <span className="text-muted-foreground/40 truncate">{ta.relation}</span>}
                  </div>
                  <div className="flex items-center gap-3 shrink-0">
                    <span className="text-muted-foreground/50">avg {ta.avg_delay_min.toFixed(0)}m late</span>
                    <span className="text-destructive font-bold">{ta.missed_caused} broken</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
