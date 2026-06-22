from __future__ import annotations

from datetime import datetime, timedelta, timezone
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
from supershift_mcp.writer import android_device_status as read_android_device_status
from supershift_mcp.writer import build_android_calendar_intents
from supershift_mcp.writer import build_ui_automation_plan
from supershift_mcp.writer import create_supershift_shifts as write_supershift_shifts
from supershift_mcp.writer import create_supershift_shifts_from_text as write_supershift_shifts_from_text
from supershift_mcp.writer import dump_supershift_ui as read_supershift_ui
from supershift_mcp.writer import load_ui_profile
from supershift_mcp.writer import parse_shift_text as parse_shift_lines
from supershift_mcp.writer import supershift_app_status as read_supershift_app_status
from supershift_mcp.writer import validate_shift_drafts

try:
    from mcp.server.mcpserver import MCPServer
except ImportError:  # pragma: no cover - compatibility with older SDKs
    from mcp.server.fastmcp import FastMCP as MCPServer


mcp = MCPServer("supershift-mcp")


@mcp.tool()
def calendar_status(calendar: str | None = None) -> dict[str, Any]:
    """Return basic information about the configured Supershift export calendar."""
    return calendar_bounds(calendar)


@mcp.tool()
def list_shifts(start: str, end: str, calendar: str | None = None) -> list[dict[str, Any]]:
    """List shifts overlapping an ISO date/datetime range."""
    return [shift.as_dict() for shift in read_shifts(start, end, calendar)]


@mcp.tool()
def filter_shifts(
    start: str,
    end: str,
    calendar: str | None = None,
    title_contains: str | None = None,
    location_contains: str | None = None,
    notes_contains: str | None = None,
    min_hours: float | None = None,
    max_hours: float | None = None,
) -> list[dict[str, Any]]:
    """List shifts matching text and duration filters."""
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


@mcp.tool()
def get_shift(uid: str, calendar: str | None = None) -> dict[str, Any] | None:
    """Find one shift by calendar UID."""
    return read_shift(uid, calendar)


@mcp.tool()
def current_shift(at: str | None = None, calendar: str | None = None) -> dict[str, Any] | None:
    """Return the active shift at an ISO date/datetime, or now if omitted."""
    return read_current_shift(at, calendar)


@mcp.tool()
def shifts_on_date(day: str, calendar: str | None = None) -> list[dict[str, Any]]:
    """List all shifts touching one calendar date."""
    return read_shifts_on_date(day, calendar)


@mcp.tool()
def next_shift(after: str | None = None, days: int = 90, calendar: str | None = None) -> dict[str, Any] | None:
    """Return the next shift after an ISO date/datetime, searching up to days ahead."""
    shift = read_next_shift(after, days, calendar)
    return shift.as_dict() if shift else None


@mcp.tool()
def summarize_shifts(start: str, end: str, calendar: str | None = None) -> dict[str, Any]:
    """Summarize shift count and hours over an ISO date/datetime range."""
    return summarize_calendar(start, end, calendar)


@mcp.tool()
def summarize_by_period(
    start: str,
    end: str,
    period: str = "day",
    calendar: str | None = None,
    include_all_day: bool = False,
) -> dict[str, Any]:
    """Summarize hours by day, week, month, or weekday."""
    return summarize_calendar_by_period(start, end, period, calendar, include_all_day)


@mcp.tool()
def detect_conflicts(start: str, end: str, calendar: str | None = None) -> list[dict[str, Any]]:
    """Find overlapping shifts in a range."""
    return read_conflicts(start, end, calendar)


@mcp.tool()
def rest_periods(
    start: str,
    end: str,
    calendar: str | None = None,
    minimum_hours: float = 11,
) -> list[dict[str, Any]]:
    """Calculate rest hours between consecutive shifts and flag short rests."""
    return read_rest_periods(start, end, calendar, minimum_hours)


@mcp.tool()
def free_days(start: str, end: str, calendar: str | None = None) -> list[str]:
    """List dates without any shift between start inclusive and end exclusive."""
    return read_free_days(start, end, calendar)


@mcp.tool()
def export_shifts(
    start: str,
    end: str,
    output_format: str = "json",
    calendar: str | None = None,
) -> str:
    """Export shifts as json, csv, or markdown."""
    return export_calendar_shifts(start, end, output_format, calendar)


@mcp.tool()
def estimate_pay(
    start: str,
    end: str,
    hourly_rate: float,
    calendar: str | None = None,
    title_rates: dict[str, float] | None = None,
    currency: str = "EUR",
    include_all_day: bool = False,
) -> dict[str, Any]:
    """Estimate pay using a default hourly rate and optional per-title rates."""
    return estimate_calendar_pay(start, end, hourly_rate, calendar, title_rates, currency, include_all_day)


@mcp.tool()
def shift_titles(calendar: str | None = None) -> list[str]:
    """List distinct shift titles found in the calendar."""
    return unique_titles(calendar)


@mcp.tool()
def shift_locations(calendar: str | None = None) -> list[str]:
    """List distinct shift locations found in the calendar."""
    return unique_locations(calendar)


@mcp.tool()
def upcoming_shifts(days: int = 14, calendar: str | None = None) -> list[dict[str, Any]]:
    """List shifts from now through the next number of days."""
    if days <= 0:
        raise ValueError("days must be positive.")
    now = datetime.now(timezone.utc).astimezone()
    end = now + timedelta(days=days)
    return [shift.as_dict() for shift in read_shifts(now, end, calendar)]


@mcp.tool()
def parse_shifts_text(text: str, default_timezone: str = "+02:00") -> list[dict[str, Any]]:
    """Parse text lines like '24.06.2026 06:00-14:00 Fruehdienst @ Ort # Notiz'."""
    return [draft.as_dict() for draft in parse_shift_lines(text, default_timezone)]


@mcp.tool()
def validate_shifts_for_write(shifts: list[dict[str, Any]]) -> list[str]:
    """Validate structured shifts before attempting a write backend."""
    return validate_shift_drafts(shifts)


@mcp.tool()
def android_device_status() -> dict[str, Any]:
    """Report connected Android devices visible through ADB."""
    return read_android_device_status()


@mcp.tool()
def supershift_app_status() -> dict[str, Any]:
    """Report whether app.supershift is installed on the connected Android device."""
    return read_supershift_app_status()


@mcp.tool()
def dump_supershift_ui() -> dict[str, Any]:
    """Launch Supershift and dump the current Android UI XML for profile creation."""
    return read_supershift_ui()


@mcp.tool()
def preview_supershift_write(
    shifts: list[dict[str, Any]],
    backend: str = "adb_ui",
    profile_path: str | None = None,
) -> dict[str, Any]:
    """Build a dry-run write plan for Supershift without touching the device."""
    if backend == "adb_ui":
        profile = load_ui_profile(profile_path)
        return build_ui_automation_plan(shifts, profile)
    if backend == "android_calendar_intent":
        return {
            "ok": True,
            "backend": backend,
            "commands": build_android_calendar_intents(shifts),
            "warning": "This opens Android Calendar insert intents, not the Supershift app.",
        }
    raise ValueError("backend must be one of: adb_ui, android_calendar_intent.")


@mcp.tool()
def create_supershift_shifts(
    shifts: list[dict[str, Any]],
    backend: str = "adb_ui",
    profile_path: str | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Create shifts through a configured backend. Defaults to dry-run."""
    return write_supershift_shifts(shifts, backend, profile_path, dry_run)


@mcp.tool()
def create_supershift_shifts_from_text(
    text: str,
    backend: str = "adb_ui",
    profile_path: str | None = None,
    dry_run: bool = True,
    default_timezone: str = "+02:00",
) -> dict[str, Any]:
    """Parse free text and create shifts through a configured backend. Defaults to dry-run."""
    return write_supershift_shifts_from_text(text, backend, profile_path, dry_run, default_timezone=default_timezone)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
