"""SessionStore backend mặc định — dict trong RAM, không cần hạ tầng ngoài.

An toàn cho CLI (`python -m app.main`) và unit test (không cần Redis chạy
nền). Dùng khi `SESSION_STORE_BACKEND` không set hoặc = "memory".
"""

from __future__ import annotations

import threading
import time
from typing import Any


class InMemorySessionStore:
    """Session store trong RAM. Chỉ dùng đúng khi service chạy 1 process duy
    nhất — nhiều worker/replica sẽ có dict riêng biệt, session không chia sẻ
    được (xem SessionStore docstring / factory.py)."""

    def __init__(self, ttl_seconds: int = 1800) -> None:
        self._default_ttl = ttl_seconds
        self._data: dict[str, tuple[list[dict[str, Any]], float]] = {}
        self._streaks: dict[str, tuple[int, float]] = {}
        self._last_query: dict[str, tuple[dict[str, Any], float]] = {}
        # Starlette chạy route handler (def, không async def) trong threadpool
        # -> dict này có thể bị nhiều request đụng vào đồng thời.
        self._lock = threading.Lock()

    def get(self, session_id: str) -> list[dict[str, Any]]:
        with self._lock:
            entry = self._data.get(session_id)
            if entry is None:
                return []
            messages, expires_at = entry
            if time.time() >= expires_at:
                del self._data[session_id]
                return []
            return list(messages)

    def save(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
        ttl_seconds: int | None = None,
    ) -> None:
        ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl
        with self._lock:
            self._data[session_id] = (list(messages), time.time() + ttl)

    def delete(self, session_id: str) -> None:
        with self._lock:
            self._data.pop(session_id, None)
            self._streaks.pop(session_id, None)
            self._last_query.pop(session_id, None)

    def get_clarification_streak(self, session_id: str) -> int:
        with self._lock:
            entry = self._streaks.get(session_id)
            if entry is None:
                return 0
            streak, expires_at = entry
            if time.time() >= expires_at:
                del self._streaks[session_id]
                return 0
            return streak

    def set_clarification_streak(
        self,
        session_id: str,
        streak: int,
        ttl_seconds: int | None = None,
    ) -> None:
        ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl
        with self._lock:
            self._streaks[session_id] = (streak, time.time() + ttl)

    def get_last_query_context(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            entry = self._last_query.get(session_id)
            if entry is None:
                return None
            query, expires_at = entry
            if time.time() >= expires_at:
                del self._last_query[session_id]
                return None
            return dict(query)

    def set_last_query_context(
        self,
        session_id: str,
        query: dict[str, Any],
        ttl_seconds: int | None = None,
    ) -> None:
        ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl
        with self._lock:
            self._last_query[session_id] = (dict(query), time.time() + ttl)
