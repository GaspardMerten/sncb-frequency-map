import { cn } from "@/lib/utils";
import { ChevronDown } from "lucide-react";

interface SelectProps {
  value?: string;
  onValueChange?: (value: string) => void;
  children?: React.ReactNode;
  placeholder?: string;
  className?: string;
}

export function Select({ value, onValueChange, children, placeholder, className }: SelectProps) {
  return (
    <div className={cn("relative", className)}>
      <select
        value={value ?? ""}
        onChange={(e) => onValueChange?.(e.target.value)}
        className={cn(
          "flex h-9 w-full appearance-none rounded-xl border border-border/60 bg-card px-3 py-1.5 pr-8 text-sm transition-all duration-200",
          "placeholder:text-muted-foreground/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/20 focus-visible:border-primary/40",
          "disabled:cursor-not-allowed disabled:opacity-50",
          "hover:border-border",
          !value && "text-muted-foreground",
        )}
      >
        {placeholder && (
          <option value="" disabled>
            {placeholder}
          </option>
        )}
        {children}
      </select>
      <ChevronDown className="pointer-events-none absolute right-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground/50" />
    </div>
  );
}

interface SelectOptionProps extends React.OptionHTMLAttributes<HTMLOptionElement> {}

export function SelectOption({ ...props }: SelectOptionProps) {
  return <option {...props} />;
}
