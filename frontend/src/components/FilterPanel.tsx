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
    <div className="flex flex-col items-center gap-1">
      <span className="text-[10px] uppercase tracking-wider text-muted-foreground/70">
        {label}
      </span>
      <div className="flex items-center gap-1.5">
        <button
          onClick={() => onChange(clamp(value - 1))}
          className="flex h-6 w-6 items-center justify-center rounded-md border border-border bg-card text-muted-foreground transition-colors hover:bg-muted hover:text-foreground active:scale-95 cursor-pointer"
        >
          <Minus className="h-3 w-3" />
        </button>
        <span className="w-10 text-center text-sm font-semibold tabular-nums text-foreground">
          {value}h
        </span>
        <button
          onClick={() => onChange(clamp(value + 1))}
          className="flex h-6 w-6 items-center justify-center rounded-md border border-border bg-card text-muted-foreground transition-colors hover:bg-muted hover:text-foreground active:scale-95 cursor-pointer"
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
    <div className="space-y-3">
      {/* Date Range */}
      <div>
        <Label className="text-xs font-semibold tracking-wide">
          Date Range
        </Label>
        <div className="grid grid-cols-2 gap-2 mt-2">
          <div className="space-y-1">
            <span className="text-[10px] uppercase tracking-wider text-muted-foreground/70">
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
            <span className="text-[10px] uppercase tracking-wider text-muted-foreground/70">
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

      {/* Divider */}
      <div className="border-t border-border/50" />

      {/* Days of Week */}
      <div>
        <Label className="text-xs font-semibold tracking-wide">
          Days of Week
        </Label>
        <div className="flex gap-1.5 mt-2">
          {DAYS.map((day, i) => (
            <button
              key={i}
              onClick={() => toggleWeekday(i)}
              className={cn(
                "w-9 h-9 rounded-lg text-[11px] transition-all duration-150 cursor-pointer",
                filters.weekdays.includes(i)
                  ? "bg-primary text-primary-foreground shadow-sm font-bold active:scale-90"
                  : "bg-card text-muted-foreground border border-border hover:border-primary/40 hover:text-foreground font-medium active:scale-95",
              )}
            >
              {day}
            </button>
          ))}
        </div>
      </div>

      {/* Divider */}
      <div className="border-t border-border/50" />

      {/* Holidays */}
      <div className="space-y-2.5">
        <Label className="text-xs font-semibold tracking-wide">Holidays</Label>
        <div className="flex items-center justify-between">
          <span className="text-xs text-foreground/70">
            Exclude public holidays
          </span>
          <Switch
            checked={filters.excludePub}
            onCheckedChange={(checked) => set("excludePub", checked)}
          />
        </div>
        <div className="flex items-center justify-between">
          <span className="text-xs text-foreground/70">
            Exclude school holidays
          </span>
          <Switch
            checked={filters.excludeSch}
            onCheckedChange={(checked) => set("excludeSch", checked)}
          />
        </div>
      </div>

      {/* Divider */}
      <div className="border-t border-border/50" />

      {/* Time of Day */}
      <div className="space-y-2.5">
        <Label className="text-xs font-semibold tracking-wide">
          Time of Day
        </Label>
        <div className="flex items-center justify-between">
          <span className="text-xs text-foreground/70">Filter by hour</span>
          <Switch
            checked={filters.useHour}
            onCheckedChange={(checked) => set("useHour", checked)}
          />
        </div>
        {filters.useHour && (
          <div className="flex items-center justify-center gap-4 rounded-lg border border-border/50 bg-muted/30 px-4 py-3">
            <HourStepper
              value={filters.hourStart}
              onChange={(v) => set("hourStart", v)}
              label="From"
            />
            <div className="mt-4 text-xs font-medium text-muted-foreground">
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
