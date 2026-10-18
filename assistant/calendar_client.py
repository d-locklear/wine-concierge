"""Google Calendar access for the assistant.

Uses the app's existing Google service account (GOOGLE_CREDENTIALS_JSON) with
domain-wide delegation to act as GOOGLE_CALENDAR_USER, limited to the
calendar.events scope. Reminders are short calendar events that don't block
time and alert at the chosen moment.
"""

import json
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from google.auth.transport.requests import AuthorizedSession
from google.oauth2 import service_account

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
API = "https://www.googleapis.com/calendar/v3"
REMINDER_MINUTES = 15
MAX_TITLE_CHARS = 200
MAX_EVENT_DAYS = 7
# Marks events this assistant created, so Undo can never delete anything else.
CREATED_BY = "ambient-assistant"


class CalendarNotConfigured(Exception):
    pass


class CalendarError(Exception):
    """A readable reason the calendar request failed."""


class EventNotFound(Exception):
    pass


def timezone_name():
    return os.getenv("ASSISTANT_TIMEZONE", "America/New_York")


def local_zone():
    try:
        return ZoneInfo(timezone_name())
    except ZoneInfoNotFoundError:
        return ZoneInfo("America/New_York")


def now_local():
    return datetime.now(local_zone())


def parse_when(value):
    """Parse an ISO 8601 date-time; times without an offset are in the owner's time zone."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("A date and time is required")
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=local_zone())
    return parsed


def is_configured():
    return bool(os.getenv("GOOGLE_CALENDAR_USER") and os.getenv("GOOGLE_CREDENTIALS_JSON"))


def _session():
    user = os.getenv("GOOGLE_CALENDAR_USER")
    raw = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if not user or not raw:
        raise CalendarNotConfigured()
    try:
        info = json.loads(raw)
        creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES).with_subject(user)
    except (ValueError, KeyError) as exc:
        raise CalendarError("GOOGLE_CREDENTIALS_JSON isn't a valid service account key") from exc
    return AuthorizedSession(creds)


def _calendar_id():
    return os.getenv("GOOGLE_CALENDAR_ID", "primary")


def _check(resp):
    if resp.status_code == 404:
        raise EventNotFound()
    if not resp.ok:
        try:
            error = resp.json().get("error")
            detail = error.get("message") if isinstance(error, dict) else resp.json().get("error_description") or error
        except ValueError:
            detail = None
        raise CalendarError(detail or f"HTTP {resp.status_code}")
    return resp.json() if resp.content else None


def _request(method, path, **kwargs):
    try:
        session = _session()
        return _check(session.request(method, f"{API}{path}", timeout=20, **kwargs))
    except (CalendarNotConfigured, CalendarError, EventNotFound):
        raise
    except Exception as exc:  # noqa: BLE001 - auth refresh failures surface here (e.g. delegation not set up)
        message = str(exc)
        if "unauthorized_client" in message:
            message = ("Google refused access. Check domain-wide delegation for the service account "
                       "with the calendar.events scope, and that the Calendar API is enabled.")
        raise CalendarError(message[:300]) from exc


def _summary(event):
    def moment(side):
        value = event.get(side) or {}
        return value.get("dateTime") or value.get("date")

    private = (event.get("extendedProperties") or {}).get("private") or {}
    return {
        "id": event.get("id"),
        "title": event.get("summary") or "(no title)",
        "start": moment("start"),
        "end": moment("end"),
        "all_day": "date" in (event.get("start") or {}),
        "location": event.get("location"),
        "link": event.get("htmlLink"),
        "kind": private.get("kind"),
        "created_by_assistant": private.get("createdBy") == CREATED_BY,
    }


def build_event(kind, title, start, end=None, minutes_before=0, location=None, notes=None):
    """Validate input and return a Calendar API event body."""
    title = str(title or "").strip()
    if not title:
        raise ValueError("A title is required")
    if len(title) > MAX_TITLE_CHARS:
        raise ValueError(f"Titles can be at most {MAX_TITLE_CHARS} characters")
    if kind not in ("reminder", "event"):
        raise ValueError("kind must be reminder or event")
    start_dt = parse_when(start)
    if kind == "reminder":
        end_dt = start_dt + timedelta(minutes=REMINDER_MINUTES)
    else:
        end_dt = parse_when(end) if end else start_dt + timedelta(hours=1)
    if end_dt <= start_dt:
        raise ValueError("The end must be after the start")
    if end_dt - start_dt > timedelta(days=MAX_EVENT_DAYS):
        raise ValueError(f"Events can be at most {MAX_EVENT_DAYS} days long")
    if not isinstance(minutes_before, int) or isinstance(minutes_before, bool) or not 0 <= minutes_before <= 40320:
        raise ValueError("minutes_before must be between 0 and 40320 (four weeks)")

    tz = timezone_name()
    body = {
        "summary": f"⏰ {title}" if kind == "reminder" else title,
        "start": {"dateTime": start_dt.isoformat(), "timeZone": tz},
        "end": {"dateTime": end_dt.isoformat(), "timeZone": tz},
        "description": "\n\n".join(p for p in [str(notes).strip() if notes else "", "Added by your assistant."] if p),
        "reminders": {"useDefault": False, "overrides": [{"method": "popup", "minutes": minutes_before}]},
        "extendedProperties": {"private": {"createdBy": CREATED_BY, "kind": kind}},
    }
    if kind == "reminder":
        # Show as free so a reminder never makes the owner look busy.
        body["transparency"] = "transparent"
    if location:
        body["location"] = str(location).strip()[:500]
    return body


def create_event(body):
    return _summary(_request("POST", f"/calendars/{_calendar_id()}/events", json=body))


def delete_assistant_event(event_id):
    """Delete an event only if this assistant created it."""
    event = _request("GET", f"/calendars/{_calendar_id()}/events/{event_id}")
    if not _summary(event)["created_by_assistant"]:
        raise EventNotFound()
    _request("DELETE", f"/calendars/{_calendar_id()}/events/{event_id}")


def list_events(start, end, limit=50):
    data = _request("GET", f"/calendars/{_calendar_id()}/events", params={
        "timeMin": start.isoformat(),
        "timeMax": end.isoformat(),
        "singleEvents": "true",
        "orderBy": "startTime",
        "maxResults": str(limit),
        "timeZone": timezone_name(),
    })
    return [_summary(e) for e in (data or {}).get("items", []) if e.get("status") != "cancelled"]
