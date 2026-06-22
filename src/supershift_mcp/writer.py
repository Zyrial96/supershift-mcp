from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import uuid
from typing import Any, Callable
from urllib.parse import quote
import xml.etree.ElementTree as ET

from dateutil.parser import isoparse


SUPERSHIFT_PACKAGE = "app.supershift"
WRITE_ENV = "SUPERSHIFT_WRITE_ENABLED"
REVERSE_ENV = "SUPERSHIFT_REVERSE_ENABLED"
DEFAULT_TIMEZONE = "+02:00"
SUPERSHIFT_PROD_URL = "https://supershift.app"
ANDROID_NS = "{http://schemas.android.com/apk/res/android}"
SUPERSHIFT_DB_PATH = f"/data/data/{SUPERSHIFT_PACKAGE}/databases/Supershift.db"


@dataclass(frozen=True)
class ShiftDraft:
    title: str
    start: str
    end: str
    location: str | None = None
    notes: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "start": self.start,
            "end": self.end,
            "location": self.location,
            "notes": self.notes,
        }

    @property
    def context(self) -> dict[str, str]:
        start = isoparse(self.start)
        end = isoparse(self.end)
        return {
            "title": self.title,
            "start": self.start,
            "end": self.end,
            "date": start.date().isoformat(),
            "start_time": start.strftime("%H:%M"),
            "end_time": end.strftime("%H:%M"),
            "location": self.location or "",
            "notes": self.notes or "",
        }


SHIFT_LINE_RE = re.compile(
    r"^\s*(?P<date>\d{4}-\d{2}-\d{2}|\d{1,2}\.\d{1,2}\.\d{4})\s+"
    r"(?P<start>\d{1,2}:\d{2})\s*[-–]\s*(?P<end>\d{1,2}:\d{2})\s+"
    r"(?P<body>.+?)\s*$"
)


def parse_shift_text(text: str, default_timezone: str = DEFAULT_TIMEZONE) -> list[ShiftDraft]:
    drafts: list[ShiftDraft] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        match = SHIFT_LINE_RE.match(line)
        if not match:
            raise ValueError(
                f"Line {line_number} is not a supported shift format. "
                "Use: 24.06.2026 06:00-14:00 Fruehdienst @ Ort # Notiz"
            )
        body = match.group("body")
        title, location, notes = _split_body(body)
        start, end = _parse_start_end(
            match.group("date"),
            match.group("start"),
            match.group("end"),
            default_timezone,
        )
        drafts.append(
            ShiftDraft(
                title=title,
                start=start.isoformat(),
                end=end.isoformat(),
                location=location,
                notes=notes,
            )
        )
    return drafts


def normalize_shift_drafts(shifts: list[dict[str, Any] | ShiftDraft]) -> list[ShiftDraft]:
    drafts: list[ShiftDraft] = []
    for shift in shifts:
        if isinstance(shift, ShiftDraft):
            drafts.append(shift)
            continue
        drafts.append(
            ShiftDraft(
                title=str(shift.get("title") or ""),
                start=str(shift.get("start") or ""),
                end=str(shift.get("end") or ""),
                location=shift.get("location"),
                notes=shift.get("notes"),
            )
        )
    return drafts


def validate_shift_drafts(shifts: list[dict[str, Any] | ShiftDraft]) -> list[str]:
    errors: list[str] = []
    for index, draft in enumerate(normalize_shift_drafts(shifts)):
        if not draft.title.strip():
            errors.append(f"shift[{index}].title is required")
        try:
            start = isoparse(draft.start)
            end = isoparse(draft.end)
        except ValueError:
            errors.append(f"shift[{index}].start and end must be ISO datetimes")
            continue
        if end <= start:
            errors.append(f"shift[{index}].end must be after start")
    return errors


def load_ui_profile(profile_path: str | None = None) -> dict[str, Any]:
    if profile_path is None:
        profile_path = os.getenv("SUPERSHIFT_UI_PROFILE")
    if not profile_path:
        raise ValueError(
            "No UI profile configured. Provide profile_path or set SUPERSHIFT_UI_PROFILE."
        )
    return json.loads(Path(profile_path).expanduser().read_text())


def build_ui_automation_plan(
    shifts: list[dict[str, Any] | ShiftDraft],
    profile: dict[str, Any],
) -> dict[str, Any]:
    drafts = normalize_shift_drafts(shifts)
    errors = validate_shift_drafts(drafts)
    if errors:
        return {"ok": False, "errors": errors, "backend": "adb_ui", "commands": []}

    package = str(profile.get("package") or SUPERSHIFT_PACKAGE)
    commands: list[list[str]] = [["shell", "monkey", "-p", package, "1"]]
    for draft in drafts:
        for step in profile.get("steps", []):
            commands.extend(_step_to_commands(step, draft.context))
    return {
        "ok": True,
        "backend": "adb_ui",
        "package": package,
        "count": len(drafts),
        "commands": commands,
    }


def build_android_calendar_intents(
    shifts: list[dict[str, Any] | ShiftDraft],
) -> list[list[str]]:
    commands: list[list[str]] = []
    for draft in normalize_shift_drafts(shifts):
        start_ms = _epoch_ms(draft.start)
        end_ms = _epoch_ms(draft.end)
        command = [
            "shell",
            "am",
            "start",
            "-a",
            "android.intent.action.INSERT",
            "-t",
            "vnd.android.cursor.item/event",
            "--el",
            "beginTime",
            str(start_ms),
            "--el",
            "endTime",
            str(end_ms),
            "--es",
            "title",
            draft.title,
        ]
        if draft.location:
            command.extend(["--es", "eventLocation", draft.location])
        if draft.notes:
            command.extend(["--es", "description", draft.notes])
        commands.append(command)
    return commands


def parse_apk_badging(output: str) -> dict[str, Any]:
    package_match = re.search(
        r"package: name='(?P<package>[^']+)'\s+versionCode='(?P<version_code>[^']+)'\s+versionName='(?P<version_name>[^']+)'",
        output,
    )
    result: dict[str, Any] = {
        "package": None,
        "version_code": None,
        "version_name": None,
        "sdk": None,
        "target_sdk": None,
        "application_label": None,
        "permissions": [],
    }
    if package_match:
        result.update(package_match.groupdict())
    sdk_match = re.search(r"sdkVersion:'([^']+)'", output)
    target_match = re.search(r"targetSdkVersion:'([^']+)'", output)
    label_match = re.search(r"application-label:'([^']+)'", output)
    if sdk_match:
        result["sdk"] = sdk_match.group(1)
    if target_match:
        result["target_sdk"] = target_match.group(1)
    if label_match:
        result["application_label"] = label_match.group(1)
    result["permissions"] = re.findall(r"uses-permission: name='([^']+)'", output)
    return result


def parse_manifest_insights(manifest_xml: str) -> dict[str, Any]:
    root = ET.fromstring(manifest_xml)
    required = root.attrib.get(f"{ANDROID_NS}requiredSplitTypes", "")
    app = root.find("application")
    allow_backup = _xml_bool(app.attrib.get(f"{ANDROID_NS}allowBackup")) if app is not None else None
    debuggable = _xml_bool(app.attrib.get(f"{ANDROID_NS}debuggable")) if app is not None else None
    activities: list[dict[str, Any]] = []
    exported_activities: list[str] = []
    deeplinks: list[dict[str, str | None]] = []
    if app is not None:
        for activity in app.findall("activity"):
            name = activity.attrib.get(f"{ANDROID_NS}name")
            exported = _xml_bool(activity.attrib.get(f"{ANDROID_NS}exported"))
            if name and exported:
                exported_activities.append(name)
            activities.append({"name": name, "exported": exported})
            for data in activity.findall("./intent-filter/data"):
                link = {
                    "scheme": data.attrib.get(f"{ANDROID_NS}scheme"),
                    "host": data.attrib.get(f"{ANDROID_NS}host"),
                    "path_prefix": data.attrib.get(f"{ANDROID_NS}pathPrefix"),
                }
                if any(link.values()):
                    deeplinks.append(link)
    return {
        "package": root.attrib.get("package"),
        "required_split_types": [part for part in required.split(",") if part],
        "allow_backup": allow_backup,
        "debuggable": debuggable,
        "activities": activities,
        "exported_activities": exported_activities,
        "deeplinks": deeplinks,
    }


def inspect_supershift_apk(
    apk_path: str,
    aapt_path: str = "aapt",
    manifest_path: str | None = None,
) -> dict[str, Any]:
    apk = Path(apk_path).expanduser()
    if not apk.exists():
        return {"ok": False, "error": f"APK not found: {apk}"}
    badging_result = _run([aapt_path, "dump", "badging", str(apk)], check=False)
    result: dict[str, Any] = {
        "ok": badging_result.returncode == 0,
        "apk_path": str(apk),
        "badging": parse_apk_badging(badging_result.stdout),
        "stderr": badging_result.stderr,
    }
    manifest = None
    if manifest_path:
        manifest_file = Path(manifest_path).expanduser()
        if manifest_file.exists():
            manifest = manifest_file.read_text()
    if manifest:
        result["manifest"] = parse_manifest_insights(manifest)
    result["findings"] = _reverse_static_findings(result)
    return result


def reverse_engineering_report(
    apktool_dir: str | None = None,
    jadx_dir: str | None = None,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "ok": True,
        "source": "static_apk_reverse_engineering",
        "supported_write_paths": [
            "adb_ui",
            "android_calendar_intent",
            "cloud_crud_preview",
            "root_or_backup_data_export",
        ],
        "safe_default": "adb_ui dry-run; real ADB input requires SUPERSHIFT_WRITE_ENABLED=1",
        "cloud_api": {
            "base_url": f"{SUPERSHIFT_PROD_URL}/api/",
            "auth_required": True,
            "endpoints": [
                "POST login",
                "POST createAccount",
                "POST v3/crud",
                "POST v2/sync",
                "POST checkCloudData",
                "POST deleteCloudData",
            ],
            "write_status": "preview-only until tokens, user id, device id, and live schema are captured from the user's own signed-in app.",
        },
        "local_storage": {
            "engine": "Room/SQLite on Android 2026.18; older classes still expose Realm migration/model names",
            "database": SUPERSHIFT_DB_PATH,
            "key_models": [
                "event",
                "template",
                "calendar",
                "break",
                "notification",
                "calendar_sync_task",
            ],
            "legacy_or_migration_models": [
                "EventRealm",
                "LocationRealm",
                "SyncInfoRealm",
            ],
        },
        "event_schema": {
            "date": "YYYYMMDD integer",
            "start": "seconds since local midnight",
            "end": "seconds since local midnight",
            "endDate": "YYYYMMDD integer for overnight shifts, otherwise null",
            "title": "string",
            "note": "string or null",
            "location": "object or null",
            "calendarId": "required for cloud CRUD",
        },
        "limitations": [
            "No exported Supershift activity found for direct shift insertion.",
            "Direct SQLite writes require adb root or equivalent /data/data access and a fresh backup.",
            "Cloud writes are not executed without authenticated context from the user's own installation.",
        ],
    }
    if apktool_dir:
        manifest = Path(apktool_dir).expanduser() / "AndroidManifest.xml"
        if manifest.exists():
            report["manifest"] = parse_manifest_insights(manifest.read_text())
    if jadx_dir:
        report["jadx_dir"] = str(Path(jadx_dir).expanduser())
    return report


def plan_supershift_deeplink_probe(urls: list[str], dry_run: bool = True) -> dict[str, Any]:
    commands = [
        [
            "shell",
            "am",
            "start",
            "-a",
            "android.intent.action.VIEW",
            "-d",
            url,
            SUPERSHIFT_PACKAGE,
        ]
        for url in urls
    ]
    return {"ok": True, "backend": "adb_deeplink", "dry_run": dry_run, "commands": commands}


def probe_supershift_deeplinks(
    urls: list[str],
    dry_run: bool = True,
    adb_path: str = "adb",
) -> dict[str, Any]:
    plan = plan_supershift_deeplink_probe(urls, dry_run)
    if dry_run:
        return {**plan, "executed": False}
    if os.getenv(REVERSE_ENV) != "1":
        return {
            **plan,
            "ok": False,
            "executed": False,
            "error": f"Refusing to launch deeplinks. Set {REVERSE_ENV}=1.",
        }
    return _execute_adb_plan(plan, adb_path)


def install_supershift_apks(
    apk_paths: list[str],
    dry_run: bool = True,
    adb_path: str = "adb",
) -> dict[str, Any]:
    apks = [str(Path(path).expanduser()) for path in apk_paths]
    commands = [["install-multiple", "-r", *apks]]
    plan = {"ok": True, "backend": "adb_install_multiple", "dry_run": dry_run, "commands": commands}
    if dry_run:
        return {**plan, "executed": False}
    if os.getenv(REVERSE_ENV) != "1":
        return {
            **plan,
            "ok": False,
            "executed": False,
            "error": f"Refusing to install APKs. Set {REVERSE_ENV}=1.",
        }
    return _execute_adb_plan(plan, adb_path)


def supershift_data_access_status(adb_path: str = "adb") -> dict[str, Any]:
    status = supershift_app_status(adb_path)
    if not status.get("installed"):
        return {**status, "ok": False, "data_access": "app_not_installed"}
    run_as = _run([adb_path, "shell", "run-as", SUPERSHIFT_PACKAGE, "ls", "files"], check=False)
    root_probe = _run([adb_path, "shell", f"ls /data/data/{SUPERSHIFT_PACKAGE}"], check=False)
    sqlite_probe = _run([adb_path, "shell", f"ls {SUPERSHIFT_DB_PATH}"], check=False)
    data_candidates = [
        SUPERSHIFT_DB_PATH,
        f"{SUPERSHIFT_DB_PATH}-wal",
        f"{SUPERSHIFT_DB_PATH}-shm",
    ]
    return {
        **status,
        "ok": True,
        "run_as_available": run_as.returncode == 0,
        "root_data_available": root_probe.returncode == 0,
        "sqlite_db_available": sqlite_probe.returncode == 0,
        "data_candidates": data_candidates,
        "realm_candidates": data_candidates,
        "run_as_stdout": run_as.stdout,
        "run_as_stderr": run_as.stderr,
        "root_stdout": root_probe.stdout,
        "root_stderr": root_probe.stderr,
        "sqlite_stdout": sqlite_probe.stdout,
        "sqlite_stderr": sqlite_probe.stderr,
    }


def pull_supershift_data(
    output_dir: str,
    dry_run: bool = True,
    adb_path: str = "adb",
) -> dict[str, Any]:
    destination = Path(output_dir).expanduser()
    remote_tar = "/sdcard/supershift-data.tar"
    commands = [
        [
            "shell",
            "run-as",
            SUPERSHIFT_PACKAGE,
            "tar",
            "-cf",
            remote_tar,
            "files",
            "shared_prefs",
            "databases",
        ],
        ["pull", remote_tar, str(destination / "supershift-data.tar")],
        ["shell", "rm", "-f", remote_tar],
    ]
    plan = {"ok": True, "backend": "adb_run_as_backup", "dry_run": dry_run, "commands": commands}
    if dry_run:
        return {**plan, "executed": False}
    if os.getenv(REVERSE_ENV) != "1":
        return {
            **plan,
            "ok": False,
            "executed": False,
            "error": f"Refusing to pull app data. Set {REVERSE_ENV}=1.",
        }
    destination.mkdir(parents=True, exist_ok=True)
    return _execute_adb_plan(plan, adb_path)


def build_cloud_crud_preview(
    shifts: list[dict[str, Any] | ShiftDraft],
    calendar_id: str,
    event_type: int = 0,
) -> dict[str, Any]:
    drafts = normalize_shift_drafts(shifts)
    errors = validate_shift_drafts(drafts)
    if errors:
        return {"ok": False, "errors": errors, "backend": "cloud_crud_preview"}
    events = [_draft_to_cloud_event(draft, calendar_id, event_type) for draft in drafts]
    return {
        "ok": True,
        "backend": "cloud_crud_preview",
        "endpoint": f"POST {SUPERSHIFT_PROD_URL}/api/v3/crud",
        "auth_required": True,
        "headers_required": [
            "Authorization",
            "X-User-Id",
            "X-Device-Id",
            "Supershift custom headers from app session",
        ],
        "payload": {"events": {"create": events}},
        "warning": (
            "Preview only. The APK exposes this REST shape, but the MCP does not send it "
            "without authenticated context captured from your own signed-in Supershift app."
        ),
    }


def build_sqlite_insert_plan(
    shifts: list[dict[str, Any] | ShiftDraft],
    calendar_row_id: int = 1,
    db_path: str = SUPERSHIFT_DB_PATH,
    dry_run: bool = True,
) -> dict[str, Any]:
    drafts = normalize_shift_drafts(shifts)
    errors = validate_shift_drafts(drafts)
    if errors:
        return {"ok": False, "errors": errors, "backend": "sqlite_root"}
    statements = ["BEGIN TRANSACTION;"]
    for draft in drafts:
        statements.extend(_draft_to_sqlite_inserts(draft, calendar_row_id))
    statements.append("COMMIT;")
    sql = "\n".join(statements)
    shell_sql = " ".join(statements)
    sqlite_command = f"sqlite3 {shlex.quote(db_path)} {shlex.quote(shell_sql)}"
    commands = [
        ["shell", "am", "force-stop", SUPERSHIFT_PACKAGE],
        ["shell", sqlite_command],
        ["shell", "am", "start", "-n", f"{SUPERSHIFT_PACKAGE}/.common.ui.LauncherActivity"],
    ]
    return {
        "ok": True,
        "backend": "sqlite_root",
        "dry_run": dry_run,
        "requires": ["adb root or equivalent /data/data access", "sqlite3 on device", "fresh backup"],
        "db_path": db_path,
        "calendar_row_id": calendar_row_id,
        "sql": sql,
        "commands": commands,
        "warning": "Experimental direct DB path. Use only on your own device/emulator after backup.",
    }


def create_supershift_shifts_sqlite(
    shifts: list[dict[str, Any] | ShiftDraft],
    calendar_row_id: int = 1,
    db_path: str = SUPERSHIFT_DB_PATH,
    dry_run: bool = True,
    adb_path: str = "adb",
) -> dict[str, Any]:
    plan = build_sqlite_insert_plan(shifts, calendar_row_id, db_path, dry_run)
    if not plan.get("ok") or dry_run:
        return {**plan, "executed": False}
    if os.getenv(REVERSE_ENV) != "1":
        return {
            **plan,
            "ok": False,
            "executed": False,
            "error": f"Refusing direct DB write. Set {REVERSE_ENV}=1.",
        }
    return _execute_adb_plan(plan, adb_path)


def create_supershift_shifts_sqlite_from_text(
    text: str,
    calendar_row_id: int = 1,
    db_path: str = SUPERSHIFT_DB_PATH,
    dry_run: bool = True,
    adb_path: str = "adb",
    default_timezone: str = DEFAULT_TIMEZONE,
) -> dict[str, Any]:
    drafts = parse_shift_text(text, default_timezone)
    result = create_supershift_shifts_sqlite(drafts, calendar_row_id, db_path, dry_run, adb_path)
    return {**result, "shifts": [draft.as_dict() for draft in drafts]}


def android_device_status(adb_path: str = "adb") -> dict[str, Any]:
    if shutil.which(adb_path) is None:
        return {"adb_available": False, "devices": [], "error": f"{adb_path} not found"}
    result = _run([adb_path, "devices", "-l"], check=False)
    devices = []
    for line in result.stdout.splitlines()[1:]:
        if not line.strip():
            continue
        parts = line.split()
        devices.append({"serial": parts[0], "state": parts[1] if len(parts) > 1 else "unknown"})
    return {
        "adb_available": True,
        "devices": devices,
        "raw": result.stdout,
        "stderr": result.stderr,
    }


def supershift_app_status(adb_path: str = "adb") -> dict[str, Any]:
    devices = android_device_status(adb_path)
    if not devices.get("devices"):
        return {**devices, "installed": False, "error": "No Android device connected via ADB."}
    result = _run([adb_path, "shell", "pm", "path", SUPERSHIFT_PACKAGE], check=False)
    return {
        **devices,
        "installed": result.returncode == 0 and bool(result.stdout.strip()),
        "package": SUPERSHIFT_PACKAGE,
        "path": result.stdout.strip() or None,
        "stderr": result.stderr,
    }


def dump_supershift_ui(adb_path: str = "adb") -> dict[str, Any]:
    status = supershift_app_status(adb_path)
    if not status.get("installed"):
        return {**status, "ok": False}
    _run([adb_path, "shell", "monkey", "-p", SUPERSHIFT_PACKAGE, "1"], check=False)
    _run([adb_path, "shell", "uiautomator", "dump", "/sdcard/window.xml"], check=False)
    result = _run([adb_path, "exec-out", "cat", "/sdcard/window.xml"], check=False)
    return {**status, "ok": result.returncode == 0, "xml": result.stdout, "stderr": result.stderr}


def create_supershift_shifts(
    shifts: list[dict[str, Any] | ShiftDraft],
    backend: str = "adb_ui",
    profile_path: str | None = None,
    dry_run: bool = True,
    adb_path: str = "adb",
) -> dict[str, Any]:
    drafts = normalize_shift_drafts(shifts)
    errors = validate_shift_drafts(drafts)
    if errors:
        return {"ok": False, "errors": errors}

    if backend == "adb_ui":
        profile = load_ui_profile(profile_path)
        plan = build_ui_automation_plan(drafts, profile)
    elif backend == "android_calendar_intent":
        plan = {
            "ok": True,
            "backend": backend,
            "count": len(drafts),
            "commands": build_android_calendar_intents(drafts),
            "warning": "This opens Android Calendar insert intents, not the Supershift app.",
        }
    else:
        raise ValueError("backend must be one of: adb_ui, android_calendar_intent.")

    if dry_run:
        return {**plan, "executed": False, "dry_run": True}
    if os.getenv(WRITE_ENV) != "1":
        return {
            **plan,
            "executed": False,
            "dry_run": False,
            "ok": False,
            "error": f"Refusing to write. Set {WRITE_ENV}=1 to enable ADB input.",
        }

    results = []
    for command in plan["commands"]:
        result = _run([adb_path, *command], check=False)
        results.append(
            {
                "command": [adb_path, *command],
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        )
        if result.returncode != 0:
            return {**plan, "ok": False, "executed": True, "results": results}
    return {**plan, "ok": True, "executed": True, "results": results}


def create_supershift_shifts_from_text(
    text: str,
    backend: str = "adb_ui",
    profile_path: str | None = None,
    dry_run: bool = True,
    adb_path: str = "adb",
    default_timezone: str = DEFAULT_TIMEZONE,
) -> dict[str, Any]:
    drafts = parse_shift_text(text, default_timezone)
    result = create_supershift_shifts(drafts, backend, profile_path, dry_run, adb_path)
    return {**result, "shifts": [draft.as_dict() for draft in drafts]}


def _split_body(body: str) -> tuple[str, str | None, str | None]:
    notes = None
    if "#" in body:
        body, notes = body.split("#", 1)
        notes = notes.strip() or None
    location = None
    if "@" in body:
        body, location = body.split("@", 1)
        location = location.strip() or None
    return body.strip(), location, notes


def _parse_start_end(
    day: str,
    start_time: str,
    end_time: str,
    default_timezone: str,
) -> tuple[datetime, datetime]:
    if "." in day:
        parsed_day = datetime.strptime(day, "%d.%m.%Y").date()
    else:
        parsed_day = datetime.strptime(day, "%Y-%m-%d").date()
    start = isoparse(f"{parsed_day.isoformat()}T{_pad_time(start_time)}:00{default_timezone}")
    end = isoparse(f"{parsed_day.isoformat()}T{_pad_time(end_time)}:00{default_timezone}")
    if end <= start:
        end += timedelta(days=1)
    return start, end


def _pad_time(value: str) -> str:
    hour, minute = value.split(":", 1)
    return f"{int(hour):02d}:{minute}"


def _step_to_commands(step: dict[str, Any], context: dict[str, str]) -> list[list[str]]:
    action = step.get("action")
    if action == "tap":
        return [["shell", "input", "tap", str(step["x"]), str(step["y"])]]
    if action == "text":
        value = _format_step_value(str(step.get("value", "")), context)
        return [["shell", "input", "text", _adb_text(value)]]
    if action == "keyevent":
        return [["shell", "input", "keyevent", str(step["key"])]]
    if action == "swipe":
        return [
            [
                "shell",
                "input",
                "swipe",
                str(step["x1"]),
                str(step["y1"]),
                str(step["x2"]),
                str(step["y2"]),
                str(step.get("duration_ms", 300)),
            ]
        ]
    if action == "wait":
        seconds = str(float(step.get("seconds", 1)))
        return [["shell", "sleep", seconds]]
    raise ValueError(f"Unsupported UI automation action: {action}")


def _format_step_value(template: str, context: dict[str, str]) -> str:
    return template.format(**context)


def _adb_text(value: str) -> str:
    return quote(value, safe="").replace("%20", "%s")


def _epoch_ms(value: str) -> int:
    return int(isoparse(value).timestamp() * 1000)


def _xml_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    return value.lower() == "true"


def _reverse_static_findings(inspect_result: dict[str, Any]) -> list[str]:
    findings: list[str] = []
    badging = inspect_result.get("badging", {})
    if badging.get("package") == SUPERSHIFT_PACKAGE:
        findings.append("APK package matches app.supershift.")
    permissions = set(badging.get("permissions", []))
    if "android.permission.WRITE_CALENDAR" in permissions:
        findings.append("APK can write Android Calendar events.")
    if "android.permission.INTERNET" in permissions:
        findings.append("APK has network access for Cloud Sync.")
    manifest = inspect_result.get("manifest", {})
    if manifest.get("required_split_types"):
        findings.append("APK requires split APKs; install-multiple is needed.")
    if manifest.get("allow_backup") is True:
        findings.append("Android backup/data extraction may be available, depending on device policy.")
    return findings


def _execute_adb_plan(plan: dict[str, Any], adb_path: str) -> dict[str, Any]:
    results = []
    for command in plan["commands"]:
        result = _run([adb_path, *command], check=False)
        results.append(
            {
                "command": [adb_path, *command],
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        )
        if result.returncode != 0:
            return {**plan, "ok": False, "executed": True, "results": results}
    return {**plan, "ok": True, "executed": True, "results": results}


def _draft_to_cloud_event(draft: ShiftDraft, calendar_id: str, event_type: int) -> dict[str, Any]:
    start = isoparse(draft.start)
    end = isoparse(draft.end)
    event = {
        "uuid": str(uuid.uuid4()),
        "updatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "deleted": False,
        "breaks": [],
        "location": {"title": draft.location} if draft.location else None,
        "notifications": [],
        "date": int(start.strftime("%Y%m%d")),
        "type": event_type,
        "template": None,
        "start": _seconds_since_midnight(start),
        "end": _seconds_since_midnight(end),
        "title": draft.title,
        "endDate": int(end.strftime("%Y%m%d")) if end.date() != start.date() else None,
        "allDay": False,
        "note": draft.notes,
        "recurrenceRule": None,
        "calendarId": calendar_id,
    }
    return event


def _draft_to_sqlite_inserts(draft: ShiftDraft, calendar_row_id: int) -> list[str]:
    start = isoparse(draft.start)
    end = isoparse(draft.end)
    date_int = int(start.strftime("%Y%m%d"))
    end_date_int = int(end.strftime("%Y%m%d"))
    now = datetime.now(timezone.utc).timestamp()
    event_uuid = str(uuid.uuid4())
    values = [
        _sql_string(event_uuid),
        str(date_int),
        "NULL",
        "0",
        "0",
        str(now),
        "0.0",
        _sql_string(draft.notes),
        str(_seconds_since_midnight(start)),
        str(_seconds_since_midnight(end)),
        str(end_date_int),
        "0",
        "0",
        _sql_string(draft.title),
        "NULL",
        "NULL",
        str(calendar_row_id),
        "NULL",
        _sql_string(draft.location),
        "NULL",
        "NULL",
        "NULL",
        "NULL",
    ]
    columns = [
        "eventUuid",
        "date",
        "cloudId",
        "cloudInSync",
        "deleted",
        "localLastModified",
        "cloudLastModified",
        "note",
        "startTime",
        "endTime",
        "endDate",
        "allDay",
        "type",
        "title",
        "recurrenceRule",
        "templateId",
        "calendarId",
        "ownerUserId",
        "location_address1",
        "location_address2",
        "location_longitude",
        "location_latitude",
        "location_viewport",
    ]
    event_insert = f"INSERT INTO event ({', '.join(columns)}) VALUES ({', '.join(values)});"
    sync_insert = (
        "INSERT INTO calendar_sync_task (calendarEntryUuid, created) "
        f"VALUES ({_sql_string(event_uuid)}, {int(now * 1000)});"
    )
    return [event_insert, sync_insert]


def _sql_string(value: str | None) -> str:
    if value is None or value == "":
        return "NULL"
    return "'" + value.replace("'", "''") + "'"


def _seconds_since_midnight(value: datetime) -> float:
    return float(value.hour * 3600 + value.minute * 60 + value.second)


def _run(
    command: list[str],
    check: bool = True,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> subprocess.CompletedProcess[str]:
    return runner(command, text=True, capture_output=True, check=check)
