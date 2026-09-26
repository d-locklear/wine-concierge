import hmac
import json
import os

from datetime import datetime, timezone

import requests
from flask import Blueprint, Response, current_app, jsonify, request, send_from_directory

from .memory_store import (
    CATEGORIES,
    MAX_MEMORY_CHARS,
    MemoryNotFound,
    StorageNotConfigured,
    UnreadableMemory,
    get_store,
)

assistant_bp = Blueprint(
    "assistant",
    __name__,
    url_prefix="/assistant",
    static_folder="static",
)

REALTIME_CLIENT_SECRETS_URL = "https://api.openai.com/v1/realtime/client_secrets"
CHAT_COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions"
EMBEDDINGS_URL = "https://api.openai.com/v1/embeddings"

MAX_TRANSCRIPT_ENTRIES = 3000
MAX_TRANSCRIPT_CHARS = 200_000

# Working persona until the name and personality decision is made.
ASSISTANT_INSTRUCTIONS = """You are a private personal assistant for the owner of \
Locklear Vineyard and Winery in North Carolina. You speak naturally and concisely, \
like a trusted chief of staff who also knows winemaking and vineyard operations. \
Keep spoken replies short unless asked for detail. If you are unsure, say so.

The owner saves notes from past conversations as memories. When they ask about \
anything that might be in them (past decisions, plans, commitments, open questions, \
people, preferences, "what did we say about..."), call search_memories before \
answering. Answer only from what it returns, mention when a memory is from (for \
example "on September 25th you decided..."), and if nothing relevant comes back, \
say you don't have that saved rather than guessing. You cannot yet save new \
memories by voice, set reminders, or take other actions; if asked, say that is \
coming in a later version."""

SEARCH_TOOL = {
    "type": "function",
    "name": "search_memories",
    "description": "Search the owner's saved memories by meaning. Use for questions about past "
                   "conversations, decisions, commitments, plans, open questions, or preferences.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What to look for, in plain words."},
            "category": {
                "type": "string",
                "enum": ["winery", "projects", "personal", "preferences"],
                "description": "Only set this if the owner clearly limits the question to one area.",
            },
        },
        "required": ["query"],
    },
}


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
- "category": where these notes belong: "winery", "projects", "personal", or "preferences"
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
            "tools": [SEARCH_TOOL],
            "tool_choice": "auto",
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


@assistant_bp.route("/library")
def library():
    return send_from_directory(assistant_bp.static_folder, "library.html")


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
        "category": raw.get("category") if raw.get("category") in CATEGORIES else "winery",
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



def embedding_model():
    return os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")


class EmbeddingError(Exception):
    pass


def embed(texts):
    """Return one embedding per text, or raise EmbeddingError with a readable reason."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise EmbeddingError("OPENAI_API_KEY is not configured")
    vectors = []
    for start in range(0, len(texts), 100):
        batch = texts[start:start + 100]
        try:
            resp = requests.post(
                EMBEDDINGS_URL,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": embedding_model(), "input": batch},
                timeout=30,
            )
        except requests.RequestException as exc:
            raise EmbeddingError("Could not reach the embedding service") from exc
        if not resp.ok:
            raise EmbeddingError(upstream_error_message(resp))
        try:
            data = sorted(resp.json()["data"], key=lambda d: d["index"])
            vectors.extend(d["embedding"] for d in data)
        except (ValueError, KeyError, TypeError) as exc:
            raise EmbeddingError("Embedding service returned an unreadable result") from exc
    if len(vectors) != len(texts):
        raise EmbeddingError("Embedding service returned the wrong number of results")
    return vectors


def embed_or_none(texts):
    """Embeddings for saving; on failure save anyway and let search backfill later."""
    try:
        return embed(texts)
    except EmbeddingError as exc:
        current_app.logger.warning("Saving memories without embeddings for now: %s", exc)
        return [None] * len(texts)


def store_or_error():
    """Return (store, None) or (None, error response)."""
    try:
        return get_store(), None
    except StorageNotConfigured:
        return None, (jsonify({"error": "Memory storage isn't set up yet (DATABASE_URL and MEMORY_ENCRYPTION_KEY)"}), 503)


def clean_memory(item):
    """Validate one memory from the page. Returns (memory, error message)."""
    if not isinstance(item, dict):
        return None, "Each memory must be an object"
    text = str(item.get("text") or "").strip()
    category = item.get("category")
    if not text:
        return None, "Memory text is empty"
    if len(text) > MAX_MEMORY_CHARS:
        return None, f"A memory can be at most {MAX_MEMORY_CHARS} characters"
    if category not in CATEGORIES:
        return None, f"Category must be one of: {', '.join(CATEGORIES)}"
    return {"text": text, "category": category}, None


def parse_session_start(value):
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def storage_failure(exc):
    if isinstance(exc, UnreadableMemory):
        current_app.logger.error("A stored memory could not be decrypted; MEMORY_ENCRYPTION_KEY may have changed")
        return jsonify({"error": "Saved memories can't be decrypted. Was MEMORY_ENCRYPTION_KEY changed?"}), 500
    current_app.logger.error("Memory storage error: %s", type(exc).__name__)
    return jsonify({"error": "Memory storage is unavailable right now"}), 503


@assistant_bp.route("/memories", methods=["GET"])
def list_memories():
    denied = check_access()
    if denied:
        return denied
    store, error = store_or_error()
    if error:
        return error
    category = request.args.get("category") or None
    if category and category not in CATEGORIES:
        return jsonify({"error": "Unknown category"}), 400
    try:
        return jsonify({"memories": store.list(category), "categories": list(CATEGORIES)})
    except Exception as exc:  # noqa: BLE001 - report storage problems without leaking details
        return storage_failure(exc)


@assistant_bp.route("/memories", methods=["POST"])
def save_memories():
    """Save the memories the owner approved on the review screen."""
    denied = check_access()
    if denied:
        return denied
    store, error = store_or_error()
    if error:
        return error
    body = request.get_json(silent=True) or {}
    items = body.get("memories")
    if not isinstance(items, list) or not items:
        return jsonify({"error": "Choose at least one memory to save"}), 400
    if len(items) > 100:
        return jsonify({"error": "Too many memories at once"}), 413
    cleaned = []
    for item in items:
        memory, problem = clean_memory(item)
        if problem:
            return jsonify({"error": problem}), 400
        cleaned.append(memory)
    for memory, vector in zip(cleaned, embed_or_none([m["text"] for m in cleaned])):
        memory["embedding"] = vector
    try:
        saved = store.add_many(
            cleaned,
            source="conversation",
            session_started_at=parse_session_start(body.get("session_started_at")),
            embedding_model=embedding_model(),
        )
    except Exception as exc:  # noqa: BLE001
        return storage_failure(exc)
    return jsonify({"memories": saved}), 201


@assistant_bp.route("/memories/<int:memory_id>", methods=["PATCH"])
def edit_memory(memory_id):
    denied = check_access()
    if denied:
        return denied
    store, error = store_or_error()
    if error:
        return error
    body = request.get_json(silent=True) or {}
    text = body.get("text")
    category = body.get("category")
    if text is None and category is None:
        return jsonify({"error": "Nothing to change"}), 400
    if text is not None:
        text = str(text).strip()
        if not text or len(text) > MAX_MEMORY_CHARS:
            return jsonify({"error": f"Memory text must be 1-{MAX_MEMORY_CHARS} characters"}), 400
    if category is not None and category not in CATEGORIES:
        return jsonify({"error": "Unknown category"}), 400
    vector = embed_or_none([text])[0] if text is not None else None
    try:
        memory = store.update(memory_id, text=text, category=category, embedding=vector, embedding_model=embedding_model())
        return jsonify({"memory": memory})
    except MemoryNotFound:
        return jsonify({"error": "Memory not found"}), 404
    except Exception as exc:  # noqa: BLE001
        return storage_failure(exc)


@assistant_bp.route("/memories/<int:memory_id>", methods=["DELETE"])
def delete_memory(memory_id):
    denied = check_access()
    if denied:
        return denied
    store, error = store_or_error()
    if error:
        return error
    try:
        store.delete(memory_id)
    except MemoryNotFound:
        return jsonify({"error": "Memory not found"}), 404
    except Exception as exc:  # noqa: BLE001
        return storage_failure(exc)
    return "", 204


@assistant_bp.route("/memories/export", methods=["GET"])
def export_memories():
    """Download every memory (decrypted) plus the audit log as JSON."""
    denied = check_access()
    if denied:
        return denied
    store, error = store_or_error()
    if error:
        return error
    try:
        payload = {
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "memories": store.list(),
            "audit": store.audit(limit=10000),
        }
    except Exception as exc:  # noqa: BLE001
        return storage_failure(exc)
    return Response(
        json.dumps(payload, indent=2),
        mimetype="application/json",
        headers={"Content-Disposition": "attachment; filename=assistant-memories.json"},
    )


@assistant_bp.route("/memories/search", methods=["POST"])
def search_memories():
    """Find memories by meaning. Also fingerprints any memories saved without one."""
    denied = check_access()
    if denied:
        return denied
    store, error = store_or_error()
    if error:
        return error
    body = request.get_json(silent=True) or {}
    query = str(body.get("query") or "").strip()
    category = body.get("category") or None
    if not query:
        return jsonify({"error": "Search for something"}), 400
    if len(query) > 1000:
        return jsonify({"error": "Search is too long"}), 400
    if category and category not in CATEGORIES:
        return jsonify({"error": "Unknown category"}), 400
    limit = body.get("limit")
    limit = limit if isinstance(limit, int) and 1 <= limit <= 20 else 6

    model = embedding_model()
    try:
        missing = store.missing_embeddings(model)
        if missing:
            vectors = embed([text for _, text in missing])
            store.set_embeddings([(memory_id, v) for (memory_id, _), v in zip(missing, vectors)], model)
        query_vector = embed([query])[0]
        results = store.search(query_vector, model, category=category, limit=limit)
    except EmbeddingError as exc:
        current_app.logger.error("Memory search embedding failed: %s", exc)
        return jsonify({"error": f"Search service unavailable: {exc}"}), 502
    except Exception as exc:  # noqa: BLE001
        return storage_failure(exc)
    return jsonify({"results": results})
