import { cn } from "@/lib/utils";

export function Label({ className, ...props }: React.LabelHTMLAttributes<HTMLLabelElement>) {
  return (
    <label
      className={cn(
        "text-[11px] font-medium text-muted-foreground uppercase tracking-wider",
        className,
      )}
      {...props}
    />
  );
}
