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
          "flex h-9 w-full appearance-none rounded-md border border-input bg-background px-3 py-1.5 pr-8 text-sm shadow-sm transition-colors",
          "placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
          "disabled:cursor-not-allowed disabled:opacity-50",
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
      <ChevronDown className="pointer-events-none absolute right-2 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
    </div>
  );
}

interface SelectOptionProps extends React.OptionHTMLAttributes<HTMLOptionElement> {}

export function SelectOption({ ...props }: SelectOptionProps) {
  return <option {...props} />;
}
