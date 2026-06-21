from __future__ import annotations

from typing import Any

from supershift_mcp.calendar import fetch_ics
from supershift_mcp.calendar import list_shifts as read_shifts
from supershift_mcp.calendar import next_shift as read_next_shift
from supershift_mcp.calendar import parse_shifts, summarize_shifts as summarize_calendar

try:
    from fastapi import FastAPI, Query
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Install the API extra first: pip install 'supershift-mcp[api]'") from exc


app = FastAPI(
    title="Supershift MCP API",
    description="Read-only API for Supershift-exported calendar data.",
    version="0.1.0",
)


@app.get("/health")
def health(calendar: str | None = Query(default=None)) -> dict[str, Any]:
    shifts = parse_shifts(fetch_ics(calendar))
    return {"ok": True, "event_count": len(shifts)}


@app.get("/shifts")
def shifts(start: str, end: str, calendar: str | None = Query(default=None)) -> list[dict[str, Any]]:
    return [shift.as_dict() for shift in read_shifts(start, end, calendar)]


@app.get("/shifts/next")
def next_shift(after: str | None = None, days: int = 90, calendar: str | None = Query(default=None)) -> dict[str, Any] | None:
    shift = read_next_shift(after, days, calendar)
    return shift.as_dict() if shift else None


@app.get("/summary")
def summary(start: str, end: str, calendar: str | None = Query(default=None)) -> dict[str, Any]:
    return summarize_calendar(start, end, calendar)


def main() -> None:
    import uvicorn

    uvicorn.run("supershift_mcp.api:app", host="127.0.0.1", port=8765)
