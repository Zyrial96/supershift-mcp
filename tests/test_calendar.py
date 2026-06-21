from __future__ import annotations

from pathlib import Path

from supershift_mcp.calendar import (
    current_shift,
    detect_conflicts,
    estimate_pay,
    export_shifts,
    filter_shifts,
    find_free_days,
    find_shift,
    list_shifts,
    next_shift,
    parse_shifts,
    rest_periods,
    shifts_on_date,
    summarize_by_period,
    summarize_shifts,
)


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
BEGIN:VEVENT
UID:early-2
SUMMARY:Early shift
DTSTART:20260624T060000Z
DTEND:20260624T120000Z
LOCATION:Station B
DESCRIPTION:Training
END:VEVENT
BEGIN:VEVENT
UID:overlap-1
SUMMARY:On call
DTSTART:20260624T110000Z
DTEND:20260624T150000Z
LOCATION:Station B
END:VEVENT
BEGIN:VEVENT
UID:vacation-1
SUMMARY:Vacation
DTSTART;VALUE=DATE:20260626
DTEND;VALUE=DATE:20260627
END:VEVENT
END:VCALENDAR
"""


def test_parse_shifts_sorts_and_preserves_fields() -> None:
    shifts = parse_shifts(SAMPLE_ICS)

    assert [shift.title for shift in shifts] == [
        "Early shift",
        "Night shift",
        "Early shift",
        "On call",
        "Vacation",
    ]
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

    summary = summarize_shifts("2026-06-21", "2026-06-27", str(calendar))

    assert summary["count"] == 5
    assert summary["duration_hours"] == 50
    assert summary["by_title"] == [
        {"title": "Early shift", "count": 2, "duration_hours": 14.0},
        {"title": "Night shift", "count": 1, "duration_hours": 8.0},
        {"title": "On call", "count": 1, "duration_hours": 4.0},
        {"title": "Vacation", "count": 1, "duration_hours": 24.0},
    ]


def test_filter_and_find_shift(tmp_path: Path) -> None:
    calendar = tmp_path / "supershift.ics"
    calendar.write_bytes(SAMPLE_ICS)

    filtered = filter_shifts(
        "2026-06-21",
        "2026-06-27",
        calendar=str(calendar),
        title_contains="early",
        location_contains="station b",
    )

    assert [shift.uid for shift in filtered] == ["early-2"]
    assert find_shift("early-2", str(calendar))["title"] == "Early shift"


def test_current_and_day_lookup(tmp_path: Path) -> None:
    calendar = tmp_path / "supershift.ics"
    calendar.write_bytes(SAMPLE_ICS)

    active = current_shift("2026-06-24T11:30:00+00:00", str(calendar))
    day = shifts_on_date("2026-06-24", str(calendar))

    assert active is not None
    assert active["uid"] == "early-2"
    assert [shift["uid"] for shift in day] == ["early-2", "overlap-1"]


def test_conflicts_and_rest_periods(tmp_path: Path) -> None:
    calendar = tmp_path / "supershift.ics"
    calendar.write_bytes(SAMPLE_ICS)

    conflicts = detect_conflicts("2026-06-24", "2026-06-25", str(calendar))
    rests = rest_periods("2026-06-21", "2026-06-25", str(calendar))

    assert conflicts == [
        {
            "first_uid": "early-2",
            "second_uid": "overlap-1",
            "overlap_hours": 1.0,
        }
    ]
    assert rests[-1]["rest_hours"] == 0.0
    assert rests[-1]["warning"] == "below_minimum"


def test_free_days_period_summary_export_and_pay(tmp_path: Path) -> None:
    calendar = tmp_path / "supershift.ics"
    calendar.write_bytes(SAMPLE_ICS)

    free_days = find_free_days("2026-06-21", "2026-06-27", str(calendar))
    month = summarize_by_period("2026-06-21", "2026-06-27", "month", str(calendar))
    csv_export = export_shifts("2026-06-21", "2026-06-25", "csv", str(calendar))
    pay = estimate_pay("2026-06-21", "2026-06-25", 20, str(calendar), {"Night shift": 30})

    assert free_days == ["2026-06-25"]
    assert month["period"] == "month"
    assert month["buckets"] == [{"period": "2026-06", "count": 4, "duration_hours": 26.0}]
    assert "uid,title,start,end,duration_hours,location,notes" in csv_export
    assert pay == {
        "currency": "EUR",
        "duration_hours": 26.0,
        "estimated_pay": 600.0,
        "by_title": [
            {"title": "Early shift", "hours": 14.0, "rate": 20.0, "estimated_pay": 280.0},
            {"title": "Night shift", "hours": 8.0, "rate": 30.0, "estimated_pay": 240.0},
            {"title": "On call", "hours": 4.0, "rate": 20.0, "estimated_pay": 80.0},
        ],
    }
