from __future__ import annotations

from pathlib import Path

from supershift_mcp.calendar import list_shifts, next_shift, parse_shifts, summarize_shifts


SAMPLE_ICS = b"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//supershift-mcp//tests//EN
BEGIN:VEVENT
UID:early-1
SUMMARY:Early shift
DTSTART:20260621T060000Z
DTEND:20260621T140000Z
LOCATION:Station A
DESCRIPTION:Team alpha
END:VEVENT
BEGIN:VEVENT
UID:night-1
SUMMARY:Night shift
DTSTART:20260622T220000Z
DTEND:20260623T060000Z
END:VEVENT
END:VCALENDAR
"""


def test_parse_shifts_sorts_and_preserves_fields() -> None:
    shifts = parse_shifts(SAMPLE_ICS)

    assert [shift.title for shift in shifts] == ["Early shift", "Night shift"]
    assert shifts[0].location == "Station A"
    assert shifts[0].notes == "Team alpha"
    assert shifts[0].duration_hours == 8


def test_list_shifts_from_file(tmp_path: Path) -> None:
    calendar = tmp_path / "supershift.ics"
    calendar.write_bytes(SAMPLE_ICS)

    shifts = list_shifts("2026-06-21T00:00:00+00:00", "2026-06-22T00:00:00+00:00", str(calendar))

    assert len(shifts) == 1
    assert shifts[0].uid == "early-1"


def test_next_shift(tmp_path: Path) -> None:
    calendar = tmp_path / "supershift.ics"
    calendar.write_bytes(SAMPLE_ICS)

    shift = next_shift("2026-06-21T15:00:00+00:00", days=3, calendar=str(calendar))

    assert shift is not None
    assert shift.uid == "night-1"


def test_summary(tmp_path: Path) -> None:
    calendar = tmp_path / "supershift.ics"
    calendar.write_bytes(SAMPLE_ICS)

    summary = summarize_shifts("2026-06-21", "2026-06-24", str(calendar))

    assert summary["count"] == 2
    assert summary["duration_hours"] == 16
    assert summary["by_title"] == [
        {"title": "Early shift", "count": 1, "duration_hours": 8.0},
        {"title": "Night shift", "count": 1, "duration_hours": 8.0},
    ]
