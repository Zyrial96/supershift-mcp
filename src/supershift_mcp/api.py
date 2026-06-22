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
from supershift_mcp.writer import android_device_status as read_android_device_status
from supershift_mcp.writer import build_cloud_crud_preview
from supershift_mcp.writer import build_sqlite_insert_plan
from supershift_mcp.writer import create_supershift_shifts as write_supershift_shifts
from supershift_mcp.writer import create_supershift_shifts_sqlite as write_supershift_shifts_sqlite
from supershift_mcp.writer import create_supershift_shifts_sqlite_from_text as write_supershift_shifts_sqlite_from_text
from supershift_mcp.writer import create_supershift_shifts_from_text as write_supershift_shifts_from_text
from supershift_mcp.writer import dump_supershift_ui as read_supershift_ui
from supershift_mcp.writer import inspect_supershift_apk as read_supershift_apk
from supershift_mcp.writer import install_supershift_apks as write_supershift_apks
from supershift_mcp.writer import parse_shift_text as parse_shift_lines
from supershift_mcp.writer import probe_supershift_deeplinks as run_supershift_deeplink_probe
from supershift_mcp.writer import pull_supershift_data as run_supershift_data_pull
from supershift_mcp.writer import reverse_engineering_report as read_reverse_engineering_report
from supershift_mcp.writer import supershift_data_access_status as read_supershift_data_access_status
from supershift_mcp.writer import supershift_app_status as read_supershift_app_status
from supershift_mcp.writer import validate_shift_drafts

try:
    from fastapi import FastAPI, Query, Response
    from pydantic import BaseModel
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Install the API extra first: pip install 'supershift-mcp[api]'") from exc


app = FastAPI(
    title="Supershift MCP API",
    description="Read-only API for Supershift-exported calendar data.",
    version="0.1.0",
)


class ShiftWriteRequest(BaseModel):
    shifts: list[dict[str, Any]]
    backend: str = "adb_ui"
    profile_path: str | None = None
    dry_run: bool = True


class ShiftTextWriteRequest(BaseModel):
    text: str
    backend: str = "adb_ui"
    profile_path: str | None = None
    dry_run: bool = True
    default_timezone: str = "+02:00"


class ApkInstallRequest(BaseModel):
    apk_paths: list[str]
    dry_run: bool = True


class DeeplinkProbeRequest(BaseModel):
    urls: list[str]
    dry_run: bool = True


class DataPullRequest(BaseModel):
    output_dir: str
    dry_run: bool = True


class CloudCrudPreviewRequest(BaseModel):
    shifts: list[dict[str, Any]]
    calendar_id: str
    event_type: int = 0


class SqliteWriteRequest(BaseModel):
    shifts: list[dict[str, Any]]
    calendar_row_id: int = 1
    db_path: str = "/data/data/app.supershift/databases/Supershift.db"
    dry_run: bool = True


class SqliteTextWriteRequest(BaseModel):
    text: str
    calendar_row_id: int = 1
    db_path: str = "/data/data/app.supershift/databases/Supershift.db"
    dry_run: bool = True
    default_timezone: str = "+02:00"


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


@app.post("/write/parse")
def parse_write_text(payload: ShiftTextWriteRequest) -> list[dict[str, Any]]:
    return [draft.as_dict() for draft in parse_shift_lines(payload.text, payload.default_timezone)]


@app.post("/write/validate")
def validate_write_shifts(payload: ShiftWriteRequest) -> list[str]:
    return validate_shift_drafts(payload.shifts)


@app.get("/android/status")
def android_status() -> dict[str, Any]:
    return read_android_device_status()


@app.get("/android/supershift")
def android_supershift_status() -> dict[str, Any]:
    return read_supershift_app_status()


@app.get("/android/supershift/ui")
def android_supershift_ui() -> dict[str, Any]:
    return read_supershift_ui()


@app.get("/reverse/apk")
def inspect_apk(
    apk_path: str,
    aapt_path: str = "aapt",
    manifest_path: str | None = None,
) -> dict[str, Any]:
    return read_supershift_apk(apk_path, aapt_path, manifest_path)


@app.get("/reverse/report")
def reverse_report(
    apktool_dir: str | None = None,
    jadx_dir: str | None = None,
) -> dict[str, Any]:
    return read_reverse_engineering_report(apktool_dir, jadx_dir)


@app.post("/android/supershift/install")
def install_apks(payload: ApkInstallRequest) -> dict[str, Any]:
    return write_supershift_apks(payload.apk_paths, payload.dry_run)


@app.post("/android/supershift/deeplinks")
def probe_deeplinks(payload: DeeplinkProbeRequest) -> dict[str, Any]:
    return run_supershift_deeplink_probe(payload.urls, payload.dry_run)


@app.get("/android/supershift/data")
def data_access_status() -> dict[str, Any]:
    return read_supershift_data_access_status()


@app.post("/android/supershift/data/pull")
def pull_data(payload: DataPullRequest) -> dict[str, Any]:
    return run_supershift_data_pull(payload.output_dir, payload.dry_run)


@app.post("/write/supershift/cloud/preview")
def preview_cloud_crud(payload: CloudCrudPreviewRequest) -> dict[str, Any]:
    return build_cloud_crud_preview(payload.shifts, payload.calendar_id, payload.event_type)


@app.post("/write/supershift/sqlite/preview")
def preview_sqlite_write(payload: SqliteWriteRequest) -> dict[str, Any]:
    return build_sqlite_insert_plan(
        payload.shifts,
        payload.calendar_row_id,
        payload.db_path,
        dry_run=True,
    )


@app.post("/write/supershift/sqlite")
def write_sqlite(payload: SqliteWriteRequest) -> dict[str, Any]:
    return write_supershift_shifts_sqlite(
        payload.shifts,
        payload.calendar_row_id,
        payload.db_path,
        payload.dry_run,
    )


@app.post("/write/supershift/sqlite/text")
def write_sqlite_text(payload: SqliteTextWriteRequest) -> dict[str, Any]:
    return write_supershift_shifts_sqlite_from_text(
        payload.text,
        payload.calendar_row_id,
        payload.db_path,
        payload.dry_run,
        default_timezone=payload.default_timezone,
    )


@app.post("/write/supershift")
def write_shifts(payload: ShiftWriteRequest) -> dict[str, Any]:
    return write_supershift_shifts(
        payload.shifts,
        payload.backend,
        payload.profile_path,
        payload.dry_run,
    )


@app.post("/write/supershift/text")
def write_shifts_from_text(payload: ShiftTextWriteRequest) -> dict[str, Any]:
    return write_supershift_shifts_from_text(
        payload.text,
        payload.backend,
        payload.profile_path,
        payload.dry_run,
        default_timezone=payload.default_timezone,
    )


def main() -> None:
    import uvicorn

    uvicorn.run("supershift_mcp.api:app", host="127.0.0.1", port=8765)
