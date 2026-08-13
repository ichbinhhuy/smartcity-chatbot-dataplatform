"""Unit test cho app/session/ — InMemorySessionStore và RedisSessionStore.

RedisSessionStore dùng `fakeredis.FakeRedis` (giả lập in-process) thay vì
skip-if-no-Redis: skip sẽ âm thầm không assert gì trên máy/CI không có Redis
cài sẵn, che mất regression thay vì bắt được nó.
"""

from __future__ import annotations

import time

import fakeredis
import pytest
import redis as redis_lib

from app.session.memory_store import InMemorySessionStore
from app.session.redis_store import RedisSessionStore


class TestInMemorySessionStore:
    def test_get_missing_session_returns_empty(self):
        store = InMemorySessionStore()
        assert store.get("khong-ton-tai") == []

    def test_save_then_get_roundtrip(self):
        store = InMemorySessionStore()
        messages = [{"role": "user", "content": "hello"}]
        store.save("s1", messages)
        assert store.get("s1") == messages

    def test_save_overwrites_not_appends(self):
        store = InMemorySessionStore()
        store.save("s1", [{"role": "user", "content": "first"}])
        store.save("s1", [{"role": "user", "content": "second"}])
        result = store.get("s1")
        assert len(result) == 1
        assert result[0]["content"] == "second"

    def test_negative_ttl_expires_immediately(self):
        store = InMemorySessionStore()
        store.save("s1", [{"role": "user", "content": "hi"}], ttl_seconds=-1)
        assert store.get("s1") == []

    def test_delete_removes_session(self):
        store = InMemorySessionStore()
        store.save("s1", [{"role": "user", "content": "hi"}])
        store.delete("s1")
        assert store.get("s1") == []

    def test_delete_missing_session_is_noop(self):
        store = InMemorySessionStore()
        store.delete("khong-ton-tai")  # không raise

    def test_clarification_streak_missing_session_returns_zero(self):
        store = InMemorySessionStore()
        assert store.get_clarification_streak("khong-ton-tai") == 0

    def test_clarification_streak_roundtrip(self):
        store = InMemorySessionStore()
        store.set_clarification_streak("s1", 2)
        assert store.get_clarification_streak("s1") == 2

    def test_clarification_streak_negative_ttl_expires_immediately(self):
        store = InMemorySessionStore()
        store.set_clarification_streak("s1", 2, ttl_seconds=-1)
        assert store.get_clarification_streak("s1") == 0

    def test_delete_also_clears_clarification_streak(self):
        store = InMemorySessionStore()
        store.set_clarification_streak("s1", 2)
        store.delete("s1")
        assert store.get_clarification_streak("s1") == 0


class TestRedisSessionStore:
    @pytest.fixture
    def fake_client(self):
        return fakeredis.FakeRedis(decode_responses=True)

    @pytest.fixture
    def store(self, fake_client):
        return RedisSessionStore(redis_url="redis://unused", ttl_seconds=60, client=fake_client)

    def test_get_missing_session_returns_empty(self, store):
        assert store.get("khong-ton-tai") == []

    def test_save_then_get_roundtrip(self, store):
        messages = [{"role": "user", "content": "hello"}]
        store.save("s1", messages)
        assert store.get("s1") == messages

    def test_save_overwrites_not_appends(self, store):
        store.save("s1", [{"role": "user", "content": "first"}])
        store.save("s1", [{"role": "user", "content": "second"}])
        result = store.get("s1")
        assert len(result) == 1
        assert result[0]["content"] == "second"

    def test_save_sets_ttl(self, store, fake_client):
        store.save("s1", [{"role": "user", "content": "hi"}], ttl_seconds=120)
        ttl = fake_client.ttl(store._key("s1"))
        assert 0 < ttl <= 120

    def test_delete_removes_session(self, store):
        store.save("s1", [{"role": "user", "content": "hi"}])
        store.delete("s1")
        assert store.get("s1") == []

    def test_get_degrades_to_empty_on_redis_error(self, store, monkeypatch):
        def _raise(*a, **kw):
            raise redis_lib.exceptions.ConnectionError("boom")

        monkeypatch.setattr(store._client, "get", _raise)
        assert store.get("s1") == []  # không raise

    def test_save_degrades_to_noop_on_redis_error(self, store, monkeypatch):
        def _raise(*a, **kw):
            raise redis_lib.exceptions.ConnectionError("boom")

        monkeypatch.setattr(store._client, "setex", _raise)
        store.save("s1", [{"role": "user", "content": "hi"}])  # không raise

    def test_delete_degrades_to_noop_on_redis_error(self, store, monkeypatch):
        def _raise(*a, **kw):
            raise redis_lib.exceptions.ConnectionError("boom")

        monkeypatch.setattr(store._client, "delete", _raise)
        store.delete("s1")  # không raise

    def test_get_degrades_to_empty_on_corrupt_payload(self, store, fake_client):
        fake_client.set(store._key("s1"), "khong-phai-json{{{")
        assert store.get("s1") == []

    def test_clarification_streak_missing_session_returns_zero(self, store):
        assert store.get_clarification_streak("khong-ton-tai") == 0

    def test_clarification_streak_roundtrip(self, store):
        store.set_clarification_streak("s1", 2)
        assert store.get_clarification_streak("s1") == 2

    def test_clarification_streak_sets_ttl(self, store, fake_client):
        store.set_clarification_streak("s1", 1, ttl_seconds=120)
        ttl = fake_client.ttl(store._streak_key("s1"))
        assert 0 < ttl <= 120

    def test_delete_also_clears_clarification_streak(self, store):
        store.set_clarification_streak("s1", 2)
        store.delete("s1")
        assert store.get_clarification_streak("s1") == 0

    def test_clarification_streak_degrades_to_zero_on_redis_error(self, store, monkeypatch):
        def _raise(*a, **kw):
            raise redis_lib.exceptions.ConnectionError("boom")

        monkeypatch.setattr(store._client, "get", _raise)
        assert store.get_clarification_streak("s1") == 0  # không raise

    def test_set_clarification_streak_degrades_to_noop_on_redis_error(self, store, monkeypatch):
        def _raise(*a, **kw):
            raise redis_lib.exceptions.ConnectionError("boom")

        monkeypatch.setattr(store._client, "setex", _raise)
        store.set_clarification_streak("s1", 1)  # không raise
