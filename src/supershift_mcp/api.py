from __future__ import annotations

from typing import Any

from supershift_mcp.calendar import calendar_bounds
from supershift_mcp.calendar import current_shift as read_current_shift
from supershift_mcp.calendar import detect_conflicts as read_conflicts
from supershift_mcp.calendar import estimate_pay as estimate_calendar_pay
from supershift_mcp.calendar import export_shifts as export_calendar_shifts
from supershift_mcp.calendar import filter_shifts as read_filtered_shifts
from supershift_mcp.calendar import find_free_days as read_free_days
from supershift_mcp.calendar import find_shift as read_shift
from supershift_mcp.calendar import list_shifts as read_shifts
from supershift_mcp.calendar import next_shift as read_next_shift
from supershift_mcp.calendar import rest_periods as read_rest_periods
from supershift_mcp.calendar import shifts_on_date as read_shifts_on_date
from supershift_mcp.calendar import summarize_by_period as summarize_calendar_by_period
from supershift_mcp.calendar import summarize_shifts as summarize_calendar
from supershift_mcp.calendar import unique_locations, unique_titles

try:
    from fastapi import FastAPI, Query, Response
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Install the API extra first: pip install 'supershift-mcp[api]'") from exc


app = FastAPI(
    title="Supershift MCP API",
    description="Read-only API for Supershift-exported calendar data.",
    version="0.1.0",
)


@app.get("/health")
def health(calendar: str | None = Query(default=None)) -> dict[str, Any]:
    return {"ok": True, **calendar_bounds(calendar)}


@app.get("/shifts")
def shifts(start: str, end: str, calendar: str | None = Query(default=None)) -> list[dict[str, Any]]:
    return [shift.as_dict() for shift in read_shifts(start, end, calendar)]


@app.get("/shifts/filter")
def filtered_shifts(
    start: str,
    end: str,
    calendar: str | None = Query(default=None),
    title_contains: str | None = None,
    location_contains: str | None = None,
    notes_contains: str | None = None,
    min_hours: float | None = None,
    max_hours: float | None = None,
) -> list[dict[str, Any]]:
    return [
        shift.as_dict()
        for shift in read_filtered_shifts(
            start,
            end,
            calendar,
            title_contains,
            location_contains,
            notes_contains,
            min_hours,
            max_hours,
        )
    ]


@app.get("/shifts/current")
def current_shift(at: str | None = None, calendar: str | None = Query(default=None)) -> dict[str, Any] | None:
    return read_current_shift(at, calendar)


@app.get("/shifts/next")
def next_shift(after: str | None = None, days: int = 90, calendar: str | None = Query(default=None)) -> dict[str, Any] | None:
    shift = read_next_shift(after, days, calendar)
    return shift.as_dict() if shift else None


@app.get("/shifts/date/{day}")
def shifts_on_date(day: str, calendar: str | None = Query(default=None)) -> list[dict[str, Any]]:
    return read_shifts_on_date(day, calendar)


@app.get("/shifts/{uid}")
def get_shift(uid: str, calendar: str | None = Query(default=None)) -> dict[str, Any] | None:
    return read_shift(uid, calendar)


@app.get("/summary")
def summary(start: str, end: str, calendar: str | None = Query(default=None)) -> dict[str, Any]:
    return summarize_calendar(start, end, calendar)


@app.get("/summary/period")
def period_summary(
    start: str,
    end: str,
    period: str = "day",
    calendar: str | None = Query(default=None),
    include_all_day: bool = False,
) -> dict[str, Any]:
    return summarize_calendar_by_period(start, end, period, calendar, include_all_day)


@app.get("/conflicts")
def conflicts(start: str, end: str, calendar: str | None = Query(default=None)) -> list[dict[str, Any]]:
    return read_conflicts(start, end, calendar)


@app.get("/rest-periods")
def rest_periods(
    start: str,
    end: str,
    calendar: str | None = Query(default=None),
    minimum_hours: float = 11,
) -> list[dict[str, Any]]:
    return read_rest_periods(start, end, calendar, minimum_hours)


@app.get("/free-days")
def free_days(start: str, end: str, calendar: str | None = Query(default=None)) -> list[str]:
    return read_free_days(start, end, calendar)


@app.get("/export")
def export_shifts(
    start: str,
    end: str,
    output_format: str = "json",
    calendar: str | None = Query(default=None),
) -> Response:
    body = export_calendar_shifts(start, end, output_format, calendar)
    media_type = {
        "csv": "text/csv",
        "markdown": "text/markdown",
    }.get(output_format.lower(), "application/json")
    return Response(content=body, media_type=media_type)


@app.get("/pay")
def estimate_pay(
    start: str,
    end: str,
    hourly_rate: float,
    calendar: str | None = Query(default=None),
    currency: str = "EUR",
    include_all_day: bool = False,
) -> dict[str, Any]:
    return estimate_calendar_pay(start, end, hourly_rate, calendar, currency=currency, include_all_day=include_all_day)


@app.get("/titles")
def titles(calendar: str | None = Query(default=None)) -> list[str]:
    return unique_titles(calendar)


@app.get("/locations")
def locations(calendar: str | None = Query(default=None)) -> list[str]:
    return unique_locations(calendar)


def main() -> None:
    import uvicorn

    uvicorn.run("supershift_mcp.api:app", host="127.0.0.1", port=8765)
