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


def build_query_tool(catalog: Catalog) -> dict[str, Any]:
    """Tool duy nhất: LLM điền form đúng shape Cube thay vì viết SQL."""
    measure_names = catalog.measure_names()
    dimension_names = catalog.dimension_names()
    time_dimension_names = catalog.time_dimension_names()

    return {
        "name": QUERY_TOOL_NAME,
        "description": (
            "Truy vấn dữ liệu Smart City qua Cube. "
            "Chỉ gọi tool này khi đã xác định được chắc chắn measure người dùng cần. "
            "measures/dimensions phải lấy từ danh sách enum — không được bịa tên mới. "
            "Mọi measure trong một lần gọi phải thuộc cùng một cube (cùng tiền tố trước dấu chấm)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "measures": {
                    "type": "array",
                    "description": "Các chỉ số cần tính, dạng <cube>.<measure>.",
                    "items": {"type": "string", "enum": measure_names},
                    "minItems": 1,
                },
                "dimensions": {
                    "type": "array",
                    "description": (
                        "Các chiều để nhóm kết quả (GROUP BY). "
                        "Bỏ trống nếu người dùng chỉ muốn một con số tổng."
                    ),
                    "items": {"type": "string", "enum": dimension_names},
                },
                "filters": {
                    "type": "array",
                    "description": "Điều kiện lọc. Không dùng cho lọc theo thời gian — hãy dùng timeDimensions.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "member": {"type": "string", "enum": dimension_names},
                            "operator": {"type": "string", "enum": _FILTER_OPERATORS},
                            "values": {
                                "type": "array",
                                "description": "Giá trị lọc, luôn là mảng (kể cả khi chỉ có một giá trị).",
                                "items": {"type": "string"},
                            },
                        },
                        "required": ["member", "operator", "values"],
                        "additionalProperties": False,
                    },
                },
                "timeDimensions": {
                    "type": "array",
                    "description": "Khoảng thời gian. Bỏ trống nếu câu hỏi không nhắc tới thời gian.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "dimension": {"type": "string", "enum": time_dimension_names},
                            "dateRange": {
                                "description": (
                                    "Chuỗi tương đối (vd 'last month') hoặc mảng [start, end] ISO date."
                                ),
                                "anyOf": [
                                    {"type": "string", "enum": RELATIVE_DATE_RANGES},
                                    {
                                        "type": "array",
                                        "items": {"type": "string"},
                                        "minItems": 2,
                                        "maxItems": 2,
                                    },
                                ],
                            },
                            "granularity": {"type": "string", "enum": TIME_GRAINS},
                        },
                        "required": ["dimension"],
                        "additionalProperties": False,
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
                        "additionalProperties": False,
                    },
                },
                "limit": {
                    "type": "integer",
                    "description": "Số dòng tối đa. Dùng cho câu hỏi dạng top-N.",
                    "minimum": 1,
                    "maximum": 1000,
                },
            },
            "required": ["measures"],
            "additionalProperties": False,
        },
    }


def build_tools(catalog: Catalog) -> list[dict[str, Any]]:
    return [build_query_tool(catalog)]
