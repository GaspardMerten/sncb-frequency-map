import { cn } from "@/lib/utils";
import { useRef, useState } from "react";

interface SliderProps {
  value?: number;
  onValueChange?: (value: number) => void;
  min?: number;
  max?: number;
  step?: number;
  className?: string;
}

export function Slider({ value = 0, onValueChange, min = 0, max = 100, step = 1, className }: SliderProps) {
  const [active, setActive] = useState(false);
  const trackRef = useRef<HTMLDivElement>(null);
  const pct = ((value - min) / (max - min)) * 100;

  return (
    <div className={cn("relative flex w-full touch-none select-none items-center", className)}>
      {/* Track */}
      <div ref={trackRef} className="relative h-1.5 w-full rounded-full bg-muted">
        {/* Fill */}
        <div className="absolute h-full rounded-full bg-primary" style={{ width: `${pct}%` }} />
      </div>

      {/* Value label */}
      <div
        className={cn(
          "absolute -top-8 rounded-md bg-foreground px-1.5 py-0.5 text-xs text-background shadow transition-opacity",
          active ? "opacity-100" : "opacity-0",
        )}
        style={{ left: `calc(${pct}% - 0.75rem)` }}
      >
        {value}
      </div>

      {/* Native range input (invisible but functional) */}
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onValueChange?.(Number(e.target.value))}
        onMouseDown={() => setActive(true)}
        onMouseUp={() => setActive(false)}
        onTouchStart={() => setActive(true)}
        onTouchEnd={() => setActive(false)}
        onFocus={() => setActive(true)}
        onBlur={() => setActive(false)}
        className="absolute inset-0 h-full w-full cursor-pointer opacity-0"
      />

      {/* Visual thumb */}
      <div
        className={cn(
          "absolute h-4 w-4 rounded-full border-2 border-primary bg-white shadow-sm transition-shadow",
          "pointer-events-none",
          active && "ring-2 ring-ring",
        )}
        style={{ left: `calc(${pct}% - 0.5rem)` }}
      />
    </div>
  );
}
