import { useState } from "react";
import { ChevronDown, Info } from "lucide-react";
import { cn } from "@/lib/utils";

interface MethodologyPanelProps {
  children: React.ReactNode;
}

export function MethodologyPanel({ children }: MethodologyPanelProps) {
  const [open, setOpen] = useState(false);

  return (
    <div className="rounded-2xl border border-border/50 bg-card shadow-sm overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-2 px-4 py-3 text-xs font-medium text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
      >
        <Info className="w-3.5 h-3.5" />
        How is this computed?
        <ChevronDown className={cn("w-3.5 h-3.5 ml-auto transition-transform", open && "rotate-180")} />
      </button>
      {open && (
        <div className="px-4 pb-4 text-xs text-muted-foreground/80 leading-relaxed space-y-2 border-t border-border/30 pt-3 animate-slide-up">
          {children}
        </div>
      )}
    </div>
  );
}
