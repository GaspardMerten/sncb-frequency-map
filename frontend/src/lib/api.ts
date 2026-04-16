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

export interface SSEProgress {
  done: number;
  total: number;
  phase?: string;
}

/**
 * Fetch an SSE endpoint that streams progress events then a final result.
 * Calls onProgress for each "progress" event.
 * Returns the parsed data from the "result" event.
 */
export async function fetchApiSSE<T = unknown>(
  endpoint: string,
  params: Record<string, string | number | boolean | undefined | null> = {},
  onProgress?: (progress: SSEProgress) => void,
): Promise<T> {
  const url = new URL(`${API_BASE}/api${endpoint}`, window.location.origin);
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== "") {
      url.searchParams.set(key, String(value));
    }
  }

  const res = await fetch(url);
  if (!res.ok) throw new Error(`API error: ${res.status}`);

  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let result: T | undefined;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // Parse SSE events from buffer
    const parts = buffer.split("\n\n");
    buffer = parts.pop()!; // keep incomplete part

    for (const part of parts) {
      const lines = part.split("\n");
      let event = "";
      let data = "";
      for (const line of lines) {
        if (line.startsWith("event: ")) event = line.slice(7);
        else if (line.startsWith("data: ")) data = line.slice(6);
      }
      if (event === "progress" && onProgress && data) {
        onProgress(JSON.parse(data));
      } else if (event === "result" && data) {
        result = JSON.parse(data);
      }
    }
  }

  if (result === undefined) throw new Error("No result received from SSE stream");
  return result;
}
