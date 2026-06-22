from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any, Callable
from urllib.parse import quote

from dateutil.parser import isoparse


SUPERSHIFT_PACKAGE = "app.supershift"
WRITE_ENV = "SUPERSHIFT_WRITE_ENABLED"
DEFAULT_TIMEZONE = "+02:00"


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


def _run(
    command: list[str],
    check: bool = True,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> subprocess.CompletedProcess[str]:
    return runner(command, text=True, capture_output=True, check=check)
