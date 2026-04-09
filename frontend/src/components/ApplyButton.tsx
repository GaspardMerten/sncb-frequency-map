import { Button } from "@/components/ui/button";
import { Loader2 } from "lucide-react";

interface ApplyButtonProps {
  loading: boolean;
  onClick: () => void;
  label?: string;
  loadingLabel?: string;
}

export function ApplyButton({ loading, onClick, label = "Apply Filters", loadingLabel = "Computing..." }: ApplyButtonProps) {
  return (
    <div className="border-t border-border pt-3 mt-3">
      <Button onClick={onClick} disabled={loading} className="w-full" size="sm">
        {loading ? (
          <>
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
            {loadingLabel}
          </>
        ) : (
          label
        )}
      </Button>
    </div>
  );
}
