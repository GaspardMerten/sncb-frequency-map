import type { LucideIcon } from "lucide-react";

interface EmptyStateProps {
  icon: LucideIcon;
  message?: string;
}

export function EmptyState({ icon: Icon, message = "Configure settings and click Apply" }: EmptyStateProps) {
  return (
    <div className="flex items-center justify-center h-96">
      <div className="text-center">
        <div className="w-16 h-16 rounded-2xl bg-muted flex items-center justify-center mx-auto mb-4">
          <Icon className="w-8 h-8 text-muted-foreground/40" />
        </div>
        <p className="text-sm text-muted-foreground">{message}</p>
      </div>
    </div>
  );
}
