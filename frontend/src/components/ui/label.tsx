import { cn } from "@/lib/utils";

export function Label({ className, ...props }: React.LabelHTMLAttributes<HTMLLabelElement>) {
  return (
    <label
      className={cn(
        "text-[11px] font-semibold text-foreground/60 uppercase tracking-widest",
        className,
      )}
      {...props}
    />
  );
}
