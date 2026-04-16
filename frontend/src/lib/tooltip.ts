export const tooltipStyle = {
  backgroundColor: "rgba(255,255,255,0.95)",
  color: "#111",
  padding: "6px 8px",
  borderRadius: "8px",
  border: "1px solid #e5e7eb",
  boxShadow: "0 2px 8px rgba(0,0,0,0.12)",
  fontSize: "12px",
} as const;

export function tooltipBox(html: string) {
  return { html, style: tooltipStyle };
}
