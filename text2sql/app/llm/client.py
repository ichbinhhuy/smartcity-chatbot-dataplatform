"""Interface chung cho LLM — phần còn lại của hệ thống (orchestrator, server) chỉ
biết tới `LLMClient`, không quan tâm provider cụ thể là gì.

Implementation có sẵn (tất cả ở `app/llm/`): `GroqLLMClient`, `OpenAILLMClient`,
`GeminiLLMClient`, `OpenRouterLLMClient` — provider được chọn qua biến môi trường
`LLM_PROVIDER` trong `.env`, xem `app/llm/factory.py`. Muốn thêm provider mới, viết
thêm một class thoả `LLMClient` và đăng ký vào `factory.py`.
"""

from __future__ import annotations

from typing import Any, Protocol

from app.llm.types import LLMResponse


class LLMClient(Protocol):
    def interpret_query(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> LLMResponse:
        """Lượt NLU: câu hỏi -> lời gọi tool `query_metrics` (hoặc text nếu mơ hồ).

        Phải cho phép model KHÔNG gọi tool (tương đương `tool_choice=auto`) —
        đây là cơ chế disambiguation chính của pipeline, xem app/nlu/parser.py.
        """
        ...

    def generate_answer(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
    ) -> LLMResponse:
        """Lượt NLG: kết quả truy vấn từ Cube -> câu trả lời tự nhiên."""
        ...
