import { Skeleton } from "@/components/ui/skeleton";

interface LoadingStateProps {
  message?: string;
  className?: string;
}

export function LoadingState({ message = "Loading data...", className }: LoadingStateProps) {
  return (
    <div className={`flex items-center justify-center h-96 ${className ?? ""}`}>
      <div className="text-center space-y-4">
        {/* Pulsing ring + bouncing dots */}
        <div className="relative flex items-center justify-center">
          {/* Outer pulsing ring */}
          <div
            className="absolute w-14 h-14 rounded-full border-2 border-primary/20"
            style={{
              animation: "loading-ring 2s ease-in-out infinite",
            }}
          />
          {/* Bouncing dots */}
          <div className="flex items-center justify-center gap-1.5">
            {[0, 1, 2].map((i) => (
              <div
                key={i}
                className="w-2.5 h-2.5 rounded-full bg-primary"
                style={{
                  opacity: 1 - i * 0.15,
                  animation: "bounce-dot 1.2s ease-in-out infinite",
                  animationDelay: `${i * 0.15}s`,
                }}
              />
            ))}
          </div>
        </div>
        <p className="text-sm text-muted-foreground">{message}</p>
      </div>
    </div>
  );
}

/** Inline skeleton metrics while data is loading */
export function MetricsSkeleton({ count = 4 }: { count?: number }) {
  return (
    <div className={`grid grid-cols-2 md:grid-cols-${count} gap-3 mb-4`}>
      {Array.from({ length: count }).map((_, i) => (
        <div
          key={i}
          className="bg-gradient-to-br from-card to-muted/30 border border-border rounded-xl px-4 py-3"
        >
          <Skeleton className="h-3 w-16 mb-2 rounded" />
          <Skeleton className="h-8 w-28 rounded-md shimmer-skeleton" />
        </div>
      ))}
    </div>
  );
}
