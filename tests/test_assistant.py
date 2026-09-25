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


def test_session_requires_api_key(client, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    resp = client.post("/assistant/session")
    assert resp.status_code == 500


def test_session_returns_ephemeral_secret_not_api_key(client, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real-secret")
    upstream = MagicMock(ok=True)
    upstream.json.return_value = {"value": "ek_temp", "expires_at": 123}
    with patch("assistant.routes.requests.post", return_value=upstream) as post:
        resp = client.post("/assistant/session")

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
        resp = client.post("/assistant/session")
    assert resp.status_code == 502
