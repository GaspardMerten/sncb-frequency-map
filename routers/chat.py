"""Chat endpoint for the missed-connections report chatbot.

Uses Google Gemini to answer questions about report data,
with tool-calling support for fetching additional data and
generating chart specifications.
"""

import json
import os
from datetime import date, timedelta
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
- Perform calculations on the provided data
- Generate charts using the `render_chart` tool to visualize insights
- Compare metrics across different dimensions

## Guidelines
- Be concise but insightful — prioritize actionable findings
- Use Belgian railway context (SNCB/NMBS, common routes, commuter patterns)
- When showing numbers, use the exact data from the report context
- If the user asks about data not in the report, explain what data is available
- Proactively suggest interesting analyses when appropriate
- Use render_chart to create visualizations when they'd help explain a point
- Answer in the same language the user writes in (French, Dutch, English)

## Report context
The report analyzes missed train connections: when a connecting train departs before a delayed arriving train reaches the station.
Key metrics: planned connections, missed connections, miss rate, added wait time, close calls (connections saved despite delays).
"""


def _build_report_context(report_summary: dict) -> str:
    """Build a concise text summary of report data for the LLM context."""
    parts = []
    ov = report_summary.get("overview", {})
    if ov:
        parts.append(
            f"Period: {ov.get('start_date', '?')} to {ov.get('end_date', '?')} ({ov.get('n_days', '?')} days)\n"
            f"Total connections: {ov.get('total_connections', 0):,} | "
            f"Missed: {ov.get('total_missed', 0):,} ({ov.get('pct_missed', 0)}%)\n"
            f"Close calls (saved): {ov.get('close_calls', 0):,} | "
            f"Total added wait: {ov.get('total_added_wait_minutes', 0):,.0f} min"
        )

    hourly = report_summary.get("hourly", [])
    if hourly:
        worst = sorted(hourly, key=lambda h: -h.get("pct", 0))[:3]
        parts.append(
            "Worst hours: "
            + ", ".join(f"{h['hour']}h ({h['pct']}%)" for h in worst)
        )

    dow = report_summary.get("dow_summary", [])
    if dow:
        worst_d = sorted(dow, key=lambda d: -d.get("pct", 0))[:2]
        parts.append(
            "Worst days: "
            + ", ".join(f"{d['label']} ({d['pct']}%)" for d in worst_d)
        )

    stations = report_summary.get("stations", [])
    if stations:
        top = stations[:10]
        parts.append(
            "Top 10 stations by impact:\n"
            + "\n".join(
                f"  {s['name']}: {s['missed']}/{s['planned']} missed ({s['pct_missed']}%), "
                f"impact={s.get('impact_score', 0):.0f}"
                for s in top
            )
        )

    corridors = report_summary.get("corridors", [])
    if corridors:
        parts.append(
            "Corridors:\n"
            + "\n".join(
                f"  {c['origin']}→{c['destination']}: {c['pct_missed']}% missed, "
                f"reliability {c['reliability_pct']}%"
                for c in corridors
            )
        )

    lucky = report_summary.get("lucky", {})
    if lucky:
        parts.append(
            f"Close calls: {lucky.get('total_close_calls', 0):,} "
            f"({lucky.get('pct_saved', 0)}% of at-risk connections saved)"
        )

    wait = report_summary.get("added_wait", {})
    if wait:
        parts.append(
            f"Added wait: avg {wait.get('avg_wait_min', 0):.1f} min, "
            f"median {wait.get('median_wait_min', 0):.1f} min"
        )

    domino = report_summary.get("domino_trains", [])
    if domino:
        top_d = domino[:5]
        parts.append(
            "Top domino trains (cause most downstream misses):\n"
            + "\n".join(
                f"  {t.get('relation', t['train'])} ({t['train']}): "
                f"{t['total_missed_caused']} misses across {t['n_stations']} stations"
                for t in top_d
            )
        )

    weather = report_summary.get("weather")
    if weather:
        corr = weather.get("correlations", {})
        parts.append(
            "Weather correlations: "
            + ", ".join(f"{k}={v:.2f}" for k, v in corr.items())
        )

    ws_trains = report_summary.get("weather_sensitive_trains", [])
    if ws_trains:
        parts.append(
            f"Weather-sensitive trains: {len(ws_trains)} identified\n"
            + "\n".join(
                f"  {t.get('relation', t['train'])}: "
                f"rain sensitivity {t['rain_sensitivity']:.1f}x "
                f"(rainy {t['avg_delay_rainy']:.1f}min vs dry {t['avg_delay_dry']:.1f}min)"
                for t in ws_trains[:5]
            )
        )

    daily = report_summary.get("daily", [])
    if daily:
        parts.append(
            "Daily breakdown:\n"
            + "\n".join(
                f"  {d['date']} ({d['dow_label']}): "
                f"{d['missed']}/{d['planned']} ({d['pct']}%)"
                for d in daily
            )
        )

    return "\n\n".join(parts)


@router.post("/chat")
async def chat_endpoint(request: Request):
    """Stream a chat response using Gemini with report context."""
    body = await request.json()
    messages: list[dict] = body.get("messages", [])
    report_data: dict = body.get("report_data", {})

    report_context = _build_report_context(report_data)

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
                {"text": f"## Current report data\n\n{report_context}"},
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
            tool_calls_pending = []
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
