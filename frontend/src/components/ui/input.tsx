import { cn } from "@/lib/utils";

export function Input({ className, ...props }: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={cn(
        "flex h-9 w-full rounded-xl border border-border/60 bg-card px-3 py-1.5 text-sm transition-all duration-200",
        "placeholder:text-muted-foreground/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/20 focus-visible:border-primary/40",
        "disabled:cursor-not-allowed disabled:opacity-50",
        "hover:border-border",
        className,
      )}
      {...props}
    />
  );
}
