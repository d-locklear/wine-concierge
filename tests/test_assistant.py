import json
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


def test_session_accepts_nested_client_secret_shape(client, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real-secret")
    upstream = MagicMock(ok=True)
    upstream.json.return_value = {"client_secret": {"value": "ek_nested", "expires_at": 5}}
    with patch("assistant.routes.requests.post", return_value=upstream):
        resp = client.post("/assistant/session", headers=AUTH)
    assert resp.status_code == 200
    assert resp.get_json()["client_secret"] == "ek_nested"


def test_session_missing_secret_is_an_error(client, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real-secret")
    upstream = MagicMock(ok=True)
    upstream.json.return_value = {"id": "sess_1"}
    with patch("assistant.routes.requests.post", return_value=upstream):
        resp = client.post("/assistant/session", headers=AUTH)
    assert resp.status_code == 502


def test_session_refusal_passes_through_reason(client, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real-secret")
    upstream = MagicMock(ok=False, status_code=400)
    upstream.json.return_value = {"error": {"message": "Unknown parameter"}}
    with patch("assistant.routes.requests.post", return_value=upstream):
        resp = client.post("/assistant/session", headers=AUTH)
    assert resp.status_code == 502
    assert "Unknown parameter" in resp.get_json()["error"]


def test_session_enables_input_transcription(client, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real-secret")
    upstream = MagicMock(ok=True)
    upstream.json.return_value = {"value": "ek_temp"}
    with patch("assistant.routes.requests.post", return_value=upstream) as post:
        resp = client.post("/assistant/session", headers=AUTH)
    audio_input = post.call_args.kwargs["json"]["session"]["audio"]["input"]
    assert audio_input["transcription"]["model"]
    assert resp.get_json()["transcription_model"] == audio_input["transcription"]["model"]
    assert audio_input["noise_reduction"]["type"] == "far_field"
    # The page reuses this so its session.update doesn't drop transcription or noise reduction.
    assert resp.get_json()["audio_input"] == audio_input


def chat_reply(content):
    upstream = MagicMock(ok=True)
    upstream.json.return_value = {"choices": [{"message": {"content": content}}]}
    return upstream


SESSION = {
    "entries": [
        {"t": 65000, "speaker": "assistant", "text": "Sure, I can help."},
        {"t": 1000, "speaker": "user", "text": "Let's bottle the Muscadine Friday."},
    ],
    "marks": [3000],
}


def test_summarize_requires_access_code(client, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real-secret")
    with patch("assistant.routes.requests.post") as post:
        assert client.post("/assistant/summarize", json=SESSION).status_code == 401
    post.assert_not_called()


def test_summarize_sends_ordered_transcript_and_normalizes_notes(client, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real-secret")
    model_json = json.dumps({
        "summary": "Planned bottling.",
        "decisions": ["Bottle Muscadine on Friday", ""],
        "action_items": [{"task": "Book the bottling line", "owner": "Daryl"}, {"owner": "no task"}],
        "questions": "not a list",
        "important_moments": [{"time": "00:03", "note": "Bottling date"}],
    })
    with patch("assistant.routes.requests.post", return_value=chat_reply(model_json)) as post:
        resp = client.post("/assistant/summarize", json=SESSION, headers=AUTH)

    assert resp.status_code == 200
    sent = post.call_args.kwargs["json"]
    transcript = sent["messages"][1]["content"]
    assert transcript.splitlines() == [
        "[00:01] You: Let's bottle the Muscadine Friday.",
        "[00:03] ★ Marked important",
        "[01:05] Assistant: Sure, I can help.",
    ]
    assert sent["response_format"] == {"type": "json_object"}
    notes = resp.get_json()["notes"]
    assert notes["decisions"] == ["Bottle Muscadine on Friday"]
    assert notes["action_items"] == [{"task": "Book the bottling line", "owner": "Daryl", "due": None}]
    assert notes["questions"] == []
    assert notes["promises"] == []
    assert notes["important_moments"] == [{"time": "00:03", "note": "Bottling date"}]


def test_summarize_rejects_empty_transcript(client, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real-secret")
    with patch("assistant.routes.requests.post") as post:
        resp = client.post(
            "/assistant/summarize",
            json={"entries": [{"t": 0, "speaker": "user", "text": "  "}], "marks": [100]},
            headers=AUTH,
        )
    assert resp.status_code == 400
    post.assert_not_called()


def test_summarize_ignores_malformed_items(client, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real-secret")
    body = {"entries": ["junk", {"t": "soon", "speaker": "user", "text": "Hello"}], "marks": ["x", True]}
    with patch("assistant.routes.requests.post", return_value=chat_reply("{}")) as post:
        resp = client.post("/assistant/summarize", json=body, headers=AUTH)
    assert resp.status_code == 200
    assert post.call_args.kwargs["json"]["messages"][1]["content"] == "[00:00] You: Hello"


def test_summarize_rejects_oversized_transcript(client, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real-secret")
    body = {"entries": [{"t": 0, "speaker": "user", "text": "x" * 200_001}], "marks": []}
    with patch("assistant.routes.requests.post") as post:
        resp = client.post("/assistant/summarize", json=body, headers=AUTH)
    assert resp.status_code == 413
    post.assert_not_called()


def test_summarize_unreadable_model_output(client, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real-secret")
    with patch("assistant.routes.requests.post", return_value=chat_reply("not json")):
        resp = client.post("/assistant/summarize", json=SESSION, headers=AUTH)
    assert resp.status_code == 502


def test_summarize_upstream_refusal_passes_reason(client, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real-secret")
    upstream = MagicMock(ok=False, status_code=404)
    upstream.json.return_value = {"error": {"message": "model not found"}}
    with patch("assistant.routes.requests.post", return_value=upstream):
        resp = client.post("/assistant/summarize", json=SESSION, headers=AUTH)
    assert resp.status_code == 502
    assert "model not found" in resp.get_json()["error"]


@pytest.mark.parametrize("suggested, expected", [("personal", "personal"), ("work", "winery"), (None, "winery")])
def test_summarize_suggests_a_valid_category(client, monkeypatch, suggested, expected):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real-secret")
    with patch("assistant.routes.requests.post", return_value=chat_reply(json.dumps({"category": suggested}))):
        resp = client.post("/assistant/summarize", json=SESSION, headers=AUTH)
    assert resp.get_json()["notes"]["category"] == expected
