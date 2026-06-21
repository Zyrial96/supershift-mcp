from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
import csv
import io
import json
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


def filter_shifts(
    start: str | datetime | date,
    end: str | datetime | date,
    calendar: str | None = None,
    title_contains: str | None = None,
    location_contains: str | None = None,
    notes_contains: str | None = None,
    min_hours: float | None = None,
    max_hours: float | None = None,
) -> list[Shift]:
    shifts = list_shifts(start, end, calendar)
    return [
        shift
        for shift in shifts
        if _contains(shift.title, title_contains)
        and _contains(shift.location, location_contains)
        and _contains(shift.notes, notes_contains)
        and (min_hours is None or shift.duration_hours >= min_hours)
        and (max_hours is None or shift.duration_hours <= max_hours)
    ]


def find_shift(uid: str, calendar: str | None = None) -> dict[str, Any] | None:
    for shift in parse_shifts(fetch_ics(calendar)):
        if shift.uid == uid:
            return shift.as_dict()
    return None


def current_shift(at: str | datetime | date | None = None, calendar: str | None = None) -> dict[str, Any] | None:
    at_dt = parse_boundary(at, default=datetime.now(timezone.utc).astimezone())
    for shift in parse_shifts(fetch_ics(calendar)):
        if shift.start <= at_dt < shift.end:
            return shift.as_dict()
    return None


def shifts_on_date(day: str | datetime | date, calendar: str | None = None) -> list[dict[str, Any]]:
    start = parse_boundary(day)
    end = start + timedelta(days=1)
    return [shift.as_dict() for shift in list_shifts(start, end, calendar)]


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


def detect_conflicts(
    start: str | datetime | date,
    end: str | datetime | date,
    calendar: str | None = None,
) -> list[dict[str, Any]]:
    shifts = list_shifts(start, end, calendar)
    conflicts: list[dict[str, Any]] = []
    for index, first in enumerate(shifts):
        for second in shifts[index + 1 :]:
            overlap_start = max(first.start, second.start)
            overlap_end = min(first.end, second.end)
            if overlap_start < overlap_end:
                conflicts.append(
                    {
                        "first_uid": first.uid,
                        "second_uid": second.uid,
                        "overlap_hours": round((overlap_end - overlap_start).total_seconds() / 3600, 2),
                    }
                )
    return conflicts


def rest_periods(
    start: str | datetime | date,
    end: str | datetime | date,
    calendar: str | None = None,
    minimum_hours: float = 11,
) -> list[dict[str, Any]]:
    shifts = list_shifts(start, end, calendar)
    periods: list[dict[str, Any]] = []
    for previous, following in zip(shifts, shifts[1:]):
        rest_hours = max((following.start - previous.end).total_seconds() / 3600, 0)
        periods.append(
            {
                "previous_uid": previous.uid,
                "next_uid": following.uid,
                "rest_hours": round(rest_hours, 2),
                "warning": "below_minimum" if rest_hours < minimum_hours else None,
            }
        )
    return periods


def find_free_days(
    start: str | datetime | date,
    end: str | datetime | date,
    calendar: str | None = None,
) -> list[str]:
    start_day = parse_boundary(start).date()
    end_day = parse_boundary(end).date()
    shifts = list_shifts(start, end, calendar)
    occupied = {
        day
        for shift in shifts
        for day in _dates_between(shift.start.date(), (shift.end - timedelta(microseconds=1)).date())
    }

    free: list[str] = []
    current = start_day
    while current < end_day:
        if current not in occupied:
            free.append(current.isoformat())
        current += timedelta(days=1)
    return free


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


def summarize_by_period(
    start: str | datetime | date,
    end: str | datetime | date,
    period: str = "day",
    calendar: str | None = None,
    include_all_day: bool = False,
) -> dict[str, Any]:
    shifts = [
        shift
        for shift in list_shifts(start, end, calendar)
        if include_all_day or not shift.all_day
    ]
    buckets: dict[str, dict[str, float | int | str]] = {}
    for shift in shifts:
        key = _period_key(shift.start, period)
        bucket = buckets.setdefault(key, {"period": key, "count": 0, "duration_hours": 0.0})
        bucket["count"] = int(bucket["count"]) + 1
        bucket["duration_hours"] = round(float(bucket["duration_hours"]) + shift.duration_hours, 2)

    return {
        "period": period,
        "start": parse_boundary(start).isoformat(),
        "end": parse_boundary(end).isoformat(),
        "buckets": [buckets[key] for key in sorted(buckets)],
    }


def export_shifts(
    start: str | datetime | date,
    end: str | datetime | date,
    output_format: str = "json",
    calendar: str | None = None,
) -> str:
    rows = [shift.as_dict() for shift in list_shifts(start, end, calendar)]
    normalized = output_format.lower()
    if normalized == "json":
        return json.dumps(rows, indent=2, ensure_ascii=False)
    if normalized == "markdown":
        return _markdown_table(rows)
    if normalized == "csv":
        return _csv(rows)
    raise ValueError("output_format must be one of: json, csv, markdown.")


def estimate_pay(
    start: str | datetime | date,
    end: str | datetime | date,
    hourly_rate: float,
    calendar: str | None = None,
    title_rates: dict[str, float] | None = None,
    currency: str = "EUR",
    include_all_day: bool = False,
) -> dict[str, Any]:
    if hourly_rate < 0:
        raise ValueError("hourly_rate must not be negative.")
    title_rates = title_rates or {}
    shifts = [
        shift
        for shift in list_shifts(start, end, calendar)
        if include_all_day or not shift.all_day
    ]
    by_title: dict[str, dict[str, float | str]] = {}
    for shift in shifts:
        rate = float(title_rates.get(shift.title, hourly_rate))
        bucket = by_title.setdefault(
            shift.title,
            {"title": shift.title, "hours": 0.0, "rate": rate, "estimated_pay": 0.0},
        )
        bucket["hours"] = round(float(bucket["hours"]) + shift.duration_hours, 2)
        bucket["estimated_pay"] = round(float(bucket["estimated_pay"]) + shift.duration_hours * rate, 2)

    items = sorted(by_title.values(), key=lambda item: str(item["title"]).lower())
    return {
        "currency": currency,
        "duration_hours": round(sum(float(item["hours"]) for item in items), 2),
        "estimated_pay": round(sum(float(item["estimated_pay"]) for item in items), 2),
        "by_title": items,
    }


def unique_titles(calendar: str | None = None) -> list[str]:
    return sorted({shift.title for shift in parse_shifts(fetch_ics(calendar))})


def unique_locations(calendar: str | None = None) -> list[str]:
    return sorted({shift.location for shift in parse_shifts(fetch_ics(calendar)) if shift.location})


def calendar_bounds(calendar: str | None = None) -> dict[str, Any]:
    shifts = parse_shifts(fetch_ics(calendar))
    if not shifts:
        return {"event_count": 0, "first_shift": None, "last_shift": None}
    return {
        "event_count": len(shifts),
        "first_shift": shifts[0].as_dict(),
        "last_shift": shifts[-1].as_dict(),
        "titles": unique_titles(calendar),
        "locations": unique_locations(calendar),
    }


def _contains(value: str | None, needle: str | None) -> bool:
    if needle is None:
        return True
    return needle.casefold() in (value or "").casefold()


def _dates_between(start: date, end: date) -> list[date]:
    days: list[date] = []
    current = start
    while current <= end:
        days.append(current)
        current += timedelta(days=1)
    return days


def _period_key(value: datetime, period: str) -> str:
    normalized = period.lower()
    if normalized == "day":
        return value.date().isoformat()
    if normalized == "week":
        year, week, _ = value.isocalendar()
        return f"{year}-W{week:02d}"
    if normalized == "month":
        return value.strftime("%Y-%m")
    if normalized == "weekday":
        return value.strftime("%A")
    raise ValueError("period must be one of: day, week, month, weekday.")


def _csv(rows: list[dict[str, Any]]) -> str:
    output = io.StringIO()
    fieldnames = ["uid", "title", "start", "end", "duration_hours", "location", "notes"]
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def _markdown_table(rows: list[dict[str, Any]]) -> str:
    headers = ["uid", "title", "start", "end", "duration_hours"]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(header) or "") for header in headers) + " |")
    return "\n".join(lines)
