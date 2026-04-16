"""Chat endpoint for the missed-connections report chatbot.

Uses Google Gemini to answer questions about report data,
with tool-calling support for generating chart specifications.
"""

import json
import os
from typing import Any

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

router = APIRouter()

_GEMINI_KEY = os.getenv("GEMINI_API_KEY", "")
_GEMINI_MODEL = "gemini-2.5-flash"
_GEMINI_URL = (
    f"https://generativelanguage.googleapis.com/v1beta/models/{_GEMINI_MODEL}"
    f":streamGenerateContent?alt=sse&key={_GEMINI_KEY}"
)

# ---- Tool definitions for Gemini function calling ----

_TOOLS = [
    {
        "function_declarations": [
            {
                "name": "render_chart",
                "description": (
                    "Render a Recharts chart in the chat. Supports bar, line, area, scatter, and pie charts. "
                    "Provide the chart type, data array, and axis configuration."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "chart_type": {
                            "type": "string",
                            "enum": ["bar", "line", "area", "scatter", "pie"],
                            "description": "Type of chart to render",
                        },
                        "title": {
                            "type": "string",
                            "description": "Chart title",
                        },
                        "data": {
                            "type": "array",
                            "items": {"type": "object"},
                            "description": "Array of data objects for the chart",
                        },
                        "x_key": {
                            "type": "string",
                            "description": "Key in data objects for X axis (or name key for pie)",
                        },
                        "y_keys": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Keys in data objects for Y axis series",
                        },
                        "colors": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Colors for each Y series (hex codes)",
                        },
                        "x_label": {"type": "string", "description": "X axis label"},
                        "y_label": {"type": "string", "description": "Y axis label"},
                    },
                    "required": ["chart_type", "data", "x_key", "y_keys"],
                },
            },
        ]
    }
]

_SYSTEM_PROMPT = """\
You are an expert data analyst assistant embedded in a Belgian railway missed-connections report.
You help the user understand the report data, spot patterns, and draw conclusions.

## Your capabilities
- Explain any section of the report (overview, daily/hourly patterns, stations, corridors, weather, etc.)
- Perform calculations and cross-reference data across sections
- Generate charts using the `render_chart` tool to visualize insights
- Compare metrics across different dimensions (hours, days, stations, corridors)

## Guidelines
- Be concise but insightful — prioritize actionable findings
- Use Belgian railway context (SNCB/NMBS, common routes, commuter patterns)
- When showing numbers, use the exact data from the report context
- If the user asks about data not in the report, explain what data IS available
- Proactively suggest interesting analyses when appropriate
- Use render_chart to create visualizations when they'd help explain a point
- Answer in the same language the user writes in (French, Dutch, English)
- When comparing or ranking, always cite the numbers from the data

## Key metric definitions
- **Planned connections**: number of arriving_train→departing_train pairs where the planned gap
  was between min_transfer and max_transfer minutes (typically 2-15 min) at the same station
- **Missed connection**: a planned connection where the arriving train was late enough that it
  arrived AFTER the departing train left (actual_arr > actual_dep)
- **Miss rate (pct)**: missed / planned × 100
- **Close call**: a connection where the arriving train was delayed (delay_arr > 0) but the
  connection was still made (actual_arr <= actual_dep) — i.e., nearly missed but saved
- **Impact score** (for stations): missed_count × sqrt(pct_missed/100). This weights both volume
  and rate — a station with 1000 misses at 10% is ranked higher than one with 100 misses at 50%.
  Stations are sorted by impact score in the report.
- **Added wait time**: when a connection is missed, the extra minutes the passenger must wait
  for the next available departure at that station. Only counted when next departure found within 60 min.
- **Domino trains**: arriving trains that cause the most missed connections across multiple stations.
  Sorted by total_missed_caused. n_days_seen = max days seen at any single station (not sum across stations).
- **Rain sensitivity** (weather-sensitive trains): avg_delay_rainy / avg_delay_dry. A value of 2.0×
  means the train is twice as delayed on rainy days. Only shown when ≥3 rainy AND ≥3 dry days exist.
- **Corridors**: track connections for specific origin→destination city pairs routed through Brussels.
  Each corridor has worst_hours showing which hours have the highest miss rate on that specific route.

## Data structure
The full report JSON is provided below. You have access to ALL data the user sees. Key sections:
- overview: period, totals, percentages
- hourly[]: per-hour planned/missed/pct for ALL hours 0-23
- daily[]: per-day breakdown with day-of-week
- dow_summary[]: aggregated by day of week
- stations[]: top stations with planned/missed/pct_missed/impact_score, some have worst_pairs[]
- corridors[]: per-corridor with planned/missed/pct_missed AND worst_hours[] per corridor
- hub_spotlight[]: detailed per-station analysis with heatmap[] (hour×dow grid) and toxic_arrivals[]
- domino_trains[]: trains causing most downstream misses
- lucky: close-call statistics
- added_wait: wait time distribution
- weather: daily weather data with correlations and comparison (rain/wind/cold thresholds)
- weather_sensitive_trains[]: per-train rain/wind sensitivity

Cross-reference freely. For example, if asked "which corridor is worst at 18h", look at each
corridor's worst_hours array for hour=18. If asked about a specific station's hourly pattern,
check hub_spotlight for that station's heatmap data.
"""


@router.post("/chat")
async def chat_endpoint(request: Request):
    """Stream a chat response using Gemini with report context."""
    body = await request.json()
    messages: list[dict] = body.get("messages", [])
    report_data: dict = body.get("report_data", {})

    # Send the full report JSON — Gemini has a large context window
    # and can parse structured data better than a lossy text summary
    report_json = json.dumps(report_data, default=str, ensure_ascii=False)

    # Build Gemini contents array
    contents = []
    for msg in messages:
        role = "user" if msg["role"] == "user" else "model"
        contents.append({
            "role": role,
            "parts": [{"text": msg["content"]}],
        })

    gemini_body = {
        "contents": contents,
        "systemInstruction": {
            "parts": [
                {"text": _SYSTEM_PROMPT},
                {"text": f"## Full report data (JSON)\n\n{report_json}"},
            ]
        },
        "tools": _TOOLS,
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 4096,
        },
    }

    async def stream():
        async with httpx.AsyncClient(timeout=60.0) as client:
            async with client.stream(
                "POST", _GEMINI_URL, json=gemini_body
            ) as response:
                if response.status_code != 200:
                    error_body = await response.aread()
                    yield f"data: {json.dumps({'type': 'error', 'content': f'Gemini API error {response.status_code}: {error_body.decode()[:200]}'})}\n\n"
                    return

                buffer = ""
                async for chunk in response.aiter_text():
                    buffer += chunk
                    # SSE from Gemini: lines starting with "data: "
                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        line = line.strip()
                        if not line.startswith("data: "):
                            continue
                        raw = line[6:]
                        if raw == "[DONE]":
                            break
                        try:
                            payload = json.loads(raw)
                        except json.JSONDecodeError:
                            continue

                        candidates = payload.get("candidates", [])
                        if not candidates:
                            continue
                        content = candidates[0].get("content", {})
                        parts = content.get("parts", [])

                        for part in parts:
                            if "text" in part:
                                yield f"data: {json.dumps({'type': 'text', 'content': part['text']})}\n\n"
                            elif "functionCall" in part:
                                fc = part["functionCall"]
                                if fc["name"] == "render_chart":
                                    yield f"data: {json.dumps({'type': 'chart', 'spec': fc['args']})}\n\n"

            yield "data: [DONE]\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")
