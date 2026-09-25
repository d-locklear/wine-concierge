import hmac
import json
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
CHAT_COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions"

MAX_TRANSCRIPT_ENTRIES = 3000
MAX_TRANSCRIPT_CHARS = 200_000

# Working persona until the name and personality decision is made.
ASSISTANT_INSTRUCTIONS = """You are a private personal assistant for the owner of \
Locklear Vineyard and Winery in North Carolina. You speak naturally and concisely, \
like a trusted chief of staff who also knows winemaking and vineyard operations. \
Keep spoken replies short unless asked for detail. If you are unsure, say so. \
You cannot yet save memories, set reminders, or take actions; if asked, say that \
this is coming in a later version rather than pretending to do it."""


SUMMARY_INSTRUCTIONS = """You turn conversation transcripts into concise working notes \
for the owner of Locklear Vineyard and Winery. "You" in the transcript is the owner; \
"Assistant" is their voice assistant. Other people in the room may appear under "You" \
because speakers are not separated yet, so infer who said what from context and say \
"someone" when unsure. Only include what the transcript supports; never invent names, \
dates, or commitments. Lines marked ★ are moments the owner flagged as important.

Reply with a JSON object with exactly these keys:
- "summary": 2-5 sentence overview (string)
- "decisions": decisions that were made (array of strings)
- "action_items": array of {"task": string, "owner": string or null, "due": string or null}
- "promises": commitments someone made to someone else (array of strings)
- "questions": open questions left unresolved (array of strings)
- "important_moments": array of {"time": "mm:ss", "note": string} explaining each ★ moment
Use empty arrays when there is nothing for a key."""


def transcription_model():
    return os.getenv("TRANSCRIPTION_MODEL", "gpt-4o-mini-transcribe")


def audio_input_config():
    # far_field suits a phone on a table or speakerphone; near_field suits a headset.
    return {
        "transcription": {"model": transcription_model()},
        "noise_reduction": {"type": os.getenv("NOISE_REDUCTION", "far_field")},
    }


def realtime_session_config():
    return {
        "session": {
            "type": "realtime",
            "model": os.getenv("REALTIME_MODEL", "gpt-realtime"),
            "instructions": ASSISTANT_INSTRUCTIONS,
            "audio": {
                "input": audio_input_config(),
                "output": {"voice": os.getenv("REALTIME_VOICE", "marin")},
            },
        }
    }


def check_access():
    """Return an error response if the request lacks the access code, else None."""
    access_code = os.getenv("ASSISTANT_ACCESS_CODE")
    if not access_code:
        return jsonify({"error": "ASSISTANT_ACCESS_CODE is not configured"}), 500
    supplied = request.headers.get("X-Access-Code", "")
    if not hmac.compare_digest(supplied.encode(), access_code.encode()):
        return jsonify({"error": "Wrong access code"}), 401
    return None


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
    denied = check_access()
    if denied:
        return denied

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
        "transcription_model": transcription_model(),
        "audio_input": audio_input_config(),
    })


def fmt_ms(ms):
    seconds = max(0, int(ms // 1000))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def as_ms(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0


def build_transcript(entries, marks):
    """Render entries and marks as timestamped lines in time order."""
    lines = []
    for entry in entries:
        speaker = "Assistant" if entry.get("speaker") == "assistant" else "You"
        text = str(entry.get("text") or "").strip()
        if text:
            t = as_ms(entry.get("t"))
            lines.append((t, f"[{fmt_ms(t)}] {speaker}: {text}"))
    for mark in marks:
        lines.append((float(mark), f"[{fmt_ms(mark)}] ★ Marked important"))
    lines.sort(key=lambda line: line[0])
    return "\n".join(line for _, line in lines)


def as_str_list(value):
    if not isinstance(value, list):
        return []
    return [str(v).strip() for v in value if isinstance(v, (str, int, float)) and str(v).strip()]


def optional_str(value):
    return str(value).strip() if isinstance(value, (str, int, float)) and str(value).strip() else None


def normalize_notes(raw):
    """Coerce the model's JSON into the fixed shape the page expects."""
    raw = raw if isinstance(raw, dict) else {}
    actions = []
    for item in raw.get("action_items") or []:
        if isinstance(item, dict) and optional_str(item.get("task")):
            actions.append({
                "task": optional_str(item.get("task")),
                "owner": optional_str(item.get("owner")),
                "due": optional_str(item.get("due")),
            })
    moments = []
    for item in raw.get("important_moments") or []:
        if isinstance(item, dict) and optional_str(item.get("note")):
            moments.append({"time": optional_str(item.get("time")) or "", "note": optional_str(item.get("note"))})
    return {
        "summary": optional_str(raw.get("summary")) or "",
        "decisions": as_str_list(raw.get("decisions")),
        "action_items": actions,
        "promises": as_str_list(raw.get("promises")),
        "questions": as_str_list(raw.get("questions")),
        "important_moments": moments,
    }


@assistant_bp.route("/summarize", methods=["POST"])
def summarize():
    """Turn a finished session's transcript into notes. Nothing is stored."""
    denied = check_access()
    if denied:
        return denied

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return jsonify({"error": "OPENAI_API_KEY is not configured"}), 500

    body = request.get_json(silent=True) or {}
    entries = body.get("entries")
    marks = body.get("marks") or []
    if not isinstance(entries, list) or not isinstance(marks, list):
        return jsonify({"error": "entries and marks must be lists"}), 400
    if len(entries) > MAX_TRANSCRIPT_ENTRIES:
        return jsonify({"error": "Transcript is too long to summarize"}), 413
    entries = [e for e in entries if isinstance(e, dict)]
    marks = [as_ms(m) for m in marks if isinstance(m, (int, float)) and not isinstance(m, bool)]

    transcript = build_transcript(entries, marks)
    if not transcript.strip() or all("★" in line for line in transcript.splitlines()):
        return jsonify({"error": "Nothing was transcribed in this session"}), 400
    if len(transcript) > MAX_TRANSCRIPT_CHARS:
        return jsonify({"error": "Transcript is too long to summarize"}), 413

    try:
        resp = requests.post(
            CHAT_COMPLETIONS_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": os.getenv("SUMMARY_MODEL", "gpt-5-mini"),
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": SUMMARY_INSTRUCTIONS},
                    {"role": "user", "content": transcript},
                ],
            },
            timeout=90,
        )
    except requests.RequestException:
        return jsonify({"error": "Could not reach the summary service"}), 502

    if not resp.ok:
        detail = upstream_error_message(resp)
        # Log the reason only; never the transcript.
        current_app.logger.error("Summary refused (%s): %s", resp.status_code, detail)
        return jsonify({"error": f"Summary service refused the request: {detail}"}), 502

    try:
        content = resp.json()["choices"][0]["message"]["content"]
        notes = normalize_notes(json.loads(content))
    except (ValueError, KeyError, IndexError, TypeError):
        current_app.logger.error("Summary response was not valid JSON notes")
        return jsonify({"error": "Summary service returned an unreadable result"}), 502

    return jsonify({"notes": notes, "transcript": transcript})
