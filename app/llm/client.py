"""Interface chung cho LLM — provider cụ thể (Claude, v.v.) là quyết định sau.

Kiến trúc chỉ định nghĩa hợp đồng ở đây, KHÔNG có implementation cụ thể — xem
docs/02-cube-architecture.md ("LLM cụ thể chưa chốt"). Muốn chạy thật, viết một
class thoả `LLMClient` (ví dụ `app.llm.claude.ClaudeClient`) và inject vào
`NLUOrchestrator`.
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
