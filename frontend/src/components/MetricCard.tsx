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
        "relative overflow-hidden rounded-2xl border border-border/50 bg-card px-4 py-3.5",
        "transition-all duration-300 ease-out hover:shadow-md hover:border-border",
        "group",
        className,
      )}
    >
      {/* Subtle gradient accent at top */}
      <div className={cn(
        "absolute top-0 left-0 right-0 h-[2px]",
        danger
          ? "bg-gradient-to-r from-destructive/60 via-destructive/30 to-transparent"
          : "bg-gradient-to-r from-primary/50 via-primary/20 to-transparent",
      )} />

      {Icon && (
        <Icon className="absolute top-3.5 right-3.5 h-4 w-4 text-muted-foreground/30 group-hover:text-muted-foreground/50 transition-colors" />
      )}
      <div className="text-[10px] text-muted-foreground uppercase tracking-widest font-medium">
        {label}
      </div>
      {loading ? (
        <Skeleton className="h-8 w-28 mt-1.5 rounded-lg" />
      ) : (
        <div className={cn(
          "text-2xl font-bold mt-1 truncate tracking-tight",
          danger ? "text-destructive" : "text-foreground",
        )}>
          {value}
          {suffix && <span className="text-xs font-medium text-muted-foreground ml-1">{suffix}</span>}
        </div>
      )}
    </div>
  );
}
