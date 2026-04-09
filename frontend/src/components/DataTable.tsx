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
    <div className="bg-card rounded-xl border border-border overflow-hidden">
      <div className="px-4 py-3 border-b border-border">
        <h3 className="text-sm font-semibold text-foreground">{title}</h3>
      </div>
      <div className="overflow-y-auto" style={{ maxHeight }}>
        <table className="w-full text-xs">
          <thead className="bg-muted/50 sticky top-0">
            <tr>
              {columns.map((col, i) => (
                <th
                  key={i}
                  className={cn(
                    "px-3 py-2 font-medium text-muted-foreground",
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
                  "border-t border-border/50 hover:bg-accent/50 transition-colors",
                  onRowClick && "cursor-pointer",
                )}
                onClick={() => onRowClick?.(row)}
              >
                {columns.map((col, j) => (
                  <td
                    key={j}
                    className={cn(
                      "px-3 py-2",
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
