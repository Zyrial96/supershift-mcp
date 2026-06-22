from __future__ import annotations

from supershift_mcp.writer import (
    ShiftDraft,
    build_android_calendar_intents,
    build_ui_automation_plan,
    parse_shift_text,
    validate_shift_drafts,
)


def test_parse_shift_text_supports_german_dates_locations_and_notes() -> None:
    drafts = parse_shift_text(
        """
        24.06.2026 06:00-14:00 Fruehdienst @ Station A # Team alpha
        2026-06-25 14:00-22:00 Spaetdienst
        """
    )

    assert [draft.title for draft in drafts] == ["Fruehdienst", "Spaetdienst"]
    assert drafts[0].start == "2026-06-24T06:00:00+02:00"
    assert drafts[0].end == "2026-06-24T14:00:00+02:00"
    assert drafts[0].location == "Station A"
    assert drafts[0].notes == "Team alpha"


def test_parse_shift_text_rolls_overnight_shift_to_next_day() -> None:
    drafts = parse_shift_text("26.06.2026 22:00-06:00 Nachtdienst")

    assert drafts[0].start == "2026-06-26T22:00:00+02:00"
    assert drafts[0].end == "2026-06-27T06:00:00+02:00"


def test_validate_shift_drafts_rejects_bad_ranges() -> None:
    errors = validate_shift_drafts(
        [
            {
                "title": "",
                "start": "2026-06-24T14:00:00+02:00",
                "end": "2026-06-24T06:00:00+02:00",
            }
        ]
    )

    assert errors == [
        "shift[0].title is required",
        "shift[0].end must be after start",
    ]


def test_build_ui_automation_plan_uses_profile_placeholders() -> None:
    draft = ShiftDraft(
        title="Fruehdienst",
        start="2026-06-24T06:00:00+02:00",
        end="2026-06-24T14:00:00+02:00",
        location="Station A",
        notes="Team alpha",
    )
    profile = {
        "package": "app.supershift",
        "steps": [
            {"action": "tap", "x": 120, "y": 220},
            {"action": "text", "value": "{title}"},
            {"action": "text", "value": "{date} {start_time}-{end_time}"},
        ],
    }

    plan = build_ui_automation_plan([draft], profile)

    assert plan["backend"] == "adb_ui"
    assert plan["package"] == "app.supershift"
    assert plan["commands"] == [
        ["shell", "monkey", "-p", "app.supershift", "1"],
        ["shell", "input", "tap", "120", "220"],
        ["shell", "input", "text", "Fruehdienst"],
        ["shell", "input", "text", "2026-06-24%s06%3A00-14%3A00"],
    ]


def test_build_android_calendar_intents_returns_safe_fallback_commands() -> None:
    draft = ShiftDraft(
        title="Nachtdienst",
        start="2026-06-26T22:00:00+02:00",
        end="2026-06-27T06:00:00+02:00",
    )

    commands = build_android_calendar_intents([draft])

    assert commands[0][:7] == [
        "shell",
        "am",
        "start",
        "-a",
        "android.intent.action.INSERT",
        "-t",
        "vnd.android.cursor.item/event",
    ]
    assert "Nachtdienst" in commands[0]
