import os
import uuid

import pytest
from flask import Flask

from assistant import assistant_bp, routes
from assistant.memory_store import MemoryNotFound, MemoryStore, StorageNotConfigured, UnreadableMemory

AUTH = {"X-Access-Code": "letmein"}


@pytest.fixture(autouse=True)
def access_code(monkeypatch):
    monkeypatch.setenv("ASSISTANT_ACCESS_CODE", "letmein")


@pytest.fixture
def client():
    app = Flask(__name__)
    app.register_blueprint(assistant_bp)
    return app.test_client()


class FakeStore:
    def __init__(self):
        self.rows = {}
        self.next_id = 1
        self.audit_log = []

    def add_many(self, items, source, session_started_at=None):
        saved = []
        for item in items:
            row = {"id": self.next_id, "source": source, "session_started_at": session_started_at and session_started_at.isoformat(),
                   "created_at": "2026-09-25T20:00:00+00:00", "updated_at": "2026-09-25T20:00:00+00:00", **item}
            self.rows[self.next_id] = row
            self.audit_log.append((self.next_id, "created"))
            self.next_id += 1
            saved.append(row)
        return saved

    def list(self, category=None):
        return [r for r in reversed(self.rows.values()) if not category or r["category"] == category]

    def update(self, memory_id, text=None, category=None):
        if memory_id not in self.rows:
            raise MemoryNotFound()
        row = self.rows[memory_id]
        row.update({k: v for k, v in (("text", text), ("category", category)) if v is not None})
        return row

    def delete(self, memory_id):
        if self.rows.pop(memory_id, None) is None:
            raise MemoryNotFound()

    def audit(self, limit=200):
        return [{"memory_id": m, "action": a} for m, a in self.audit_log][:limit]


@pytest.fixture
def store(monkeypatch):
    fake = FakeStore()
    monkeypatch.setattr(routes, "get_store", lambda: fake)
    return fake


def test_memory_routes_require_access_code(client, store):
    assert client.get("/assistant/memories").status_code == 401
    assert client.post("/assistant/memories", json={"memories": []}).status_code == 401
    assert client.patch("/assistant/memories/1", json={"text": "x"}).status_code == 401
    assert client.delete("/assistant/memories/1").status_code == 401
    assert client.get("/assistant/memories/export").status_code == 401


def test_unconfigured_storage_returns_503(client, monkeypatch):
    def not_configured():
        raise StorageNotConfigured()
    monkeypatch.setattr(routes, "get_store", not_configured)
    resp = client.get("/assistant/memories", headers=AUTH)
    assert resp.status_code == 503
    assert "DATABASE_URL" in resp.get_json()["error"]


def test_save_list_edit_delete_flow(client, store):
    resp = client.post("/assistant/memories", headers=AUTH, json={
        "memories": [
            {"text": "  Bottle Muscadine Friday ", "category": "winery"},
            {"text": "Prefers morning meetings", "category": "preferences"},
        ],
        "session_started_at": "2026-09-25T19:00:00.000Z",
    })
    assert resp.status_code == 201
    saved = resp.get_json()["memories"]
    assert saved[0]["text"] == "Bottle Muscadine Friday"
    assert saved[0]["source"] == "conversation"
    assert saved[0]["session_started_at"].startswith("2026-09-25T19:00:00")

    winery = client.get("/assistant/memories?category=winery", headers=AUTH).get_json()["memories"]
    assert [m["text"] for m in winery] == ["Bottle Muscadine Friday"]

    edited = client.patch(f"/assistant/memories/{saved[0]['id']}", headers=AUTH, json={"category": "projects"})
    assert edited.get_json()["memory"]["category"] == "projects"

    assert client.delete(f"/assistant/memories/{saved[1]['id']}", headers=AUTH).status_code == 204
    assert client.delete(f"/assistant/memories/{saved[1]['id']}", headers=AUTH).status_code == 404
    assert len(client.get("/assistant/memories", headers=AUTH).get_json()["memories"]) == 1


@pytest.mark.parametrize("memories", [
    [],
    [{"text": "", "category": "winery"}],
    [{"text": "ok", "category": "work"}],
    [{"text": "x" * 4001, "category": "winery"}],
    ["not an object"],
])
def test_save_rejects_bad_memories(client, store, memories):
    resp = client.post("/assistant/memories", headers=AUTH, json={"memories": memories})
    assert resp.status_code == 400
    assert store.rows == {}


def test_edit_validation(client, store):
    store.add_many([{"text": "a", "category": "winery"}], source="conversation")
    assert client.patch("/assistant/memories/1", headers=AUTH, json={}).status_code == 400
    assert client.patch("/assistant/memories/1", headers=AUTH, json={"text": "  "}).status_code == 400
    assert client.patch("/assistant/memories/1", headers=AUTH, json={"category": "nope"}).status_code == 400
    assert client.patch("/assistant/memories/99", headers=AUTH, json={"text": "b"}).status_code == 404


def test_list_rejects_unknown_category(client, store):
    assert client.get("/assistant/memories?category=nope", headers=AUTH).status_code == 400


def test_export_includes_memories_and_audit(client, store):
    store.add_many([{"text": "a", "category": "winery"}], source="conversation")
    resp = client.get("/assistant/memories/export", headers=AUTH)
    assert resp.status_code == 200
    assert "attachment" in resp.headers["Content-Disposition"]
    body = resp.get_json()
    assert body["memories"][0]["text"] == "a"
    assert body["audit"] == [{"memory_id": 1, "action": "created"}]


def test_undecryptable_memory_reports_key_problem(client, monkeypatch):
    class BrokenStore(FakeStore):
        def list(self, category=None):
            raise UnreadableMemory()
    monkeypatch.setattr(routes, "get_store", BrokenStore)
    resp = client.get("/assistant/memories", headers=AUTH)
    assert resp.status_code == 500
    assert "MEMORY_ENCRYPTION_KEY" in resp.get_json()["error"]


def test_library_page_served(client):
    resp = client.get("/assistant/library")
    assert resp.status_code == 200
    assert b"Export all memories" in resp.data


# --- Real Postgres (set TEST_DATABASE_URL to run) ---

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
needs_db = pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL not set")


@pytest.fixture
def pg_store():
    import psycopg
    schema = f"test_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
        conn.execute(f"CREATE SCHEMA {schema}")
    url = f"{TEST_DATABASE_URL}?options=-csearch_path%3D{schema}"
    yield MemoryStore(url, "a-long-random-test-secret"), url
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
        conn.execute(f"DROP SCHEMA {schema} CASCADE")


@needs_db
def test_postgres_store_round_trip_is_encrypted_and_audited(pg_store):
    import psycopg
    store, url = pg_store
    saved = store.add_many(
        [{"text": "Secret blend ratio 60/40", "category": "winery"}, {"text": "Call Mom Sunday", "category": "personal"}],
        source="conversation",
    )
    assert [m["text"] for m in store.list()] == ["Call Mom Sunday", "Secret blend ratio 60/40"]
    assert [m["text"] for m in store.list("winery")] == ["Secret blend ratio 60/40"]

    with psycopg.connect(url) as conn:
        raw = conn.execute("SELECT text_encrypted FROM memories").fetchall()
    assert all(b"Secret" not in bytes(r[0]) and b"Mom" not in bytes(r[0]) for r in raw)

    updated = store.update(saved[0]["id"], text="Blend ratio 55/45")
    assert updated["text"] == "Blend ratio 55/45" and updated["category"] == "winery"
    store.delete(saved[1]["id"])
    with pytest.raises(MemoryNotFound):
        store.delete(saved[1]["id"])
    with pytest.raises(MemoryNotFound):
        store.update(9999, text="x")

    actions = [(a["memory_id"], a["action"]) for a in store.audit()]
    assert actions == [(saved[1]["id"], "deleted"), (saved[0]["id"], "edited"),
                       (saved[1]["id"], "created"), (saved[0]["id"], "created")]


@needs_db
def test_postgres_store_wrong_key_is_unreadable(pg_store):
    store, url = pg_store
    store.add_many([{"text": "hello", "category": "winery"}], source="conversation")
    with pytest.raises(UnreadableMemory):
        MemoryStore(url, "a-different-secret").list()
