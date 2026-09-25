import hmac
import os

import requests
from flask import Blueprint, current_app, jsonify, request, send_from_directory

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


def upstream_error_message(resp):
    try:
        return resp.json()["error"]["message"]
    except (ValueError, KeyError, TypeError):
        return f"HTTP {resp.status_code}"


@assistant_bp.route("/")
def index():
    return send_from_directory(assistant_bp.static_folder, "index.html")


@assistant_bp.route("/session", methods=["POST"])
def create_session():
    """Mint a short-lived client secret so the browser never sees OPENAI_API_KEY."""
    access_code = os.getenv("ASSISTANT_ACCESS_CODE")
    if not access_code:
        return jsonify({"error": "ASSISTANT_ACCESS_CODE is not configured"}), 500
    supplied = request.headers.get("X-Access-Code", "")
    if not hmac.compare_digest(supplied.encode(), access_code.encode()):
        return jsonify({"error": "Wrong access code"}), 401

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
        detail = upstream_error_message(resp)
        current_app.logger.error("Realtime session refused (%s): %s", resp.status_code, detail)
        return jsonify({"error": f"Voice service refused the session: {detail}"}), 502

    data = resp.json()
    # The GA API returns {"value": ...}; the older beta shape nests it under "client_secret".
    nested = data.get("client_secret") if isinstance(data.get("client_secret"), dict) else {}
    secret = data.get("value") or nested.get("value")
    if not secret:
        current_app.logger.error("Realtime session response had no client secret: keys=%s", list(data))
        return jsonify({"error": "Voice service returned no session key"}), 502

    return jsonify({
        "client_secret": secret,
        "expires_at": data.get("expires_at") or nested.get("expires_at"),
        "model": realtime_session_config()["session"]["model"],
    })
