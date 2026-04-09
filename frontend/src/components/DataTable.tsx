import { cn } from "@/lib/utils";

interface Column<T> {
  header: string;
  accessor: (row: T, index: number) => React.ReactNode;
  align?: "left" | "right";
  className?: string;
}

interface DataTableProps<T> {
  title: string;
  columns: Column<T>[];
  data: T[];
  maxRows?: number;
  maxHeight?: string;
  onRowClick?: (row: T) => void;
  keyFn: (row: T, index: number) => string | number;
}

export function DataTable<T>({
  title,
  columns,
  data,
  maxRows = 50,
  maxHeight = "calc(100vh - 18rem)",
  onRowClick,
  keyFn,
}: DataTableProps<T>) {
  return (
    <div className="bg-card rounded-2xl border border-border/60 overflow-hidden shadow-sm">
      <div className="px-4 py-3.5 border-b border-border/40">
        <h3 className="text-sm font-semibold text-foreground tracking-tight">{title}</h3>
      </div>
      <div className="overflow-y-auto" style={{ maxHeight }}>
        <table className="w-full text-xs">
          <thead className="bg-muted/40 sticky top-0 z-10">
            <tr>
              {columns.map((col, i) => (
                <th
                  key={i}
                  className={cn(
                    "px-3 py-2.5 font-semibold text-muted-foreground/80 text-[10px] uppercase tracking-widest",
                    col.align === "right" ? "text-right" : "text-left",
                  )}
                >
                  {col.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.slice(0, maxRows).map((row, i) => (
              <tr
                key={keyFn(row, i)}
                className={cn(
                  "border-t border-border/30 transition-colors duration-150",
                  "hover:bg-primary/[0.03]",
                  onRowClick && "cursor-pointer",
                )}
                onClick={() => onRowClick?.(row)}
              >
                {columns.map((col, j) => (
                  <td
                    key={j}
                    className={cn(
                      "px-3 py-2.5",
                      col.align === "right" ? "text-right" : "text-left",
                      col.className,
                    )}
                  >
                    {col.accessor(row, i)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
