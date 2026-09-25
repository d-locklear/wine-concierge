from unittest.mock import MagicMock, patch

import pytest
import requests
from flask import Flask

from assistant import assistant_bp


@pytest.fixture
def client():
    app = Flask(__name__)
    app.register_blueprint(assistant_bp)
    return app.test_client()


def test_index_serves_page(client):
    resp = client.get("/assistant/")
    assert resp.status_code == 200
    assert b"Mark important" in resp.data


AUTH = {"X-Access-Code": "letmein"}


@pytest.fixture(autouse=True)
def access_code(monkeypatch):
    monkeypatch.setenv("ASSISTANT_ACCESS_CODE", "letmein")


def test_session_requires_access_code(client, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real-secret")
    with patch("assistant.routes.requests.post") as post:
        assert client.post("/assistant/session").status_code == 401
        wrong = client.post("/assistant/session", headers={"X-Access-Code": "nope"})
        assert wrong.status_code == 401
    post.assert_not_called()


def test_session_refuses_when_access_code_unset(client, monkeypatch):
    monkeypatch.delenv("ASSISTANT_ACCESS_CODE")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real-secret")
    assert client.post("/assistant/session", headers=AUTH).status_code == 500


def test_session_requires_api_key(client, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    resp = client.post("/assistant/session", headers=AUTH)
    assert resp.status_code == 500


def test_session_returns_ephemeral_secret_not_api_key(client, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real-secret")
    upstream = MagicMock(ok=True)
    upstream.json.return_value = {"value": "ek_temp", "expires_at": 123}
    with patch("assistant.routes.requests.post", return_value=upstream) as post:
        resp = client.post("/assistant/session", headers=AUTH)

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["client_secret"] == "ek_temp"
    assert "sk-real-secret" not in resp.get_data(as_text=True)
    sent = post.call_args.kwargs
    assert sent["headers"]["Authorization"] == "Bearer sk-real-secret"
    assert sent["json"]["session"]["type"] == "realtime"


def test_session_upstream_failure(client, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real-secret")
    with patch("assistant.routes.requests.post", side_effect=requests.ConnectionError):
        resp = client.post("/assistant/session", headers=AUTH)
    assert resp.status_code == 502
