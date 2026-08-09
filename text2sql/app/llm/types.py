"""Kiểu dữ liệu chuẩn hoá cho response của LLM — không phụ thuộc SDK của provider nào.

Khi một provider cụ thể được chọn (Claude, v.v.), implementation của
`app.llm.client.LLMClient` chịu trách nhiệm dịch response gốc của SDK đó sang
các kiểu này. Phần còn lại của hệ thống (parser, orchestrator) chỉ biết tới
`LLMResponse`, không biết provider là gì — xem docs/02-cube-architecture.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class LLMError(RuntimeError):
    """Provider implementation raise cái này khi gọi LLM thất bại (network, auth, rate limit...)."""


@dataclass
class LLMToolCall:
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class LLMResponse:
    text: str = ""
    tool_calls: list[LLMToolCall] = field(default_factory=list)
    is_refusal: bool = False
    refusal_reason: str | None = None
    # Nội dung gốc của lượt assistant, cần echo lại nguyên vẹn khi tiếp tục hội
    # thoại (một số provider yêu cầu gửi lại nguyên block, kể cả phần không phải
    # text/tool_use). Shape do provider tự quyết định, orchestrator chỉ echo lại.
    raw_assistant_content: Any = None
    usage: dict[str, int] = field(default_factory=dict)

    @property
    def has_tool_call(self) -> bool:
        return bool(self.tool_calls)
