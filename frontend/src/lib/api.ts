/// <reference types="vite/client" />

const API_BASE = import.meta.env.VITE_API_BASE ?? "";

export async function fetchApi<T = unknown>(
  endpoint: string,
  params: Record<string, string | number | boolean | undefined | null> = {},
): Promise<T> {
  const url = new URL(`${API_BASE}/api${endpoint}`, window.location.origin);
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== "") {
      url.searchParams.set(key, String(value));
    }
  }
  const res = await fetch(url);
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}
