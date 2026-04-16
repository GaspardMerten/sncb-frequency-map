import { useState, useRef, useEffect, useCallback } from "react";
import {
  Send,
  X,
  Bot,
  User,
  Loader2,
} from "lucide-react";
import {
  BarChart, Bar, LineChart, Line, AreaChart, Area,
  ScatterChart, Scatter, PieChart, Pie, Cell,
  XAxis, YAxis, Tooltip, ResponsiveContainer,
} from "recharts";
import { cn } from "@/lib/utils";

/* ---------- Types ---------- */

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  charts?: ChartSpec[];
}

interface ChartSpec {
  chart_type: "bar" | "line" | "area" | "scatter" | "pie";
  title?: string;
  data: Record<string, unknown>[];
  x_key: string;
  y_keys: string[];
  colors?: string[];
  x_label?: string;
  y_label?: string;
}

interface ReportChatbotProps {
  reportData: Record<string, unknown>;
  onClose: () => void;
}

/* ---------- Chart colors ---------- */

const DEFAULT_COLORS = [
  "hsl(220, 70%, 55%)",
  "hsl(350, 70%, 55%)",
  "hsl(160, 60%, 45%)",
  "hsl(45, 80%, 50%)",
  "hsl(280, 60%, 55%)",
];

const PIE_COLORS = [
  "#6366f1", "#f43f5e", "#10b981", "#f59e0b", "#8b5cf6",
  "#06b6d4", "#ec4899", "#84cc16",
];

const TT_STYLE = {
  fontSize: 11,
  borderRadius: 8,
  border: "1px solid var(--color-border)",
  backgroundColor: "var(--color-card)",
};

/* ---------- Chart renderer ---------- */

function ChatChart({ spec }: { spec: ChartSpec }) {
  const colors = spec.colors?.length ? spec.colors : DEFAULT_COLORS;

  const common = (
    <>
      <XAxis
        dataKey={spec.x_key}
        tick={{ fontSize: 10 }}
        label={spec.x_label ? { value: spec.x_label, position: "insideBottom", offset: -5, fontSize: 10 } : undefined}
      />
      <YAxis
        tick={{ fontSize: 10 }}
        label={spec.y_label ? { value: spec.y_label, angle: -90, position: "insideLeft", fontSize: 10 } : undefined}
      />
      <Tooltip contentStyle={TT_STYLE} />
    </>
  );

  return (
    <div className="my-2 bg-muted/30 rounded-lg p-3">
      {spec.title && (
        <p className="text-xs font-medium text-muted-foreground mb-2">{spec.title}</p>
      )}
      <ResponsiveContainer width="100%" height={180}>
        {spec.chart_type === "bar" ? (
          <BarChart data={spec.data}>
            {common}
            {spec.y_keys.map((k, i) => (
              <Bar key={k} dataKey={k} fill={colors[i % colors.length]} radius={[3, 3, 0, 0]} />
            ))}
          </BarChart>
        ) : spec.chart_type === "line" ? (
          <LineChart data={spec.data}>
            {common}
            {spec.y_keys.map((k, i) => (
              <Line key={k} dataKey={k} stroke={colors[i % colors.length]} strokeWidth={2} dot={false} />
            ))}
          </LineChart>
        ) : spec.chart_type === "area" ? (
          <AreaChart data={spec.data}>
            {common}
            {spec.y_keys.map((k, i) => (
              <Area key={k} dataKey={k} stroke={colors[i % colors.length]} fill={colors[i % colors.length]} fillOpacity={0.2} />
            ))}
          </AreaChart>
        ) : spec.chart_type === "scatter" ? (
          <ScatterChart>
            {common}
            <Scatter data={spec.data} fill={colors[0]}>
              {spec.data.map((_, i) => (
                <Cell key={i} fill={colors[i % colors.length]} />
              ))}
            </Scatter>
          </ScatterChart>
        ) : spec.chart_type === "pie" ? (
          <PieChart>
            <Pie
              data={spec.data}
              dataKey={spec.y_keys[0]}
              nameKey={spec.x_key}
              cx="50%"
              cy="50%"
              outerRadius={70}
              label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`}
            >
              {spec.data.map((_, i) => (
                <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />
              ))}
            </Pie>
            <Tooltip contentStyle={TT_STYLE} />
          </PieChart>
        ) : (
          <BarChart data={spec.data}>
            {common}
            {spec.y_keys.map((k, i) => (
              <Bar key={k} dataKey={k} fill={colors[i % colors.length]} />
            ))}
          </BarChart>
        )}
      </ResponsiveContainer>
    </div>
  );
}

/* ---------- Markdown-lite renderer ---------- */

function renderContent(text: string) {
  // Simple markdown: **bold**, `code`, newlines
  const parts = text.split(/(\*\*.*?\*\*|`[^`]+`|\n)/g);
  return parts.map((p, i) => {
    if (p.startsWith("**") && p.endsWith("**"))
      return <strong key={i}>{p.slice(2, -2)}</strong>;
    if (p.startsWith("`") && p.endsWith("`"))
      return <code key={i} className="bg-muted/50 px-1 py-0.5 rounded text-[11px]">{p.slice(1, -1)}</code>;
    if (p === "\n") return <br key={i} />;
    return <span key={i}>{p}</span>;
  });
}

/* ---------- Component ---------- */

export function ReportChatbot({ reportData, onClose }: ReportChatbotProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: "welcome",
      role: "assistant",
      content:
        "Hello! I can help you understand this missed connections report. Ask me anything about the data — patterns, stations, weather impact, or I can create charts to visualize specific insights.",
    },
  ]);
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const sendMessage = useCallback(async () => {
    const text = input.trim();
    if (!text || isStreaming) return;

    const userMsg: ChatMessage = { id: crypto.randomUUID(), role: "user", content: text };
    const assistantMsg: ChatMessage = { id: crypto.randomUUID(), role: "assistant", content: "", charts: [] };

    setMessages((prev) => [...prev, userMsg, assistantMsg]);
    setInput("");
    setIsStreaming(true);

    // Build history (exclude welcome message)
    const history = [...messages.filter((m) => m.id !== "welcome"), userMsg].map((m) => ({
      role: m.role,
      content: m.content,
    }));

    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ messages: history, report_data: reportData }),
      });

      if (!res.ok) throw new Error(`API error: ${res.status}`);

      const reader = res.body!.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split("\n");
        buffer = lines.pop()!;

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const raw = line.slice(6);
          if (raw === "[DONE]") break;

          try {
            const event = JSON.parse(raw);
            if (event.type === "text") {
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantMsg.id ? { ...m, content: m.content + event.content } : m,
                ),
              );
            } else if (event.type === "chart") {
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantMsg.id
                    ? { ...m, charts: [...(m.charts || []), event.spec as ChartSpec] }
                    : m,
                ),
              );
            } else if (event.type === "error") {
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantMsg.id ? { ...m, content: `Error: ${event.content}` } : m,
                ),
              );
            }
          } catch {
            // skip malformed lines
          }
        }
      }
    } catch (err) {
      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantMsg.id
            ? { ...m, content: `Failed to get response: ${(err as Error).message}` }
            : m,
        ),
      );
    } finally {
      setIsStreaming(false);
    }
  }, [input, isStreaming, messages, reportData]);

  return (
    <div className="flex flex-col h-full border-l border-border/40 bg-background">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border/40">
        <div className="flex items-center gap-2">
          <Bot className="w-4 h-4 text-primary" />
          <span className="text-sm font-semibold">Report Assistant</span>
        </div>
        <button
          onClick={onClose}
          className="p-1 rounded-md hover:bg-muted/50 transition-colors cursor-pointer"
        >
          <X className="w-4 h-4 text-muted-foreground" />
        </button>
      </div>

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.map((msg) => (
          <div
            key={msg.id}
            className={cn(
              "flex gap-2.5",
              msg.role === "user" ? "justify-end" : "justify-start",
            )}
          >
            {msg.role === "assistant" && (
              <div className="w-6 h-6 rounded-full bg-primary/10 flex items-center justify-center shrink-0 mt-0.5">
                <Bot className="w-3.5 h-3.5 text-primary" />
              </div>
            )}
            <div
              className={cn(
                "max-w-[85%] rounded-xl px-3.5 py-2.5 text-[13px] leading-relaxed",
                msg.role === "user"
                  ? "bg-primary text-primary-foreground"
                  : "bg-muted/40",
              )}
            >
              {msg.content ? renderContent(msg.content) : (
                isStreaming && msg.role === "assistant" && !msg.content ? (
                  <Loader2 className="w-4 h-4 animate-spin text-muted-foreground" />
                ) : null
              )}
              {msg.charts?.map((spec, i) => (
                <ChatChart key={i} spec={spec} />
              ))}
            </div>
            {msg.role === "user" && (
              <div className="w-6 h-6 rounded-full bg-primary/20 flex items-center justify-center shrink-0 mt-0.5">
                <User className="w-3.5 h-3.5 text-primary" />
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Input */}
      <div className="border-t border-border/40 p-3">
        <div className="flex gap-2">
          <input
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && sendMessage()}
            placeholder="Ask about the report..."
            disabled={isStreaming}
            className="flex-1 bg-muted/30 rounded-lg px-3 py-2 text-sm placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary/30 disabled:opacity-50"
          />
          <button
            onClick={sendMessage}
            disabled={isStreaming || !input.trim()}
            className={cn(
              "p-2 rounded-lg transition-colors cursor-pointer",
              input.trim() && !isStreaming
                ? "bg-primary text-primary-foreground hover:bg-primary/90"
                : "bg-muted/30 text-muted-foreground/40",
            )}
          >
            {isStreaming ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Send className="w-4 h-4" />
            )}
          </button>
        </div>
        <p className="text-[10px] text-muted-foreground/40 mt-1.5 text-center">
          Powered by Gemini — may make mistakes
        </p>
      </div>
    </div>
  );
}
