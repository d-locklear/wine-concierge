import os

import requests
from flask import Blueprint, jsonify, send_from_directory

assistant_bp = Blueprint(
    "assistant",
    __name__,
    url_prefix="/assistant",
    static_folder="static",
)

REALTIME_CLIENT_SECRETS_URL = "https://api.openai.com/v1/realtime/client_secrets"

# Working persona until the name and personality decision is made.
ASSISTANT_INSTRUCTIONS = """You are a private personal assistant for the owner of \
Locklear Vineyard and Winery in North Carolina. You speak naturally and concisely, \
like a trusted chief of staff who also knows winemaking and vineyard operations. \
Keep spoken replies short unless asked for detail. If you are unsure, say so. \
You cannot yet save memories, set reminders, or take actions; if asked, say that \
this is coming in a later version rather than pretending to do it."""


def realtime_session_config():
    return {
        "session": {
            "type": "realtime",
            "model": os.getenv("REALTIME_MODEL", "gpt-realtime"),
            "instructions": ASSISTANT_INSTRUCTIONS,
            "audio": {
                "output": {"voice": os.getenv("REALTIME_VOICE", "marin")},
            },
        }
    }


@assistant_bp.route("/")
def index():
    return send_from_directory(assistant_bp.static_folder, "index.html")


@assistant_bp.route("/session", methods=["POST"])
def create_session():
    """Mint a short-lived client secret so the browser never sees OPENAI_API_KEY."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return jsonify({"error": "OPENAI_API_KEY is not configured"}), 500

    try:
        resp = requests.post(
            REALTIME_CLIENT_SECRETS_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=realtime_session_config(),
            timeout=10,
        )
    except requests.RequestException:
        return jsonify({"error": "Could not reach the voice service"}), 502

    if not resp.ok:
        return jsonify({"error": "Voice service refused the session"}), 502

    data = resp.json()
    return jsonify({
        "client_secret": data.get("value"),
        "expires_at": data.get("expires_at"),
        "model": realtime_session_config()["session"]["model"],
    })
