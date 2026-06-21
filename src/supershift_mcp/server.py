from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from supershift_mcp.calendar import fetch_ics
from supershift_mcp.calendar import list_shifts as read_shifts
from supershift_mcp.calendar import next_shift as read_next_shift
from supershift_mcp.calendar import parse_shifts, summarize_shifts as summarize_calendar

try:
    from mcp.server.mcpserver import MCPServer
except ImportError:  # pragma: no cover - compatibility with older SDKs
    from mcp.server.fastmcp import FastMCP as MCPServer


mcp = MCPServer("supershift-mcp")


@mcp.tool()
def calendar_status(calendar: str | None = None) -> dict[str, Any]:
    """Return basic information about the configured Supershift export calendar."""
    shifts = parse_shifts(fetch_ics(calendar))
    return {
        "event_count": len(shifts),
        "first_shift": shifts[0].as_dict() if shifts else None,
        "last_shift": shifts[-1].as_dict() if shifts else None,
    }


@mcp.tool()
def list_shifts(start: str, end: str, calendar: str | None = None) -> list[dict[str, Any]]:
    """List shifts overlapping an ISO date/datetime range."""
    return [shift.as_dict() for shift in read_shifts(start, end, calendar)]


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
def upcoming_shifts(days: int = 14, calendar: str | None = None) -> list[dict[str, Any]]:
    """List shifts from now through the next number of days."""
    if days <= 0:
        raise ValueError("days must be positive.")
    now = datetime.now(timezone.utc).astimezone()
    end = now + timedelta(days=days)
    return [shift.as_dict() for shift in read_shifts(now, end, calendar)]


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
