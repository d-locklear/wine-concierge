import os
import uuid
from unittest.mock import MagicMock, patch

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
        self.embeddings = {}

    def add_many(self, items, source, session_started_at=None, embedding_model=None):
        saved = []
        for item in items:
            item = dict(item)
            self.embeddings[self.next_id] = item.pop("embedding", None)
            row = {"id": self.next_id, "source": source, "session_started_at": session_started_at and session_started_at.isoformat(),
                   "created_at": "2026-09-25T20:00:00+00:00", "updated_at": "2026-09-25T20:00:00+00:00", **item}
            self.rows[self.next_id] = row
            self.audit_log.append((self.next_id, "created"))
            self.next_id += 1
            saved.append(row)
        return saved

    def list(self, category=None):
        return [r for r in reversed(self.rows.values()) if not category or r["category"] == category]

    def update(self, memory_id, text=None, category=None, embedding=None, embedding_model=None):
        if memory_id not in self.rows:
            raise MemoryNotFound()
        if text is not None:
            self.embeddings[memory_id] = embedding
        row = self.rows[memory_id]
        row.update({k: v for k, v in (("text", text), ("category", category)) if v is not None})
        return row

    def delete(self, memory_id):
        if self.rows.pop(memory_id, None) is None:
            raise MemoryNotFound()

    def audit(self, limit=200):
        return [{"memory_id": m, "action": a} for m, a in self.audit_log][:limit]

    def missing_embeddings(self, embedding_model, limit=500):
        return [(i, r["text"]) for i, r in self.rows.items() if self.embeddings.get(i) is None][:limit]

    def set_embeddings(self, pairs, embedding_model):
        self.embeddings.update(dict(pairs))

    def search(self, query_vector, embedding_model, category=None, limit=6, min_score=0.2):
        scored = []
        for i, row in self.rows.items():
            vec = self.embeddings.get(i)
            if vec is None or (category and row["category"] != category):
                continue
            score = sum(a * b for a, b in zip(vec, query_vector))
            if score >= min_score:
                scored.append({**row, "score": score})
        return sorted(scored, key=lambda r: r["score"], reverse=True)[:limit]


# Fake embeddings: one dimension per keyword, normalized, so similarity is predictable.
KEYWORDS = ["cork", "bottl", "mom", "tasting"]


def fake_vector(text):
    vec = [float(k in text.lower()) for k in KEYWORDS] + [0.01]
    norm = sum(v * v for v in vec) ** 0.5
    return [v / norm for v in vec]


def fake_openai(calls=None, fail=False):
    """Stand-in for requests.post that answers the embeddings endpoint."""
    def post(url, headers=None, json=None, timeout=None):
        if calls is not None:
            calls.append((url, json))
        resp = MagicMock()
        if fail:
            resp.ok, resp.status_code = False, 429
            resp.json.return_value = {"error": {"message": "You have no credits remaining"}}
            return resp
        assert url.endswith("/embeddings")
        resp.ok = True
        resp.json.return_value = {"data": [{"index": i, "embedding": fake_vector(t)} for i, t in enumerate(json["input"])]}
        return resp
    return post


@pytest.fixture(autouse=True)
def openai(monkeypatch):
    """Every test talks to the fake embeddings service unless it patches its own."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real-secret")
    calls = []
    monkeypatch.setattr("assistant.routes.requests.post", fake_openai(calls))
    return calls


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


def test_saving_fingerprints_memories(client, store, openai):
    client.post("/assistant/memories", headers=AUTH, json={"memories": [{"text": "Order corks", "category": "winery"}]})
    assert openai[0][0].endswith("/embeddings")
    assert openai[0][1]["input"] == ["Order corks"]
    assert store.embeddings[1] == fake_vector("Order corks")


def test_saving_still_works_when_fingerprinting_fails(client, store):
    with patch("assistant.routes.requests.post", side_effect=fake_openai(fail=True)):
        resp = client.post("/assistant/memories", headers=AUTH, json={"memories": [{"text": "Order corks", "category": "winery"}]})
    assert resp.status_code == 201
    assert store.embeddings[1] is None


def test_editing_text_refreshes_fingerprint(client, store):
    store.add_many([{"text": "Order corks", "category": "winery", "embedding": fake_vector("corks")}], source="conversation")
    client.patch("/assistant/memories/1", headers=AUTH, json={"text": "Call Mom"})
    assert store.embeddings[1] == fake_vector("Call Mom")


def test_search_ranks_by_meaning_and_backfills(client, store, openai):
    store.add_many([
        {"text": "Decided: bottle the Muscadine Friday", "category": "winery", "embedding": fake_vector("bottle")},
        {"text": "Open question: enough corks?", "category": "winery"},  # saved without a fingerprint
        {"text": "Call Mom on Sunday", "category": "personal", "embedding": fake_vector("mom")},
    ], source="conversation")
    resp = client.post("/assistant/memories/search", headers=AUTH, json={"query": "cork supply"})
    assert resp.status_code == 200
    results = resp.get_json()["results"]
    assert [r["text"] for r in results] == ["Open question: enough corks?"]
    assert store.embeddings[2] is not None
    # One call backfills the unfingerprinted memory, one embeds the query.
    assert [c[1]["input"] for c in openai] == [["Open question: enough corks?"], ["cork supply"]]


def test_search_respects_category(client, store):
    store.add_many([
        {"text": "Mom likes the tasting room", "category": "personal", "embedding": fake_vector("mom tasting")},
        {"text": "Tasting room hours", "category": "winery", "embedding": fake_vector("tasting")},
    ], source="conversation")
    resp = client.post("/assistant/memories/search", headers=AUTH, json={"query": "tasting", "category": "winery"})
    assert [r["text"] for r in resp.get_json()["results"]] == ["Tasting room hours"]


@pytest.mark.parametrize("body, status", [
    ({}, 400),
    ({"query": "   "}, 400),
    ({"query": "x" * 1001}, 400),
    ({"query": "corks", "category": "work"}, 400),
])
def test_search_validation(client, store, body, status):
    assert client.post("/assistant/memories/search", headers=AUTH, json=body).status_code == status


def test_search_requires_access_code(client, store):
    assert client.post("/assistant/memories/search", json={"query": "corks"}).status_code == 401


def test_search_reports_embedding_failure(client, store):
    with patch("assistant.routes.requests.post", side_effect=fake_openai(fail=True)):
        resp = client.post("/assistant/memories/search", headers=AUTH, json={"query": "corks"})
    assert resp.status_code == 502
    assert "no credits" in resp.get_json()["error"]


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


@needs_db
def test_postgres_search_with_encrypted_embeddings(pg_store):
    import psycopg
    store, url = pg_store
    saved = store.add_many([
        {"text": "Decided: bottle Friday", "category": "winery", "embedding": fake_vector("bottle")},
        {"text": "Enough corks?", "category": "winery"},
        {"text": "Call Mom", "category": "personal", "embedding": fake_vector("mom")},
    ], source="conversation", embedding_model="m1")

    assert [text for _, text in store.missing_embeddings("m1")] == ["Enough corks?"]
    # A different model means everything needs new fingerprints.
    assert len(store.missing_embeddings("m2")) == 3
    store.set_embeddings([(saved[1]["id"], fake_vector("corks"))], "m1")
    assert store.missing_embeddings("m1") == []

    with psycopg.connect(url) as conn:
        blobs = [bytes(r[0]) for r in conn.execute("SELECT embedding_encrypted FROM memories").fetchall()]
    assert all(blob.startswith(b"gAAAA") for blob in blobs)  # Fernet tokens, not raw floats

    results = store.search(fake_vector("corks"), "m1")
    assert [r["text"] for r in results] == ["Enough corks?"]
    assert results[0]["score"] > 0.9
    assert store.search(fake_vector("mom"), "m1", category="winery") == []

    # Editing the text without a new fingerprint queues it for backfill; category-only edits keep it.
    store.update(saved[2]["id"], category="projects")
    assert store.missing_embeddings("m1") == []
    store.update(saved[2]["id"], text="Call Dad")
    assert [text for _, text in store.missing_embeddings("m1")] == ["Call Dad"]
    store.update(saved[0]["id"], text="Bottle Saturday", embedding=fake_vector("bottle"), embedding_model="m1")
    assert [r["text"] for r in store.search(fake_vector("bottle"), "m1")] == ["Bottle Saturday"]
