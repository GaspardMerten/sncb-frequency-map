import { cn } from "@/lib/utils";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Minus, Plus } from "lucide-react";

export interface Filters {
  startDate: string;
  endDate: string;
  weekdays: number[];
  excludePub: boolean;
  excludeSch: boolean;
  useHour: boolean;
  hourStart: number;
  hourEnd: number;
}

interface FilterPanelProps {
  filters: Filters;
  onChange: (filters: Filters) => void;
}

const DAYS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"];

function HourStepper({
  value,
  onChange,
  label,
}: {
  value: number;
  onChange: (v: number) => void;
  label: string;
}) {
  const clamp = (v: number) => Math.max(0, Math.min(24, v));
  return (
    <div className="flex flex-col items-center gap-1.5">
      <span className="text-[10px] uppercase tracking-widest text-muted-foreground/60 font-medium">
        {label}
      </span>
      <div className="flex items-center gap-2">
        <button
          onClick={() => onChange(clamp(value - 1))}
          className="flex h-7 w-7 items-center justify-center rounded-lg border border-border/60 bg-card text-muted-foreground transition-all hover:bg-muted hover:text-foreground hover:border-border active:scale-90 cursor-pointer"
        >
          <Minus className="h-3 w-3" />
        </button>
        <span className="w-10 text-center text-sm font-bold tabular-nums text-foreground">
          {value}h
        </span>
        <button
          onClick={() => onChange(clamp(value + 1))}
          className="flex h-7 w-7 items-center justify-center rounded-lg border border-border/60 bg-card text-muted-foreground transition-all hover:bg-muted hover:text-foreground hover:border-border active:scale-90 cursor-pointer"
        >
          <Plus className="h-3 w-3" />
        </button>
      </div>
    </div>
  );
}

export function FilterPanel({ filters, onChange }: FilterPanelProps) {
  const toggleWeekday = (i: number) => {
    const idx = filters.weekdays.indexOf(i);
    const next = [...filters.weekdays];
    if (idx >= 0) next.splice(idx, 1);
    else next.push(i);
    onChange({ ...filters, weekdays: next });
  };

  const set = <K extends keyof Filters>(key: K, value: Filters[K]) =>
    onChange({ ...filters, [key]: value });

  return (
    <div className="space-y-3.5">
      {/* Date Range */}
      <div>
        <Label className="text-[11px] font-semibold tracking-wide text-foreground/70">
          Date Range
        </Label>
        <div className="grid grid-cols-2 gap-2 mt-2">
          <div className="space-y-1">
            <span className="text-[10px] uppercase tracking-widest text-muted-foreground/60 font-medium">
              From
            </span>
            <Input
              type="date"
              value={filters.startDate}
              onChange={(e) => set("startDate", e.target.value)}
              className="h-9 w-full text-xs"
            />
          </div>
          <div className="space-y-1">
            <span className="text-[10px] uppercase tracking-widest text-muted-foreground/60 font-medium">
              To
            </span>
            <Input
              type="date"
              value={filters.endDate}
              onChange={(e) => set("endDate", e.target.value)}
              className="h-9 w-full text-xs"
            />
          </div>
        </div>
      </div>

      <div className="border-t border-border/40" />

      {/* Days of Week */}
      <div>
        <Label className="text-[11px] font-semibold tracking-wide text-foreground/70">
          Days of Week
        </Label>
        <div className="flex gap-1.5 mt-2">
          {DAYS.map((day, i) => (
            <button
              key={i}
              onClick={() => toggleWeekday(i)}
              className={cn(
                "flex-1 h-9 rounded-lg text-[11px] transition-all duration-200 cursor-pointer",
                filters.weekdays.includes(i)
                  ? "bg-gradient-to-b from-primary to-primary/85 text-primary-foreground shadow-sm shadow-primary/20 font-bold active:scale-90"
                  : "bg-card text-muted-foreground border border-border/60 hover:border-primary/30 hover:text-foreground font-medium active:scale-95",
              )}
            >
              {day}
            </button>
          ))}
        </div>
      </div>

      <div className="border-t border-border/40" />

      {/* Holidays */}
      <div className="space-y-2.5">
        <Label className="text-[11px] font-semibold tracking-wide text-foreground/70">Holidays</Label>
        <div className="flex items-center justify-between">
          <span className="text-xs text-foreground/60">
            Exclude public holidays
          </span>
          <Switch
            checked={filters.excludePub}
            onCheckedChange={(checked) => set("excludePub", checked)}
          />
        </div>
        <div className="flex items-center justify-between">
          <span className="text-xs text-foreground/60">
            Exclude school holidays
          </span>
          <Switch
            checked={filters.excludeSch}
            onCheckedChange={(checked) => set("excludeSch", checked)}
          />
        </div>
      </div>

      <div className="border-t border-border/40" />

      {/* Time of Day */}
      <div className="space-y-2.5">
        <Label className="text-[11px] font-semibold tracking-wide text-foreground/70">
          Time of Day
        </Label>
        <div className="flex items-center justify-between">
          <span className="text-xs text-foreground/60">Filter by hour</span>
          <Switch
            checked={filters.useHour}
            onCheckedChange={(checked) => set("useHour", checked)}
          />
        </div>
        {filters.useHour && (
          <div className="flex items-center justify-center gap-4 rounded-xl border border-border/40 bg-muted/30 px-4 py-3.5">
            <HourStepper
              value={filters.hourStart}
              onChange={(v) => set("hourStart", v)}
              label="From"
            />
            <div className="mt-5 text-xs font-medium text-muted-foreground/50">
              —
            </div>
            <HourStepper
              value={filters.hourEnd}
              onChange={(v) => set("hourEnd", v)}
              label="To"
            />
          </div>
        )}
      </div>
    </div>
  );
}
