"""Encrypted long-term memory storage in Postgres.

Memory text is encrypted before it reaches the database, so the database alone
is unreadable. Embeddings (used for search by meaning) are encrypted too, and
similarity is computed in the app after decrypting. The audit log records what
happened to each memory and when, never the memory text itself.

Sessions are the automatic history of past conversations: the transcript text
and notes (never audio), encrypted the same way and deleted when they expire.
"""

import base64
import hashlib
import json
import os
import threading

import numpy as np
import psycopg
from cryptography.fernet import Fernet, InvalidToken
from psycopg.rows import dict_row

CATEGORIES = ("winery", "projects", "personal", "preferences")
MAX_MEMORY_CHARS = 4000

SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id BIGSERIAL PRIMARY KEY,
    category TEXT NOT NULL,
    text_encrypted BYTEA NOT NULL,
    source TEXT NOT NULL,
    session_started_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS memories_category_created_idx ON memories (category, created_at DESC);
ALTER TABLE memories ADD COLUMN IF NOT EXISTS embedding_encrypted BYTEA;
ALTER TABLE memories ADD COLUMN IF NOT EXISTS embedding_model TEXT;
CREATE TABLE IF NOT EXISTS sessions (
    id BIGSERIAL PRIMARY KEY,
    started_at TIMESTAMPTZ,
    ended_at TIMESTAMPTZ,
    notes_encrypted BYTEA,
    transcript_encrypted BYTEA NOT NULL,
    embedding_encrypted BYTEA,
    embedding_model TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS sessions_expires_idx ON sessions (expires_at);
CREATE TABLE IF NOT EXISTS memory_audit (
    id BIGSERIAL PRIMARY KEY,
    memory_id BIGINT NOT NULL,
    action TEXT NOT NULL,
    at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE memory_audit ADD COLUMN IF NOT EXISTS subject TEXT NOT NULL DEFAULT 'memory';
"""


class StorageNotConfigured(Exception):
    pass


class MemoryNotFound(Exception):
    pass


class UnreadableMemory(Exception):
    """Stored text can't be decrypted, usually because the encryption key changed."""


def fernet_from_secret(secret):
    # Any long random string works (e.g. Render's "Generate" value); derive a Fernet key from it.
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest()))


class MemoryStore:
    def __init__(self, database_url, secret):
        self.database_url = database_url
        self.fernet = fernet_from_secret(secret)
        self._schema_ready = False
        self._lock = threading.Lock()

    def _connect(self):
        conn = psycopg.connect(self.database_url, row_factory=dict_row)
        if not self._schema_ready:
            with self._lock:
                if not self._schema_ready:
                    conn.execute(SCHEMA)
                    conn.commit()
                    self._schema_ready = True
        return conn

    def _encrypt(self, text):
        return self.fernet.encrypt(text.encode())

    def _decrypt(self, blob):
        try:
            return self.fernet.decrypt(bytes(blob)).decode()
        except InvalidToken as exc:
            raise UnreadableMemory() from exc

    def _row(self, row):
        return {
            "id": row["id"],
            "category": row["category"],
            "text": self._decrypt(row["text_encrypted"]),
            "source": row["source"],
            "session_started_at": iso(row["session_started_at"]),
            "created_at": iso(row["created_at"]),
            "updated_at": iso(row["updated_at"]),
        }

    def _encrypt_vector(self, vector):
        return self.fernet.encrypt(np.asarray(vector, dtype=np.float32).tobytes())

    def _decrypt_vector(self, blob):
        try:
            return np.frombuffer(self.fernet.decrypt(bytes(blob)), dtype=np.float32)
        except InvalidToken as exc:
            raise UnreadableMemory() from exc

    def add_many(self, items, source, session_started_at=None, embedding_model=None):
        """items: list of {"text", "category", optional "embedding"} already validated."""
        saved = []
        with self._connect() as conn:
            for item in items:
                embedding = item.get("embedding")
                row = conn.execute(
                    """INSERT INTO memories
                         (category, text_encrypted, source, session_started_at, embedding_encrypted, embedding_model)
                       VALUES (%s, %s, %s, %s, %s, %s) RETURNING *""",
                    (
                        item["category"], self._encrypt(item["text"]), source, session_started_at,
                        self._encrypt_vector(embedding) if embedding is not None else None,
                        embedding_model if embedding is not None else None,
                    ),
                ).fetchone()
                conn.execute(
                    "INSERT INTO memory_audit (memory_id, action) VALUES (%s, 'created')", (row["id"],)
                )
                saved.append(self._row(row))
        return saved

    def list(self, category=None):
        with self._connect() as conn:
            if category:
                rows = conn.execute(
                    "SELECT * FROM memories WHERE category = %s ORDER BY created_at DESC, id DESC",
                    (category,),
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM memories ORDER BY created_at DESC, id DESC").fetchall()
        return [self._row(r) for r in rows]

    def update(self, memory_id, text=None, category=None, embedding=None, embedding_model=None):
        """Changing the text replaces its embedding (or clears it for a later backfill)."""
        with self._connect() as conn:
            row = conn.execute(
                """UPDATE memories
                   SET text_encrypted = COALESCE(%s, text_encrypted),
                       category = COALESCE(%s, category),
                       embedding_encrypted = CASE WHEN %s THEN %s ELSE embedding_encrypted END,
                       embedding_model = CASE WHEN %s THEN %s ELSE embedding_model END,
                       updated_at = now()
                   WHERE id = %s RETURNING *""",
                (
                    self._encrypt(text) if text is not None else None,
                    category,
                    text is not None, self._encrypt_vector(embedding) if embedding is not None else None,
                    text is not None, embedding_model if embedding is not None else None,
                    memory_id,
                ),
            ).fetchone()
            if not row:
                raise MemoryNotFound()
            conn.execute("INSERT INTO memory_audit (memory_id, action) VALUES (%s, 'edited')", (memory_id,))
        return self._row(row)

    def delete(self, memory_id):
        with self._connect() as conn:
            deleted = conn.execute("DELETE FROM memories WHERE id = %s RETURNING id", (memory_id,)).fetchone()
            if not deleted:
                raise MemoryNotFound()
            conn.execute("INSERT INTO memory_audit (memory_id, action) VALUES (%s, 'deleted')", (memory_id,))

    def missing_embeddings(self, embedding_model, limit=500):
        """Memories with no embedding (or one from a different model): [(id, text)]."""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT id, text_encrypted FROM memories
                   WHERE embedding_encrypted IS NULL OR embedding_model IS DISTINCT FROM %s
                   ORDER BY id LIMIT %s""",
                (embedding_model, limit),
            ).fetchall()
        return [(r["id"], self._decrypt(r["text_encrypted"])) for r in rows]

    def set_embeddings(self, pairs, embedding_model):
        """pairs: [(memory_id, vector)]. Not audited: the memory itself doesn't change."""
        with self._connect() as conn:
            for memory_id, vector in pairs:
                conn.execute(
                    "UPDATE memories SET embedding_encrypted = %s, embedding_model = %s WHERE id = %s",
                    (self._encrypt_vector(vector), embedding_model, memory_id),
                )

    def search(self, query_vector, embedding_model, category=None, limit=6, min_score=0.2, include_sessions=False):
        """Rank memories (and optionally past sessions) by cosine similarity to query_vector.

        Results carry "type" ("memory" or "session") and "score". Sessions have no
        category, so they're left out when a category is given.
        """
        with self._connect() as conn:
            sql = "SELECT * FROM memories WHERE embedding_model = %s AND embedding_encrypted IS NOT NULL"
            params = [embedding_model]
            if category:
                sql += " AND category = %s"
                params.append(category)
            candidates = [("memory", r) for r in conn.execute(sql, params).fetchall()]
            if include_sessions and not category:
                self._purge_expired(conn)
                candidates += [("session", r) for r in conn.execute(
                    "SELECT * FROM sessions WHERE embedding_model = %s AND embedding_encrypted IS NOT NULL",
                    (embedding_model,),
                ).fetchall()]
        if not candidates:
            return []
        query = np.asarray(query_vector, dtype=np.float32)
        matrix = np.stack([self._decrypt_vector(r["embedding_encrypted"]) for _, r in candidates])
        norms = np.linalg.norm(matrix, axis=1) * (np.linalg.norm(query) or 1.0)
        scores = matrix @ query / np.where(norms == 0, 1.0, norms)
        ranked = sorted(zip(scores.tolist(), candidates), key=lambda pair: pair[0], reverse=True)
        results = []
        for score, (kind, row) in ranked[:limit]:
            if score < min_score:
                continue
            item = self._row(row) if kind == "memory" else self._session_summary(row)
            results.append({**item, "type": kind, "score": round(score, 3)})
        return results

    # --- Sessions: automatic, expiring history of past conversations ---

    def _purge_expired(self, conn):
        expired = conn.execute("DELETE FROM sessions WHERE expires_at <= now() RETURNING id").fetchall()
        for row in expired:
            conn.execute(
                "INSERT INTO memory_audit (memory_id, action, subject) VALUES (%s, 'expired', 'session')", (row["id"],)
            )

    def _decrypt_json(self, blob):
        return json.loads(self._decrypt(blob)) if blob is not None else None

    def _session_summary(self, row):
        notes = self._decrypt_json(row["notes_encrypted"])
        return {
            "id": row["id"],
            "started_at": iso(row["started_at"]),
            "ended_at": iso(row["ended_at"]),
            "created_at": iso(row["created_at"]),
            "expires_at": iso(row["expires_at"]),
            "summary": (notes or {}).get("summary") or "",
            "has_notes": notes is not None,
        }

    def add_session(self, transcript, notes=None, started_at=None, ended_at=None,
                    embedding=None, embedding_model=None, retention_days=90):
        with self._connect() as conn:
            self._purge_expired(conn)
            row = conn.execute(
                """INSERT INTO sessions
                     (started_at, ended_at, notes_encrypted, transcript_encrypted,
                      embedding_encrypted, embedding_model, expires_at)
                   VALUES (%s, %s, %s, %s, %s, %s, now() + make_interval(days => %s)) RETURNING *""",
                (
                    started_at, ended_at,
                    self._encrypt(json.dumps(notes)) if notes is not None else None,
                    self._encrypt(transcript),
                    self._encrypt_vector(embedding) if embedding is not None else None,
                    embedding_model if embedding is not None else None,
                    retention_days,
                ),
            ).fetchone()
            conn.execute(
                "INSERT INTO memory_audit (memory_id, action, subject) VALUES (%s, 'created', 'session')", (row["id"],)
            )
        return self._session_summary(row)

    def list_sessions(self):
        with self._connect() as conn:
            self._purge_expired(conn)
            rows = conn.execute("SELECT * FROM sessions ORDER BY COALESCE(started_at, created_at) DESC, id DESC").fetchall()
        return [self._session_summary(r) for r in rows]

    def get_session(self, session_id):
        with self._connect() as conn:
            self._purge_expired(conn)
            row = conn.execute("SELECT * FROM sessions WHERE id = %s", (session_id,)).fetchone()
        if not row:
            raise MemoryNotFound()
        return {
            **self._session_summary(row),
            "notes": self._decrypt_json(row["notes_encrypted"]),
            "transcript": self._decrypt(row["transcript_encrypted"]),
        }

    def delete_session(self, session_id):
        with self._connect() as conn:
            deleted = conn.execute("DELETE FROM sessions WHERE id = %s RETURNING id", (session_id,)).fetchone()
            if not deleted:
                raise MemoryNotFound()
            conn.execute(
                "INSERT INTO memory_audit (memory_id, action, subject) VALUES (%s, 'deleted', 'session')", (session_id,)
            )

    def missing_session_embeddings(self, embedding_model, limit=200):
        """Sessions needing an embedding: [(id, notes or None, transcript)]."""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT id, notes_encrypted, transcript_encrypted FROM sessions
                   WHERE expires_at > now()
                     AND (embedding_encrypted IS NULL OR embedding_model IS DISTINCT FROM %s)
                   ORDER BY id LIMIT %s""",
                (embedding_model, limit),
            ).fetchall()
        return [(r["id"], self._decrypt_json(r["notes_encrypted"]), self._decrypt(r["transcript_encrypted"])) for r in rows]

    def set_session_embeddings(self, pairs, embedding_model):
        with self._connect() as conn:
            for session_id, vector in pairs:
                conn.execute(
                    "UPDATE sessions SET embedding_encrypted = %s, embedding_model = %s WHERE id = %s",
                    (self._encrypt_vector(vector), embedding_model, session_id),
                )

    def export_sessions(self):
        with self._connect() as conn:
            self._purge_expired(conn)
            ids = [r["id"] for r in conn.execute("SELECT id FROM sessions ORDER BY id").fetchall()]
        return [self.get_session(i) for i in ids]

    def audit(self, limit=200):
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT memory_id, action, subject, at FROM memory_audit ORDER BY at DESC, id DESC LIMIT %s", (limit,)
            ).fetchall()
        return [
            {"subject": r["subject"], "id": r["memory_id"], "memory_id": r["memory_id"], "action": r["action"], "at": iso(r["at"])}
            for r in rows
        ]


def iso(value):
    return value.isoformat() if value else None


_stores = {}
_stores_lock = threading.Lock()


def get_store():
    """Return the configured store, or raise StorageNotConfigured."""
    database_url = os.getenv("DATABASE_URL")
    secret = os.getenv("MEMORY_ENCRYPTION_KEY")
    if not database_url or not secret:
        raise StorageNotConfigured()
    key = (database_url, secret)
    with _stores_lock:
        if key not in _stores:
            _stores.clear()
            _stores[key] = MemoryStore(database_url, secret)
        return _stores[key]
