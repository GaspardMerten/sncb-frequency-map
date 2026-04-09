import { AlertTriangle } from "lucide-react";

interface ErrorAlertProps {
  message: string;
}

export function ErrorAlert({ message }: ErrorAlertProps) {
  return (
    <div className="mt-4 bg-destructive/10 border border-destructive/20 rounded-xl p-4 flex items-start gap-3">
      <AlertTriangle className="w-4 h-4 text-destructive mt-0.5 shrink-0" />
      <p className="text-sm text-destructive">{message}</p>
    </div>
  );
}
