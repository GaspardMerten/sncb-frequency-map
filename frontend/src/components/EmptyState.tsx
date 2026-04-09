import type { LucideIcon } from "lucide-react";

interface EmptyStateProps {
  icon: LucideIcon;
  message?: string;
}

export function EmptyState({ icon: Icon, message = "Configure settings and click Apply" }: EmptyStateProps) {
  return (
    <div className="flex items-center justify-center h-96">
      <div className="text-center">
        <div className="w-20 h-20 rounded-3xl bg-gradient-to-br from-muted to-muted/50 flex items-center justify-center mx-auto mb-5 border border-border/40">
          <Icon className="w-9 h-9 text-muted-foreground/30" />
        </div>
        <p className="text-sm text-muted-foreground font-medium">{message}</p>
        <p className="text-xs text-muted-foreground/50 mt-1">Use the sidebar controls to get started</p>
      </div>
    </div>
  );
}
