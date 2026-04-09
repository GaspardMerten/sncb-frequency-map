import { AlertTriangle } from "lucide-react";

interface ErrorAlertProps {
  message: string;
}

export function ErrorAlert({ message }: ErrorAlertProps) {
  return (
    <div className="mt-4 bg-destructive/[0.06] border border-destructive/15 rounded-2xl p-4 flex items-start gap-3 animate-slide-up">
      <div className="w-8 h-8 rounded-xl bg-destructive/10 flex items-center justify-center shrink-0">
        <AlertTriangle className="w-4 h-4 text-destructive" />
      </div>
      <div>
        <p className="text-sm font-medium text-destructive">Something went wrong</p>
        <p className="text-xs text-destructive/70 mt-0.5">{message}</p>
      </div>
    </div>
  );
}
