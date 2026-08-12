"""Interface chung cho session/conversation-history store.

Đổi backend (memory -> redis -> ...) = viết thêm 1 class implement Protocol
này + đăng ký vào `factory.py`, KHÔNG sửa code gọi (`server.py`) — cùng
nguyên tắc `LLMClient` (xem `app/llm/client.py`, `app/llm/factory.py`).

Contract bắt buộc: implementation KHÔNG ĐƯỢC raise khi backend không khả dụng
(Redis down, timeout...) — phải tự bắt lỗi, log (print, theo convention hiện có
của codebase — xem "[WARMUP]"/"[RAG Engine]"/"[Qdrant Notice]" trong
`app/server.py` và `app/retrieval/retriever.py`), và degrade: `get()` trả `[]`,
`save()`/`delete()` no-op. Session store là tính năng bổ trợ (multi-turn) — một
sự cố ở đây không được phép biến 1 request chat đang hoạt động tốt (sinh Cube
query + trả lời) thành lỗi 500.
"""

from __future__ import annotations

from typing import Any, Protocol


class SessionStore(Protocol):
    def get(self, session_id: str) -> list[dict[str, Any]]:
        """Trả về [] nếu session chưa tồn tại hoặc đã hết hạn."""
        ...

    def save(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
        ttl_seconds: int | None = None,
    ) -> None:
        """Ghi đè toàn bộ — `NLUResult.messages` luôn là bản đầy đủ đã cập nhật,
        không phải delta cần append."""
        ...

    def delete(self, session_id: str) -> None: ...
