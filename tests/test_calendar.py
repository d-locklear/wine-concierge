import json
from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
from flask import Flask

from assistant import assistant_bp, calendar_client, routes

AUTH = {"X-Access-Code": "letmein"}
NY = ZoneInfo("America/New_York")


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("ASSISTANT_ACCESS_CODE", "letmein")
    monkeypatch.setenv("GOOGLE_CALENDAR_USER", "owner@example.com")
    monkeypatch.setenv("GOOGLE_CREDENTIALS_JSON", "{}")
    monkeypatch.delenv("ASSISTANT_TIMEZONE", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)


@pytest.fixture
def client():
    app = Flask(__name__)
    app.register_blueprint(assistant_bp)
    return app.test_client()


class FakeGoogle:
    """Stands in for AuthorizedSession against the Calendar API."""

    def __init__(self):
        self.events = {}
        self.calls = []

    def request(self, method, url, timeout=None, json=None, params=None):
        self.calls.append((method, url, json, params))
        resp = MagicMock()
        resp.ok, resp.status_code, resp.content = True, 200, b"x"
        event_id = url.rsplit("/events/", 1)[1] if "/events/" in url else None
        if method == "POST":
            event = {**json, "id": f"evt{len(self.events) + 1}", "htmlLink": "https://calendar/x"}
            self.events[event["id"]] = event
            resp.json.return_value = event
        elif method == "GET" and event_id:
            if event_id not in self.events:
                resp.ok, resp.status_code = False, 404
            resp.json.return_value = self.events.get(event_id, {"error": {"message": "Not Found"}})
        elif method == "GET":
            resp.json.return_value = {"items": list(self.events.values())}
        elif method == "DELETE":
            self.events.pop(event_id, None)
            resp.status_code, resp.content = 204, b""
        return resp


@pytest.fixture
def google(monkeypatch):
    fake = FakeGoogle()
    monkeypatch.setattr(calendar_client, "_session", lambda: fake)
    return fake


def test_reminder_is_a_short_free_event_that_alerts_on_time():
    body = calendar_client.build_event("reminder", "Call the cork supplier", "2026-10-01T09:00:00")
    assert body["summary"] == "⏰ Call the cork supplier"
    assert body["start"]["dateTime"] == "2026-10-01T09:00:00-04:00"  # naive times are the owner's zone
    assert body["end"]["dateTime"] == "2026-10-01T09:15:00-04:00"
    assert body["transparency"] == "transparent"
    assert body["reminders"] == {"useDefault": False, "overrides": [{"method": "popup", "minutes": 0}]}
    assert body["extendedProperties"]["private"] == {"createdBy": "ambient-assistant", "kind": "reminder"}


def test_event_defaults_to_one_hour_and_keeps_explicit_offsets():
    body = calendar_client.build_event("event", "Distributor tasting", "2026-10-06T14:00:00-04:00",
                                       location="Tasting room", notes="Bring the 2024 Chambourcin", minutes_before=10)
    assert body["end"]["dateTime"] == "2026-10-06T15:00:00-04:00"
    assert "transparency" not in body
    assert body["location"] == "Tasting room"
    assert body["description"].startswith("Bring the 2024 Chambourcin")


@pytest.mark.parametrize("kwargs, message", [
    ({"kind": "reminder", "title": " ", "start": "2026-10-01T09:00"}, "title"),
    ({"kind": "reminder", "title": "x" * 201, "start": "2026-10-01T09:00"}, "at most"),
    ({"kind": "meeting", "title": "x", "start": "2026-10-01T09:00"}, "kind"),
    ({"kind": "reminder", "title": "x", "start": "Thursday"}, "isoformat"),
    ({"kind": "event", "title": "x", "start": "2026-10-01T09:00", "end": "2026-10-01T08:00"}, "after"),
    ({"kind": "event", "title": "x", "start": "2026-10-01T09:00", "end": "2026-10-20T09:00"}, "days"),
    ({"kind": "reminder", "title": "x", "start": "2026-10-01T09:00", "minutes_before": -5}, "minutes_before"),
])
def test_build_event_validation(kwargs, message):
    with pytest.raises(ValueError, match=message):
        calendar_client.build_event(**kwargs)


def test_add_reminder_route_creates_and_audits(client, google, monkeypatch):
    audited = []
    monkeypatch.setattr(routes, "audit_calendar", lambda action, ref: audited.append((action, ref)))
    resp = client.post("/assistant/calendar/events", headers=AUTH,
                       json={"kind": "reminder", "title": "Call the cork supplier", "start": "2026-10-01T09:00:00"})
    assert resp.status_code == 201
    event = resp.get_json()["event"]
    assert event["title"] == "⏰ Call the cork supplier"
    assert event["created_by_assistant"] is True
    assert google.calls[0][1].endswith("/calendars/primary/events")
    assert audited == [("created_reminder", "evt1")]


def test_event_route_defaults_alert_to_ten_minutes(client, google):
    client.post("/assistant/calendar/events", headers=AUTH, json={"kind": "event", "title": "Tasting", "start": "2026-10-06T14:00"})
    assert google.calls[0][2]["reminders"]["overrides"] == [{"method": "popup", "minutes": 10}]


def test_add_route_rejects_bad_input_without_calling_google(client, google):
    resp = client.post("/assistant/calendar/events", headers=AUTH, json={"kind": "reminder", "title": "x", "start": "soon"})
    assert resp.status_code == 400
    assert google.calls == []


def test_undo_only_deletes_assistant_events(client, google):
    google.events["mine"] = calendar_client.build_event("reminder", "x", "2026-10-01T09:00") | {"id": "mine"}
    google.events["theirs"] = {"id": "theirs", "summary": "Board meeting"}
    assert client.delete("/assistant/calendar/events/theirs", headers=AUTH).status_code == 404
    assert "theirs" in google.events
    assert client.delete("/assistant/calendar/events/mine", headers=AUTH).status_code == 204
    assert "mine" not in google.events
    assert client.delete("/assistant/calendar/events/mine", headers=AUTH).status_code == 404
    assert client.delete("/assistant/calendar/events/bad%2Fid", headers=AUTH).status_code in (400, 404)


def test_check_calendar_lists_events(client, google):
    google.events["a"] = {"id": "a", "summary": "Bottling", "start": {"dateTime": "2026-10-02T08:00:00-04:00"},
                          "end": {"dateTime": "2026-10-02T12:00:00-04:00"}}
    google.events["b"] = {"id": "b", "summary": "Harvest party", "start": {"date": "2026-10-03"}, "end": {"date": "2026-10-04"}}
    resp = client.get("/assistant/calendar/events?start=2026-10-02T00:00&end=2026-10-04T00:00", headers=AUTH)
    events = resp.get_json()["events"]
    assert [(e["title"], e["all_day"]) for e in events] == [("Bottling", False), ("Harvest party", True)]
    params = google.calls[0][3]
    assert params["timeMin"] == "2026-10-02T00:00:00-04:00" and params["singleEvents"] == "true"


@pytest.mark.parametrize("query", ["", "?start=2026-10-02T00:00", "?start=2026-10-05&end=2026-10-01", "?start=2026-01-01&end=2026-06-01"])
def test_check_calendar_validation(client, google, query):
    assert client.get(f"/assistant/calendar/events{query}", headers=AUTH).status_code == 400


def test_calendar_routes_require_access_code(client, google):
    assert client.post("/assistant/calendar/events", json={}).status_code == 401
    assert client.delete("/assistant/calendar/events/x").status_code == 401
    assert client.get("/assistant/calendar/events").status_code == 401


def test_not_connected_is_a_clear_503(client, monkeypatch):
    monkeypatch.delenv("GOOGLE_CALENDAR_USER")
    resp = client.post("/assistant/calendar/events", headers=AUTH, json={"kind": "reminder", "title": "x", "start": "2026-10-01T09:00"})
    assert resp.status_code == 503
    assert "GOOGLE_CALENDAR_USER" in resp.get_json()["error"]


def test_missing_delegation_gives_a_helpful_reason(client, monkeypatch):
    session = MagicMock()
    session.request.side_effect = Exception("('unauthorized_client: Client is unauthorized to retrieve access tokens', {})")
    monkeypatch.setattr(calendar_client, "_session", lambda: session)
    resp = client.post("/assistant/calendar/events", headers=AUTH, json={"kind": "reminder", "title": "x", "start": "2026-10-01T09:00"})
    assert resp.status_code == 502
    assert "domain-wide delegation" in resp.get_json()["error"]


def test_session_instructions_include_local_date_and_calendar_tools(client, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk")
    monkeypatch.setattr(calendar_client, "now_local", lambda: datetime(2026, 9, 26, 8, 5, tzinfo=NY))
    upstream = MagicMock(ok=True)
    upstream.json.return_value = {"value": "ek"}
    with patch("assistant.routes.requests.post", return_value=upstream) as post:
        client.post("/assistant/session", headers=AUTH)
    session = post.call_args.kwargs["json"]["session"]
    assert "Right now it is Saturday, September 26, 2026, 8:05 AM (America/New_York, UTC offset -0400)" in session["instructions"]
    assert "isn't connected" not in session["instructions"]
    assert {"add_reminder", "add_calendar_event", "check_calendar"} <= {t["name"] for t in session["tools"]}


def test_session_instructions_warn_when_calendar_not_connected(client, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk")
    monkeypatch.delenv("GOOGLE_CALENDAR_USER")
    upstream = MagicMock(ok=True)
    upstream.json.return_value = {"value": "ek"}
    with patch("assistant.routes.requests.post", return_value=upstream) as post:
        client.post("/assistant/session", headers=AUTH)
    assert "calendar isn't connected yet" in post.call_args.kwargs["json"]["session"]["instructions"]


def test_real_credentials_are_delegated_to_the_owner(monkeypatch):
    """The service account key is loaded with calendar.events scope and impersonates the owner."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    pem = rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    monkeypatch.setenv("GOOGLE_CREDENTIALS_JSON", json.dumps({
        "type": "service_account", "client_email": "bot@proj.iam.gserviceaccount.com", "private_key": pem,
        "token_uri": "https://oauth2.googleapis.com/token", "project_id": "proj", "private_key_id": "k", "client_id": "1",
    }))
    session = calendar_client._session()
    assert session.credentials._subject == "owner@example.com"
    assert session.credentials._scopes == ["https://www.googleapis.com/auth/calendar.events"]
