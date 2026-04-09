import { cn } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";
import type { LucideIcon } from "lucide-react";

interface MetricCardProps {
  label: string;
  value: string | number;
  suffix?: string;
  icon?: LucideIcon;
  loading?: boolean;
  className?: string;
  danger?: boolean;
}

export function MetricCard({ label, value, suffix, icon: Icon, loading, className, danger }: MetricCardProps) {
  return (
    <div
      className={cn(
        "relative bg-gradient-to-br from-card to-muted/30 border border-border rounded-xl px-4 py-3",
        "transition-all duration-200 ease-out hover:scale-[1.02] hover:shadow-md",
        className,
      )}
    >
      {Icon && (
        <Icon className="absolute top-3 right-3 h-4 w-4 text-muted-foreground/50" />
      )}
      <div className="text-[10px] text-muted-foreground uppercase tracking-wider font-medium">
        {label}
      </div>
      {loading ? (
        <Skeleton className="h-8 w-28 mt-1 rounded-md" />
      ) : (
        <div className={cn("text-2xl font-bold mt-0.5 truncate", danger ? "text-destructive" : "text-primary")}>
          {value}
          {suffix && <span className="text-sm font-medium text-muted-foreground ml-0.5">{suffix}</span>}
        </div>
      )}
    </div>
  );
}
