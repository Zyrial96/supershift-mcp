# supershift-mcp

`supershift-mcp` is a small MCP and HTTP bridge for schedules exported from
[Supershift](https://supershift.app/).

## Research result

As of 2026-06-21, I could not find a documented public Supershift API or an
existing Supershift MCP server. The public Supershift pages document local use,
optional Cloud Sync, calendar sharing, and export to external calendars. Google
Play also lists Android Calendar Export as a Pro feature.

This project therefore uses the stable integration point Supershift exposes to
users: exported calendar data, usually an `.ics` file or a private calendar URL
from the target calendar provider.

It deliberately does not reverse engineer Supershift Cloud Sync or private app
storage. The current bridge is read-oriented. It can list shifts, find the next
shift, and summarize hours from an exported calendar.

## Features

- MCP stdio server for AI clients
- Optional FastAPI HTTP API
- Reads local `.ics` files or HTTPS calendar URLs
- Lists shifts in a date range
- Returns the next shift
- Summarizes worked hours by shift title

## Install

```bash
python3 -m pip install "git+https://github.com/Zyrial96/supershift-mcp.git"
```

For local development:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[api,dev]"
pytest
```

## Configure

Set `SUPERSHIFT_ICS` to either a local `.ics` file or a private calendar URL:

```bash
export SUPERSHIFT_ICS="/path/to/supershift.ics"
```

or:

```bash
export SUPERSHIFT_ICS="https://calendar.example/private/supershift.ics"
```

On Android, Supershift Pro can export shifts to Google Calendar. You can then
use a private iCal URL for that calendar, or periodically export an `.ics` file.

## Run MCP

```bash
supershift-mcp
```

Example MCP client configuration:

```json
{
  "mcpServers": {
    "supershift": {
      "command": "supershift-mcp",
      "env": {
        "SUPERSHIFT_ICS": "/path/to/supershift.ics"
      }
    }
  }
}
```

Available tools:

- `calendar_status(calendar: str | None = None)`
- `list_shifts(start: str, end: str, calendar: str | None = None)`
- `next_shift(after: str | None = None, days: int = 90, calendar: str | None = None)`
- `summarize_shifts(start: str, end: str, calendar: str | None = None)`

## Run HTTP API

Install the API extra first:

```bash
python -m pip install -e ".[api]"
```

Then start the server:

```bash
supershift-api
```

Endpoints:

- `GET /health`
- `GET /shifts?start=2026-06-01&end=2026-07-01`
- `GET /shifts/next?days=30`
- `GET /summary?start=2026-06-01&end=2026-07-01`

## Boundaries

This is not an official Supershift product. It cannot create or edit entries
inside the Supershift Android app unless Supershift publishes a supported write
API in the future. Writing directly into Cloud Sync or private app storage would
be fragile and may violate user expectations or terms.
