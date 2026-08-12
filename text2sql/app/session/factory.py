"""Factory chọn SessionStore backend dựa theo biến môi trường
`SESSION_STORE_BACKEND` — xem `text2sql/.env` / `data-transform/docker-compose.yml`.

Mirror đúng shape `app/llm/factory.py`, với 1 khác biệt có chủ đích: ở đây
CACHE SINGLETON (`get_llm_client()` thì cố ý tạo mới mỗi lần). Lý do:
- `InMemorySessionStore` phải sống xuyên suốt process mới có tác dụng — tạo
  mới mỗi request sẽ âm thầm vô hiệu hoá toàn bộ tính năng.
- `redis.Redis` là 1 connection pool, được thiết kế để tái sử dụng, không phải
  tạo mới mỗi lần gọi.
"""

from __future__ import annotations

from app.config import Settings
from app.config import settings as default_settings
from app.session.memory_store import InMemorySessionStore
from app.session.redis_store import RedisSessionStore
from app.session.store import SessionStore

_STORES: dict[str, type] = {
    "memory": InMemorySessionStore,
    "redis": RedisSessionStore,
}

_store_singleton: SessionStore | None = None


def get_session_store(settings: Settings | None = None) -> SessionStore:
    global _store_singleton
    if _store_singleton is not None:
        return _store_singleton

    settings = settings or default_settings
    backend = (settings.session_store_backend or "memory").strip().lower()
    store_cls = _STORES.get(backend)
    if store_cls is None:
        supported = ", ".join(sorted(_STORES))
        raise ValueError(f"SESSION_STORE_BACKEND='{backend}' không hợp lệ. Các giá trị được hỗ trợ: {supported}.")

    if backend == "redis":
        _store_singleton = RedisSessionStore(redis_url=settings.redis_url, ttl_seconds=settings.session_ttl_seconds)
    else:
        _store_singleton = InMemorySessionStore(ttl_seconds=settings.session_ttl_seconds)
    return _store_singleton


def reset_session_store_cache() -> None:
    """Test-only: xoá cache singleton để test sau không kế thừa state của test trước."""
    global _store_singleton
    _store_singleton = None
