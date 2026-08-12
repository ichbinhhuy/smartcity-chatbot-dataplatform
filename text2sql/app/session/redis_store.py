"""SessionStore backend dùng Redis — cho deploy thật (xem
`data-transform/docker-compose.yml`, service `web` set `SESSION_STORE_BACKEND=redis`).

Dùng `redis` sync client (KHÔNG dùng `redis.asyncio`) — khớp style
sync-httpx-everywhere hiện có trong repo (`app/query_engine/cube_client.py`,
`app/catalog/cube_meta.py`, `app/retrieval/retriever.py`); FastAPI route
handler ở đây cũng là `def` (sync), không phải `async def`.
"""

from __future__ import annotations

import json
from typing import Any

import redis

_KEY_PREFIX = "text2sql:session:"


class RedisSessionStore:
    def __init__(
        self,
        redis_url: str,
        ttl_seconds: int = 1800,
        client: "redis.Redis | None" = None,
    ) -> None:
        self._default_ttl = ttl_seconds
        # `redis.Redis.from_url()` chỉ dựng connection pool, KHÔNG mở TCP ngay
        # -> an toàn kể cả khi Redis chưa sẵn sàng lúc app khởi động. Lỗi thật
        # sự chỉ lộ ra ở lần gọi GET/SETEX/DEL đầu tiên (đã được try/except bắt
        # bên dưới). Ngoại lệ: nếu `redis_url` sai định dạng, `from_url()` tự
        # throw ngay ở đây — CỐ Ý không nuốt lỗi này (lỗi cấu hình/gõ sai, không
        # phải outage tạm thời; nuốt sẽ khiến hệ thống trông như "chạy được" mà
        # thực ra không bao giờ lưu được gì).
        self._client = client or redis.Redis.from_url(redis_url, decode_responses=True)

    @staticmethod
    def _key(session_id: str) -> str:
        return f"{_KEY_PREFIX}{session_id}"

    def get(self, session_id: str) -> list[dict[str, Any]]:
        try:
            raw = self._client.get(self._key(session_id))
        except redis.exceptions.RedisError as exc:
            print(f"[RedisSessionStore] get() thất bại: {exc} — fallback về history rỗng.")
            return []
        if raw is None:
            return []
        try:
            return json.loads(raw)
        except (TypeError, ValueError) as exc:
            print(f"[RedisSessionStore] payload hỏng cho session_id={session_id}: {exc} — fallback về history rỗng.")
            return []

    def save(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
        ttl_seconds: int | None = None,
    ) -> None:
        ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl
        try:
            self._client.setex(self._key(session_id), ttl, json.dumps(messages, ensure_ascii=False))
        except redis.exceptions.RedisError as exc:
            print(f"[RedisSessionStore] save() thất bại: {exc} — session_id={session_id} không được lưu.")

    def delete(self, session_id: str) -> None:
        try:
            self._client.delete(self._key(session_id))
        except redis.exceptions.RedisError as exc:
            print(f"[RedisSessionStore] delete() thất bại: {exc} — session_id={session_id}.")
