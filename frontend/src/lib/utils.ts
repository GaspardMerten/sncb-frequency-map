import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Green -> Yellow -> Red color interpolation */
export function valueToColor(ratio: number): string {
  ratio = Math.max(0, Math.min(1, ratio));
  let r: number, g: number, b: number;
  if (ratio < 0.5) {
    const t = ratio * 2;
    r = Math.round(34 + 221 * t);
    g = Math.round(180 - 40 * t);
    b = Math.round(34 - 30 * t);
  } else {
    const t = (ratio - 0.5) * 2;
    r = Math.round(255 - 35 * t);
    g = Math.round(140 - 120 * t);
    b = Math.round(4 + 30 * t);
  }
  return `rgb(${r},${g},${b})`;
}

/** Format number with locale separators */
export function fmt(n: number | null | undefined, decimals = 0): string {
  if (n === null || n === undefined) return "\u2014";
  return Number(n).toLocaleString("en", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

/** Get date string N days ago */
export function daysAgo(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
}

/** Today as YYYY-MM-DD */
export function today(): string {
  return new Date().toISOString().slice(0, 10);
}

/** Build standard filter params */
export function filterParams(filters: {
  startDate: string;
  endDate: string;
  weekdays: number[];
  excludePub: boolean;
  excludeSch: boolean;
  useHour: boolean;
  hourStart: number;
  hourEnd: number;
}): Record<string, string | number | boolean> {
  const params: Record<string, string | number | boolean> = {
    start: filters.startDate,
    end: filters.endDate,
    weekdays: filters.weekdays.join(","),
    exclude_pub: filters.excludePub,
    exclude_sch: filters.excludeSch,
  };
  if (filters.useHour) {
    params.hour_start = filters.hourStart;
    params.hour_end = filters.hourEnd;
  }
  return params;
}
