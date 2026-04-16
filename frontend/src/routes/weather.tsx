import { createRoute } from "@tanstack/react-router";
import { useState, useMemo, useCallback, useRef } from "react";
import { CloudRain, Search } from "lucide-react";
import {
  ScatterChart, Scatter, XAxis, YAxis, Tooltip, ResponsiveContainer,
  CartesianGrid, ZAxis, Cell, Legend, BarChart, Bar,
} from "recharts";
import { rootRoute } from "./__root";
import { Layout } from "@/components/Layout";
import { FilterPanel, type Filters } from "@/components/FilterPanel";
import { MetricCard } from "@/components/MetricCard";
import { EmptyState } from "@/components/EmptyState";
import { ErrorAlert } from "@/components/ErrorAlert";
import { ApplyButton } from "@/components/ApplyButton";
import { MethodologyPanel } from "@/components/MethodologyPanel";
import { Label } from "@/components/ui/label";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { fetchApiSSE } from "@/lib/api";
import { filterParams, fmt, daysAgo, valueToColor } from "@/lib/utils";
import { cn } from "@/lib/utils";

export const weatherRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/weather",
  component: WeatherPage,
});

interface DailyPoint {
  date: string;
  weekday: number;
  n_trains: number;
  avg_delay: number;
  median_delay: number;
  pct_late: number;
  temp: number | null;
  precipitation: number | null;
  rain: number | null;
  snow: number | null;
  wind_speed: number | null;
  wind_gusts: number | null;
}

interface HourlyPoint {
  hour: number;
  avg_delay: number;
  pct_late: number;
  n_trains: number;
  avg_precip_mm: number;
  avg_wind_kmh: number;
  avg_temp_c: number;
  precip_delay_corr: number | null;
  n_observations: number;
}

interface SensitiveTrain {
  train: string;
  relation: string;
  n_days: number;
  avg_delay_min: number;
  avg_delay_rainy: number;
  avg_delay_dry: number;
  rain_sensitivity: number;
  rainy_days: number;
  dry_days: number;
}

interface WeatherDelayData {
  n_days: number;
  start_date: string;
  end_date: string;
  daily: DailyPoint[];
  correlations: Record<string, number>;
  hourly?: HourlyPoint[];
  sensitive_trains?: SensitiveTrain[];
  error?: string;
}

const WEATHER_VARS = [
  { key: "precipitation", label: "Precipitation (mm)", color: "#3b82f6" },
  { key: "rain", label: "Rain (mm)", color: "#06b6d4" },
  { key: "snow", label: "Snowfall (cm)", color: "#8b5cf6" },
  { key: "wind_speed", label: "Wind Speed (km/h)", color: "#f59e0b" },
  { key: "wind_gusts", label: "Wind Gusts (km/h)", color: "#ef4444" },
  { key: "temp", label: "Temperature (\u00b0C)", color: "#10b981" },
] as const;

const DELAY_VARS = [
  { key: "avg_delay", label: "Avg Delay (min)" },
  { key: "pct_late", label: "% Late (>1 min)" },
] as const;

const WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function corrLabel(r: number): string {
  const abs = Math.abs(r);
  if (abs < 0.1) return "None";
  if (abs < 0.3) return "Weak";
  if (abs < 0.5) return "Moderate";
  if (abs < 0.7) return "Strong";
  return "Very strong";
}

function corrColor(r: number): string {
  const abs = Math.abs(r);
  if (abs < 0.1) return "text-muted-foreground";
  if (abs < 0.3) return "text-amber-600";
  if (abs < 0.5) return "text-orange-600";
  return "text-red-600";
}

function WeatherPage() {
  const [filters, setFilters] = useState<Filters>({
    startDate: daysAgo(32), endDate: daysAgo(2),
    weekdays: [0, 1, 2, 3, 4, 5, 6],
    excludePub: false, excludeSch: false,
    useHour: true, hourStart: 5, hourEnd: 24,
  });
  const [metric, setMetric] = useState<"departure" | "arrival">("departure");
  const [selectedWeather, setSelectedWeather] = useState("precipitation");
  const [selectedDelay, setSelectedDelay] = useState("avg_delay");

  const [data, setData] = useState<WeatherDelayData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isFetching, setIsFetching] = useState(false);
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null);
  const [wtSearch, setWtSearch] = useState("");
  const abortRef = useRef<AbortController | null>(null);

  const loadData = useCallback(async () => {
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;

    setIsFetching(true);
    setError(null);
    setProgress(null);

    try {
      const result = await fetchApiSSE<WeatherDelayData>(
        "/weather-delay",
        { ...filterParams(filters), metric },
        ({ done, total }) => setProgress({ done, total }),
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
  }, [filters, metric]);

  const scatterData = useMemo(() => {
    if (!data?.daily) return [];
    return data.daily
      .filter((p) => p[selectedWeather as keyof DailyPoint] !== null)
      .map((p) => ({
        x: p[selectedWeather as keyof DailyPoint] as number,
        y: p[selectedDelay as keyof DailyPoint] as number,
        date: p.date,
        weekday: p.weekday,
        n_trains: p.n_trains,
        label: `${p.date} (${WEEKDAY_NAMES[p.weekday]})`,
      }));
  }, [data, selectedWeather, selectedDelay]);

  const timelineData = useMemo(() => {
    if (!data?.daily) return [];
    return data.daily.map((p) => ({
      date: p.date.slice(5), // MM-DD
      fullDate: p.date,
      avg_delay: p.avg_delay,
      pct_late: p.pct_late,
      precipitation: p.precipitation ?? 0,
      wind_speed: p.wind_speed ?? 0,
      temp: p.temp ?? 0,
    }));
  }, [data]);

  const corrKey = `${selectedWeather}_vs_${selectedDelay}`;
  const corrValue = data?.correlations?.[corrKey];

  const weatherInfo = WEATHER_VARS.find((w) => w.key === selectedWeather)!;
  const delayInfo = DELAY_VARS.find((d) => d.key === selectedDelay)!;

  // Summary stats
  const avgDelay = data?.daily?.length
    ? (data.daily.reduce((s, p) => s + p.avg_delay, 0) / data.daily.length).toFixed(1)
    : null;
  const avgPctLate = data?.daily?.length
    ? (data.daily.reduce((s, p) => s + p.pct_late, 0) / data.daily.length).toFixed(1)
    : null;
  const rainyDays = data?.daily?.filter((p) => (p.precipitation ?? 0) > 1).length ?? 0;
  const snowDays = data?.daily?.filter((p) => (p.snow ?? 0) > 0).length ?? 0;

  return (
    <Layout
      sidebar={
        <>
          <FilterPanel filters={filters} onChange={setFilters} />

          <div className="border-t border-border/40 pt-3 mt-3">
            <Label>Delay Metric</Label>
            <Tabs value={metric} onValueChange={(v) => setMetric(v as "departure" | "arrival")} className="mt-1.5">
              <TabsList className="w-full">
                <TabsTrigger value="departure" className="flex-1">Departure</TabsTrigger>
                <TabsTrigger value="arrival" className="flex-1">Arrival</TabsTrigger>
              </TabsList>
            </Tabs>
          </div>

          {data && !data.error && (
            <>
              <div className="border-t border-border/40 pt-3 mt-3">
                <Label>Weather Variable</Label>
                <div className="mt-1.5 space-y-1">
                  {WEATHER_VARS.map((w) => (
                    <button
                      key={w.key}
                      onClick={() => setSelectedWeather(w.key)}
                      className={cn(
                        "w-full text-left px-2.5 py-1.5 rounded-lg text-xs font-medium transition-colors",
                        selectedWeather === w.key
                          ? "bg-primary text-primary-foreground shadow-sm"
                          : "text-muted-foreground hover:bg-muted hover:text-foreground",
                      )}
                    >
                      {w.label}
                    </button>
                  ))}
                </div>
              </div>

              <div className="border-t border-border/40 pt-3 mt-3">
                <Label>Delay Variable</Label>
                <div className="mt-1.5 space-y-1">
                  {DELAY_VARS.map((d) => (
                    <button
                      key={d.key}
                      onClick={() => setSelectedDelay(d.key)}
                      className={cn(
                        "w-full text-left px-2.5 py-1.5 rounded-lg text-xs font-medium transition-colors",
                        selectedDelay === d.key
                          ? "bg-primary text-primary-foreground shadow-sm"
                          : "text-muted-foreground hover:bg-muted hover:text-foreground",
                      )}
                    >
                      {d.label}
                    </button>
                  ))}
                </div>
              </div>
            </>
          )}

          <ApplyButton loading={isFetching} onClick={loadData} label="Analyse" />
        </>
      }
    >
      {data && !data.error && !isFetching && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5 animate-slide-up">
          <MetricCard label="Days Analysed" value={fmt(data.n_days)} />
          <MetricCard label="Avg Delay" value={avgDelay ?? "\u2014"} suffix=" min" />
          <MetricCard label="Avg % Late" value={avgPctLate ?? "\u2014"} suffix="%" />
          <MetricCard label="Rainy Days" value={fmt(rainyDays)} suffix={snowDays > 0 ? ` (+${snowDays} snow)` : ""} />
        </div>
      )}

      {isFetching && (
        <div className="flex flex-col items-center justify-center py-20 animate-slide-up">
          <CloudRain className="h-10 w-10 text-primary/40 mb-4 animate-pulse" />
          {progress ? (
            <>
              <div className="w-64 h-2 rounded-full bg-muted overflow-hidden mb-2">
                <div
                  className="h-full rounded-full bg-primary transition-all duration-300 ease-out"
                  style={{ width: `${Math.round((progress.done / progress.total) * 100)}%` }}
                />
              </div>
              <p className="text-sm text-muted-foreground">
                Fetching day {progress.done} of {progress.total}...
              </p>
            </>
          ) : (
            <p className="text-sm text-muted-foreground">Preparing weather analysis...</p>
          )}
        </div>
      )}

      {!isFetching && !data && <EmptyState icon={CloudRain} message="Select a date range and click Analyse" />}

      {data && !data.error && !isFetching && (
        <div className="space-y-4 animate-slide-up">
          {/* Correlation matrix */}
          <div className="bg-card rounded-2xl border border-border/50 p-5 shadow-sm">
            <h3 className="text-sm font-semibold text-foreground mb-4">Correlation Matrix (Pearson r)</h3>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr>
                    <th className="px-3 py-2 text-left text-muted-foreground font-medium">Weather</th>
                    {DELAY_VARS.map((d) => (
                      <th key={d.key} className="px-3 py-2 text-right text-muted-foreground font-medium">{d.label}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {WEATHER_VARS.map((w) => (
                    <tr key={w.key} className="border-t border-border/30 hover:bg-muted/30">
                      <td className="px-3 py-2 font-medium text-foreground">{w.label}</td>
                      {DELAY_VARS.map((d) => {
                        const k = `${w.key}_vs_${d.key}`;
                        const r = data.correlations[k];
                        return (
                          <td key={k} className="px-3 py-2 text-right">
                            {r !== undefined ? (
                              <span className={cn("font-semibold", corrColor(r))}>
                                {r > 0 ? "+" : ""}{r.toFixed(3)} <span className="font-normal text-muted-foreground">({corrLabel(r)})</span>
                              </span>
                            ) : (
                              <span className="text-muted-foreground">&mdash;</span>
                            )}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Scatter plot */}
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
            <div className="bg-card rounded-2xl border border-border/50 p-5 shadow-sm">
              <div className="flex items-center justify-between mb-1">
                <h3 className="text-sm font-semibold text-foreground">
                  {weatherInfo.label} vs {delayInfo.label}
                </h3>
                {corrValue !== undefined && (
                  <span className={cn("text-xs font-semibold px-2.5 py-1 rounded-full border", corrColor(corrValue))}>
                    r = {corrValue > 0 ? "+" : ""}{corrValue.toFixed(3)} ({corrLabel(corrValue)})
                  </span>
                )}
              </div>
              <p className="text-[10px] text-muted-foreground mb-3">
                Bubble size = number of trains &middot; Color = delay severity
              </p>
              <ResponsiveContainer width="100%" height={340}>
                <ScatterChart margin={{ top: 8, right: 16, bottom: 8, left: 8 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" opacity={0.4} />
                  <XAxis
                    dataKey="x" type="number" name={weatherInfo.label}
                    tick={{ fontSize: 10 }}
                    label={{ value: weatherInfo.label, position: "insideBottom", offset: -2, fontSize: 10 }}
                  />
                  <YAxis
                    dataKey="y" type="number" name={delayInfo.label}
                    tick={{ fontSize: 10 }}
                    label={{ value: delayInfo.label, angle: -90, position: "insideLeft", offset: 5, fontSize: 10 }}
                  />
                  <ZAxis dataKey="n_trains" range={[30, 200]} name="Trains" />
                  <Tooltip
                    cursor={{ strokeDasharray: "3 3" }}
                    content={({ active, payload }) => {
                      if (!active || !payload?.length) return null;
                      const d = payload[0].payload;
                      return (
                        <div className="rounded-xl border border-border/50 bg-card px-3 py-2 text-xs shadow-lg">
                          <p className="font-semibold">{d.label}</p>
                          <p>{weatherInfo.label}: {d.x} &middot; {delayInfo.label}: {d.y}</p>
                          <p className="text-muted-foreground">{fmt(d.n_trains)} trains</p>
                        </div>
                      );
                    }}
                  />
                  <Scatter data={scatterData} fill={weatherInfo.color}>
                    {scatterData.map((entry, i) => (
                      <Cell key={i} fill={valueToColor(entry.y / Math.max(...scatterData.map((d) => d.y), 1))} opacity={0.75} />
                    ))}
                  </Scatter>
                </ScatterChart>
              </ResponsiveContainer>
            </div>

            {/* Timeline: overlay weather + delay */}
            <div className="bg-card rounded-2xl border border-border/50 p-5 shadow-sm">
              <h3 className="text-sm font-semibold text-foreground mb-4">Daily Timeline</h3>
              <ResponsiveContainer width="100%" height={340}>
                <BarChart data={timelineData} margin={{ top: 8, right: 16, bottom: 8, left: 8 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" opacity={0.4} />
                  <XAxis dataKey="date" tick={{ fontSize: 9 }} interval="preserveStartEnd" />
                  <YAxis yAxisId="delay" tick={{ fontSize: 10 }} label={{ value: "Avg delay (min)", angle: -90, position: "insideLeft", offset: 5, fontSize: 10 }} />
                  <YAxis yAxisId="weather" orientation="right" tick={{ fontSize: 10 }} label={{ value: weatherInfo.label, angle: 90, position: "insideRight", offset: 5, fontSize: 10 }} />
                  <Tooltip
                    contentStyle={{ fontSize: 11, borderRadius: 12, border: "1px solid var(--color-border)" }}
                    labelFormatter={(label: string, payload: any[]) => payload?.[0]?.payload?.fullDate ?? label}
                  />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  <Bar yAxisId="weather" dataKey={selectedWeather} name={weatherInfo.label} fill={weatherInfo.color} opacity={0.4} radius={[3, 3, 0, 0]} />
                  <Bar yAxisId="delay" dataKey="avg_delay" name="Avg Delay (min)" radius={[3, 3, 0, 0]}>
                    {timelineData.map((entry, i) => (
                      <Cell key={i} fill={valueToColor(entry.avg_delay / Math.max(...timelineData.map((d) => d.avg_delay), 1))} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Weekday breakdown */}
          <div className="bg-card rounded-2xl border border-border/50 p-5 shadow-sm">
            <h3 className="text-sm font-semibold text-foreground mb-4">Delay by Day of Week</h3>
            <WeekdayChart data={data.daily} />
          </div>

          {/* Weather-sensitive trains */}
          {data.sensitive_trains && data.sensitive_trains.length > 0 && (
            <div className="bg-card rounded-2xl border border-border/50 p-5 shadow-sm">
              <h3 className="text-sm font-semibold text-foreground mb-1">Weather-Sensitive Trains</h3>
              <p className="text-[10px] text-muted-foreground mb-3">
                Services whose delays increase most during rain (≥2mm). Sensitivity = avg delay on rainy days ÷ dry days. Only trains averaging ≥1 min delay shown.
              </p>
              <div className="relative mb-2">
                <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3 h-3 text-muted-foreground/40" />
                <input
                  value={wtSearch}
                  onChange={(e) => setWtSearch(e.target.value)}
                  placeholder="Search train or relation..."
                  className="w-full bg-muted/30 rounded-lg pl-7 pr-3 py-1.5 text-[10px] placeholder:text-muted-foreground/40 focus:outline-none focus:ring-1 focus:ring-primary/30"
                />
              </div>
              <div className="space-y-1.5 max-h-[400px] overflow-y-auto">
                {(wtSearch.trim()
                  ? data.sensitive_trains.filter((t) => {
                      const q = wtSearch.toLowerCase();
                      return t.train.toLowerCase().includes(q) || (t.relation && t.relation.toLowerCase().includes(q));
                    })
                  : data.sensitive_trains.slice(0, 10)
                ).map((t, i) => {
                  const maxS = data.sensitive_trains![0]?.rain_sensitivity ?? 1;
                  return (
                    <div key={t.train} className="flex items-center gap-3 text-xs">
                      <span className="text-muted-foreground/40 font-bold w-4 text-right">{i + 1}</span>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center justify-between">
                          <span className="font-medium truncate">{t.relation || `#${t.train}`} <span className="text-muted-foreground/50 font-mono text-[9px]">#{t.train}</span></span>
                          <span className="font-black text-blue-600 tabular-nums ml-2">{t.rain_sensitivity.toFixed(1)}×</span>
                        </div>
                        <div className="h-1.5 rounded-full bg-muted/60 overflow-hidden mt-0.5">
                          <div className="h-full rounded-full bg-blue-500/60" style={{ width: `${Math.max((t.rain_sensitivity / maxS) * 100, 4)}%` }} />
                        </div>
                        <div className="flex gap-3 mt-0.5 text-[9px] text-muted-foreground/50">
                          <span>rainy: {t.avg_delay_rainy.toFixed(1)}m ({t.rainy_days}d)</span>
                          <span>dry: {t.avg_delay_dry.toFixed(1)}m ({t.dry_days}d)</span>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Hourly weather vs delay */}
          {data.hourly && data.hourly.length > 0 && (
            <div className="bg-card rounded-2xl border border-border/50 p-5 shadow-sm">
              <h3 className="text-sm font-semibold text-foreground mb-1">Hourly Weather vs Delay</h3>
              <p className="text-[10px] text-muted-foreground mb-3">
                Average precipitation and delay per hour of day, aggregated across all days in the range.
                Bars show precipitation; line shows average delay.
              </p>
              <ResponsiveContainer width="100%" height={260}>
                <BarChart data={data.hourly} margin={{ top: 8, right: 16, bottom: 4, left: 8 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" opacity={0.4} />
                  <XAxis dataKey="hour" tick={{ fontSize: 10 }} tickFormatter={(h: number) => `${h}h`} />
                  <YAxis yAxisId="precip" tick={{ fontSize: 10 }} label={{ value: "Precip (mm)", angle: -90, position: "insideLeft", offset: 5, fontSize: 10 }} />
                  <YAxis yAxisId="delay" orientation="right" tick={{ fontSize: 10 }} label={{ value: "Avg delay (min)", angle: 90, position: "insideRight", offset: 5, fontSize: 10 }} />
                  <Tooltip
                    contentStyle={{ fontSize: 11, borderRadius: 12, border: "1px solid var(--color-border)" }}
                    labelFormatter={(h: number) => `${h}:00`}
                    formatter={(value: number, name: string) => {
                      if (name === "Avg Precip (mm)") return [`${value.toFixed(2)} mm`, name];
                      if (name === "Avg Delay (min)") return [`${value.toFixed(2)} min`, name];
                      if (name === "Precip-Delay Corr") return [value !== null ? value.toFixed(3) : "n/a", name];
                      return [value, name];
                    }}
                  />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  <Bar yAxisId="precip" dataKey="avg_precip_mm" name="Avg Precip (mm)" fill="#3b82f6" opacity={0.5} radius={[3, 3, 0, 0]} />
                  <Bar yAxisId="delay" dataKey="avg_delay" name="Avg Delay (min)" radius={[3, 3, 0, 0]}>
                    {data.hourly.map((entry, i) => (
                      <Cell key={i} fill={valueToColor(entry.avg_delay / Math.max(...data.hourly!.map((d) => d.avg_delay), 1))} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
              {data.hourly.some((h) => h.precip_delay_corr !== null) && (
                <div className="mt-3 flex flex-wrap gap-2">
                  {data.hourly.filter((h) => h.precip_delay_corr !== null).map((h) => (
                    <span
                      key={h.hour}
                      className={cn(
                        "text-[9px] px-2 py-0.5 rounded-full border font-medium",
                        h.precip_delay_corr! > 0.3 ? "text-red-600 border-red-200 bg-red-50"
                          : h.precip_delay_corr! < -0.1 ? "text-blue-600 border-blue-200 bg-blue-50"
                          : "text-muted-foreground border-border bg-muted/30",
                      )}
                    >
                      {h.hour}h: r={h.precip_delay_corr!.toFixed(2)}
                    </span>
                  ))}
                </div>
              )}
            </div>
          )}

          <MethodologyPanel>
            <p>Weather data is sourced from the <b>Open-Meteo Archive API</b> (ERA5 reanalysis), providing both daily and hourly measurements for central Belgium (Brussels, 50.85N 4.35E).</p>
            <p>Train delay data comes from the Infrabel real-time punctuality feed. For each day in the range, we compute the average delay, median delay, and percentage of trains late (&gt;1 min) across all stations.</p>
            <p>The <b>hourly chart</b> aggregates precipitation and delays by hour of day. For each hour, the per-hour Pearson correlation between that hour's precipitation and delays is computed across all days — revealing whether rain at specific times (e.g. morning rush) has a stronger impact on delays than rain at other times.</p>
            <p>Days are filtered by weekday and holiday settings — e.g. excluding weekends isolates commuter patterns, while excluding holidays removes atypical traffic days that could skew correlations.</p>
            <p>The <b>Pearson correlation coefficient (r)</b> measures the linear relationship between each weather variable and delay metric. Values range from -1 to +1. Scatter point size reflects the number of trains that day; color reflects delay severity.</p>
          </MethodologyPanel>
        </div>
      )}

      {(error || data?.error) && <ErrorAlert message={data?.error ?? error ?? "Unknown error"} />}
    </Layout>
  );
}

function WeekdayChart({ data }: { data: DailyPoint[] }) {
  const weekdayStats = useMemo(() => {
    const buckets: Record<number, { delays: number[]; pct: number[] }> = {};
    for (let i = 0; i < 7; i++) buckets[i] = { delays: [], pct: [] };
    for (const p of data) {
      buckets[p.weekday].delays.push(p.avg_delay);
      buckets[p.weekday].pct.push(p.pct_late);
    }
    return WEEKDAY_NAMES.map((name, i) => {
      const b = buckets[i];
      const n = b.delays.length;
      return {
        name,
        avg_delay: n ? +(b.delays.reduce((s, v) => s + v, 0) / n).toFixed(1) : 0,
        pct_late: n ? +(b.pct.reduce((s, v) => s + v, 0) / n).toFixed(1) : 0,
        n_days: n,
      };
    });
  }, [data]);

  const maxDelay = Math.max(...weekdayStats.map((d) => d.avg_delay), 1);

  return (
    <ResponsiveContainer width="100%" height={200}>
      <BarChart data={weekdayStats} margin={{ top: 4, right: 8, bottom: 4, left: 8 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" opacity={0.4} />
        <XAxis dataKey="name" tick={{ fontSize: 11 }} />
        <YAxis tick={{ fontSize: 10 }} label={{ value: "Avg delay (min)", angle: -90, position: "insideLeft", offset: 5, fontSize: 10 }} />
        <Tooltip
          contentStyle={{ fontSize: 11, borderRadius: 12, border: "1px solid var(--color-border)" }}
          formatter={(value: number, name: string) => {
            if (name === "Avg Delay") return [`${value} min`, name];
            return [`${value}`, name];
          }}
        />
        <Bar dataKey="avg_delay" name="Avg Delay" radius={[4, 4, 0, 0]}>
          {weekdayStats.map((entry, i) => (
            <Cell key={i} fill={valueToColor(entry.avg_delay / maxDelay)} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
