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
REFUSE_TOOL_NAME = "refuse_request"

_FILTER_OPERATORS = [
    "equals", "notEquals", "contains", "notContains", "gt", "gte", "lt", "lte", "set", "notSet"
]

_REFUSAL_REASONS = [
    "out_of_domain",
    "external_data_unavailable",
    "hallucination_forecast_request",
]
# Cố ý KHÔNG có "other" — enum chỉ gồm 3 case rõ ràng nêu ở prompt.py Nhóm 1.
# Từng có "other" làm lối thoát mơ hồ: LLM dùng nó để từ chối cả những câu hỏi
# lẽ ra cần hỏi lại (Nhóm 2) chứ không phải từ chối hẳn — xem benchmark
# text2sql/tests/benchmark_results/. Không khớp chính xác 1 trong 3 lý do =>
# KHÔNG được gọi tool này, phải chuyển sang answer hoặc clarification.


def build_query_tool(catalog: Catalog, candidates: dict[str, list[str]] | None = None) -> dict[str, Any]:
    """Tool duy nhất: LLM điền form đúng shape Cube thay vì viết SQL."""
    time_dimension_names = catalog.time_dimension_names()

    m_desc = (
        "Các chỉ số cần tính, dạng <cube>.<measure>. Có thể để RỖNG nếu câu hỏi chỉ cần "
        "liệt kê/đếm số lượng theo dimensions (vd 'có bao nhiêu khu vực') mà không cần tính "
        "chỉ số nào — khi đó BẮT BUỘC dimensions phải có ít nhất 1 phần tử. Lưu ý: với câu hỏi "
        "'Tổng số X'/'bao nhiêu X' về MỘT ĐỐI TƯỢNG (không phải một chỉ số đo lường), hãy kiểm tra "
        "cả Dimension dạng số (type: number) của cube danh mục/tham chiếu trước khi tìm trong measures "
        "— dimension đó có thể tự nó chính là câu trả lời."
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


def build_refuse_tool() -> dict[str, Any]:
    """Tool để LLM chủ động từ chối yêu cầu — thay cho việc dựa vào trường
    `is_refusal` từ provider (không provider hiện tại nào populate trường
    này, xem app/llm/openai_compatible.py). Biến "từ chối" thành 1 quyết
    định tool-call có cấu trúc, test được, thay vì suy đoán từ text tự do.

    Cố ý KHÔNG liệt kê các trường hợp phá hoại dữ liệu/rò rỉ credential vào
    enum `reason` — những trường hợp đó nên được chặn bởi 1 lớp guardrail
    tất định độc lập với LLM (xem Phase 2 trong kế hoạch fix), không phải
    để LLM tự phán đoán.
    """
    return {
        "name": REFUSE_TOOL_NAME,
        "description": (
            "Từ chối yêu cầu — CHỈ dùng cho đúng 3 lý do liệt kê trong enum `reason`, không có lý do "
            "nào khác. KHÔNG dùng tool này khi chỉ cần hỏi lại để làm rõ 1 chi tiết còn thiếu (dùng "
            "text thường), và KHÔNG dùng chỉ vì không chắc 1 ngày/khoảng thời gian cụ thể có dữ liệu "
            "hay không — hãy cứ gọi query_metrics, hệ thống sẽ tự trả về rỗng nếu thật sự không có."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "enum": _REFUSAL_REASONS,
                    "description": "Loại lý do từ chối — xem mô tả tool.",
                },
                "message": {
                    "type": "string",
                    "description": (
                        "Câu trả lời tiếng Việt giải thích rõ vì sao từ chối. Nếu một phần câu hỏi "
                        "vẫn trả lời được bằng dữ liệu nội bộ hệ thống, BẮT BUỘC nêu rõ phần đó trong "
                        "message thay vì âm thầm bỏ qua."
                    ),
                },
            },
            "required": ["reason", "message"],
        },
    }


def build_tools(catalog: Catalog, candidates: dict[str, list[str]] | None = None) -> list[dict[str, Any]]:
    return [build_query_tool(catalog, candidates), build_refuse_tool()]
