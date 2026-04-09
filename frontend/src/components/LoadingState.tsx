import { Skeleton } from "@/components/ui/skeleton";

interface LoadingStateProps {
  message?: string;
  className?: string;
}

export function LoadingState({ message = "Loading data...", className }: LoadingStateProps) {
  return (
    <div className={`flex items-center justify-center h-96 ${className ?? ""}`}>
      <div className="text-center space-y-5">
        <div className="relative flex items-center justify-center">
          {/* Outer ring */}
          <div
            className="absolute w-16 h-16 rounded-full border-2 border-primary/15"
            style={{ animation: "loading-ring 2s ease-in-out infinite" }}
          />
          {/* Middle ring */}
          <div
            className="absolute w-12 h-12 rounded-full border-2 border-primary/10"
            style={{ animation: "loading-ring 2s ease-in-out infinite 0.4s" }}
          />
          {/* Bouncing dots */}
          <div className="flex items-center justify-center gap-2">
            {[0, 1, 2].map((i) => (
              <div
                key={i}
                className="w-2.5 h-2.5 rounded-full bg-gradient-to-b from-primary to-primary/70"
                style={{
                  animation: "bounce-dot 1.4s ease-in-out infinite",
                  animationDelay: `${i * 0.18}s`,
                }}
              />
            ))}
          </div>
        </div>
        <p className="text-sm text-muted-foreground font-medium">{message}</p>
      </div>
    </div>
  );
}

export function MetricsSkeleton({ count = 4 }: { count?: number }) {
  return (
    <div className={`grid grid-cols-2 md:grid-cols-${count} gap-3 mb-4`}>
      {Array.from({ length: count }).map((_, i) => (
        <div
          key={i}
          className="rounded-2xl border border-border/50 bg-card px-4 py-3.5"
        >
          <Skeleton className="h-3 w-16 mb-2.5 rounded-lg" />
          <Skeleton className="h-8 w-28 rounded-lg skeleton-shimmer" />
        </div>
      ))}
    </div>
  );
}
