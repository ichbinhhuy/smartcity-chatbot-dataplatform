"""Sinh tool schema (function-calling) từ Cube catalog.

Nguyên tắc: KHÔNG hard-code enum. Catalog tới từ Cube Meta API
(app/catalog/cube_meta.py) — thêm một measure mới trong cube schema là enum ở
đây tự cập nhật, không cần sửa code. Xem docs/02-cube-architecture.md mục 3.
"""

from __future__ import annotations

from typing import Any

from app.catalog.models import Catalog
from app.nlu.types import RELATIVE_DATE_RANGES, TIME_GRAINS

QUERY_TOOL_NAME = "query_metrics"

_FILTER_OPERATORS = [
    "equals", "notEquals", "contains", "notContains", "gt", "gte", "lt", "lte", "set", "notSet"
]


def build_query_tool(catalog: Catalog, candidates: dict[str, list[str]] | None = None) -> dict[str, Any]:
    """Tool duy nhất: LLM điền form đúng shape Cube thay vì viết SQL."""
    time_dimension_names = catalog.time_dimension_names()

    m_desc = (
        "Các chỉ số cần tính, dạng <cube>.<measure>. Có thể để RỖNG nếu câu hỏi chỉ cần "
        "liệt kê/đếm số lượng theo dimensions (vd 'có bao nhiêu khu vực') mà không cần tính "
        "chỉ số nào — khi đó BẮT BUỘC dimensions phải có ít nhất 1 phần tử."
    )
    d_desc = "Các chiều để nhóm kết quả."
    if candidates and candidates.get("measures"):
        m_desc += f" Gợi ý Top-K candidate: {', '.join(candidates['measures'])}"
    if candidates and candidates.get("dimensions"):
        d_desc += f" Gợi ý Top-K candidate: {', '.join(candidates['dimensions'])}"

    return {
        "name": QUERY_TOOL_NAME,
        "description": (
            "Truy vấn dữ liệu Smart City qua Cube. "
            "Chỉ gọi tool này khi đã xác định được chắc chắn measure hoặc dimension người dùng cần. "
            "measures/dimensions phải lấy từ danh sách enum — không được bịa tên mới. "
            "Mọi measure/dimension/filter trong một lần gọi phải thuộc cùng một cube (cùng tiền tố trước dấu chấm). "
            "Nếu câu hỏi chỉ cần liệt kê/đếm theo dimension (không cần tính chỉ số cụ thể), "
            "được phép để measures rỗng — nhưng phải có ít nhất measures hoặc dimensions không rỗng."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "measures": {
                    "type": "array",
                    "description": m_desc,
                    "items": {"type": "string"},
                },
                "dimensions": {
                    "type": "array",
                    "description": d_desc,
                    "items": {"type": "string"},
                },
                "filters": {
                    "type": "array",
                    "description": "Điều kiện lọc. Không dùng cho lọc theo thời gian — hãy dùng timeDimensions.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "member": {"type": "string"},
                            "operator": {"type": "string", "enum": _FILTER_OPERATORS},
                            "values": {
                                "type": "array",
                                "description": "Giá trị lọc, luôn là mảng.",
                                "items": {"type": "string"},
                            },
                        },
                        "required": ["member", "operator", "values"],
                    },
                },
                "timeDimensions": {
                    "type": "array",
                    "description": "Khoảng thời gian. Bỏ trống nếu câu hỏi không nhắc tới thời gian.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "dimension": {
                                "type": "string",
                                "description": f"Cột thời gian, một trong: {', '.join(time_dimension_names)}",
                            },
                            "dateRange": {
                                "description": (
                                    "Khoảng thời gian: dùng chuỗi tương đối như 'today', 'yesterday', "
                                    "'last 7 days', 'last 30 days', 'this month', 'last month'."
                                ),
                            },
                            "granularity": {
                                "type": "string",
                                "description": f"Độ phân giải thời gian. Một trong: {', '.join(TIME_GRAINS)}",
                            },
                        },
                        "required": ["dimension"],
                    },
                },
                "order": {
                    "type": "array",
                    "description": "Sắp xếp kết quả. field phải là một measure hoặc dimension đã chọn ở trên.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "field": {"type": "string"},
                            "direction": {"type": "string", "enum": ["asc", "desc"]},
                        },
                        "required": ["field", "direction"],
                    },
                },
                "limit": {
                    "type": "integer",
                    "description": "Số dòng tối đa. Dùng cho câu hỏi dạng top-N.",
                    "minimum": 1,
                    "maximum": 1000,
                },
            },
            # Không khai "required": ["measures"] nữa — ràng buộc thật là
            # "measures HOẶC dimensions phải có ít nhất 1", JSON Schema không
            # diễn đạt gọn được kiểu ràng buộc này qua `required` (cần
            # `anyOf`, phức tạp hoá schema cho nhiều provider function-
            # calling). Validator (`app/nlu/types.py::CubeQuery`) enforce
            # đúng ràng buộc này và trả lỗi rõ ràng qua repair loop nếu vi
            # phạm — xem docs/04-ambiguous-question-handling.md.
        },
    }


def build_tools(catalog: Catalog, candidates: dict[str, list[str]] | None = None) -> list[dict[str, Any]]:
    return [build_query_tool(catalog, candidates)]
