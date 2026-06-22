from __future__ import annotations

from supershift_mcp.writer import (
    ShiftDraft,
    build_android_calendar_intents,
    build_cloud_crud_preview,
    build_sqlite_insert_plan,
    build_ui_automation_plan,
    parse_apk_badging,
    parse_manifest_insights,
    parse_shift_text,
    plan_supershift_deeplink_probe,
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


def test_parse_apk_badging_extracts_package_version_and_permissions() -> None:
    badging = """
    package: name='app.supershift' versionCode='26185' versionName='2026.18'
    sdkVersion:'28'
    targetSdkVersion:'36'
    uses-permission: name='android.permission.WRITE_CALENDAR'
    uses-permission: name='android.permission.INTERNET'
    application-label:'Supershift'
    """

    parsed = parse_apk_badging(badging)

    assert parsed["package"] == "app.supershift"
    assert parsed["version_code"] == "26185"
    assert parsed["version_name"] == "2026.18"
    assert parsed["target_sdk"] == "36"
    assert "android.permission.WRITE_CALENDAR" in parsed["permissions"]


def test_parse_manifest_insights_extracts_exported_and_deeplinks() -> None:
    manifest = """
    <manifest xmlns:android="http://schemas.android.com/apk/res/android" android:requiredSplitTypes="base__abi,base__density" package="app.supershift">
      <application android:allowBackup="true" android:debuggable="false">
        <activity android:exported="true" android:name="app.supershift.main.DeeplinkActivity">
          <intent-filter>
            <action android:name="android.intent.action.VIEW"/>
            <data android:host="supershift.app" android:pathPrefix="/open/" android:scheme="https"/>
          </intent-filter>
        </activity>
        <activity android:exported="false" android:name="app.supershift.event.ui.EditorActivity"/>
      </application>
    </manifest>
    """

    parsed = parse_manifest_insights(manifest)

    assert parsed["required_split_types"] == ["base__abi", "base__density"]
    assert parsed["allow_backup"] is True
    assert parsed["debuggable"] is False
    assert parsed["exported_activities"] == ["app.supershift.main.DeeplinkActivity"]
    assert parsed["deeplinks"] == [
        {"scheme": "https", "host": "supershift.app", "path_prefix": "/open/"}
    ]


def test_plan_supershift_deeplink_probe_builds_adb_commands() -> None:
    plan = plan_supershift_deeplink_probe(["https://supershift.app/open/test"])

    assert plan["dry_run"] is True
    assert plan["commands"] == [
        [
            "shell",
            "am",
            "start",
            "-a",
            "android.intent.action.VIEW",
            "-d",
            "https://supershift.app/open/test",
            "app.supershift",
        ]
    ]


def test_build_cloud_crud_preview_creates_experimental_event_payload() -> None:
    draft = ShiftDraft(
        title="Fruehdienst",
        start="2026-06-24T06:00:00+02:00",
        end="2026-06-24T14:00:00+02:00",
        location="Station A",
        notes="Team alpha",
    )

    preview = build_cloud_crud_preview([draft], calendar_id="primary")

    event = preview["payload"]["events"]["create"][0]
    assert preview["endpoint"] == "POST https://supershift.app/api/v3/crud"
    assert event["date"] == 20260624
    assert event["endDate"] is None
    assert event["start"] == 21600.0
    assert event["end"] == 50400.0
    assert event["title"] == "Fruehdienst"
    assert event["note"] == "Team alpha"
    assert event["location"] == {"title": "Station A"}


def test_build_sqlite_insert_plan_creates_root_safe_transaction() -> None:
    draft = ShiftDraft(
        title="Nachtdienst",
        start="2026-06-26T22:00:00+02:00",
        end="2026-06-27T06:00:00+02:00",
        location="Station B",
        notes="Nacht",
    )

    plan = build_sqlite_insert_plan([draft], calendar_row_id=1)

    assert plan["backend"] == "sqlite_root"
    assert plan["dry_run"] is True
    sql = plan["sql"]
    assert "BEGIN TRANSACTION;" in sql
    assert "INSERT INTO event" in sql
    assert "INSERT INTO calendar_sync_task" in sql
    assert "20260626" in sql
    assert "20260627" in sql
    assert "79200.0" in sql
    assert "21600.0" in sql
    assert "'Nachtdienst'" in sql
    assert "'Station B'" in sql
