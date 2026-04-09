import { valueToColor } from "@/lib/utils";

interface ColorLegendProps {
  min?: string;
  max?: string;
  label?: string;
  steps?: number;
}

export function ColorLegend({ min = "Low", max = "High", label, steps = 40 }: ColorLegendProps) {
  return (
    <div className="flex items-center gap-2 text-[10px] text-muted-foreground">
      {label && <span className="font-medium shrink-0">{label}</span>}
      <span className="shrink-0">{min}</span>
      <div className="flex h-2.5 flex-1 min-w-[100px] max-w-[200px] rounded-full overflow-hidden">
        {Array.from({ length: steps }, (_, i) => (
          <div
            key={i}
            className="flex-1 h-full"
            style={{ backgroundColor: valueToColor(i / (steps - 1)) }}
          />
        ))}
      </div>
      <span className="shrink-0">{max}</span>
    </div>
  );
}
