from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
import os
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from dateutil.parser import isoparse
from icalendar import Calendar


DEFAULT_ENV = "SUPERSHIFT_ICS"


@dataclass(frozen=True)
class Shift:
    uid: str | None
    title: str
    start: datetime
    end: datetime
    all_day: bool = False
    location: str | None = None
    notes: str | None = None

    @property
    def duration_hours(self) -> float:
        return max((self.end - self.start).total_seconds() / 3600, 0)

    def as_dict(self) -> dict[str, Any]:
        return {
            "uid": self.uid,
            "title": self.title,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "all_day": self.all_day,
            "location": self.location,
            "notes": self.notes,
            "duration_hours": round(self.duration_hours, 2),
        }


def resolve_calendar_source(calendar: str | None = None) -> str:
    source = calendar or os.getenv(DEFAULT_ENV)
    if not source:
        raise ValueError(f"Provide a calendar path/URL or set {DEFAULT_ENV}.")
    return source


def fetch_ics(calendar: str | None = None) -> bytes:
    source = resolve_calendar_source(calendar)
    if source.startswith(("http://", "https://")):
        request = Request(source, headers={"User-Agent": "supershift-mcp/0.1"})
        with urlopen(request, timeout=20) as response:
            return response.read()

    path = Path(source).expanduser()
    return path.read_bytes()


def parse_boundary(value: str | datetime | date | None, *, default: datetime | None = None) -> datetime:
    if value is None:
        if default is None:
            raise ValueError("A date or datetime value is required.")
        return default
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return _with_local_timezone(datetime.combine(value, time.min))

    parsed = isoparse(value)
    return _with_local_timezone(parsed)


def _with_local_timezone(value: datetime) -> datetime:
    if value.tzinfo is not None:
        return value
    return value.replace(tzinfo=datetime.now().astimezone().tzinfo)


def _to_datetime(value: Any) -> tuple[datetime, bool]:
    if isinstance(value, datetime):
        return value, False
    if isinstance(value, date):
        return _with_local_timezone(datetime.combine(value, time.min)), True
    raise ValueError(f"Unsupported calendar datetime value: {value!r}")


def _text(component: Any, key: str) -> str | None:
    value = component.get(key)
    if value is None:
        return None
    return str(value)


def _event_to_shift(event: Any) -> Shift:
    start_raw = event.decoded("dtstart")
    end_raw = event.decoded("dtend", None)
    start, all_day = _to_datetime(start_raw)
    if end_raw is None:
        end = start
    else:
        end, _ = _to_datetime(end_raw)

    return Shift(
        uid=_text(event, "uid"),
        title=_text(event, "summary") or "Shift",
        start=start,
        end=end,
        all_day=all_day,
        location=_text(event, "location"),
        notes=_text(event, "description"),
    )


def parse_shifts(ics_data: bytes) -> list[Shift]:
    calendar = Calendar.from_ical(ics_data)
    shifts: list[Shift] = []
    for event in calendar.walk("VEVENT"):
        shifts.append(_event_to_shift(event))
    return sorted(shifts, key=lambda shift: (shift.start, shift.end, shift.title))


def _overlaps(shift: Shift, start: datetime, end: datetime) -> bool:
    return shift.start < end and shift.end > start


def list_shifts(start: str | datetime | date, end: str | datetime | date, calendar: str | None = None) -> list[Shift]:
    start_dt = parse_boundary(start)
    end_dt = parse_boundary(end)
    if end_dt <= start_dt:
        raise ValueError("end must be after start.")

    return [
        shift
        for shift in parse_shifts(fetch_ics(calendar))
        if _overlaps(shift, start_dt, end_dt)
    ]


def next_shift(after: str | datetime | date | None = None, days: int = 90, calendar: str | None = None) -> Shift | None:
    if days <= 0:
        raise ValueError("days must be positive.")

    now = datetime.now(timezone.utc).astimezone()
    after_dt = parse_boundary(after, default=now)
    horizon = after_dt + timedelta(days=days)

    candidates = [
        shift
        for shift in list_shifts(after_dt, horizon, calendar)
        if shift.end > after_dt
    ]
    return candidates[0] if candidates else None


def summarize_shifts(start: str | datetime | date, end: str | datetime | date, calendar: str | None = None) -> dict[str, Any]:
    shifts = list_shifts(start, end, calendar)
    by_title: dict[str, dict[str, float | int | str]] = {}
    for shift in shifts:
        bucket = by_title.setdefault(
            shift.title,
            {"title": shift.title, "count": 0, "duration_hours": 0.0},
        )
        bucket["count"] = int(bucket["count"]) + 1
        bucket["duration_hours"] = round(float(bucket["duration_hours"]) + shift.duration_hours, 2)

    return {
        "start": parse_boundary(start).isoformat(),
        "end": parse_boundary(end).isoformat(),
        "count": len(shifts),
        "duration_hours": round(sum(shift.duration_hours for shift in shifts), 2),
        "by_title": sorted(by_title.values(), key=lambda item: str(item["title"]).lower()),
    }
