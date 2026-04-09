import { Button } from "@/components/ui/button";
import { Loader2, Sparkles } from "lucide-react";

interface ApplyButtonProps {
  loading: boolean;
  onClick: () => void;
  label?: string;
  loadingLabel?: string;
}

export function ApplyButton({ loading, onClick, label = "Apply Filters", loadingLabel = "Computing..." }: ApplyButtonProps) {
  return (
    <div className="pt-3 mt-3 border-t border-border/40">
      <Button onClick={onClick} disabled={loading} className="w-full h-10 rounded-xl text-sm font-semibold" size="default">
        {loading ? (
          <>
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
            {loadingLabel}
          </>
        ) : (
          <>
            <Sparkles className="w-3.5 h-3.5" />
            {label}
          </>
        )}
      </Button>
    </div>
  );
}
