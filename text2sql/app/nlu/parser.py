"""Phân loại `LLMResponse` (đã chuẩn hoá, không phụ thuộc provider) thành 3 tình huống.

- `is_refusal`     -> safety classifier từ chối.
- có tool call      -> model đã hiểu, chuyển sang validation.
- chỉ có text        -> model KHÔNG chắc, đó là câu hỏi làm rõ.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.llm.types import LLMResponse
from app.nlu.tool_schema import QUERY_TOOL_NAME, REFUSE_TOOL_NAME


@dataclass
class ParsedResponse:
    text: str
    tool_call_id: str | None = None
    tool_input: dict[str, Any] | None = None
    is_refusal: bool = False
    refusal_reason: str | None = None
    # Nội dung assistant nguyên bản, cần echo lại khi tiếp tục hội thoại.
    raw_assistant_content: Any = None

    @property
    def has_tool_call(self) -> bool:
        return self.tool_input is not None


def parse_response(response: LLMResponse) -> ParsedResponse:
    if response.is_refusal:
        return ParsedResponse(
            text=response.text or "Yêu cầu bị từ chối vì lý do an toàn.",
            is_refusal=True,
            refusal_reason=response.refusal_reason,
            raw_assistant_content=response.raw_assistant_content,
        )

    for call in response.tool_calls:
        if call.name == QUERY_TOOL_NAME:
            return ParsedResponse(
                text=response.text,
                tool_call_id=call.id,
                tool_input=call.input,
                raw_assistant_content=response.raw_assistant_content,
            )
        if call.name == REFUSE_TOOL_NAME:
            # LLM tự quyết định từ chối qua tool call có cấu trúc — xem
            # app/nlu/tool_schema.py::build_refuse_tool(). Tái dùng nhánh
            # REFUSAL sẵn có ở orchestrator.py (vốn chỉ chờ is_refusal=True)
            # thay vì cần sửa orchestrator.
            refuse_input = call.input or {}
            return ParsedResponse(
                text=refuse_input.get("message") or "Yêu cầu nằm ngoài phạm vi hệ thống hỗ trợ.",
                is_refusal=True,
                refusal_reason=refuse_input.get("reason"),
                raw_assistant_content=response.raw_assistant_content,
            )

    return ParsedResponse(text=response.text, raw_assistant_content=response.raw_assistant_content)
