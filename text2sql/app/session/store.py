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

    # ---- Clarification-loop cap (xem app/server.py `_apply_clarification_cap`) ----
    # Đếm riêng, tách khỏi `messages` — history không mang metadata trạng
    # thái (QUERY/CLARIFICATION/...) theo từng lượt nên không thể suy ra
    # streak đáng tin cậy từ nội dung message. Cùng contract degrade-êm như
    # get()/save() ở trên.

    def get_clarification_streak(self, session_id: str) -> int:
        """Trả về 0 nếu session chưa tồn tại/đã hết hạn."""
        ...

    def set_clarification_streak(
        self,
        session_id: str,
        streak: int,
        ttl_seconds: int | None = None,
    ) -> None: ...

    # ---- Ngữ cảnh query gần nhất (xem app/nlu/validator.py `prior_query`) ----
    # Bug 2 (kế hoạch fix, Phase 2): multi-turn hay mất `timeDimensions` của
    # lượt trước khi LLM không lặp lại mốc thời gian ở lượt sau (dựa hoàn
    # toàn vào prompt Rule 8(a) — Phase 1 — vẫn không đủ ổn định qua benchmark
    # thực tế). Lưu lại `CubeQuery` (dạng dict, JSON-serializable) của lần
    # QUERY thành công gần nhất trong session, để validator có nguồn dự phòng
    # tất định thay vì chỉ trông chờ model tự nhớ. Cùng contract degrade-êm
    # như get()/save() ở trên — KHÔNG raise khi backend lỗi.

    def get_last_query_context(self, session_id: str) -> dict[str, Any] | None:
        """Trả về `None` nếu session chưa có query nào thành công/đã hết hạn."""
        ...

    def set_last_query_context(
        self,
        session_id: str,
        query: dict[str, Any],
        ttl_seconds: int | None = None,
    ) -> None: ...
