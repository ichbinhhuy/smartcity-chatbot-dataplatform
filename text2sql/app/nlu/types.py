"""Kiểu dữ liệu của Cube query — hợp đồng giữa NLU và Cube Core.

Field đặt tên camelCase, KHỚP THẲNG với format JSON của Cube REST API (xem
docs/02-cube-architecture.md mục 2: "Cube query đúng shape Cube ngay từ tool
schema — không cần adapter dịch riêng"). Đây là lựa chọn có chủ ý để tránh
thêm một lớp chuyển đổi tên field — một nguồn lỗi tiềm ẩn.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field

CubeFilterOperator = Literal[
    "equals", "notEquals", "contains", "notContains", "gt", "gte", "lt", "lte", "set", "notSet"
]

TIME_GRAINS = ["second", "minute", "hour", "day", "week", "month", "quarter", "year"]

# Cụm thời gian tương đối Cube hiểu trực tiếp trong `dateRange` dạng chuỗi.
RELATIVE_DATE_RANGES = [
    "today",
    "yesterday",
    "this week",
    "last week",
    "this month",
    "last month",
    "this quarter",
    "last quarter",
    "this year",
    "last year",
    "last 7 days",
    "last 30 days",
]


class CubeFilter(BaseModel):
    member: str
    operator: CubeFilterOperator
    values: list[str] = Field(default_factory=list)


class CubeTimeDimension(BaseModel):
    dimension: str
    dateRange: str | list[str] | None = None
    granularity: str | None = None


class CubeOrderEntry(BaseModel):
    field: str
    direction: Literal["asc", "desc"] = "desc"


class CubeQuery(BaseModel):
    """Kết quả cuối cùng của bước NLU — gửi thẳng tới Cube REST API `/load`."""

    measures: list[str] = Field(min_length=1)
    dimensions: list[str] = Field(default_factory=list)
    filters: list[CubeFilter] = Field(default_factory=list)
    timeDimensions: list[CubeTimeDimension] = Field(default_factory=list)
    order: list[CubeOrderEntry] = Field(default_factory=list)
    limit: int | None = None

    def to_cube_payload(self) -> dict[str, Any]:
        """Serialize đúng format Cube REST API mong đợi (`order` là object, không phải mảng)."""
        payload = self.model_dump(exclude_none=True, exclude={"order"})
        if self.order:
            payload["order"] = {o.field: o.direction for o in self.order}
        return payload


class NLUStatus(str, Enum):
    QUERY = "query"  # hiểu được, đã có Cube query hợp lệ
    CLARIFICATION = "clarification"  # mơ hồ / ngoài phạm vi -> cần hỏi lại người dùng
    INVALID = "invalid"  # LLM gọi tool nhưng tham số không hợp lệ
    REFUSAL = "refusal"  # bị safety classifier từ chối
    ERROR = "error"  # lỗi hệ thống (gọi LLM thất bại...)


class NLUResult(BaseModel):
    status: NLUStatus
    query: CubeQuery | None = None
    # Câu hỏi làm rõ / thông báo lỗi để hiển thị cho người dùng.
    message: str | None = None
    errors: list[str] = Field(default_factory=list)
    # Tham số thô LLM trả về — giữ lại để log và debug prompt.
    raw_tool_input: dict[str, Any] | None = None
    # Lịch sử hội thoại đã cập nhật, dùng cho lượt tiếp theo (multi-turn).
    messages: list[dict[str, Any]] = Field(default_factory=list)
    # Gợi ý ngắn gọn (tối đa 3) rút từ RAG candidates khi status=CLARIFICATION —
    # dùng để render quick-reply chip ở FE (xem app/nlu/prompt.py:build_clarification_suggestions).
    suggestions: list[str] = Field(default_factory=list)
    usage: dict[str, int] = Field(default_factory=dict)
